from importlib.resources import files
import json


def test_legacy_catalog_resources_are_packaged() -> None:
    data = files("clinical_warrant.data")

    for filename in ("prototypes.json", "rules.json", "mock_cases.json"):
        assert data.joinpath(filename).is_file()


def test_context_intake_categories_are_packaged(monkeypatch, tmp_path) -> None:
    monkeypatch.chdir(tmp_path)
    categories = files("clinical_warrant.data").joinpath(
        "context_intake", "categories"
    )
    resources = sorted(categories.iterdir(), key=lambda resource: resource.name)
    json_resources = [resource for resource in resources if resource.name.endswith(".json")]

    assert len(json_resources) == 14
    for resource in json_resources:
        with resource.open("r", encoding="utf-8") as stream:
            category = json.load(stream)
        assert category["category_id"]
        assert isinstance(category["fields"], dict)
