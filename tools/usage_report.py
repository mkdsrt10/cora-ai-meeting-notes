#!/usr/bin/env python3
"""Weekly beta usage report over a receiver root. Stdlib only.

    python tools/usage_report.py <receiver-root> [--since DAYS]

Reads only <root>/events/*.jsonl and <root>/recordings/*/*/meta.json (layout: receiver/README.md)
and prints Markdown to stdout, one section per app version.
"""
import argparse
import html
import json
import re
import statistics
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import unquote

# Same set as python/policy.py LOCAL_PROVIDERS: text models that run on the Mac.
LOCAL_PROVIDERS = frozenset({"local_mlx", "local"})


def load_events(root):
    """Every event line, oldest day first. A batch the sender resent (same install, event id, name and ts)
    counts once."""
    events, seen = [], set()
    for day_file in sorted((root / "events").glob("*.jsonl")):
        with open(day_file, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    event = json.loads(line)
                except ValueError:
                    continue
                if not isinstance(event, dict):
                    continue
                if event.get("id") is not None:
                    key = json.dumps([event.get("install_id"), event.get("id"), event.get("name"), event.get("ts")])
                    if key in seen:
                        continue
                    seen.add(key)
                events.append(event)
    return events


def load_captures(root):
    """meta.json of every stored Captured Recording; display names arrive percent-encoded from the header."""
    captures = []
    for meta_file in sorted((root / "recordings").glob("*/*/meta.json")):
        try:
            meta = json.loads(meta_file.read_text(encoding="utf-8"))
        except ValueError:
            continue
        if isinstance(meta, dict):
            if meta.get("display_name"):
                meta["display_name"] = unquote(str(meta["display_name"]))
            meta["_folder"] = meta_file.parent.relative_to(root).as_posix()
            captures.append(meta)
    return captures


def cell(value):
    """A Markdown table cell: HTML and pipes escaped, line breaks kept as <br>."""
    text = "-" if value is None or value == "" else html.escape(str(value), quote=False)
    return text.replace("\\", "\\\\").replace("|", "\\|").replace("\r\n", "\n").replace("\n", "<br>")


def version_key(version):
    """Sort key, used with reverse=True: newest first, numeric parts compared as numbers, 'unknown' last."""
    parts = [int(p) if p.isdigit() else p for p in re.split(r"[.\-+]", version)]
    return (version != "unknown", [(0, p) if isinstance(p, int) else (1, p) for p in parts])


def version_of(record):
    return record.get("app_version") or "unknown"


def parse_ts(value):
    """Event ts: ISO 8601 (with or without Z) or epoch seconds/milliseconds. None when unreadable."""
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value / 1000 if value > 1e11 else value, timezone.utc)
    try:
        moment = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


def payload(event):
    p = event.get("payload")
    return p if isinstance(p, dict) else {}


def named(events, name):
    return [e for e in events if e.get("name") == name]


def pct(part, whole):
    return f"{round(100 * part / whole)}%" if whole else "n/a"


def per_recording(events, name):
    """(install_id, recording_id) -> first event of `name` for that Recording."""
    found = {}
    for e in named(events, name):
        rid = payload(e).get("recording_id")
        if rid:
            found.setdefault((e.get("install_id"), rid), e)
    return found


def capture_count(captures):
    if not captures:
        return "0"
    reasons = defaultdict(int)
    for c in captures:
        reasons[c.get("reason") or "unknown"] += 1
    return f"{len(captures)} (" + ", ".join(f"{r} {n}" for r, n in sorted(reasons.items())) + ")"


def version_metrics(events, captures=()):
    rows = [("Active installs", str(len({e.get("install_id") for e in events})))]

    finished = named(events, "processing_finished")
    failed = sum(1 for e in finished if payload(e).get("status") != "ok")
    rows.append(("Processing failure rate", f"{pct(failed, len(finished))} ({failed} of {len(finished)})"))

    stopped = per_recording(events, "recording_stopped")
    waits = []
    for key, done in per_recording([e for e in finished if payload(e).get("status") == "ok"], "processing_finished").items():
        start, end = parse_ts(stopped.get(key, {}).get("ts")), parse_ts(done.get("ts"))
        if start and end and end >= start:
            waits.append((end - start).total_seconds())
    median = f"{statistics.median(waits):.0f} s ({len(waits)} recordings)" if waits else "n/a"
    rows.append(("Median stop to notes", median))

    providers = [str(payload(e).get("text_provider")).lower() for e in finished if payload(e).get("text_provider")]
    local = sum(1 for p in providers if p in LOCAL_PROVIDERS)
    mix = (f"{pct(local, len(providers))} local, {pct(len(providers) - local, len(providers))} cloud "
           f"({len(providers)} jobs)") if providers else "n/a"
    rows.append(("Local vs cloud (text model)", mix))

    ok_transcripts = len(per_recording([e for e in finished if payload(e).get("status") == "ok"],
                                       "processing_finished"))
    corrections = sum(n for n in (payload(e).get("corrections") for e in named(events, "transcript_corrected"))
                      if isinstance(n, (int, float)) and not isinstance(n, bool))
    rows.append(("Corrections per transcript", f"{corrections / ok_transcripts:.1f} ({corrections:g} over "
                 f"{ok_transcripts} transcripts)" if ok_transcripts else "n/a"))
    rows.append(("Captured recordings", capture_count(captures)))
    return rows


def recordings_per_person(events, names):
    recordings = defaultdict(set)
    for name in ("recording_stopped", "processing_finished"):
        for install, rid in per_recording(events, name):
            recordings[cell(names.get(install) or f"({install})")].add((install, rid))
    return sorted(((who, str(len(recs))) for who, recs in recordings.items()), key=lambda r: (-int(r[1]), r[0]))


def thumbs_by_target(events):
    counts = defaultdict(lambda: [0, 0])
    for e in named(events, "feedback"):
        p = payload(e)
        if p.get("rating") in ("up", "down"):
            counts[p.get("target") or "unknown"][0 if p["rating"] == "up" else 1] += 1
    return [(target, str(up), str(down), pct(up, up + down)) for target, (up, down) in sorted(counts.items())]


def display_names(events):
    """install_id -> the latest non-empty display name it sent (day files are read oldest first)."""
    names = {}
    for e in events:
        if e.get("display_name"):
            names[e.get("install_id")] = str(e["display_name"])
    return names


def table(header, rows):
    out = ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
    out += ["| " + " | ".join(cells) + " |" for cells in rows]
    return out


def received_since(cutoff):
    """Filter on the receiver's received_at stamp; everything passes when there is no cutoff."""
    def keep(record):
        if cutoff is None:
            return True
        moment = parse_ts(record.get("received_at"))
        return moment is not None and moment >= cutoff
    return keep


def render(root, since_days=None, now=None):
    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(days=since_days) if since_days is not None else None
    keep = received_since(cutoff)
    by_version = defaultdict(list)
    for event in filter(keep, load_events(root)):
        by_version[version_of(event)].append(event)
    captures_by_version = defaultdict(list)
    for meta in filter(keep, load_captures(root)):
        captures_by_version[version_of(meta)].append(meta)
    names = display_names(e for v in by_version.values() for e in v)
    window = (f"last {since_days:g} days (received since {cutoff:%Y-%m-%d %H:%M} UTC)" if cutoff
              else "everything received")
    out = ["# Cora beta usage report", "", f"Receiver root `{root}`, {window}; generated {now:%Y-%m-%d %H:%M} UTC.",
           ""]
    for version in sorted(set(by_version) | set(captures_by_version), key=version_key, reverse=True):
        events, captures = by_version.get(version, []), captures_by_version.get(version, [])
        out += [f"## {version}", ""] + table(("Metric", "Value"), version_metrics(events, captures)) + [""]
        out += [f"### Recordings per person ({version})", ""]
        people = recordings_per_person(events, names)
        out += (table(("Name", "Recordings"), people) if people else ["No recordings."]) + [""]
        out += [f"### Thumbs up by target ({version})", ""]
        thumbs = thumbs_by_target(events)
        out += (table(("Target", "Up", "Down", "Up ratio"), thumbs) if thumbs else ["No feedback."]) + [""]
        out += [f"### Captured recordings ({version})", ""]
        stored = [(cell(c.get("display_name") or names.get(c.get("install_id")) or f"({c.get('install_id')})"),
                   cell(c.get("recording_id")), cell(c.get("reason")), cell(c["_folder"]))
                  for c in sorted(captures, key=lambda c: str(c.get("received_at")))]
        out += (table(("Name", "Recording", "Reason", "Folder"), stored) if stored else ["None."]) + [""]
    out += ["## Comments", ""]
    comments = []
    for version, events in sorted(by_version.items(), key=lambda kv: version_key(kv[0]), reverse=True):
        for e in named(events, "feedback"):
            p = payload(e)
            if p.get("comment"):
                who = e.get("display_name") or names.get(e.get("install_id")) or f"({e.get('install_id')})"
                comments.append((cell(version), cell(who), cell(p.get("recording_id")), cell(p.get("target")),
                                 cell(p.get("rating")), cell(p["comment"])))
    out += (table(("Version", "Name", "Recording", "Target", "Rating", "Comment"), comments)
            if comments else ["No comments."]) + [""]
    return "\n".join(out)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("root", type=Path, help="receiver root directory")
    parser.add_argument("--since", type=float, metavar="DAYS",
                        help="only events and Captured Recordings received in the last DAYS days")
    args = parser.parse_args(argv)
    if not args.root.is_dir():
        print(f"usage_report: {args.root} is not a receiver root (no such directory)", file=sys.stderr)
        return 2
    if args.since is not None and args.since <= 0:
        parser.error("--since must be a positive number of days")
    sys.stdout.write(render(args.root, args.since))
    return 0


if __name__ == "__main__":
    sys.exit(main())
