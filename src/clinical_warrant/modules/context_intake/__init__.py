"""Public API for context intake category registry."""

from clinical_warrant.modules.context_intake.domain.category_registry import (
    CategoryDefinition,
    CategoryField,
    CategoryRegistry,
    RegistryError,
)
from clinical_warrant.modules.context_intake.infrastructure.category_registry import load_category_registry
from clinical_warrant.modules.context_intake.domain.classification import IntakeClassificationResult, IntakePrototypeCategory
from clinical_warrant.modules.context_intake.application.classifier import IntakeQuestionClassifier
from clinical_warrant.modules.context_intake.infrastructure.prototype_catalog import load_intake_prototype_catalog

__all__ = [
    "CategoryDefinition",
    "CategoryField",
    "CategoryRegistry",
    "RegistryError",
    "load_category_registry",
    "IntakeClassificationResult",
    "IntakeQuestionClassifier",
    "IntakePrototypeCategory",
    "load_intake_prototype_catalog",
]
