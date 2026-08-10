"""Test bootstrap.

The environment is pinned here before any application module is imported, so
the suite never reads the developer's real .env or personal documents and runs
identically on a clean CI machine.
"""

import atexit
import os
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

_FIXTURE_DIR = tempfile.mkdtemp(prefix="job-chat-tests-")
(Path(_FIXTURE_DIR) / "fixture.md").write_text("# Fixture profile", encoding="utf-8")
atexit.register(shutil.rmtree, _FIXTURE_DIR, True)

# load_dotenv() does not override variables that are already set, so these win
# over any real .env on a developer machine.
os.environ["GROQ_API_KEY"] = "test-key-not-used"
os.environ["DATA_DIR"] = _FIXTURE_DIR
os.environ["CANDIDATE_NAME"] = "Test Candidate"
# Set to empty rather than deleted: load_dotenv() skips keys already present, so
# an empty value keeps real Langfuse credentials out and stops the suite emitting
# traces to a live project.
for _optional in ("LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY", "LANGFUSE_HOST", "LANGFUSE_BASE_URL"):
    os.environ[_optional] = ""
