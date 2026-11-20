"""Pure tri-state decision policy over validated inputs and rules."""

from __future__ import annotations

from clinical_warrant.shared.domain.catalog import RuleDefinition
from clinical_warrant.shared.domain.contracts import (
    CheckKind,
    CheckResult,
    CheckStatus,
    ClassificationResult,
    Decision,
    DecisionInput,
    DecisionResult,
    QuestionType,
    ReasonCode,
)


class WarrantError(RuntimeError):
    """Raised when the classifier output or rule catalog cannot be used."""


def decide(
    request: DecisionInput,
    classification: ClassificationResult,
    rules_by_type: dict[QuestionType, RuleDefinition],
) -> DecisionResult:
    if not isinstance(classification, ClassificationResult):
        raise WarrantError("classifier must return a ClassificationResult")
    if classification.category is QuestionType.UNKNOWN:
        return _result(
            classification,
            None,
            (CheckResult(CheckKind.CASE_SUFFICIENCY, CheckStatus.SKIPPED),
             CheckResult(CheckKind.RULE_APPLICABILITY, CheckStatus.SKIPPED),
             CheckResult(CheckKind.RESPONSE_SCOPE, CheckStatus.SKIPPED)),
            Decision.RESTRICT,
            ReasonCode.UNKNOWN_INTENT,
        )

    rule = rules_by_type.get(classification.category)
    if rule is None:
        raise WarrantError(f"no toy rule is defined for {classification.category.value}")
    if request.requested_scope != "education":
        return _result(
            classification,
            rule.rule_id,
            (CheckResult(CheckKind.CASE_SUFFICIENCY, CheckStatus.SKIPPED),
             CheckResult(CheckKind.RULE_APPLICABILITY, CheckStatus.SKIPPED),
             CheckResult(CheckKind.RESPONSE_SCOPE, CheckStatus.FAIL, ReasonCode.SCOPE_MISMATCH)),
            Decision.RESTRICT,
            ReasonCode.SCOPE_MISMATCH,
        )

    missing_fields = tuple(
        field for field in rule.required_case_fields if _is_missing(request.case, field)
    )
    if _is_missing(request.case, rule.applicability_field):
        applicability = CheckResult(CheckKind.RULE_APPLICABILITY, CheckStatus.UNDETERMINED)
    elif request.case[rule.applicability_field] == rule.applicability_value:
        applicability = CheckResult(CheckKind.RULE_APPLICABILITY, CheckStatus.PASS)
    else:
        applicability = CheckResult(
            CheckKind.RULE_APPLICABILITY, CheckStatus.FAIL, ReasonCode.RULE_NOT_APPLICABLE
        )
    response_scope = CheckResult(CheckKind.RESPONSE_SCOPE, CheckStatus.PASS)

    if applicability.status is CheckStatus.FAIL:
        decision = Decision.RESTRICT
        reason_code = ReasonCode.RULE_NOT_APPLICABLE
        reported_missing_fields: tuple[str, ...] = ()
        case_sufficiency = CheckResult(CheckKind.CASE_SUFFICIENCY, CheckStatus.SKIPPED)
    elif missing_fields:
        decision = Decision.NEED_MORE_INFO
        reason_code = ReasonCode.CASE_INFO_MISSING
        reported_missing_fields = missing_fields
        case_sufficiency = CheckResult(
            CheckKind.CASE_SUFFICIENCY, CheckStatus.FAIL, ReasonCode.CASE_INFO_MISSING
        )
    else:
        if applicability.status is not CheckStatus.PASS:
            raise WarrantError("cannot allow education when rule applicability is not confirmed")
        decision = Decision.ALLOW_EDUCATION
        reason_code = ReasonCode.ALL_CHECKS_PASSED
        reported_missing_fields = ()
        case_sufficiency = CheckResult(CheckKind.CASE_SUFFICIENCY, CheckStatus.PASS)
    return _result(
        classification,
        rule.rule_id,
        (case_sufficiency, applicability, response_scope),
        decision,
        reason_code,
        reported_missing_fields,
    )


def validate_rules(rules: tuple[RuleDefinition, ...]) -> dict[QuestionType, RuleDefinition]:
    expected_categories = {
        QuestionType.RESULT_INTERPRETATION,
        QuestionType.WINDOW_PERIOD,
        QuestionType.EXPOSURE_RISK,
        QuestionType.PREVENTION_EDUCATION,
    }
    by_type: dict[QuestionType, RuleDefinition] = {}
    seen_ids: set[str] = set()
    for rule in rules:
        if not isinstance(rule, RuleDefinition):
            raise WarrantError("rules must contain RuleDefinition values")
        if not isinstance(rule.rule_id, str) or not rule.rule_id.strip():
            raise WarrantError("rule_id must be a non-empty string")
        if rule.rule_id in seen_ids:
            raise WarrantError(f"duplicate rule id: {rule.rule_id}")
        seen_ids.add(rule.rule_id)
        if not isinstance(rule.question_type, QuestionType) or rule.question_type not in expected_categories:
            raise WarrantError("each rule must map to a known question category")
        if rule.question_type in by_type:
            raise WarrantError(f"duplicate rule category: {rule.question_type.value}")
        fields = rule.required_case_fields
        if (not isinstance(fields, tuple) or not fields
                or any(not isinstance(field, str) or not field.strip() for field in fields)
                or len(set(fields)) != len(fields)):
            raise WarrantError(f"rule {rule.rule_id} has invalid required_case_fields")
        if not isinstance(rule.applicability_field, str) or rule.applicability_field not in fields:
            raise WarrantError(f"rule {rule.rule_id} applicability field must be required")
        if not isinstance(rule.applicability_value, str) or not rule.applicability_value.strip():
            raise WarrantError(f"rule {rule.rule_id} has invalid applicability value")
        by_type[rule.question_type] = rule
    if set(by_type) != expected_categories:
        raise WarrantError("rules must cover all four known question categories")
    return by_type


def _is_missing(case: dict, field: str) -> bool:
    if field not in case:
        return True
    value = case[field]
    return value is None or (isinstance(value, str) and not value.strip())


def _result(
    classification: ClassificationResult,
    rule_id: str | None,
    checks: tuple[CheckResult, ...],
    decision: Decision,
    reason_code: ReasonCode,
    missing_fields: tuple[str, ...] = (),
) -> DecisionResult:
    return DecisionResult(
        classification=classification,
        rule_id=rule_id,
        checks=checks,
        missing_fields=missing_fields,
        reason_codes=(reason_code,),
        decision=decision,
    )
