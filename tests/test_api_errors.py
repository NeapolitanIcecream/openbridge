import os

from fastapi.testclient import TestClient

import openbridge.config as config
from openbridge.app import create_app


def test_http_exception_returns_openai_error_shape():
    os.environ["OPENROUTER_API_KEY"] = "test"
    os.environ["OPENBRIDGE_STATE_BACKEND"] = "disabled"
    config._settings = None

    app = create_app()
    with TestClient(app) as client:
        resp = client.get("/v1/responses/resp_1")
        assert resp.status_code == 501
        data = resp.json()
        assert "error" in data
        assert data["error"]["message"] == "State store is disabled"


def test_validation_error_returns_openai_error_shape():
    os.environ["OPENROUTER_API_KEY"] = "test"
    os.environ["OPENBRIDGE_STATE_BACKEND"] = "disabled"
    config._settings = None

    app = create_app()
    with TestClient(app) as client:
        resp = client.post("/v1/responses", json={"oops": True})
        assert resp.status_code == 422
        data = resp.json()
        assert "error" in data
