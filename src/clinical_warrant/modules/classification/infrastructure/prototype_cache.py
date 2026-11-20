"""Atomic filesystem cache for prototype embeddings."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any, Sequence

from clinical_warrant.modules.classification.domain.errors import ClassifierError


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


class FilePrototypeVectorCache:
    """Persist vectors with model/prototype identity and atomic replacement."""

    def __init__(self, cache_dir: str | Path | None = None) -> None:
        self.cache_dir = Path(cache_dir).expanduser() if cache_dir is not None else default_cache_dir()
        self.cache_file = self.cache_dir / "prototype-vectors.json"

    def read(self, identity: dict[str, Any]) -> Sequence[Sequence[float]] | None:
        try:
            payload = json.loads(self.cache_file.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return None
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            return None
        if not isinstance(payload, dict) or payload.get("identity") != identity:
            return None
        vectors = payload.get("vectors")
        return vectors if isinstance(vectors, list) else None

    def write(self, identity: dict[str, Any], vectors: Sequence[Sequence[float]]) -> None:
        payload = {"identity": identity, "vectors": [list(item) for item in vectors]}
        temporary_path: Path | None = None
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
            if temporary_path is not None:
                try:
                    temporary_path.unlink(missing_ok=True)
                except OSError:
                    pass
            raise ClassifierError(f"could not write prototype cache: {self.cache_file}") from error
