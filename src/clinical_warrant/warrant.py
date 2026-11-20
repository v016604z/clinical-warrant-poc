"""Backward-compatible decision API with packaged default toy rules."""

from clinical_warrant.infrastructure.catalog import load_research_catalog
from clinical_warrant.modules.decision.application.warrant import (
    QuestionClassifierProtocol,
    WarrantEngine as _WarrantEngine,
    WarrantError,
)
from clinical_warrant.modules.decision.domain.policy import (
    _is_missing,
    validate_rules as _validate_rule_definitions,
)
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


class WarrantEngine(_WarrantEngine):
    """Compatibility wrapper retaining the original optional rules argument."""

    def __init__(self, classifier, *, rules: tuple[RuleDefinition, ...] | None = None) -> None:
        active_rules = rules if rules is not None else load_research_catalog().rules
        super().__init__(classifier, rules=active_rules)


__all__ = [
    "CheckKind", "CheckResult", "CheckStatus", "ClassificationResult", "Decision",
    "DecisionInput", "DecisionResult", "QuestionClassifierProtocol", "QuestionType",
    "ReasonCode", "WarrantEngine", "WarrantError",
]
