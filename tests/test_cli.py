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


def test_help_lists_commands(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as error:
        main(["--help"])

    assert error.value.code == 0
    output = capsys.readouterr().out
    assert "decide" in output
    assert "evaluate" in output
    assert "labeled JSONL scenario dataset" in output


def test_evaluate_writes_machine_readable_report_and_returns_zero_on_mismatches(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    source = tmp_path / "cases.jsonl"
    records = [
        {
            "id": case_id,
            "input": valid_input(),
            "expected": {
                "category": category,
                "decision": "allow_education",
                "missing_fields": [],
                "reason_codes": ["all_checks_passed"],
            },
        }
        for case_id, category in [
            ("one", "result_interpretation"),
            ("intentional-mismatch", "prevention_education"),
        ]
    ]
    source.write_text(
        "".join(json.dumps(record, ensure_ascii=False) + "\n" for record in records),
        encoding="utf-8",
    )
    calls = []

    def factory(*, threshold: float):
        calls.append(threshold)
        return FixedClassifier()

    exit_code = main(
        ["evaluate", "--input", str(source), "--output", str(tmp_path / "reports")],
        classifier_factory=factory,
    )
    output = capsys.readouterr()

    assert exit_code == 0
    assert output.err == ""
    assert calls == [0.5]
    payload = json.loads(output.out)
    report_dir = Path(payload["run_dir"])
    summary = json.loads((report_dir / "summary.json").read_text(encoding="utf-8"))
    assert payload["total_cases"] == summary["total_cases"] == 2
    assert summary["metrics"]["classification_accuracy"]["value"] == 0.5
    predictions = (report_dir / "predictions.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(predictions) == 2
    assert json.loads(predictions[0])["input"]["query"] == valid_input()["query"]
    errors = (report_dir / "errors.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(errors) == 1
    assert json.loads(errors[0])["id"] == "intentional-mismatch"
    assert summary["metadata"]["rule_sha256"]
    assert summary["metadata"]["prototype_sha256"] is None
    assert summary["metadata"]["model_id"] is None


def test_evaluate_invalid_dataset_fails_before_classifier_load(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    source = tmp_path / "bad.jsonl"
    source.write_text('{"id":"broken"}\n', encoding="utf-8")
    calls = []

    def factory(**kwargs):
        calls.append(kwargs)
        raise AssertionError("invalid dataset must not load the model")

    exit_code = main(
        ["evaluate", "--input", str(source), "--output", str(tmp_path / "reports")],
        classifier_factory=factory,
    )
    output = capsys.readouterr()

    assert exit_code == 2
    assert output.out == ""
    assert "line 1" in output.err
    assert calls == []


def test_evaluate_model_failure_emits_no_report_or_stdout(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    source = tmp_path / "cases.jsonl"
    source.write_text(
        json.dumps(
            {
                "id": "one",
                "input": valid_input(),
                "expected": {
                    "category": "result_interpretation",
                    "decision": "allow_education",
                    "missing_fields": [],
                    "reason_codes": ["all_checks_passed"],
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )
    reports = tmp_path / "reports"

    def failing_factory(**kwargs):
        raise ClassifierError("model unavailable")

    exit_code = main(
        ["evaluate", "--input", str(source), "--output", str(reports)],
        classifier_factory=failing_factory,
    )
    output = capsys.readouterr()

    assert exit_code == 1
    assert output.out == ""
    assert "model unavailable" in output.err
    assert not reports.exists()


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
