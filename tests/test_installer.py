"""scripts/install.sh must refuse bad input before it touches the network or disk."""
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "install.sh"
pytestmark = pytest.mark.skipif(sys.platform != "darwin", reason="installer is macOS-only")


def run(*args):
    return subprocess.run(["bash", str(SCRIPT), *args], capture_output=True, text=True, timeout=30)


def test_help_prints_usage():
    out = run("--help")
    assert out.returncode == 0 and "--version" in out.stdout


def test_rejects_unknown_option():
    assert run("--bogus").returncode != 0


@pytest.mark.parametrize("version", ["latest", "v1;rm -rf /", "../../etc", "v1.2"])
def test_rejects_malformed_version(version):
    out = run("--dry-run", "--version", version)
    assert out.returncode != 0 and "unexpected version" in out.stderr


def test_dry_run_changes_nothing(tmp_path):
    out = run("--dry-run", "--version", "v0.2.2", "--dir", str(tmp_path / "apps"))
    assert out.returncode == 0 and "dry run" in out.stdout
    assert not (tmp_path / "apps").exists()
