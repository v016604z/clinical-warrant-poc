"""Command-line entry point for the Clinical Warrant PoC."""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from pathlib import Path
import sys
from typing import Callable

from clinical_warrant import __version__
from clinical_warrant.classifier import DEFAULT_THRESHOLD, ClassifierError, QuestionClassifier
from clinical_warrant.contracts import ContractError, DecisionInput, DecisionResult
from clinical_warrant.warrant import WarrantEngine, WarrantError


def build_parser() -> argparse.ArgumentParser:
    """Build the command-line parser without running any application logic."""
    parser = argparse.ArgumentParser(
        prog="clinical-warrant",
        description="Clinical Warrant PoC command-line interface.",
        epilog="evaluate is reserved for a later project stage and is not implemented yet.",
    )
    parser.add_argument(
        "--version", action="version", version=f"%(prog)s {__version__}"
    )
    commands = parser.add_subparsers(dest="command")

    decide = commands.add_parser("decide", help="Check one request and return a decision")
    decide.add_argument("--input", required=True, metavar="FILE")
    decide.add_argument("--threshold", type=float, default=DEFAULT_THRESHOLD)

    evaluate = commands.add_parser(
        "evaluate", help="Evaluate scenarios (not implemented yet)"
    )
    evaluate.add_argument("--input", required=True, metavar="FILE")
    evaluate.add_argument("--output", required=True, metavar="DIR")
    return parser


def main(
    argv: Sequence[str] | None = None,
    *,
    classifier_factory: Callable[..., QuestionClassifier] | None = None,
) -> int:
    """Run ``decide`` or report that the future-stage evaluator is unavailable."""
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command is None:
        parser.print_help()
        return 0

    if args.command == "evaluate":
        parser.error("'evaluate' is not implemented yet; no evaluation was run.")

    try:
        request = DecisionInput.from_json(
            Path(args.input).read_text(encoding="utf-8-sig")
        )
    except (OSError, UnicodeError, ContractError) as error:
        print(f"error: invalid input: {error}", file=sys.stderr)
        return 2

    factory = classifier_factory or QuestionClassifier.from_pretrained
    try:
        classifier = factory(threshold=args.threshold)
        result = WarrantEngine(classifier).decide(request)
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
