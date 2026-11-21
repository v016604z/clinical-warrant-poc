"""CPU adapter for the pinned multilingual Sentence Transformer model."""

from __future__ import annotations

from pathlib import Path
from typing import Sequence

from clinical_warrant.modules.classification.domain.errors import ClassifierError


MODEL_ID = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
MODEL_REVISION = "e8f8c211226b894fcb81acc59f3b34ba3efd5f42"
MODEL_MAX_SEQUENCE_LENGTH = 128


class SentenceTransformerEncoder:
    """Load the pinned Sentence Transformer on CPU when explicitly requested."""

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
