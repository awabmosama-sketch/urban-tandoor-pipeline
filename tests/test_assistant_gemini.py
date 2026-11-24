import pytest


@pytest.mark.asyncio
async def test_gemini_error_details_are_useful_without_exposing_api_key(monkeypatch):
    from app.services import gemini_client
    from app.services.gemini_client import (
        GeminiProviderError,
        generate_gemini_reply,
    )

    class FakeResponse:
        status_code = 404

        def json(self):
            return {
                "error": {
                    "message": "models/gemini-test was not found; key=test-key"
                }
            }

    class FakeAsyncClient:
        def __init__(self, *, timeout):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc_value, traceback):
            return None

        async def post(self, url, *, headers, json):
            return FakeResponse()

    monkeypatch.setattr(gemini_client.httpx, "AsyncClient", FakeAsyncClient)

    with pytest.raises(GeminiProviderError) as error:
        await generate_gemini_reply(
            [{"role": "system", "content": "system"}, {"role": "user", "content": "hi"}],
            api_key="test-key",
            model="gemini-test",
            base_url="https://example.test/v1beta",
            timeout_s=10,
        )

    assert str(error.value) == "Gemini returned HTTP 404. Check server logs."
    assert "models/gemini-test was not found" not in str(error.value)
    assert "test-key" not in str(error.value)


@pytest.mark.asyncio
async def test_assistant_sends_grounded_prompt_to_gemini(db, monkeypatch):
    from app.config import Settings
    from app.services import assistant_service, gemini_client

    requests = []
    response_text = "Chicken Biryani is 420 PKR."

    class FakeResponse:
        status_code = 200

        def json(self):
            return {
                "candidates": [
                    {"content": {"parts": [{"text": response_text}]}}
                ],
                "modelVersion": "gemini-test-version",
            }

    class FakeAsyncClient:
        def __init__(self, *, timeout):
            assert timeout == 7

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc_value, traceback):
            return None

        async def post(self, url, *, headers, json):
            requests.append({"url": url, "headers": headers, "json": json})
            return FakeResponse()

    monkeypatch.setattr(
        assistant_service,
        "get_settings",
        lambda: Settings(
            gemini_api_key="test-key",
            gemini_model="gemini-test-model",
            gemini_timeout_s=7,
        ),
    )
    monkeypatch.setattr(gemini_client.httpx, "AsyncClient", FakeAsyncClient)

    result = await assistant_service.ask_concierge(
        db, message="How much is chicken biryani?", history=[]
    )

    assert result["reply"] == "Chicken Biryani is 420 PKR."
    assert result["model"] == "gemini-test-version"
    assert isinstance(result["latency_ms"], int)
    assert result["latency_ms"] >= 0
    assert {
        "reply": "Chicken Biryani is 420 PKR.",
        "model": "gemini-test-version",
    } == {key: result[key] for key in ("reply", "model")}

    response_text = " ".join(["Biryani"] * 50)
    long_result = await assistant_service.ask_concierge(
        db, message="How much is chicken biryani?", history=[]
    )
    assert len(long_result["reply"].split()) <= 40
    assert long_result["reply"].endswith("...")

    request = requests[0]
    assert request["url"].endswith("/models/gemini-test-model:generateContent")
    assert request["headers"]["x-goog-api-key"] == "test-key"
    payload = request["json"]
    assert "ACTIVE MENU" in payload["systemInstruction"]["parts"][0]["text"]
    assert payload["contents"] == [
        {"role": "user", "parts": [{"text": "How much is chicken biryani?"}]}
    ]
    assert payload["generationConfig"]["maxOutputTokens"] == 96
