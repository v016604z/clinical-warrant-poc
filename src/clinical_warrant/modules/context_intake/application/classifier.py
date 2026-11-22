"""Prototype classifier dedicated to the Context Intake 14-category catalog."""

from __future__ import annotations

import hashlib
import json
import math
from typing import Sequence

from clinical_warrant.modules.classification import ClassifierError, TextEncoder
from clinical_warrant.modules.context_intake.domain.category_registry import CategoryRegistry
from clinical_warrant.modules.context_intake.domain.classification import (
    IntakeClassificationResult,
    IntakePrototypeCategory,
)


class IntakeQuestionClassifier:
    def __init__(self, encoder: TextEncoder, *, registry: CategoryRegistry,
                 prototypes: Sequence[IntakePrototypeCategory], threshold: float, cache=None) -> None:
        self.threshold = _validate_threshold(threshold)
        self.encoder = encoder
        self.registry = registry
        self.prototypes = tuple(prototypes)
        _validate_prototypes(self.prototypes, registry)
        for name in ("model_id", "revision"):
            value = getattr(encoder, name, None)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"encoder must provide a non-empty {name}")
        self.model_id = encoder.model_id
        self.model_revision = encoder.revision
        self.cache = cache
        self._identity = {
            "namespace": "context-intake-14",
            "model_id": self.model_id,
            "model_revision": self.model_revision,
            "catalog_version": registry.version,
            "prototype_sha256": _prototype_fingerprint(self.prototypes),
        }
        self._prototype_sha256 = self._identity["prototype_sha256"]
        self._vectors: tuple[tuple[str, tuple[float, ...]], ...] | None = None

    @property
    def prototype_sha256(self) -> str:
        return self._prototype_sha256

    @property
    def catalog_version(self) -> str:
        return self.registry.version

    def classify(self, query: str) -> IntakeClassificationResult:
        if not isinstance(query, str) or not query.strip():
            raise ValueError("query must be a non-empty string")
        prototypes = self._load_or_create_vectors()
        try:
            output = self.encoder.encode([query])
        except Exception as error:
            if isinstance(error, ClassifierError):
                raise
            raise ClassifierError("query encoding failed") from error
        vector = _validate_vectors(output, expected_count=1,
                                   expected_dimension=len(prototypes[0][1]))[0]
        best_by_category: dict[str, float] = {}
        for category_id, prototype_vector in prototypes:
            score = _cosine_similarity(vector, prototype_vector)
            best_by_category[category_id] = max(best_by_category.get(category_id, -2.0), score)
        ranked = sorted(best_by_category.items(), key=lambda item: (-item[1], item[0]))
        (top1_id, top1_score), (top2_id, top2_score) = ranked[:2]
        return IntakeClassificationResult(
            top1_category_id=top1_id, top1_similarity=top1_score,
            top2_category_id=top2_id, top2_similarity=top2_score,
            is_unknown=top1_score < self.threshold, model_id=self.model_id,
            model_revision=self.model_revision, catalog_version=self.registry.version,
        )

    def _load_or_create_vectors(self) -> tuple[tuple[str, tuple[float, ...]], ...]:
        if self._vectors is not None:
            return self._vectors
        expected = sum(len(item.prototypes) for item in self.prototypes)
        cached = self.cache.read(self._identity) if self.cache is not None else None
        if cached is not None:
            try:
                vectors = _validate_vectors(cached, expected_count=expected)
            except ClassifierError:
                vectors = ()
            if vectors:
                self._vectors = _tag_vectors(self.prototypes, vectors)
                return self._vectors
        texts = [text for item in self.prototypes for text in item.prototypes]
        try:
            vectors = _validate_vectors(self.encoder.encode(texts), expected_count=len(texts))
        except Exception as error:
            if isinstance(error, ClassifierError):
                raise
            raise ClassifierError("prototype encoding failed") from error
        if self.cache is not None:
            self.cache.write(self._identity, vectors)
        self._vectors = _tag_vectors(self.prototypes, vectors)
        return self._vectors


def _validate_prototypes(prototypes: tuple[IntakePrototypeCategory, ...], registry: CategoryRegistry) -> None:
    if any(not isinstance(item, IntakePrototypeCategory) for item in prototypes):
        raise ValueError("prototypes must be intake prototype categories")
    ids = [item.category_id for item in prototypes]
    if (any(not isinstance(item, str) or not item.strip() for item in ids)
            or len(ids) < 2 or len(ids) != len(set(ids))
            or set(ids) != {item.category_id for item in registry.categories}):
        raise ValueError("prototype category IDs must exactly match the category registry")
    if any(not item.prototypes or any(not isinstance(text, str) or not text.strip() for text in item.prototypes)
           for item in prototypes):
        raise ValueError("every intake category must have at least one prototype")


def _prototype_fingerprint(prototypes: Sequence[IntakePrototypeCategory]) -> str:
    content = [{"category_id": item.category_id, "prototypes": list(item.prototypes)} for item in prototypes]
    canonical = json.dumps(content, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _validate_threshold(value: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not -1 <= value <= 1:
        raise ValueError("threshold must be a finite number between -1 and 1")
    return float(value)


def _validate_vectors(vectors, *, expected_count: int, expected_dimension: int | None = None):
    if isinstance(vectors, (str, bytes)):
        raise ClassifierError("encoder output must be a sequence of vectors")
    try:
        rows = list(vectors)
    except TypeError as error:
        raise ClassifierError("encoder output must be a sequence of vectors") from error
    if len(rows) != expected_count:
        raise ClassifierError(f"encoder returned {len(rows)} vectors; expected {expected_count}")
    result, dimension = [], expected_dimension
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
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
                raise ClassifierError(f"vector {row_index} contains an invalid numeric value")
            values.append(float(value))
        if not any(value != 0 for value in values):
            raise ClassifierError(f"vector {row_index} has zero norm")
        result.append(tuple(values))
    return tuple(result)


def _cosine_similarity(left: Sequence[float], right: Sequence[float]) -> float:
    if len(left) != len(right):
        raise ClassifierError("cannot compare vectors with different dimensions")
    left_scale, right_scale = max(map(abs, left)), max(map(abs, right))
    if left_scale == 0 or right_scale == 0:
        raise ClassifierError("cosine similarity requires non-zero vectors")
    left_scaled = [value / left_scale for value in left]
    right_scaled = [value / right_scale for value in right]
    dot = sum(a * b for a, b in zip(left_scaled, right_scaled))
    denom = math.sqrt(sum(x*x for x in left_scaled) * sum(x*x for x in right_scaled))
    return max(-1.0, min(1.0, dot / denom))


def _tag_vectors(prototypes: Sequence[IntakePrototypeCategory], vectors: Sequence[tuple[float, ...]]):
    ids = [item.category_id for item in prototypes for _ in item.prototypes]
    return tuple(zip(ids, vectors))
