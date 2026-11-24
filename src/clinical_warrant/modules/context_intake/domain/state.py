"""In-memory domain state for multi-turn context intake."""

from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Literal, Mapping, TypeAlias

from clinical_warrant.modules.context_intake.domain.classification import IntakeClassificationResult


AttributeScalar: TypeAlias = str | int | bool
ChangeAction: TypeAlias = Literal["add", "correct", "confirm"]
CategorySource: TypeAlias = Literal["classification", "continuation", "handoff"]


def _identifier(value: str, name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")


def _value(value: object, name: str) -> None:
    if value is None or not isinstance(value, (str, int, bool)):
        raise ValueError(f"{name} must be a non-null string, integer, or boolean")
    if isinstance(value, str) and not value.strip():
        raise ValueError(f"{name} must not be blank")


def _same_value(left: AttributeScalar, right: AttributeScalar) -> bool:
    # bool subclasses int, but False and 0 are distinct domain values.
    return type(left) is type(right) and left == right


@dataclass(frozen=True)
class AttributeChange:
    """One accepted addition, correction, or explicit confirmation."""

    action: ChangeAction
    old_value: AttributeScalar | None
    new_value: AttributeScalar
    source_turn_id: str

    def __post_init__(self) -> None:
        if self.action not in ("add", "correct", "confirm"):
            raise ValueError("action must be add, correct, or confirm")
        if self.action == "add" and self.old_value is not None:
            raise ValueError("an add change must not have an old value")
        if self.action != "add" and self.old_value is None:
            raise ValueError("a correction or confirmation must have an old value")
        if self.old_value is not None:
            _value(self.old_value, "old_value")
        _value(self.new_value, "new_value")
        _identifier(self.source_turn_id, "source_turn_id")


@dataclass(frozen=True)
class AttributeValue:
    """Current explicit value and the changes that produced it."""

    value: AttributeScalar
    source_turn_id: str
    history: tuple[AttributeChange, ...]

    def __post_init__(self) -> None:
        _value(self.value, "value")
        _identifier(self.source_turn_id, "source_turn_id")
        if not self.history:
            raise ValueError("attribute history must include its add change")
        if any(not isinstance(change, AttributeChange) for change in self.history):
            raise ValueError("history entries must be AttributeChange values")
        last = self.history[-1]
        if not _same_value(last.new_value, self.value) or last.source_turn_id != self.source_turn_id:
            raise ValueError("current value and source turn must match the latest change")


@dataclass(frozen=True)
class CaseState:
    """A participant-owned case whose attributes are shared across categories."""

    case_id: str
    participant_id: str
    attributes: Mapping[str, AttributeValue] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _identifier(self.case_id, "case_id")
        _identifier(self.participant_id, "participant_id")
        attributes = dict(self.attributes)
        for key, attribute in attributes.items():
            _identifier(key, "field_key")
            if not isinstance(attribute, AttributeValue):
                raise ValueError("attributes must contain AttributeValue values")
        object.__setattr__(self, "attributes", MappingProxyType(attributes))

    def with_attribute(
        self,
        field_key: str,
        value: AttributeScalar,
        source_turn_id: str,
        *,
        action: ChangeAction | None = None,
    ) -> CaseState:
        """Return updated case state; differing values require explicit approval."""
        _identifier(field_key, "field_key")
        _value(value, "value")
        _identifier(source_turn_id, "source_turn_id")
        current = self.attributes.get(field_key)
        if current is None:
            if action not in (None, "add"):
                raise ValueError("a new attribute must use the add action")
            change = AttributeChange("add", None, value, source_turn_id)
            updated = AttributeValue(value, source_turn_id, (change,))
        else:
            if _same_value(current.value, value):
                return self
            if action not in ("correct", "confirm"):
                raise ValueError("a differing value requires explicit correct or confirm action")
            change = AttributeChange(action, current.value, value, source_turn_id)
            updated = AttributeValue(value, source_turn_id, (*current.history, change))
        attributes = dict(self.attributes)
        attributes[field_key] = updated
        return CaseState(self.case_id, self.participant_id, attributes)


@dataclass(frozen=True)
class PendingQuestion:
    """A single unanswered field question tied to its originating case/category."""

    case_id: str
    category_id: str
    field_key: str
    question: str

    def __post_init__(self) -> None:
        for name in ("case_id", "category_id", "field_key", "question"):
            _identifier(getattr(self, name), name)


@dataclass(frozen=True)
class PendingConflict:
    """A candidate value awaiting clarification without replacing the known value."""

    case_id: str
    category_id: str
    field_key: str
    old_value: AttributeScalar
    candidate_value: AttributeScalar
    old_source_turn_id: str
    candidate_source_turn_id: str

    def __post_init__(self) -> None:
        for name in ("case_id", "category_id", "field_key", "old_source_turn_id", "candidate_source_turn_id"):
            _identifier(getattr(self, name), name)
        _value(self.old_value, "old_value")
        _value(self.candidate_value, "candidate_value")
        if _same_value(self.old_value, self.candidate_value):
            raise ValueError("a pending conflict must contain differing values")


@dataclass(frozen=True)
class TurnEvent:
    """Structured turn provenance; deliberately excludes the original message."""

    turn_id: str
    case_id: str | None
    category_id: str | None
    category_source: CategorySource
    classification: IntakeClassificationResult | None
    selected_fields: tuple[str, ...]
    catalog_version: str

    def __post_init__(self) -> None:
        _identifier(self.turn_id, "turn_id")
        if self.case_id is not None:
            _identifier(self.case_id, "case_id")
        if self.category_id is not None:
            _identifier(self.category_id, "category_id")
        if self.category_source not in ("classification", "continuation", "handoff"):
            raise ValueError("category_source must be classification, continuation, or handoff")
        _identifier(self.catalog_version, "catalog_version")
        selected_fields = tuple(self.selected_fields)
        for field_key in selected_fields:
            _identifier(field_key, "selected field")
        if len(selected_fields) != len(set(selected_fields)):
            raise ValueError("selected_fields must not contain duplicates")
        if self.category_id is None and selected_fields:
            raise ValueError("selected_fields require a category_id")
        if self.case_id is None and selected_fields:
            raise ValueError("selected_fields require a case_id")
        object.__setattr__(self, "selected_fields", selected_fields)
        if self.category_source == "classification" and self.classification is None:
            raise ValueError("classification source requires a classification result")
        if self.category_source != "classification" and self.classification is not None:
            raise ValueError("only classification source may include a classification result")
        if self.classification is not None:
            if not isinstance(self.classification, IntakeClassificationResult):
                raise ValueError("classification must be an IntakeClassificationResult or None")
            if self.classification.catalog_version != self.catalog_version:
                raise ValueError("classification and turn must use the same catalog version")
            if self.classification.is_unknown:
                if self.category_id is not None:
                    raise ValueError("unknown classification must not set category_id")
            elif self.category_id != self.classification.top1_category_id:
                raise ValueError("accepted classification category must match Top-1")


@dataclass(frozen=True)
class SessionState:
    """Participant session with active pointers and its in-memory case collection."""

    session_id: str
    participant_id: str
    cases: Mapping[str, CaseState] = field(default_factory=dict)
    active_case_id: str | None = None
    active_category_id: str | None = None
    pending_question: PendingQuestion | None = None
    pending_conflict: PendingConflict | None = None
    turn_events: tuple[TurnEvent, ...] = ()
    awaiting_case_restatement: bool = False

    def __post_init__(self) -> None:
        _identifier(self.session_id, "session_id")
        _identifier(self.participant_id, "participant_id")
        if type(self.awaiting_case_restatement) is not bool:
            raise ValueError("awaiting_case_restatement must be a boolean")
        cases = dict(self.cases)
        for case_id, case in cases.items():
            _identifier(case_id, "case_id")
            if not isinstance(case, CaseState) or case.case_id != case_id:
                raise ValueError("case mapping keys must match CaseState IDs")
            if case.participant_id != self.participant_id:
                raise ValueError("case participant must match session participant")
        object.__setattr__(self, "cases", MappingProxyType(cases))
        if self.active_case_id is not None:
            _identifier(self.active_case_id, "active_case_id")
            if self.active_case_id not in cases:
                raise ValueError("active case must belong to this session participant")
        if self.active_category_id is not None:
            _identifier(self.active_category_id, "active_category_id")
        for name in ("pending_question", "pending_conflict"):
            pending = getattr(self, name)
            if pending is None:
                continue
            if self.active_case_id != pending.case_id or self.active_category_id != pending.category_id:
                raise ValueError(f"{name} must match the active case and category")
            if pending.case_id not in cases:
                raise ValueError(f"{name} case must belong to this session participant")
        turn_events = tuple(self.turn_events)
        turn_ids: set[str] = set()
        for event in turn_events:
            if not isinstance(event, TurnEvent):
                raise ValueError("turn_events must contain TurnEvent values")
            if event.turn_id in turn_ids:
                raise ValueError("turn event IDs must be unique within a session")
            turn_ids.add(event.turn_id)
            if event.case_id is not None and event.case_id not in cases:
                raise ValueError("turn event case must belong to this session participant")
        object.__setattr__(self, "turn_events", turn_events)
