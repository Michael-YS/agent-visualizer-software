# Claude Code adapter

This is an independent Python package for forwarding Claude Code hook events to the Agent Monitor bridge. It has no runtime import or package dependency on another adapter. The HTTP bridge defaults to `http://127.0.0.1:8000`; the local receiver listens only on `127.0.0.1:18766` by default.

The event names, matchers, stdin JSON input, and `SessionStart` `hookSpecificOutput.additionalContext` response follow Anthropic's [Hooks reference](https://code.claude.com/docs/en/hooks). The adapter listens to `SessionStart`, `UserPromptSubmit`, `PreToolUse`, `PostToolUse`, `PostToolUseFailure`, `PermissionRequest`, permission and idle `Notification`, `Stop`, `StopFailure`, and `SessionEnd`. A failed tool remains part of the work state; API failure reported by `StopFailure` is shown as an error. Permission and idle notifications remain visible across `Stop`, so a manual wait is not cleared as completed.

## Install and run

From this directory, install the package and its optional test tools into the Python environment that will run Claude Code hooks:

```powershell
python -m pip install -e ".[test]"
agent-monitor-claude-adapter
```

Install the hook configuration either by enabling the plugin from this directory with `claude --plugin-dir D:\code\agent-visualizer\agent-visualizer-software\adapters\claude-code\plugin`, or by merging [`settings.example.json`](settings.example.json) into your user or project `.claude/settings.json`. The hook command must be available on `PATH` in Claude Code's environment. Plugin hook registration lives under [`plugin/hooks/hooks.json`](plugin/hooks/hooks.json). The settings-only installation does not load plugin skills; to use the optional report workflow, copy [`plugin/skills/report-status/SKILL.md`](plugin/skills/report-status/SKILL.md) into `~/.claude/skills/report-status/SKILL.md`.

Configuration environment variables:

| Variable | Default | Purpose |
| --- | --- | --- |
| `AGENT_MONITOR_CLAUDE_ADAPTER_URL` | `http://127.0.0.1:18766` | Hook receiver URL |
| `AGENT_MONITOR_CLAUDE_ADAPTER_HOST` | `127.0.0.1` | Receiver bind address |
| `AGENT_MONITOR_CLAUDE_ADAPTER_PORT` | `18766` | Receiver bind port |
| `AGENT_MONITOR_CLAUDE_BRIDGE_URL` | `AGENT_MONITOR_BRIDGE_URL`, then `http://127.0.0.1:8000` | Agent Monitor bridge base URL |
| `AGENT_MONITOR_CLAUDE_HEARTBEAT_SECONDS` | `30` | Heartbeat interval for process-bound sessions |
| `AGENT_MONITOR_CLAUDE_RETRY_SECONDS` | `2` | Receiver retry interval |

Hooks post locally with a 650 ms request timeout and fail open when the receiver is unavailable. The receiver queues the latest state and retries bridge publication; it does not queue every intermediate update. It sends a heartbeat only when a Claude Code ancestor process and its creation time were positively identified. Missing process identity therefore means event updates still work, but the session is not kept alive by fabricated heartbeats.

The report endpoint is `POST http://127.0.0.1:18766/v1/reports`, with JSON such as `{"session_id":"<exact hook session_id>","state":"needs_input","detail":"Waiting for a choice"}`. Use the exact session ID injected by the `SessionStart` hook; explicit reports can set `idle`, `thinking`, `tool_running`, `needs_input`, `turn_complete`, `error`, or `offline`.

The plugin's `/agent-monitor-claude-code:report-status` skill describes when to send an explicit report. The installed `agent-monitor-claude-report` command accepts JSON on stdin, validates it, and posts with a bounded timeout; status text does not need to appear in shell arguments.

Install and start the separate bridge service as described in the repository's main README. This package only sends bridge-compatible agent status frames; it does not install or configure the bridge.

## Development

```powershell
python -m pytest
```
