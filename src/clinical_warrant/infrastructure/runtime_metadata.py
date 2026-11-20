"""Runtime package metadata used in reproducibility reports."""

from importlib.metadata import PackageNotFoundError, version


def installed_version(distribution: str) -> str | None:
    try:
        return version(distribution)
    except PackageNotFoundError:
        return None


def core_dependency_versions() -> dict[str, str | None]:
    return {
        "sentence-transformers": installed_version("sentence-transformers"),
        "transformers": installed_version("transformers"),
        "torch": installed_version("torch"),
    }
