import app


def test_chat_without_job_description_does_not_access_the_graph(monkeypatch):
    def graph_must_not_be_requested(_session_id):
        raise AssertionError("A model graph must not be accessed without a job description.")

    monkeypatch.setattr(app, "graph_for_session", graph_must_not_be_requested)

    result = list(app.stream_response(
        [{"role": "user", "content": "Tell me about my experience"}],
        " \n ",
        "thread-id",
        "session-id",
    ))

    assert len(result) == 1
    assert "Paste a job description" in result[0][-1]["content"]


def test_upload_builds_a_per_session_graph(monkeypatch, tmp_path):
    markdown_file = tmp_path / "resume.md"
    markdown_file.write_text("# Resume", encoding="utf-8")
    build_calls = []
    monkeypatch.setattr(app, "convert_uploaded_documents", lambda _files: "# Profile")
    monkeypatch.setattr(
        app,
        "build_graph",
        lambda **kwargs: build_calls.append(kwargs) or "compiled-graph",
    )
    monkeypatch.setitem(app.SESSION_DATA, "upload-test-session", {})

    status = app.process_profile_upload(
        [str(markdown_file)], "upload-test-session"
    )

    assert "Profile ready" in status
    assert build_calls == [{
        "api_key": app.SETTINGS.openrouter_api_key,
        "profile_data": "# Profile",
    }]
    assert app.graph_for_session("upload-test-session") == "compiled-graph"
