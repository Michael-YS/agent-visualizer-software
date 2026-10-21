---
name: report-status
description: Report meaningful Codex task status changes to Agent Monitor.
---

# Report status to Agent Monitor

Use the Agent Monitor MCP tool `report_status` with the `monitor_session_id` injected by the Codex `SessionStart` hook. Do not substitute the Codex session ID or invent an ID. If the injected ID is missing, skip reporting and continue the task normally.

Call `report_status(session_id, state, detail)` only when the task enters a meaningful phase, needs user input, encounters a task-level error, or completes:

- `thinking`: substantive analysis or implementation has started.
- `tool_running`: a substantial external operation is underway and hooks do not already report it.
- `needs_input`: progress is blocked on a concrete user decision or answer; state briefly what is needed.
- `error`: the task cannot proceed because of a material failure; state the blocker briefly.
- `turn_complete`: the requested work is complete; summarize the outcome briefly.
- `idle`: the work was interrupted or deliberately paused.

Keep `detail` concise and safe to display. Never include prompts, secrets, full commands, or tool output. Do not report on every tool call, send periodic heartbeat updates, or duplicate routine states already supplied by hooks. In combined hook and MCP mode, use MCP mainly to add useful task-level context and to report `needs_input` or `error` that lifecycle hooks cannot infer.
