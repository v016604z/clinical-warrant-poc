"""Case field coverage for an explicitly selected category registry version."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from clinical_warrant.modules.context_intake.domain.category_registry import CategoryRegistry
from clinical_warrant.modules.context_intake.domain.state import CaseState, TurnEvent


class CoverageError(ValueError):
    """Coverage history cannot be computed from the supplied events."""


@dataclass(frozen=True)
class CategoryCoverage:
    case_id: str | None
    category_id: str
    catalog_version: str
    selection_catalog_version: str | None
    catalog_count: int
    selected_count: int
    known_count: int
    selected_known_count: int
    selected_unknown_count: int
    coverage_rate: float | None


def calculate_case_coverage(
    registry: CategoryRegistry,
    case: CaseState | None,
    turn_events: Sequence[TurnEvent],
    category_id: str,
    *,
    case_id: str | None = None,
    as_of_turn_id: str | None = None,
) -> CategoryCoverage:
    """Calculate category counts using this registry and the case's event history.

    Historical registry versions are selected by passing their immutable registry.
    ``as_of_turn_id`` reconstructs known and selected fields at that event boundary.
    """
    category = registry.get(category_id)
    if case is not None:
        if case_id is not None and case_id != case.case_id:
            raise CoverageError("case_id does not match the supplied case")
        case_id = case.case_id

    event_positions = {event.turn_id: index for index, event in enumerate(turn_events)}
    if len(event_positions) != len(turn_events):
        raise CoverageError("turn event IDs must be unique")
    end = len(turn_events) - 1
    if as_of_turn_id is not None:
        if as_of_turn_id not in event_positions:
            raise CoverageError(f"as_of turn not found: {as_of_turn_id}")
        end = event_positions[as_of_turn_id]

    field_keys = set(category.fields)
    if case is None:
        return CategoryCoverage(case_id, category_id, registry.version, None,
                                len(field_keys), 0, 0, 0, 0, None)

    known: set[str] = set()
    for key, attribute in case.attributes.items():
        if as_of_turn_id is None:
            if attribute.value is not None:
                known.add(key)
            continue
        changes_seen = False
        for change in attribute.history:
            position = event_positions.get(change.source_turn_id)
            if position is None:
                raise CoverageError(f"attribute source turn not found: {change.source_turn_id}")
            if position <= end:
                changes_seen = True
        if changes_seen:
            known.add(key)

    selected_event = next((
        event for event in reversed(turn_events[:end + 1])
        if event.case_id == case.case_id
        and event.category_id == category_id
        and event.category_source == "classification"
    ), None)
    selected = set(selected_event.selected_fields) if selected_event else set()
    selected_in_category = selected & field_keys
    known_in_category = known & field_keys
    selected_known = selected_in_category & known_in_category
    catalog_count = len(field_keys)
    return CategoryCoverage(
        case.case_id,
        category_id,
        registry.version,
        selected_event.catalog_version if selected_event else None,
        catalog_count,
        len(selected_in_category),
        len(known_in_category),
        len(selected_known),
        len(selected_in_category - selected_known),
        len(known_in_category) / catalog_count if catalog_count else None,
    )


__all__ = ["CategoryCoverage", "CoverageError", "calculate_case_coverage"]
