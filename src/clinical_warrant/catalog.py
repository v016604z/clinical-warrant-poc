"""Load and validate packaged research-only prototypes, rules, and cases."""

from __future__ import annotations

import json
from dataclasses import dataclass
from importlib.resources import files
from typing import Any, Mapping

from clinical_warrant.contracts import ContractError, DecisionInput, QuestionType


class CatalogError(ValueError):
    """Raised when packaged prototype, rule, or fixture data is inconsistent."""


QUESTION_TYPES = frozenset(
    {
        QuestionType.RESULT_INTERPRETATION,
        QuestionType.WINDOW_PERIOD,
        QuestionType.EXPOSURE_RISK,
        QuestionType.PREVENTION_EDUCATION,
    }
)


@dataclass(frozen=True)
class PrototypeCategory:
    category: QuestionType
    label_zh: str
    prototypes: tuple[str, ...]


@dataclass(frozen=True)
class RuleDefinition:
    rule_id: str
    question_type: QuestionType
    required_case_fields: tuple[str, ...]
    applicability_field: str
    applicability_value: str


@dataclass(frozen=True)
class MockCase:
    case_id: str
    request: DecisionInput
    question_type: QuestionType
    rule_id: str
    data_state: str


@dataclass(frozen=True)
class ResearchCatalog:
    prototypes: tuple[PrototypeCategory, ...]
    rules: tuple[RuleDefinition, ...]
    mock_cases: tuple[MockCase, ...]


def _object(value: Any, name: str) -> Mapping[str, Any]:
    if not isinstance(value, dict):
        raise CatalogError(f"{name} must be an object")
    return value


def _text(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise CatalogError(f"{name} must be a non-empty string")
    return value


def _question_type(value: Any, name: str) -> QuestionType:
    try:
        category = QuestionType(value)
    except (ValueError, TypeError) as error:
        raise CatalogError(f"{name} is not a recognized question type") from error
    if category not in QUESTION_TYPES:
        raise CatalogError(f"{name} cannot be unknown")
    return category


def validate_prototypes(raw: Any) -> tuple[PrototypeCategory, ...]:
    data = _object(raw, "prototypes")
    _text(data.get("purpose"), "prototypes.purpose")
    entries = data.get("categories")
    if not isinstance(entries, list):
        raise CatalogError("prototypes.categories must be an array")
    parsed = []
    seen: set[QuestionType] = set()
    for index, raw_entry in enumerate(entries):
        entry = _object(raw_entry, f"prototypes.categories[{index}]")
        category = _question_type(entry.get("category"), f"category[{index}]")
        if category in seen:
            raise CatalogError(f"duplicate prototype category: {category.value}")
        seen.add(category)
        label = _text(entry.get("label_zh"), f"label_zh[{index}]")
        values = entry.get("prototypes")
        if not isinstance(values, list) or not values:
            raise CatalogError(f"prototypes for {category.value} must not be empty")
        parsed_values = tuple(
            _text(item, f"prototypes[{index}]") for index, item in enumerate(values)
        )
        parsed.append(PrototypeCategory(category, label, parsed_values))
    if seen != QUESTION_TYPES:
        missing = sorted(item.value for item in QUESTION_TYPES - seen)
        raise CatalogError(f"missing prototype categories: {', '.join(missing)}")
    return tuple(parsed)


def validate_rules(
    raw: Any, prototypes: tuple[PrototypeCategory, ...]
) -> tuple[RuleDefinition, ...]:
    data = _object(raw, "rules")
    _text(data.get("purpose"), "rules.purpose")
    entries = data.get("rules")
    if not isinstance(entries, list):
        raise CatalogError("rules.rules must be an array")
    expected_categories = {item.category for item in prototypes}
    seen_ids: set[str] = set()
    seen_categories: set[QuestionType] = set()
    parsed = []
    for index, raw_entry in enumerate(entries):
        entry = _object(raw_entry, f"rules.rules[{index}]")
        rule_id = _text(entry.get("rule_id"), f"rule_id[{index}]")
        if rule_id in seen_ids:
            raise CatalogError(f"duplicate rule id: {rule_id}")
        seen_ids.add(rule_id)
        category = _question_type(entry.get("question_type"), f"question_type[{index}]")
        if category in seen_categories:
            raise CatalogError(f"duplicate rule category: {category.value}")
        seen_categories.add(category)
        required = entry.get("required_case_fields")
        if not isinstance(required, list) or not required:
            raise CatalogError(f"required_case_fields for {rule_id} must not be empty")
        fields = tuple(_text(field, f"required_case_fields[{index}]") for field in required)
        if len(fields) != len(set(fields)):
            raise CatalogError(f"required_case_fields for {rule_id} has duplicates")
        applicability = _object(entry.get("applies_when"), f"applies_when[{index}]")
        field = _text(applicability.get("field"), f"applies_when.field[{index}]")
        expected = _text(applicability.get("equals"), f"applies_when.equals[{index}]")
        if field not in fields:
            raise CatalogError(f"applicability field for {rule_id} must be required")
        parsed.append(RuleDefinition(rule_id, category, fields, field, expected))
    if seen_categories != expected_categories:
        missing = sorted(item.value for item in expected_categories - seen_categories)
        raise CatalogError(f"missing rule categories: {', '.join(missing)}")
    return tuple(parsed)


def validate_mock_cases(
    raw: Any, rules: tuple[RuleDefinition, ...]
) -> tuple[MockCase, ...]:
    data = _object(raw, "mock_cases")
    _text(data.get("purpose"), "mock_cases.purpose")
    entries = data.get("cases")
    if not isinstance(entries, list) or not entries:
        raise CatalogError("mock_cases.cases must be a non-empty array")
    rules_by_id = {rule.rule_id: rule for rule in rules}
    seen_ids: set[str] = set()
    parsed = []
    allowed_states = {"complete", "missing_required_field"}
    for index, raw_entry in enumerate(entries):
        entry = _object(raw_entry, f"mock_cases.cases[{index}]")
        case_id = _text(entry.get("case_id"), f"case_id[{index}]")
        if case_id in seen_ids:
            raise CatalogError(f"duplicate case id: {case_id}")
        seen_ids.add(case_id)
        category = _question_type(entry.get("question_type"), f"question_type[{index}]")
        rule_id = _text(entry.get("rule_id"), f"rule_id[{index}]")
        rule = rules_by_id.get(rule_id)
        if rule is None:
            raise CatalogError(f"case {case_id} references unknown rule {rule_id}")
        if rule.question_type is not category:
            raise CatalogError(f"case {case_id} category does not match rule {rule_id}")
        state = _text(entry.get("data_state"), f"data_state[{index}]")
        if state not in allowed_states:
            raise CatalogError(f"case {case_id} has unsupported data_state {state!r}")
        request = DecisionInput.from_dict(
            {
                "query": entry.get("query"),
                "case": entry.get("case"),
                "requested_scope": entry.get("requested_scope"),
            }
        )
        has_all_fields = set(rule.required_case_fields).issubset(request.case)
        if state == "complete" and not has_all_fields:
            raise CatalogError(f"case {case_id} is marked complete but misses rule fields")
        if state == "missing_required_field" and has_all_fields:
            raise CatalogError(f"case {case_id} is marked incomplete but has all rule fields")
        parsed.append(MockCase(case_id, request, category, rule_id, state))
    return tuple(parsed)


def _load_json(resource_name: str) -> Any:
    resource = files("clinical_warrant.data").joinpath(resource_name)
    try:
        with resource.open("r", encoding="utf-8") as stream:
            return json.load(stream)
    except (OSError, json.JSONDecodeError) as error:
        raise CatalogError(f"could not load packaged resource {resource_name}") from error


def load_research_catalog() -> ResearchCatalog:
    """Load packaged JSON using import resources, independent of current directory."""
    prototypes = validate_prototypes(_load_json("prototypes.json"))
    rules = validate_rules(_load_json("rules.json"), prototypes)
    mock_cases = validate_mock_cases(_load_json("mock_cases.json"), rules)
    return ResearchCatalog(prototypes, rules, mock_cases)
