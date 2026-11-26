import pytest

import credentials


@pytest.mark.parametrize("url", ["https://api.openai.com/v1", "http://localhost:11434/v1", "http://127.0.0.1:8080"])
def test_llm_base_url_allowed(url):
    assert credentials.validate_llm_base_url(url)


@pytest.mark.parametrize("url", ["http://evil.example.com/v1", "file:///etc/passwd", "https://user:pw@x.com", "ftp://x", ""])
def test_llm_base_url_rejected(url):
    with pytest.raises(ValueError):
        credentials.validate_llm_base_url(url)

