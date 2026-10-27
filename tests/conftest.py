"""Test bootstrap.

The environment is pinned here before any application module is imported, so
the suite never reads the developer's real .env or personal documents and runs
identically on a clean CI machine.
"""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# load_dotenv() does not override variables that are already set, so these win
# over any real .env on a developer machine.
os.environ["OPENROUTER_API_KEY"] = "test-key-not-used"
os.environ["CANDIDATE_NAME"] = "Test Candidate"
# Set to empty rather than deleted: load_dotenv() skips keys already present, so
# an empty value keeps real Langfuse credentials out and stops the suite emitting
# traces to a live project.
for _optional in ("LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY", "LANGFUSE_HOST", "LANGFUSE_BASE_URL"):
    os.environ[_optional] = ""
