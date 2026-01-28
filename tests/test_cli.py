from typer.testing import CliRunner

from openbridge import __version__
from openbridge.cli import app
from openbridge.config import reset_settings_cache


def test_cli_version_does_not_require_api_key() -> None:
    reset_settings_cache()
    runner = CliRunner()
    result = runner.invoke(app, ["--version"], env={"OPENROUTER_API_KEY": None})
    assert result.exit_code == 0
    assert result.stdout.strip() == __version__
    assert result.stderr.strip() == ""


def test_cli_missing_api_key_shows_clean_error() -> None:
    reset_settings_cache()
    runner = CliRunner()
    result = runner.invoke(app, [], env={"OPENROUTER_API_KEY": None})
    assert result.exit_code == 1
    assert "configuration error" in result.stderr.lower()
    assert "OPENROUTER_API_KEY" in result.stderr

