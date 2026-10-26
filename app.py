import logging
import sys
import uuid
from functools import partial

import gradio as gr
from langchain_core.messages import AIMessage, HumanMessage

from config import ConfigError, get_settings
from graph import build_graph
from observability import build_run_config, flush
from graph import ATS_NODE
from skills import ACTIONS

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


def show_action_label(label, chat_history):
    """Show the button's short label in the chat instead of its full instruction."""
    return chat_history + [{"role": "user", "content": f"**{label}**"}]


def run_action(key, chat_history, job_description, thread_id):
    _, instruction = ACTIONS[key]
    yield from stream_response(
        chat_history, job_description, thread_id, model_query=instruction, action=key
    )


def stream_response(chat_history, job_description, thread_id, model_query=None, action=""):
    """Stream the assistant reply for the last user message.

    model_query lets a skill button send its instruction to the model while the
    chat shows only a short label. The ATS node returns one structured report
    rather than a token stream, so its text arrives as a single update (a
    placeholder is shown meanwhile when the button asked for it). Every other
    node streams token by token, whether a button or the router chose it.
    """
    if not chat_history or chat_history[-1]["role"] != "user":
        yield chat_history
        return

    job_description = (job_description or "").strip()
    state = {
        "messages": [HumanMessage(content=model_query or chat_history[-1]["content"])],
        "job_description": job_description,
        "action": action,
    }
    config = build_run_config(thread_id, job_description)

    chat_history = chat_history + [{"role": "assistant", "content": ""}]
    try:
        if action == "ats":
            chat_history[-1]["content"] = "_Extracting and scoring keywords…_"
            yield chat_history

        streamed = False
        for mode, chunk in GRAPH.stream(state, config, stream_mode=["messages", "updates"]):
            if mode == "messages":
                message, meta = chunk
                # The ATS node's model call emits structured-output fragments, not prose.
                if meta.get("langgraph_node") == ATS_NODE:
                    continue
                if isinstance(message, AIMessage) and message.content:
                    if not streamed:
                        chat_history[-1]["content"] = ""
                        streamed = True
                    chat_history[-1]["content"] += message.content
                    yield chat_history
            elif mode == "updates":
                ats_update = chunk.get(ATS_NODE)
                if ats_update and ats_update.get("messages"):
                    chat_history[-1]["content"] = str(ats_update["messages"][-1].text)
                    yield chat_history
    except Exception as exc:
        logger.exception("Request failed")
        detail = str(exc)
        if "rate_limit" in detail or "429" in detail:
            detail = (
                "OpenRouter rate limit reached. Check your account's limits or wait "
                "before retrying."
            )
        elif "413" in detail:
            detail = (
                "The request is too large for the OpenRouter model. Shorten the job "
                "description or lower LLM_MAX_TOKENS, then retry."
            )
        chat_history[-1]["content"] = f"**Request failed.** {detail}"
        yield chat_history


with gr.Blocks(title="job-chat", fill_height=True, analytics_enabled=False) as demo:
    thread_id = gr.State(new_thread_id)

    gr.Markdown("## Job chat")
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
            with gr.Row():
                action_buttons = {
                    key: gr.Button(label, size="sm")
                    for key, (label, _) in ACTIONS.items()
                }

            chatbot = gr.Chatbot(height=520, show_label=False, resizable=True)
            with gr.Row():
                query_box = gr.Textbox(
                    placeholder="Ask a question...",
                    show_label=False,
                    submit_btn=True,
                    scale=5,
                )
                stop_btn = gr.Button("Stop", variant="stop", scale=1)
            clear_chat_btn = gr.Button("Reset conversation")

    jd_box.change(jd_status, inputs=jd_box, outputs=jd_state)
    clear_jd_btn.click(lambda: "", outputs=jd_box)

    # A new thread id starts a fresh checkpointed conversation; the old one stays on disk.
    clear_chat_btn.click(lambda: ([], new_thread_id()), outputs=[chatbot, thread_id])

    generation_events = []

    generation_events.append(query_box.submit(
        add_user_message,
        inputs=[query_box, chatbot],
        outputs=[query_box, chatbot],
        queue=False,
    ).then(
        stream_response,
        inputs=[chatbot, jd_box, thread_id],
        outputs=chatbot,
    ))

    for key, button in action_buttons.items():
        generation_events.append(button.click(
            partial(show_action_label, ACTIONS[key][0]),
            inputs=chatbot,
            outputs=chatbot,
            queue=False,
        ).then(
            partial(run_action, key),
            inputs=[chatbot, jd_box, thread_id],
            outputs=chatbot,
        ))

    stop_btn.click(fn=None, cancels=generation_events, queue=False)


if __name__ == "__main__":
    logger.info("Model: %s | tracing: %s", SETTINGS.model, SETTINGS.tracing_enabled)
    try:
        demo.launch()
    finally:
        flush()
