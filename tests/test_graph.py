"""Routing and history trimming. Neither needs a model call."""

import pytest
from langchain_core.messages import AIMessage, HumanMessage, trim_messages

from graph import route_action


@pytest.mark.parametrize(
    "action,expected",
    [
        ("ats", "ats_analysis"),
        ("review", "answer"),
        ("cover_letter", "answer"),
        ("", "answer"),
        (None, "answer"),
        ("unknown", "answer"),
    ],
)
def test_only_ats_routes_to_structured_output(action, expected):
    assert route_action({"action": action}) == expected


def test_missing_action_key_falls_back_to_chat():
    assert route_action({}) == "answer"


def conversation(turns):
    messages = []
    for i in range(turns):
        messages.append(HumanMessage(content=f"q{i}"))
        messages.append(AIMessage(content=f"a{i}"))
    return messages


def trim(messages, max_turns):
    return trim_messages(
        messages,
        max_tokens=max_turns * 2,
        token_counter=len,
        strategy="last",
        start_on="human",
        include_system=False,
    )


@pytest.mark.parametrize("turns", [1, 3, 5, 20])
def test_history_never_exceeds_the_window(turns):
    assert len(trim(conversation(turns), max_turns=3)) <= 6


def test_short_history_is_left_alone():
    messages = conversation(2)
    assert trim(messages, max_turns=5) == messages


def test_trimming_keeps_the_most_recent_turns():
    trimmed = trim(conversation(10), max_turns=2)
    assert trimmed[-1].content == "a9"
    assert "q0" not in [m.content for m in trimmed]


def test_window_starts_on_a_human_message():
    """Starting mid-exchange on an orphaned AI reply confuses the model."""
    assert isinstance(trim(conversation(10), max_turns=3)[0], HumanMessage)


def test_cost_plateaus_once_the_window_is_full():
    sizes = [len(trim(conversation(t), max_turns=3)) for t in range(1, 11)]
    assert sizes[-1] == sizes[-2] == 6
