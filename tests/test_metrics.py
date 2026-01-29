import os

from fastapi.testclient import TestClient

import openbridge.config as config
from openbridge.app import create_app


def test_metrics_use_route_templates_for_path_labels():
    os.environ["OPENROUTER_API_KEY"] = "test"
    os.environ["OPENBRIDGE_STATE_BACKEND"] = "disabled"
    config._settings = None

    app = create_app()
    unique = "resp_metrics_unique_123"
    with TestClient(app) as client:
        resp = client.get(f"/v1/responses/{unique}")
        assert resp.status_code == 501

        metrics = client.get("/metrics")
        assert metrics.status_code == 200
        body = metrics.text

        assert 'path="/v1/responses/{response_id}"' in body
        assert f'path="/v1/responses/{unique}"' not in body
