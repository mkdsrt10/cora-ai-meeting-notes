import pytest

from pipeline import romanize as r


@pytest.mark.parametrize("native,roman", [
    ("ठीक है", "theek hai"), ("क्या कर रहे हो", "kya kar rahe ho"), ("मतलब", "matlab"),
    ("मैं कल भेज दूंगा", "main kal bhej doonga"), ("नहीं", "nahin"), ("ज़रूर", "zaroor"),
    ("Okay मतलब", "Okay matlab"), ("हाँ", "haan"),
])
def test_rule_based_transliteration(native, roman):
    assert r.transliterate(native) == roman


def test_llm_output_is_used_when_valid_and_rules_otherwise():
    segments = [
        {"text": "मेरा समराइजेशन पार्ट"},
        {"text": "ठीक है"},
        {"text": "already latin"},
    ]

    def fake_llm(prompt):
        assert "[0]" in prompt and "[1]" in prompt and "[2]" not in prompt  # only Devanagari turns sent
        return "[0] mera summarization part\n[1] ठीक है"  # second line still Devanagari -> rejected

    stats = r.romanize_segments(segments, generate=fake_llm)
    assert segments[0]["text"] == "mera summarization part" and segments[0]["text_script_method"] == "llm"
    assert segments[1]["text"] == "theek hai" and segments[1]["text_script_method"] == "rules"
    assert segments[0]["text_native"] == "मेरा समराइजेशन पार्ट"  # original kept for training
    assert segments[2] == {"text": "already latin"}
    assert stats == {"segments": 2, "llm": 1, "rules": 1}


def test_llm_output_with_implausible_length_is_rejected():
    segments = [{"text": "ठीक है"}]
    r.romanize_segments(segments, generate=lambda p: "[0] " + "made up content " * 20)
    assert segments[0]["text"] == "theek hai"


def test_native_mode_leaves_text(monkeypatch):
    monkeypatch.setattr(r, "target_script", lambda: "native")
    segments = [{"text": "ठीक है"}]
    r.romanize_segments(segments)
    assert segments[0]["text"] == "ठीक है"
