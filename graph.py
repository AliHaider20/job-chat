"""LangGraph application graph.

Preset actions route by their action name and always receive the full profile.
Free-form chat is classified by the semantic router, which decides whether the
question needs no profile, retrieved excerpts, or all of it.
"""

import logging
import sqlite3
from functools import partial
from typing import Annotated, TypedDict

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, trim_messages
from langchain_groq import ChatGroq
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import START, StateGraph
from langgraph.graph.message import add_messages

import router as router_module
from ats import ATSAnalysis, format_ats_report
from config import get_settings
from dataloader import ProfileLoader
from embeddings import embed
from prompts import (
    NO_JD_PLACEHOLDER,
    build_qa_prompt,
    build_rag_prompt,
    build_trivial_prompt,
    render_system_prompt,
)
from retrieval import ProfileIndex, chunk_documents
from router import SemanticRouter

logger = logging.getLogger(__name__)


class ChatState(TypedDict):
    # add_messages appends rather than overwrites, so each turn extends the thread.
    messages: Annotated[list, add_messages]
    job_description: str
    # "ats" routes to structured keyword analysis; anything else answers as chat.
    action: str


NODE_BY_ROUTE = {
    router_module.TRIVIAL: "trivial_answer",
    router_module.SPECIFIC: "rag_answer",
    router_module.FULL: "answer",
}


def latest_text(messages) -> str:
    """Text of the most recent message.

    Message content survives a checkpoint round trip as a list of content
    blocks rather than a plain string, so `.content` cannot be used directly.
    `.text` returns a str for either shape.
    """
    if not messages:
        return ""
    return str(messages[-1].text)


def route_action(state, semantic_router=None) -> str:
    """Pick the node for this turn.

    Preset actions always get the full profile: a retrieval miss would silently
    corrupt an ATS score or a fit review. Only free-form chat is routed.
    """
    action = state.get("action")
    if action == "ats":
        return "ats_analysis"
    if action:
        return "answer"
    if semantic_router is None:
        return "answer"

    messages = state.get("messages") or []
    query = latest_text(messages)
    return NODE_BY_ROUTE[semantic_router.route(query)]


# Actions that write prose rather than analyse, and so use a higher temperature.
DRAFTING_ACTIONS = {"cover_letter"}


def build_llm(temperature=None):
    settings = get_settings()
    return ChatGroq(
        api_key=settings.groq_api_key,
        model=settings.model,
        temperature=settings.temperature if temperature is None else temperature,
        max_tokens=settings.max_tokens,
    )


def build_graph():
    settings = get_settings()
    profile_data = ProfileLoader(settings.data_dir).load_and_format_markdown()
    prompt = build_qa_prompt()
    llm = build_llm()
    chain = prompt | llm
    drafting_chain = prompt | build_llm(settings.drafting_temperature)
    rag_chain = build_rag_prompt() | llm
    trivial_chain = build_trivial_prompt() | llm
    structured_llm = llm.with_structured_output(ATSAnalysis)

    index = ProfileIndex(chunk_documents(profile_data), embed)
    semantic_router = SemanticRouter(embed)
    logger.info("Indexed %d profile chunks for retrieval.", len(index.chunks))

    # Two messages per turn (human + ai).
    max_history_messages = settings.max_history_turns * 2

    def recent_history(state):
        # Older turns remain in the checkpoint; they are simply not resent,
        # which keeps per-turn cost flat instead of growing with the thread.
        return trim_messages(
            state["messages"][:-1],
            max_tokens=max_history_messages,
            token_counter=len,
            strategy="last",
            start_on="human",
            include_system=False,
        )

    def answer(state: ChatState):
        active = drafting_chain if state.get("action") in DRAFTING_ACTIONS else chain
        response = active.invoke({
            "context_text": profile_data,
            "job_description": state.get("job_description") or NO_JD_PLACEHOLDER,
            "user_query": latest_text(state["messages"]),
            "history": recent_history(state),
        })
        return {"messages": [response]}

    def rag_answer(state: ChatState):
        """Narrow question: send only the excerpts that match it."""
        query = latest_text(state["messages"])
        response = rag_chain.invoke({
            "context_text": index.search_text(query, k=settings.retrieval_top_k),
            "user_query": query,
            "history": recent_history(state),
        })
        return {"messages": [response]}

    def trivial_answer(state: ChatState):
        """Greeting or pleasantry: no profile at all."""
        response = trivial_chain.invoke({
            "user_query": latest_text(state["messages"]),
            "history": recent_history(state),
        })
        return {"messages": [response]}

    def ats_analysis(state: ChatState):
        """Classify keywords with structured output, then score them in Python."""
        analysis = structured_llm.invoke([
            SystemMessage(content=render_system_prompt(profile_data, state.get("job_description"))),
            HumanMessage(content=latest_text(state["messages"])),
        ])
        return {"messages": [AIMessage(content=format_ats_report(analysis))]}

    builder = StateGraph(ChatState)
    builder.add_node("answer", answer)
    builder.add_node("rag_answer", rag_answer)
    builder.add_node("trivial_answer", trivial_answer)
    builder.add_node("ats_analysis", ats_analysis)
    builder.add_conditional_edges(
        START,
        partial(route_action, semantic_router=semantic_router),
        ["answer", "rag_answer", "trivial_answer", "ats_analysis"],
    )

    # check_same_thread=False: Gradio serves requests from a pool of threads.
    conn = sqlite3.connect(str(settings.checkpoint_db), check_same_thread=False)
    return builder.compile(checkpointer=SqliteSaver(conn))
