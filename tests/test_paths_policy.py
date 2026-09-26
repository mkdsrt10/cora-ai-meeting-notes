import json
import os
import stat

import paths
import policy


def test_data_dir_is_isolated_from_repo():
    assert paths.DATA_DIR == paths.Path(os.environ["VOICECOACH_DATA_DIR"]).resolve()
    assert paths.APP_ROOT not in paths.DATA_DIR.parents


def test_ensure_data_dir_is_private_and_seeds_config():
    paths.ensure_data_dir()
    assert stat.S_IMODE(paths.DATA_DIR.stat().st_mode) == 0o700
    assert paths.CONFIG_PATH.exists()
    new_file = paths.LOGS_DIR / "probe.log"
    new_file.write_text("x")
    assert stat.S_IMODE(new_file.stat().st_mode) == 0o600  # umask applied


def test_lockdown_via_env(monkeypatch):
    assert not policy.lockdown_enabled()
    monkeypatch.setenv("VOICECOACH_ENTERPRISE_LOCKDOWN", "1")
    assert policy.lockdown_enabled()
    assert not policy.provider_allowed("anthropic")
    assert not policy.provider_allowed("custom", "https://api.example.com/v1")
    assert policy.provider_allowed("custom", "http://localhost:11434/v1")
    assert policy.provider_allowed("local_mlx")


def test_lockdown_via_config(monkeypatch):
    cfg = json.loads(paths.CONFIG_PATH.read_text())
    paths.CONFIG_PATH.write_text(json.dumps({**cfg, "enterprise_lockdown": True}))
    try:
        assert policy.lockdown_enabled()
        import tracing
        monkeypatch.setattr(tracing, "LANGFUSE_PUBLIC_KEY", "pk")
        monkeypatch.setattr(tracing, "LANGFUSE_SECRET_KEY", "sk")
        monkeypatch.setenv("VOICECOACH_TRACING", "1")
        assert not tracing.tracing_opted_in()
    finally:
        paths.CONFIG_PATH.write_text(json.dumps(cfg))


def test_tracing_off_without_keys():
    import tracing
    assert not tracing.tracing_opted_in()


def test_fresh_install_import_creates_private_data_dir(tmp_path):
    import subprocess
    import sys
    fresh = tmp_path / "brand-new" / "data"
    code = "import db, paths; print(paths.DATA_DIR)"
    env = {**os.environ, "VOICECOACH_DATA_DIR": str(fresh)}
    result = subprocess.run([sys.executable, "-c", code], cwd=paths.PYTHON_DIR, env=env, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert (fresh / "voicecoach.db").exists()
    assert stat.S_IMODE(fresh.stat().st_mode) == 0o700
