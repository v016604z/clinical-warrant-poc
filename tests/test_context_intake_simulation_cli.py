"""CLI and offline evaluation tests for the synthetic Context Intake demonstration."""

import json
from pathlib import Path

from clinical_warrant.interfaces.cli import main


FIXTURE = Path(__file__).parents[1] / "evaluation" / "context_intake" / "synthetic_multiturn.json"


def test_intake_demo_replays_fixture_with_explicit_simulation_notice(capsys):
    assert main(["intake", "demo", "--fixture", str(FIXTURE)]) == 0
    output = json.loads(capsys.readouterr().out)
    assert "synthetic offline simulation" in output["notice"]
    assert output["metrics"]["turn_count"] == 9
    assert output["metrics"]["correction_count"] == 1
    assert output["metrics"]["repeated_question_count"] == 1
    assert output["metrics"]["extraction_exact_match"]["value"] == 1.0
    assert output["metrics"]["state_field_accuracy"]["value"] == 1.0
    assert "exposure_route" not in output["turns"][0]["attributes"]
    assert output["turns"][1]["extracted_attributes"] == {}
    assert output["turns"][1]["attributes"]["exposure_datetime"] == "昨天"
    assert output["turns"][2]["extracted_attributes"] == {}
    assert output["turns"][2]["attributes"]["exposure_datetime"] == "昨天"
    assert output["turns"][5]["attributes"]["exposure_datetime"] == "前天"
    assert {item["category_id"] for item in output["metrics"]["coverage"]} == {
        "personal_exposure_risk", "pep_post_exposure", "window_period",
        "test_result_interpretation",
    }


def test_fixture_keeps_cases_separate_and_does_not_assign_ambiguous_recent_event():
    from clinical_warrant.modules.context_intake import load_category_registry
    from clinical_warrant.modules.context_intake.application.simulation import (
        load_conversation_fixture,
        replay_conversation,
    )

    _, fixture = load_conversation_fixture(FIXTURE)
    assert "last_possible_exposure_date" not in FIXTURE.read_text(encoding="utf-8")
    replay = replay_conversation(fixture, load_category_registry())
    session = replay["session"]

    assert len(session.cases) == 2
    first_case_id, second_case_id = session.cases
    assert session.cases[first_case_id].attributes["exposure_datetime"].value == "前天"
    assert session.cases[second_case_id].attributes["exposure_datetime"].value == "今天"
    assert session.cases[first_case_id].attributes["exposure_datetime"].value != session.cases[second_case_id].attributes["exposure_datetime"].value
    assert session.turn_events[5].category_id == "test_result_interpretation"
    assert session.turn_events[5].case_id == first_case_id
    assert session.turn_events[7].category_id == "window_period"
    assert session.turn_events[7].case_id is None
    assert replay["turns"][7]["extracted_attributes"] == {}


def test_intake_step_demo_pauses_for_each_fixture_turn(monkeypatch, capsys):
    prompts = []
    monkeypatch.setattr("builtins.input", lambda prompt: prompts.append(prompt) or "")

    assert main(["intake", "demo", "--fixture", str(FIXTURE), "--step"]) == 0

    lines = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert len(prompts) == 9
    assert len(lines) == 10
    assert [turn["category_id"] for turn in lines[:-1]][-1] is None
    assert lines[-1]["metrics"]["turn_count"] == 9


def test_intake_evaluate_publishes_separate_immutable_run(tmp_path, capsys):
    assert main([
        "intake", "evaluate", "--input", str(FIXTURE), "--output", str(tmp_path)
    ]) == 0
    published = json.loads(capsys.readouterr().out)
    run = Path(published["run_dir"])
    assert (run / "summary.json").is_file()
    assert (run / "predictions.jsonl").is_file()
    assert (run / "errors.jsonl").read_text(encoding="utf-8") == ""
    summary = json.loads((run / "summary.json").read_text(encoding="utf-8"))
    assert summary["metadata"]["evaluation_type"] == "synthetic_offline_context_intake_simulation"
    assert len(summary["metadata"]["fixture_sha256"]) == 64


def test_intake_does_not_change_existing_cli_commands():
    from clinical_warrant.interfaces.cli import build_parser

    parser = build_parser()
    assert parser.parse_args(["decide", "--input", "case.json"]).command == "decide"
    assert parser.parse_args(["evaluate", "--input", "cases.jsonl", "--output", "runs"]).command == "evaluate"
    assert parser.parse_args(["kb", "validate", "--dataset", "dataset"]).command == "kb"


def test_fixture_extraction_rejects_unregistered_fields():
    import pytest

    from clinical_warrant.modules.context_intake import load_category_registry
    from clinical_warrant.modules.context_intake.application.extraction import (
        ExtractionError,
        parse_extraction_response,
    )

    payload = json.dumps({
        "selected_fields": ["not_a_registry_field"],
        "extracted_attributes": {},
        "selection_reason": "test",
        "clarification_question": None,
        "clarification_field_key": None,
    })
    with pytest.raises(ExtractionError):
        parse_extraction_response(payload, load_category_registry().get("personal_exposure_risk"))


def test_evaluation_records_extraction_and_state_mismatches():
    from clinical_warrant.modules.context_intake import load_category_registry
    from clinical_warrant.modules.context_intake.application.simulation import evaluate_fixture

    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    fixture["steps"][0]["expected_extracted_attributes"]["exposure_route"] = "錯誤標註"
    fixture["steps"][0]["expected_attributes"]["exposure_route"] = "錯誤標註"
    report = evaluate_fixture(b"synthetic-fixture", fixture, load_category_registry())
    assert {error["error_type"] for error in report["errors"]} == {
        "extraction_mismatch", "state_field_mismatch"
    }


def test_evaluation_reveals_unsupported_exposure_route_extraction():
    from clinical_warrant.modules.context_intake import load_category_registry
    from clinical_warrant.modules.context_intake.application.simulation import evaluate_fixture

    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    fixture["steps"][0]["extractor_response"]["extracted_attributes"]["exposure_route"] = "性行為"
    report = evaluate_fixture(b"synthetic-fixture", fixture, load_category_registry())

    assert {error["error_type"] for error in report["errors"]} == {
        "extraction_mismatch", "unexpected_state_field"
    }
    assert report["predictions"][0]["extracted_attributes"]["exposure_route"] == "性行為"
