import json
from pathlib import Path


PLUGIN_ROOT = Path(__file__).parents[1] / "codex-plugin"


def test_plugin_manifest_references_existing_components() -> None:
    manifest = json.loads((PLUGIN_ROOT / "plugin.json").read_text(encoding="utf-8"))
    extension = manifest["extensions"]["com.openai"]
    assert (PLUGIN_ROOT / extension["hooks"]).is_file()
    assert (PLUGIN_ROOT / "mcp.json").is_file()
    assert (PLUGIN_ROOT / "skills" / "report-status" / "SKILL.md").is_file()


def test_all_hook_commands_use_installed_adapter_module() -> None:
    config = json.loads((PLUGIN_ROOT / "hooks" / "hooks.json").read_text(encoding="utf-8"))
    handlers = [
        handler
        for groups in config["hooks"].values()
        for group in groups
        for handler in group["hooks"]
    ]
    assert handlers
    assert {handler["command"] for handler in handlers} == {
        "python3 -m agent_monitor_adapter.codex_hook"
    }
    assert {handler["commandWindows"] for handler in handlers} == {
        "python -m agent_monitor_adapter.codex_hook"
    }
    user_prompt = config["hooks"]["UserPromptSubmit"][0]["hooks"][0]
    assert "async" not in user_prompt
