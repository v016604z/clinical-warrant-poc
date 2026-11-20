"""Backward-compatible classifier API assembled from classification ports."""

from __future__ import annotations

from pathlib import Path
from typing import Sequence

from clinical_warrant.infrastructure.catalog import load_research_catalog
from clinical_warrant.modules.classification.application.classifier import (
    DEFAULT_THRESHOLD,
    QuestionClassifier as _QuestionClassifier,
    TextEncoder,
    _cosine_similarity,
    _prototype_fingerprint,
    _validate_vectors,
)
from clinical_warrant.modules.classification.domain.errors import ClassifierError
from clinical_warrant.modules.classification.infrastructure.model_encoder import (
    MODEL_ID,
    MODEL_MAX_SEQUENCE_LENGTH,
    MODEL_REVISION,
    SentenceTransformerEncoder,
)
from clinical_warrant.modules.classification.infrastructure.prototype_cache import (
    FilePrototypeVectorCache,
    default_cache_dir,
)
from clinical_warrant.shared.domain.catalog import PrototypeCategory


def _validate_threshold(value: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("threshold must be a finite number between -1 and 1")
    import math

    if not math.isfinite(value) or not -1.0 <= value <= 1.0:
        raise ValueError("threshold must be a finite number between -1 and 1")
    return float(value)


class QuestionClassifier(_QuestionClassifier):
    """Compatibility wrapper retaining the original constructor and factory."""

    def __init__(
        self,
        encoder: TextEncoder,
        *,
        threshold: float = DEFAULT_THRESHOLD,
        prototypes: Sequence[PrototypeCategory] | None = None,
        cache_dir: str | Path | None = None,
    ) -> None:
        self.cache_store = FilePrototypeVectorCache(cache_dir)
        self.cache_dir = self.cache_store.cache_dir
        self.cache_file = self.cache_store.cache_file
        active_prototypes = prototypes if prototypes is not None else load_research_catalog().prototypes
        super().__init__(
            encoder,
            threshold=threshold,
            prototypes=active_prototypes,
            cache=self.cache_store,
        )

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


__all__ = [
    "ClassifierError", "DEFAULT_THRESHOLD", "MODEL_ID", "MODEL_MAX_SEQUENCE_LENGTH",
    "MODEL_REVISION", "QuestionClassifier", "SentenceTransformerEncoder", "TextEncoder",
    "default_cache_dir", "_cosine_similarity", "_validate_threshold", "_validate_vectors",
]
