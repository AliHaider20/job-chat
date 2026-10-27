import logging
import sys
import uuid
from functools import partial
from pathlib import Path

import gradio as gr
from langchain_core.messages import AIMessage, HumanMessage
from openai import LengthFinishReasonError

from config import ConfigError, get_settings
from dataloader import convert_uploaded_documents
from graph import ATS_NODE, build_graph
from observability import build_run_config, flush
from skills import ACTIONS
import spaces

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("job-chat")

try:
    SETTINGS = get_settings(require_api_key=False)
except ConfigError as exc:
    sys.exit(f"Startup failed: {exc}")

SESSION_DATA = {}

@spaces.GPU
def temp():
    pass


def new_thread_id():
    return str(uuid.uuid4())


def discard_session_data(session_id):
    SESSION_DATA.pop(session_id, None)


def graph_for_session(session_id):
    session = SESSION_DATA.get(session_id)
    return session.get("graph") if session else None


def request_error_detail(exc):
    if isinstance(exc, LengthFinishReasonError):
        return (
            "The ATS report exceeded the model's response-token limit and was incomplete. "
            "Retry with a shorter job description, choose a model with a larger output "
            "limit, or raise ATS_MAX_TOKENS if the model supports it."
        )

    detail = str(exc)
    if "rate_limit" in detail or "429" in detail:
        return (
            "OpenRouter rate limit reached. Check your account's limits or wait "
            "before retrying."
        )
    if "413" in detail:
        return (
            "The request is too large for the OpenRouter model. Shorten the job "
            "description or lower LLM_MAX_TOKENS, then retry."
        )
    return detail


def connect_api_key(api_key, session_id):
    api_key = (api_key or "").strip()
    if not api_key:
        return "", "Paste your OpenRouter API key to connect."

    session = SESSION_DATA.setdefault(session_id, {})
    session["api_key"] = api_key
    profile_data = session.get("profile_data")
    if not profile_data:
        return "", "Key saved for this browser session. Upload your profile documents to continue."

    try:
        session["graph"] = build_graph(api_key=api_key, profile_data=profile_data)
    except Exception as exc:
        detail = str(exc).replace(api_key, "[redacted]")
        logger.error("Could not initialize an OpenRouter graph: %s", detail)
        return "", f"**Could not connect.** {detail}"

    return "", "Key and profile ready for this browser session. Send a message to verify the key."


def process_profile_upload(files, session_id):
    if not files:
        return "Choose one or more profile documents to upload."

    try:
        profile_data = convert_uploaded_documents(files)
    except Exception as exc:
        logger.error("Could not process profile upload: %s", exc)
        return f"**Upload failed.** {exc}"

    session = SESSION_DATA.setdefault(session_id, {})
    session["profile_data"] = profile_data
    session["graph"] = None
    api_key = session.get("api_key") or SETTINGS.openrouter_api_key

    if not api_key:
        return "Profile converted to Markdown and held for this session. Connect your OpenRouter key to continue."

    try:
        session["graph"] = build_graph(api_key=api_key, profile_data=profile_data)
    except Exception as exc:
        detail = str(exc).replace(api_key, "[redacted]")
        logger.error("Could not initialize the uploaded profile: %s", detail)
        return f"**Profile converted, but setup failed.** {detail}"

    names = ", ".join(Path(file_path).name for file_path in files)
    return f"**Profile ready.** Converted and loaded: {names}"


def clear_profile(session_id):
    session = SESSION_DATA.get(session_id)
    if session:
        session.pop("profile_data", None)
        session.pop("graph", None)
    return None, "Uploaded profile cleared from this session."


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


def run_action(key, chat_history, job_description, thread_id, session_id):
    _, instruction = ACTIONS[key]
    yield from stream_response(
        chat_history,
        job_description,
        thread_id,
        model_query=instruction,
        action=key,
        session_id=session_id,
    )


def stream_response(
    chat_history, job_description, thread_id, session_id=None, model_query=None, action=""
):
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
    if not job_description:
        chat_history = chat_history + [{
            "role": "assistant",
            "content": "Paste a job description in the **Target role** panel before asking a question or using a skill.",
        }]
        yield chat_history
        return

    graph = graph_for_session(session_id)
    if graph is None:
        chat_history = chat_history + [{
            "role": "assistant",
            "content": "Upload your profile documents and connect an OpenRouter API key before chatting.",
        }]
        yield chat_history
        return

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
        for mode, chunk in graph.stream(state, config, stream_mode=["messages", "updates"]):
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
        detail = request_error_detail(exc)
        chat_history[-1]["content"] = f"**Request failed.** {detail}"
        yield chat_history


with gr.Blocks(title="job-chat", fill_height=True, analytics_enabled=False) as demo:
    thread_id = gr.State(new_thread_id)
    session_id = gr.State(new_thread_id, delete_callback=discard_session_data)

    gr.Markdown("## Job chat")
    gr.Markdown("Ask about your background, draft interview answers, or test your fit against a role.")
    gr.Markdown("### OpenRouter API key")
    api_key_box = gr.Textbox(
        label="Paste your OpenRouter API key",
        placeholder="sk-or-v1-…",
        type="password",
        show_label=True,
    )
    connect_key_btn = gr.Button("Connect key")
    key_status = gr.Markdown(
        "Using the server-configured key."
        if SETTINGS.openrouter_api_key
        else "An API key is required to use the model. Your key is kept in server memory for this browser session and is not written to disk."
    )

    with gr.Row(equal_height=False):
        with gr.Column(scale=1):
            gr.Markdown("### Your profile")
            profile_upload = gr.File(
                label="Upload profile documents",
                file_count="multiple",
                file_types=[".pdf", ".docx", ".md", ".txt"],
                type="filepath",
            )
            profile_status = gr.Markdown(
                "Upload PDF, DOCX, Markdown, or text files. A new upload replaces the previous profile."
            )
            clear_profile_btn = gr.Button("Clear uploaded profile")
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
    connect_key_btn.click(
        connect_api_key,
        inputs=[api_key_box, session_id],
        outputs=[api_key_box, key_status],
    )
    profile_upload.upload(
        process_profile_upload,
        inputs=[profile_upload, session_id],
        outputs=profile_status,
    )
    clear_profile_btn.click(
        clear_profile,
        inputs=session_id,
        outputs=[profile_upload, profile_status],
    )

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
        inputs=[chatbot, jd_box, thread_id, session_id],
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
            inputs=[chatbot, jd_box, thread_id, session_id],
            outputs=chatbot,
        ))

    stop_btn.click(fn=None, cancels=generation_events, queue=False)


if __name__ == "__main__":
    logger.info("Model: %s | tracing: %s", SETTINGS.model, SETTINGS.tracing_enabled)
    try:
        demo.launch(server_name="0.0.0.0", server_port=7860, share=False)
    finally:
        flush()
