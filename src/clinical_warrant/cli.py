"""Backward-compatible CLI import path and console-script target."""

from clinical_warrant.interfaces.cli import _evaluate, _threshold, build_parser, main

__all__ = ["build_parser", "main"]
