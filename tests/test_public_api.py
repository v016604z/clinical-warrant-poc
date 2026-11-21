"""Public module APIs and supported command-line entry points."""

from importlib.util import find_spec

from clinical_warrant.interfaces.cli import build_parser, main
from clinical_warrant.modules.classification import ClassifierError, QuestionClassifier, TextEncoder
from clinical_warrant.modules.decision import QuestionClassifierProtocol, WarrantEngine, WarrantError
from clinical_warrant.modules.evaluation import (
    DecisionEngine,
    EvaluationCase,
    EvaluationError,
    evaluate_cases,
    load_evaluation_jsonl,
)
from clinical_warrant.modules.knowledge_base import (
    CdcQaAdapter,
    GenericJsonlAdapter,
    KnowledgeBaseValidationError,
    KnowledgeChunk,
    KnowledgeDocument,
    SourceRecord,
    parse_json_object,
)


def test_business_module_public_apis_are_available() -> None:
    assert QuestionClassifier is not None
    assert TextEncoder is not None
    assert ClassifierError is not None
    assert WarrantEngine is not None
    assert QuestionClassifierProtocol is not None
    assert WarrantError is not None
    assert DecisionEngine is not None
    assert EvaluationCase is not None
    assert EvaluationError is not None
    assert evaluate_cases is not None
    assert load_evaluation_jsonl is not None
    assert issubclass(KnowledgeBaseValidationError, ValueError)
    assert SourceRecord is not None
    assert CdcQaAdapter is not None
    assert GenericJsonlAdapter is not None
    assert KnowledgeDocument is not None
    assert KnowledgeChunk is not None
    assert parse_json_object('{"kind":"fixture"}') == {"kind": "fixture"}


def test_cli_interface_exposes_help_and_version_commands(capsys) -> None:
    parser = build_parser()
    assert parser.parse_args(["decide", "--input", "request.json"]).command == "decide"
    assert callable(main)
    assert "clinical-warrant" in parser.prog


def test_legacy_root_modules_are_removed() -> None:
    for module in ("catalog", "classifier", "cli", "contracts", "evaluation", "warrant"):
        assert find_spec(f"clinical_warrant.{module}") is None
