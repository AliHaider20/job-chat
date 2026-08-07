# job-chat

A private assistant for job applications. It answers questions about your background, drafts
interview answers, scores your profile against a job description, and writes cover letters —
grounded only in your own career documents.

## Setup

**1. Create the environment**

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows
source .venv/bin/activate       # macOS / Linux
pip install -r requirements.txt
```

**2. Configure `.env`** in the project root:

```ini
GROQ_API_KEY=gsk_...            # required
CANDIDATE_NAME=Your Name        # used in the system prompt

# Optional — Langfuse tracing. Tracing turns on only when both keys are present.
LANGFUSE_PUBLIC_KEY=pk-lf-...
LANGFUSE_SECRET_KEY=sk-lf-...
LANGFUSE_BASE_URL=https://us.cloud.langfuse.com
```

| Variable | Default | Purpose |
|---|---|---|
| `GROQ_API_KEY` | — | Required. Startup fails without it. |
| `CANDIDATE_NAME` | `the candidate` | Your name, used in the system prompt. |
| `DATA_DIR` | `data` | Folder holding your profile documents. Relative paths resolve against the project root. |
| `GROQ_MODEL` | `openai/gpt-oss-120b` | Model id. |
| `LLM_TEMPERATURE` | `0.0` | Sampling temperature. |
| `LLM_MAX_TOKENS` | `3000` | Response cap. See the token budget note below. |
| `MAX_HISTORY_TURNS` | `10` | Turns replayed to the model per request. |
| `CHECKPOINT_DB` | `checkpoints.sqlite` | Where conversation threads persist. |
| `LANGFUSE_PUBLIC_KEY` / `LANGFUSE_SECRET_KEY` | — | Enable tracing when both are set. |
| `LANGFUSE_HOST` or `LANGFUSE_BASE_URL` | `https://cloud.langfuse.com` | Langfuse region. Use the US host if your keys are US. |

**3. Add your documents.** Put your resume, project write-ups, and any other career documents
in `data/`. PDFs must be converted to Markdown first — the app reads only `.md`:

```bash
pip install -r requirements-ingest.txt   # docling, heavy; needed only for this step
python pdf_2_markdown_converter.py
```

**4. Run**

```bash
python app.py                   # http://localhost:7860
```

Paste a job description into the left panel, then chat or use the preset buttons.

## Project structure

```
job-chat/
├── app.py                       # Gradio UI and event wiring — the entry point
├── graph.py                     # LangGraph state graph, routing, LLM construction
├── prompts.py                   # System prompt and the three preset action instructions
├── ats.py                       # ATS schema and score calculation
├── dataloader.py                # Loads and concatenates the Markdown profile documents
├── config.py                    # Environment settings with validation
├── observability.py             # Langfuse tracing (optional, fails open)
├── pdf_2_markdown_converter.py  # One-off: PDF -> Markdown
├── data/                        # Your documents (gitignored)
├── tests/                       # Unit tests; no API calls
├── requirements.txt             # Runtime
├── requirements-ingest.txt      # PDF conversion only
└── requirements-dev.txt         # Tests
```

## Graph structure

One state graph with two nodes. Routing depends on `action` in the state: the ATS button needs
structured output, everything else streams as chat.

```mermaid
flowchart LR
    START([START]) -->|action == "ats"| ATS["ats_analysis<br/>structured output"]
    START -->|otherwise| ANSWER["answer<br/>streaming chat"]
    ATS --> FINISH([END])
    ANSWER --> FINISH
```

**State**

| Field | Purpose |
|---|---|
| `messages` | Conversation, appended via `add_messages`. |
| `job_description` | The pasted target role. |
| `action` | `ats`, `review`, `cover_letter`, or empty for free chat. |

**`answer`** renders the system prompt with your documents and the job description, replays the
last `MAX_HISTORY_TURNS` turns, and streams the reply. Older turns stay in the checkpoint but are
not resent, so cost per turn stays flat however long the conversation runs.

**`ats_analysis`** asks the model only to classify each job-description keyword as matched or
missing. The percentage is computed in Python from the list lengths, so the score cannot
contradict the lists it is derived from.

**Persistence.** A SQLite checkpointer keeps each thread on disk, so conversations survive a
restart. "Reset conversation" starts a new thread; the previous one is retained.

## Tests

```bash
pip install -r requirements-dev.txt
python -m pytest tests/ -q
```

Unit tests only — no API calls, no keys needed. They cover the ATS score arithmetic, config
validation, document loading, routing, history trimming, and prompt templating.

## Token budget

Groq's free tier allows 8,000 tokens per minute and 200,000 per day. Each request sends your full
profile (~3,900 tokens) plus the job description plus the reserved response budget, so a single
request costs roughly 7,000–8,000 tokens. That is about 25–40 requests per day. `LLM_MAX_TOKENS`
is capped at 3,000 to keep requests under the per-minute ceiling; raising it triggers HTTP 413.
