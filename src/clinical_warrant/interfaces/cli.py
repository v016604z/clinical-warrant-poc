"""Command-line entry point for the Clinical Warrant PoC."""

from __future__ import annotations

import argparse
from collections.abc import Sequence
import json
import math
from pathlib import Path
import sqlite3
import sys
from typing import Callable
from uuid import uuid4

from clinical_warrant import __version__
from clinical_warrant.bootstrap.composition import (
    build_warrant_engine,
    build_context_intake_chat_runtime,
    evaluate_scenarios,
    hash_dataset,
    kb_build,
    kb_merge,
    kb_validate,
)
from clinical_warrant.modules.classification import (
    DEFAULT_THRESHOLD,
    ClassifierError,
    QuestionClassifier,
)
from clinical_warrant.modules.decision import WarrantError
from clinical_warrant.modules.evaluation import (
    EvaluationError,
    load_evaluation_jsonl,
)
from clinical_warrant.modules.knowledge_base.infrastructure.run_io import RunIOError
from clinical_warrant.modules.context_intake.application.simulation import (
    FixtureError,
    evaluate_fixture,
    load_conversation_fixture,
)
from clinical_warrant.modules.context_intake import load_category_registry
from clinical_warrant.modules.evaluation.infrastructure.report_writer import publish_report
from clinical_warrant.shared.domain.contracts import ContractError, DecisionInput, DecisionResult


def build_parser() -> argparse.ArgumentParser:
    """Build the command-line parser without running any application logic."""
    parser = argparse.ArgumentParser(
        prog="clinical-warrant",
        description="Clinical Warrant PoC command-line interface.",
        epilog="evaluate runs a user-provided labeled JSONL scenario dataset.",
    )
    parser.add_argument(
        "--version", action="version", version=f"%(prog)s {__version__}"
    )
    commands = parser.add_subparsers(dest="command")

    decide = commands.add_parser("decide", help="Check one request and return a decision")
    decide.add_argument("--input", required=True, metavar="FILE")
    decide.add_argument("--threshold", type=float, default=DEFAULT_THRESHOLD)

    evaluate = commands.add_parser("evaluate", help="Evaluate a JSONL scenario dataset")
    evaluate.add_argument("--input", required=True, metavar="FILE")
    evaluate.add_argument("--output", required=True, metavar="DIR")
    evaluate.add_argument("--threshold", type=_threshold, default=DEFAULT_THRESHOLD)

    kb = commands.add_parser("kb", help="Build and inspect a local RAG knowledge base")
    kb_commands = kb.add_subparsers(dest="kb_command", required=True)
    build = kb_commands.add_parser("build", help="Build an immutable KB run")
    build.add_argument("--adapter", choices=("cdc_qa", "generic_jsonl"), required=True)
    build.add_argument("--input", required=True, metavar="FILE")
    build.add_argument("--output-dir", required=True, metavar="DIR")
    build.add_argument("--source-root", metavar="DIR")
    build.add_argument("--intended-use")
    build.add_argument("--usage-decision", choices=("allowed", "unknown", "prohibited"))
    build.add_argument("--dataset-id")
    build.add_argument("--attribution")
    build.add_argument("--rights-config", metavar="FILE")
    build.add_argument("--mapping", metavar="FILE")
    build.add_argument("--as-of", required=True, metavar="YYYY-MM-DD")
    build.add_argument("--stale-after-days", type=_nonnegative_int, required=True)
    build.add_argument("--require-time-sensitive-review", action="store_true")
    build.add_argument("--max-chars", type=_positive_int, default=1200)
    build.add_argument("--overlap-chars", type=_nonnegative_int, default=100)
    build.add_argument("--strict", action="store_true", help="Fail the build if any record is rejected (default: false)")

    merge = kb_commands.add_parser("merge", help="Merge completed KB runs")
    merge.add_argument("--inputs", nargs="+", required=True, metavar="DIR")
    merge.add_argument("--output-dir", required=True, metavar="DIR")
    merge.add_argument("--strict", action="store_true")

    validate = kb_commands.add_parser("validate", help="Validate a completed KB run")
    validate.add_argument("--dataset", required=True, metavar="DIR")

    intake = commands.add_parser("intake", help="Run synthetic Context Intake demonstrations")
    intake_commands = intake.add_subparsers(dest="intake_command", required=True)
    demo = intake_commands.add_parser("demo", help="Replay an offline multi-turn fixture")
    demo.add_argument("--fixture", required=True, metavar="FILE")
    demo.add_argument("--step", action="store_true", help="Pause after each fixture turn for guided review")
    intake_eval = intake_commands.add_parser("evaluate", help="Evaluate an offline multi-turn fixture")
    intake_eval.add_argument("--input", required=True, metavar="FILE")
    intake_eval.add_argument("--output", required=True, metavar="DIR")
    chat = intake_commands.add_parser("chat", help="Start a live Context Intake conversation")
    chat.add_argument("--participant-id", help="Anonymous participant ID (generated when omitted)")
    chat.add_argument("--session-id", help="Resume this saved session")
    chat.add_argument("--db", default="runtime-data/context-intake.sqlite3", metavar="FILE")
    chat.add_argument("--threshold", type=_threshold, default=0.5)
    return parser


def main(
    argv: Sequence[str] | None = None,
    *,
    classifier_factory: Callable[..., QuestionClassifier] | None = None,
    chat_runtime_factory: Callable[..., tuple[object, sqlite3.Connection]] | None = None,
) -> int:
    """Run one decision or evaluate a complete JSONL dataset."""
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command is None:
        parser.print_help()
        return 0

    if args.command == "kb":
        try:
            if args.kb_command == "build":
                _validate_kb_build_args(args, parser)
                result = kb_build(args)
            elif args.kb_command == "merge":
                result = kb_merge(args)
            else:
                result = kb_validate(args)
        except (ValueError, json.JSONDecodeError) as error:
            diagnostic = ""
            if args.kb_command in {"build", "merge"}:
                target = Path(args.output_dir)
                if (target / "failure.json").is_file():
                    diagnostic = f" (diagnostics: {target})"
            print(f"error: invalid knowledge base contract: {error}{diagnostic}", file=sys.stderr)
            return 2
        except RunIOError as error:
            print(f"error: invalid knowledge base run: {error}", file=sys.stderr)
            return 2
        except (OSError, RuntimeError) as error:
            diagnostic = ""
            if args.kb_command in {"build", "merge"}:
                target = Path(args.output_dir)
                if (target / "failure.json").is_file():
                    diagnostic = f" (diagnostics: {target})"
            print(f"error: knowledge base operation failed: {error}{diagnostic}", file=sys.stderr)
            return 1
        print(json.dumps(result, ensure_ascii=False, separators=(",", ":")))
        return 0

    if args.command == "intake":
        if args.intake_command == "chat":
            return run_intake_chat(args, runtime_factory=chat_runtime_factory)
        try:
            raw, fixture = load_conversation_fixture(
                args.fixture if args.intake_command == "demo" else args.input
            )
            registry = load_category_registry()
            if args.intake_command == "demo":
                def show_turn(turn):
                    if args.step:
                        print(json.dumps(turn, ensure_ascii=False, separators=(",", ":")), flush=True)
                        input("按 Enter 繼續下一個 fixture 回合…")
                report = evaluate_fixture(raw, fixture, registry, on_turn=show_turn)
                print(json.dumps({
                    "notice": "synthetic offline simulation; not a medical AI assessment",
                    "scenario_id": report["metadata"]["scenario_id"],
                    "turns": report["predictions"], "metrics": report["metrics"],
                }, ensure_ascii=False, separators=(",", ":")))
                return 0
            from datetime import datetime, timezone
            from uuid import uuid4
            report = evaluate_fixture(raw, fixture, registry)
            now = datetime.now(timezone.utc)
            run_id = f"{now.strftime('%Y%m%dT%H%M%SZ')}-{uuid4().hex[:10]}"
            report["metadata"]["run_id"] = run_id
            published = publish_report({
                "run_id": run_id,
                "summary": {key: value for key, value in report.items()
                            if key not in {"predictions", "errors"}},
                "predictions": report["predictions"],
                "errors": report["errors"],
            }, args.output)
            print(json.dumps(published, ensure_ascii=False, separators=(",", ":")))
            return 0
        except (OSError, FixtureError, ValueError) as error:
            print(f"error: invalid intake fixture or evaluation: {error}", file=sys.stderr)
            return 2
        except Exception as error:
            print(f"error: intake evaluation failed: {error}", file=sys.stderr)
            return 1

    if args.command == "evaluate":
        return _evaluate(args, classifier_factory=classifier_factory)

    try:
        request = DecisionInput.from_json(
            Path(args.input).read_text(encoding="utf-8-sig")
        )
    except (OSError, UnicodeError, ContractError) as error:
        print(f"error: invalid input: {error}", file=sys.stderr)
        return 2

    try:
        engine = build_warrant_engine(
            threshold=args.threshold,
            classifier_factory=classifier_factory,
        )
        result = engine.decide(request)
    except (ClassifierError, WarrantError, ValueError) as error:
        print(f"error: decision failed: {error}", file=sys.stderr)
        return 1
    except Exception as error:
        print(f"error: decision failed: {error}", file=sys.stderr)
        return 1

    if not isinstance(result, DecisionResult):
        print("error: decision engine returned an invalid result", file=sys.stderr)
        return 1
    print(result.to_json())
    return 0


def run_intake_chat(
    args,
    *,
    runtime_factory: Callable[..., tuple[object, sqlite3.Connection]] | None = None,
    input_fn: Callable[[str], str] | None = None,
    output_fn: Callable[[str], object] | None = None,
) -> int:
    """Run the interactive CLI without retaining original messages."""
    from clinical_warrant.modules.context_intake.application.coverage import calculate_case_coverage

    input_fn = input if input_fn is None else input_fn
    output_fn = print if output_fn is None else output_fn
    if args.session_id and not args.participant_id:
        output_fn("恢復 Session 時必須同時提供 Participant ID。")
        return 2
    factory = build_context_intake_chat_runtime if runtime_factory is None else runtime_factory
    try:
        orchestrator, connection = factory(db_path=args.db, threshold=args.threshold)
    except Exception:
        output_fn("無法啟動對話服務，請檢查本機設定與 API 連線。")
        return 1

    service = orchestrator.intake_service
    repository = service.repository
    try:
        try:
            restored = repository.load_session(args.session_id) if args.session_id else None
        except Exception:
            output_fn("無法讀取 Session；請確認本機資料庫可讀且版本相容。")
            return 1
        if args.session_id and restored is None:
            output_fn("找不到指定的 Session ID。")
            return 2
        if restored is not None and args.participant_id != restored.participant_id:
            output_fn("指定的 Participant ID 與 Session 不符。")
            return 2
        participant_id = args.participant_id or f"anon-{uuid4()}"
        session_id = args.session_id or str(uuid4())
        output_fn(f"Participant ID: {participant_id}")
        output_fn(f"Session ID: {session_id}")
        output_fn("輸入問題開始對話；`:case` 查看個案、`:use ID` 切換、`:clear` 清除目前個案、`:exit` 離開。")
        if restored is not None:
            _show_active_case(restored, output_fn)

        while True:
            try:
                message = input_fn("你> ").strip()
            except (EOFError, KeyboardInterrupt):
                output_fn("已結束對話。")
                return 0
            if not message:
                continue
            command, _, argument = message.partition(" ")
            command = command.lower().replace("/", ":", 1) if message.startswith("/") else command.lower()
            if command in {":exit", ":quit"}:
                output_fn("已結束對話。")
                return 0
            if command in {":help", ":?"}:
                output_fn("命令：`:case`、`:use CASE_ID`、`:clear`、`:exit`。其他輸入會作為對話內容。")
                continue
            if command == ":case":
                try:
                    current = service.sessions.get(session_id) or repository.load_session(session_id)
                except Exception:
                    output_fn("無法讀取 Session；請確認本機資料庫可讀且版本相容。")
                    continue
                _show_active_case(current, output_fn)
                continue
            if command == ":use":
                if not argument.strip():
                    output_fn("用法：`:use CASE_ID`")
                    continue
                try:
                    selected = service.select_case(participant_id, session_id, argument.strip())
                except Exception:
                    output_fn("無法切換個案；請確認 Case ID 屬於此 Participant。")
                    continue
                output_fn(f"已切換至 Case {selected.active_case_id}。")
                _show_active_case(selected, output_fn)
                continue
            if command == ":clear":
                try:
                    cleared = service.clear_active_case(participant_id, session_id)
                except Exception:
                    output_fn("無法清除目前個案關聯。")
                    continue
                output_fn("已清除目前個案關聯；既有 Case 資料仍保留。")
                _show_active_case(cleared, output_fn)
                continue

            try:
                result = orchestrator.process_turn(
                    participant_id=participant_id, session_id=session_id, message=message
                )
            except Exception:
                output_fn("本輪處理失敗，未儲存不完整資料；請稍後重試。")
                continue
            _show_turn(result, service.registry, output_fn, calculate_case_coverage)

    finally:
        connection.close()


def _show_active_case(session, output_fn: Callable[[str], object]) -> None:
    if session is None:
        output_fn("目前沒有已儲存的 Session 或 Case。")
        return
    session_case_ids = {
        event.case_id for event in session.turn_events if event.case_id is not None
    }
    if session.active_case_id is not None:
        session_case_ids.add(session.active_case_id)
    output_fn(f"目前 Case: {session.active_case_id or '無'}")
    if session.active_case_id is None:
        available = sorted(session_case_ids & session.cases.keys())
        if available:
            output_fn("可切換的 Case: " + ", ".join(available))
        return
    case = session.cases[session.active_case_id]
    if not case.attributes:
        output_fn("已知欄位: 無")
    else:
        known = ", ".join(f"{key}={value.value}" for key, value in sorted(case.attributes.items()))
        output_fn(f"已知欄位: {known}")
    others = sorted((session_case_ids & session.cases.keys()) - {session.active_case_id})
    if others:
        output_fn("其他 Case: " + ", ".join(others))


def _show_turn(result, registry, output_fn, calculate_coverage) -> None:
    category_id = result.category_id
    if category_id is None:
        output_fn("Category: 未分類")
    else:
        category = registry.get(category_id)
        output_fn(f"Category: {category.category_name} ({category_id})")
    intake = result.intake_result
    selected = intake.extraction.selected_fields if intake and intake.extraction else ()
    output_fn("Selected fields: " + (", ".join(selected) if selected else "無"))
    session = result.session
    case = session.cases.get(session.active_case_id) if session.active_case_id else None
    known = ", ".join(f"{key}={value.value}" for key, value in sorted(case.attributes.items())) if case else "無"
    output_fn("Known fields: " + known)
    output_fn("Clarification: " + (result.clarification or "無"))
    if category_id is not None and registry.get(category_id).fields:
        try:
            coverage = calculate_coverage(registry, case, session.turn_events, category_id)
            rate = "不可計算" if coverage.coverage_rate is None else f"{coverage.coverage_rate:.0%}"
            output_fn(
                "Coverage: selected {}/{}; known {}/{}; selected-known {}/{}; rate {}".format(
                    coverage.selected_count, coverage.catalog_count,
                    coverage.known_count, coverage.catalog_count,
                    coverage.selected_known_count, coverage.catalog_count, rate,
                )
            )
        except Exception:
            output_fn("Coverage: 無法計算（本輪已成功儲存）")
    else:
        output_fn("Coverage: 不適用")


def _evaluate(args, *, classifier_factory: Callable[..., QuestionClassifier] | None) -> int:
    try:
        raw_bytes = Path(args.input).read_bytes()
        text = raw_bytes.decode("utf-8-sig")
        cases = load_evaluation_jsonl(text)
    except (OSError, UnicodeError, EvaluationError) as error:
        print(f"error: invalid evaluation input: {error}", file=sys.stderr)
        return 2

    try:
        engine = build_warrant_engine(
            threshold=args.threshold,
            classifier_factory=classifier_factory,
        )
        run = evaluate_scenarios(
            cases,
            engine,
            args.output,
            threshold=args.threshold,
            dataset_sha256=hash_dataset(raw_bytes),
        )
    except Exception as error:
        print(f"error: evaluation failed: {error}", file=sys.stderr)
        return 1

    print(
        json.dumps(
            {
                "run_id": run["run_id"],
                "run_dir": run["run_dir"],
                "total_cases": run["summary"]["total_cases"],
                "metrics": run["summary"]["metrics"],
            },
            ensure_ascii=True,
            separators=(",", ":"),
        )
    )
    return 0


def _threshold(value: str) -> float:
    try:
        threshold = float(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("threshold must be a finite number from -1 to 1") from error
    if not math.isfinite(threshold) or not -1.0 <= threshold <= 1.0:
        raise argparse.ArgumentTypeError("threshold must be a finite number from -1 to 1")
    return threshold


def _positive_int(value: str) -> int:
    result = _nonnegative_int(value)
    if result == 0:
        raise argparse.ArgumentTypeError("value must be greater than zero")
    return result


def _nonnegative_int(value: str) -> int:
    try:
        result = int(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("value must be a non-negative integer") from error
    if result < 0:
        raise argparse.ArgumentTypeError("value must be a non-negative integer")
    return result


def _validate_kb_build_args(args, parser) -> None:
    if args.adapter == "cdc_qa":
        missing = [name for name in ("source_root", "intended_use", "usage_decision") if not getattr(args, name)]
        if missing:
            parser.error("kb build --adapter cdc_qa requires --" + " --".join(item.replace("_", "-") for item in missing))
        if args.dataset_id or args.attribution or args.rights_config:
            parser.error("CDC adapter does not accept generic rights options")
    else:
        missing = [name for name in ("dataset_id", "attribution", "rights_config") if not getattr(args, name)]
        if missing:
            parser.error("kb build --adapter generic_jsonl requires --" + " --".join(item.replace("_", "-") for item in missing))
        if args.source_root or args.intended_use or args.usage_decision:
            parser.error("generic_jsonl adapter does not accept CDC options")
    from datetime import date
    try:
        if date.fromisoformat(args.as_of).isoformat() != args.as_of:
            raise ValueError
    except ValueError:
        parser.error("--as-of must be a valid YYYY-MM-DD date")
    if args.overlap_chars >= args.max_chars:
        parser.error("--overlap-chars must be less than --max-chars")
