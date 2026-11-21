import json
from copy import deepcopy

import pytest

from clinical_warrant.shared.domain.contracts import (
    CheckKind,
    CheckResult,
    CheckStatus,
    ClassificationResult,
    ContractError,
    Decision,
    DecisionInput,
    DecisionResult,
    QuestionType,
    ReasonCode,
)


def test_envelope_json_round_trip_preserves_case_and_explicit_scope() -> None:
    request = DecisionInput(
        query="請辨識這個虛構案例的問題類型。",
        case={"scenario_id": "synthetic-01", "optional": ["sample"]},
        requested_scope="internal_review",
    )

    assert DecisionInput.from_json(request.to_json()) == request


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"query": "問題", "case": {}},
        {"query": " ", "case": {}, "requested_scope": "education"},
        {"query": 12, "case": {}, "requested_scope": "education"},
        {"query": "問題", "case": [], "requested_scope": "education"},
        {"query": "問題", "case": {}, "requested_scope": True},
        {"query": "問題", "case": {}, "requested_scope": "education", "extra": 1},
        {"query": "問題", "case": {"bad": float("nan")}, "requested_scope": "education"},
    ],
)
def test_invalid_envelope_is_rejected(payload: dict[str, object]) -> None:
    with pytest.raises(ContractError):
        DecisionInput.from_dict(payload)


def test_case_missing_rule_fields_and_non_education_scope_are_valid_input() -> None:
    request = DecisionInput.from_dict(
        {"query": "問題", "case": {"scenario_id": "synthetic-02"}, "requested_scope": "diagnosis"}
    )

    assert request.case == {"scenario_id": "synthetic-02"}
    assert request.requested_scope == "diagnosis"


def test_invalid_json_is_a_contract_error() -> None:
    with pytest.raises(ContractError, match="valid JSON"):
        DecisionInput.from_json('{"query":')


@pytest.mark.parametrize("similarity", [True, -1.01, 1.01, float("nan")])
def test_classifier_similarity_rejects_invalid_scores(similarity: object) -> None:
    with pytest.raises(ContractError):
        ClassificationResult(QuestionType.UNKNOWN, similarity)  # type: ignore[arg-type]


@pytest.mark.parametrize("similarity", [-1.0, -0.42, 0.0, 1.0])
def test_classifier_similarity_accepts_cosine_range(similarity: float) -> None:
    assert ClassificationResult(QuestionType.UNKNOWN, similarity).similarity == similarity


def test_decision_result_json_round_trip_preserves_enums_and_check_semantics() -> None:
    result = DecisionResult(
        classification=ClassificationResult(QuestionType.WINDOW_PERIOD, 0.73),
        rule_id="toy-window-period-v1",
        checks=(
            CheckResult(CheckKind.CASE_SUFFICIENCY, CheckStatus.UNDETERMINED),
            CheckResult(CheckKind.RULE_APPLICABILITY, CheckStatus.SKIPPED),
            CheckResult(CheckKind.RESPONSE_SCOPE, CheckStatus.PASS),
        ),
        missing_fields=("toy_rule_flag",),
        reason_codes=(ReasonCode.CASE_INFO_MISSING,),
        decision=Decision.NEED_MORE_INFO,
    )

    serialized = result.to_json()
    restored = DecisionResult.from_json(serialized)
    assert restored == result
    assert json.loads(serialized)["decision"] == "need_more_info"


def test_result_parser_rejects_boolean_similarity() -> None:
    payload = {
        "classification": {"category": "unknown", "similarity": True},
        "rule_id": None,
        "checks": [],
        "missing_fields": [],
        "reason_codes": ["unknown_intent"],
        "decision": "restrict",
    }

    with pytest.raises(ContractError, match="similarity"):
        DecisionResult.from_dict(payload)


def test_result_requires_each_check_kind_exactly_once() -> None:
    base = DecisionResult(
        classification=ClassificationResult(QuestionType.UNKNOWN, None),
        rule_id=None,
        checks=tuple(
            CheckResult(kind, CheckStatus.SKIPPED) for kind in CheckKind
        ),
        missing_fields=(),
        reason_codes=(ReasonCode.UNKNOWN_INTENT,),
        decision=Decision.RESTRICT,
    )
    with pytest.raises(ContractError, match="exactly once"):
        DecisionResult(
            classification=base.classification,
            rule_id=None,
            checks=base.checks[:2],
            missing_fields=(),
            reason_codes=base.reason_codes,
            decision=base.decision,
        )
    with pytest.raises(ContractError, match="exactly once"):
        DecisionResult(
            classification=base.classification,
            rule_id=None,
            checks=(base.checks[0], base.checks[0], base.checks[2]),
            missing_fields=(),
            reason_codes=base.reason_codes,
            decision=base.decision,
        )


@pytest.mark.parametrize(
    ("section", "key", "invalid_value"),
    [
        ("classification", "category", "not_a_question_type"),
        ("root", "decision", "not_a_decision"),
        ("checks[0]", "status", "not_a_check_status"),
    ],
)
def test_result_parser_rejects_unknown_enum_values(
    section: str, key: str, invalid_value: str
) -> None:
    valid = DecisionResult(
        classification=ClassificationResult(QuestionType.UNKNOWN, None),
        rule_id=None,
        checks=tuple(CheckResult(kind, CheckStatus.SKIPPED) for kind in CheckKind),
        missing_fields=(),
        reason_codes=(ReasonCode.UNKNOWN_INTENT,),
        decision=Decision.RESTRICT,
    ).to_dict()
    payload = deepcopy(valid)
    if section == "root":
        target = payload
    elif section == "checks[0]":
        target = payload["checks"][0]
    else:
        target = payload[section]
    target[key] = invalid_value

    with pytest.raises(ContractError):
        DecisionResult.from_dict(payload)
