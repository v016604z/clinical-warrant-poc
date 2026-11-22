"""Read JSONL records into provenance-preserving adapter input envelopes."""

from __future__ import annotations

import base64
from pathlib import Path
from typing import Any, Iterator

from ..domain.runs import SourceInput
from ..domain.contracts import KnowledgeBaseValidationError, parse_json_object


def read_inputs(path: str | Path, adapter: Any, *, raw_bytes: bytes | None = None) -> Iterator[SourceInput]:
    """Yield one SourceInput per physical line; malformed rows remain diagnosable."""
    source = Path(path)
    rows = raw_bytes.splitlines(keepends=True) if raw_bytes is not None else source.open("rb")
    try:
        for line_number, raw in enumerate(rows, 1):
            locator = str(source)
            try:
                text = raw.decode("utf-8")
            except UnicodeDecodeError as error:
                yield SourceInput(locator, line_number,
                                  {"raw_bytes_base64": base64.b64encode(raw).decode("ascii")}, None,
                                  f"invalid UTF-8: {error}", "input_decode_error")
                continue
            try:
                record = parse_json_object(text)
            except KnowledgeBaseValidationError as error:
                yield SourceInput(locator, line_number, text.rstrip("\r\n"), None,
                                  str(error), "invalid_json")
                continue
            try:
                source_record = adapter.adapt(record)
            except KnowledgeBaseValidationError as error:
                code = ("missing_source_locator" if _missing_source_locator(record, adapter.to_config())
                        and ("source_url" in str(error) or "source_locator" in str(error))
                        else "input_adaptation_error")
                yield SourceInput(locator, line_number, record, None,
                                  str(error), code)
                continue
            yield SourceInput(locator, line_number, record, source_record)
    finally:
        if raw_bytes is None:
            rows.close()


__all__ = ["read_inputs"]


def _missing_source_locator(record: dict[str, Any], config: dict[str, Any]) -> bool:
    mapping = config["mapping"]
    field = mapping["source_url"] if config["type"] == "generic_jsonl" else mapping["source_locator"]
    value = record.get(field)
    return not isinstance(value, str) or not value.strip()
