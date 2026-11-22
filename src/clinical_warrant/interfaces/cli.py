"""Command-line entry point for the Clinical Warrant PoC."""

from __future__ import annotations

import argparse
from collections.abc import Sequence
import json
import math
from pathlib import Path
import sys
from typing import Callable

from clinical_warrant import __version__
from clinical_warrant.bootstrap.composition import (
    build_warrant_engine,
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
    return parser


def main(
    argv: Sequence[str] | None = None,
    *,
    classifier_factory: Callable[..., QuestionClassifier] | None = None,
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
