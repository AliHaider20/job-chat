"""Skill registry.

Each skill is a markdown file in skills/ that becomes the model's operating
instructions for one task. The four buttons in the UI run them directly, and the
semantic router sends matching free-form requests to the same skills.
"""

from dataclasses import dataclass
from functools import lru_cache

from config import PROJECT_ROOT

SKILLS_DIR = PROJECT_ROOT / "skills"


@dataclass(frozen=True)
class Skill:
    label: str  # button text
    filename: str
    instruction: str  # the user turn a button click sends


SKILLS = {
    "review": Skill(
        "Resume review",
        "review-resume-detailed.md",
        "Run the resume review skill on my resume against the loaded job description.",
    ),
    "ats": Skill(
        "ATS score & keywords",
        "analyze-ats-keywords.md",
        "Run the ATS keyword analysis skill on my resume against the loaded job description.",
    ),
    "cover_letter": Skill(
        "Cover letter",
        "write-cover-letter.md",
        "Write my cover letter for the loaded job description using the cover letter skill.",
    ),
    "email": Skill(
        "Application email",
        "email-writing.md",
        "Write my direct application email for the loaded job description using the email skill.",
    ),
}

# Skills that write prose rather than analyse, and so use a higher temperature.
DRAFTING_SKILLS = {"cover_letter", "email"}

# Button order and (label, instruction) pairs, as the UI consumes them.
ACTIONS = {key: (skill.label, skill.instruction) for key, skill in SKILLS.items()}


@lru_cache(maxsize=None)
def load_skill(key: str) -> str:
    """The skill's markdown, read once. Raises if the file is missing."""
    path = SKILLS_DIR / SKILLS[key].filename
    return path.read_text(encoding="utf-8").strip()
