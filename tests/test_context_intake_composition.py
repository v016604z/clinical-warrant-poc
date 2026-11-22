"""Composition wiring checks for injected Context Intake ports."""

from types import SimpleNamespace

import pytest

from clinical_warrant.bootstrap.composition import build_context_intake_service
from clinical_warrant.modules.context_intake.domain.category_registry import validate_category_registry


def registry():
    return validate_category_registry([{
        "category_id": "test_category",
        "category_name": "測試",
        "fields": {"note": {"type": "string", "description": "文字"}},
    }])


def test_custom_registry_requires_matching_injected_classifier():
    custom = registry()
    extractor = object()
    with pytest.raises(ValueError, match="custom registry requires"):
        build_context_intake_service(extractor=extractor, registry=custom)

    classifier = SimpleNamespace(catalog_version=custom.version)
    service = build_context_intake_service(
        extractor=extractor, registry=custom, classifier=classifier,
    )
    assert service.registry is custom
    assert service.classifier is classifier

    stale = SimpleNamespace(catalog_version="different-version")
    with pytest.raises(ValueError, match="does not match"):
        build_context_intake_service(extractor=extractor, registry=custom, classifier=stale)
