"""Command-line entry point for the Clinical Warrant PoC."""

from __future__ import annotations

import argparse
from collections.abc import Sequence

from clinical_warrant import __version__


def build_parser() -> argparse.ArgumentParser:
    """Build the command-line parser without running any application logic."""
    parser = argparse.ArgumentParser(
        prog="clinical-warrant",
        description="Clinical Warrant PoC command-line interface.",
        epilog=(
            "The decide and evaluate commands are reserved for later project "
            "stages and are not implemented yet."
        ),
    )
    parser.add_argument(
        "--version", action="version", version=f"%(prog)s {__version__}"
    )
    commands = parser.add_subparsers(dest="command")

    decide = commands.add_parser("decide", help="Run a decision (not implemented yet)")
    decide.add_argument("--input", required=True, metavar="FILE")

    evaluate = commands.add_parser(
        "evaluate", help="Evaluate scenarios (not implemented yet)"
    )
    evaluate.add_argument("--input", required=True, metavar="FILE")
    evaluate.add_argument("--output", required=True, metavar="DIR")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Display CLI help or report that a future-stage command is unavailable."""
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command is None:
        parser.print_help()
        return 0

    parser.error(
        f"'{args.command}' is not implemented yet; no decision or evaluation was run."
    )
