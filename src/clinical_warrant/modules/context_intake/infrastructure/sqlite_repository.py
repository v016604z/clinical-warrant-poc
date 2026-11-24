"""SQLite persistence for Context Intake session state."""

from __future__ import annotations

import json
import sqlite3
from typing import Any
from uuid import uuid4

from clinical_warrant.modules.context_intake.domain.classification import IntakeClassificationResult
from clinical_warrant.modules.context_intake.domain.state import (
    AttributeChange,
    AttributeValue,
    CaseState,
    PendingConflict,
    PendingQuestion,
    SessionState,
    TurnEvent,
)


SCHEMA_VERSION = 2

_SCHEMA = (
    """CREATE TABLE participants (
        participant_id TEXT PRIMARY KEY
    )""",
    """CREATE TABLE case_contexts (
        case_id TEXT PRIMARY KEY,
        participant_id TEXT NOT NULL REFERENCES participants(participant_id),
        UNIQUE (participant_id, case_id)
    )""",
    """CREATE TABLE sessions (
        session_id TEXT PRIMARY KEY,
        participant_id TEXT NOT NULL REFERENCES participants(participant_id),
        active_case_id TEXT,
        active_category_id TEXT,
        active_catalog_version TEXT,
        pending_question_json TEXT,
        pending_conflict_json TEXT,
        awaiting_case_restatement INTEGER NOT NULL DEFAULT 0 CHECK (awaiting_case_restatement IN (0, 1)),
        UNIQUE (participant_id, session_id),
        FOREIGN KEY (participant_id, active_case_id)
            REFERENCES case_contexts(participant_id, case_id)
            DEFERRABLE INITIALLY DEFERRED
    )""",
    """CREATE TABLE turn_events (
        turn_id TEXT PRIMARY KEY,
        turn_order INTEGER NOT NULL,
        session_id TEXT NOT NULL,
        participant_id TEXT NOT NULL,
        case_id TEXT,
        category_id TEXT,
        category_source TEXT NOT NULL,
        catalog_version TEXT NOT NULL,
        top1_category_id TEXT,
        top1_similarity REAL,
        top2_category_id TEXT,
        top2_similarity REAL,
        is_unknown INTEGER,
        model_id TEXT,
        model_revision TEXT,
        selected_fields_json TEXT NOT NULL,
        FOREIGN KEY (participant_id, session_id)
            REFERENCES sessions(participant_id, session_id) ON DELETE CASCADE,
        FOREIGN KEY (participant_id, case_id)
            REFERENCES case_contexts(participant_id, case_id)
            DEFERRABLE INITIALLY DEFERRED,
        UNIQUE (session_id, turn_order),
        UNIQUE (turn_id, case_id)
    )""",
    """CREATE TABLE case_attributes (
        case_id TEXT NOT NULL REFERENCES case_contexts(case_id) ON DELETE CASCADE,
        field_key TEXT NOT NULL,
        value_type TEXT NOT NULL CHECK (value_type IN ('str', 'int', 'bool')),
        value_json TEXT NOT NULL,
        source_turn_id TEXT NOT NULL,
        PRIMARY KEY (case_id, field_key),
        FOREIGN KEY (source_turn_id, case_id)
            REFERENCES turn_events(turn_id, case_id)
    )""",
    """CREATE TABLE attribute_history (
        history_id TEXT PRIMARY KEY,
        case_id TEXT NOT NULL,
        field_key TEXT NOT NULL,
        change_order INTEGER NOT NULL,
        action TEXT NOT NULL CHECK (action IN ('add', 'correct', 'confirm')),
        old_value_type TEXT CHECK (old_value_type IS NULL OR old_value_type IN ('str', 'int', 'bool')),
        old_value_json TEXT,
        new_value_type TEXT NOT NULL CHECK (new_value_type IN ('str', 'int', 'bool')),
        new_value_json TEXT NOT NULL,
        source_turn_id TEXT NOT NULL,
        UNIQUE (case_id, field_key, source_turn_id, action),
        UNIQUE (case_id, field_key, change_order),
        FOREIGN KEY (case_id, field_key)
            REFERENCES case_attributes(case_id, field_key) ON DELETE CASCADE,
        FOREIGN KEY (source_turn_id, case_id)
            REFERENCES turn_events(turn_id, case_id)
    )""",
)


def initialize_database(connection: sqlite3.Connection) -> None:
    """Create the current schema or transactionally upgrade the supported v1 schema."""
    connection.execute("PRAGMA foreign_keys = ON")
    if connection.execute("PRAGMA foreign_keys").fetchone()[0] != 1:
        raise RuntimeError("SQLite foreign key enforcement must be enabled outside a transaction")
    version = connection.execute("PRAGMA user_version").fetchone()[0]
    if version == SCHEMA_VERSION:
        return
    if version not in (0, 1):
        raise RuntimeError(f"unsupported Context Intake schema version: {version}")
    connection.execute("BEGIN IMMEDIATE")
    try:
        if version == 0:
            for statement in _SCHEMA:
                connection.execute(statement)
        else:
            connection.execute(
                "ALTER TABLE sessions ADD COLUMN awaiting_case_restatement "
                "INTEGER NOT NULL DEFAULT 0 CHECK (awaiting_case_restatement IN (0, 1))"
            )
        connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
        connection.commit()
    except Exception:
        connection.rollback()
        raise


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _scalar(value: str | int | bool | None) -> tuple[str | None, str | None]:
    if value is None:
        return None, None
    kind = "bool" if type(value) is bool else "int" if type(value) is int else "str"
    return kind, _json(value)


def _decode_scalar(kind: str | None, raw: str | None) -> str | int | bool | None:
    if kind is None:
        return None
    value = json.loads(raw)
    expected = {"bool": bool, "int": int, "str": str}[kind]
    if type(value) is not expected:
        raise ValueError(f"stored scalar type mismatch: {kind}")
    return value


def _row_dict(cursor: sqlite3.Cursor, row: tuple[Any, ...]) -> dict[str, Any]:
    return dict(zip((col[0] for col in cursor.description), row))


def _load_case(db: sqlite3.Connection, case_id: str, participant_id: str) -> CaseState:
    attr_cur = db.execute("SELECT * FROM case_attributes WHERE case_id = ?", (case_id,))
    attributes: dict[str, AttributeValue] = {}
    for raw_attr in attr_cur.fetchall():
        attr = _row_dict(attr_cur, raw_attr)
        hist_cur = db.execute(
            "SELECT * FROM attribute_history WHERE case_id = ? AND field_key = ? ORDER BY change_order",
            (case_id, attr["field_key"]),
        )
        history = tuple(AttributeChange(
            item["action"],
            _decode_scalar(item["old_value_type"], item["old_value_json"]),
            _decode_scalar(item["new_value_type"], item["new_value_json"]),
            item["source_turn_id"],
        ) for item in map(lambda r: _row_dict(hist_cur, r), hist_cur.fetchall()))
        attributes[attr["field_key"]] = AttributeValue(
            _decode_scalar(attr["value_type"], attr["value_json"]),
            attr["source_turn_id"], history,
        )
    return CaseState(case_id, participant_id, attributes)


def _pending_question_json(value: PendingQuestion | None) -> str | None:
    return None if value is None else _json({
        "case_id": value.case_id, "category_id": value.category_id,
        "field_key": value.field_key, "question": value.question,
    })


def _pending_conflict_json(value: PendingConflict | None) -> str | None:
    if value is None:
        return None
    old_type, old_json = _scalar(value.old_value)
    new_type, new_json = _scalar(value.candidate_value)
    return _json({
        "case_id": value.case_id, "category_id": value.category_id,
        "field_key": value.field_key, "old_type": old_type, "old": old_json,
        "candidate_type": new_type, "candidate": new_json,
        "old_source_turn_id": value.old_source_turn_id,
        "candidate_source_turn_id": value.candidate_source_turn_id,
    })


class SQLiteContextIntakeRepository:
    """Store and reconstruct immutable Context Intake state on a caller connection."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection
        initialize_database(connection)

    def save_session(self, session: SessionState) -> None:
        db = self.connection
        db.execute("BEGIN IMMEDIATE")
        try:
            existing = db.execute(
                "SELECT participant_id FROM sessions WHERE session_id = ?", (session.session_id,)
            ).fetchone()
            if existing and existing[0] != session.participant_id:
                raise ValueError("an existing session cannot change participant")
            db.execute("INSERT OR IGNORE INTO participants VALUES (?)", (session.participant_id,))

            for case in session.cases.values():
                prior = db.execute(
                    "SELECT participant_id FROM case_contexts WHERE case_id = ?", (case.case_id,)
                ).fetchone()
                if prior and prior[0] != case.participant_id:
                    raise ValueError("an existing case cannot change participant")
                db.execute(
                    "INSERT OR IGNORE INTO case_contexts(case_id, participant_id) VALUES (?, ?)",
                    (case.case_id, case.participant_id),
                )

            active_version = next((
                event.catalog_version for event in reversed(session.turn_events)
                if session.active_category_id is not None
                and event.category_id == session.active_category_id
            ), None)
            db.execute(
                """INSERT INTO sessions (
                    session_id, participant_id, active_case_id, active_category_id,
                    active_catalog_version, pending_question_json, pending_conflict_json,
                    awaiting_case_restatement
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(session_id) DO UPDATE SET
                    active_case_id=excluded.active_case_id,
                    active_category_id=excluded.active_category_id,
                    active_catalog_version=excluded.active_catalog_version,
                    pending_question_json=excluded.pending_question_json,
                    pending_conflict_json=excluded.pending_conflict_json,
                    awaiting_case_restatement=excluded.awaiting_case_restatement""",
                (session.session_id, session.participant_id, session.active_case_id,
                 session.active_category_id, active_version,
                 _pending_question_json(session.pending_question),
                 _pending_conflict_json(session.pending_conflict),
                 int(session.awaiting_case_restatement)),
            )

            expected_events = []
            for turn_order, event in enumerate(session.turn_events):
                classification = event.classification
                values = (
                    event.turn_id, turn_order, session.session_id, session.participant_id,
                    event.case_id, event.category_id, event.category_source, event.catalog_version,
                    classification.top1_category_id if classification else None,
                    classification.top1_similarity if classification else None,
                    classification.top2_category_id if classification else None,
                    classification.top2_similarity if classification else None,
                    int(classification.is_unknown) if classification else None,
                    classification.model_id if classification else None,
                    classification.model_revision if classification else None,
                    _json(event.selected_fields),
                )
                expected_events.append(values)

            existing_events = db.execute(
                "SELECT * FROM turn_events WHERE session_id = ? ORDER BY turn_order",
                (session.session_id,),
            ).fetchall()
            if len(existing_events) > len(expected_events):
                raise ValueError("a stale session snapshot cannot remove persisted turn events")
            for order, stored in enumerate(existing_events):
                actual = tuple(stored)
                if actual != expected_events[order]:
                    raise ValueError("a persisted turn event cannot be changed or reordered")
            for values in expected_events[len(existing_events):]:
                collision = db.execute(
                    "SELECT session_id FROM turn_events WHERE turn_id = ?", (values[0],)
                ).fetchone()
                if collision:
                    raise ValueError("a turn_id is already used by another persisted event")
                db.execute("INSERT INTO turn_events VALUES (" + ",".join("?" for _ in values) + ")", values)

            for case in session.cases.values():
                for field_key, attribute in case.attributes.items():
                    kind, raw = _scalar(attribute.value)
                    stored_history = db.execute(
                        """SELECT change_order, action, old_value_type, old_value_json,
                            new_value_type, new_value_json, source_turn_id
                            FROM attribute_history WHERE case_id=? AND field_key=? ORDER BY change_order""",
                        (case.case_id, field_key),
                    ).fetchall()
                    stored_history = [tuple(row) for row in stored_history]
                    expected_history = []
                    for order, change in enumerate(attribute.history):
                        old_kind, old_raw = _scalar(change.old_value)
                        new_kind, new_raw = _scalar(change.new_value)
                        expected_history.append((order, change.action, old_kind, old_raw,
                                                 new_kind, new_raw, change.source_turn_id))
                    if len(stored_history) > len(expected_history):
                        raise ValueError("a stale case snapshot cannot remove attribute history")
                    if stored_history != expected_history[:len(stored_history)]:
                        raise ValueError("persisted attribute history cannot be changed or reordered")
                    db.execute(
                        """INSERT INTO case_attributes VALUES (?, ?, ?, ?, ?)
                        ON CONFLICT(case_id, field_key) DO UPDATE SET
                            value_type=excluded.value_type,
                            value_json=excluded.value_json,
                            source_turn_id=excluded.source_turn_id""",
                        (case.case_id, field_key, kind, raw, attribute.source_turn_id),
                    )
                    for change_row in expected_history[len(stored_history):]:
                        db.execute(
                            """INSERT INTO attribute_history VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                            (str(uuid4()), case.case_id, field_key, *change_row),
                        )
            db.commit()
        except Exception:
            db.rollback()
            raise

    def load_session(self, session_id: str) -> SessionState | None:
        db = self.connection
        cur = db.execute("SELECT * FROM sessions WHERE session_id = ?", (session_id,))
        raw_session = cur.fetchone()
        if raw_session is None:
            return None
        session = _row_dict(cur, raw_session)

        cases: dict[str, CaseState] = {}
        cur = db.execute("SELECT case_id, participant_id FROM case_contexts WHERE participant_id = ?", (session["participant_id"],))
        for case_id, participant_id in cur.fetchall():
            cases[case_id] = _load_case(db, case_id, participant_id)

        events: list[TurnEvent] = []
        cur = db.execute("SELECT * FROM turn_events WHERE session_id = ? ORDER BY turn_order", (session_id,))
        for raw_event in cur.fetchall():
            row = _row_dict(cur, raw_event)
            classification = None
            if row["top1_category_id"] is not None:
                classification = IntakeClassificationResult(
                    row["top1_category_id"], row["top1_similarity"],
                    row["top2_category_id"], row["top2_similarity"],
                    bool(row["is_unknown"]), row["model_id"], row["model_revision"],
                    row["catalog_version"],
                )
            events.append(TurnEvent(
                row["turn_id"], row["case_id"], row["category_id"],
                row["category_source"], classification,
                tuple(json.loads(row["selected_fields_json"])), row["catalog_version"],
            ))

        pending_question = None
        if session["pending_question_json"]:
            pending_question = PendingQuestion(**json.loads(session["pending_question_json"]))
        pending_conflict = None
        if session["pending_conflict_json"]:
            raw = json.loads(session["pending_conflict_json"])
            pending_conflict = PendingConflict(
                raw["case_id"], raw["category_id"], raw["field_key"],
                _decode_scalar(raw["old_type"], raw["old"]),
                _decode_scalar(raw["candidate_type"], raw["candidate"]),
                raw["old_source_turn_id"], raw["candidate_source_turn_id"],
            )
        return SessionState(
            session["session_id"], session["participant_id"], cases,
            session["active_case_id"], session["active_category_id"],
            pending_question, pending_conflict, tuple(events),
            bool(session["awaiting_case_restatement"]),
        )

    def get_case(self, case_id: str, participant_id: str) -> CaseState | None:
        row = self.connection.execute(
            "SELECT participant_id FROM case_contexts WHERE case_id = ?", (case_id,)
        ).fetchone()
        if row is None or row[0] != participant_id:
            return None
        return _load_case(self.connection, case_id, participant_id)

    def delete_case(self, case_id: str, participant_id: str) -> bool:
        db = self.connection
        db.execute("BEGIN IMMEDIATE")
        try:
            row = db.execute(
                "SELECT participant_id FROM case_contexts WHERE case_id = ?", (case_id,)
            ).fetchone()
            if row is None or row[0] != participant_id:
                db.rollback()
                return False
            owner = row[0]
            db.execute(
                """UPDATE sessions SET active_case_id=NULL, active_category_id=NULL,
                    active_catalog_version=NULL,
                    pending_question_json=NULL, pending_conflict_json=NULL,
                    awaiting_case_restatement=0
                    WHERE participant_id=? AND active_case_id=?""", (owner, case_id)
            )
            db.execute("DELETE FROM case_attributes WHERE case_id=?", (case_id,))
            db.execute(
                "UPDATE turn_events SET case_id=NULL, selected_fields_json='[]' WHERE participant_id=? AND case_id=?",
                (owner, case_id),
            )
            db.execute("DELETE FROM case_contexts WHERE case_id=?", (case_id,))
            db.commit()
            return True
        except Exception:
            db.rollback()
            raise


__all__ = ["SQLiteContextIntakeRepository", "initialize_database", "SCHEMA_VERSION"]
