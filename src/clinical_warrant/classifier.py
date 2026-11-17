"""Prototype-based question classification with explicit unknown handling."""

from __future__ import annotations

import hashlib
import json
import math
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, Sequence

from clinical_warrant.catalog import PrototypeCategory, load_research_catalog
from clinical_warrant.contracts import ClassificationResult, QuestionType


MODEL_ID = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
# Pin an immutable Hub commit so cached vectors always belong to the loaded model.
MODEL_REVISION = "e8f8c211226b894fcb81acc59f3b34ba3efd5f42"
DEFAULT_THRESHOLD = 0.5
MODEL_MAX_SEQUENCE_LENGTH = 128
_CACHE_FORMAT_VERSION = 1


class ClassifierError(RuntimeError):
    """Raised when model inference or prototype-vector handling fails."""


class TextEncoder(Protocol):
    """Minimal encoder interface to keep classifier tests independent of ML libs."""

    model_id: str
    revision: str

    def encode(self, texts: Sequence[str]) -> Sequence[Sequence[float]]:
        """Return one dense vector per input string."""


class SentenceTransformerEncoder:
    """CPU adapter for the pinned multilingual Sentence Transformer model."""

    model_id = MODEL_ID
    revision = MODEL_REVISION

    def __init__(self, *, cache_dir: Path | None = None) -> None:
        try:
            from sentence_transformers import SentenceTransformer
        except Exception as error:
            raise ClassifierError(
                "could not initialize sentence-transformers; install the project "
                "model extra (and CPU PyTorch) before using the real encoder"
            ) from error

        hub_cache = cache_dir / "hub" if cache_dir is not None else None
        try:
            self._model = SentenceTransformer(
                self.model_id,
                revision=self.revision,
                device="cpu",
                backend="torch",
                cache_folder=str(hub_cache) if hub_cache is not None else None,
            )
            self._model.max_seq_length = MODEL_MAX_SEQUENCE_LENGTH
        except Exception as error:
            raise ClassifierError(
                f"could not load {self.model_id} at revision {self.revision} on CPU"
            ) from error

    def encode(self, texts: Sequence[str]) -> Sequence[Sequence[float]]:
        try:
            vectors = self._model.encode(
                list(texts),
                convert_to_numpy=True,
                normalize_embeddings=False,
                show_progress_bar=False,
            )
            return vectors.tolist() if hasattr(vectors, "tolist") else vectors
        except Exception as error:
            raise ClassifierError("sentence-transformers encoding failed") from error


@dataclass(frozen=True)
class _PrototypeVector:
    category: QuestionType
    vector: tuple[float, ...]


def default_cache_dir() -> Path:
    """Return an OS user cache directory outside the source tree."""
    configured = os.environ.get("CLINICAL_WARRANT_CACHE")
    if configured:
        return Path(configured).expanduser()
    if os.name == "nt":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    else:
        base = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache"))
    return base / "clinical-warrant-poc"


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
        raise ClassifierError(
            f"encoder returned {len(rows)} vectors; expected {expected_count}"
        )

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
        {
            "category": entry.category.value,
            "label_zh": entry.label_zh,
            "prototypes": list(entry.prototypes),
        }
        for entry in prototypes
    ]
    canonical = json.dumps(content, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class QuestionClassifier:
    """Classify a query by its highest cosine score against category prototypes."""

    def __init__(
        self,
        encoder: TextEncoder,
        *,
        threshold: float = DEFAULT_THRESHOLD,
        prototypes: Sequence[PrototypeCategory] | None = None,
        cache_dir: str | Path | None = None,
    ) -> None:
        self.threshold = _validate_threshold(threshold)
        self.encoder = encoder
        self.prototypes = tuple(
            prototypes if prototypes is not None else load_research_catalog().prototypes
        )
        if not self.prototypes:
            raise ValueError("at least one question prototype category is required")
        if any(not entry.prototypes for entry in self.prototypes):
            raise ValueError("every question category must have at least one prototype")
        categories = [entry.category for entry in self.prototypes]
        if len(categories) != len(set(categories)):
            raise ValueError("question prototype categories must be unique")
        if QuestionType.UNKNOWN in categories:
            raise ValueError("unknown is a result category, not a prototype category")
        if set(categories) != {
            QuestionType.RESULT_INTERPRETATION,
            QuestionType.WINDOW_PERIOD,
            QuestionType.EXPOSURE_RISK,
            QuestionType.PREVENTION_EDUCATION,
        }:
            raise ValueError("prototypes must cover all four known question categories")
        for name in ("model_id", "revision"):
            value = getattr(self.encoder, name, None)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"encoder must provide a non-empty {name}")
        self.cache_dir = (
            Path(cache_dir).expanduser() if cache_dir is not None else default_cache_dir()
        )
        self.cache_file = self.cache_dir / "prototype-vectors.json"
        self._identity = {
            "format_version": _CACHE_FORMAT_VERSION,
            "model_id": self.encoder.model_id,
            "model_revision": self.encoder.revision,
            "prototype_sha256": _prototype_fingerprint(self.prototypes),
        }
        self._prototype_vectors: tuple[_PrototypeVector, ...] | None = None

    @classmethod
    def from_pretrained(
        cls,
        *,
        threshold: float = DEFAULT_THRESHOLD,
        cache_dir: str | Path | None = None,
    ) -> "QuestionClassifier":
        threshold = _validate_threshold(threshold)
        explicit_cache = Path(cache_dir).expanduser() if cache_dir is not None else None
        resolved_cache = explicit_cache if explicit_cache is not None else default_cache_dir()
        encoder = SentenceTransformerEncoder(cache_dir=explicit_cache)
        return cls(encoder, threshold=threshold, cache_dir=resolved_cache)

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
        query_vectors = _validate_vectors(
            query_output,
            expected_count=1,
            expected_dimension=len(prototypes[0].vector),
        )
        query_vector = query_vectors[0]

        best_by_category: dict[QuestionType, float] = {}
        for prototype in prototypes:
            score = _cosine_similarity(query_vector, prototype.vector)
            previous = best_by_category.get(prototype.category)
            if previous is None or score > previous:
                best_by_category[prototype.category] = score
        best_category, best_score = max(
            best_by_category.items(), key=lambda item: item[1]
        )
        category = (
            QuestionType.UNKNOWN if best_score < self.threshold else best_category
        )
        return ClassificationResult(category=category, similarity=best_score)

    def _load_or_create_prototype_vectors(self) -> tuple[_PrototypeVector, ...]:
        if self._prototype_vectors is not None:
            return self._prototype_vectors
        cached = self._read_cache()
        if cached is not None:
            self._prototype_vectors = cached
            return cached

        texts: list[str] = []
        categories: list[QuestionType] = []
        for entry in self.prototypes:
            for text in entry.prototypes:
                texts.append(text)
                categories.append(entry.category)
        try:
            raw_vectors = self.encoder.encode(texts)
        except Exception as error:
            if isinstance(error, ClassifierError):
                raise
            raise ClassifierError("prototype encoding failed") from error
        vectors = _validate_vectors(raw_vectors, expected_count=len(texts))
        tagged = tuple(
            _PrototypeVector(category, vector)
            for category, vector in zip(categories, vectors)
        )
        self._write_cache(tagged)
        self._prototype_vectors = tagged
        return tagged

    def _read_cache(self) -> tuple[_PrototypeVector, ...] | None:
        try:
            payload = json.loads(self.cache_file.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return None
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            return None
        if not isinstance(payload, dict) or payload.get("identity") != self._identity:
            return None
        vectors = payload.get("vectors")
        if not isinstance(vectors, list) or len(vectors) != sum(
            len(entry.prototypes) for entry in self.prototypes
        ):
            return None
        try:
            parsed = _validate_vectors(vectors, expected_count=len(vectors))
        except ClassifierError:
            return None
        categories = [
            entry.category
            for entry in self.prototypes
            for _ in entry.prototypes
        ]
        return tuple(
            _PrototypeVector(category, vector)
            for category, vector in zip(categories, parsed)
        )

    def _write_cache(self, vectors: Sequence[_PrototypeVector]) -> None:
        payload = {
            "identity": self._identity,
            "vectors": [list(item.vector) for item in vectors],
        }
        try:
            self.cache_dir.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=self.cache_dir,
                prefix=".prototype-vectors-",
                suffix=".tmp",
                delete=False,
            ) as stream:
                temporary_path = Path(stream.name)
                json.dump(payload, stream, ensure_ascii=False, allow_nan=False)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary_path, self.cache_file)
        except OSError as error:
            try:
                temporary_path.unlink(missing_ok=True)
            except (OSError, UnboundLocalError):
                pass
            raise ClassifierError(f"could not write prototype cache: {self.cache_file}") from error


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
    # Floating point roundoff can push unit cosine a few ulps out of range.
    return max(-1.0, min(1.0, dot / (left_norm * right_norm)))
