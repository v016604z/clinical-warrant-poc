import pytest

from clinical_warrant.modules.context_intake.domain.category_registry import (
    RegistryError,
    validate_category_registry,
)


def categories():
    return [
        {"category_id": "one_category", "category_name": "第一類", "fields": {
            "shared_key": {"type": "string", "description": "文字"},
        }},
        {"category_id": "two_category", "category_name": "第二類", "fields": {}},
    ]


def test_validation_allows_empty_fields_and_produces_reproducible_version():
    raw = categories()

    first = validate_category_registry(raw)
    second = validate_category_registry(raw)

    assert first == second
    assert first.categories[1].fields == {}
    assert len(first.version) == 64


@pytest.mark.parametrize("mutate, message", [
    (lambda rows: rows[0].update(extra=True), "exactly"),
    (lambda rows: rows[0].update(category_id="Not_Snake"), "snake_case"),
    (lambda rows: rows[1].update(category_id=rows[0]["category_id"]), "duplicate"),
    (lambda rows: rows[1].update(fields={"shared_key": {"type": "integer", "description": "數值"}}), "conflicting definitions"),
    (lambda rows: rows[0]["fields"]["shared_key"].update(type="number"), "unsupported"),
    (lambda rows: rows[0]["fields"]["shared_key"].update(extra=True), "exactly"),
    (lambda rows: rows[1].update(fields={"shared_key": {"type": "string", "description": "不同描述"}}), "conflicting definitions"),
])
def test_validation_rejects_invalid_registry(mutate, message):
    raw = categories()
    mutate(raw)

    with pytest.raises(RegistryError, match=message):
        validate_category_registry(raw)


def test_registry_version_is_independent_of_category_order():
    raw = categories()

    assert validate_category_registry(raw).version == validate_category_registry(list(reversed(raw))).version


def test_registry_lookup_rejects_unknown_id():
    registry = validate_category_registry(categories())

    assert registry.get("one_category").category_id == "one_category"
    with pytest.raises(RegistryError, match="unknown category_id"):
        registry.get("not_registered")


def test_category_fields_are_immutable():
    registry = validate_category_registry(categories())

    with pytest.raises(TypeError):
        registry.categories[0].fields["another"] = registry.categories[0].fields["shared_key"]


def test_packaged_registry_loads_and_rejects_file_set_or_filename_mismatch(monkeypatch):
    from clinical_warrant.modules.context_intake.infrastructure import category_registry as loader

    source = [
        {"category_id": category_id, "category_name": category_id, "fields": {}}
        for category_id in loader.CATEGORY_IDS
    ]

    class Resource:
        def __init__(self, name="", document=None):
            self.name = name
            self.document = document

        def joinpath(self, *parts):
            return Resource(parts[-1])

        def iterdir(self):
            return [Resource(f"{category_id}.json") for category_id in loader.CATEGORY_IDS]

        def is_file(self):
            return self.name.endswith(".json")

        def open(self, *_args, **_kwargs):
            import io
            return io.StringIO(__import__("json").dumps(source[loader.CATEGORY_IDS.index(self.name[:-5])]))

    monkeypatch.setattr(loader, "files", lambda _anchor: Resource())
    loaded = loader.load_category_registry()
    assert len(loaded.categories) == 14

    source[0]["category_id"] = "wrong_id"
    with pytest.raises(RegistryError, match="does not match filename"):
        loader.load_category_registry()
    source[0]["category_id"] = loader.CATEGORY_IDS[0]

    monkeypatch.setattr(loader, "files", lambda _anchor: Resource())
    original_iterdir = Resource.iterdir
    monkeypatch.setattr(Resource, "iterdir", lambda self: original_iterdir(self) + [Resource("extra.json")])
    with pytest.raises(RegistryError, match="do not match"):
        loader.load_category_registry()


def test_public_loader_reads_packaged_fourteen_categories():
    from clinical_warrant.modules.context_intake import load_category_registry

    registry = load_category_registry()

    assert len(registry.categories) == 14
    assert registry.get("hiv_basics").fields == {}
    assert len(registry.version) == 64


def test_exposure_datetime_is_shared_by_five_runtime_categories_and_changes_registry_version():
    from clinical_warrant.modules.context_intake import load_category_registry

    registry = load_category_registry()
    shared_categories = (
        "personal_exposure_risk", "pep_post_exposure", "symptom_questions",
        "window_period", "test_result_interpretation",
    )
    field = registry.get("personal_exposure_risk").fields["exposure_datetime"]

    for category_id in shared_categories:
        assert registry.get(category_id).fields["exposure_datetime"] == field
    for category_id in ("window_period", "test_result_interpretation"):
        assert "last_possible_exposure_date" not in registry.get(category_id).fields

    previous_schema = []
    for category in registry.categories:
        fields = {
            key: {"type": value.type, "description": value.description}
            for key, value in category.fields.items()
        }
        if category.category_id in ("window_period", "test_result_interpretation"):
            definition = fields.pop("exposure_datetime")
            fields["last_possible_exposure_date"] = definition
        previous_schema.append({
            "category_id": category.category_id,
            "category_name": category.category_name,
            "fields": fields,
        })

    assert validate_category_registry(previous_schema).version != registry.version


def test_loader_rejects_duplicate_json_member(monkeypatch):
    from clinical_warrant.modules.context_intake.infrastructure import category_registry as loader

    class Resource:
        def __init__(self, name=""):
            self.name = name

        def joinpath(self, *parts):
            return Resource(parts[-1])

        def iterdir(self):
            return [Resource(f"{category_id}.json") for category_id in loader.CATEGORY_IDS]

        def is_file(self):
            return True

        def open(self, *_args, **_kwargs):
            import io
            text = '{"category_id":"harm_reduction","category_name":"X","fields":{"x":{"type":"string","description":"a","description":"b"}}}'
            return io.StringIO(text)

    monkeypatch.setattr(loader, "files", lambda _anchor: Resource())
    with pytest.raises(RegistryError, match="duplicate JSON key"):
        loader.load_category_registry()
