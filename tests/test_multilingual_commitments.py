"""Fictional turns exercising the action-item prefilter, without a model."""
import unicodedata

import pytest

from pipeline.notes import _mine_commitment_turns


@pytest.mark.parametrize(("promises", "other"), [
    (["Draft நாளை அனுப்புவேன்.", "Draft naalai anuppuven."], "அவர் அதை அனுப்புவார்."),
    (["Report రేపు పంపిస్తాను.", "Report repu pampistanu."], "ఆమె రేపు పంపుతుంది."),
    (["Draft কাল পাঠাবো।", "Draft kal pathiye debo."], "আমি draft পাঠাবো না।"),
    (["Notes उद्या पाठवेन।", "Notes udya pathavto."], "ती उद्या पाठवेल."),
    (["Voy a revisar el draft.", "Mañana compartiré el draft.", unicodedata.normalize("NFD", "Revisaré el plan.")], "No enviaré el draft."),
    (["Vou enviar o draft.", "Revisarei o plano."], "Não vou enviar o draft."),
    (["I'll send the draft.", "Draft bhej dungi."], "The draft arrived."),
])
def test_commitment_turns_keep_speaker_and_original_text(promises, other):
    turns = [{"speaker_name": "A", "text": text} for text in [*promises, other]]
    assert _mine_commitment_turns(turns, min_turns=2) == "\n".join(f"A: {text}" for text in promises)
    assert _mine_commitment_turns(turns, min_turns=len(promises) + 1) == ""


def test_mixed_language_meeting_reaches_threshold_across_speakers():
    turns = [
        {"speaker_name": "A", "text": "I'll share the outline."},
        {"speaker_name": "B", "text": "Draft काल पाठवेन।"},
        {"speaker_name": "A", "text": "Vou revisar o plano."},
        {"speaker_name": "C", "text": "The draft is on the screen."},
    ]
    assert _mine_commitment_turns(turns).splitlines() == [
        "A: I'll share the outline.", "B: Draft काल पाठवेन।", "A: Vou revisar o plano.",
    ]


@pytest.mark.parametrize("count", [2, 3])
def test_action_item_model_receives_selected_turns_or_full_context(fake_text, count):
    from pipeline.notes import generate_enhanced_notes
    from pipeline.text_model import text_model

    turns = [{"speaker_name": "A", "text": text} for text in
             ["Notes उद्या पाठवेन।", "Revisaré el draft.", "Report repu pampistanu."][:count]]
    filler = "The calendar is on screen."
    turns.append({"speaker_name": "B", "text": filler})
    transcript = "\n".join(f"{turn['speaker_name']}: {turn['text']}" for turn in turns)
    generate_enhanced_notes(transcript, [], turns, text_model({}))
    action_prompt = next(call["prompt"] for call in fake_text.calls if "Extract ONLY the concrete action" in call["prompt"])
    assert (filler in action_prompt) == (count < 3)
    assert all(f"A: {turn['text']}" in action_prompt for turn in turns[:-1])
    assert filler in fake_text.calls[0]["prompt"]  # overview still receives the whole transcript
