from pathlib import Path

from claude_code_adapter import report


def test_report_payload_validates_and_bounds_detail():
    payload = report._payload({"session_id": "sid", "state": "needs_input",
                               "detail": "é" * 500})
    assert payload is not None
    assert len(payload["detail"].encode("utf-8")) <= report.MAX_DETAIL_BYTES
    assert report._payload({"session_id": "sid", "state": "not-a-state"}) is None
    assert report._payload({"state": "thinking"}) is None


def test_plugin_skill_is_present_and_uses_injected_identity():
    skill = Path(__file__).parents[1] / "plugin" / "skills" / "report-status" / "SKILL.md"
    text = skill.read_text(encoding="utf-8")
    assert "exact `session_id`" in text
    assert "agent-monitor-claude-report" in text
    assert "Never include the user's prompt" in text
