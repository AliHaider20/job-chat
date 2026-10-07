import pytest

from prompts import ACTIONS, NO_JD_PLACEHOLDER, build_qa_prompt, render_system_prompt


def test_every_action_has_a_label_and_an_instruction():
    assert set(ACTIONS) == {"review", "ats", "cover_letter"}
    for label, instruction in ACTIONS.values():
        assert label.strip()
        assert len(instruction) > 200


def test_actions_handle_a_missing_job_description():
    for _, instruction in ACTIONS.values():
        assert "no job description is loaded" in instruction.lower()


def test_ats_action_does_not_ask_the_model_to_do_arithmetic():
    """Scoring moved to Python; the prompt must not reintroduce it."""
    _, instruction = ACTIONS["ats"]
    assert "Do not compute a score" in instruction


def test_ats_action_has_no_inclusion_list_of_technologies():
    """An 'INCLUDE: Python, Kubernetes, ...' list was once extracted as if it were
    the job description. Technology names may appear only inside matching rules,
    which are explicitly flagged as illustrations."""
    _, instruction = ACTIONS["ats"]
    assert "INCLUDE:" not in instruction
    assert "They are not keywords to look for" in instruction
    assert "ONLY from the text inside the <job_description>" in instruction


class TestBrevityDefaults:
    """Chat answers are capped, but the preset actions run long by design and
    inherit the same system prompt, so the cap has to yield to them."""

    def test_the_chat_prompts_cap_their_length(self):
        from prompts import QA_SYSTEM_PROMPT, RAG_SYSTEM_PROMPT

        for prompt in (QA_SYSTEM_PROMPT, RAG_SYSTEM_PROMPT):
            assert "Ceiling of about" in prompt

    def test_a_requested_format_overrides_the_cap(self):
        """Without this, the 150-word ceiling would truncate a cover letter."""
        from prompts import QA_SYSTEM_PROMPT

        assert "that format wins and the length ceiling below does not apply" in QA_SYSTEM_PROMPT

    def test_the_actions_that_run_long_still_state_their_own_format(self):
        from prompts import COVER_LETTER, DETAILED_REVIEW

        assert "EXACTLY FOUR paragraphs" in COVER_LETTER
        assert "Use these headings" in DETAILED_REVIEW


def test_system_prompt_renders_both_sources():
    rendered = render_system_prompt("PROFILE-MARKER", "JD-MARKER")
    assert "PROFILE-MARKER" in rendered
    assert "JD-MARKER" in rendered
    assert "{" not in rendered.split("<candidate_documents>")[0]


def test_system_prompt_substitutes_a_placeholder_for_an_absent_job_description():
    assert NO_JD_PLACEHOLDER in render_system_prompt("PROFILE", "")
    assert NO_JD_PLACEHOLDER in render_system_prompt("PROFILE", None)


def test_chat_prompt_orders_system_history_then_query():
    messages = build_qa_prompt().invoke({
        "context_text": "PROFILE",
        "job_description": "JD",
        "user_query": "QUESTION",
        "history": [],
    }).to_messages()

    assert [m.type for m in messages] == ["system", "human"]
    assert messages[-1].content == "QUESTION"


def test_chat_prompt_places_history_between_system_and_query():
    from langchain_core.messages import AIMessage, HumanMessage

    messages = build_qa_prompt().invoke({
        "context_text": "PROFILE",
        "job_description": "JD",
        "user_query": "NEW",
        "history": [HumanMessage(content="OLD"), AIMessage(content="REPLY")],
    }).to_messages()

    assert [m.type for m in messages] == ["system", "human", "ai", "human"]
    assert messages[-1].content == "NEW"


@pytest.mark.parametrize("key", ["review", "ats", "cover_letter"])
def test_action_instructions_survive_prompt_templating(key):
    """Braces in an instruction must not be parsed as template variables."""
    _, instruction = ACTIONS[key]
    messages = build_qa_prompt().invoke({
        "context_text": "PROFILE",
        "job_description": "JD",
        "user_query": instruction,
        "history": [],
    }).to_messages()
    assert messages[-1].content == instruction
