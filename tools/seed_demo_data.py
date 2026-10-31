#!/usr/bin/env python3
"""Seed a throwaway Cora data dir with fictional meetings.

For screenshots, demos, design work, and contributors who want a populated
UI without recording anything. Every name, company and line of dialogue is
made up ("Northwind Labs"); nothing here comes from a real recording.

    python tools/seed_demo_data.py /tmp/cora-demo
    VOICECOACH_DATA_DIR=/tmp/cora-demo python python/server.py --port 8799
"""
from __future__ import annotations

import datetime as dt
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

if len(sys.argv) != 2:
    sys.exit(__doc__)
DATA = Path(sys.argv[1]).expanduser().resolve()
if DATA.exists() and any(DATA.iterdir()):
    sys.exit(f"{DATA} is not empty — pick a fresh directory (this never touches real data).")
os.environ["VOICECOACH_DATA_DIR"] = str(DATA)
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "python"))

import db  # noqa: E402
import paths  # noqa: E402

SELF = "Alex Rivera"
NOW = dt.datetime(2026, 10, 15, 17, 30).astimezone()


def ts(sec: float) -> str:
    return f"{int(sec // 60):02d}:{int(sec % 60):02d}"


MEETINGS = [
    {
        "title": "Q4 roadmap review",
        "days_ago": 0, "hour": 11,
        "people": ["Priya Shah", "Rahul Mehta", "Dana Cruz"],
        "lines": [
            ("Priya Shah", "Okay, let's start with the Q4 roadmap. The big question is whether offline sync ships in November or slips to January."),
            (SELF, "Honestly, I think November is risky. The conflict resolution piece isn't done, aur agar hum rush karenge toh support tickets double ho jayenge."),
            ("Rahul Mehta", "Agreed. Engineering estimate is six weeks for conflict resolution, and we only have four before the freeze."),
            ("Dana Cruz", "From the customer side, Acme and two other accounts are asking for it. But they care more about it being reliable than early."),
            ("Priya Shah", "Then let's commit to January for offline sync and ship the export API in November instead."),
            (SELF, "That works. Rahul, can you own the revised timeline and share it by Friday?"),
            ("Rahul Mehta", "Yes, I'll have it by Friday with the dependency list."),
            ("Dana Cruz", "I'll tell Acme this week so it doesn't surprise them."),
            ("Priya Shah", "One open question — do we need a beta program for offline sync, or straight to GA?"),
            (SELF, "Let's decide that next week once we see the timeline."),
        ],
        "decisions": ["Offline sync moves to January; the export API ships in November instead."],
        "actions": ["Rahul Mehta — share the revised Q4 timeline with dependencies by Friday",
                    "Dana Cruz — brief Acme and the other two accounts on the January date this week"],
        "questions": ["Beta program for offline sync, or straight to GA?"],
        "folder": "Planning",
    },
    {
        "title": "1:1 with Priya — growth and feedback",
        "days_ago": 1, "hour": 15,
        "people": ["Priya Shah"],
        "lines": [
            (SELF, "How are you feeling about the roadmap work this month?"),
            ("Priya Shah", "Good overall, but I feel like I'm in too many status meetings. Mujhe deep work ka time nahi mil raha."),
            (SELF, "That's fair. Which of those could become async updates?"),
            ("Priya Shah", "The Tuesday sync and the design review prep, probably both."),
            (SELF, "Let's try making Tuesday async for three weeks and see. Anything you want from me?"),
            ("Priya Shah", "More direct feedback on my roadmap docs, before they go to leadership."),
            (SELF, "Deal. Send me drafts a day early and I'll review them the same day."),
        ],
        "decisions": ["Tuesday sync becomes an async written update for a three-week trial."],
        "actions": ["Priya Shah — send roadmap drafts one day before leadership review",
                    f"{SELF} — review Priya's drafts the same day they arrive"],
        "questions": ["Should design review prep also go async?"],
        "folder": "1:1s",
    },
    {
        "title": "Acme customer call — renewal",
        "days_ago": 2, "hour": 10,
        "people": ["Sam Lee", "Dana Cruz"],
        "lines": [
            ("Sam Lee", "Thanks for making time. We're coming up on renewal and the main thing for us is the audit log."),
            ("Dana Cruz", "Understood. What specifically does your compliance team need from it?"),
            ("Sam Lee", "Exportable logs, ninety-day retention minimum, and who changed what."),
            (SELF, "We have the who-changed-what today. Ninety-day retention is on the roadmap for November."),
            ("Sam Lee", "If November holds, we can sign the renewal this quarter."),
            ("Dana Cruz", "I'll send a written confirmation of the November date and the retention spec."),
        ],
        "decisions": ["Acme will renew this quarter if 90-day audit-log retention ships in November."],
        "actions": ["Dana Cruz — send Acme written confirmation of the November date and retention spec"],
        "questions": ["Does Acme need log export in CSV, JSON, or both?"],
        "folder": "Customers",
    },
    {
        "title": "Design review — onboarding flow",
        "days_ago": 4, "hour": 14,
        "people": ["Rahul Mehta", "Priya Shah"],
        "lines": [
            ("Rahul Mehta", "The new onboarding has five steps. Drop-off is highest at step three, permissions."),
            ("Priya Shah", "We ask for screen recording before showing why. Pehle value dikhao, phir permission maango."),
            (SELF, "Agreed — show a sample meeting first, then ask for permissions in context."),
            ("Rahul Mehta", "I can prototype that by Wednesday."),
        ],
        "decisions": ["Show a sample meeting before asking for permissions."],
        "actions": ["Rahul Mehta — prototype value-first onboarding by Wednesday"],
        "questions": [],
        "folder": "Planning",
    },
    {
        "title": "Hiring sync — senior backend role",
        "days_ago": 6, "hour": 12,
        "people": ["Dana Cruz"],
        "lines": [
            ("Dana Cruz", "We have three finalists for the senior backend role."),
            (SELF, "Who's strongest on distributed systems?"),
            ("Dana Cruz", "The second candidate, clearly. But their notice period is ninety days."),
            (SELF, "Ninety days is long, lekin agar woh sahi fit hain toh wait karna worth it hai. Let's make an offer."),
        ],
        "decisions": ["Extend an offer to the second finalist despite the 90-day notice period."],
        "actions": ["Dana Cruz — prepare the offer and send it by Monday"],
        "questions": ["Can we shorten the notice period with a buyout?"],
        "folder": None,
    },
]


def make_audio(path: Path, seconds: float) -> None:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        return
    subprocess.run([ffmpeg, "-loglevel", "error", "-f", "lavfi", "-i", f"anoisesrc=d={seconds}:c=pink:a=0.02",
                    "-c:a", "aac", "-b:a", "64k", str(path)], check=False)


def main() -> None:
    paths.ensure_data_dir()
    db.init_db()
    db.set_setting("onboarding_complete", True)
    db.set_setting("pending_self_name", SELF)
    db.set_setting("profession", "Head of Product")

    folders: dict[str, str] = {}
    for name in ("Planning", "1:1s", "Customers"):
        fid = name.lower().replace(":", "").replace(" ", "-")
        db.create_folder(fid, name, NOW.isoformat())
        folders[name] = fid

    for i, m in enumerate(MEETINGS):
        when = (NOW - dt.timedelta(days=m["days_ago"])).replace(hour=m["hour"], minute=0)
        rec_id = f"{when:%Y-%m-%d_%H-%M-%S}_demo_{i:02d}"
        folder = paths.RECORDINGS_DIR / rec_id
        folder.mkdir(parents=True)

        segments, t = [], 0.0
        for speaker, text in m["lines"]:
            length = max(4.0, len(text.split()) * 0.42)
            is_self = speaker == SELF
            segments.append({"speaker_id": "You" if is_self else speaker, "speaker_name": speaker,
                             "start": ts(t), "end": ts(t + length), "text": text, "language": "en"})
            t += length + 1.5
        duration = t

        speakers = [{"speaker_id": sid, "name": SELF if sid == "You" else sid, "description": ""}
                    for sid in sorted({s["speaker_id"] for s in segments})]
        diarization = {"summary": f"{m['title']}.", "model": "demo", "speakers": speakers, "segments": segments}
        call_summary = {
            "title": m["title"],
            "overview": f"{m['title']} with {', '.join(m['people'])}. " + m["decisions"][0],
            "decisions": m["decisions"], "action_items": m["actions"],
            "unresolved_questions": m["questions"], "keywords": [],
        }
        metadata = {"recording_name": m["title"], "duration_seconds": round(duration, 1),
                    "processed_at": when.isoformat(), "source_modified_at": when.isoformat(),
                    "meeting_tool": "Zoom", "participants": m["people"] + [SELF]}
        if m["folder"]:
            metadata["folder_id"] = folders[m["folder"]]

        notes = [f"## Overview", call_summary["overview"], "", "## Action Items",
                 *[f"- [ ] {a}" for a in m["actions"]], "", "## Key Discussion & Decisions",
                 *[f"- {d}" for d in m["decisions"]], ""]
        if m["questions"]:
            notes += ["## Open Questions", *[f"- {q}" for q in m["questions"]], ""]
        transcript = [f"**{s['start']}–{s['end']} · {s['speaker_name']}**\n{s['text']}\n" for s in segments]

        (folder / "diarization.json").write_text(json.dumps(diarization, indent=2))
        (folder / "call_summary.json").write_text(json.dumps(call_summary, indent=2))
        (folder / "metadata.json").write_text(json.dumps(metadata, indent=2))
        (folder / "enhanced_notes.md").write_text("\n".join(notes))
        (folder / "transcript_diarized.md").write_text("\n".join(transcript))
        make_audio(folder / "playback.m4a", min(duration, 90))

        db.create_recording(rec_id, str(folder), m["title"], when.isoformat(), duration, 0, metadata)
        db.update_recording_data(rec_id, "diarization", diarization)
        db.update_recording_data(rec_id, "call_summary", call_summary)
        db.update_recording_data(rec_id, "identity", {"speaker_id": "You", "name": SELF})

    print(f"Seeded {len(MEETINGS)} fictional meetings into {DATA}")


if __name__ == "__main__":
    main()
