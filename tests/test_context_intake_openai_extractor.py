"""Offline contract tests for the OpenAI-backed Context Intake extractor."""

import json
import os

import pytest

from clinical_warrant.modules.context_intake.application.extraction import (
    ExtractionError,
    ExtractionRequest,
    parse_extraction_response,
)
from clinical_warrant.modules.context_intake.application.intake import ContextIntakeService
from clinical_warrant.modules.context_intake.domain.category_registry import validate_category_registry
from clinical_warrant.modules.context_intake.domain.classification import IntakeClassificationResult
from clinical_warrant.modules.context_intake.infrastructure.openai_adapter import OpenAIAdapterError
from clinical_warrant.modules.context_intake.infrastructure.openai_extractor import (
    OpenAIExtractionError,
    OpenAIExtractor,
)


@pytest.fixture
def category():
    return validate_category_registry([{
        "category_id": "exposure",
        "category_name": "暴露情境",
        "fields": {
            "exposure_datetime": {"type": "string", "description": "暴露時間"},
            "sexual_contact": {"type": "boolean", "description": "是否涉及性接觸"},
            "test_count": {"type": "integer", "description": "檢驗次數"},
        },
    }]).get("exposure")


def model_output(**updates):
    payload = {
        "selected_fields": ["exposure_datetime", "sexual_contact", "test_count"],
        "extracted_attributes": {
            "exposure_datetime": "昨天",
            "sexual_contact": None,
            "test_count": None,
        },
        "evidence": {
            "exposure_datetime": "昨天",
            "sexual_contact": None,
            "test_count": None,
        },
        "selection_reason": "使用者提到暴露時間",
        "clarification_question": None,
        "clarification_field_key": None,
    }
    payload.update(updates)
    return json.dumps(payload, ensure_ascii=False)


class FakeAdapter:
    def __init__(self, output):
        self.output = output
        self.calls = []

    def create_structured_response(self, **kwargs):
        self.calls.append(kwargs)
        return self.output


def test_extractor_builds_category_scoped_request_and_returns_existing_extraction_contract(category):
    adapter = FakeAdapter(model_output())
    extractor = OpenAIExtractor(adapter=adapter)
    request = ExtractionRequest(
        message="我昨天有一次可能的暴露",
        category=category,
        known_attributes={"test_count": 1, "invented_attribute": "不應傳送"},
        context=("請問大約是哪一天？",),
    )

    raw = extractor.extract(request)
    result = parse_extraction_response(raw, category)

    assert result.extracted_attributes == {"exposure_datetime": "昨天"}
    assert "evidence" not in json.loads(raw)
    assert len(adapter.calls) == 1
    call = adapter.calls[0]
    assert call["schema_name"] == "context_intake_extraction"
    assert set(call["schema"]["properties"]) == {
        "selected_fields", "extracted_attributes", "evidence", "selection_reason",
        "clarification_question", "clarification_field_key",
    }
    assert set(call["schema"]["properties"]["extracted_attributes"]["properties"]) == set(category.fields)
    sent = json.loads(call["input"])
    assert sent["message"] == request.message
    assert sent["known_attributes"] == {"test_count": 1}
    assert sent["context"] == ["請問大約是哪一天？"]
    assert set(sent["category"]["fields"]) == set(category.fields)


@pytest.mark.parametrize(
    ("selected", "attributes", "evidence", "expected"),
    [
        (
            ["exposure_datetime"],
            {"exposure_datetime": "昨天", "sexual_contact": None, "test_count": None},
            {"exposure_datetime": "昨天", "sexual_contact": None, "test_count": None},
            {"exposure_datetime": "昨天"},
        ),
        (
            [],
            {"exposure_datetime": None, "sexual_contact": None, "test_count": None},
            {"exposure_datetime": None, "sexual_contact": None, "test_count": None},
            {},
        ),
    ],
)
def test_partial_or_empty_selection_strips_unselected_null_fields(
    category, selected, attributes, evidence, expected,
):
    extractor = OpenAIExtractor(adapter=FakeAdapter(model_output(
        selected_fields=selected,
        extracted_attributes=attributes,
        evidence=evidence,
    )))

    raw = extractor.extract(ExtractionRequest("我昨天有一次可能的暴露", category, {}))

    assert parse_extraction_response(raw, category).extracted_attributes == expected


@pytest.mark.parametrize(
    ("attributes", "evidence", "selected"),
    [
        ({"exposure_datetime": "上週"}, {"exposure_datetime": "上週"}, ["exposure_datetime"]),
        (
            {"exposure_datetime": "昨天", "sexual_contact": None, "test_count": None},
            {"exposure_datetime": None, "sexual_contact": None, "test_count": None},
            ["exposure_datetime"],
        ),
        ({"exposure_datetime": "昨天"}, {"exposure_datetime": "前天"}, ["exposure_datetime"]),
        ({"exposure_datetime": "昨天"}, {"exposure_datetime": "昨天"}, []),
        ({"invented_field": "昨天"}, {"invented_field": "昨天"}, ["invented_field"]),
    ],
)
def test_extractor_rejects_values_without_current_message_evidence(
    category, attributes, evidence, selected,
):
    output = model_output(
        selected_fields=selected,
        extracted_attributes=attributes,
        evidence=evidence,
    )
    extractor = OpenAIExtractor(adapter=FakeAdapter(output))
    request = ExtractionRequest(
        message="我昨天有一次可能的暴露",
        category=category,
        known_attributes={},
        context=("前天曾提到另一個問題",),
    )

    with pytest.raises(OpenAIExtractionError):
        extractor.extract(request)


@pytest.mark.parametrize(
    ("field_key", "value"),
    [("exposure_datetime", "上週"), ("exposure_route", "性行為")],
)
def test_string_value_must_match_its_in_message_evidence(field_key, value):
    category = validate_category_registry([{
        "category_id": "exposure",
        "category_name": "暴露情境",
        "fields": {field_key: {"type": "string", "description": "測試欄位"}},
    }]).get("exposure")
    output = json.dumps({
        "selected_fields": [field_key],
        "extracted_attributes": {field_key: value},
        "evidence": {field_key: "昨天"},
        "selection_reason": "測試",
        "clarification_question": None,
        "clarification_field_key": None,
    }, ensure_ascii=False)
    extractor = OpenAIExtractor(adapter=FakeAdapter(output))

    with pytest.raises(OpenAIExtractionError):
        extractor.extract(ExtractionRequest("我昨天有一次可能的暴露", category, {}))


@pytest.mark.parametrize(
    "output",
    [
        "{malformed json",
        model_output(evidence={"unexpected": "昨天"}),
        model_output(
            extracted_attributes={
                "exposure_datetime": None, "sexual_contact": None, "test_count": None,
            },
            evidence={
                "exposure_datetime": "昨天", "sexual_contact": None, "test_count": None,
            },
        ),
        '{"refusal":"I cannot provide this extraction."}',
    ],
)
def test_extractor_rejects_invalid_schema_output(output, category):
    extractor = OpenAIExtractor(adapter=FakeAdapter(output))

    with pytest.raises(OpenAIExtractionError):
        extractor.extract(ExtractionRequest("我昨天有一次可能的暴露", category, {}))


class FakeClassifier:
    def __init__(self, catalog_version):
        self.catalog_version = catalog_version

    def classify(self, _message):
        return IntakeClassificationResult(
            "exposure", 0.9, "window_period", 0.8, False,
            "fake/intake", "revision-test", self.catalog_version,
        )


class FailingAdapter:
    def create_structured_response(self, **_kwargs):
        raise OpenAIAdapterError("OpenAI Responses API request failed (TimeoutError).")


class SaveSpy:
    def __init__(self):
        self.saved = []

    def save_session(self, session):
        self.saved.append(session)

    def load_session(self, _session_id):
        return None

    def delete_case(self, _case_id, _participant_id):
        return False


def registry_for(category):
    return validate_category_registry([{
        "category_id": category.category_id,
        "category_name": category.category_name,
        "fields": {
            key: {"type": field.type, "description": field.description}
            for key, field in category.fields.items()
        },
    }])


def test_service_accepts_evidence_checked_extractor_output(category):
    registry = registry_for(category)
    repository = SaveSpy()
    adapter = FakeAdapter(model_output())
    service = ContextIntakeService(
        classifier=FakeClassifier(registry.version),
        extractor=OpenAIExtractor(adapter=adapter),
        registry=registry,
        id_factory=iter(f"id-{n}" for n in range(10)).__next__,
        repository=repository,
    )

    result = service.process_turn(
        participant_id="p1", session_id="s1", message="我昨天有一次可能的暴露", new_case=True,
    )

    case = result.session.cases[result.session.active_case_id]
    assert case.attributes["exposure_datetime"].value == "昨天"
    assert "sexual_contact" not in case.attributes
    assert "test_count" not in case.attributes
    assert result.extraction.extracted_attributes == {"exposure_datetime": "昨天"}
    assert repository.saved == [result.session]


def test_api_failure_does_not_persist_or_publish_partial_intake_state(category):
    registry = registry_for(category)
    repository = SaveSpy()
    service = ContextIntakeService(
        classifier=FakeClassifier(registry.version),
        extractor=OpenAIExtractor(adapter=FailingAdapter()),
        registry=registry,
        id_factory=iter(f"id-{n}" for n in range(10)).__next__,
        repository=repository,
    )

    with pytest.raises(OpenAIAdapterError):
        service.process_turn(
            participant_id="p1", session_id="s1", message="昨天有一次可能的暴露", new_case=True,
        )

    assert repository.saved == []
    assert service.sessions == {}


@pytest.mark.parametrize(
    ("invalid_output", "error_type"),
    [
        ("{malformed json", OpenAIExtractionError),
        (model_output(extra="unexpected"), OpenAIExtractionError),
        ('{"refusal":"I cannot provide this extraction."}', OpenAIExtractionError),
        (model_output(evidence={
            "exposure_datetime": "前天", "sexual_contact": None, "test_count": None,
        }), OpenAIExtractionError),
        (model_output(
            extracted_attributes={
                "exposure_datetime": "上週", "sexual_contact": None, "test_count": None,
            },
            evidence={
                "exposure_datetime": "昨天", "sexual_contact": None, "test_count": None,
            },
        ), OpenAIExtractionError),
        (model_output(extracted_attributes={
            "exposure_datetime": "昨天", "sexual_contact": None, "test_count": "3",
        }, evidence={
            "exposure_datetime": "昨天", "sexual_contact": None, "test_count": "3",
        }), ExtractionError),
        (model_output(clarification_question="請補充日期", clarification_field_key="invented_field"), ExtractionError),
    ],
)
def test_invalid_schema_refusal_or_evidence_does_not_persist(
    category, invalid_output, error_type,
):
    registry = registry_for(category)
    repository = SaveSpy()
    service = ContextIntakeService(
        classifier=FakeClassifier(registry.version),
        extractor=OpenAIExtractor(adapter=FakeAdapter(invalid_output)),
        registry=registry,
        id_factory=iter(f"id-{n}" for n in range(10)).__next__,
        repository=repository,
    )

    with pytest.raises(error_type):
        service.process_turn(
            participant_id="p1", session_id="s1", message="昨天有一次可能的暴露，檢驗 3 次", new_case=True,
        )

    assert repository.saved == []
    assert service.sessions == {}


@pytest.mark.skipif(
    os.environ.get("RUN_CONTEXT_INTAKE_OPENAI_SMOKE") != "1",
    reason="set RUN_CONTEXT_INTAKE_OPENAI_SMOKE=1 to make a billable OpenAI extraction request",
)
def test_real_openai_extractor_smoke():
    from dotenv import load_dotenv

    load_dotenv(override=False)
    if not os.environ.get("OPENAI_API_KEY"):
        pytest.fail("RUN_CONTEXT_INTAKE_OPENAI_SMOKE=1 requires OPENAI_API_KEY in process environment or .env")

    from clinical_warrant.modules.context_intake.infrastructure.category_registry import load_category_registry

    category = load_category_registry().get("personal_exposure_risk")
    extractor = OpenAIExtractor()
    raw = extractor.extract(ExtractionRequest(
        message="我昨天有一次可能的暴露",
        category=category,
        known_attributes={},
    ))
    result = parse_extraction_response(raw, category)

    assert "evidence" not in json.loads(raw)
    assert result.extracted_attributes.get("exposure_datetime") == "昨天"
    assert "exposure_route" not in result.extracted_attributes
    assert "sexual_activity_type" not in result.extracted_attributes
