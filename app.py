import logging
import sys
import uuid

import gradio as gr
from langchain_core.messages import AIMessage, HumanMessage

from config import ConfigError, get_settings
from graph import build_graph
from observability import build_run_config, flush

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("job-chat")

try:
    SETTINGS = get_settings()
    GRAPH = build_graph()
except (ConfigError, FileNotFoundError) as exc:
    sys.exit(f"Startup failed: {exc}")


def new_thread_id():
    return str(uuid.uuid4())


def jd_status(job_description):
    if job_description and job_description.strip():
        return f"**Loaded** — {len(job_description.split())} words"
    return "*No job description. Fit questions need one.*"


def add_user_message(user_query, chat_history):
    if not user_query.strip():
        return "", chat_history
    return "", chat_history + [{"role": "user", "content": user_query}]


def stream_response(chat_history, job_description, thread_id):
    """Stream the assistant reply for the last user message."""
    if not chat_history or chat_history[-1]["role"] != "user":
        yield chat_history
        return

    job_description = (job_description or "").strip()
    state = {
        "messages": [HumanMessage(content=chat_history[-1]["content"])],
        "job_description": job_description,
    }
    config = build_run_config(thread_id, job_description)

    chat_history = chat_history + [{"role": "assistant", "content": ""}]
    try:
        for chunk, _meta in GRAPH.stream(state, config, stream_mode="messages"):
            if isinstance(chunk, AIMessage) and chunk.content:
                chat_history[-1]["content"] += chunk.content
                yield chat_history
    except Exception as exc:
        logger.exception("Request failed")
        chat_history[-1]["content"] = f"Request failed: {exc}"
        yield chat_history


with gr.Blocks(title="job-chat", fill_height=True, analytics_enabled=False) as demo:
    thread_id = gr.State(new_thread_id)

    gr.Markdown("## job-chat")
    gr.Markdown("Ask about your background, draft interview answers, or test your fit against a role.")

    with gr.Row(equal_height=False):
        with gr.Column(scale=1):
            gr.Markdown("### Target role")
            jd_box = gr.Textbox(
                lines=18,
                max_lines=18,
                placeholder="Paste the full job description here.",
                show_label=False,
            )
            jd_state = gr.Markdown(jd_status(""))
            clear_jd_btn = gr.Button("Clear job description")

        with gr.Column(scale=2):
            chatbot = gr.Chatbot(height=520, show_label=False, resizable=True)
            query_box = gr.Textbox(
                placeholder="Ask a question...",
                show_label=False,
                submit_btn=True,
            )
            clear_chat_btn = gr.Button("Reset conversation")

    jd_box.change(jd_status, inputs=jd_box, outputs=jd_state)
    clear_jd_btn.click(lambda: "", outputs=jd_box)

    # A new thread id starts a fresh checkpointed conversation; the old one stays on disk.
    clear_chat_btn.click(lambda: ([], new_thread_id()), outputs=[chatbot, thread_id])

    query_box.submit(
        add_user_message,
        inputs=[query_box, chatbot],
        outputs=[query_box, chatbot],
        queue=False,
    ).then(
        stream_response,
        inputs=[chatbot, jd_box, thread_id],
        outputs=chatbot,
    )


if __name__ == "__main__":
    logger.info("Model: %s | tracing: %s", SETTINGS.model, SETTINGS.tracing_enabled)
    try:
        demo.launch()
    finally:
        flush()
