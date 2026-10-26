"""Semantic router: three answer tiers plus the four skills.

Queries are compared against the centroid of a few reference examples per
route. Routing is deliberately asymmetric: sending a real question to a route
without the profile produces a confident answer about the candidate with no
evidence behind it, while sending a greeting to the full profile merely wastes
tokens. So anything short of a clear, confident match falls back to FULL.

The skill routes use the same rule: a request must clearly ask for a skill to
get one, otherwise it is answered as ordinary chat. The route names equal the
skill keys in skills.py.
"""

import logging

import numpy as np

logger = logging.getLogger(__name__)

TRIVIAL = "trivial"
SPECIFIC = "specific"
FULL = "full"
# Skill routes. Names match the keys in skills.SKILLS.
REVIEW = "review"
ATS = "ats"
COVER_LETTER = "cover_letter"
EMAIL = "email"

SKILL_ROUTES = (REVIEW, ATS, COVER_LETTER, EMAIL)

REFERENCE_QUERIES = {
    TRIVIAL: [
        "hello",
        "hi there",
        "hey",
        "how are you?",
        "thanks!",
        "thank you",
        "good morning",
        "good evening",
        "who are you?",
        "what can you do?",
        "bye",
    ],
    SPECIFIC: [
        "do I know Rust?",
        "what is my Python experience?",
        "have I used Kubernetes?",
        "which projects used FAISS?",
        "tell me about my volunteer work",
        "what certifications do I have?",
        "where did I use Docker?",
        "what did I do at my last job?",
        "which languages do I know?",
    ],
    FULL: [
        "am I a fit for this role?",
        "what are my weakest areas?",
        "how should I position myself?",
        "summarise my background",
        "what should I emphasise in the interview?",
        "what gaps do I have for this job?",
        "what do I bring to the table?",
        "how do I compare to this job description?",
        "what will they push back on?",
    ],
    REVIEW: [
        "review my resume",
        "critique my resume for this job",
        "how can I improve my resume?",
        "give me feedback on my resume",
        "tear down my resume against this job description",
        "which resume bullets are weak?",
        "rewrite my weakest resume bullets",
    ],
    ATS: [
        "what is my ATS score?",
        "run an ATS check",
        "which keywords am I missing for this job?",
        "will my resume pass the applicant tracking system?",
        "compare my resume keywords to the job description",
        "how well do my keywords match this posting?",
    ],
    COVER_LETTER: [
        "write me a cover letter",
        "draft a cover letter for this role",
        "I need a cover letter for this job",
        "can you write my cover letter?",
        "cover letter for this position",
    ],
    EMAIL: [
        "write an application email",
        "draft an email to the recruiter for this job",
        "write a short email applying for this role",
        "help me email the hiring manager",
        "give me subject lines and an email to apply",
    ],
}

# Tuned against the reference set: correct routes score 0.38-0.60 with margins
# above 0.25, so these thresholds reject genuinely ambiguous queries only.
MIN_SCORE = 0.35
MIN_MARGIN = 0.10


class SemanticRouter:
    def __init__(self, embed_fn, references=None, min_score=MIN_SCORE, min_margin=MIN_MARGIN):
        self.min_score = min_score
        self.min_margin = min_margin
        references = references or REFERENCE_QUERIES

        self.routes = list(references)
        centroids = np.stack([embed_fn(references[route]).mean(axis=0) for route in self.routes])
        norms = np.linalg.norm(centroids, axis=1, keepdims=True)
        self.centroids = centroids / np.where(norms == 0, 1, norms)
        self.embed_fn = embed_fn

    def scores(self, query) -> dict:
        vector = self.embed_fn([query])[0]
        norm = np.linalg.norm(vector)
        if norm:
            vector = vector / norm
        return dict(zip(self.routes, (self.centroids @ vector).tolist()))

    def route(self, query) -> str:
        # Defensive: an unroutable query must never crash the turn.
        if not isinstance(query, str) or not query.strip():
            logger.info("Route %s | unroutable query, not scored", FULL)
            return FULL

        scores = self.scores(query)
        ranked = sorted(scores.items(), key=lambda item: item[1], reverse=True)
        (winner, top), (runner_up_route, runner_up) = ranked[0], ranked[1]
        margin = top - runner_up

        # Leaving the profile behind requires confidence; FULL is the safe default.
        if winner == FULL:
            chosen, why = FULL, "top match"
        elif top < self.min_score:
            chosen, why = FULL, f"{winner} below min_score {self.min_score}"
        elif margin < self.min_margin:
            chosen, why = FULL, f"{winner} over {runner_up_route} below min_margin {self.min_margin}"
        else:
            chosen, why = winner, "top match"

        logger.info(
            "Route %s | %s | margin %.3f | %s | query: %.60r",
            chosen,
            why,
            margin,
            " ".join(f"{route}={score:.3f}" for route, score in ranked),
            query,
        )
        return chosen
