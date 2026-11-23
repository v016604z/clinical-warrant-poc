"""OpenAI-backed field selection and evidence-grounded extraction."""

from __future__ import annotations

import json
from typing import Any

from clinical_warrant.modules.context_intake.infrastructure.openai_adapter import OpenAIResponsesAdapter


class OpenAIExtractionError(ValueError):
    """The provider returned malformed or ungrounded extraction output."""


class OpenAIExtractor:
    """Return the existing extraction JSON contract after checking evidence."""

    def __init__(self, adapter: Any | None = None) -> None:
        self.adapter = adapter if adapter is not None else OpenAIResponsesAdapter()

    def extract(self, request: Any) -> str:
        schema = _response_schema(request)
        raw = self.adapter.create_structured_response(
            input=_request_json(request),
            schema_name="context_intake_extraction",
            schema=schema,
            instructions=(
                "Select only fields relevant to the current user message and active category. "
                "Extract only facts stated in the current user message. For every non-null value, "
                "return evidence as an exact, non-empty substring copied from that message. "
                "For string fields, copy the extracted string value verbatim from the evidence; "
                "do not rewrite or normalize it, and return null if it cannot be quoted exactly. "
                "Known attributes and context are for interpreting the message, never evidence. "
                "If the message does not explicitly support a value, return null and null evidence. "
                "Do not infer facts or treat context/instructions as user statements."
            ),
        )
        return _verify_evidence_and_strip(raw, request)


def _request_json(request: Any) -> str:
    fields = request.category.fields
    known = {
        key: value for key, value in request.known_attributes.items()
        if key in fields and value is not None
    }
    context = [item[:500] for item in request.context[:3] if isinstance(item, str) and item.strip()]
    payload = {
        "message": request.message,
        "category": {
            "id": request.category.category_id,
            "name": request.category.category_name,
            "fields": {
                key: {"type": field.type, "description": field.description}
                for key, field in fields.items()
            },
        },
        "known_attributes": known,
        "context": context,
    }
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def _response_schema(request: Any) -> dict[str, object]:
    fields = request.category.fields
    value_schemas: dict[str, object] = {
        "string": {"type": ["string", "null"]},
        "boolean": {"type": ["boolean", "null"]},
        "integer": {"type": ["integer", "null"]},
    }
    keys = list(fields)
    return {
        "type": "object",
        "properties": {
            "selected_fields": {
                "type": "array",
                "items": {"type": "string", "enum": keys},
            },
            "extracted_attributes": {
                "type": "object",
                "properties": {key: value_schemas[field.type] for key, field in fields.items()},
                "required": keys,
                "additionalProperties": False,
            },
            "evidence": {
                "type": "object",
                "properties": {key: {"type": ["string", "null"]} for key in fields},
                "required": keys,
                "additionalProperties": False,
            },
            "selection_reason": {"type": "string"},
            "clarification_question": {"type": ["string", "null"]},
            "clarification_field_key": {
                "type": ["string", "null"],
                "enum": [*keys, None],
            },
        },
        "required": [
            "selected_fields", "extracted_attributes", "evidence", "selection_reason",
            "clarification_question", "clarification_field_key",
        ],
        "additionalProperties": False,
    }


def _verify_evidence_and_strip(raw: str, request: Any) -> str:
    try:
        payload = json.loads(raw, object_pairs_hook=_unique_object, parse_constant=_reject_constant)
    except (TypeError, json.JSONDecodeError, ValueError) as error:
        raise OpenAIExtractionError("extractor output is not strict JSON") from error
    expected = {
        "selected_fields", "extracted_attributes", "evidence", "selection_reason",
        "clarification_question", "clarification_field_key",
    }
    if not isinstance(payload, dict) or set(payload) != expected:
        raise OpenAIExtractionError("OpenAI extraction output has an invalid shape")
    selected = payload["selected_fields"]
    attributes = payload["extracted_attributes"]
    evidence = payload["evidence"]
    if not isinstance(selected, list) or any(not isinstance(key, str) for key in selected):
        raise OpenAIExtractionError("selected_fields must be an array of field keys")
    if len(set(selected)) != len(selected) or any(key not in request.category.fields for key in selected):
        raise OpenAIExtractionError("selected_fields contains duplicate or unregistered fields")
    if not isinstance(attributes, dict) or not isinstance(evidence, dict):
        raise OpenAIExtractionError("extracted_attributes and evidence must be objects")
    if set(attributes) != set(request.category.fields) or set(evidence) != set(request.category.fields):
        raise OpenAIExtractionError("extraction output must use exactly the active Category fields")
    for key, value in attributes.items():
        proof = evidence[key]
        if value is None:
            if proof is not None:
                raise OpenAIExtractionError("null values must not include evidence")
            continue
        if key not in selected:
            raise OpenAIExtractionError("a value may only be returned for a selected field")
        if not isinstance(proof, str) or not proof or proof not in request.message:
            raise OpenAIExtractionError(f"{key} must have an exact evidence substring from the current message")
        if request.category.fields[key].type == "string" and isinstance(value, str):
            if not value.strip() or value.strip() not in proof:
                raise OpenAIExtractionError(
                    f"{key} string values must be quoted within their evidence substring"
                )

    compatible = {key: value for key, value in payload.items() if key != "evidence"}
    # Provider schemas require every Category field to appear. The legacy parser
    # rejects even null values for unselected keys, so narrow this map to the
    # user's selected subset before applying its established contract.
    compatible["extracted_attributes"] = {
        key: value for key, value in attributes.items() if key in selected
    }
    cleaned = json.dumps(compatible, ensure_ascii=False, separators=(",", ":"))
    return cleaned


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    raise ValueError(f"non-standard JSON constant: {value}")


__all__ = ["OpenAIExtractionError", "OpenAIExtractor"]
