"""Load the allowlisted category documents from package resources."""

from __future__ import annotations

import json
from importlib.resources import files

from clinical_warrant.modules.context_intake.domain.category_registry import (
    CategoryRegistry,
    RegistryError,
    validate_category_registry,
)

CATEGORY_IDS = (
    "harm_reduction", "hiv_basics", "maternal_child_health", "pep_post_exposure",
    "personal_exposure_risk", "prep_medication", "prep_policy_services",
    "prevention_methods", "screening_recommendation", "symptom_questions",
    "testing_services", "test_result_interpretation", "transmission_education", "window_period",
)


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result = {}
    for key, value in pairs:
        if key in result:
            raise RegistryError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def load_category_registry() -> CategoryRegistry:
    """Load and validate the 14 packaged categories; callers cannot supply paths."""
    root = files("clinical_warrant.data").joinpath("context_intake", "categories")
    documents = []
    try:
        packaged_ids = {
            item.name[:-5]
            for item in root.iterdir()
            if item.name.endswith(".json") and item.is_file()
        }
        if packaged_ids != set(CATEGORY_IDS):
            raise RegistryError("packaged category files do not match the registered IDs")
        for category_id in CATEGORY_IDS:
            resource = root.joinpath(f"{category_id}.json")
            with resource.open("r", encoding="utf-8") as stream:
                document = json.load(stream, object_pairs_hook=_unique_object)
            if isinstance(document, dict) and document.get("category_id") != category_id:
                raise RegistryError(f"category_id does not match filename: {category_id}.json")
            documents.append(document)
    except (OSError, json.JSONDecodeError) as error:
        raise RegistryError("could not load packaged category registry") from error
    return validate_category_registry(documents)
