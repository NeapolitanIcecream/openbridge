import httpx
import pytest
import respx

from openbridge.clients.openrouter import OpenRouterClient
from openbridge.config import Settings
from openbridge.services.upstream import call_with_retry


@pytest.mark.asyncio
@respx.mock
async def test_call_with_retry_success():
    settings = Settings(OPENROUTER_API_KEY="test")
    client = OpenRouterClient(settings)

    url = f"{settings.openrouter_base_url.rstrip('/')}/chat/completions"
    respx.post(url).mock(return_value=httpx.Response(200, json={"choices": []}))

    response = await call_with_retry(
        client=client,
        payload={"model": "openai/gpt-4.1", "messages": []},
        settings=settings,
    )

    assert response.status_code == 200
    await client.close()
