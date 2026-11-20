"""Backward-compatible import path for shared JSON contracts."""

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

__all__ = [
    "CheckKind", "CheckResult", "CheckStatus", "ClassificationResult", "ContractError",
    "Decision", "DecisionInput", "DecisionResult", "QuestionType", "ReasonCode",
]
