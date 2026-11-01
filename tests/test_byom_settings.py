"""Bring-your-own-model Settings: base-URL resolution, listing a provider's
models through the backend, and the credentials routes Settings calls.

Transport is stubbed at requests.get/post; keys and provider bodies must
never appear in what the renderer receives."""
from pipeline import text_model as tm


def test_base_url_is_the_entered_url_else_the_preset_default():
    assert tm.base_url("groq") == "https://api.groq.com/openai/v1"
    assert tm.base_url("ollama", "") == "http://localhost:11434/v1"
    assert tm.base_url("custom", " http://localhost:4000/v1/ ") == "http://localhost:4000/v1"
    assert tm.base_url("custom") == ""
