from importlib.metadata import version

import pytest

from clinical_warrant import __version__
from clinical_warrant.cli import main


def test_package_version_is_available() -> None:
    assert __version__ == version("clinical-warrant-poc")


def test_help_lists_reserved_commands(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as error:
        main(["--help"])

    assert error.value.code == 0
    output = capsys.readouterr().out
    assert "decide" in output
    assert "evaluate" in output
    assert "not implemented yet" in output


def test_reserved_command_fails_clearly(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as error:
        main(["decide", "--input", "unused.json"])

    assert error.value.code == 2
    assert "not implemented yet" in capsys.readouterr().err
