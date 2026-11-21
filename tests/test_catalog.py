import pytest

from clinical_warrant.shared.domain.catalog import (
    CatalogError,
    validate_mock_cases,
    validate_prototypes,
    validate_rules,
)
from clinical_warrant.infrastructure.catalog import load_research_catalog
from clinical_warrant.shared.domain.contracts import QuestionType


def test_packaged_catalog_loads_outside_repository_directory(monkeypatch, tmp_path) -> None:
    monkeypatch.chdir(tmp_path)

    catalog = load_research_catalog()

    assert {item.category for item in catalog.prototypes} == {
        QuestionType.RESULT_INTERPRETATION,
        QuestionType.WINDOW_PERIOD,
        QuestionType.EXPOSURE_RISK,
        QuestionType.PREVENTION_EDUCATION,
    }
    assert all(item.prototypes for item in catalog.prototypes)
    assert len({rule.rule_id for rule in catalog.rules}) == len(catalog.rules) == 4
    assert all(case.rule_id in {rule.rule_id for rule in catalog.rules} for case in catalog.mock_cases)


def test_mock_fixtures_cover_complete_missing_and_nonmatching_symbolic_cases() -> None:
    catalog = load_research_catalog()
    states = {case.data_state for case in catalog.mock_cases}

    assert "complete" in states
    assert "missing_required_field" in states
    assert any(case.request.requested_scope == "education" for case in catalog.mock_cases)
    assert any(case.request.case.get("toy_rule_flag") == "not_applicable" for case in catalog.mock_cases)


def test_empty_prototype_list_is_rejected() -> None:
    catalog = load_research_catalog()
    raw = {
        "purpose": "test",
        "categories": [
            {"category": item.category.value, "label_zh": item.label_zh, "prototypes": list(item.prototypes)}
            for item in catalog.prototypes
        ],
    }
    raw["categories"][0]["prototypes"] = []

    with pytest.raises(CatalogError, match="must not be empty"):
        validate_prototypes(raw)


def test_duplicate_rule_id_is_rejected() -> None:
    catalog = load_research_catalog()
    raw = {
        "purpose": "test",
        "rules": [
            {
                "rule_id": rule.rule_id,
                "question_type": rule.question_type.value,
                "required_case_fields": list(rule.required_case_fields),
                "applies_when": {"field": rule.applicability_field, "equals": rule.applicability_value},
            }
            for rule in catalog.rules
        ],
    }
    raw["rules"][1]["rule_id"] = raw["rules"][0]["rule_id"]

    with pytest.raises(CatalogError, match="duplicate rule id"):
        validate_rules(raw, catalog.prototypes)


def test_mock_case_unknown_rule_reference_is_rejected() -> None:
    catalog = load_research_catalog()
    raw = {
        "purpose": "test",
        "cases": [
            {
                "case_id": case.case_id,
                "query": case.request.query,
                "question_type": case.question_type.value,
                "requested_scope": case.request.requested_scope,
                "rule_id": case.rule_id,
                "data_state": case.data_state,
                "case": dict(case.request.case),
            }
            for case in catalog.mock_cases
        ],
    }
    raw["cases"][0]["rule_id"] = "missing-rule"

    with pytest.raises(CatalogError, match="unknown rule"):
        validate_mock_cases(raw, catalog.rules)


def test_mock_case_category_must_match_referenced_rule() -> None:
    catalog = load_research_catalog()
    raw = {
        "purpose": "test",
        "cases": [
            {
                "case_id": case.case_id,
                "query": case.request.query,
                "question_type": case.question_type.value,
                "requested_scope": case.request.requested_scope,
                "rule_id": case.rule_id,
                "data_state": case.data_state,
                "case": dict(case.request.case),
            }
            for case in catalog.mock_cases
        ],
    }
    raw["cases"][0]["question_type"] = QuestionType.WINDOW_PERIOD.value

    with pytest.raises(CatalogError, match="does not match rule"):
        validate_mock_cases(raw, catalog.rules)


def test_complete_mock_case_must_include_rule_fields() -> None:
    catalog = load_research_catalog()
    raw = {
        "purpose": "test",
        "cases": [
            {
                "case_id": case.case_id,
                "query": case.request.query,
                "question_type": case.question_type.value,
                "requested_scope": case.request.requested_scope,
                "rule_id": case.rule_id,
                "data_state": case.data_state,
                "case": dict(case.request.case),
            }
            for case in catalog.mock_cases
        ],
    }
    raw["cases"][0]["case"].pop("toy_rule_flag")

    with pytest.raises(CatalogError, match="marked complete but misses"):
        validate_mock_cases(raw, catalog.rules)
