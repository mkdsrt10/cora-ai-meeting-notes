"""processing.recommend(hardware): the one rule for which Processing mode
this Mac should use. Local is preferred whenever the Mac can run it well;
Cloud is recommended only when it cannot. Onboarding, Settings, the team
build default and the app_started Usage event all read it."""
import pytest

import db
import processing


def hw(gb, arch="arm64"):
    return {"memory_gb": gb, "architecture": arch, "cpu_count": 8}


def levels(rec):
    return {mode: v["level"] for mode, v in rec["modes"].items()}


@pytest.mark.parametrize("gb, arch, recommended, expected", [
    (8, "arm64", "cloud", {"local_light": "warn", "local_thorough": "blocked", "cloud": "recommended"}),
    (16, "arm64", "local_light", {"local_light": "recommended", "local_thorough": "warn", "cloud": "ok"}),
    (18, "arm64", "local_light", {"local_light": "recommended", "local_thorough": "warn", "cloud": "ok"}),
    (24, "arm64", "local_thorough", {"local_light": "ok", "local_thorough": "recommended", "cloud": "ok"}),
    (64, "arm64", "local_thorough", {"local_light": "ok", "local_thorough": "recommended", "cloud": "ok"}),
    (64, "x86_64", "cloud", {"local_light": "blocked", "local_thorough": "blocked", "cloud": "recommended"}),
    (8, "x86_64", "cloud", {"local_light": "blocked", "local_thorough": "blocked", "cloud": "recommended"}),
])
def test_the_rule_table(gb, arch, recommended, expected):
    rec = processing.recommend(hw(gb, arch), lockdown=False)
    assert rec["recommended_mode"] == recommended
    assert levels(rec) == expected
    assert all(v["reason"] for v in rec["modes"].values())
    assert rec["low_ram"] is (0 < gb < 16)


def test_an_8_gb_mac_gets_the_plain_words_warning():
    rec = processing.recommend(hw(8), lockdown=False)
    assert rec["warning"] == "This Mac has 8 GB of memory. Cloud is recommended; Local may be slow or fail on long calls."
    assert "competes with your call for memory" in rec["modes"]["local_light"]["reason"]
    assert processing.recommend(hw(32), lockdown=False)["warning"] is None


def test_unknown_memory_recommends_light_without_warnings():
    rec = processing.recommend(hw(0), lockdown=False)
    assert rec["recommended_mode"] == "local_light" and rec["low_ram"] is False
    assert "warn" not in levels(rec).values()


def test_under_lockdown_cloud_is_blocked_and_a_local_mode_is_recommended():
    rec = processing.recommend(hw(8), lockdown=True)
    assert rec["modes"]["cloud"]["level"] == "blocked"
    assert rec["recommended_mode"] == "local_light"


def test_hardware_reports_the_same_recommendation(monkeypatch):
    monkeypatch.setattr(processing, "_memory_bytes", lambda: 8 * 1024**3)
    monkeypatch.setattr(processing.platform, "machine", lambda: "arm64")
    hardware = processing.hardware()
    assert hardware["memory_gb"] == 8 and hardware["recommended_mode"] == "cloud"
    assert hardware["explanation"] == processing.recommend(hardware)["modes"]["cloud"]["reason"]


@pytest.mark.parametrize("gb, mode", [(8, "cloud"), (64, "local_thorough"), (18, "local_light")])
def test_a_team_build_defaults_to_the_recommendation(monkeypatch, gb, mode):
    db.init_db()
    monkeypatch.setattr(db, "get_setting", lambda key, default=None: default)
    monkeypatch.setattr(processing, "_config", lambda: {"default_processing_mode": "recommended"})
    monkeypatch.setattr(processing, "hardware", lambda: hw(gb))
    assert processing.preferences()["mode"] == mode


def test_the_processing_api_carries_the_recommendation(monkeypatch):
    from api.routes import settings as routes
    monkeypatch.setattr(processing, "hardware", lambda: hw(8))

    class Req:
        def send_json(self, body, status=200):
            self.body = body
    req = Req()
    routes.get_api_processing(req, "", {})
    assert req.body["recommendation"]["recommended_mode"] == "cloud"
    assert req.body["recommendation"]["modes"]["local_thorough"]["level"] == "blocked"
