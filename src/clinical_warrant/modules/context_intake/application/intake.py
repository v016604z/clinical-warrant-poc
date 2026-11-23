"""In-memory multi-turn Context Intake orchestration."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Callable, Mapping, Protocol
from uuid import uuid4

from clinical_warrant.modules.context_intake.application.extraction import (
    ExtractionResult,
    ExtractionRequest,
    Extractor,
    parse_extraction_response,
)
from clinical_warrant.modules.context_intake.domain.category_registry import CategoryRegistry
from clinical_warrant.modules.context_intake.domain.classification import IntakeClassificationResult
from clinical_warrant.modules.context_intake.domain.state import (
    CaseState,
    PendingConflict,
    PendingQuestion,
    SessionState,
    TurnEvent,
)


class IntakeClassifier(Protocol):
    def classify(self, query: str) -> IntakeClassificationResult: ...


class ContextIntakeRepository(Protocol):
    """Persistence port for complete immutable session snapshots."""

    def save_session(self, session: SessionState) -> None: ...

    def load_session(self, session_id: str) -> SessionState | None: ...

    def delete_case(self, case_id: str, participant_id: str) -> bool: ...


@dataclass(frozen=True)
class IntakeTurnResult:
    session: SessionState
    turn_id: str
    category_id: str | None
    category_source: str
    classification: IntakeClassificationResult | None
    extraction: ExtractionResult | None
    clarification: str | None
    handoff_required: bool = False


class ContextIntakeService:
    """Coordinate classification, extraction and immutable in-memory session state.

    Callers must pass ``new_case=True`` when a turn establishes a case context,
    including the first case and each subsequent new exposure. A category's
    having fields is not evidence that the user described a personal event.
    """

    def __init__(
        self,
        *,
        classifier: IntakeClassifier,
        extractor: Extractor,
        registry: CategoryRegistry,
        id_factory: Callable[[], str] | None = None,
        repository: ContextIntakeRepository | None = None,
    ) -> None:
        self.classifier = classifier
        self.extractor = extractor
        self.registry = registry
        classifier_version = getattr(classifier, "catalog_version", None)
        if classifier_version is not None and classifier_version != registry.version:
            raise ValueError("classifier catalog_version does not match the Category Registry")
        self.id_factory = id_factory or (lambda: str(uuid4()))
        self.repository = repository
        self._sessions: dict[str, SessionState] = {}

    @property
    def sessions(self) -> Mapping[str, SessionState]:
        return dict(self._sessions)

    def process_turn(
        self,
        *,
        participant_id: str,
        message: str,
        session_id: str | None = None,
        new_case: bool = False,
        new_question: bool = False,
        clear_case: bool = False,
        confirm_conflict: bool = False,
        keep_existing: bool = False,
        correct_fields: tuple[str, ...] = (),
        urgent_handoff: bool = False,
        classification: IntakeClassificationResult | None = None,
    ) -> IntakeTurnResult:
        """Process one user turn; IDs and state transitions are service-owned.

        ``confirm_conflict`` explicitly accepts the pending candidate. Values in
        ``correct_fields`` are explicit user corrections and are added to history.
        ``urgent_handoff`` is supplied by the caller and only requests immediate
        routing; this service does not decide whether a situation is urgent.
        """
        if not isinstance(participant_id, str) or not participant_id.strip():
            raise ValueError("participant_id must be a non-empty string")
        if not isinstance(message, str) or not message.strip():
            raise ValueError("message must be a non-empty string")
        if any(type(value) is not bool for value in (
            new_case, new_question, clear_case, confirm_conflict, keep_existing, urgent_handoff
        )):
            raise ValueError("new_case, new_question, clear_case, conflict controls, and urgent_handoff must be booleans")
        if not isinstance(correct_fields, tuple) or any(not isinstance(key, str) for key in correct_fields):
            raise ValueError("correct_fields must be a tuple of field keys")
        if len(correct_fields) != len(set(correct_fields)):
            raise ValueError("correct_fields must not contain duplicates")
        if new_case and new_question:
            raise ValueError("new_case and new_question are mutually exclusive")
        if clear_case and (new_case or confirm_conflict or keep_existing or urgent_handoff):
            raise ValueError("clear_case cannot be combined with new_case, conflict resolution, or urgent_handoff")
        if confirm_conflict and keep_existing:
            raise ValueError("confirm_conflict and keep_existing are mutually exclusive")
        if (confirm_conflict or keep_existing) and (new_case or new_question):
            raise ValueError("conflict resolution cannot be combined with a new case or question")

        if session_id is None:
            session_id = self.id_factory()
        current = self._sessions.get(session_id)
        if current is None:
            current = self.repository.load_session(session_id) if self.repository is not None else None
            if current is not None and current.participant_id != participant_id:
                raise ValueError("session participant does not match participant_id")
            if current is not None:
                self._validate_restored_session(current)
            if current is None:
                current = SessionState(session_id=session_id, participant_id=participant_id)
        elif current.participant_id != participant_id:
            raise ValueError("session participant does not match participant_id")
        turn_id = self.id_factory()

        # This is a caller-provided routing signal, not a medical urgency
        # classifier. It must immediately let the upper layer handle referral.
        if urgent_handoff:
            updated = self._append_event(current, TurnEvent(
                turn_id, current.active_case_id, current.active_category_id,
                "handoff", None, (), self.registry.version,
            ))
            self._commit(updated)
            return IntakeTurnResult(
                updated, turn_id, current.active_category_id, "handoff", None, None, None, True
            )

        if clear_case:
            # Keep the case collection and history; only stop associating this
            # and subsequent turns with the prior active case.
            current = replace(
                current, active_case_id=None, active_category_id=None,
                pending_question=None, pending_conflict=None,
            )

        # A direct conflict confirmation is a structured caller signal; it must
        # not needlessly invoke either the classifier or the extractor.
        if (confirm_conflict or keep_existing) and current.pending_conflict is None:
            raise ValueError("conflict resolution requires a pending conflict")
        if current.pending_conflict is not None and (confirm_conflict or keep_existing):
            conflict = current.pending_conflict
            case = current.cases[conflict.case_id]
            if confirm_conflict:
                case = case.with_attribute(
                    conflict.field_key, conflict.candidate_value, turn_id, action="confirm"
                )
            updated = self._replace_case(
                current, case, pending_conflict=None, pending_question=None,
            )
            updated = self._append_event(updated, TurnEvent(
                turn_id, case.case_id, conflict.category_id, "continuation", None, (),
                self.registry.version,
            ))
            self._commit(updated)
            return IntakeTurnResult(
                updated, turn_id, conflict.category_id, "continuation", None, None,
                None if confirm_conflict else "已保留原先記錄的值。",
            )

        continuation = (not new_case and not new_question and not clear_case
                        and (current.pending_question is not None or current.pending_conflict is not None))
        if continuation:
            classification = None
        elif classification is None:
            classification = self.classifier.classify(message)
        if (classification is not None and getattr(classification, "catalog_version", None) is not None
                and classification.catalog_version != self.registry.version):
            raise ValueError("classification catalog_version does not match the Category Registry")
        category_id = (
            current.pending_question.category_id if current.pending_question is not None and continuation
            else current.pending_conflict.category_id if current.pending_conflict is not None and continuation
            else None if classification is None or classification.is_unknown
            else classification.top1_category_id
        )
        if category_id is None:
            updated = replace(current, active_category_id=None, pending_question=None, pending_conflict=None)
            updated = self._append_event(updated, TurnEvent(
                turn_id, None, None, "classification", classification, (), self.registry.version,
            ))
            self._commit(updated)
            return IntakeTurnResult(
                updated, turn_id, None, "classification", classification, None,
                "我還不確定您想詢問哪一類問題，可以再補充一下嗎？",
            )

        category = self.registry.get(category_id)
        cases = dict(current.cases)
        active_case_id = current.active_case_id
        if new_case:
            active_case_id = self.id_factory()
            cases[active_case_id] = CaseState(active_case_id, participant_id)
        case = cases.get(active_case_id) if active_case_id is not None else None
        active_category_id = category_id
        pending_question = None if new_case or new_question or clear_case or not continuation else current.pending_question
        pending_conflict = None if new_case or new_question or clear_case or not continuation else current.pending_conflict

        # Without explicit case context (or for a fieldless education category),
        # return classification only and never create person-specific facts.
        if case is None or not category.fields:
            if correct_fields:
                raise ValueError("correct_fields requires an active case and extractable attributes")
            updated = SessionState(
                session_id, participant_id, cases, active_case_id, active_category_id,
                turn_events=current.turn_events,
            )
            updated = self._append_event(updated, TurnEvent(
                turn_id, case.case_id if case is not None else None, category_id,
                "continuation" if continuation else "classification", classification, (),
                self.registry.version,
            ))
            self._commit(updated)
            return IntakeTurnResult(updated, turn_id, category_id,
                                    "continuation" if continuation else "classification",
                                    classification, None, None)

        known = {key: item.value for key, item in case.attributes.items()}
        context = ()
        if pending_question is not None:
            context = (pending_question.question,)
        elif pending_conflict is not None:
            context = (f"請確認欄位 {pending_conflict.field_key} 的資料。",)
        request = ExtractionRequest(message, category, known, context)
        extraction = parse_extraction_response(self.extractor.extract(request), category)
        attributes = dict(extraction.extracted_attributes)
        event_selected_fields = extraction.selected_fields
        if continuation:
            expected_key = (
                pending_question.field_key if pending_question is not None
                else pending_conflict.field_key if pending_conflict is not None
                else None
            )
            # A short answer to a pending question must never populate another
            # field, even if the model selected it for this category.
            attributes = {key: value for key, value in attributes.items() if key == expected_key}
            event_selected_fields = tuple(
                key for key in extraction.selected_fields if key == expected_key
            )
            if (extraction.clarification_field_key is not None
                    and extraction.clarification_field_key != expected_key):
                raise ValueError("a continuation cannot change the pending clarification field")
            if any(key != expected_key for key in correct_fields):
                raise ValueError("a continuation can only correct its pending field")
        if set(correct_fields) - attributes.keys():
            raise ValueError("correct_fields must refer to extracted attributes")
        if any(key not in case.attributes for key in correct_fields):
            raise ValueError("correct_fields must refer to an already known case attribute")

        clarification: str | None = None
        for field_key, value in attributes.items():
            current_value = case.attributes.get(field_key)
            if field_key in correct_fields:
                case = case.with_attribute(field_key, value, turn_id, action="correct")
                if pending_conflict is not None and pending_conflict.field_key == field_key:
                    pending_conflict = None
            elif current_value is not None and (
                type(value) is not type(current_value.value) or value != current_value.value
            ):
                if pending_conflict is not None and pending_conflict.field_key != field_key:
                    raise ValueError("one turn cannot create conflicts for multiple fields")
                pending_conflict = PendingConflict(
                    case.case_id, category_id, field_key, current_value.value, value,
                    current_value.source_turn_id, turn_id,
                )
                clarification = (
                    f"{field_key} 先前記錄為「{current_value.value}」，本次提供「{value}」。"
                    "請確認要保留哪一個值。"
                )
            else:
                case = case.with_attribute(field_key, value, turn_id)
                if pending_question is not None and pending_question.field_key == field_key:
                    pending_question = None

        cases[case.case_id] = case
        if pending_conflict is not None and clarification is None:
            clarification = (
                f"請確認 {pending_conflict.field_key} 是否改為「{pending_conflict.candidate_value}」。"
            )
        if pending_conflict is None and extraction.clarification_question is not None:
            key = extraction.clarification_field_key
            if key is not None and key not in case.attributes:
                pending_question = PendingQuestion(case.case_id, category_id, key,
                                                   extraction.clarification_question)
                clarification = extraction.clarification_question
        updated = SessionState(
            session_id, participant_id, cases, case.case_id, active_category_id,
            pending_question, pending_conflict, current.turn_events,
        )
        updated = self._append_event(updated, TurnEvent(
            turn_id, case.case_id, category_id,
            "continuation" if continuation else "classification", classification,
            event_selected_fields, self.registry.version,
        ))
        self._commit(updated)
        return IntakeTurnResult(
            updated, turn_id, category_id,
            "continuation" if continuation else "classification",
            classification, extraction, clarification,
        )

    @staticmethod
    def _replace_case(
        session: SessionState,
        case: CaseState,
        *,
        pending_question: PendingQuestion | None,
        pending_conflict: PendingConflict | None,
    ) -> SessionState:
        cases = dict(session.cases)
        cases[case.case_id] = case
        return SessionState(
            session.session_id, session.participant_id, cases, case.case_id,
            session.active_category_id, pending_question, pending_conflict, session.turn_events,
        )

    @staticmethod
    def _append_event(session: SessionState, event: TurnEvent) -> SessionState:
        """Return a state with this successful turn appended as structured history."""
        return replace(session, turn_events=(*session.turn_events, event))

    def _commit(self, session: SessionState) -> None:
        """Persist first so a failed write cannot publish partial memory state."""
        if self.repository is not None:
            self.repository.save_session(session)
        self._sessions[session.session_id] = session

    def _validate_restored_session(self, session: SessionState) -> None:
        """Reject active state that cannot be interpreted by the current Registry."""
        category_id = session.active_category_id
        if category_id is None:
            return
        if not session.turn_events:
            raise ValueError("stored active category has no originating turn event")
        last_event = session.turn_events[-1]
        if last_event.catalog_version != self.registry.version:
            raise ValueError("stored active category uses a different Category Registry version")
        if last_event.category_id != category_id:
            raise ValueError("stored active category does not match the latest turn event")
        try:
            category = self.registry.get(category_id)
        except (KeyError, ValueError) as error:
            raise ValueError("stored active category is not present in the current Registry") from error
        for pending in (session.pending_question, session.pending_conflict):
            if pending is not None and pending.field_key not in category.fields:
                raise ValueError("stored pending field is not present in the current Category")

    def delete_case(self, participant_id: str, case_id: str) -> bool:
        """Delete a participant-owned case and evict all affected session snapshots."""
        if self.repository is None:
            raise RuntimeError("delete_case requires an injected repository")
        if not isinstance(participant_id, str) or not participant_id.strip():
            raise ValueError("participant_id must be a non-empty string")
        if not isinstance(case_id, str) or not case_id.strip():
            raise ValueError("case_id must be a non-empty string")
        deleted = self.repository.delete_case(case_id, participant_id=participant_id)
        if deleted:
            self._sessions = {
                session_id: session
                for session_id, session in self._sessions.items()
                if session.participant_id != participant_id
            }
        return deleted


__all__ = ["ContextIntakeRepository", "ContextIntakeService", "IntakeTurnResult"]
