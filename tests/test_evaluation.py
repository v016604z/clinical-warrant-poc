import json
from pathlib import Path

import pytest

from clinical_warrant.infrastructure.catalog import load_research_catalog
from clinical_warrant.shared.domain.contracts import (
    CheckKind,
    CheckResult,
    CheckStatus,
    ClassificationResult,
    Decision,
    DecisionInput,
    DecisionResult,
    QuestionType,
    ReasonCode,
)
from clinical_warrant.modules.evaluation.application.evaluation import (
    DecisionEngine,
    EvaluationCase,
    EvaluationError,
    ExpectedResult,
    evaluate_cases,
    load_evaluation_jsonl,
)
from clinical_warrant.bootstrap.composition import evaluate_scenarios
from clinical_warrant.modules.evaluation.infrastructure.report_writer import publish_report


DATASET = Path(__file__).parents[1] / "evaluation" / "v1" / "synthetic_hiv_cases.jsonl"


def test_synthetic_dataset_is_separate_and_covers_categories_and_decisions() -> None:
    cases = load_evaluation_jsonl(DATASET.read_text(encoding="utf-8"))
    categories = {case.expected.category for case in cases}

    assert len(cases) == 20
    assert categories == set(QuestionType)
    assert all(case.request.query for case in cases)
    assert sum(case.expected.decision is Decision.ALLOW_EDUCATION for case in cases) == 8
    catalog_queries = {
        text for group in load_research_catalog().prototypes for text in group.prototypes
    }
    assert all(case.request.query not in catalog_queries for case in cases)


def _line(case_id: str, *, expected: dict | None = None) -> str:
    return json.dumps(
        {
            "id": case_id,
            "input": {
                "query": f"synthetic query {case_id}",
                "case": {},
                "requested_scope": "education",
            },
            "expected": expected
            or {
                "category": "result_interpretation",
                "decision": "allow_education",
                "missing_fields": [],
                "reason_codes": ["all_checks_passed"],
            },
        }
    )


def _evaluate_pure(
    cases: tuple[EvaluationCase, ...],
    engine: DecisionEngine,
    *,
    threshold: float = 0.5,
    dataset_sha256: str = "hash",
) -> dict:
    return evaluate_cases(
        cases,
        engine,
        threshold=threshold,
        dataset_sha256=dataset_sha256,
        package_version="0.1.0",
        core_dependencies={
            "sentence-transformers": None,
            "transformers": None,
            "torch": None,
        },
    )


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("", "must not be empty"),
        (_line("one") + "\nnot-json\n", "line 2: invalid JSON"),
        (_line("x") + "\n" + _line("x"), "line 2: duplicate id"),
        (
            _line("x", expected={"category": "bad", "decision": "restrict", "missing_fields": [], "reason_codes": []}),
            "known question type",
        ),
        (
            _line("x", expected={"category": "unknown", "decision": "restrict", "missing_fields": [1], "reason_codes": []}),
            "array of non-empty strings",
        ),
        (
            _line("x", expected={"category": "unknown", "decision": "bad", "missing_fields": [], "reason_codes": []}),
            "not a known decision",
        ),
    ],
)
def test_invalid_jsonl_is_rejected_with_context(text: str, message: str) -> None:
    with pytest.raises(EvaluationError, match=message):
        load_evaluation_jsonl(text)

def test_blank_line_is_reported_instead_of_silently_skipped() -> None:
    with pytest.raises(EvaluationError, match="line 2: blank lines"):
        load_evaluation_jsonl(_line("one") + "\n\n" + _line("two"))


def _result(
    category: QuestionType,
    decision: Decision,
    missing_fields: tuple[str, ...] = (),
    reasons: tuple[ReasonCode, ...] = (ReasonCode.ALL_CHECKS_PASSED,),
) -> DecisionResult:
    return DecisionResult(
        classification=ClassificationResult(category, 0.8),
        rule_id="toy-test-rule" if category is not QuestionType.UNKNOWN else None,
        checks=(
            CheckResult(CheckKind.CASE_SUFFICIENCY, CheckStatus.PASS),
            CheckResult(CheckKind.RULE_APPLICABILITY, CheckStatus.PASS),
            CheckResult(CheckKind.RESPONSE_SCOPE, CheckStatus.PASS),
        ),
        missing_fields=missing_fields,
        reason_codes=reasons,
        decision=decision,
    )


class SequenceEngine:
    def __init__(self, results: list[DecisionResult] | None = None, fail_at: int | None = None):
        self.results = results or []
        self.fail_at = fail_at
        self.calls = 0

    def decide(self, request: DecisionInput) -> DecisionResult:
        index = self.calls
        self.calls += 1
        if self.fail_at == index:
            raise RuntimeError("synthetic encoder failure")
        return self.results[index]


def test_metrics_errors_and_confusion_are_counted_without_treating_unknown_as_failure(
    tmp_path: Path,
) -> None:
    cases = load_evaluation_jsonl(
        "\n".join(
            [
                _line("known"),
                _line(
                    "unknown",
                    expected={
                        "category": "unknown",
                        "decision": "restrict",
                        "missing_fields": [],
                        "reason_codes": ["unknown_intent"],
                    },
                ),
            ]
        )
    )
    engine = SequenceEngine(
        [
            _result(QuestionType.RESULT_INTERPRETATION, Decision.ALLOW_EDUCATION),
            _result(
                QuestionType.UNKNOWN,
                Decision.RESTRICT,
                reasons=(ReasonCode.UNKNOWN_INTENT,),
            ),
        ]
    )

    report_data = _evaluate_pure(
        cases,
        engine,
        threshold=0.5,
        dataset_sha256="dataset-hash",
    )
    run = publish_report(report_data, tmp_path / "reports")
    summary = run["summary"]
    report = Path(run["run_dir"])

    assert engine.calls == 2
    assert summary["metrics"]["classification_accuracy"] == {
        "numerator": 2,
        "denominator": 2,
        "value": 1.0,
    }
    assert summary["metrics"]["unknown_rate"]["value"] == 0.5
    assert summary["confusion_counts"]["unknown"]["unknown"] == 1
    assert summary["counts"]["cases_with_any_mismatch"] == 0
    assert (report / "summary.json").is_file()
    assert len((report / "predictions.jsonl").read_text(encoding="utf-8").splitlines()) == 2
    assert (report / "errors.jsonl").read_text(encoding="utf-8") == ""
    assert summary["metadata"]["dataset_sha256"] == "dataset-hash"


def test_mismatches_are_written_as_case_details_and_do_not_fail_run(tmp_path: Path) -> None:
    cases = load_evaluation_jsonl(_line("wrong-category"))
    engine = SequenceEngine(
        [
            _result(
                QuestionType.WINDOW_PERIOD,
                Decision.NEED_MORE_INFO,
                ("scenario_id",),
                (ReasonCode.CASE_INFO_MISSING,),
            )
        ]
    )

    run = evaluate_scenarios(
        cases, engine, tmp_path, threshold=0.5, dataset_sha256="hash"
    )

    assert run["summary"]["counts"]["reason_codes_mismatch"] == 1
    assert run["summary"]["metrics"]["missing_fields_accuracy"]["value"] == 0.0
    error = json.loads((Path(run["run_dir"]) / "errors.jsonl").read_text(encoding="utf-8"))
    assert error["id"] == "wrong-category"
    assert set(error["mismatches"]) == {
        "category", "decision", "missing_fields", "reason_codes"
    }


def test_missing_fields_and_reason_codes_compare_as_sets(tmp_path: Path) -> None:
    cases = load_evaluation_jsonl(
        _line(
            "unordered",
            expected={
                "category": "result_interpretation",
                "decision": "restrict",
                "missing_fields": ["b", "a"],
                "reason_codes": ["scope_mismatch", "rule_not_applicable"],
            },
        )
    )
    engine = SequenceEngine(
        [
            _result(
                QuestionType.RESULT_INTERPRETATION,
                Decision.RESTRICT,
                ("a", "b"),
                (ReasonCode.RULE_NOT_APPLICABLE, ReasonCode.SCOPE_MISMATCH),
            )
        ]
    )

    run = evaluate_scenarios(cases, engine, tmp_path, threshold=0.5, dataset_sha256="hash")

    error_path = Path(run["run_dir"]) / "errors.jsonl"
    assert error_path.read_text(encoding="utf-8") == ""
    assert run["summary"]["counts"]["missing_fields_match"] == 1
    assert run["summary"]["counts"]["reason_codes_match"] == 1


def test_incorrect_unknown_prediction_is_counted_in_full_case_denominators(
    tmp_path: Path,
) -> None:
    cases = load_evaluation_jsonl(_line("known"))
    engine = SequenceEngine(
        [
            _result(
                QuestionType.UNKNOWN,
                Decision.RESTRICT,
                reasons=(ReasonCode.UNKNOWN_INTENT,),
            )
        ]
    )

    run = evaluate_scenarios(
        cases, engine, tmp_path, threshold=0.5, dataset_sha256="hash"
    )

    assert run["summary"]["metrics"]["classification_accuracy"]["denominator"] == 1
    assert run["summary"]["metrics"]["classification_accuracy"]["value"] == 0.0
    assert run["summary"]["metrics"]["unknown_rate"]["value"] == 1.0
    assert run["summary"]["counts"]["cases_with_any_mismatch"] == 1


def test_engine_failure_leaves_no_report_and_one_engine_is_reused(tmp_path: Path) -> None:
    cases = load_evaluation_jsonl("\n".join([_line("first"), _line("second")]))
    output = tmp_path / "reports"
    engine = SequenceEngine(
        [_result(QuestionType.RESULT_INTERPRETATION, Decision.ALLOW_EDUCATION)],
        fail_at=1,
    )

    with pytest.raises(EvaluationError, match="case 'second' failed"):
        evaluate_scenarios(cases, engine, output, threshold=0.5, dataset_sha256="hash")

    assert engine.calls == 2
    assert not output.exists()


def test_repeated_evaluation_preserves_each_run(tmp_path: Path) -> None:
    cases = load_evaluation_jsonl(_line("one"))
    output = tmp_path / "reports"

    run1 = evaluate_scenarios(
        cases,
        SequenceEngine([_result(QuestionType.RESULT_INTERPRETATION, Decision.ALLOW_EDUCATION)]),
        output,
        threshold=0.5,
        dataset_sha256="hash",
    )
    run2 = evaluate_scenarios(
        cases,
        SequenceEngine([_result(QuestionType.RESULT_INTERPRETATION, Decision.ALLOW_EDUCATION)]),
        output,
        threshold=0.5,
        dataset_sha256="hash",
    )

    assert run1["run_id"] != run2["run_id"]
    assert Path(run1["run_dir"]).is_dir()
    assert Path(run2["run_dir"]).is_dir()
    assert len(list(output.glob("run-*"))) == 2


def test_publish_failure_removes_only_new_temporary_run_and_preserves_old_report(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cases = load_evaluation_jsonl(_line("one"))
    output = tmp_path / "reports"
    engine_result = _result(QuestionType.RESULT_INTERPRETATION, Decision.ALLOW_EDUCATION)
    existing = evaluate_scenarios(
        cases,
        SequenceEngine([engine_result]),
        output,
        threshold=0.5,
        dataset_sha256="hash",
    )
    original_replace = Path.replace

    def fail_temporary_publish(source: Path, target: Path) -> Path:
        if source.name.startswith(".evaluation-"):
            raise OSError("synthetic atomic publish failure")
        return original_replace(source, target)

    monkeypatch.setattr(Path, "replace", fail_temporary_publish)
    with pytest.raises(EvaluationError, match="synthetic atomic publish failure"):
        evaluate_scenarios(
            cases,
            SequenceEngine([engine_result]),
            output,
            threshold=0.5,
            dataset_sha256="hash",
        )

    assert Path(existing["run_dir"], "summary.json").is_file()
    assert len(list(output.glob("run-*"))) == 1
    assert list(output.glob(".evaluation-*")) == []


def test_metadata_does_not_claim_default_catalog_for_injected_engine(tmp_path: Path) -> None:
    cases = load_evaluation_jsonl(_line("injected"))
    run = evaluate_scenarios(
        cases,
        SequenceEngine([_result(QuestionType.RESULT_INTERPRETATION, Decision.ALLOW_EDUCATION)]),
        tmp_path,
        threshold=0.5,
        dataset_sha256="hash",
    )
    metadata = run["summary"]["metadata"]

    assert metadata["prototype_sha256"] is None
    assert metadata["rule_sha256"] is None
    assert metadata["prototype_identity_source"] == "unavailable_in_injected_engine"
    assert metadata["rule_identity_source"] == "unavailable_in_injected_engine"
    assert metadata["model_id"] is None
    assert metadata["unique_query_count"] == 1


def test_requested_threshold_must_match_exposed_classifier_threshold(tmp_path: Path) -> None:
    cases = load_evaluation_jsonl(_line("threshold"))
    engine = SequenceEngine(
        [_result(QuestionType.RESULT_INTERPRETATION, Decision.ALLOW_EDUCATION)]
    )
    engine.classifier = type("ClassifierMetadata", (), {"threshold": 0.7})()

    with pytest.raises(EvaluationError, match="does not match classifier threshold"):
        evaluate_scenarios(cases, engine, tmp_path, threshold=0.5, dataset_sha256="hash")

    assert engine.calls == 0
    assert list(tmp_path.iterdir()) == []
