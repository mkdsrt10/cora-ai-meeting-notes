"""Read-only, payload-free processing history for one meeting."""
from __future__ import annotations

import json
import math
import re
import sqlite3

import ai_trace

LOCAL_PROVIDERS = {'mlx', 'local_mlx', 'apple_vision', 'local'}
SPAN_FIELDS = ('id', 'run_id', 'parent_id', 'kind', 'name', 'provider', 'model', 'model_revision',
               'started_at', 'duration_s', 'status', 'input_tokens', 'output_tokens',
               'prompt_tps', 'generation_tps', 'tokens_per_s', 'audio_s', 'rtf', 'peak_memory_mb')


def number(value):
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and value >= 0 else None


def decoded(value):
    try:
        result = json.loads(value or '{}')
        return result if isinstance(result, dict) else {}
    except (TypeError, ValueError):
        return {}


def error_text(value):
    text = str(value or '')[:2000]
    return re.sub(r'(?i)(bearer\s+|(?:api[_-]?key|token|authorization)[=:]\s*)[^\s&,;]+', r'\1[redacted]', text)


def history(recording_id, aliases=()):
    result = dict(enabled=ai_trace.enabled(), runs=[], calls=[], truncated=False)
    if not ai_trace.TRACE_DB.exists():
        return result
    # No trace payloads, credentials, prompts or arbitrary metrics leave this reader.
    ids = tuple(dict.fromkeys([recording_id, *(alias for alias in aliases if isinstance(alias, str) and alias)]))
    placeholders = ','.join('?' for _ in ids)
    with sqlite3.connect(ai_trace.TRACE_DB.as_uri() + '?mode=ro', uri=True, timeout=5) as conn:
        conn.row_factory = sqlite3.Row
        runs = conn.execute('SELECT id, pipeline, started_at, ended_at, duration_s, status, error, meta FROM runs WHERE recording_id IN (' + placeholders + ') ORDER BY started_at DESC LIMIT 51', ids).fetchall()
        rows = conn.execute('SELECT ' + ','.join(SPAN_FIELDS) + ',error,metrics FROM spans WHERE recording_id IN (' + placeholders + ') OR run_id IN (SELECT id FROM runs WHERE recording_id IN (' + placeholders + ')) ORDER BY started_at DESC LIMIT 2001', ids + ids).fetchall()
    result['truncated'] = len(rows) > 2000 or len(runs) > 50
    for row in runs[:50]:
        run = {key: row[key] for key in ('id', 'pipeline', 'started_at', 'ended_at', 'duration_s', 'status')}
        run['error'] = error_text(row['error'])
        run['process_peak_rss_mb'] = number(decoded(row['meta']).get('process_peak_rss_mb'))
        result['runs'].append(run)
    for row in reversed(rows[:2000]):
        call = {key: row[key] for key in SPAN_FIELDS}
        metrics = decoded(row['metrics'])
        call['error'] = error_text(row['error'])
        call['process_peak_rss_mb'] = number(metrics.get('process_peak_rss_mb'))
        cost = number(metrics.get('cost_usd'))
        call['cost_usd'] = cost if cost is not None else 0 if call['provider'] in LOCAL_PROVIDERS else None
        call['cost_source'] = 'reported' if cost is not None else 'local_api' if call['provider'] in LOCAL_PROVIDERS else 'unavailable'
        result['calls'].append(call)
    return result
