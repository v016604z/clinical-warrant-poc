"""Backward-compatible catalog API."""

from clinical_warrant.infrastructure.catalog import load_research_catalog
from clinical_warrant.shared.domain.catalog import (
    QUESTION_TYPES,
    CatalogError,
    MockCase,
    PrototypeCategory,
    ResearchCatalog,
    RuleDefinition,
    validate_mock_cases,
    validate_prototypes,
    validate_rules,
)
from clinical_warrant.shared.domain.contracts import ContractError, DecisionInput, QuestionType

__all__ = [
    "QUESTION_TYPES", "CatalogError", "MockCase", "PrototypeCategory",
    "ResearchCatalog", "RuleDefinition", "ContractError", "DecisionInput", "QuestionType",
    "load_research_catalog", "validate_mock_cases",
    "validate_prototypes", "validate_rules",
]
