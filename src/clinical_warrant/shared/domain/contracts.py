"""Typed JSON contracts shared by the later PoC stages.

These data structures validate shape and primitive types only. They do not
classify questions, evaluate rules, or make clinical decisions.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from enum import Enum
from typing import Any, Mapping


class ContractError(ValueError):
    """Raised when JSON does not match a public data contract."""


class QuestionType(str, Enum):
    RESULT_INTERPRETATION = "result_interpretation"
    WINDOW_PERIOD = "window_period"
    EXPOSURE_RISK = "exposure_risk"
    PREVENTION_EDUCATION = "prevention_education"
    UNKNOWN = "unknown"


class Decision(str, Enum):
    ALLOW_EDUCATION = "allow_education"
    NEED_MORE_INFO = "need_more_info"
    RESTRICT = "restrict"


class CheckKind(str, Enum):
    CASE_SUFFICIENCY = "case_sufficiency"
    RULE_APPLICABILITY = "rule_applicability"
    RESPONSE_SCOPE = "response_scope"


class CheckStatus(str, Enum):
    PASS = "pass"
    FAIL = "fail"
    UNDETERMINED = "undetermined"
    SKIPPED = "skipped"


class ReasonCode(str, Enum):
    UNKNOWN_INTENT = "unknown_intent"
    SCOPE_MISMATCH = "scope_mismatch"
    RULE_NOT_APPLICABLE = "rule_not_applicable"
    CASE_INFO_MISSING = "case_info_missing"
    ALL_CHECKS_PASSED = "all_checks_passed"


def _expect_object(value: Any, expected: set[str], name: str) -> Mapping[str, Any]:
    if not isinstance(value, dict):
        raise ContractError(f"{name} must be a JSON object")
    missing = expected - value.keys()
    extra = value.keys() - expected
    if missing:
        raise ContractError(f"{name} is missing fields: {', '.join(sorted(missing))}")
    if extra:
        raise ContractError(f"{name} has unexpected fields: {', '.join(sorted(extra))}")
    return value


def _expect_text(value: Any, name: str, *, allow_empty: bool = False) -> str:
    if not isinstance(value, str):
        raise ContractError(f"{name} must be a string")
    if not allow_empty and not value.strip():
        raise ContractError(f"{name} must not be empty")
    return value


def _expect_json_value(value: Any, name: str) -> None:
    """Check recursively that a value can be represented by standard JSON."""
    if value is None or isinstance(value, (str, bool, int)):
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ContractError(f"{name} must not contain NaN or infinity")
        return
    if isinstance(value, list):
        for index, item in enumerate(value):
            _expect_json_value(item, f"{name}[{index}]")
        return
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                raise ContractError(f"{name} object keys must be strings")
            _expect_json_value(item, f"{name}.{key}")
        return
    raise ContractError(f"{name} contains a non-JSON value")


def _enum(enum_type: type[Enum], value: Any, name: str) -> Any:
    if not isinstance(value, str):
        raise ContractError(f"{name} must be a string enum value")
    try:
        return enum_type(value)
    except ValueError as error:
        raise ContractError(f"invalid {name}: {value!r}") from error


@dataclass(frozen=True)
class DecisionInput:
    """Top-level request envelope; absent fields inside ``case`` are allowed."""

    query: str
    case: Mapping[str, Any]
    requested_scope: str

    def __post_init__(self) -> None:
        _expect_text(self.query, "query")
        _expect_text(self.requested_scope, "requested_scope")
        if not isinstance(self.case, dict):
            raise ContractError("case must be a JSON object")
        _expect_json_value(self.case, "case")

    def to_dict(self) -> dict[str, Any]:
        return {
            "query": self.query,
            "case": dict(self.case),
            "requested_scope": self.requested_scope,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, allow_nan=False)

    @classmethod
    def from_dict(cls, value: Any) -> "DecisionInput":
        data = _expect_object(value, {"query", "case", "requested_scope"}, "input")
        return cls(
            query=_expect_text(data["query"], "query"),
            case=data["case"],
            requested_scope=_expect_text(data["requested_scope"], "requested_scope"),
        )

    @classmethod
    def from_json(cls, value: str) -> "DecisionInput":
        try:
            parsed = json.loads(value)
        except (TypeError, json.JSONDecodeError) as error:
            raise ContractError("input must be valid JSON") from error
        return cls.from_dict(parsed)


@dataclass(frozen=True)
class ClassificationResult:
    category: QuestionType
    similarity: float | None

    def __post_init__(self) -> None:
        if not isinstance(self.category, QuestionType):
            raise ContractError("category must be a QuestionType")
        if self.similarity is not None:
            if isinstance(self.similarity, bool) or not isinstance(self.similarity, (int, float)):
                raise ContractError("similarity must be a number or null")
            if not math.isfinite(self.similarity) or not -1.0 <= self.similarity <= 1.0:
                raise ContractError("similarity must be finite and between -1 and 1")


@dataclass(frozen=True)
class CheckResult:
    kind: CheckKind
    status: CheckStatus
    reason_code: ReasonCode | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.kind, CheckKind):
            raise ContractError("kind must be a CheckKind")
        if not isinstance(self.status, CheckStatus):
            raise ContractError("status must be a CheckStatus")
        if self.reason_code is not None and not isinstance(self.reason_code, ReasonCode):
            raise ContractError("reason_code must be a ReasonCode or null")


@dataclass(frozen=True)
class DecisionResult:
    classification: ClassificationResult
    rule_id: str | None
    checks: tuple[CheckResult, ...]
    missing_fields: tuple[str, ...]
    reason_codes: tuple[ReasonCode, ...]
    decision: Decision

    def __post_init__(self) -> None:
        if not isinstance(self.classification, ClassificationResult):
            raise ContractError("classification must be a ClassificationResult")
        if self.rule_id is not None:
            _expect_text(self.rule_id, "rule_id")
        if not isinstance(self.checks, tuple) or not all(
            isinstance(check, CheckResult) for check in self.checks
        ):
            raise ContractError("checks must be a tuple of CheckResult values")
        check_kinds = tuple(check.kind for check in self.checks)
        if len(check_kinds) != len(CheckKind) or set(check_kinds) != set(CheckKind):
            raise ContractError("checks must contain each CheckKind exactly once")
        if not isinstance(self.missing_fields, tuple) or not all(
            isinstance(item, str) and item.strip() for item in self.missing_fields
        ):
            raise ContractError("missing_fields must contain non-empty strings")
        if not isinstance(self.reason_codes, tuple) or not all(
            isinstance(item, ReasonCode) for item in self.reason_codes
        ):
            raise ContractError("reason_codes must be a tuple of ReasonCode values")
        if not isinstance(self.decision, Decision):
            raise ContractError("decision must be a Decision")

    def to_dict(self) -> dict[str, Any]:
        return {
            "classification": {
                "category": self.classification.category.value,
                "similarity": self.classification.similarity,
            },
            "rule_id": self.rule_id,
            "checks": [
                {
                    "kind": check.kind.value,
                    "status": check.status.value,
                    "reason_code": check.reason_code.value if check.reason_code else None,
                }
                for check in self.checks
            ],
            "missing_fields": list(self.missing_fields),
            "reason_codes": [code.value for code in self.reason_codes],
            "decision": self.decision.value,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, allow_nan=False)

    @classmethod
    def from_dict(cls, value: Any) -> "DecisionResult":
        data = _expect_object(
            value,
            {"classification", "rule_id", "checks", "missing_fields", "reason_codes", "decision"},
            "result",
        )
        classification_data = _expect_object(
            data["classification"], {"category", "similarity"}, "classification"
        )
        similarity = classification_data["similarity"]
        classification = ClassificationResult(
            category=_enum(QuestionType, classification_data["category"], "category"),
            similarity=similarity,
        )
        rule_id = data["rule_id"]
        if rule_id is not None:
            rule_id = _expect_text(rule_id, "rule_id")
        if not isinstance(data["checks"], list):
            raise ContractError("checks must be a JSON array")
        checks = []
        for index, raw_check in enumerate(data["checks"]):
            check_data = _expect_object(
                raw_check, {"kind", "status", "reason_code"}, f"checks[{index}]"
            )
            reason = check_data["reason_code"]
            checks.append(
                CheckResult(
                    kind=_enum(CheckKind, check_data["kind"], f"checks[{index}].kind"),
                    status=_enum(CheckStatus, check_data["status"], f"checks[{index}].status"),
                    reason_code=(
                        _enum(ReasonCode, reason, f"checks[{index}].reason_code")
                        if reason is not None
                        else None
                    ),
                )
            )
        missing_fields = data["missing_fields"]
        reason_codes = data["reason_codes"]
        if not isinstance(missing_fields, list):
            raise ContractError("missing_fields must be a JSON array")
        if not isinstance(reason_codes, list):
            raise ContractError("reason_codes must be a JSON array")
        return cls(
            classification=classification,
            rule_id=rule_id,
            checks=tuple(checks),
            missing_fields=tuple(
                _expect_text(item, f"missing_fields[{index}]")
                for index, item in enumerate(missing_fields)
            ),
            reason_codes=tuple(
                _enum(ReasonCode, item, f"reason_codes[{index}]")
                for index, item in enumerate(reason_codes)
            ),
            decision=_enum(Decision, data["decision"], "decision"),
        )

    @classmethod
    def from_json(cls, value: str) -> "DecisionResult":
        try:
            parsed = json.loads(value)
        except (TypeError, json.JSONDecodeError) as error:
            raise ContractError("result must be valid JSON") from error
        return cls.from_dict(parsed)
