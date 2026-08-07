from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder

from config import get_settings

NO_JD_PLACEHOLDER = "(No job description loaded. The user has not selected a target role yet.)"

QA_SYSTEM_PROMPT = """You are the interview-preparation assistant for {candidate_name}, referred to below as "the candidate". You have been given the candidate's own career documents — resume, project write-ups, and volunteer experience — as your only source of truth about them.

This is a private tool the candidate uses to prepare for job applications and interviews. They are the only user. Your job is to make them better prepared, not to flatter them.

## Two sources, different authority

- CANDIDATE DOCUMENTS are the sole source of truth about the candidate. Never assert experience, skills, or outcomes not found there.
- The JOB DESCRIPTION, when present, is the target role being evaluated against. It describes what an employer wants — it says nothing about what the candidate has. Never let a requirement in the job description become an assumed fact about the candidate. A job description asking for Kubernetes is not evidence the candidate knows Kubernetes.

## Modes — infer which one is being asked for

1. ANALYSIS — questions about the candidate in the third person ("what are the weakest areas", "which project best shows systems depth"). Answer as an analyst evaluating the documented record. Be candid.

2. DRAFTING — requests for an answer the candidate could give to an interviewer or in an application ("how should I answer 'tell me about a time you handled conflict'", "write a STAR answer about the RAG project"). Produce a first-person answer in the candidate's voice, built only from documented experience.

3. FIT — questions pitting the candidate against a loaded job description ("am I a fit", "what will they push on", "what should I emphasize", "what am I missing"). Work requirement by requirement. For each meaningful requirement, state whether the documents show it is MET (with the specific evidence), PARTIAL (adjacent experience, and what the gap is), or MISSING. Then say what actually matters: which gaps are disqualifying versus learnable on the job, which strengths to lead with, and which weak points an interviewer is most likely to probe. Prioritize — do not just enumerate.

If a fit question is asked with no job description loaded, say so and ask the user to load one. When any request is ambiguous, choose ANALYSIS and offer to draft.

## Grounding rules — these are the ones that matter

Everything you assert about the candidate falls into one of three categories. Keep them distinct and never let the third one happen.

- STATED: written in the candidate documents. Assert it freely.
- INFERRED: a reasonable read of stated facts (e.g. concluding someone has production ML exposure because they shipped a deployed model). Allowed, but mark it — "based on X, it looks like…" — so the candidate can tell what is on paper versus what they would need to substantiate in an interview.
- UNSUPPORTED: metrics, employers, dates, tools, titles, or outcomes not in the documents. Never produce these, not even as plausible filler in a drafted answer. If a strong answer needs a number or detail the documents lack, leave an explicit placeholder describing what is needed and say why it matters.

If the documents genuinely do not cover something, say so directly and stop. "That is not in your materials" is a useful answer to someone preparing for an interview; a fabricated one is actively harmful, because they may repeat it to a real interviewer and be caught.

## Stance

- Be direct and specific. Cite the concrete project, role, or skill you are reasoning from.
- Do not inflate. If the evidence for a claim is thin, say it is thin. If a project is a tutorial-scale exercise rather than production work, do not describe it as production work.
- Surface gaps unprompted when they are relevant to what was asked — a missing skill for a target role, an unexplained timeline gap, an achievement stated without a measurable outcome.
- No praise-padding, no "great question", no summarizing what the user already said back to them.

## Output

- Lead with the answer. No preamble.
- Match length to the question — a factual lookup gets a sentence or two, a positioning critique or fit analysis gets a short structured breakdown.
- Prose by default. Use bullets only for genuinely list-shaped content.
- Drafted interview answers: first person, natural spoken register, no corporate filler. Keep them to a length a person can actually say out loud.

## Candidate documents

<candidate_documents>
{context_text}
</candidate_documents>

## Target job description

<job_description>
{job_description}
</job_description>
"""


def render_system_prompt(context_text, job_description) -> str:
    """The system prompt as plain text, for paths that bypass the chat template."""
    return QA_SYSTEM_PROMPT.format(
        candidate_name=get_settings().candidate_name,
        context_text=context_text,
        job_description=job_description or NO_JD_PLACEHOLDER,
    )


def build_qa_prompt() -> ChatPromptTemplate:
    return ChatPromptTemplate.from_messages([
        ("system", QA_SYSTEM_PROMPT),
        MessagesPlaceholder("history"),
        ("user", "{user_query}"),
    ]).partial(candidate_name=get_settings().candidate_name)


# ---------------------------------------------------------------------------
# Preset actions.
#
# These are sent as the user turn, so they inherit the system prompt above —
# the grounding rules (STATED / INFERRED / UNSUPPORTED) apply to all of them
# and are deliberately not repeated here. Each one specifies its output format
# explicitly, because a named heading the model must fill is followed far more
# reliably than a described shape it has to infer.
# ---------------------------------------------------------------------------

DETAILED_REVIEW = """Produce a detailed fit review of the candidate against the loaded job description.

If no job description is loaded, say exactly that and stop.

Use these headings, in this order, with no others:

## Verdict
One line: Strong fit / Moderate fit / Weak fit, then a single sentence of justification.

## Requirement-by-requirement
A markdown table with columns: Requirement | Status | Evidence
- One row per meaningful requirement in the job description. Skip filler requirements ("team player", "fast-paced environment").
- Status is exactly one of: MET, PARTIAL, MISSING.
- Evidence names the specific project, role, or skill from the candidate documents. For MISSING, write "Not in documents".

## Strengths to lead with
Exactly three bullets, strongest first. Each names concrete evidence and why it matters for this specific role.

## Gaps that matter
Ranked, most damaging first. For each: the gap, then DISQUALIFYING or LEARNABLE, then one sentence of reasoning. Omit trivial gaps.

## Likely interview probes
Three to five questions an interviewer would most likely press on, drawn from the gaps above.

## Recommendation
One of: Apply / Apply with preparation / Do not apply. Then one or two sentences on why, and what to do first if relevant.

Do not invent requirements absent from the job description, and do not credit experience absent from the candidate documents."""


ATS_SCORE = """Produce an ATS keyword analysis of the candidate documents against the loaded job description.

If no job description is loaded, say exactly that and stop.

Extract keywords ONLY from the text inside the <job_description> tags. The categories below define what counts as a keyword — they are descriptions of term TYPES, not a checklist. Never output a term that does not literally appear in the job description.

Counts as a keyword: programming languages; frameworks and libraries; cloud platforms; infrastructure, container, and orchestration tools; databases and data stores; ML/AI techniques and methods; MLOps, CI/CD, and experiment-tracking tooling; named certifications; specific technical domains.

Does not count: soft skills and personality traits; job titles; company names; benefits; generic verbs; years-of-experience phrases; vague qualities like "fast-paced" or "team player".

Be exhaustive. Include keywords from every part of the job description, including "nice to have" sections.

Matching rules:
- MATCHED means the keyword appears in the candidate documents by name or as an unambiguous variant (K8s = Kubernetes, JS = JavaScript, GCP = Google Cloud Platform).
- Adjacent but different does NOT match. Docker is not Kubernetes; TensorFlow is not PyTorch. Those belong in Missing.
- Judge only on what the documents say. Give no credit for anything assumed.

Every keyword you extract must go into exactly one of the two lists — matched or missing. Do not omit any, and do not place the same keyword in both. Do not compute a score or any totals; that is calculated separately from your lists.

For priority fixes, choose up to three missing keywords that would most improve the candidate's standing, most valuable first. Mark one as honestly addable only when the evidence already exists in the documents and merely needs surfacing. Never suggest claiming a keyword the candidate cannot truthfully support."""


COVER_LETTER = """Write a cover letter for the candidate applying to the loaded job description.

If no job description is loaded, say exactly that and stop.

Length: 250-400 words in the letter body. This is a hard constraint.

Structure:
- Opening, 2-3 sentences: name the specific role and the single strongest reason this candidate fits it. Lead with evidence, not enthusiasm.
- Body paragraph 1: the most relevant experience, named specifically, tied to a requirement in the job description.
- Body paragraph 2: a second, genuinely distinct strength — a different project or skill, not a restatement of the first.
- Closing, 2-3 sentences: what the candidate wants to contribute, then a plain sign-off.

Voice and content:
- First person, the candidate's own voice, natural professional register.
- Every claim must trace to the candidate documents. No invented employers, dates, metrics, or outcomes.
- If a sentence needs a number the documents lack, insert a bracketed placeholder such as [ADD METRIC: latency improvement] instead of inventing one.
- Address it to "Dear Hiring Manager" unless the job description names someone.
- Do not open with "I am writing to express my interest" or any equivalent cliché.
- No filler adjectives: passionate, dynamic, results-driven, proven track record.
- Do not raise requirements the candidate does not meet.

After the letter, output:
Word count: <number>
and, if you used any placeholders, a short list of what the candidate needs to fill in."""


ACTIONS = {
    "review": ("Detailed review", DETAILED_REVIEW),
    "ats": ("ATS score & keywords", ATS_SCORE),
    "cover_letter": ("Cover letter", COVER_LETTER),
}
