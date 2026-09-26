import pytest

import credentials
import vm_sync


@pytest.mark.parametrize("url", ["https://api.openai.com/v1", "http://localhost:11434/v1", "http://127.0.0.1:8080"])
def test_llm_base_url_allowed(url):
    assert credentials.validate_llm_base_url(url)


@pytest.mark.parametrize("url", ["http://evil.example.com/v1", "file:///etc/passwd", "https://user:pw@x.com", "ftp://x", ""])
def test_llm_base_url_rejected(url):
    with pytest.raises(ValueError):
        credentials.validate_llm_base_url(url)


@pytest.mark.parametrize("host", ["-oProxyCommand=touch /tmp/pwned", "a b", "host;rm -rf", ""])
def test_vm_sync_rejects_option_injection(host):
    assert vm_sync.HOST_RE.fullmatch(host) is None
    ok, _ = vm_sync.check_vm_reachability(host)
    assert not ok


def test_vm_sync_disabled_without_config():
    assert vm_sync.configured_target() is None
    assert vm_sync.sync_to_vm()["status"] == "disabled"
