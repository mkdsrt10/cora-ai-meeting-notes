"""Point every test at a throwaway data dir *before* any app module imports
paths.py, so tests never read or modify a real user's recordings or DB."""
import os
import sys
import tempfile
from pathlib import Path

_DATA = tempfile.mkdtemp(prefix="cora-test-")
os.environ["VOICECOACH_DATA_DIR"] = _DATA
os.environ.pop("VOICECOACH_ENTERPRISE_LOCKDOWN", None)
os.environ.pop("LANGFUSE_PUBLIC_KEY", None)
os.environ.pop("LANGFUSE_SECRET_KEY", None)
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "python"))
