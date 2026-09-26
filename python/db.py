from __future__ import annotations

import sqlite3
import json
import time
from typing import Any

import paths

DB_PATH = paths.DB_PATH

def get_db():
    if not DB_PATH.parent.exists():  # fresh install: create the private data dir first
        paths.ensure_data_dir()
    conn = sqlite3.connect(DB_PATH, timeout=10.0)
    conn.row_factory = sqlite3.Row
    # WAL instead of the default rollback-journal mode: readers (the UI's
    # 2-4s polling) no longer block behind a writer (the archive/batch
    # pipelines, running as separate processes) mid-transaction — only
    # writer-vs-writer still serializes. A no-op after the first call since
    # WAL is a persistent per-database-file setting, not per-connection.
    conn.execute("PRAGMA journal_mode=WAL")
    return conn

def init_db():
    with get_db() as conn:
        conn.execute('''
            CREATE TABLE IF NOT EXISTS recordings (
                id TEXT PRIMARY KEY,
                folder_path TEXT,
                title TEXT,
                recorded_at TEXT,
                duration_seconds REAL,
                size_bytes INTEGER,
                metadata JSON,
                diarization JSON,
                coaching JSON,
                delivery_metrics JSON,
                call_summary JSON,
                speaker_labels JSON,
                identity JSON
            )
        ''')
        try:
            conn.execute("ALTER TABLE recordings ADD COLUMN status TEXT")
        except sqlite3.OperationalError:
            pass  # column already exists
        try:
            conn.execute("ALTER TABLE recordings ADD COLUMN notes TEXT DEFAULT ''")
        except sqlite3.OperationalError:
            pass  # column already exists
        try:
            conn.execute("ALTER TABLE recordings ADD COLUMN summaries JSON DEFAULT '{}'")
        except sqlite3.OperationalError:
            pass  # column already exists
        conn.execute('''
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value JSON
            )
        ''')
        conn.execute('''
            CREATE TABLE IF NOT EXISTS people (
                id TEXT PRIMARY KEY,
                name TEXT,
                role TEXT,
                organization TEXT,
                tags JSON,
                is_self BOOLEAN DEFAULT 0,
                reference_clip_path TEXT,
                first_seen TEXT,
                last_seen TEXT,
                recordings_count INTEGER DEFAULT 0
            )
        ''')
        conn.execute('''
            CREATE TABLE IF NOT EXISTS speaker_matches (
                recording_id TEXT,
                speaker_id TEXT,
                person_id TEXT,
                confidence TEXT,
                confirmed BOOLEAN DEFAULT 0,
                PRIMARY KEY (recording_id, speaker_id)
            )
        ''')
        conn.execute('''
            CREATE TABLE IF NOT EXISTS todo_state (
                recording_id TEXT,
                item_index INTEGER,
                done BOOLEAN DEFAULT 0,
                done_at TEXT,
                PRIMARY KEY (recording_id, item_index)
            )
        ''')
        conn.execute('''
            CREATE TABLE IF NOT EXISTS vocabulary_terms (
                term TEXT PRIMARY KEY,
                weight INTEGER DEFAULT 1,
                source TEXT,
                first_seen TEXT,
                last_seen TEXT
            )
        ''')
        conn.execute('''
            CREATE TABLE IF NOT EXISTS folders (
                id TEXT PRIMARY KEY,
                name TEXT,
                created_at TEXT
            )
        ''')
        conn.execute('''
            CREATE TABLE IF NOT EXISTS live_transcript_entries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                recording_id TEXT,
                type TEXT,
                speaker_id TEXT,
                start_seconds REAL,
                end_seconds REAL,
                text TEXT,
                image_path TEXT,
                created_at TEXT
            )
        ''')
        conn.execute('CREATE INDEX IF NOT EXISTS idx_live_transcript_recording ON live_transcript_entries(recording_id)')

        conn.execute('''
            CREATE TABLE IF NOT EXISTS training_pairs (
                id TEXT PRIMARY KEY,
                recording_id TEXT,
                pair_type TEXT,
                input_data JSON,
                expected_output JSON,
                metadata JSON,
                dataset_name TEXT DEFAULT 'whisper-hinglish-v2',
                synced_to_cloud BOOLEAN DEFAULT 0,
                created_at TEXT
            )
        ''')
        conn.execute('CREATE INDEX IF NOT EXISTS idx_training_pairs_dataset ON training_pairs(dataset_name)')
        conn.execute('CREATE INDEX IF NOT EXISTS idx_training_pairs_rec ON training_pairs(recording_id)')
        conn.commit()


def add_training_pair(pair_id: str, recording_id: str, pair_type: str, input_data: dict, expected_output: dict, metadata: dict = None, dataset_name: str = "whisper-hinglish-v2"):
    now_iso = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    with get_db() as conn:
        conn.execute('''
            INSERT OR REPLACE INTO training_pairs
            (id, recording_id, pair_type, input_data, expected_output, metadata, dataset_name, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ''', (pair_id, recording_id, pair_type, json.dumps(input_data), json.dumps(expected_output), json.dumps(metadata or {}), dataset_name, now_iso))
        conn.commit()


def get_training_pairs_count(dataset_name: str = None) -> int:
    with get_db() as conn:
        if dataset_name:
            row = conn.execute("SELECT COUNT(*) FROM training_pairs WHERE dataset_name = ?", (dataset_name,)).fetchone()
        else:
            row = conn.execute("SELECT COUNT(*) FROM training_pairs").fetchone()
        return row[0] if row else 0


def get_all_training_pairs(dataset_name: str = None) -> list[dict[str, Any]]:
    with get_db() as conn:
        if dataset_name:
            rows = conn.execute("SELECT * FROM training_pairs WHERE dataset_name = ? ORDER BY created_at DESC", (dataset_name,)).fetchall()
        else:
            rows = conn.execute("SELECT * FROM training_pairs ORDER BY created_at DESC").fetchall()
        result = []
        for r in rows:
            d = dict(r)
            d["input_data"] = json.loads(d["input_data"]) if d.get("input_data") else {}
            d["expected_output"] = json.loads(d["expected_output"]) if d.get("expected_output") else {}
            d["metadata"] = json.loads(d["metadata"]) if d.get("metadata") else {}
            result.append(d)
        return result

def get_setting(key, default=None):
    with get_db() as conn:
        row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
        if row is None or row["value"] is None or row["value"] == "":
            return default
        value = row["value"]
        # The column's type affinity turns stored JSON numbers ("42") back
        # into SQLite integers/reals, so only strings still need decoding.
        return json.loads(value) if isinstance(value, str) else value

def set_setting(key, value):
    with get_db() as conn:
        conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, json.dumps(value)))
        conn.commit()

def create_pending_recording(recording_id, source_stem, recorded_at, status, archetype=None, meeting_tool=None, continues_recording_id=None):
    """A live placeholder row, created the instant recording starts — before
    any folder/audio file exists. metadata carries source_stem so the
    archive step can find and retire it once the real row is created."""
    with get_db() as conn:
        meta = {"source_stem": source_stem}
        if archetype:
            meta["archetype"] = archetype
        if meeting_tool:
            meta["meeting_tool"] = meeting_tool
        if continues_recording_id:
            meta["continues_recording_id"] = continues_recording_id
        conn.execute('''
            INSERT OR REPLACE INTO recordings
            (id, folder_path, title, recorded_at, duration_seconds, size_bytes, metadata, diarization, coaching, delivery_metrics, call_summary, speaker_labels, identity, status)
            VALUES (?, '', '', ?, 0, 0, ?, '{}', '{}', '{}', '{}', '{}', '{}', ?)
        ''', (recording_id, recorded_at, json.dumps(meta), status))
        conn.commit()

def get_pending_recording(source_stem):
    with get_db() as conn:
        row = conn.execute(
            "SELECT * FROM recordings WHERE status IS NOT NULL AND json_extract(metadata, '$.source_stem') = ?",
            (source_stem,),
        ).fetchone()
        if row:
            d = dict(row)
            for k in ["metadata", "diarization", "coaching", "delivery_metrics", "call_summary", "speaker_labels", "identity", "summaries"]:
                d[k] = json.loads(d[k]) if d.get(k) else {}
            return d
        return None

def set_pending_recording_status(recording_id, status):
    with get_db() as conn:
        conn.execute("UPDATE recordings SET status = ? WHERE id = ?", (status, recording_id))
        conn.commit()

def retire_pending_recording(source_stem):
    """Delete the placeholder row (if any) once the real archived row for
    the same source file has been created."""
    with get_db() as conn:
        conn.execute(
            "DELETE FROM recordings WHERE status IS NOT NULL AND json_extract(metadata, '$.source_stem') = ?",
            (source_stem,),
        )
        conn.commit()

def add_live_transcript_entry(recording_id, entry_type, speaker_id=None, start_seconds=None, end_seconds=None, text=None, image_path=None, created_at=None):
    """Append one entry to a recording's live chat-style feed — either a
    'speech' turn (produced by the live-transcribe worker as it goes) or a
    'screenshot' card (added the moment a manual snap is OCR'd). Ordered by
    `id`, so entries render in the order they actually happened."""
    with get_db() as conn:
        conn.execute('''
            INSERT INTO live_transcript_entries
            (recording_id, type, speaker_id, start_seconds, end_seconds, text, image_path, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ''', (recording_id, entry_type, speaker_id, start_seconds, end_seconds, text, image_path, created_at or time.strftime("%Y-%m-%dT%H:%M:%S%z")))
        conn.commit()

def get_live_transcript_entries(recording_id):
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM live_transcript_entries WHERE recording_id = ? ORDER BY id ASC",
            (recording_id,),
        ).fetchall()
        return [dict(row) for row in rows]

def retag_live_transcript_entries(old_recording_id, new_recording_id):
    """Re-point a pending recording's live-feed entries at the real archived
    id once the recording is retired — otherwise they'd be orphaned under
    an id nothing references anymore."""
    with get_db() as conn:
        conn.execute(
            "UPDATE live_transcript_entries SET recording_id = ? WHERE recording_id = ?",
            (new_recording_id, old_recording_id),
        )
        conn.commit()

def delete_recording(recording_id):
    with get_db() as conn:
        conn.execute("DELETE FROM recordings WHERE id = ?", (recording_id,))
        conn.commit()

def create_recording(recording_id, folder_path, title, recorded_at, duration_seconds, size_bytes, metadata):
    with get_db() as conn:
        conn.execute('''
            INSERT OR REPLACE INTO recordings 
            (id, folder_path, title, recorded_at, duration_seconds, size_bytes, metadata, diarization, coaching, delivery_metrics, call_summary, speaker_labels, identity)
            VALUES (?, ?, ?, ?, ?, ?, ?, '{}', '{}', '{}', '{}', '{}', '{}')
        ''', (recording_id, folder_path, title, recorded_at, duration_seconds, size_bytes, json.dumps(metadata)))
        conn.commit()

def update_recording_title(recording_id: str, new_title: str) -> None:
    """Update title column and metadata.recording_name in SQLite."""
    with get_db() as conn:
        row = conn.execute("SELECT metadata FROM recordings WHERE id = ?", (recording_id,)).fetchone()
        meta = json.loads(row["metadata"]) if row and row["metadata"] else {}
        meta["recording_name"] = new_title
        meta["recording_name_source"] = "user"
        conn.execute(
            "UPDATE recordings SET title = ?, metadata = ? WHERE id = ?",
            (new_title, json.dumps(meta), recording_id)
        )
        conn.commit()

def update_recording_data(recording_id, field, data):
    allowed_fields = {"metadata", "diarization", "coaching", "delivery_metrics", "call_summary", "speaker_labels", "identity"}
    if field not in allowed_fields:
        raise ValueError(f"Invalid field: {field}")
    with get_db() as conn:
        conn.execute(f"UPDATE recordings SET {field} = ? WHERE id = ?", (json.dumps(data), recording_id))
        conn.commit()

def get_recording_data(recording_id, field):
    allowed_fields = {"metadata", "diarization", "coaching", "delivery_metrics", "call_summary", "speaker_labels", "identity"}
    if field not in allowed_fields:
        raise ValueError(f"Invalid field: {field}")
    with get_db() as conn:
        row = conn.execute(f"SELECT {field} FROM recordings WHERE id = ?", (recording_id,)).fetchone()
        if row and row[field]:
            return json.loads(row[field])
        return {}

def get_recording_by_live_id(live_id):
    """Resolve an archived recording by the id it was tracked under while
    still live (main.js's meeting_<timestamp>), for a UI that was polling
    that id before archiving replaced it with the real folder id."""
    with get_db() as conn:
        row = conn.execute(
            "SELECT * FROM recordings WHERE status IS NULL AND json_extract(metadata, '$.live_recording_id') = ?",
            (live_id,),
        ).fetchone()
        if row:
            d = dict(row)
            for k in ["metadata", "diarization", "coaching", "delivery_metrics", "call_summary", "speaker_labels", "identity", "summaries"]:
                d[k] = json.loads(d[k]) if d.get(k) else {}
            return d
        return None

def get_notes(recording_id):
    """Freeform user notes for a recording — plain text, not JSON, since it's
    edited directly (a notepad), not a structured record."""
    with get_db() as conn:
        row = conn.execute("SELECT notes FROM recordings WHERE id = ?", (recording_id,)).fetchone()
        return (row["notes"] or "") if row else ""

def update_notes(recording_id, text):
    with get_db() as conn:
        conn.execute("UPDATE recordings SET notes = ? WHERE id = ?", (text, recording_id))
        conn.commit()

def get_summaries(recording_id):
    """All saved summary variants for a recording, keyed by format name
    (e.g. 'executive', 'detailed_minutes', 'action_items_only')."""
    with get_db() as conn:
        row = conn.execute("SELECT summaries FROM recordings WHERE id = ?", (recording_id,)).fetchone()
        if row and row["summaries"]:
            return json.loads(row["summaries"])
        return {}

def get_summary(recording_id, format_name):
    return get_summaries(recording_id).get(format_name)

def update_summary(recording_id, format_name, data):
    """Save one summary variant without clobbering the others."""
    with get_db() as conn:
        current = get_summaries(recording_id)
        current[format_name] = data
        conn.execute("UPDATE recordings SET summaries = ? WHERE id = ?", (json.dumps(current), recording_id))
        conn.commit()

def get_all_recordings():
    with get_db() as conn:
        rows = conn.execute("SELECT * FROM recordings ORDER BY recorded_at DESC").fetchall()
        result = []
        for row in rows:
            d = dict(row)
            for k in ["metadata", "diarization", "coaching", "delivery_metrics", "call_summary", "speaker_labels", "identity", "summaries"]:
                d[k] = json.loads(d[k]) if d.get(k) else {}
            result.append(d)
        return result

def get_recording(recording_id):
    with get_db() as conn:
        row = conn.execute("SELECT * FROM recordings WHERE id = ?", (recording_id,)).fetchone()
        if row:
            d = dict(row)
            for k in ["metadata", "diarization", "coaching", "delivery_metrics", "call_summary", "speaker_labels", "identity", "summaries"]:
                d[k] = json.loads(d[k]) if d.get(k) else {}
            return d
        return None

def get_unprocessed_recording():
    with get_db() as conn:
        # Find recordings that have metadata but no diarization. status IS
        # NULL excludes live pending placeholder rows (status='recording' /
        # 'processing') — those aren't archived yet and have no folder on
        # disk, so returning one here sent /api/process-recording an id that
        # didn't exist (a real 400 seen in practice: the archive-watcher's
        # first pass queries this before the file is old enough to archive,
        # got back the still-live placeholder, and failed on a folder that
        # didn't exist yet).
        row = conn.execute("SELECT * FROM recordings WHERE status IS NULL AND json_extract(diarization, '$.model') IS NULL ORDER BY recorded_at DESC LIMIT 1").fetchone()
        if row:
            d = dict(row)
            for k in ["metadata", "diarization", "coaching", "delivery_metrics", "call_summary", "speaker_labels", "identity", "summaries"]:
                d[k] = json.loads(d[k]) if d.get(k) else {}
            return d
        return None

def get_person(person_id):
    with get_db() as conn:
        row = conn.execute("SELECT * FROM people WHERE id = ?", (person_id,)).fetchone()
        if row:
            d = dict(row)
            d["tags"] = json.loads(d["tags"]) if d.get("tags") else []
            return d
        return None

def get_self_person_id():
    with get_db() as conn:
        row = conn.execute("SELECT id FROM people WHERE is_self = 1").fetchone()
        return row["id"] if row else None

def upsert_person(person_id, name, role, organization, tags, is_self, reference_clip_path, first_seen, last_seen, recordings_count):
    with get_db() as conn:
        existing = conn.execute("SELECT is_self FROM people WHERE id = ?", (person_id,)).fetchone()
        final_is_self = int(is_self) if is_self is not None else (existing["is_self"] if existing else 0)
        
        # If this person is marked as self, unmark anyone else
        if final_is_self:
            conn.execute("UPDATE people SET is_self = 0")
            
        conn.execute('''
            INSERT INTO people (id, name, role, organization, tags, is_self, reference_clip_path, first_seen, last_seen, recordings_count)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                name=excluded.name,
                role=excluded.role,
                organization=excluded.organization,
                tags=excluded.tags,
                is_self=excluded.is_self,
                reference_clip_path=excluded.reference_clip_path,
                last_seen=excluded.last_seen,
                recordings_count=excluded.recordings_count
        ''', (person_id, name, role, organization, json.dumps(tags), final_is_self, reference_clip_path, first_seen, last_seen, recordings_count))
        conn.commit()

def get_recent_people(limit=8):
    with get_db() as conn:
        rows = conn.execute("SELECT * FROM people WHERE reference_clip_path IS NOT NULL ORDER BY last_seen DESC LIMIT ?", (limit,)).fetchall()
        result = []
        for row in rows:
            d = dict(row)
            d["tags"] = json.loads(d["tags"]) if d.get("tags") else []
            result.append(d)
        return result

def get_all_people():
    with get_db() as conn:
        rows = conn.execute("SELECT * FROM people ORDER BY last_seen DESC").fetchall()
        result = []
        for row in rows:
            d = dict(row)
            d["tags"] = json.loads(d["tags"]) if d.get("tags") else []
            d["recordings_count"] = conn.execute("SELECT COUNT(*) FROM speaker_matches WHERE person_id = ?", (d["id"],)).fetchone()[0]
            result.append(d)
        return result

def get_person_recordings(person_id):
    with get_db() as conn:
        rows = conn.execute('''
            SELECT r.id, r.title, r.recorded_at, m.speaker_id, m.confidence, m.confirmed
            FROM speaker_matches m JOIN recordings r ON r.id = m.recording_id
            WHERE m.person_id = ? ORDER BY r.recorded_at DESC
        ''', (person_id,)).fetchall()
        return [dict(row) for row in rows]

def delete_person(person_id):
    with get_db() as conn:
        conn.execute("DELETE FROM people WHERE id = ?", (person_id,))
        conn.commit()

def merge_people(primary_id, duplicate_id):
    with get_db() as conn:
        conn.execute(
            "UPDATE OR REPLACE speaker_matches SET person_id = ? WHERE person_id = ?",
            (primary_id, duplicate_id),
        )
        conn.execute("DELETE FROM people WHERE id = ?", (duplicate_id,))
        conn.commit()

def get_speaker_matches(recording_id):
    with get_db() as conn:
        if recording_id is None:
            return [dict(row) for row in conn.execute("SELECT * FROM speaker_matches").fetchall()]
        return [dict(row) for row in conn.execute("SELECT * FROM speaker_matches WHERE recording_id = ?", (recording_id,)).fetchall()]

def upsert_speaker_match(recording_id, speaker_id, person_id, confidence, confirmed):
    with get_db() as conn:
        conn.execute('''
            INSERT INTO speaker_matches (recording_id, speaker_id, person_id, confidence, confirmed)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(recording_id, speaker_id) DO UPDATE SET
                person_id=excluded.person_id,
                confidence=excluded.confidence,
                confirmed=excluded.confirmed
        ''', (recording_id, speaker_id, person_id, confidence, int(confirmed)))
        conn.commit()

def get_todo_states():
    with get_db() as conn:
        return [dict(row) for row in conn.execute("SELECT * FROM todo_state").fetchall()]

def upsert_vocabulary_term(term, source, now_iso):
    """Record or reinforce a transcription vocabulary term (a name, product, or
    system word worth biasing Whisper toward). Repeated sightings raise its
    weight, so terms that come up across many meetings surface first when a
    prompt has to be capped to a handful of terms."""
    with get_db() as conn:
        conn.execute('''
            INSERT INTO vocabulary_terms (term, weight, source, first_seen, last_seen)
            VALUES (?, 1, ?, ?, ?)
            ON CONFLICT(term) DO UPDATE SET
                weight = weight + 1,
                last_seen = excluded.last_seen
        ''', (term, source, now_iso, now_iso))
        conn.commit()

def get_vocabulary_terms(limit=40):
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM vocabulary_terms ORDER BY weight DESC, last_seen DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(row) for row in rows]

def search_vocabulary_terms(query_words, limit=15):
    """Terms whose text overlaps a meeting title/context (e.g. shares a word
    with 'Univar renewal sync') get a relevance boost for that recording,
    on top of their general weight."""
    if not query_words:
        return []
    with get_db() as conn:
        clauses = " OR ".join(["term LIKE ?"] * len(query_words))
        params = [f"%{word}%" for word in query_words]
        rows = conn.execute(
            f"SELECT * FROM vocabulary_terms WHERE {clauses} ORDER BY weight DESC LIMIT ?",
            (*params, limit),
        ).fetchall()
        return [dict(row) for row in rows]

def delete_vocabulary_term(term):
    with get_db() as conn:
        conn.execute("DELETE FROM vocabulary_terms WHERE term = ?", (term,))
        conn.commit()

def merge_vocabulary_terms(primary, duplicate):
    """Fold duplicate's weight into primary and drop duplicate. The kept
    term's last_seen becomes whichever of the two is more recent."""
    with get_db() as conn:
        rows = {row["term"]: dict(row) for row in conn.execute(
            "SELECT * FROM vocabulary_terms WHERE term IN (?, ?)", (primary, duplicate)
        ).fetchall()}
        if primary not in rows or duplicate not in rows:
            raise ValueError("Both terms must exist")
        combined_weight = rows[primary]["weight"] + rows[duplicate]["weight"]
        last_seen = max(rows[primary]["last_seen"] or "", rows[duplicate]["last_seen"] or "")
        conn.execute(
            "UPDATE vocabulary_terms SET weight = ?, last_seen = ? WHERE term = ?",
            (combined_weight, last_seen, primary),
        )
        conn.execute("DELETE FROM vocabulary_terms WHERE term = ?", (duplicate,))
        conn.commit()

def create_folder(folder_id, name, created_at):
    with get_db() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO folders (id, name, created_at) VALUES (?, ?, ?)",
            (folder_id, name, created_at),
        )
        conn.commit()

def get_folders():
    with get_db() as conn:
        rows = conn.execute("SELECT * FROM folders ORDER BY name COLLATE NOCASE").fetchall()
        return [dict(row) for row in rows]

def delete_folder(folder_id):
    with get_db() as conn:
        conn.execute("DELETE FROM folders WHERE id = ?", (folder_id,))
        conn.commit()

init_db()
