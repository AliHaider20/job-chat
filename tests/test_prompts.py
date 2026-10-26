from prompts import NO_JD_PLACEHOLDER, build_qa_prompt, render_system_prompt


class TestBrevityDefaults:
    """Chat answers are capped, but skills define their own formats and must not be."""

    def test_regular_chat_prompts_are_concise(self):
        from prompts import QA_SYSTEM_PROMPT, RAG_SYSTEM_PROMPT, TRIVIAL_SYSTEM_PROMPT

        assert len(QA_SYSTEM_PROMPT) < 1_000
        assert len(TRIVIAL_SYSTEM_PROMPT) < 250
        assert len(RAG_SYSTEM_PROMPT) < 500
        assert "default to 1–3 sentences" in QA_SYSTEM_PROMPT
        assert "one brief sentence" in TRIVIAL_SYSTEM_PROMPT
        assert "No profile is provided" in TRIVIAL_SYSTEM_PROMPT
        assert "Be direct and concise" in RAG_SYSTEM_PROMPT
        assert "no unrelated background" in RAG_SYSTEM_PROMPT
        assert "Do not treat missing excerpts as proof" in RAG_SYSTEM_PROMPT

    def test_the_skill_prompt_lets_the_skill_set_its_own_length(self):
        from prompts import SKILL_SYSTEM_PROMPT

        assert "overrides any default brevity" in SKILL_SYSTEM_PROMPT
        assert "Ceiling of about" not in SKILL_SYSTEM_PROMPT


class TestSkillPrompt:
    def test_renders_skill_profile_and_job_description(self):
        from prompts import render_skill_prompt

        rendered = render_skill_prompt("SKILL-MARKER", "PROFILE-MARKER", "JD-MARKER")
        for marker in ("SKILL-MARKER", "PROFILE-MARKER", "JD-MARKER"):
            assert marker in rendered

    def test_substitutes_a_placeholder_for_an_absent_job_description(self):
        from prompts import render_skill_prompt

        assert NO_JD_PLACEHOLDER in render_skill_prompt("S", "P", "")
        assert NO_JD_PLACEHOLDER in render_skill_prompt("S", "P", None)

    def test_braces_in_a_skill_are_not_parsed_as_placeholders(self):
        from prompts import build_skill_prompt

        messages = build_skill_prompt().invoke({
            "skill_text": "Use {curly} braces and {{double}} ones",
            "context_text": "PROFILE",
            "job_description": "JD",
            "user_query": "go",
            "history": [],
        }).to_messages()
        assert "Use {curly} braces and {{double}} ones" in messages[0].content
        assert [m.type for m in messages] == ["system", "human"]


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
