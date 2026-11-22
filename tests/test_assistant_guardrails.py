"""The concierge must stay inside the Urban Tandoor domain."""
import pytest

from app.schemas.assistant import ChatTurn
from app.services.guardrails import (
    SCOPE_REFUSAL,
    GroundingContext,
    build_messages,
    is_in_scope,
    is_reply_in_scope,
    sanitize_message,
)

VOCABULARY = ("Chicken Biryani", "Beef Seekh Kabab", "Zinger Burger")


@pytest.mark.parametrize(
    "message",
    [
        "who is the CEO of Meta?",
        "tell me about Zuckerberg",
        "Who founded Microsoft?",
        "What is the weather in Karachi tomorrow?",
        "tell me a joke",
        "what is the capital of France?",
        "write a poem about rain",
    ],
)
def test_off_topic_questions_are_rejected(message):
    assert is_in_scope(message, VOCABULARY) is False


@pytest.mark.parametrize(
    "message",
    [
        "how much is chicken biryani?",
        "what is spicy and vegetarian?",
        "which branch is open now?",
        "do you have a family deal?",
        "hello",
        "recommend something for two people",
    ],
)
def test_restaurant_questions_are_allowed(message):
    assert is_in_scope(message, VOCABULARY) is True


def test_live_menu_vocabulary_beats_off_topic_words():
    # "Tesla" is a car maker, but it is also a real dish name in this fixture.
    assert is_in_scope("how much is the Tesla Burger?", ("Tesla Burger",)) is True


def test_mixed_question_is_rejected():
    message = "what is the price of biryani and who is the CEO of Meta?"
    assert is_in_scope(message, VOCABULARY) is False


def test_leaked_off_topic_reply_is_caught():
    assert is_reply_in_scope("Chicken Biryani is 420 PKR.", VOCABULARY) is True
    assert is_reply_in_scope("Mark Zuckerberg founded Meta.", VOCABULARY) is False
    assert is_reply_in_scope("The Tesla Burger is 990 PKR.", ("Tesla Burger",)) is True


def test_sanitize_message_collapses_whitespace_and_control_chars():
    assert sanitize_message("  what\x00is\t\nthe price?  ") == "what is the price?"


def test_build_messages_drops_off_topic_history():
    context = GroundingContext(
        text="BRANCHES: UTG-KHI-001, Karachi",
        vocabulary=VOCABULARY,
    )
    history = [
        ChatTurn(role="user", content="who is the CEO of Meta?"),
        ChatTurn(role="assistant", content="Mark Zuckerberg"),
        ChatTurn(role="user", content="how much is chicken biryani?"),
        ChatTurn(role="assistant", content="1280 PKR"),
    ]

    messages = build_messages(context, history, "is it spicy?")

    assert len(messages) == 2
    assert messages[1] == {"role": "user", "content": "is it spicy?"}
    system = messages[0]["content"]
    assert SCOPE_REFUSAL in system
    assert "Mark Zuckerberg" not in system
    assert "how much is chicken biryani?" in system
    assert "RESTAURANT DATA:" in system
    assert "EARLIER CONVERSATION" in system


@pytest.mark.asyncio
async def test_off_topic_chat_refused_without_provider(client):
    response = await client.post(
        "/api/v1/assistant/chat",
        json={"message": "who is the CEO of Meta?"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["reply"] == SCOPE_REFUSAL
    assert body["model"] == "scope-guard"
