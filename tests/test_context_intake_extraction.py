import json

import pytest

from clinical_warrant.modules.context_intake.application.extraction import (
    ExtractionError,
    ExtractionRequest,
    Extractor,
    parse_extraction_response,
)
from clinical_warrant.modules.context_intake.domain.category_registry import validate_category_registry


@pytest.fixture
def category():
    return validate_category_registry([{
        "category_id": "test_category",
        "category_name": "測試類別",
        "fields": {
            "note": {"type": "string", "description": "文字"},
            "present": {"type": "boolean", "description": "是否"},
            "count": {"type": "integer", "description": "數量"},
        },
    }]).get("test_category")


def response(**updates):
    payload = {
        "selected_fields": ["note", "present", "count"],
        "extracted_attributes": {"note": "已說明", "present": False, "count": 0},
        "selection_reason": "與本輪內容相關",
        "clarification_question": None,
        "clarification_field_key": None,
    }
    payload.update(updates)
    return json.dumps(payload, ensure_ascii=False)


def response_without(key):
    payload = json.loads(response())
    del payload[key]
    return json.dumps(payload)


class FakeExtractor:
    def __init__(self, raw):
        self.raw = raw

    def extract(self, request):
        self.request = request
        return self.raw


def test_extractor_protocol_uses_raw_json_port(category):
    request = ExtractionRequest("訊息", category, {}, ("必要上下文",))
    fake: Extractor = FakeExtractor(response())

    result = parse_extraction_response(fake.extract(request), request.category)

    assert fake.request is request
    assert result.extracted_attributes == {"note": "已說明", "present": False, "count": 0}
    assert result.selected_fields == ("note", "present", "count")


@pytest.mark.parametrize("raw", [
    "```json\n{}\n```",
    '{"selected_fields": [], "selected_fields": [], "extracted_attributes": {}, "selection_reason": "", "clarification_question": null, "clarification_field_key": null}',
    response(extra="no"),
    response_without("clarification_field_key"),
    response(selection_reason="   "),
    "{\"selected_fields\": [], \"extracted_attributes\": {}, \"selection_reason\": NaN, \"clarification_question\": null, \"clarification_field_key\": null}",
])
def test_parser_rejects_non_strict_or_wrong_shape_output(category, raw):
    with pytest.raises(ExtractionError):
        parse_extraction_response(raw, category)


@pytest.mark.parametrize("payload", [
    {"selected_fields": ["invented"]},
    {"selected_fields": ["note", "note"]},
    {"extracted_attributes": {"invented": "x"}},
    {"extracted_attributes": {"present": True}, "selected_fields": ["note"]},
    {"extracted_attributes": {"present": 0}},
    {"extracted_attributes": {"count": True}},
    {"extracted_attributes": {"count": 1.0}},
    {"extracted_attributes": {"note": 4}},
    {"clarification_question": "請補充", "clarification_field_key": "invented"},
    {"clarification_question": "請補充", "clarification_field_key": "present", "selected_fields": ["note"]},
    {"clarification_field_key": "note"},
])
def test_parser_rejects_unregistered_unselected_or_wrongly_typed_data(category, payload):
    with pytest.raises(ExtractionError):
        parse_extraction_response(response(**payload), category)


@pytest.mark.parametrize("value", [None, "", "   ", "不知道", "不清楚", "不確定", "未知", "未提供", "I don't know", "not sure"])
def test_unknown_string_and_null_are_omitted_not_clear_commands(category, value):
    result = parse_extraction_response(response(
        selected_fields=["note"], extracted_attributes={"note": value},
    ), category)

    assert result.extracted_attributes == {}


def test_clarification_key_is_tied_to_selected_field(category):
    result = parse_extraction_response(response(
        selected_fields=["note"], extracted_attributes={},
        clarification_question="請補充文字", clarification_field_key="note",
    ), category)

    assert result.clarification_field_key == "note"


def test_response_attributes_are_immutable(category):
    result = parse_extraction_response(response(), category)

    with pytest.raises(TypeError):
        result.extracted_attributes["note"] = "覆寫"
