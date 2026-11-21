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
