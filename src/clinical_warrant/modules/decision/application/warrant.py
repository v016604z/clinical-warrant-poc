"""Decision use case that classifies a request and applies domain policy."""

from __future__ import annotations

from typing import Protocol

from clinical_warrant.modules.decision.domain.policy import WarrantError, decide, validate_rules
from clinical_warrant.shared.domain.catalog import RuleDefinition
from clinical_warrant.shared.domain.contracts import ClassificationResult, DecisionInput, DecisionResult


class QuestionClassifierProtocol(Protocol):
    def classify(self, query: str) -> ClassificationResult:
        """Return the question type and its cosine similarity."""


class WarrantEngine:
    """Coordinate classification with the pure tri-state decision policy."""

    def __init__(self, classifier: QuestionClassifierProtocol, *, rules: tuple[RuleDefinition, ...]) -> None:
        self.classifier = classifier
        self.rules_by_type = validate_rules(rules)

    def decide(self, request: DecisionInput) -> DecisionResult:
        classification = self.classifier.classify(request.query)
        return decide(request, classification, self.rules_by_type)
