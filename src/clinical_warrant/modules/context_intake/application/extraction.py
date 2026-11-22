"""Ports and strict output parsing for Context Intake extraction."""

from __future__ import annotations

import json
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Mapping, Protocol

from clinical_warrant.modules.context_intake.domain.category_registry import CategoryDefinition


JSONValue = str | int | float | bool | None


class ExtractionError(ValueError):
    """The extractor returned malformed or unsafe structured output."""


@dataclass(frozen=True)
class ExtractionRequest:
    message: str
    category: CategoryDefinition
    known_attributes: Mapping[str, JSONValue]
    context: tuple[str, ...] = ()


class Extractor(Protocol):
    """Replaceable port; adapters return the model's raw JSON text."""

    def extract(self, request: ExtractionRequest) -> str: ...


@dataclass(frozen=True)
class ExtractionResult:
    selected_fields: tuple[str, ...]
    extracted_attributes: Mapping[str, JSONValue]
    selection_reason: str
    clarification_question: str | None
    clarification_field_key: str | None


def parse_extraction_response(raw: str, category: CategoryDefinition) -> ExtractionResult:
    """Parse model output and retain only explicit, registered, typed values."""
    if not isinstance(raw, str) or raw.lstrip().startswith("```"):
        raise ExtractionError("extractor output must be plain JSON text")
    try:
        payload = json.loads(raw, object_pairs_hook=_unique_object, parse_constant=_reject_constant)
    except (json.JSONDecodeError, ValueError) as error:
        raise ExtractionError("extractor output is not strict JSON") from error
    expected = {
        "selected_fields", "extracted_attributes", "selection_reason",
        "clarification_question", "clarification_field_key",
    }
    if not isinstance(payload, dict) or set(payload) != expected:
        raise ExtractionError("extractor output must contain exactly the required fields")

    selected = payload["selected_fields"]
    if not isinstance(selected, list) or any(not isinstance(key, str) for key in selected):
        raise ExtractionError("selected_fields must be an array of field keys")
    if len(set(selected)) != len(selected):
        raise ExtractionError("selected_fields must not contain duplicates")
    if any(key not in category.fields for key in selected):
        raise ExtractionError("selected_fields contains a field outside the active Category")

    attributes = payload["extracted_attributes"]
    if not isinstance(attributes, dict):
        raise ExtractionError("extracted_attributes must be an object")
    known: dict[str, JSONValue] = {}
    for key, value in attributes.items():
        if key not in category.fields or key not in selected:
            raise ExtractionError("extracted_attributes contains an unselected or unregistered field")
        if value is None:
            continue
        field_type = category.fields[key].type
        if field_type == "string":
            if not isinstance(value, str):
                raise ExtractionError(f"{key} must be a string or null")
            if _is_unknown(value):
                continue
            known[key] = value
        elif field_type == "boolean":
            if type(value) is not bool:
                raise ExtractionError(f"{key} must be a boolean or null")
            known[key] = value
        elif field_type == "integer":
            if type(value) is not int:
                raise ExtractionError(f"{key} must be an integer or null")
            known[key] = value
        else:
            raise ExtractionError(f"{key} has an unsupported Registry type")

    reason = payload["selection_reason"]
    if not isinstance(reason, str) or not reason.strip():
        raise ExtractionError("selection_reason must be a non-empty string")
    question = payload["clarification_question"]
    if question is not None and (not isinstance(question, str) or not question.strip()):
        raise ExtractionError("clarification_question must be a non-empty string or null")
    field_key = payload["clarification_field_key"]
    if question is None:
        if field_key is not None:
            raise ExtractionError("clarification_field_key requires a clarification_question")
    elif not isinstance(field_key, str) or field_key not in selected or field_key not in category.fields:
        raise ExtractionError("clarification_field_key must be a selected field in the active Category")

    return ExtractionResult(
        tuple(selected), MappingProxyType(known), reason, question, field_key,
    )


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    raise ValueError(f"non-standard JSON constant: {value}")


def _is_unknown(value: str) -> bool:
    normalized = value.strip().casefold()
    return not normalized or normalized in {
        "不知道", "不清楚", "不確定", "未知", "無法回答", "未提供",
        "i don't know", "dont know", "unknown", "not sure", "n/a",
    }
