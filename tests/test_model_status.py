"""Model readiness checks (config.model_ready and friends) — the guard
against a broken/incomplete local model silently getting picked."""
from pathlib import Path

import pipeline.config as pcfg


def _touch(path: Path, size: int = 0) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"x" * size)


def test_dir_with_no_weights_is_not_ready(tmp_path):
    model_dir = tmp_path / "broken-model"
    _touch(model_dir / "config.json", 10)
    _touch(model_dir / "tokenizer.json", 10)
    assert not pcfg._dir_has_weights(model_dir)
    assert not pcfg.model_ready(str(model_dir))


def test_dir_with_zero_byte_weights_is_not_ready(tmp_path):
    model_dir = tmp_path / "truncated-model"
    _touch(model_dir / "weights.safetensors", 0)
    assert not pcfg.model_ready(str(model_dir))


def test_dir_with_real_whisper_weights_is_ready(tmp_path):
    model_dir = tmp_path / "whisper-model"
    _touch(model_dir / "weights.npz", 128)
    assert pcfg.model_ready(str(model_dir))


def test_dir_with_sharded_llm_weights_is_ready(tmp_path):
    model_dir = tmp_path / "llm-model"
    _touch(model_dir / "model-00001-of-00002.safetensors", 128)
    assert pcfg.model_ready(str(model_dir))


def test_nonexistent_local_path_is_not_ready(tmp_path):
    assert not pcfg.model_ready(str(tmp_path / "does-not-exist"))


def test_never_downloaded_hf_repo_is_not_ready():
    assert not pcfg.model_ready("some-org/never-downloaded-repo-xyz")


def test_local_whisper_models_skips_broken_entries(tmp_path, monkeypatch):
    good = tmp_path / "good"
    bad = tmp_path / "bad"
    _touch(good / "weights.npz", 64)
    _touch(bad / "config.json", 10)  # exists, but no weights
    monkeypatch.setattr(pcfg, "_config", lambda: {
        "local_whisper_models": [{"path": str(bad), "label": "Bad"}, {"path": str(good), "label": "Good"}],
    })
    models = pcfg.local_whisper_models()
    assert [m["label"] for m in models] == ["Good"]


def test_resolve_whisper_model_falls_back_when_explicit_choice_is_broken(tmp_path, monkeypatch):
    broken = tmp_path / "broken-choice"
    _touch(broken / "config.json", 10)
    monkeypatch.setattr(pcfg.db, "get_setting", lambda key, default=None: str(broken) if key == "whisper_model_choice" else default)
    monkeypatch.setattr(pcfg, "_config", lambda: {})
    assert pcfg.resolve_whisper_model() == pcfg.PUBLIC_WHISPER_FALLBACK


def test_resolve_whisper_model_honors_explicit_hf_repo_choice(monkeypatch):
    monkeypatch.setattr(pcfg.db, "get_setting", lambda key, default=None: "org/some-repo" if key == "whisper_model_choice" else default)
    assert pcfg.resolve_whisper_model() == "org/some-repo"


def test_whisper_model_status_reports_readiness(monkeypatch):
    monkeypatch.setattr(pcfg, "resolve_whisper_model", lambda: pcfg.PUBLIC_WHISPER_FALLBACK)
    monkeypatch.setattr(pcfg, "model_ready", lambda model_id: model_id == pcfg.PUBLIC_WHISPER_FALLBACK)
    status = pcfg.whisper_model_status()
    assert (status["model_id"], status["ready"]) == (pcfg.PUBLIC_WHISPER_FALLBACK, True)
