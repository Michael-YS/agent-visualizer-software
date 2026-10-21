---
name: report-status
description: Report a meaningful Claude Code session status change to the local Agent Monitor adapter. Use the exact session ID supplied by the Claude Code adapter's SessionStart hook.
---

# Report Claude Code session status

Send a report only for a meaningful state change that lifecycle hooks cannot identify, such as a human decision request or a task-level error. Hook events already report prompts, tools, permission waits, turn completion, API failure, and session end. Avoid repetitive updates.

Use the exact `session_id` from the Agent Monitor `SessionStart` context. Valid states are `idle`, `thinking`, `tool_running`, `needs_input`, `turn_complete`, `error`, and `offline`. Keep `detail` brief and high-level. Never include the user's prompt, private file contents, shell commands, tool arguments, credentials, or raw tool output.

Send one JSON object on standard input to the installed `agent-monitor-claude-report` command. The command validates the fields with Python and posts to the local receiver at `AGENT_MONITOR_CLAUDE_ADAPTER_URL`, defaulting to `http://127.0.0.1:18766`. For example, send `{"session_id":"<exact session_id>","state":"needs_input","detail":"Waiting for a user decision"}` through stdin. On PowerShell, stream a JSON here-string to the command's stdin; keep user-derived text out of the shell command and include only a short, non-sensitive status summary. The command has a 650 ms timeout and silently fails open if the receiver is unavailable.

The receiver forwards the latest report to the Agent Monitor bridge. Do not send a report after `SessionEnd`; the hook has already marked the session offline.
