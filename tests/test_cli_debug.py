from pathlib import Path

import httpx
import respx
from typer.testing import CliRunner

from openbridge.cli import app
from openbridge.config import reset_settings_cache


def test_cli_debug_works_without_openrouter_api_key() -> None:
    reset_settings_cache()
    runner = CliRunner()
    with respx.mock:
        respx.get("http://127.0.0.1:8000/v1/debug/responses/resp_1").mock(
            return_value=httpx.Response(200, json={"response_id": "resp_1"})
        )
        result = runner.invoke(app, ["debug", "resp_1", "--raw"], env={"OPENROUTER_API_KEY": None})
        assert result.exit_code == 0
        assert '"response_id": "resp_1"' in result.stdout


def test_cli_debug_can_write_output_file() -> None:
    reset_settings_cache()
    runner = CliRunner()
    with runner.isolated_filesystem():
        with respx.mock:
            respx.get("http://127.0.0.1:8000/v1/debug/responses/resp_1").mock(
                return_value=httpx.Response(200, json={"response_id": "resp_1"})
            )
            result = runner.invoke(
                app,
                ["debug", "resp_1", "--raw", "--output", "bundle.json"],
                env={"OPENROUTER_API_KEY": None},
            )
            assert result.exit_code == 0
            assert Path("bundle.json").read_text(encoding="utf-8").strip()
