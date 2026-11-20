"""Compatibility checks for established package entry points."""

from clinical_warrant.catalog import PrototypeCategory as LegacyPrototypeCategory
from clinical_warrant.catalog import ContractError as LegacyCatalogContractError
from clinical_warrant.catalog import DecisionInput as LegacyCatalogDecisionInput
from clinical_warrant.catalog import QuestionType as LegacyCatalogQuestionType
from clinical_warrant.classifier import QuestionClassifier as LegacyQuestionClassifier
from clinical_warrant.cli import main
from clinical_warrant.contracts import DecisionInput as LegacyDecisionInput
from clinical_warrant.modules.classification import QuestionClassifier
from clinical_warrant.modules.decision import WarrantEngine
from clinical_warrant.shared.domain.catalog import PrototypeCategory
from clinical_warrant.shared.domain.contracts import DecisionInput
from clinical_warrant.warrant import WarrantEngine as LegacyWarrantEngine
from clinical_warrant.warrant import (
    CheckKind as LegacyCheckKind,
    ClassificationResult as LegacyClassificationResult,
    Decision as LegacyDecision,
    DecisionResult as LegacyDecisionResult,
    QuestionClassifierProtocol as LegacyQuestionClassifierProtocol,
    QuestionType as LegacyWarrantQuestionType,
    ReasonCode as LegacyReasonCode,
)
from clinical_warrant.shared.domain.contracts import (
    CheckKind,
    ClassificationResult,
    ContractError,
    Decision,
    DecisionResult,
    QuestionType,
    ReasonCode,
)
from clinical_warrant.modules.decision import QuestionClassifierProtocol
from clinical_warrant.modules.evaluation import DecisionEngine as PublicDecisionEngine
from clinical_warrant.evaluation import DecisionEngine as LegacyDecisionEngine


def test_legacy_imports_forward_to_new_public_module_types() -> None:
    assert LegacyPrototypeCategory is PrototypeCategory
    assert LegacyDecisionInput is DecisionInput
    assert LegacyCatalogContractError is ContractError
    assert LegacyCatalogDecisionInput is DecisionInput
    assert LegacyCatalogQuestionType is QuestionType
    assert issubclass(LegacyQuestionClassifier, QuestionClassifier)
    assert issubclass(LegacyWarrantEngine, WarrantEngine)
    assert LegacyCheckKind is CheckKind
    assert LegacyClassificationResult is ClassificationResult
    assert LegacyDecision is Decision
    assert LegacyDecisionResult is DecisionResult
    assert LegacyQuestionClassifierProtocol is QuestionClassifierProtocol
    assert LegacyWarrantQuestionType is QuestionType
    assert LegacyReasonCode is ReasonCode
    assert LegacyDecisionEngine is PublicDecisionEngine


def test_legacy_cli_entrypoint_remains_callable() -> None:
    assert callable(main)
