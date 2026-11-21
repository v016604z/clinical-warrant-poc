from dataclasses import replace

import pytest

from clinical_warrant.bootstrap.composition import build_warrant_engine
from clinical_warrant.infrastructure.catalog import load_research_catalog
from clinical_warrant.shared.domain.contracts import (
    CheckKind,
    CheckStatus,
    ClassificationResult,
    Decision,
    DecisionInput,
    QuestionType,
    ReasonCode,
)
from clinical_warrant.modules.decision import WarrantEngine, WarrantError


class FixedClassifier:
    def __init__(self, category: QuestionType, similarity: float | None = 0.8) -> None:
        self.result = ClassificationResult(category, similarity)

    def classify(self, query: str) -> ClassificationResult:
        return self.result


def test_bootstrap_injects_packaged_rules_into_decision_engine() -> None:
    engine = build_warrant_engine(
        classifier_factory=lambda *, threshold: FixedClassifier(
            QuestionType.RESULT_INTERPRETATION
        )
    )

    assert len(engine.rules_by_type) == 4
    assert engine.decide(
        DecisionInput(
            "test query",
            {"scenario_id": "synthetic", "toy_rule_flag": "applicable"},
            "education",
        )
    ).decision is Decision.ALLOW_EDUCATION


def decide(
    category: QuestionType,
    case: dict,
    requested_scope: str = "education",
):
    request = DecisionInput("模擬問題", case, requested_scope)
    catalog = load_research_catalog()
    return WarrantEngine(FixedClassifier(category), rules=catalog.rules).decide(request)


@pytest.mark.parametrize(
    "category",
    [
        QuestionType.RESULT_INTERPRETATION,
        QuestionType.WINDOW_PERIOD,
        QuestionType.EXPOSURE_RISK,
        QuestionType.PREVENTION_EDUCATION,
    ],
)
def test_each_known_category_allows_when_toy_case_is_complete(category) -> None:
    result = decide(
        category, {"scenario_id": "synthetic-01", "toy_rule_flag": "applicable"}
    )

    assert result.classification.category is category
    assert result.rule_id
    assert result.decision is Decision.ALLOW_EDUCATION
    assert result.reason_codes == (ReasonCode.ALL_CHECKS_PASSED,)
    assert {check.kind: check.status for check in result.checks} == {
        CheckKind.CASE_SUFFICIENCY: CheckStatus.PASS,
        CheckKind.RULE_APPLICABILITY: CheckStatus.PASS,
        CheckKind.RESPONSE_SCOPE: CheckStatus.PASS,
    }


@pytest.mark.parametrize(
    ("case", "expected_missing"),
    [
        ({"scenario_id": "synthetic-02"}, ("toy_rule_flag",)),
        ({"scenario_id": None, "toy_rule_flag": "applicable"}, ("scenario_id",)),
        ({"scenario_id": "synthetic-03", "toy_rule_flag": "  "}, ("toy_rule_flag",)),
        ({}, ("scenario_id", "toy_rule_flag")),
    ],
)
def test_missing_rule_fields_request_more_information(case, expected_missing) -> None:
    result = decide(QuestionType.WINDOW_PERIOD, case)
    statuses = {check.kind: check.status for check in result.checks}

    assert result.decision is Decision.NEED_MORE_INFO
    assert result.reason_codes == (ReasonCode.CASE_INFO_MISSING,)
    assert result.missing_fields == expected_missing
    assert statuses == {
        CheckKind.CASE_SUFFICIENCY: CheckStatus.FAIL,
        CheckKind.RULE_APPLICABILITY: CheckStatus.UNDETERMINED
        if "toy_rule_flag" in expected_missing
        else CheckStatus.PASS,
        CheckKind.RESPONSE_SCOPE: CheckStatus.PASS,
    }


@pytest.mark.parametrize("present_value", [False, 0])
def test_falsey_case_values_are_present_not_missing(present_value) -> None:
    result = decide(
        QuestionType.EXPOSURE_RISK,
        {"scenario_id": present_value, "toy_rule_flag": "applicable"},
    )

    assert result.decision is Decision.ALLOW_EDUCATION
    assert result.missing_fields == ()


def test_unknown_intent_has_priority_and_skips_all_checks() -> None:
    result = decide(QuestionType.UNKNOWN, {}, requested_scope="diagnosis")

    assert result.decision is Decision.RESTRICT
    assert result.rule_id is None
    assert result.reason_codes == (ReasonCode.UNKNOWN_INTENT,)
    assert result.missing_fields == ()
    assert {check.kind: check.status for check in result.checks} == {
        kind: CheckStatus.SKIPPED for kind in CheckKind
    }


def test_explicit_scope_mismatch_precedes_missing_case_fields() -> None:
    result = decide(QuestionType.RESULT_INTERPRETATION, {}, requested_scope="diagnosis")

    assert result.decision is Decision.RESTRICT
    assert result.reason_codes == (ReasonCode.SCOPE_MISMATCH,)
    assert result.missing_fields == ()
    assert {check.kind: check.status for check in result.checks} == {
        CheckKind.CASE_SUFFICIENCY: CheckStatus.SKIPPED,
        CheckKind.RULE_APPLICABILITY: CheckStatus.SKIPPED,
        CheckKind.RESPONSE_SCOPE: CheckStatus.FAIL,
    }


def test_known_non_applicable_rule_precedes_unrelated_missing_fields() -> None:
    result = decide(
        QuestionType.PREVENTION_EDUCATION,
        {"toy_rule_flag": "not_applicable"},
    )

    assert result.decision is Decision.RESTRICT
    assert result.reason_codes == (ReasonCode.RULE_NOT_APPLICABLE,)
    assert result.missing_fields == ()
    assert {check.kind: check.status for check in result.checks} == {
        CheckKind.CASE_SUFFICIENCY: CheckStatus.SKIPPED,
        CheckKind.RULE_APPLICABILITY: CheckStatus.FAIL,
        CheckKind.RESPONSE_SCOPE: CheckStatus.PASS,
    }


def test_missing_applicability_marker_is_undetermined_not_a_failure() -> None:
    result = decide(QuestionType.WINDOW_PERIOD, {"scenario_id": "synthetic-04"})

    assert result.decision is Decision.NEED_MORE_INFO
    assert result.reason_codes == (ReasonCode.CASE_INFO_MISSING,)
    assert result.missing_fields == ("toy_rule_flag",)
    assert {check.kind: check.status for check in result.checks} == {
        CheckKind.CASE_SUFFICIENCY: CheckStatus.FAIL,
        CheckKind.RULE_APPLICABILITY: CheckStatus.UNDETERMINED,
        CheckKind.RESPONSE_SCOPE: CheckStatus.PASS,
    }


@pytest.mark.parametrize(
    "invalid_kind", ["unrequired_marker", "duplicate_id", "duplicate_category"]
)
def test_engine_rejects_malformed_injected_rules(invalid_kind) -> None:
    rules = list(load_research_catalog().rules)
    if invalid_kind == "unrequired_marker":
        rules[0] = replace(rules[0], applicability_field="unlisted_marker")
    elif invalid_kind == "duplicate_id":
        rules[1] = replace(rules[1], rule_id=rules[0].rule_id)
    else:
        rules[1] = replace(rules[1], question_type=rules[0].question_type)

    with pytest.raises(WarrantError):
        WarrantEngine(FixedClassifier(QuestionType.RESULT_INTERPRETATION), rules=tuple(rules))
