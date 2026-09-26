import json

import speaker_guess as sg


def seg(sid, text):
    return {"speaker_id": sid, "speaker_name": sid, "text": text}


ROSTER = ["Jane Doe", "Priya Shah", "Rahul Mehta"]


def test_rules_self_intro_and_handoff():
    segments = [
        seg("You", "Morning all. Priya, can you start with the roadmap?"),
        seg("Participant", "Sure, so the roadmap has three phases."),
        seg("Participant", "Hi everyone, this is Rahul from finance."),
    ]
    stats = sg.guess_speakers(segments, ROSTER, "Jane Doe", "Roadmap", generate=None)
    assert [s["speaker_name"] for s in segments] == ["You", "Priya Shah", "Rahul Mehta"]
    assert segments[1]["speaker_source"] == "rule_guess" and segments[1]["original_speaker_id"] == "Participant"
    assert stats == {"unresolved": 2, "rule": 2, "llm": 0, "kept_generic": 0}


def test_llm_guess_is_validated():
    segments = [
        seg("You", "Let's look at the budget numbers."),
        seg("Participant", "The budget is up ten percent this quarter."),
        seg("Participant", "I disagree with the forecast."),
        seg("Participant", "Ok."),
    ]

    def fake_llm(prompt):
        assert "[1] ???" in prompt and "[0] ME" in prompt and "Jane" not in prompt.split("TRANSCRIPT")[0].split("(other")[0]
        return json.dumps([
            {"turn": 1, "speaker": "Rahul Mehta", "confidence": 0.8, "evidence": "The budget is up ten percent"},
            {"turn": 2, "speaker": "Somebody Else", "confidence": 0.9, "evidence": "I disagree"},       # not on roster
            {"turn": 3, "speaker": "Priya Shah", "confidence": 0.9, "evidence": "a quote that isn't there"},  # fabricated
            {"turn": 0, "speaker": "Priya Shah", "confidence": 0.9, "evidence": "budget numbers"},    # my own turn
        ])

    stats = sg.guess_speakers(segments, ROSTER, "Jane Doe", "Budget", generate=fake_llm, model_id="test-llm")
    assert segments[0]["speaker_id"] == "You"
    assert segments[1]["speaker_name"] == "Rahul Mehta" and segments[1]["speaker_source"] == "llm_guess"
    assert segments[1]["speaker_guess"]["model"] == "test-llm"
    assert segments[2]["speaker_id"] == "Participant" and "speaker_guess" not in segments[2]
    assert segments[3]["speaker_id"] == "Participant" and segments[3]["speaker_guess"]["confidence"] <= 0.4
    assert stats["llm"] == 1 and stats["kept_generic"] == 2


def test_nothing_to_do_without_roster():
    segments = [seg("Participant", "hello")]
    assert sg.guess_speakers(segments, [], "Jane", "")["kept_generic"] == 1
    assert segments[0]["speaker_id"] == "Participant"


def test_truncated_llm_output_is_salvaged():
    import json_repair
    raw = ('[{"turn": 1, "speaker": "Priya Shah", "confidence": 0.9, "evidence": "roadmap"}, '
           '{"turn": 2, "speaker": "Rahul Mehta", "confidence": 0.8, "evidence": "budget"}, {"turn": 3, "speak')
    items = sg.parse_guess_list(raw, json_repair)
    assert [i["turn"] for i in items] == [1, 2]
    assert sg.parse_guess_list("no json here", json_repair) == []
    assert [i["turn"] for i in sg.parse_guess_list('[{"turn": 5, "speaker": "X"}]', json_repair)] == [5]
