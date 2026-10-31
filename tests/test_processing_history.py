"""History is recording-scoped, metrics-only, and honest about missing measurements."""
import json
import sqlite3

import pytest

import ai_trace
from processing_history import history


@pytest.fixture
def traces(tmp_path, monkeypatch):
    path = tmp_path / 'traces.db'
    monkeypatch.setattr(ai_trace, 'TRACE_DB', path)
    monkeypatch.setattr(ai_trace, '_schema_ready', False)
    monkeypatch.setattr(ai_trace, 'enabled', lambda: True)
    return path


def test_missing_history_does_not_create_database(traces):
    assert history('no-meeting') == dict(enabled=True, runs=[], calls=[], truncated=False)
    assert not traces.exists()


def test_scoped_metrics_without_prompts_or_credentials(traces):
    with ai_trace.run('notes_regeneration', recording_id='meeting') as run:
        with ai_trace.span('llm','notes.chunk.0',provider='mlx',model='org/model',input={'secret':'private prompt'}) as span:
            span.set_output('private response', input_tokens=100, output_tokens=20, peak_memory_mb=512)
        with ai_trace.span('llm','notes.merge',provider='gemini',model='cloud-model') as span:
            span.set_output('private cloud response', input_tokens=200, output_tokens=50, cost_usd=0.012)
    with ai_trace.run('other', recording_id='other-meeting'):
        with ai_trace.span('llm','other-call',provider='gemini'):
            pass
    data = history('meeting')
    assert len(data['runs']) == 1 and data['runs'][0]['id'] == run
    assert data['runs'][0]['process_peak_rss_mb'] > 0
    assert [call['name'] for call in data['calls']] == ['notes.chunk.0','notes.merge']
    assert data['calls'][0]['cost_usd'] == 0 and data['calls'][0]['cost_source'] == 'local_api'
    assert data['calls'][1]['cost_usd'] == 0.012
    assert data['calls'][0]['input_tokens'] == 100 and data['calls'][0]['peak_memory_mb'] == 512
    assert all(call['process_peak_rss_mb'] > 0 for call in data['calls'])
    serialized = json.dumps(data)
    for forbidden in ('private prompt','private response','private cloud response','other-call','"input":','"output":','"settings":','"params":'):
        assert forbidden not in serialized


def test_missing_usage_and_failures_are_preserved(traces):
    with pytest.raises(ValueError):
        with ai_trace.run('failure',recording_id='meeting'):
            with ai_trace.span('llm','failed-call',provider='custom'):
                raise ValueError('api_key=secret123 Bearer secret456')
    data = history('meeting')
    assert data['runs'][0]['status'] == 'error'
    call = data['calls'][0]
    assert call['input_tokens'] is None and call['cost_usd'] is None
    assert 'secret123' not in call['error'] and 'secret456' not in call['error']
    assert '[redacted]' in call['error']


def test_old_orphan_spans_and_disabled_tracing_still_visible(traces, monkeypatch):
    with ai_trace.span('ocr','screenshot',provider='apple_vision',recording_id='meeting'):
        pass
    monkeypatch.setattr(ai_trace, 'enabled', lambda: False)
    data = history('meeting')
    assert not data['enabled'] and not data['runs']
    assert data['calls'][0]['run_id'] is None
    with sqlite3.connect(traces) as conn:
        conn.execute("UPDATE spans SET metrics='not json' WHERE recording_id='meeting'")
    assert history('meeting')['calls'][0]['process_peak_rss_mb'] is None


def test_nan_and_negative_costs_are_unavailable(traces):
    with ai_trace.span('llm','call',provider='gemini',recording_id='meeting') as span:
        span.set(cost_usd=-1)
    assert history('meeting')['calls'][0]['cost_usd'] is None


def test_capture_aliases_and_continuations_keep_history(traces):
    with ai_trace.span('ocr','live-screen',provider='apple_vision',recording_id='live-id'):
        pass
    with ai_trace.run('continued',recording_id='child'):
        with ai_trace.span('llm','continued-notes',provider='mlx'):
            pass
    ai_trace.reassign_recording('child','parent')
    assert not history('child')['runs']
    data = history('parent',aliases=['live-id'])
    assert {call['name'] for call in data['calls']} == {'live-screen','continued-notes'}
    assert len(data['runs']) == 1
