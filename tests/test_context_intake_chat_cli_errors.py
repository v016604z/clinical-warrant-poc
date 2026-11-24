from types import SimpleNamespace
import sqlite3
from pathlib import Path
from uuid import UUID

from clinical_warrant.interfaces.cli import (
    _show_active_case,
    _show_turn,
    build_parser,
    run_intake_chat,
)
from clinical_warrant.modules.context_intake import load_category_registry
from clinical_warrant.modules.context_intake.domain.state import CaseState, SessionState, TurnEvent
from clinical_warrant.modules.context_intake.domain.classification import IntakeClassificationResult
from clinical_warrant.modules.context_intake.infrastructure.sqlite_repository import (
    SQLiteContextIntakeRepository,
    initialize_database,
)


class _Connection:
    def __init__(self):
        self.closed = False

    def close(self):
        self.closed = True


class _Repository:
    def load_session(self, _session_id):
        raise OSError("private database detail")


def test_session_restore_read_error_is_reported_without_traceback():
    connection = _Connection()
    orchestrator = SimpleNamespace(
        intake_service=SimpleNamespace(repository=_Repository())
    )
    output = []
    args = SimpleNamespace(
        session_id="known-session", participant_id="participant-1",
        db="unused.sqlite", threshold=0.5,
    )

    result = run_intake_chat(
        args,
        runtime_factory=lambda **_kwargs: (orchestrator, connection),
        input_fn=lambda _prompt: (_ for _ in ()).throw(AssertionError("must not start chat")),
        output_fn=output.append,
    )

    assert result == 1
    assert output
    assert "private database detail" not in "\n".join(output)
    assert connection.closed


def test_coverage_display_error_does_not_claim_saved_turn_was_lost():
    output = []
    result = SimpleNamespace(
        category_id="personal_exposure_risk",
        intake_result=None,
        session=SimpleNamespace(active_case_id=None, cases={}, turn_events=()),
        clarification=None,
    )
    category = SimpleNamespace(category_name="Exposure", fields=(object(),))
    registry = SimpleNamespace(get=lambda _category_id: category)

    def broken_coverage(*_args):
        raise RuntimeError("display-only failure")

    _show_turn(result, registry, output.append, broken_coverage)

    coverage_line = next(line for line in output if line.startswith("Coverage:"))
    assert "display-only failure" not in coverage_line
    assert "已成功儲存" in coverage_line
    assert "未儲存" not in coverage_line


def test_active_case_view_hides_cases_without_a_session_turn_event():
    active = SimpleNamespace(attributes={})
    cross_session = SimpleNamespace(attributes={})
    session = SimpleNamespace(
        active_case_id="case-active",
        cases={"case-active": active, "case-from-other-session": cross_session},
        turn_events=(SimpleNamespace(case_id="case-active"),),
    )
    output = []

    _show_active_case(session, output.append)

    assert any("case-active" in line for line in output)
    assert all("case-from-other-session" not in line for line in output)


class _ChatService:
    def __init__(self, repository, registry):
        self.repository = repository
        self.registry = registry
        self.sessions = {}

    def process_turn(self, *, participant_id, session_id, message):
        previous = self.sessions.get(session_id) or self.repository.load_session(session_id)
        turn_number = len(previous.cases) + 1 if previous else 1
        case_id = f"case-{turn_number}"
        category_id = "personal_exposure_risk"
        turn_id = f"turn-{turn_number}"
        case = CaseState(case_id, participant_id).with_attribute(
            "exposure_datetime", f"time-{turn_number}", turn_id
        )
        event = TurnEvent(
            turn_id, case_id, category_id, "classification",
            IntakeClassificationResult(
                category_id, 0.9, "hiv_basics", 0.1, False,
                "fake", "test", self.registry.version,
            ),
            ("exposure_datetime",), self.registry.version,
        )
        cases = dict(previous.cases) if previous else {}
        cases[case_id] = case
        events = (*previous.turn_events, event) if previous else (event,)
        state = SessionState(
            session_id, participant_id, cases, case_id, category_id,
            turn_events=events,
        )
        self.repository.save_session(state)
        self.sessions[session_id] = state
        return SimpleNamespace(
            session=state, category_id=category_id,
            intake_result=SimpleNamespace(extraction=SimpleNamespace(selected_fields=("exposure_datetime",))),
            route_decision=SimpleNamespace(action="new_case"),
            clarification="Please clarify the event." if turn_number == 2 else None,
        )

    def select_case(self, participant_id, session_id, case_id):
        state = self.sessions.get(session_id) or self.repository.load_session(session_id)
        case = state.cases[case_id]
        if case.participant_id != participant_id:
            raise ValueError("foreign case")
        updated = SessionState(
            state.session_id, state.participant_id, state.cases, case_id,
            state.active_category_id, state.pending_question, state.pending_conflict,
            state.turn_events, state.awaiting_case_restatement,
        )
        self.repository.save_session(updated)
        self.sessions[session_id] = updated
        return updated

    def clear_active_case(self, participant_id, session_id):
        state = self.sessions.get(session_id) or self.repository.load_session(session_id)
        updated = SessionState(
            state.session_id, participant_id, state.cases,
            turn_events=state.turn_events,
        )
        self.repository.save_session(updated)
        self.sessions[session_id] = updated
        return updated


class _ChatOrchestrator:
    def __init__(self, service):
        self.intake_service = service

    def process_turn(self, **kwargs):
        return self.intake_service.process_turn(**kwargs)


def _chat_runtime(db_path, threshold):
    connection = sqlite3.connect(db_path)
    initialize_database(connection)
    registry = load_category_registry()
    repository = SQLiteContextIntakeRepository(connection)
    service = _ChatService(repository, registry)
    return _ChatOrchestrator(service), connection


def test_chat_parser_keeps_legacy_commands_and_accepts_chat_options():
    parser = build_parser()
    chat_args = parser.parse_args([
        "intake", "chat", "--participant-id", "p1", "--session-id", "s1",
        "--db", "chat.sqlite", "--threshold", "0.7",
    ])
    demo_args = parser.parse_args(["intake", "demo", "--fixture", "fixture.json"])
    evaluate_args = parser.parse_args([
        "intake", "evaluate", "--input", "fixture.json", "--output", "reports",
    ])

    assert (chat_args.command, chat_args.intake_command) == ("intake", "chat")
    assert chat_args.threshold == 0.7
    assert (demo_args.intake_command, evaluate_args.intake_command) == ("demo", "evaluate")


def test_chat_commands_and_sqlite_session_restore_across_cli_instances(tmp_path: Path):
    db_path = tmp_path / "chat.sqlite"
    output = []
    inputs = iter(["first event", "second event", ":case", ":clear", ":use case-1", ":case", ":exit"])
    args = SimpleNamespace(
        session_id=None, participant_id=None, db=str(db_path), threshold=0.5,
    )
    result = run_intake_chat(
        args, runtime_factory=_chat_runtime,
        input_fn=lambda _prompt: next(inputs), output_fn=output.append,
    )

    assert result == 0
    assert any(line.startswith("Category:") for line in output), output
    assert any(line.startswith("Selected fields:") for line in output)
    assert any(line.startswith("Known fields:") for line in output)
    assert any(line.startswith("Clarification:") for line in output)
    assert any(line.startswith("Coverage:") for line in output)
    assert any("Please clarify the event." in line for line in output)
    assert any("case-2" in line for line in output)
    participant_id = next(line.split(": ", 1)[1] for line in output if line.startswith("Participant ID:"))
    session_id = next(line.split(": ", 1)[1] for line in output if line.startswith("Session ID:"))
    UUID(session_id)
    assert participant_id.startswith("anon-")
    assert any("case-1" in line for line in output)

    restored_output = []
    restored_inputs = iter([":case", ":exit"])
    restored_args = SimpleNamespace(
        session_id=session_id, participant_id=participant_id,
        db=str(db_path), threshold=0.5,
    )
    assert run_intake_chat(
        restored_args, runtime_factory=_chat_runtime,
        input_fn=lambda _prompt: next(restored_inputs), output_fn=restored_output.append,
    ) == 0
    assert any("exposure_datetime=time-1" in line for line in restored_output)

    connection = sqlite3.connect(db_path)
    saved = SQLiteContextIntakeRepository(connection).load_session(session_id)
    assert saved.active_case_id == "case-1"
    assert len(saved.cases) == 2
    connection.close()
