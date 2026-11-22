"""Load the independent Context Intake prototype catalog from package resources."""

from __future__ import annotations

import json
from importlib.resources import files

from clinical_warrant.modules.context_intake.domain.category_registry import RegistryError
from clinical_warrant.modules.context_intake.domain.classification import IntakePrototypeCategory
from clinical_warrant.modules.context_intake.infrastructure.category_registry import load_category_registry


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise RegistryError(f"duplicate prototype catalog key: {key}")
        result[key] = value
    return result


def load_intake_prototype_catalog() -> tuple[IntakePrototypeCategory, ...]:
    resource = files("clinical_warrant.data").joinpath("context_intake", "prototypes.json")
    try:
        with resource.open("r", encoding="utf-8") as stream:
            payload = json.load(stream, object_pairs_hook=_unique_object)
    except RegistryError:
        raise
    except (OSError, json.JSONDecodeError) as error:
        raise RegistryError("could not load Context Intake prototype catalog") from error
    if not isinstance(payload, dict) or set(payload) != {"categories"} or not isinstance(payload["categories"], list):
        raise RegistryError("prototype catalog must contain only a categories array")
    result = []
    seen = set()
    for index, item in enumerate(payload["categories"]):
        if not isinstance(item, dict) or set(item) != {"category_id", "prototypes"}:
            raise RegistryError(f"prototype category[{index}] must contain category_id and prototypes")
        category_id, values = item["category_id"], item["prototypes"]
        if not isinstance(category_id, str) or not category_id.strip() or category_id in seen:
            raise RegistryError(f"prototype category[{index}] has an invalid or duplicate category_id")
        if not isinstance(values, list) or not values or any(not isinstance(value, str) or not value.strip() for value in values):
            raise RegistryError(f"prototypes for {category_id} must be a non-empty string array")
        seen.add(category_id)
        result.append(IntakePrototypeCategory(category_id, tuple(values)))
    expected = {item.category_id for item in load_category_registry().categories}
    if seen != expected:
        raise RegistryError("prototype category IDs do not match the category registry")
    return tuple(result)
