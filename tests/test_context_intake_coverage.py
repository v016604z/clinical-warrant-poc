import pytest

from clinical_warrant.modules.context_intake.application.coverage import (
    CoverageError,
    calculate_case_coverage,
)
from clinical_warrant.modules.context_intake.domain.category_registry import validate_category_registry
from clinical_warrant.modules.context_intake.domain.classification import IntakeClassificationResult
from clinical_warrant.modules.context_intake.domain.state import CaseState, TurnEvent


def registry(fields, *, name="Category"):
    return validate_category_registry([{
        "category_id": "test_category",
        "category_name": name,
        "fields": {key: {"type": kind, "description": key} for key, kind in fields.items()},
    }])


def classified(turn_id, case_id, category_id, selected, version):
    result = IntakeClassificationResult(
        category_id, 0.9, "other_category", 0.1, False,
        "test-model", "test-revision", version,
    )
    return TurnEvent(turn_id, case_id, category_id, "classification", result, tuple(selected), version)


def continuation(turn_id, case_id, category_id, selected, version):
    return TurnEvent(turn_id, case_id, category_id, "continuation", None, tuple(selected), version)


def handoff(turn_id, case_id, category_id, selected, version):
    return TurnEvent(turn_id, case_id, category_id, "handoff", None, tuple(selected), version)


def test_counts_selected_known_unknown_and_shared_keys_once_per_category():
    reg = registry({"shared_key": "string", "bool_key": "boolean", "int_key": "integer"})
    case = CaseState("case-1", "participant-1")
    case = case.with_attribute("shared_key", "provided", "turn-1")
    case = case.with_attribute("bool_key", False, "turn-1")
    case = case.with_attribute("int_key", 0, "turn-1")
    events = (classified("turn-1", "case-1", "test_category", ("shared_key", "bool_key", "absent"), reg.version),)

    result = calculate_case_coverage(reg, case, events, "test_category")

    assert (result.catalog_count, result.selected_count, result.known_count) == (3, 2, 3)
    assert (result.selected_known_count, result.selected_unknown_count) == (2, 0)
    assert result.coverage_rate == 1
    assert result.selection_catalog_version == reg.version


def test_latest_classification_selection_survives_continuation_and_handoff():
    reg = registry({"first": "string", "second": "string"})
    case = CaseState("case-1", "participant-1")
    events = (
        classified("turn-1", "case-1", "test_category", ("first",), "older-version"),
        continuation("turn-2", "case-1", "test_category", ("second",), reg.version),
        handoff("turn-3", "case-1", "test_category", ("second",), reg.version),
    )

    result = calculate_case_coverage(reg, case, events, "test_category")

    assert result.selected_count == 1
    assert result.selected_unknown_count == 1
    assert result.selection_catalog_version == "older-version"


def test_latest_empty_classification_selection_resets_selection():
    reg = registry({"first": "string"})
    case = CaseState("case-1", "participant-1")
    events = (
        classified("turn-1", "case-1", "test_category", ("first",), "old"),
        classified("turn-2", "case-1", "test_category", (), reg.version),
    )

    result = calculate_case_coverage(reg, case, events, "test_category")

    assert result.selected_count == 0
    assert result.selection_catalog_version == reg.version


def test_case_and_category_isolation_and_no_case_counts_catalog_only():
    reg = registry({"shared": "string"})
    case = CaseState("case-2", "participant-1").with_attribute("shared", "known", "turn-1")
    events = (classified("turn-1", "case-1", "test_category", ("shared",), reg.version),)

    other_case = calculate_case_coverage(reg, case, events, "test_category")
    no_case = calculate_case_coverage(reg, None, events, "test_category", case_id="case-1")

    assert (other_case.selected_count, other_case.known_count) == (0, 1)
    assert no_case.catalog_count == 1
    assert (no_case.selected_count, no_case.known_count, no_case.coverage_rate) == (0, 0, None)
    assert no_case.case_id == "case-1"


def test_shared_key_is_counted_once_within_a_case_and_in_each_category():
    reg = validate_category_registry([
        {"category_id": "first_category", "category_name": "First", "fields": {
            "shared": {"type": "string", "description": "shared"},
        }},
        {"category_id": "second_category", "category_name": "Second", "fields": {
            "shared": {"type": "string", "description": "shared"},
        }},
    ])
    case = CaseState("case-1", "participant-1").with_attribute("shared", "known", "turn-1")
    events = (
        classified("turn-1", "case-1", "first_category", ("shared",), reg.version),
        classified("turn-2", "case-1", "second_category", ("shared",), reg.version),
    )

    first = calculate_case_coverage(reg, case, events, "first_category")
    second = calculate_case_coverage(reg, case, events, "second_category")

    assert (first.known_count, first.selected_count) == (1, 1)
    assert (second.known_count, second.selected_count) == (1, 1)


def test_empty_category_is_not_a_full_coverage_rate():
    reg = registry({})
    case = CaseState("case-1", "participant-1")

    result = calculate_case_coverage(reg, case, (), "test_category")

    assert result.catalog_count == 0
    assert result.coverage_rate is None


def test_as_of_reconstructs_attribute_history_and_selection():
    reg = registry({"value": "string"})
    case = CaseState("case-1", "participant-1").with_attribute("value", "old", "turn-1")
    case = case.with_attribute("value", "new", "turn-3", action="correct")
    events = (
        classified("turn-1", "case-1", "test_category", ("value",), "v1"),
        classified("turn-2", "case-1", "test_category", (), "v2"),
        continuation("turn-3", "case-1", "test_category", ("value",), "v2"),
    )

    at_first = calculate_case_coverage(reg, case, events, "test_category", as_of_turn_id="turn-1")
    at_second = calculate_case_coverage(reg, case, events, "test_category", as_of_turn_id="turn-2")
    at_third = calculate_case_coverage(reg, case, events, "test_category", as_of_turn_id="turn-3")

    assert (at_first.known_count, at_first.selected_count, at_first.selection_catalog_version) == (1, 1, "v1")
    assert (at_second.known_count, at_second.selected_count, at_second.selection_catalog_version) == (1, 0, "v2")
    assert (at_third.known_count, at_third.selected_count) == (1, 0)


def test_historical_registry_is_explicit_and_selected_fields_recompute_against_it():
    old_registry = registry({"shared": "string", "removed": "string"})
    new_registry = registry({"shared": "string", "added": "string"})
    case = CaseState("case-1", "participant-1").with_attribute("shared", "known", "turn-1")
    events = (classified("turn-1", "case-1", "test_category", ("shared", "removed"), old_registry.version),)

    old_result = calculate_case_coverage(old_registry, case, events, "test_category")
    new_result = calculate_case_coverage(new_registry, case, events, "test_category")

    assert (old_result.catalog_count, old_result.selected_count, old_result.known_count) == (2, 2, 1)
    assert (new_result.catalog_count, new_result.selected_count, new_result.known_count) == (2, 1, 1)
    assert old_result.catalog_version != new_result.catalog_version
    assert old_result.selection_catalog_version == new_result.selection_catalog_version == old_registry.version


def test_as_of_rejects_missing_target_and_missing_attribute_source_turn():
    reg = registry({"value": "string"})
    case = CaseState("case-1", "participant-1").with_attribute("value", "x", "missing-source")
    events = (classified("turn-1", "case-1", "test_category", (), reg.version),)

    with pytest.raises(CoverageError, match="as_of turn not found"):
        calculate_case_coverage(reg, case, events, "test_category", as_of_turn_id="missing")
    with pytest.raises(CoverageError, match="attribute source turn not found"):
        calculate_case_coverage(reg, case, events, "test_category", as_of_turn_id="turn-1")
