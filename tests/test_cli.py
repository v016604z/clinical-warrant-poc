import json
from importlib.metadata import version
from pathlib import Path

import pytest

from clinical_warrant import __version__
from clinical_warrant.classifier import ClassifierError
from clinical_warrant.cli import main
from clinical_warrant.contracts import DecisionResult, QuestionType


def test_package_version_is_available() -> None:
    assert __version__ == version("clinical-warrant-poc")


def test_help_lists_reserved_commands(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as error:
        main(["--help"])

    assert error.value.code == 0
    output = capsys.readouterr().out
    assert "decide" in output
    assert "evaluate" in output
    assert "not implemented yet" in output


def test_reserved_command_fails_clearly(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as error:
        main(["evaluate", "--input", "unused.json", "--output", "unused-output"])

    assert error.value.code == 2
    error_text = capsys.readouterr().err
    assert "evaluate" in error_text
    assert "not implemented yet" in error_text


class FixedClassifier:
    def classify(self, query: str):
        from clinical_warrant.contracts import ClassificationResult

        assert query
        return ClassificationResult(QuestionType.RESULT_INTERPRETATION, 0.91)


def valid_input() -> dict[str, object]:
    return {
        "query": "我的愛滋篩檢報告結果該怎麼看？",
        "case": {"scenario_id": "synthetic-cli", "toy_rule_flag": "applicable"},
        "requested_scope": "education",
    }


def test_decide_reads_utf8_bom_and_writes_only_round_trip_json(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tmp_path / "request.json"
    encoded = json.dumps(valid_input(), ensure_ascii=False).encode("utf-8")
    path.write_bytes(b"\xef\xbb\xbf" + encoded)
    factory_calls = []

    def factory(*, threshold: float):
        factory_calls.append(threshold)
        return FixedClassifier()

    exit_code = main(
        ["decide", "--input", str(path)], classifier_factory=factory
    )
    output = capsys.readouterr()

    assert exit_code == 0
    assert output.err == ""
    assert factory_calls == [0.5]
    result = DecisionResult.from_json(output.out)
    assert result.classification.category is QuestionType.RESULT_INTERPRETATION
    assert result.decision.value == "allow_education"


@pytest.mark.parametrize(
    "source", ["missing", "invalid_json", "invalid_contract", "invalid_utf8"]
)
def test_invalid_input_fails_before_classifier_is_loaded(
    source: str, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tmp_path / "request.json"
    if source == "invalid_json":
        path.write_text('{"query":', encoding="utf-8")
    elif source == "invalid_contract":
        path.write_text('{"query":"x","case":{}}', encoding="utf-8")
    elif source == "invalid_utf8":
        path.write_bytes(b"\xff\xfe")
    factory_calls = []

    def factory(**kwargs):
        factory_calls.append(kwargs)
        raise AssertionError("input errors must not load the classifier")

    exit_code = main(
        ["decide", "--input", str(path)], classifier_factory=factory
    )
    output = capsys.readouterr()

    assert exit_code == 2
    assert output.out == ""
    assert output.err.startswith("error: invalid input:")
    assert factory_calls == []


@pytest.mark.parametrize("failure_stage", ["load", "inference"])
def test_model_failure_fails_without_emitting_decision(
    failure_stage: str,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    path = tmp_path / "request.json"
    path.write_text(json.dumps(valid_input()), encoding="utf-8")

    def failing_factory(**kwargs):
        if failure_stage == "load":
            raise ClassifierError("model unavailable")

        class FailingClassifier:
            def classify(self, query: str):
                raise ClassifierError("encoder failed")

        return FailingClassifier()

    exit_code = main(
        ["decide", "--input", str(path)], classifier_factory=failing_factory
    )
    output = capsys.readouterr()

    assert exit_code == 1
    assert output.out == ""
    expected_error = "model unavailable" if failure_stage == "load" else "encoder failed"
    assert expected_error in output.err
