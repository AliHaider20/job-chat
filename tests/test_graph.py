"""Routing and history trimming. Neither needs a model call."""

import pytest
from langchain_core.messages import AIMessage, HumanMessage, trim_messages

from graph import latest_text, route_action


@pytest.mark.parametrize(
    "action,expected",
    [
        ("ats", "ats_analysis"),
        ("review", "skill_review"),
        ("cover_letter", "skill_cover_letter"),
        ("email", "skill_email"),
        ("", "answer"),
        (None, "answer"),
        ("not-a-skill", "answer"),
    ],
)
def test_each_skill_button_routes_to_its_own_node(action, expected):
    assert route_action({"action": action}) == expected


def test_missing_action_key_falls_back_to_chat():
    assert route_action({}) == "answer"


class StubRouter:
    def __init__(self, decision):
        self.decision = decision
        self.seen = []

    def route(self, query):
        self.seen.append(query)
        return self.decision


@pytest.mark.parametrize(
    "decision,expected",
    [
        ("trivial", "trivial_answer"),
        ("specific", "rag_answer"),
        ("full", "answer"),
        ("review", "skill_review"),
        ("ats", "ats_analysis"),
        ("cover_letter", "skill_cover_letter"),
        ("email", "skill_email"),
    ],
)
def test_free_chat_follows_the_semantic_router(decision, expected):
    state = {"action": "", "messages": [HumanMessage(content="a question")]}
    assert route_action(state, semantic_router=StubRouter(decision)) == expected


@pytest.mark.parametrize("action", ["review", "cover_letter", "email"])
def test_skill_buttons_bypass_the_router_and_keep_full_context(action):
    """A retrieval miss inside a review or cover letter would drop real evidence."""
    stub = StubRouter("trivial")
    state = {"action": action, "messages": [HumanMessage(content="hello")]}
    assert route_action(state, semantic_router=stub) == f"skill_{action}"
    assert stub.seen == []


def test_the_ats_action_never_reaches_the_router():
    """Retrieval could omit a skill and silently corrupt the score."""
    stub = StubRouter("specific")
    state = {"action": "ats", "messages": [HumanMessage(content="hi")]}
    assert route_action(state, semantic_router=stub) == "ats_analysis"
    assert stub.seen == []


def test_the_router_sees_the_latest_message():
    stub = StubRouter("full")
    state = {"action": "", "messages": [HumanMessage(content="old"), HumanMessage(content="newest")]}
    route_action(state, semantic_router=stub)
    assert stub.seen == ["newest"]


class TestContentBlocks:
    """Checkpointed messages come back with list content, not a plain string.

    Reading .content directly crashed the first real conversation with
    'list object has no attribute strip'.
    """

    def test_latest_text_reads_plain_string_content(self):
        assert latest_text([HumanMessage(content="hello")]) == "hello"

    def test_latest_text_reads_block_content(self):
        blocks = [HumanMessage(content=[{"type": "text", "text": "hi there"}])]
        assert latest_text(blocks) == "hi there"

    def test_latest_text_returns_a_real_string(self):
        text = latest_text([HumanMessage(content=[{"type": "text", "text": "x"}])])
        assert type(text) is str
        assert text.strip() == "x"

    def test_latest_text_handles_no_messages(self):
        assert latest_text([]) == ""

    def test_routing_survives_block_content(self):
        stub = StubRouter("specific")
        state = {"action": "", "messages": [HumanMessage(content=[{"type": "text", "text": "do I know Rust?"}])]}
        assert route_action(state, semantic_router=stub) == "rag_answer"
        assert stub.seen == ["do I know Rust?"]


def test_router_rejects_non_string_queries_without_crashing():
    from router import FULL, SemanticRouter
    from tests.test_router import REFERENCES, fake_embed

    router = SemanticRouter(fake_embed, references=REFERENCES)
    for bad in ([{"type": "text", "text": "hi"}], None, 42):
        assert router.route(bad) == FULL


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
