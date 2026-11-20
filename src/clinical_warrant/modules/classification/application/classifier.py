"""Prototype-based classification use case with explicit unknown handling."""

from __future__ import annotations

import hashlib
import json
import math
from typing import Any, Protocol, Sequence

from clinical_warrant.modules.classification.domain.errors import ClassifierError
from clinical_warrant.shared.domain.catalog import PrototypeCategory
from clinical_warrant.shared.domain.contracts import ClassificationResult, QuestionType


DEFAULT_THRESHOLD = 0.5
_CACHE_FORMAT_VERSION = 1


class TextEncoder(Protocol):
    """Model port used by the classifier application."""

    model_id: str
    revision: str

    def encode(self, texts: Sequence[str]) -> Sequence[Sequence[float]]: ...


class PrototypeVectorCache(Protocol):
    """Persistence port for derived prototype vectors."""

    def read(self, identity: dict[str, Any]) -> Sequence[Sequence[float]] | None: ...

    def write(self, identity: dict[str, Any], vectors: Sequence[Sequence[float]]) -> None: ...


class QuestionClassifier:
    """Classify a query by its highest cosine score against category prototypes."""

    def __init__(
        self,
        encoder: TextEncoder,
        *,
        prototypes: Sequence[PrototypeCategory],
        threshold: float = DEFAULT_THRESHOLD,
        cache: PrototypeVectorCache | None = None,
    ) -> None:
        self.threshold = _validate_threshold(threshold)
        self.encoder = encoder
        self.prototypes = tuple(prototypes)
        _validate_prototypes(self.prototypes)
        for name in ("model_id", "revision"):
            value = getattr(self.encoder, name, None)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"encoder must provide a non-empty {name}")
        self.model_id = self.encoder.model_id
        self.revision = self.encoder.revision
        self.cache = cache
        self._identity = {
            "format_version": _CACHE_FORMAT_VERSION,
            "model_id": self.model_id,
            "model_revision": self.revision,
            "prototype_sha256": _prototype_fingerprint(self.prototypes),
        }
        self._prototype_vectors: tuple[tuple[QuestionType, tuple[float, ...]], ...] | None = None

    def classify(self, query: str) -> ClassificationResult:
        if not isinstance(query, str) or not query.strip():
            raise ValueError("query must be a non-empty string")
        prototypes = self._load_or_create_prototype_vectors()
        try:
            query_output = self.encoder.encode([query])
        except Exception as error:
            if isinstance(error, ClassifierError):
                raise
            raise ClassifierError("query encoding failed") from error
        query_vector = _validate_vectors(
            query_output,
            expected_count=1,
            expected_dimension=len(prototypes[0][1]),
        )[0]

        best_by_category: dict[QuestionType, float] = {}
        for category, vector in prototypes:
            score = _cosine_similarity(query_vector, vector)
            previous = best_by_category.get(category)
            if previous is None or score > previous:
                best_by_category[category] = score
        best_category, best_score = max(best_by_category.items(), key=lambda item: item[1])
        category = QuestionType.UNKNOWN if best_score < self.threshold else best_category
        return ClassificationResult(category=category, similarity=best_score)

    def _load_or_create_prototype_vectors(
        self,
    ) -> tuple[tuple[QuestionType, tuple[float, ...]], ...]:
        if self._prototype_vectors is not None:
            return self._prototype_vectors
        expected = sum(len(item.prototypes) for item in self.prototypes)
        cached = self.cache.read(self._identity) if self.cache is not None else None
        if cached is not None:
            try:
                vectors = _validate_vectors(cached, expected_count=expected)
            except ClassifierError:
                vectors = ()
            if vectors:
                self._prototype_vectors = _tag_vectors(self.prototypes, vectors)
                return self._prototype_vectors

        texts = [text for item in self.prototypes for text in item.prototypes]
        try:
            raw_vectors = self.encoder.encode(texts)
        except Exception as error:
            if isinstance(error, ClassifierError):
                raise
            raise ClassifierError("prototype encoding failed") from error
        vectors = _validate_vectors(raw_vectors, expected_count=len(texts))
        if self.cache is not None:
            self.cache.write(self._identity, vectors)
        self._prototype_vectors = _tag_vectors(self.prototypes, vectors)
        return self._prototype_vectors


def _validate_prototypes(prototypes: tuple[PrototypeCategory, ...]) -> None:
    if not prototypes:
        raise ValueError("at least one question prototype category is required")
    if any(not entry.prototypes for entry in prototypes):
        raise ValueError("every question category must have at least one prototype")
    categories = [entry.category for entry in prototypes]
    if len(categories) != len(set(categories)):
        raise ValueError("question prototype categories must be unique")
    if QuestionType.UNKNOWN in categories:
        raise ValueError("unknown is a result category, not a prototype category")
    expected = {
        QuestionType.RESULT_INTERPRETATION,
        QuestionType.WINDOW_PERIOD,
        QuestionType.EXPOSURE_RISK,
        QuestionType.PREVENTION_EDUCATION,
    }
    if set(categories) != expected:
        raise ValueError("prototypes must cover all four known question categories")


def _validate_threshold(value: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("threshold must be a finite number between -1 and 1")
    if not math.isfinite(value) or not -1.0 <= value <= 1.0:
        raise ValueError("threshold must be a finite number between -1 and 1")
    return float(value)


def _validate_vectors(
    vectors: Sequence[Sequence[float]],
    *,
    expected_count: int,
    expected_dimension: int | None = None,
) -> tuple[tuple[float, ...], ...]:
    if isinstance(vectors, (str, bytes)):
        raise ClassifierError("encoder output must be a sequence of vectors")
    try:
        rows = list(vectors)
    except TypeError as error:
        raise ClassifierError("encoder output must be a sequence of vectors") from error
    if len(rows) != expected_count:
        raise ClassifierError(f"encoder returned {len(rows)} vectors; expected {expected_count}")
    result = []
    dimension = expected_dimension
    for row_index, raw_row in enumerate(rows):
        if isinstance(raw_row, (str, bytes)):
            raise ClassifierError(f"vector {row_index} is not a numeric sequence")
        try:
            row = list(raw_row)
        except TypeError as error:
            raise ClassifierError(f"vector {row_index} is not a numeric sequence") from error
        if not row:
            raise ClassifierError(f"vector {row_index} has no dimensions")
        if dimension is None:
            dimension = len(row)
        if len(row) != dimension:
            raise ClassifierError("encoder vectors have inconsistent dimensions")
        values = []
        for value in row:
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ClassifierError(f"vector {row_index} contains a non-numeric value")
            number = float(value)
            if not math.isfinite(number):
                raise ClassifierError(f"vector {row_index} contains a non-finite value")
            values.append(number)
        if not any(value != 0.0 for value in values):
            raise ClassifierError(f"vector {row_index} has zero norm")
        result.append(tuple(values))
    return tuple(result)


def _prototype_fingerprint(prototypes: Sequence[PrototypeCategory]) -> str:
    content = [
        {"category": entry.category.value, "label_zh": entry.label_zh, "prototypes": list(entry.prototypes)}
        for entry in prototypes
    ]
    canonical = json.dumps(content, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _tag_vectors(
    prototypes: Sequence[PrototypeCategory], vectors: Sequence[tuple[float, ...]]
) -> tuple[tuple[QuestionType, tuple[float, ...]], ...]:
    categories = [entry.category for entry in prototypes for _ in entry.prototypes]
    return tuple(zip(categories, vectors))


def _cosine_similarity(left: Sequence[float], right: Sequence[float]) -> float:
    if len(left) != len(right):
        raise ClassifierError("cannot compare vectors with different dimensions")
    left_scale = max(abs(value) for value in left)
    right_scale = max(abs(value) for value in right)
    if left_scale == 0.0 or right_scale == 0.0:
        raise ClassifierError("cosine similarity requires non-zero vectors")
    scaled_left = [value / left_scale for value in left]
    scaled_right = [value / right_scale for value in right]
    dot = sum(a * b for a, b in zip(scaled_left, scaled_right))
    left_norm = math.sqrt(sum(value * value for value in scaled_left))
    right_norm = math.sqrt(sum(value * value for value in scaled_right))
    if left_norm == 0.0 or right_norm == 0.0:
        raise ClassifierError("cosine similarity requires non-zero vectors")
    return max(-1.0, min(1.0, dot / (left_norm * right_norm)))
