import pytest


@pytest.mark.asyncio
async def test_provider_endpoint_reports_config_without_exposing_credentials(
    client, monkeypatch
):
    from app.api.routes import assistant as assistant_routes
    from app.config import Settings

    monkeypatch.setattr(
        assistant_routes,
        "get_settings",
        lambda: Settings(
            llm_provider="openai",
            openai_api_key="must-not-be-returned",
            openai_model="configured-openai-model",
        ),
    )

    response = await client.get("/api/v1/assistant/provider")

    assert response.status_code == 200
    assert response.json() == {
        "provider": "openai",
        "model": "configured-openai-model",
    }
    assert "must-not-be-returned" not in response.text


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("provider", "url", "model", "key"),
    [
        ("groq", "https://api.groq.test/openai/v1/chat/completions", "groq-model", "groq-key"),
        ("openai", "https://api.openai.test/v1/chat/completions", "openai-model", "openai-key"),
    ],
)
async def test_assistant_dispatches_to_selected_openai_compatible_provider(
    db, monkeypatch, provider, url, model, key
):
    from app.config import Settings
    from app.services import assistant_service, openai_compatible_client

    requests = []

    class FakeResponse:
        status_code = 200

        def json(self):
            return {
                "choices": [{"message": {"content": "Chicken Biryani is 420 PKR."}}],
                "model": model,
            }

    class FakeAsyncClient:
        def __init__(self, *, timeout):
            assert timeout == 5

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc_value, traceback):
            return None

        async def post(self, request_url, *, headers, json):
            requests.append(
                {"url": request_url, "headers": headers, "json": json}
            )
            return FakeResponse()

    settings = Settings(
        llm_provider=provider,
        groq_api_key="groq-key",
        groq_model="groq-model",
        groq_base_url="https://api.groq.test/openai/v1",
        openai_api_key="openai-key",
        openai_model="openai-model",
        openai_base_url="https://api.openai.test/v1",
        llm_timeout_s=5,
    )
    monkeypatch.setattr(assistant_service, "get_settings", lambda: settings)
    monkeypatch.setattr(
        openai_compatible_client.httpx, "AsyncClient", FakeAsyncClient
    )

    result = await assistant_service.ask_concierge(
        db, message="How much is chicken biryani?", history=[]
    )

    assert result["reply"] == "Chicken Biryani is 420 PKR."
    assert result["model"] == model
    request = requests[0]
    assert request["url"] == url
    assert request["headers"]["Authorization"] == f"Bearer {key}"
    assert request["json"]["model"] == model
    assert request["json"]["messages"][0]["role"] == "system"
    assert request["json"]["messages"][-1]["content"] == "How much is chicken biryani?"
