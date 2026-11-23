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
from clinical_warrant.modules.context_intake.application.case_router import (
    CaseRouteDecision,
    CaseRouteError,
    CaseRouteRequest,
    CaseRouter,
)
from clinical_warrant.modules.context_intake.application.conversation_orchestrator import (
    ConversationOrchestrator,
    ConversationTurnResult,
)
from clinical_warrant.modules.context_intake.application.coverage import (
    CategoryCoverage,
    CoverageError,
    calculate_case_coverage,
)
from clinical_warrant.modules.context_intake.infrastructure.prototype_catalog import load_intake_prototype_catalog
from clinical_warrant.modules.context_intake.infrastructure.sqlite_repository import (
    SQLiteContextIntakeRepository,
    initialize_database,
)
from clinical_warrant.modules.context_intake.application.intake import (
    ContextIntakeRepository,
    ContextIntakeService,
    IntakeTurnResult,
)
from clinical_warrant.modules.context_intake.application.extraction import (
    ExtractionError,
    ExtractionRequest,
    ExtractionResult,
    Extractor,
    parse_extraction_response,
)
from clinical_warrant.modules.context_intake.domain.state import (
    AttributeChange,
    AttributeValue,
    CaseState,
    PendingConflict,
    PendingQuestion,
    SessionState,
    TurnEvent,
)

__all__ = [
    "CategoryDefinition",
    "CategoryField",
    "CategoryRegistry",
    "RegistryError",
    "load_category_registry",
    "IntakeClassificationResult",
    "IntakeQuestionClassifier",
    "CaseRouteDecision",
    "CaseRouteError",
    "CaseRouteRequest",
    "CaseRouter",
    "ConversationOrchestrator",
    "ConversationTurnResult",
    "CategoryCoverage",
    "CoverageError",
    "calculate_case_coverage",
    "IntakePrototypeCategory",
    "load_intake_prototype_catalog",
    "SQLiteContextIntakeRepository",
    "initialize_database",
    "ContextIntakeService",
    "ContextIntakeRepository",
    "IntakeTurnResult",
    "ExtractionError",
    "ExtractionRequest",
    "ExtractionResult",
    "Extractor",
    "parse_extraction_response",
    "AttributeChange",
    "AttributeValue",
    "CaseState",
    "PendingConflict",
    "PendingQuestion",
    "SessionState",
    "TurnEvent",
]
