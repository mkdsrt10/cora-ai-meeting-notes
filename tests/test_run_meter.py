"""The run meter behind processing_finished's performance keys: CPU deltas,
seconds per pipeline stage, and system state sampled during the run. Probes
are faked; nothing here runs vm_stat or pmset."""
import json

import pytest

import run_meter
import usage_events
from run_meter import RunMeter

VM_STAT = """Mach Virtual Memory Statistics: (page size of 16384 bytes)
Pages free:                                   1000.
Pages active:                                 9999.
Pages inactive:                               2000.
Pages speculative:                             100.
"""


def test_probes_parse_what_macos_prints():
    assert run_meter.free_mb(VM_STAT) == round(3100 * 16384 / 1024**2)
    assert run_meter.swap_mb("total = 2048.00M  used = 1536.25M  free = 511.75M  (encrypted)") == 1536
    assert run_meter.swap_mb("total = 4.00G  used = 1.50G  free = 2.50G") == 1536
    assert [run_meter.pressure(t) for t in ("1\n", "2\n", "4\n", "x")] == ["normal", "warn", "critical", None]
    assert run_meter.thermal("Note: No thermal warning level has been recorded\n") == "nominal"
    assert run_meter.thermal("CPU_Scheduler_Limit = 100\nCPU_Speed_Limit = 70\n") == "throttled"
    assert run_meter.thermal("Thermal Warning Level = 1\n") == "warning"
    assert run_meter.on_battery("Now drawing from 'Battery Power'\n") is True
    assert run_meter.on_battery("Now drawing from 'AC Power'\n") is False


def test_stages_add_up_wall_seconds_per_stage():
    now = [0.0]
    meter = RunMeter(sample=False, clock=lambda: now[0], queue_wait_s=12.34)
    for stage, at in (("starting", 0), ("transcribing", 1), ("aligning_speakers", 31), ("generating_notes", 33),
                      ("transcribing", 40), ("persisting", 45)):
        now[0] = at
        meter.mark(stage)
    now[0] = 46
    meter.stop()
    out = meter.payload()
    assert (out["stage_starting_s"], out["stage_transcribing_s"], out["stage_aligning_speakers_s"]) == (1.0, 35.0, 2.0)
    assert (out["stage_generating_notes_s"], out["stage_persisting_s"], out["stage_romanizing_s"]) == (7.0, 1.0, None)
    assert out["queue_wait_s"] == 12.3
    assert out["cpu_user_s"] >= 0 and out["cpu_sys_s"] >= 0


def test_samples_keep_start_extremes_and_the_free_memory_at_the_rss_peak():
    meter = RunMeter(sample=False)
    seq = [  # free, swap, pressure, rss, thermal, battery
        (4000, 0, "normal", 300.0, "nominal", False),
        (900, 512, "warn", 1900.0, "nominal", False),
        (1500, 2048, "critical", 800.0, "throttled", True),
    ]
    for i, (free, swap, level, rss, therm, batt) in enumerate(seq):
        meter._samples = 0  # every sample is a slow one here
        meter.take_sample(first=(i == 0), probes={"free": lambda f=free: f, "swap": lambda s=swap: s,
                                                  "pressure": lambda p=level: p, "rss": lambda r=rss: r,
                                                  "thermal": lambda t=therm: t, "battery": lambda b=batt: b})
    out = meter.payload()
    assert (out["sys_free_mb_start"], out["sys_free_mb_min"], out["sys_free_mb_at_peak"]) == (4000, 900, 900)
    assert (out["swap_mb_start"], out["swap_mb_max"]) == (0, 2048)
    assert (out["pressure_max"], out["thermal_max"], out["on_battery"]) == ("critical", "throttled", True)
    assert out["peak_rss_mb"] == 1900.0  # this run's own peak, not the server's lifetime high-water mark


def test_a_failing_probe_leaves_its_key_null_and_never_raises():
    def boom():
        raise OSError("no vm_stat")
    meter = RunMeter(sample=False)
    meter.take_sample(first=True, probes={k: boom for k in ("free", "swap", "pressure", "rss", "thermal", "battery")})
    out = meter.payload()
    assert out["sys_free_mb_min"] is None and out["pressure_max"] is None


def test_a_call_going_live_during_the_run_is_noted():
    meter = run_meter.start(call_live=False)
    run_meter.set_call_live(True)
    run_meter.set_call_live(False)
    assert run_meter.finish(meter)["call_live"] is True


def test_the_payload_fits_the_catalog_and_carries_no_text():
    meter = RunMeter(sample=False)
    meter.stop()
    payload = meter.payload()
    assert set(payload) <= usage_events.CATALOG["processing_finished"]
    usage_events.validate("processing_finished", payload)
    assert all(v is None or isinstance(v, (int, float, bool)) or v in ("normal", "warn", "critical", "nominal",
                                                                       "warning", "throttled") for v in payload.values())
    json.dumps(payload)


def test_processing_finished_carries_the_meter_and_model_load(tmp_path, monkeypatch, fake_text, fake_transcriber):
    import db
    from test_usage_emitters import PROFILE, _events, _recording
    from pipeline import runner
    with db.get_db() as conn:
        conn.execute("DELETE FROM usage_events")
        conn.commit()
    folder = _recording("perf-run", monkeypatch, fake_text, fake_transcriber)
    runner.process_recording_local(folder, PROFILE, run_info={"queue_wait_s": 42.0, "call_live": True})
    [event] = _events(tmp_path, "processing_finished")
    assert event["queue_wait_s"] == 42.0 and event["call_live"] is True
    assert event["stage_starting_s"] is not None and event["stage_persisting_s"] is not None
    assert event["cpu_user_s"] >= 0
    assert event["model_load_s"] is None, "an all-cloud profile loads no local model"


@pytest.mark.parametrize("profile, expected", [
    ({"transcription": "local", "provider": "local_mlx"}, 0.0),
    ({"transcription": "gemini", "provider": "gemini"}, None),
])
def test_model_load_s_without_load_spans(profile, expected):
    import usage_emitters
    assert usage_emitters._model_load_s([], profile) == expected
    assert usage_emitters._model_load_s([{"kind": "model_load", "duration_s": 3.24}, {"kind": "llm"}], profile) == 3.2
