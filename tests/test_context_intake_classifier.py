"""Tests for the isolated 14-category Context Intake classifier."""

import json
import math

import pytest

from clinical_warrant.bootstrap.composition import build_intake_question_classifier
from clinical_warrant.modules.classification.infrastructure.prototype_cache import FilePrototypeVectorCache
from clinical_warrant.modules.context_intake import (
    IntakeClassificationResult,
    IntakeQuestionClassifier,
    load_category_registry,
    load_intake_prototype_catalog,
)


class FakeEncoder:
    model_id = "fake/intake"
    revision = "revision-a"

    def __init__(self, vectors):
        self.vectors = vectors
        self.calls = []

    def encode(self, texts):
        self.calls.append(tuple(texts))
        return [self.vectors[text] for text in texts]


def make_vectors(prototypes, *, query=(1.0, 0.0)):
    vectors = {}
    for index, category in enumerate(prototypes):
        angle = 2 * math.pi * index / len(prototypes)
        vector = (math.cos(angle), math.sin(angle))
        for text in category.prototypes:
            vectors[text] = vector
    vectors["query"] = query
    return vectors


def test_prototype_catalog_matches_registry_ids():
    registry = load_category_registry()
    prototypes = load_intake_prototype_catalog()

    assert {item.category_id for item in prototypes} == {
        item.category_id for item in registry.categories
    }
    assert len(prototypes) == 14


def test_classifier_returns_distinct_top_two_and_unknown_keeps_scores(tmp_path):
    registry = load_category_registry()
    prototypes = load_intake_prototype_catalog()
    classifier = IntakeQuestionClassifier(
        FakeEncoder(make_vectors(prototypes)), registry=registry,
        prototypes=prototypes, threshold=1.0,
        cache=FilePrototypeVectorCache(tmp_path / "context-intake"),
    )

    result = classifier.classify("query")

    assert result.top1_category_id == "harm_reduction"
    assert result.top1_similarity == pytest.approx(1.0)
    assert result.top2_category_id != result.top1_category_id
    assert result.top2_similarity <= result.top1_similarity
    assert result.is_unknown is False  # threshold equality is accepted
    assert result.model_id == "fake/intake"
    assert result.model_revision == "revision-a"
    assert result.catalog_version == registry.version
    assert len(classifier.prototype_sha256) == 64

    low_confidence = IntakeQuestionClassifier(
        FakeEncoder(make_vectors(prototypes, query=(0.3, 0.6))), registry=registry,
        prototypes=prototypes, threshold=1.0,
    ).classify("query")
    assert low_confidence.is_unknown is True
    assert low_confidence.top1_category_id
    assert low_confidence.top1_similarity is not None
    assert low_confidence.top2_category_id
    assert low_confidence.top2_similarity is not None


def test_prototype_cache_has_context_namespace_and_invalidates_on_identity_change(tmp_path):
    registry = load_category_registry()
    prototypes = load_intake_prototype_catalog()
    intake_cache = FilePrototypeVectorCache(tmp_path / "context-intake")
    first_encoder = FakeEncoder(make_vectors(prototypes))
    first = IntakeQuestionClassifier(first_encoder, registry=registry, prototypes=prototypes,
                                     threshold=0.6, cache=intake_cache)
    first.classify("query")
    assert (tmp_path / "context-intake" / "prototype-vectors.json").exists()
    assert not (tmp_path / "prototype-vectors.json").exists()
    payload = json.loads((tmp_path / "context-intake" / "prototype-vectors.json").read_text())
    assert payload["identity"]["namespace"] == "context-intake-14"
    assert payload["identity"]["catalog_version"] == registry.version
    assert payload["identity"]["prototype_sha256"] == first.prototype_sha256

    second_encoder = FakeEncoder(make_vectors(prototypes))
    IntakeQuestionClassifier(second_encoder, registry=registry, prototypes=prototypes,
                             threshold=0.6, cache=intake_cache).classify("query")
    assert len(second_encoder.calls) == 1  # cache hit: only query encoding

    changed_encoder = FakeEncoder(make_vectors(prototypes))
    changed_encoder.revision = "revision-b"
    IntakeQuestionClassifier(changed_encoder, registry=registry, prototypes=prototypes,
                             threshold=0.6, cache=intake_cache).classify("query")
    assert len(changed_encoder.calls) == 2


def test_factory_requires_an_explicit_threshold_and_accepts_shared_encoder():
    with pytest.raises(TypeError):
        build_intake_question_classifier()

    prototypes = load_intake_prototype_catalog()
    encoder = FakeEncoder(make_vectors(prototypes))
    classifier = build_intake_question_classifier(threshold=0.6, encoder=encoder)
    assert classifier.encoder is encoder
    assert classifier.threshold == 0.6


@pytest.mark.parametrize("updates", [
    {"top2_category_id": "harm_reduction"},
    {"top2_similarity": 1.1},
    {"top1_similarity": 0.2, "top2_similarity": 0.3},
    {"is_unknown": 1},
])
def test_result_contract_rejects_invalid_values(updates):
    values = dict(top1_category_id="harm_reduction", top1_similarity=0.8,
                  top2_category_id="hiv_basics", top2_similarity=0.4,
                  is_unknown=False, model_id="model", model_revision="rev",
                  catalog_version="catalog")
    values.update(updates)

    with pytest.raises(ValueError):
        IntakeClassificationResult(**values)
