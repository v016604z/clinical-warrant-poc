"""Unified application entry point for Context Intake conversations."""

from __future__ import annotations

from dataclasses import dataclass

from clinical_warrant.modules.context_intake.application.case_router import (
    CaseRouteDecision,
    CaseRouteRequest,
    CaseRouter,
    parse_case_route,
)
from clinical_warrant.modules.context_intake.application.intake import (
    ContextIntakeService,
    IntakeTurnResult,
)
from clinical_warrant.modules.context_intake.domain.state import SessionState


_RESTATEMENT_REMINDER = (
    "若要建立新事件，請下一輪重新完整描述事件及發生時間；"
    "單獨回答「新的」不足以建立 Case。"
)


@dataclass(frozen=True)
class ConversationTurnResult:
    """Outcome of one conversational turn and its persisted intake state, if any."""

    session: SessionState
    category_id: str | None
    route_decision: CaseRouteDecision | None
    intake_result: IntakeTurnResult | None = None
    clarification: str | None = None


class ConversationOrchestrator:
    """Classify and route each new question, delegating all writes to intake.

    Case-route clarification gates are stored in this orchestrator's memory
    only. After a process restart, the user must restate the complete event.
    """

    def __init__(self, intake_service: ContextIntakeService, case_router: CaseRouter) -> None:
        self.intake_service = intake_service
        self.case_router = case_router

    def process_turn(
        self,
        *,
        participant_id: str,
        message: str,
        session_id: str | None = None,
        new_question: bool = False,
        clear_case: bool = False,
        confirm_conflict: bool = False,
        keep_existing: bool = False,
        correct_fields: tuple[str, ...] = (),
        urgent_handoff: bool = False,
    ) -> ConversationTurnResult:
        """Process a turn without allowing the router to select any state IDs.

        Pending turns are checked by the router using their active category.
        A routed continuation reuses that category and bypasses classification;
        a routed new topic is classified before the service handles it. Callers
        may also mark a pending turn explicitly as a new question.
        """
        if not isinstance(participant_id, str) or not participant_id.strip():
            raise ValueError("participant_id must be a non-empty string")
        if not isinstance(message, str) or not message.strip():
            raise ValueError("message must be a non-empty string")
        if any(type(value) is not bool for value in (
            new_question, clear_case, confirm_conflict, keep_existing, urgent_handoff,
        )):
            raise ValueError("conversation controls must be booleans")
        if confirm_conflict and keep_existing:
            raise ValueError("confirm_conflict and keep_existing are mutually exclusive")
        if session_id is None:
            session_id = self.intake_service.id_factory()
        if not isinstance(session_id, str) or not session_id.strip():
            raise ValueError("session_id must be a non-empty string")
        current = self.intake_service.sessions.get(session_id)
        if current is None and self.intake_service.repository is not None:
            current = self.intake_service.repository.load_session(session_id)
        if current is not None and current.participant_id != participant_id:
            raise ValueError("session participant does not match participant_id")
        if current is None:
            current = SessionState(session_id=session_id, participant_id=participant_id)

        # These structured controls resolve an existing state transition and do
        # not represent a question to classify or a case to route.
        if urgent_handoff or confirm_conflict or keep_existing:
            result = self._intake(
                participant_id=participant_id, message=message, session_id=session_id,
                confirm_conflict=confirm_conflict, keep_existing=keep_existing,
                correct_fields=correct_fields, urgent_handoff=urgent_handoff,
            )
            return ConversationTurnResult(result.session, result.category_id, None, result, result.clarification)

        if current.awaiting_case_restatement:
            return self._process_restatement(
                participant_id=participant_id,
                message=message,
                session_id=session_id,
                current=current,
                clear_case=clear_case,
                correct_fields=correct_fields,
            )

        pending = current.pending_question is not None or current.pending_conflict is not None
        if pending and not new_question and not clear_case:
            # Route first using the pending turn's category. A real new event
            # must not be extracted into the old case's pending field.
            pending_category = self.intake_service.registry.get(current.active_category_id)
            request = CaseRouteRequest(message, pending_category, current)
            decision = parse_case_route(self.case_router.route(request), request)
            if decision.action == "clarify":
                clarification = _clarification_with_restatement(decision.clarification_question)
                decision = CaseRouteDecision("clarify", clarification)
                current = self.intake_service.set_pending_case_restatement(participant_id, session_id)
                return ConversationTurnResult(
                    current, pending_category.category_id, decision,
                    clarification=clarification,
                )
            if decision.action == "continue_case":
                result = self._intake(
                    participant_id=participant_id, message=message, session_id=session_id,
                    correct_fields=correct_fields,
                )
                return ConversationTurnResult(
                    result.session, pending_category.category_id, decision, result, result.clarification,
                )

            # new_case and no_case start a new classified question. The route
            # decision controls case association; classification controls its
            # category. The intake service remains the sole persistence point.
            classification = self.intake_service.classifier.classify(message)
            category_id = None if classification.is_unknown else classification.top1_category_id
            if decision.action == "new_case":
                if category_id is None:
                    current = self.intake_service.set_pending_case_restatement(participant_id, session_id)
                    return ConversationTurnResult(
                        current, None, decision,
                        clarification=_clarification_with_restatement(
                            "我還不確定這個新事件屬於哪一類。"
                        ),
                    )
                if not self.intake_service.registry.get(category_id).fields:
                    current = self.intake_service.set_pending_case_restatement(participant_id, session_id)
                    return ConversationTurnResult(
                        current, category_id, decision,
                        clarification=_clarification_with_restatement(
                            "這類問題不需要建立個人事件資料。"
                        ),
                    )
            result = self._intake(
                participant_id=participant_id,
                message=message,
                session_id=session_id,
                new_case=decision.action == "new_case",
                clear_case=decision.action == "no_case",
                correct_fields=correct_fields,
                classification=classification,
            )
            return ConversationTurnResult(
                result.session, category_id, decision, result, result.clarification,
            )

        classification = self.intake_service.classifier.classify(message)
        category_id = None if classification.is_unknown else classification.top1_category_id
        if category_id is None:
            if clear_case:
                result = self._intake(
                    participant_id=participant_id, message=message, session_id=session_id,
                    clear_case=True, new_question=new_question, correct_fields=correct_fields,
                    classification=classification,
                )
                return ConversationTurnResult(result.session, None, None, result, result.clarification)
            # An unknown or very short answer must not create a case or attach
            # facts to the active case. Explicit clear_case was handled above.
            current = self.intake_service.set_pending_case_restatement(participant_id, session_id)
            return ConversationTurnResult(
                current, None, None,
                clarification=_clarification_with_restatement(
                    "我還不確定您想詢問的類別或要描述的事件。"
                ),
            )

        # Explicitly clearing the case association takes precedence over an
        # automatic route decision for this turn.
        if clear_case:
            result = self._intake(
                participant_id=participant_id, message=message, session_id=session_id,
                clear_case=True, new_question=new_question, correct_fields=correct_fields,
                classification=classification,
            )
            return ConversationTurnResult(result.session, category_id, None, result, result.clarification)

        category = self.intake_service.registry.get(category_id)
        request = CaseRouteRequest(message=message, category=category, session=current)
        decision = parse_case_route(self.case_router.route(request), request)
        if decision.action == "clarify":
            clarification = _clarification_with_restatement(decision.clarification_question)
            decision = CaseRouteDecision("clarify", clarification)
            current = self.intake_service.set_pending_case_restatement(participant_id, session_id)
            return ConversationTurnResult(
                current, category_id, decision, clarification=clarification,
            )
        if decision.action == "continue_case" and current.active_case_id is None:
            # Defensive check in addition to parser validation, so a custom
            # parser/port cannot accidentally continue without owned state.
            return ConversationTurnResult(
                current, category_id, decision,
                clarification="目前沒有可延續的個人事件資料，請補充事件內容或重新描述問題。",
            )

        result = self._intake(
            participant_id=participant_id,
            message=message,
            session_id=session_id,
            new_case=decision.action == "new_case",
            # new_case already starts a fresh question; process_turn treats the
            # two flags as mutually exclusive.
            new_question=new_question and decision.action != "new_case",
            clear_case=decision.action == "no_case",
            correct_fields=correct_fields,
            classification=classification,
        )
        return ConversationTurnResult(result.session, category_id, decision, result, result.clarification)

    def _process_restatement(
        self,
        *,
        participant_id: str,
        message: str,
        session_id: str,
        current: SessionState,
        clear_case: bool,
        correct_fields: tuple[str, ...],
    ) -> ConversationTurnResult:
        """Require a full re-description after uncertain case association."""
        classification = self.intake_service.classifier.classify(message)
        category_id = None if classification.is_unknown else classification.top1_category_id
        if clear_case:
            result = self._intake(
                participant_id=participant_id, message=message, session_id=session_id,
                clear_case=True, correct_fields=correct_fields, classification=classification,
            )
            return ConversationTurnResult(result.session, category_id, None, result, result.clarification)
        if category_id is None:
            return ConversationTurnResult(
                current, None, None,
                clarification=_clarification_with_restatement(
                    "我還不確定您描述的完整事件屬於哪一類。"
                ),
            )

        category = self.intake_service.registry.get(category_id)
        request = CaseRouteRequest(message=message, category=category, session=current)
        decision = parse_case_route(self.case_router.route(request), request)
        if decision.action == "clarify":
            clarification = _clarification_with_restatement(decision.clarification_question)
            decision = CaseRouteDecision("clarify", clarification)
            return ConversationTurnResult(
                current, category_id, decision, clarification=clarification,
            )
        if decision.action == "new_case" and not category.fields:
            return ConversationTurnResult(
                current, category_id, decision,
                clarification=_clarification_with_restatement(
                    "這類問題不需要建立個人事件資料。"
                ),
            )

        result = self._intake(
            participant_id=participant_id,
            message=message,
            session_id=session_id,
            new_case=decision.action == "new_case",
            new_question=decision.action == "continue_case",
            clear_case=decision.action == "no_case",
            correct_fields=correct_fields,
            classification=classification,
        )
        return ConversationTurnResult(result.session, category_id, decision, result, result.clarification)

    def _intake(self, **kwargs) -> IntakeTurnResult:
        return self.intake_service.process_turn(**kwargs)


__all__ = ["ConversationOrchestrator", "ConversationTurnResult"]


def _clarification_with_restatement(question: str | None) -> str:
    prefix = question.strip() if isinstance(question, str) and question.strip() else "請補充說明。"
    return f"{prefix} {_RESTATEMENT_REMINDER}"
