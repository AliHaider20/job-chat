"""LangGraph application graph.

Today the graph is a single node, which is deliberate: it buys checkpointed
conversation state (threads that survive a restart) and gives the planned
cover-letter flow (draft -> critique -> revise) somewhere to live without a
rewrite.
"""

import sqlite3
from typing import Annotated, TypedDict

from langchain_core.messages import trim_messages
from langchain_groq import ChatGroq
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import START, StateGraph
from langgraph.graph.message import add_messages

from config import get_settings
from dataloader import ProfileLoader
from prompts import NO_JD_PLACEHOLDER, build_qa_prompt


class ChatState(TypedDict):
    # add_messages appends rather than overwrites, so each turn extends the thread.
    messages: Annotated[list, add_messages]
    job_description: str


def build_llm():
    settings = get_settings()
    return ChatGroq(
        api_key=settings.groq_api_key,
        model=settings.model,
        temperature=settings.temperature,
        max_tokens=settings.max_tokens,
    )


def build_graph():
    settings = get_settings()
    profile_data = ProfileLoader(settings.data_dir).load_and_format_markdown()
    chain = build_qa_prompt() | build_llm()

    # Two messages per turn (human + ai).
    max_history_messages = settings.max_history_turns * 2

    def answer(state: ChatState):
        # Older turns remain in the checkpoint; they are simply not resent,
        # which keeps per-turn cost flat instead of growing with the thread.
        history = trim_messages(
            state["messages"][:-1],
            max_tokens=max_history_messages,
            token_counter=len,
            strategy="last",
            start_on="human",
            include_system=False,
        )
        user_query = state["messages"][-1].content
        response = chain.invoke({
            "context_text": profile_data,
            "job_description": state.get("job_description") or NO_JD_PLACEHOLDER,
            "user_query": user_query,
            "history": history,
        })
        return {"messages": [response]}

    builder = StateGraph(ChatState)
    builder.add_node("answer", answer)
    builder.add_edge(START, "answer")

    # check_same_thread=False: Gradio serves requests from a pool of threads.
    conn = sqlite3.connect(str(settings.checkpoint_db), check_same_thread=False)
    return builder.compile(checkpointer=SqliteSaver(conn))
