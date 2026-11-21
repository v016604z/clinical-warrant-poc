import json
import os
import re
import sys
import types

import pytest

from clinical_warrant.shared.domain.catalog import PrototypeCategory
from clinical_warrant.shared.domain.contracts import QuestionType
from clinical_warrant.modules.classification import ClassifierError, QuestionClassifier as CoreQuestionClassifier
from clinical_warrant.modules.classification.application.classifier import (
    DEFAULT_THRESHOLD,
    _cosine_similarity,
)
from clinical_warrant.modules.classification.infrastructure.model_encoder import (
    MODEL_ID,
    MODEL_MAX_SEQUENCE_LENGTH,
    MODEL_REVISION,
    SentenceTransformerEncoder,
)
from clinical_warrant.modules.classification.infrastructure.prototype_cache import (
    FilePrototypeVectorCache,
    default_cache_dir,
)
from clinical_warrant.modules.classification.infrastructure import prototype_cache
from clinical_warrant.bootstrap.composition import build_warrant_engine


KNOWN_CATEGORIES = tuple(
    category for category in QuestionType if category is not QuestionType.UNKNOWN
)


def make_prototypes(suffix: str = "original") -> tuple[PrototypeCategory, ...]:
    return tuple(
        PrototypeCategory(category, category.value, (f"prototype:{category.value}:{suffix}",))
        for category in KNOWN_CATEGORIES
    )


def make_classifier(encoder, *, prototypes, threshold=DEFAULT_THRESHOLD, cache_dir=None):
    cache = FilePrototypeVectorCache(cache_dir) if cache_dir is not None else None
    return CoreQuestionClassifier(
        encoder, prototypes=prototypes, threshold=threshold, cache=cache
    )


def orthogonal_mapping(prototypes, query_vector):
    vectors = {
        "prototype:result_interpretation:original": [1.0, 0.0, 0.0, 0.0],
        "prototype:window_period:original": [0.0, 1.0, 0.0, 0.0],
        "prototype:exposure_risk:original": [0.0, 0.0, 1.0, 0.0],
        "prototype:prevention_education:original": [0.0, 0.0, 0.0, 1.0],
        "query": query_vector,
    }
    return vectors


class FakeEncoder:
    def __init__(self, vectors, *, model_id="fake/model", revision="rev-a", failure=None):
        self.vectors = vectors
        self.model_id = model_id
        self.revision = revision
        self.failure = failure
        self.calls = []

    def encode(self, texts):
        self.calls.append(tuple(texts))
        if self.failure is not None:
            raise self.failure
        return [self.vectors[text] for text in texts]


def test_model_identity_is_an_immutable_hub_revision() -> None:
    assert re.fullmatch(r"[0-9a-f]{40}", MODEL_REVISION)


def test_cache_uses_configured_default_directory(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("CLINICAL_WARRANT_CACHE", str(tmp_path))

    cache = FilePrototypeVectorCache()

    assert default_cache_dir() == tmp_path
    assert cache.cache_file == tmp_path / "prototype-vectors.json"


def test_cache_atomic_write_failure_cleans_temporary_file(monkeypatch, tmp_path) -> None:
    cache = FilePrototypeVectorCache(tmp_path)

    def fail_replace(*args):
        raise OSError("synthetic replace failure")

    monkeypatch.setattr(prototype_cache.os, "replace", fail_replace)
    with pytest.raises(ClassifierError, match="could not write prototype cache"):
        cache.write({"model_id": "test"}, [[1.0, 0.0]])

    assert list(tmp_path.iterdir()) == []


def test_classifier_uses_highest_prototype_cosine_for_category(tmp_path) -> None:
    prototypes = make_prototypes()
    prototypes = (
        PrototypeCategory(
            prototypes[0].category,
            prototypes[0].label_zh,
            ("result-low", "result-high"),
        ),
        *prototypes[1:],
    )
    vectors = {
        "result-low": [0.0, 1.0, 0.0, 0.0],
        "result-high": [1.0, 0.0, 0.0, 0.0],
        "prototype:window_period:original": [0.0, 1.0, 0.0, 0.0],
        "prototype:exposure_risk:original": [0.0, 0.0, 1.0, 0.0],
        "prototype:prevention_education:original": [0.0, 0.0, 0.0, 1.0],
        "query": [0.9, 0.1, 0.0, 0.0],
    }
    encoder = FakeEncoder(vectors)
    classifier = make_classifier(encoder, prototypes=prototypes, cache_dir=tmp_path)

    result = classifier.classify("query")

    assert result.category is QuestionType.RESULT_INTERPRETATION
    assert result.similarity == pytest.approx(0.9 / (0.9**2 + 0.1**2) ** 0.5)


@pytest.mark.parametrize(
    ("winner", "query_vector"),
    [
        (QuestionType.RESULT_INTERPRETATION, [0.8, 0.6, 0.0, 0.0]),
        (QuestionType.WINDOW_PERIOD, [0.0, 0.8, 0.6, 0.0]),
        (QuestionType.EXPOSURE_RISK, [0.0, 0.0, 0.8, 0.6]),
        (QuestionType.PREVENTION_EDUCATION, [0.6, 0.0, 0.0, 0.8]),
    ],
)
def test_each_question_category_can_win(winner, query_vector, tmp_path) -> None:
    prototypes = make_prototypes()
    vectors = orthogonal_mapping(prototypes, query_vector)
    result = make_classifier(
        FakeEncoder(vectors), prototypes=prototypes, cache_dir=tmp_path
    ).classify("query")

    assert result.category is winner


def test_negative_similarity_below_threshold_returns_unknown(tmp_path) -> None:
    prototypes = make_prototypes()
    vectors = orthogonal_mapping(prototypes, [-1.0, 0.0, 0.0, 0.0])
    for category in KNOWN_CATEGORIES:
        vectors[f"prototype:{category.value}:original"] = [1.0, 0.0, 0.0, 0.0]
    encoder = FakeEncoder(vectors)
    classifier = make_classifier(encoder, prototypes=prototypes, cache_dir=tmp_path)

    result = classifier.classify("query")

    assert result.category is QuestionType.UNKNOWN
    assert result.similarity == pytest.approx(-1.0)


def test_similarity_equal_to_threshold_remains_known(tmp_path) -> None:
    prototypes = make_prototypes()
    encoder = FakeEncoder(orthogonal_mapping(prototypes, [1.0, 0.0, 0.0, 0.0]))
    classifier = make_classifier(
        encoder, threshold=1.0, prototypes=prototypes, cache_dir=tmp_path
    )

    result = classifier.classify("query")
    assert result.category is QuestionType.RESULT_INTERPRETATION
    assert result.similarity == 1.0


@pytest.mark.parametrize("threshold", [True, float("nan"), float("inf"), -1.01, 1.01])
def test_invalid_threshold_is_rejected(threshold, tmp_path) -> None:
    with pytest.raises(ValueError, match="threshold"):
        make_classifier(
            FakeEncoder({}), threshold=threshold, prototypes=make_prototypes(), cache_dir=tmp_path
        )


@pytest.mark.parametrize(
    ("prototype_vectors", "error_message"),
    [
        ([[1.0, 0.0], [0.0, 1.0], [1.0, 1.0]], "expected 4"),
        (
            [[1.0, 0.0], [0.0, 1.0], [1.0, 1.0, 1.0], [1.0, 1.0]],
            "inconsistent dimensions",
        ),
        ([[1.0, 0.0], [0.0, 1.0], [0.0, 0.0], [1.0, 1.0]], "zero norm"),
        (
            [[1.0, 0.0], [0.0, 1.0], [1.0, 1.0], [float("nan"), 1.0]],
            "non-finite",
        ),
        ([[1.0, 0.0], [0.0, 1.0], [1.0, 1.0], [False, 1.0]], "non-numeric"),
    ],
)
def test_invalid_prototype_vector_output_is_rejected(
    prototype_vectors, error_message, tmp_path
) -> None:
    prototypes = make_prototypes()
    encoder = FakeEncoder({})
    encoder.encode = lambda texts: prototype_vectors
    classifier = make_classifier(encoder, prototypes=prototypes, cache_dir=tmp_path)

    with pytest.raises(ClassifierError, match=error_message):
        classifier.classify("query")


@pytest.mark.parametrize(
    "query_vector",
    [[0.0, 0.0, 0.0, 0.0], [float("inf"), 0.0, 0.0, 0.0], [1.0, 2.0]],
)
def test_invalid_query_vectors_are_rejected(query_vector, tmp_path) -> None:
    prototypes = make_prototypes()
    vectors = orthogonal_mapping(prototypes, query_vector)
    classifier = make_classifier(
        FakeEncoder(vectors), prototypes=prototypes, cache_dir=tmp_path
    )

    with pytest.raises(ClassifierError):
        classifier.classify("query")


def test_encoder_failure_is_reported_instead_of_unknown(tmp_path) -> None:
    prototypes = make_prototypes()
    encoder = FakeEncoder({}, failure=RuntimeError("encoder unavailable"))
    classifier = make_classifier(encoder, prototypes=prototypes, cache_dir=tmp_path)

    with pytest.raises(ClassifierError, match="prototype encoding failed"):
        classifier.classify("query")


def test_cache_hit_reuses_prototype_vectors_but_encodes_each_query(tmp_path) -> None:
    prototypes = make_prototypes()
    encoder_a = FakeEncoder(orthogonal_mapping(prototypes, [1.0, 0.0, 0.0, 0.0]))
    make_classifier(encoder_a, prototypes=prototypes, cache_dir=tmp_path).classify("query")
    assert len(encoder_a.calls) == 2  # prototype batch and query
    cache_text = (tmp_path / "prototype-vectors.json").read_text(encoding="utf-8")
    assert "query" not in cache_text

    encoder_b = FakeEncoder(orthogonal_mapping(prototypes, [0.0, 1.0, 0.0, 0.0]))
    result = make_classifier(
        encoder_b, prototypes=prototypes, cache_dir=tmp_path
    ).classify("query")

    assert len(encoder_b.calls) == 1
    assert encoder_b.calls[0] == ("query",)
    assert result.category is QuestionType.WINDOW_PERIOD
    assert not list(tmp_path.glob("*.tmp"))


@pytest.mark.parametrize("identity_change", ["model_id", "revision", "prototypes"])
def test_cache_invalidates_when_model_or_prototype_identity_changes(
    identity_change, tmp_path
) -> None:
    prototypes = make_prototypes()
    first = FakeEncoder(orthogonal_mapping(prototypes, [1.0, 0.0, 0.0, 0.0]))
    make_classifier(first, prototypes=prototypes, cache_dir=tmp_path).classify("query")

    if identity_change == "revision":
        second_prototypes = prototypes
        second = FakeEncoder(
            orthogonal_mapping(prototypes, [1.0, 0.0, 0.0, 0.0]), revision="rev-b"
        )
    elif identity_change == "model_id":
        second_prototypes = prototypes
        second = FakeEncoder(
            orthogonal_mapping(prototypes, [1.0, 0.0, 0.0, 0.0]), model_id="other/model"
        )
    else:
        second_prototypes = make_prototypes(suffix="changed")
        vectors = orthogonal_mapping(prototypes, [1.0, 0.0, 0.0, 0.0])
        vectors.update(
            {
                f"prototype:{category.value}:changed": vectors[
                    f"prototype:{category.value}:original"
                ]
                for category in KNOWN_CATEGORIES
            }
        )
        second = FakeEncoder(vectors)

    make_classifier(
        second, prototypes=second_prototypes, cache_dir=tmp_path
    ).classify("query")
    assert len(second.calls) == 2


@pytest.mark.parametrize("corrupt_bytes", [b"not-json", b"\xff\xfe"])
def test_corrupt_cache_is_rebuilt(tmp_path, corrupt_bytes) -> None:
    prototypes = make_prototypes()
    cache_file = tmp_path / "prototype-vectors.json"
    cache_file.write_bytes(corrupt_bytes)
    encoder = FakeEncoder(orthogonal_mapping(prototypes, [1.0, 0.0, 0.0, 0.0]))

    make_classifier(encoder, prototypes=prototypes, cache_dir=tmp_path).classify("query")

    assert len(encoder.calls) == 2
    assert json.loads(cache_file.read_text(encoding="utf-8"))["vectors"]


def test_malformed_cache_vectors_are_rebuilt(tmp_path) -> None:
    prototypes = make_prototypes()
    first = FakeEncoder(orthogonal_mapping(prototypes, [1.0, 0.0, 0.0, 0.0]))
    make_classifier(first, prototypes=prototypes, cache_dir=tmp_path).classify("query")
    cache_file = tmp_path / "prototype-vectors.json"
    payload = json.loads(cache_file.read_text(encoding="utf-8"))
    payload["vectors"][0] = [0.0, 0.0, 0.0, 0.0]
    cache_file.write_text(json.dumps(payload), encoding="utf-8")

    second = FakeEncoder(orthogonal_mapping(prototypes, [0.0, 1.0, 0.0, 0.0]))
    make_classifier(second, prototypes=prototypes, cache_dir=tmp_path).classify("query")

    assert len(second.calls) == 2


def test_real_encoder_missing_dependency_has_clear_error(monkeypatch, tmp_path) -> None:
    monkeypatch.setitem(sys.modules, "sentence_transformers", None)

    with pytest.raises(ClassifierError, match="install the project model extra"):
        SentenceTransformerEncoder(cache_dir=tmp_path)


def test_sentence_transformer_adapter_pins_cpu_backend_revision_and_length(
    monkeypatch, tmp_path
) -> None:
    calls = {}

    class Model:
        max_seq_length = 512

        def encode(self, texts, **kwargs):
            return FakeArray([[1.0, 0.0] for _ in texts])

    class FakeArray:
        def __init__(self, values):
            self.values = values

        def tolist(self):
            return self.values

    def sentence_transformer(model_id, **kwargs):
        calls["model_id"] = model_id
        calls.update(kwargs)
        return Model()

    module = types.ModuleType("sentence_transformers")
    module.SentenceTransformer = sentence_transformer
    monkeypatch.setitem(sys.modules, "sentence_transformers", module)

    adapter = SentenceTransformerEncoder(cache_dir=tmp_path)

    assert calls == {
        "model_id": MODEL_ID,
        "revision": MODEL_REVISION,
        "device": "cpu",
        "backend": "torch",
        "cache_folder": str(tmp_path / "hub"),
    }
    assert adapter._model.max_seq_length == MODEL_MAX_SEQUENCE_LENGTH
    assert adapter.encode(["query"]) == [[1.0, 0.0]]


def test_real_encoder_import_runtime_failure_has_clear_error(monkeypatch, tmp_path) -> None:
    import builtins

    original_import = builtins.__import__

    def failing_import(name, *args, **kwargs):
        if name == "sentence_transformers":
            raise OSError("torch DLL could not load")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", failing_import)
    with pytest.raises(ClassifierError, match="model extra") as error:
        SentenceTransformerEncoder(cache_dir=tmp_path)
    assert isinstance(error.value.__cause__, OSError)


def test_bootstrap_validates_threshold_before_loading_adapter(monkeypatch) -> None:
    def should_not_load(*args, **kwargs):
        pytest.fail("invalid threshold must fail before model loading")

    monkeypatch.setattr(
        "clinical_warrant.bootstrap.composition.SentenceTransformerEncoder",
        should_not_load,
    )
    with pytest.raises(ValueError, match="threshold"):
        build_warrant_engine(threshold=True)


@pytest.mark.parametrize(
    ("left", "right", "expected"),
    [
        ([1e308, 1e308], [1e308, 1e308], 1.0),
        ([1e308, 0.0], [-1e308, 0.0], -1.0),
        ([1e-308, 1e-308], [1e-308, 1e-308], 1.0),
        ([1e-308, 0.0], [-1e-308, 0.0], -1.0),
    ],
)
def test_cosine_is_stable_for_extreme_finite_vectors(left, right, expected) -> None:
    assert _cosine_similarity(left, right) == pytest.approx(expected)


@pytest.mark.skipif(
    os.environ.get("RUN_SENTENCE_TRANSFORMER_SMOKE") != "1",
    reason="set RUN_SENTENCE_TRANSFORMER_SMOKE=1 to download/load the pinned real model",
)
def test_real_encoder_chinese_smoke() -> None:
    classifier = build_warrant_engine().classifier
    result = classifier.classify("有哪些預防愛滋感染的方式？")

    assert result.category is QuestionType.PREVENTION_EDUCATION
    assert result.similarity is not None
