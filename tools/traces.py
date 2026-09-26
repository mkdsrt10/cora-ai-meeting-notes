#!/usr/bin/env python3
"""Query the local AI trace store (DATA_DIR/traces.db).

    python tools/traces.py stats [--days 30] [--kind llm]
        Benchmark table per (kind, name, model, weights revision, prompt
        version): calls, errors, p50/p95 latency, tokens/s, real-time
        factor, peak memory. Compare versions by reading rows side by side.

    python tools/traces.py runs [--limit 20]
        Recent pipeline runs with app/git/pipeline versions and duration.

    python tools/traces.py show RUN_ID
        Every span in one run, in order.

    python tools/traces.py export OUT.jsonl [--kind llm] [--name enhanced_notes.%] [--model M] [--corrections]
        Input/output pairs with full version metadata, for retraining or
        offline evaluation. --corrections exports human transcript/speaker
        fixes instead (the highest-quality labels).

The store holds meeting content — treat exports with the same care as the
recordings themselves.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "python"))
import paths  # noqa: E402


def connect() -> sqlite3.Connection:
    if not paths.TRACES_DB.exists():
        raise SystemExit(f"No trace store yet at {paths.TRACES_DB} — run a recording through the pipeline first.")
    conn = sqlite3.connect(paths.TRACES_DB)
    conn.row_factory = sqlite3.Row
    return conn


def percentile(values: list[float], pct: float) -> float | None:
    if not values:
        return None
    values = sorted(values)
    k = (len(values) - 1) * pct
    lo, hi = int(k), min(int(k) + 1, len(values) - 1)
    return values[lo] + (values[hi] - values[lo]) * (k - lo)


def fmt(value, digits=2) -> str:
    return "-" if value is None else f"{value:.{digits}f}"


def cmd_stats(args) -> None:
    where, params = ["started_at >= ?"], [time.time() - args.days * 86400]
    if args.kind:
        where.append("kind = ?")
        params.append(args.kind)
    rows = connect().execute(
        f"SELECT kind, name, provider, model, model_revision, prompt_hash, status, duration_s, tokens_per_s,"
        f" generation_tps, rtf, peak_memory_mb, input_tokens, output_tokens FROM spans WHERE {' AND '.join(where)}",
        params,
    ).fetchall()
    groups: dict[tuple, list[sqlite3.Row]] = {}
    for row in rows:
        groups.setdefault((row["kind"], row["name"], row["model"], row["model_revision"], row["prompt_hash"]), []).append(row)
    header = f"{'kind':<13} {'name':<34} {'model':<42} {'rev':<14} {'prompt':<9} {'n':>4} {'err':>3} {'p50 s':>7} {'p95 s':>7} {'tok/s':>7} {'rtf':>6} {'peakMB':>7} {'in tok':>8} {'out tok':>8}"
    print(header)
    print("-" * len(header))
    for (kind, name, model, rev, phash), items in sorted(groups.items(), key=lambda kv: (kv[0][0], kv[0][1])):
        durations = [r["duration_s"] for r in items if r["duration_s"] is not None]
        tps = [r["generation_tps"] or r["tokens_per_s"] for r in items if (r["generation_tps"] or r["tokens_per_s"])]
        rtf = [r["rtf"] for r in items if r["rtf"]]
        peak = [r["peak_memory_mb"] for r in items if r["peak_memory_mb"]]
        model_short = (model or "-")[-42:]
        print(f"{kind:<13} {name[:34]:<34} {model_short:<42} {(rev or '-')[:14]:<14} {(phash or '-')[:8]:<9} "
              f"{len(items):>4} {sum(r['status'] != 'ok' for r in items):>3} {fmt(percentile(durations, .5)):>7} "
              f"{fmt(percentile(durations, .95)):>7} {fmt(sum(tps) / len(tps) if tps else None, 1):>7} "
              f"{fmt(sum(rtf) / len(rtf) if rtf else None, 3):>6} {fmt(max(peak) if peak else None, 0):>7} "
              f"{sum(r['input_tokens'] or 0 for r in items):>8} {sum(r['output_tokens'] or 0 for r in items):>8}")


def cmd_runs(args) -> None:
    for row in connect().execute("SELECT r.*, (SELECT COUNT(*) FROM spans s WHERE s.run_id = r.id) AS spans"
                                 " FROM runs r ORDER BY started_at DESC LIMIT ?", (args.limit,)):
        started = time.strftime("%Y-%m-%d %H:%M", time.localtime(row["started_at"]))
        commit = (row["git_commit"] or "")[:8] + ("*" if row["git_dirty"] else "")
        print(f"{row['id'][:12]}  {started}  {row['pipeline']:<24} {row['status'] or '':<7} {fmt(row['duration_s'], 1):>7}s "
              f"spans={row['spans']:<3} app={row['app_version']} git={commit} pipeline={row['pipeline_version']}  "
              f"{row['recording_id'] or ''}")


def cmd_show(args) -> None:
    conn = connect()
    run = conn.execute("SELECT * FROM runs WHERE id LIKE ?", (args.run_id + "%",)).fetchone()
    if not run:
        raise SystemExit("No such run.")
    print(json.dumps({k: run[k] for k in run.keys() if k not in {"hardware", "settings"}}, indent=2))
    print("hardware:", run["hardware"])
    print("settings:", run["settings"])
    for span in conn.execute("SELECT * FROM spans WHERE run_id = ? ORDER BY started_at", (run["id"],)):
        extra = "  ".join(f"{k}={span[k]}" for k in ("input_tokens", "output_tokens", "generation_tps", "rtf",
                                                        "peak_memory_mb") if span[k] is not None)
        print(f"  {span['kind']:<13} {span['name']:<38} {span['status']:<5} {fmt(span['duration_s'])}s  {extra}"
              + (f"  ERROR {span['error']}" if span["error"] else ""))


def cmd_export(args) -> None:
    conn = connect()
    out = Path(args.out)
    count = 0
    with out.open("w", encoding="utf-8") as handle:
        if args.corrections:
            query = "SELECT * FROM corrections ORDER BY created_at"
            for row in conn.execute(query):
                handle.write(json.dumps({k: row[k] for k in row.keys()}, ensure_ascii=False) + "\n")
                count += 1
        else:
            where, params = ["s.status = 'ok'", "s.output IS NOT NULL"], []
            for column, value in (("s.kind", args.kind), ("s.model", args.model)):
                if value:
                    where.append(f"{column} = ?")
                    params.append(value)
            if args.name:
                where.append("s.name LIKE ?")
                params.append(args.name)
            query = ("SELECT s.*, r.app_version, r.git_commit, r.pipeline_version, r.hardware FROM spans s"
                     f" LEFT JOIN runs r ON r.id = s.run_id WHERE {' AND '.join(where)} ORDER BY s.started_at")
            for row in conn.execute(query, params):
                record = {k: row[k] for k in row.keys()}
                for key in ("input", "output", "params", "metrics", "hardware"):
                    if record.get(key):
                        record[key] = json.loads(record[key])
                handle.write(json.dumps(record, ensure_ascii=False) + "\n")
                count += 1
    out.chmod(0o600)
    print(f"Wrote {count} record(s) to {out}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("stats")
    p.add_argument("--days", type=int, default=30)
    p.add_argument("--kind")
    p.set_defaults(func=cmd_stats)
    p = sub.add_parser("runs")
    p.add_argument("--limit", type=int, default=20)
    p.set_defaults(func=cmd_runs)
    p = sub.add_parser("show")
    p.add_argument("run_id")
    p.set_defaults(func=cmd_show)
    p = sub.add_parser("export")
    p.add_argument("out")
    p.add_argument("--kind")
    p.add_argument("--name", help="SQL LIKE pattern, e.g. enhanced_notes.%%")
    p.add_argument("--model")
    p.add_argument("--corrections", action="store_true")
    p.set_defaults(func=cmd_export)
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
