import json
import sqlite3
import stat

import pytest

import ai_trace
import paths


def rows(sql, *params):
    with sqlite3.connect(ai_trace.TRACE_DB) as conn:
        conn.row_factory = sqlite3.Row
        return conn.execute(sql, params).fetchall()


@pytest.fixture
def config(monkeypatch):
    paths.ensure_data_dir()
    original = paths.CONFIG_PATH.read_text()

    def set_tracing(**kw):
        cfg = json.loads(original)
        cfg["local_tracing"] = kw
        paths.CONFIG_PATH.write_text(json.dumps(cfg))
    yield set_tracing
    paths.CONFIG_PATH.write_text(original)


def test_run_and_spans_are_recorded_with_versions(config):
    with ai_trace.run("unit_test", recording_id="rec-1") as run_id:
        with ai_trace.span("llm", "notes.overview", provider="mlx", model="org/model",
                           input={"prompt": "hi", "audio": b"\x00\x01"}, prompt_template="tmpl") as s:
            s.set(input_tokens=10, output_tokens=20, generation_tps=55.5)
            s.set_output("answer", finish_reason="stop")
    span = rows("SELECT * FROM spans WHERE run_id = ?", run_id)[0]
    assert span["recording_id"] == "rec-1" and span["status"] == "ok"
    assert span["prompt_hash"] == ai_trace.prompt_hash("tmpl")
    assert json.loads(span["output"]) == "answer"
    stored_input = json.loads(span["input"])
    assert stored_input["audio"]["bytes"] == 2 and "sha256" in stored_input["audio"]  # never raw bytes
    assert json.loads(span["metrics"])["finish_reason"] == "stop"
    run = rows("SELECT * FROM runs WHERE id = ?", run_id)[0]
    assert run["status"] == "ok" and run["pipeline_version"] == ai_trace.PIPELINE_VERSION
    assert run["app_version"] and json.loads(run["hardware"])["macos"]
    assert stat.S_IMODE(ai_trace.TRACE_DB.stat().st_mode) == 0o600


def test_errors_are_recorded_and_reraised(config):
    with pytest.raises(RuntimeError):
        with ai_trace.span("llm", "boom", provider="anthropic"):
            raise RuntimeError("api down")
    span = rows("SELECT * FROM spans WHERE name = 'boom'")[0]
    assert span["status"] == "error" and "api down" in span["error"]


def test_payloads_can_be_turned_off(config):
    config(store_payloads=False)
    with ai_trace.span("transcription", "no_payload", provider="mlx", input={"secret": "words"}) as s:
        s.set_output("transcript text", audio_s=10.0)
    span = rows("SELECT * FROM spans WHERE name = 'no_payload'")[0]
    assert span["input"] is None and span["output"] is None
    assert span["audio_s"] == 10.0 and span["rtf"] is not None


def test_disabled_writes_nothing(config):
    config(enabled=False)
    with ai_trace.span("llm", "disabled_span", provider="mlx") as s:
        s.set_output("x")
    assert not rows("SELECT * FROM spans WHERE name = 'disabled_span'")


def test_purge_recording(config):
    with ai_trace.run("unit_test", recording_id="rec-purge"):
        with ai_trace.span("llm", "p", provider="mlx"):
            pass
    ai_trace.record_correction("rec-purge", 0, "speaker", "You", "Jane")
    ai_trace.purge_recording("rec-purge")
    assert not rows("SELECT * FROM spans WHERE recording_id = 'rec-purge'")
    assert not rows("SELECT * FROM corrections WHERE recording_id = 'rec-purge'")


@pytest.fixture
def stamped_env(monkeypatch):
    """The packaged app has no package.json or .git at its root, so Electron
    stamps the version and commit into the server's environment."""
    monkeypatch.setenv("CORA_APP_VERSION", "9.8.7")
    monkeypatch.setenv("CORA_GIT_COMMIT", "abc1234")
    ai_trace.app_versions.cache_clear()
    yield
    ai_trace.app_versions.cache_clear()


def test_app_versions_prefer_the_stamp_from_electron(stamped_env, monkeypatch, tmp_path):
    monkeypatch.setattr(paths, "APP_ROOT", tmp_path)  # like a bundle: no package.json, no git
    assert ai_trace.app_versions() == {"app_version": "9.8.7", "git_commit": "abc1234", "git_dirty": None}


def test_run_row_created_under_the_stamp_carries_version_and_commit(config, stamped_env):
    with ai_trace.run("unit_test_stamped") as run_id:
        pass
    run = rows("SELECT * FROM runs WHERE id = ?", run_id)[0]
    assert (run["app_version"], run["git_commit"]) == ("9.8.7", "abc1234")


def test_app_versions_fall_back_to_the_checkout_without_a_stamp(monkeypatch):
    monkeypatch.delenv("CORA_APP_VERSION", raising=False)
    monkeypatch.delenv("CORA_GIT_COMMIT", raising=False)
    ai_trace.app_versions.cache_clear()
    try:
        info = ai_trace.app_versions()
    finally:
        ai_trace.app_versions.cache_clear()
    assert info["app_version"] == json.loads((paths.APP_ROOT / "package.json").read_text())["version"]
