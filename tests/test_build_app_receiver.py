"""A Team build carries the Beta receiver or is not built
(docs/specs/beta-receiver-in-every-team-build.md, #25). scripts/build-app.sh
refuses before any slow step; scripts/lib/beta-receiver.sh reads the release
Mac's env file, says what is wrong, and checks the stamped build-info.json."""
from pathlib import Path
import json
import os
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/build-app.sh"
LIB = ROOT / "scripts/lib/beta-receiver.sh"


def clean_env(home: Path, **extra) -> dict:
    env = {k: v for k, v in os.environ.items() if not k.startswith("CORA_BETA_")}
    env["HOME"] = str(home)
    env.update(extra)
    return env


def write_env_file(home: Path, text: str) -> Path:
    path = home / ".cora-signing/beta-receiver.env"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text.encode())
    return path


def build(home: Path, *args, **extra):
    return subprocess.run(["bash", str(SCRIPT), *args], capture_output=True, text=True,
                          env=clean_env(home, **extra), timeout=30, cwd=ROOT)


def lib(home: Path, body: str, **extra):
    return subprocess.run(["bash", "-c", f'source "{LIB}"\n{body}'], capture_output=True, text=True,
                          env=clean_env(home, **extra), timeout=30)


def load(home: Path, text: str) -> dict:
    file = write_env_file(home, text)
    out = lib(home, f'beta_receiver_load "{file}"\nprintf "%s\\n%s\\n%s" "$CORA_BETA_RECEIVER_URL" "$CORA_BETA_TOKEN" "$(beta_receiver_problem)"')
    url, token, problem = (out.stdout.split("\n") + ["", "", ""])[:3]
    return {"url": url, "token": token, "problem": problem}


def test_a_team_build_without_the_receiver_stops_at_once(tmp_path):
    result = build(tmp_path, "--team")
    assert result.returncode == 1
    assert "a Team build needs the beta receiver: CORA_BETA_RECEIVER_URL is missing" in result.stderr
    assert "--team --no-telemetry" in result.stderr
    assert "Building native helpers" not in result.stdout


def test_an_env_file_with_empty_values_does_not_count(tmp_path):
    write_env_file(tmp_path, "CORA_BETA_RECEIVER_URL=\nCORA_BETA_TOKEN=\n")
    result = build(tmp_path, "--team")
    assert result.returncode == 1 and "needs the beta receiver" in result.stderr


def test_a_quoted_or_spaced_value_left_unusable_is_refused_without_printing_the_token(tmp_path):
    write_env_file(tmp_path, "CORA_BETA_RECEIVER_URL=https://receiver.example\nCORA_BETA_TOKEN=abc def-secret\n")
    result = build(tmp_path, "--team")
    assert result.returncode == 1 and "CORA_BETA_TOKEN contains spaces or quotes" in result.stderr
    assert "secret" not in result.stderr + result.stdout


def test_no_telemetry_only_goes_with_team(tmp_path):
    result = build(tmp_path, "--no-telemetry")
    assert result.returncode == 1 and "--no-telemetry only goes with --team" in result.stderr


@pytest.mark.parametrize("text", [
    "CORA_BETA_RECEIVER_URL=https://receiver.example\nCORA_BETA_TOKEN=abc=def\n",
    "CORA_BETA_RECEIVER_URL=https://receiver.example\nCORA_BETA_TOKEN=abc=def",          # no final newline
    "CORA_BETA_RECEIVER_URL=https://receiver.example\r\nCORA_BETA_TOKEN=abc=def\r\n",  # CRLF
    "# release Mac\nexport CORA_BETA_RECEIVER_URL=\"https://receiver.example\"\n  CORA_BETA_TOKEN = 'abc=def'\nOTHER=x\n",
])
def test_the_env_file_supplies_both_values_in_the_shapes_people_write(tmp_path, text):
    assert load(tmp_path, text) == {"url": "https://receiver.example", "token": "abc=def", "problem": ""}


def test_values_already_in_the_shell_win_over_the_file(tmp_path):
    file = write_env_file(tmp_path, "CORA_BETA_RECEIVER_URL=https://file.example\nCORA_BETA_TOKEN=file\n")
    out = lib(tmp_path, f'beta_receiver_load "{file}"; echo "$CORA_BETA_RECEIVER_URL $CORA_BETA_TOKEN"',
              CORA_BETA_RECEIVER_URL="https://shell.example", CORA_BETA_TOKEN="shell")
    assert out.stdout.strip() == "https://shell.example shell"


def test_an_inline_comment_or_a_non_url_is_reported(tmp_path):
    assert load(tmp_path, "CORA_BETA_RECEIVER_URL=https://r.example # prod\nCORA_BETA_TOKEN=t\n")["problem"] \
        == "CORA_BETA_RECEIVER_URL is not an http(s) URL"
    assert load(tmp_path, "CORA_BETA_RECEIVER_URL=receiver.example\nCORA_BETA_TOKEN=t\n")["problem"] \
        == "CORA_BETA_RECEIVER_URL is not an http(s) URL"


@pytest.mark.parametrize("info,want,ok", [
    ({"receiver_url": "https://r.example", "token": "t"}, "required", True),
    ({"receiver_url": '"https://r.example"', "token": "t"}, "required", False),
    ({"receiver_url": "", "token": ""}, "required", False),
    ({"receiver_url": "", "token": ""}, "absent", True),
    ({"receiver_url": "https://r.example", "token": "t"}, "absent", False),  # a public DMG must not carry it
])
def test_the_stamped_build_info_is_read_back(tmp_path, info, want, ok):
    path = tmp_path / "build-info.json"
    path.write_text(json.dumps({"version": "0.4.5", "commit": "x", "variant": "team", **info}))
    result = lib(tmp_path, f'beta_receiver_check_stamped "{path}" {want}')
    assert (result.returncode == 0) is ok, result.stderr
