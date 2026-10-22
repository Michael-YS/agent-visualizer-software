# Agent Monitor Codex Adapter

This package connects Codex lifecycle hooks and an optional MCP reporting tool
to the existing Agent Monitor bridge. It supports Codex CLI and local Codex
desktop tasks. Each native Codex session becomes one monitor entry.

## Data flow

```text
Codex hooks -----> local adapter -----> bridge -----> MQTT -----> ESP32
Agent -> MCP -----^
```

Hooks provide automatic execution state. The MCP tool lets the agent attach a
short task-level explanation or explicitly report `needs_input` and `error`.
Both paths use the same native session ID and reducer.

The adapter reads each session's `thread_name` from the local
`$CODEX_HOME/session_index.jsonl` (default: `~/.codex/session_index.jsonl`).
Monitor names use `Codex / <chat title> / <short session ID>`, so the bridge's
Web UI, read API and ESP32 all show the same title. Names stay within 96 UTF-8
bytes. Renames are picked up on the next publication sweep, normally within
two seconds. Until a title is available, names retain the project-name fallback.
Missing or unreadable indexes do not interrupt status reporting; an already
known title is retained. Run the adapter as the same user as Codex, or set
`CODEX_HOME` to that user's Codex data directory.

## Install and run

Install into the `python` interpreter visible to Codex. A user install is the
simplest choice for both the desktop app and CLI:

```powershell
cd adapters/codex
python -m pip install --user -e ".[test]"
Copy-Item .env.example .env
python -m agent_monitor_adapter.service
```

The adapter listens on `127.0.0.1:18765` and forwards to the bridge at
`http://127.0.0.1:8000` by default. Keep both services running. Configuration
uses the variables documented in `.env.example`.

Verify that Codex's Python can import the package:

```powershell
python -c "import agent_monitor_adapter"
```

Restart the desktop app after changing its `PATH`.

## Install the Codex plugin

The local marketplace packages the hooks, MCP server, and reporting skill:

```powershell
codex plugin marketplace add .
codex plugin add agent-monitor-codex@agent-monitor-local
```

Open `/hooks` in Codex and review and trust the plugin hooks. Unmanaged hooks
are skipped until trusted. Start a new session after installation.

The plugin follows the current [Codex Hooks documentation](https://learn.chatgpt.com/docs/hooks)
and [plugin packaging format](https://developers.openai.com/plugins/build/plugins).
It was developed against `codex-cli 0.155.0-alpha.16.4`.

## State behavior

| Codex event | Monitor state |
| --- | --- |
| Session start or resume | `idle` |
| User prompt | `thinking` |
| Tool start | `tool_running` |
| Permission request | `needs_input` |
| Turn stop | `turn_complete` |
| Interrupt | `idle` |
| Session end or source process exit | `offline` |

The adapter sends a heartbeat every 30 seconds only for sessions bound to a
live Codex process. It retains only the latest state while the bridge is
unavailable and retries in the background. A heartbeat confirms that the
source process is alive; it does not detect an internally stuck session.

MCP does not expose the caller's Codex session ID. The `SessionStart` hook
therefore injects `monitor_session_id` into the agent context, and the skill
passes that exact value to `report_status`. MCP-only callers must supply a real
session ID explicitly; the adapter never guesses from the working directory.

The adapter sends chat titles but does not read transcripts or send full commands
or tool output. A title can contain text derived from a prompt. Display text
is truncated to the firmware's UTF-8 byte limits.

## Test

```powershell
python -m pytest tests
```
