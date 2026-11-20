"""Load packaged JSON catalog resources through importlib.resources."""

from __future__ import annotations

import json
from importlib.resources import files
from typing import Any

from clinical_warrant.shared.domain.catalog import (
    CatalogError,
    ResearchCatalog,
    validate_mock_cases,
    validate_prototypes,
    validate_rules,
)


def _load_json(resource_name: str) -> Any:
    resource = files("clinical_warrant.data").joinpath(resource_name)
    try:
        with resource.open("r", encoding="utf-8") as stream:
            return json.load(stream)
    except (OSError, json.JSONDecodeError) as error:
        raise CatalogError(f"could not load packaged resource {resource_name}") from error


def load_research_catalog() -> ResearchCatalog:
    """Load packaged research-only prototypes, rules, and cases."""
    prototypes = validate_prototypes(_load_json("prototypes.json"))
    rules = validate_rules(_load_json("rules.json"), prototypes)
    mock_cases = validate_mock_cases(_load_json("mock_cases.json"), rules)
    return ResearchCatalog(prototypes, rules, mock_cases)
