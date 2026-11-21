"""Atomic filesystem publisher for evaluation report artifacts."""

from __future__ import annotations

import json
from pathlib import Path
import shutil
import tempfile
from typing import Any


class ReportPublishError(RuntimeError):
    """Raised when an evaluation report cannot be published atomically."""


def publish_report(report: dict[str, Any], output_dir: str | Path) -> dict[str, Any]:
    destination = Path(output_dir).expanduser()
    temporary: Path | None = None
    try:
        destination.mkdir(parents=True, exist_ok=True)
        temporary = Path(tempfile.mkdtemp(prefix=".evaluation-", dir=destination))
        (temporary / "summary.json").write_text(
            json.dumps(report["summary"], ensure_ascii=False, indent=2, allow_nan=False) + "\n",
            encoding="utf-8",
        )
        (temporary / "predictions.jsonl").write_text(
            _jsonl(report["predictions"]), encoding="utf-8"
        )
        (temporary / "errors.jsonl").write_text(
            _jsonl(report["errors"]), encoding="utf-8"
        )
        final = destination / f"run-{report['run_id']}"
        temporary.replace(final)
        temporary = None
    except (OSError, TypeError, ValueError) as error:
        if temporary is not None:
            _remove_own_temporary_directory(temporary, destination)
        raise ReportPublishError(f"could not publish evaluation reports: {error}") from error
    return {"run_id": report["run_id"], "run_dir": str(final), "summary": report["summary"]}


def _remove_own_temporary_directory(temporary: Path, destination: Path) -> None:
    try:
        resolved_temporary = temporary.resolve()
        resolved_destination = destination.resolve()
    except OSError:
        return
    if resolved_temporary.parent == resolved_destination and resolved_temporary.name.startswith(
        ".evaluation-"
    ):
        shutil.rmtree(resolved_temporary, ignore_errors=True)


def _jsonl(records: list[dict[str, Any]]) -> str:
    return "".join(
        json.dumps(record, ensure_ascii=False, allow_nan=False, separators=(",", ":")) + "\n"
        for record in records
    )
