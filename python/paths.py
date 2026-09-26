"""Single source of truth for where Cora's code and data live.

Code (APP_ROOT) is wherever this checkout or app bundle is. Data (DATA_DIR)
is per-user and never inside the repo for new installs:

  1. $VOICECOACH_DATA_DIR, if set (Electron always sets it);
  2. ~/voicecoach-desktop, if it already holds a database (installs that
     predate this module kept code and data in the same folder);
  3. ~/Library/Application Support/Cora AI Meeting Notes.

Everything user-generated — recordings, the DB, logs, voice clips, config —
resolves under DATA_DIR, which is created 0700 so other local accounts
can't read meeting audio or transcripts.
"""
from __future__ import annotations

import os
import shutil
from pathlib import Path

APP_NAME = "Cora AI Meeting Notes"
APP_ROOT = Path(__file__).resolve().parent.parent
PYTHON_DIR = APP_ROOT / "python"
STATIC_DIR = APP_ROOT / "src" / "ui" / "web"
CAPTURE_DIR = APP_ROOT / "capture"
BIN_DIR = APP_ROOT / "bin"
PLUGINS_DIR = APP_ROOT / "plugins"
CONFIG_EXAMPLE = APP_ROOT / "config.example.json"
VOCAB_EXAMPLE = PYTHON_DIR / "curated_domain_vocabulary.example.json"

_LEGACY_DATA_DIR = Path.home() / "voicecoach-desktop"


def _resolve_data_dir() -> Path:
    override = os.environ.get("VOICECOACH_DATA_DIR")
    if override:
        return Path(override).expanduser().resolve()
    if (_LEGACY_DATA_DIR / "voicecoach.db").exists():
        return _LEGACY_DATA_DIR
    return Path.home() / "Library" / "Application Support" / APP_NAME


DATA_DIR = _resolve_data_dir()
RECORDINGS_DIR = DATA_DIR / "recordings"
INBOX_DIR = DATA_DIR / "inbox"
LOGS_DIR = DATA_DIR / "logs"
PEOPLE_DIR = DATA_DIR / "people"
DB_PATH = DATA_DIR / "voicecoach.db"
CONFIG_PATH = DATA_DIR / "config.json"
STATE_PATH = DATA_DIR / "state.json"
LOCK_PATH = DATA_DIR / ".pipeline.lock"
API_TOKEN_FILE = DATA_DIR / ".api_token"
COACH_DATA_PATH = DATA_DIR / "coach_data.json"
VOCAB_PATH = DATA_DIR / "curated_domain_vocabulary.json"
WEEKLY_REPORTS_DIR = DATA_DIR / "weekly_reports"
TRACES_DB = DATA_DIR / "traces.db"

# Everything under DATA_DIR that holds user data. When DATA_DIR is the
# legacy repo checkout, this list is what separates data from code.
_PRIVATE_ENTRIES = (
    RECORDINGS_DIR, INBOX_DIR, LOGS_DIR, PEOPLE_DIR, WEEKLY_REPORTS_DIR,
    DATA_DIR / "whisper_full_dataset",
    DB_PATH, DB_PATH.with_name("voicecoach.db-wal"), DB_PATH.with_name("voicecoach.db-shm"),
    CONFIG_PATH, STATE_PATH, API_TOKEN_FILE, COACH_DATA_PATH, VOCAB_PATH,
    TRACES_DB, TRACES_DB.with_name("traces.db-wal"), TRACES_DB.with_name("traces.db-shm"),
)
_PERMS_MARKER = DATA_DIR / ".permissions-v1"


def venv_python() -> Path:
    candidate = APP_ROOT / ".venv" / "bin" / "python"
    return candidate if candidate.exists() else Path(shutil.which("python3") or "python3")


def ensure_data_dir() -> Path:
    """Create DATA_DIR (0700) with a starter config, and restrict new files.

    Call once from every process entry point. The umask makes every file
    this process (and its children: ffmpeg, capture binaries) creates
    owner-only by default.
    """
    os.umask(0o077)
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    os.chmod(DATA_DIR, 0o700)
    for directory in (RECORDINGS_DIR, INBOX_DIR, LOGS_DIR, PEOPLE_DIR):
        directory.mkdir(exist_ok=True)
    if not CONFIG_PATH.exists() and CONFIG_EXAMPLE.exists():
        shutil.copyfile(CONFIG_EXAMPLE, CONFIG_PATH)
    harden_permissions()
    return DATA_DIR


def harden_permissions(force: bool = False) -> None:
    """One-time chmod of pre-existing data to 0700 dirs / 0600 files.

    Data written before the umask existed is world-readable (0644/0755).
    Walking recordings/ every launch would be slow, so this runs once and
    leaves a marker; the umask keeps new files private from then on.
    """
    if _PERMS_MARKER.exists() and not force:
        return
    for entry in _PRIVATE_ENTRIES:
        if not entry.exists() or entry.is_symlink():
            continue
        if entry.is_file():
            os.chmod(entry, 0o600)
            continue
        for dirpath, dirnames, filenames in os.walk(entry):
            os.chmod(dirpath, 0o700)
            for name in filenames:
                path = os.path.join(dirpath, name)
                if not os.path.islink(path):
                    os.chmod(path, 0o600)
    _PERMS_MARKER.touch()
    os.chmod(_PERMS_MARKER, 0o600)
