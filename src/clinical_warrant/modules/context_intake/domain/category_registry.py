"""Category registry values and pure validation."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Mapping


class RegistryError(ValueError):
    """Packaged category registry data is invalid."""


@dataclass(frozen=True)
class CategoryField:
    type: str
    description: str


@dataclass(frozen=True)
class CategoryDefinition:
    category_id: str
    category_name: str
    fields: Mapping[str, CategoryField]


@dataclass(frozen=True)
class CategoryRegistry:
    categories: tuple[CategoryDefinition, ...]
    version: str

    def get(self, category_id: str) -> CategoryDefinition:
        """Return a registered category or reject an unknown ID."""
        for category in self.categories:
            if category.category_id == category_id:
                return category
        raise RegistryError(f"unknown category_id: {category_id}")


def validate_category_registry(raw_categories: list[Any]) -> CategoryRegistry:
    """Validate category documents and derive a stable version from their content."""
    parsed: list[CategoryDefinition] = []
    seen_ids: set[str] = set()
    shared_definitions: dict[str, tuple[str, str]] = {}
    canonical: list[dict[str, Any]] = []
    for index, raw in enumerate(raw_categories):
        if not isinstance(raw, dict) or set(raw) != {"category_id", "category_name", "fields"}:
            raise RegistryError(f"category[{index}] must contain exactly category_id, category_name, and fields")
        category_id = raw["category_id"]
        category_name = raw["category_name"]
        fields = raw["fields"]
        if not isinstance(category_id, str) or not re.fullmatch(r"[a-z][a-z0-9]*(?:_[a-z0-9]+)*", category_id):
            raise RegistryError(f"category[{index}].category_id must be snake_case")
        if category_id in seen_ids:
            raise RegistryError(f"duplicate category_id: {category_id}")
        seen_ids.add(category_id)
        if not isinstance(category_name, str) or not category_name.strip():
            raise RegistryError(f"{category_id}.category_name must be a non-empty string")
        if not isinstance(fields, dict):
            raise RegistryError(f"{category_id}.fields must be an object")
        parsed_fields: dict[str, CategoryField] = {}
        canonical_fields: dict[str, dict[str, str]] = {}
        for key, definition in fields.items():
            if not isinstance(key, str) or not re.fullmatch(r"[a-z][a-z0-9]*(?:_[a-z0-9]+)*", key):
                raise RegistryError(f"{category_id} field key must be snake_case: {key!r}")
            if not isinstance(definition, dict) or set(definition) != {"type", "description"}:
                raise RegistryError(f"{category_id}.{key} must contain exactly type and description")
            field_type, description = definition["type"], definition["description"]
            if not isinstance(field_type, str) or field_type not in {"string", "boolean", "integer"}:
                raise RegistryError(f"{category_id}.{key}.type is unsupported")
            if not isinstance(description, str) or not description.strip():
                raise RegistryError(f"{category_id}.{key}.description must be a non-empty string")
            definition_pair = (field_type, description)
            previous_definition = shared_definitions.setdefault(key, definition_pair)
            if previous_definition != definition_pair:
                raise RegistryError(f"field {key} has conflicting definitions")
            parsed_fields[key] = CategoryField(field_type, description)
            canonical_fields[key] = {"type": field_type, "description": description}
        parsed.append(CategoryDefinition(category_id, category_name, MappingProxyType(parsed_fields)))
        canonical.append({"category_id": category_id, "category_name": category_name, "fields": canonical_fields})
    if not parsed:
        raise RegistryError("category registry must not be empty")
    canonical.sort(key=lambda item: item["category_id"])
    content = json.dumps(canonical, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    version = hashlib.sha256(content).hexdigest()
    return CategoryRegistry(tuple(parsed), version)
