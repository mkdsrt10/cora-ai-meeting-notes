"""Seed a throwaway Cora data dir with made-up meetings for tour screenshots.
Run with VOICECOACH_DATA_DIR pointing at an empty folder and python/ on sys.path."""
import json
import sys

sys.path.insert(0, sys.argv[1])
import db  # noqa: E402
import paths  # noqa: E402

paths.ensure_data_dir()
db.init_db()

MEETINGS = [
    ("2026-11-12_demo_weekly", "Weekly product sync", "2026-11-12T10:00:00+05:30", 1860,
     ["You", "Asha Rao", "Vikram Mehta"],
     "Agreed to ship the onboarding tour in the next release and to test it with five teammates first.",
     ["Asha: draft the tour copy by Friday", "Vikram: set up the beta build", "You: collect feedback from testers"]),
    ("2026-11-11_demo_customer", "Customer call: Northwind", "2026-11-11T16:30:00+05:30", 2640,
     ["You", "Daniel Park"],
     "Northwind wants exports in Markdown and a weekly summary email. Pilot starts next month.",
     ["You: send pricing for 20 seats", "Daniel: share their security questionnaire"]),
    ("2026-11-11_demo_standup", "Engineering standup", "2026-11-11T09:30:00+05:30", 720,
     ["You", "Asha Rao", "Ravi Kumar", "Meera Iyer"],
     "Release branch is green. Two bugs left in call detection; menu-bar mode is ready for review.",
     ["Ravi: fix the Zoom detection bug", "Meera: review menu-bar mode"]),
    ("2026-11-10_demo_1on1", "1:1 with Asha", "2026-11-10T15:00:00+05:30", 1500,
     ["You", "Asha Rao"],
     "Talked about the Q1 roadmap and hiring a designer.",
     ["You: share the roadmap draft"]),
]

for rec_id, title, when, secs, speakers, summary, items in MEETINGS:
    folder = paths.RECORDINGS_DIR / rec_id
    folder.mkdir(parents=True, exist_ok=True)
    db.create_recording(rec_id, str(folder), title, when, secs, 1,
                        {"recording_name": title, "recording_name_source": "user", "duration_seconds": secs,
                         "meeting_tool": "Google Meet", "source_modified_at": when, "processed_at": when})
    segs, t = [], 0
    for i, name in enumerate(speakers * 2):
        sid = f"speaker_{speakers.index(name) + 1}"
        segs.append({"speaker_id": sid, "start": f"{t // 60:02d}:{t % 60:02d}",
                     "end": f"{(t + 40) // 60:02d}:{(t + 40) % 60:02d}", "text": f"{summary.split('.')[0]}."})
        t += 45
    db.update_recording_data(rec_id, "diarization", {
        "model": "demo", "analyzed_at": when,
        "speakers": [{"speaker_id": f"speaker_{i + 1}", "name": n} for i, n in enumerate(speakers)],
        "segments": segs})
    db.update_recording_data(rec_id, "identity", {"speaker_id": "speaker_1"})
    db.update_recording_data(rec_id, "speaker_labels", {f"speaker_{i + 1}": n for i, n in enumerate(speakers)})
    db.update_recording_data(rec_id, "call_summary", {
        "title": title, "summary": summary, "action_items": items, "keywords": ["release", "beta", "tour"]})
    (folder / "enhanced_notes.md").write_text(
        f"## Summary\n{summary}\n\n## Decisions\n- Ship it to five teammates first\n- Keep the tour to five slides\n\n"
        "## Action items\n" + "\n".join(f"- [ ] {i}" for i in items) + "\n")
    db.update_notes(rec_id, "- check the pricing page\n- follow up on Friday")

for i, name in enumerate(["Asha Rao", "Vikram Mehta", "Daniel Park", "Ravi Kumar", "Meera Iyer"]):
    db.upsert_person(f"demo_p{i}", name, ["Product lead", "Engineer", "Customer", "Engineer", "Designer"][i],
                     ["Cora", "Cora", "Northwind", "Cora", "Cora"][i], [], 0, None,
                     "2026-11-01T00:00:00+00:00", "2026-11-12T00:00:00+00:00", 3)
db.set_setting("onboarding_complete", True)
db.set_setting("pending_self_name", "Priya")
db.set_setting("beta_display_name", "Priya")
db.set_setting("beta_display_name_seeded", True)
print("seeded", paths.RECORDINGS_DIR)
print(json.dumps([m[0] for m in MEETINGS]))
