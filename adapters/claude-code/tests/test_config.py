from claude_code_adapter.config import Settings


def test_claude_bridge_url_overrides_common_bridge_url(monkeypatch):
    monkeypatch.setenv("AGENT_MONITOR_BRIDGE_URL", "http://127.0.0.1:8010/")
    monkeypatch.delenv("AGENT_MONITOR_CLAUDE_BRIDGE_URL", raising=False)
    assert Settings.from_env().bridge_url == "http://127.0.0.1:8010"
    monkeypatch.setenv("AGENT_MONITOR_CLAUDE_BRIDGE_URL", "http://127.0.0.1:8020/")
    assert Settings.from_env().bridge_url == "http://127.0.0.1:8020"
