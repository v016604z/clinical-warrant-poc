"""Dependency rules for the layered modular monolith."""

import ast
from pathlib import Path


PACKAGE = Path(__file__).parents[1] / "src" / "clinical_warrant"
BUSINESS_MODULES = {"classification", "decision", "evaluation"}


def _imports_from_source(source: str, current_module: str):
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield alias.name, ()
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                package = current_module.split(".")[:-1]
                base = package[: len(package) - node.level + 1]
                module = ".".join([*base, *((node.module or "").split("."))]).rstrip(".")
            else:
                module = node.module or ""
            yield module, tuple(alias.name for alias in node.names)


def _imports(path: Path):
    relative = path.relative_to(PACKAGE).with_suffix("")
    parts = ["clinical_warrant", *relative.parts]
    current_module = ".".join(parts)
    yield from _imports_from_source(path.read_text(encoding="utf-8"), current_module)


def _public_api(module: str) -> set[str]:
    path = PACKAGE / "modules" / module / "__init__.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == "__all__" for target in node.targets
        ):
            return set(ast.literal_eval(node.value))
    raise AssertionError(f"{module} has no literal __all__ public API")


def _is_public_cross_import(target: str, imported: str, names: tuple[str, ...]) -> bool:
    public_module = f"clinical_warrant.modules.{target}"
    return imported == public_module and set(names).issubset(_public_api(target))


def test_shared_domain_does_not_depend_on_application_or_infrastructure() -> None:
    forbidden = ("clinical_warrant.modules", "clinical_warrant.infrastructure",
                 "clinical_warrant.interfaces", "clinical_warrant.bootstrap")
    domain_packages = [PACKAGE / "shared" / "domain", *((PACKAGE / "modules").glob("*"))]
    domain_files = [
        path
        for package in domain_packages
        for path in (package.rglob("*.py") if package.name != "domain" else package.glob("*.py"))
        if "domain" in path.parts
    ]
    for path in domain_files:
        for imported, _names in _imports(path):
            assert not imported.startswith(forbidden), f"{path.name} imports {imported}"


def test_application_does_not_depend_on_infrastructure_or_interfaces() -> None:
    forbidden = ("clinical_warrant.infrastructure", "clinical_warrant.interfaces",
                 "clinical_warrant.bootstrap", "clinical_warrant.catalog",
                 "clinical_warrant.classifier", "clinical_warrant.cli",
                 "clinical_warrant.contracts", "clinical_warrant.evaluation",
                 "clinical_warrant.warrant")
    for module in BUSINESS_MODULES:
        application = PACKAGE / "modules" / module / "application"
        for path in application.rglob("*.py"):
            for imported, _names in _imports(path):
                assert not imported.startswith(forbidden), (
                    f"{module} application {path.name} imports {imported}"
                )


def test_business_modules_do_not_import_each_others_internals() -> None:
    for module in BUSINESS_MODULES:
        root = PACKAGE / "modules" / module
        for path in root.rglob("*.py"):
            for imported, names in _imports(path):
                prefix = "clinical_warrant.modules."
                if not imported.startswith(prefix):
                    continue
                target = imported[len(prefix):].split(".", 1)[0]
                if target != module and target in BUSINESS_MODULES:
                    assert _is_public_cross_import(target, imported, names), (
                        f"{module} imports private path or names from {imported}: {names}"
                    )


def test_source_and_tests_do_not_import_removed_legacy_modules() -> None:
    legacy = tuple(
        f"clinical_warrant.{name}"
        for name in ("catalog", "classifier", "cli", "contracts", "evaluation", "warrant")
    )
    roots = [PACKAGE, Path(__file__).parent]
    for root in roots:
        for path in root.rglob("*.py"):
            if path == Path(__file__):
                continue
            if root == PACKAGE:
                imports = _imports(path)
            else:
                tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
                imports = (
                    (alias.name, ())
                    for node in ast.walk(tree)
                    if isinstance(node, ast.Import)
                    for alias in node.names
                )
                imports = list(imports) + [
                    (node.module or "", tuple(alias.name for alias in node.names))
                    for node in ast.walk(tree)
                    if isinstance(node, ast.ImportFrom) and node.level == 0
                ]
            for imported, _names in imports:
                assert not any(
                    imported == module or imported.startswith(module + ".") for module in legacy
                ), f"{path} imports removed module {imported}"


def test_import_checker_accepts_public_and_rejects_private_cross_module_imports() -> None:
    allowed = list(_imports_from_source(
        "from clinical_warrant.modules.decision import WarrantEngine",
        "clinical_warrant.modules.classification.application.fake",
    ))
    deep = list(_imports_from_source(
        "from clinical_warrant.modules.decision.domain.policy import decide",
        "clinical_warrant.modules.classification.application.fake",
    ))
    assert allowed == [("clinical_warrant.modules.decision", ("WarrantEngine",))]
    assert deep == [("clinical_warrant.modules.decision.domain.policy", ("decide",))]
    assert _is_public_cross_import("decision", *allowed[0])
    assert not _is_public_cross_import("decision", *deep[0])
    private_name = list(_imports_from_source(
        "from clinical_warrant.modules.decision import validate_rules",
        "clinical_warrant.modules.classification.application.fake",
    ))[0]
    assert not _is_public_cross_import("decision", *private_name)


def test_import_checker_resolves_relative_imports() -> None:
    imports = list(_imports_from_source(
        "from ...decision import WarrantEngine",
        "clinical_warrant.modules.classification.application.fake",
    ))
    assert imports == [("clinical_warrant.modules.decision", ("WarrantEngine",))]
    assert _is_public_cross_import("decision", *imports[0])
