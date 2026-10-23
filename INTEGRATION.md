# Integrate any agent harness

The contract is [status.schema.json](status.schema.json), generated from the
bridge's `app.models.AgentStatus`. Build the smallest native hook, plugin or
extension for the installed harness. Existing [adapters](adapters/README.md)
are optional reference implementations; they are not dependencies.

For instructions that can be forwarded on their own, use [AGENT_SETUP.md](AGENT_SETUP.md).
Ask the user what to call this harness before configuring reporting; preserve
that confirmed value exactly in every `name` field. If it exceeds 96 UTF-8
bytes, ask for a shorter name. Prefer native hooks/events; consider MCP or a
skill when hooks are unavailable, or only to fill gaps in hook coverage.

## Status message

Send one JSON object to `POST <bridge-base-url>/v1/agents/state` with
`Content-Type: application/json`. The default base URL is
`http://127.0.0.1:8000`; allow configuration with `AGENT_MONITOR_BRIDGE_URL`.

```json
{
  "id": "my-harness-a34b90e2",
  "name": "Agent / project",
  "host": "desktop",
  "state": "needs_input",
  "detail": "Fix login timeout: waiting for retry policy confirmation",
  "timestamp": 1792530000
}
```

`id`, `name`, `host`, and `state` are required. Omitted `detail` becomes `""`;
omitted `timestamp` becomes the bridge's current Unix time in seconds. Send a
fresh timestamp on each update and heartbeat. Extra fields are rejected.

For integrations, `detail` must include an agent-written task summary and current
progress whenever a task exists, for example `Fix login timeout: checking retries`.
Keep `name` as the user-confirmed harness name. Cache the summary per session,
retain it through tool/wait/heartbeat/completion updates, and replace it when a
new task begins. Native events must not overwrite it with a generic label.
When hooks cannot obtain a safe summary, let the agent supply it once at task
start or a change of objective through a small local interface or MCP/skill;
hooks still drive lifecycle updates. Summarize the task purpose without copying
raw prompts or sensitive content. With no task, a plain waiting label is fine.
Keep within existing byte limits; do not add a new protocol field.

For Codex, session titles can be read by native session ID from `thread_name`
in the local `$CODEX_HOME/session_index.jsonl` (default `~/.codex/`). Verify the
installed version's index format. For generated integrations, keep the confirmed
`name` unchanged and append a display-safe title to `detail` alongside the task
summary and progress. Missing/unreadable indexes and partial records must not
interrupt reporting. Pick up renames without changing identity or lifecycle.
See [the standalone Codex instructions](AGENT_SETUP.md#codex补充会话标题) for
fallback and verification requirements. The reference Codex adapter instead
uses titles in its automatic `name`; adapt that mapping before reusing it for
the fixed-name onboarding contract. Never add a `title` protocol field.

Use a stable ID derived from host identity, harness name and native session ID,
for example `<harness>-<sha256(host|harness|session)[:20]>`. It must match
`^[A-Za-z0-9][A-Za-z0-9._-]*$` and be at most 96 characters. Keep it across a
resume of that session; use a different ID for a new session. Do not generate a
new ID for every tool call or infer the ID from a task's prose.

`id`, `name` and `host` must contain non-whitespace text. Name and host are each
limited to 96 UTF-8 bytes, detail to 512. Truncate at complete code points.
The compact JSON forwarded to MQTT, including all fields, must fit 1024 UTF-8
bytes; JSON escaping counts too. The `x-*` byte annotations in the schema are
informational to generic JSON Schema validators. Use the bridge validator below
to enforce byte, blank-value and total-message constraints.

## State semantics

| State | Evidence |
| --- | --- |
| `idle` | Session attached and waiting for a new request, or deliberately interrupted/paused |
| `thinking` | A request is being processed outside tool execution |
| `tool_running` | At least one tracked tool call is running |
| `needs_input` | Confirmed need for human approval or explicit task-level request for a human answer |
| `turn_complete` | Current agent turn ended successfully; session may remain open |
| `error` | Confirmed model/request failure or explicit task-level failure |
| `offline` | Session closed or its verified source process exited |

Prefer actual lifecycle events. A tool's nonzero exit is not proof of task
failure; the agent may recover. Silence is not proof of `needs_input`. Do not
map every end-of-turn event to `offline`, or model errors/aborts to successful
completion. Track concurrent tool IDs so finishing one tool does not finish all.
Clear permission waits on the matching resolution. Preserve explicit human
waits or task errors until genuinely resolved or a new user request begins;
routine tool callbacks must not erase them. A skill/MCP/tool may report the
same contract when hooks cannot infer task meaning. Both paths must use the
same session ID; the reporting tool must not overwrite its own reported state.

For every harness that supports automatic approval, distinguish human approval
from automated review. An approval-request event alone is not evidence that a
person must act. Policy engines and approval agents remain work in progress;
unknown routing must not imply human attention. Recheck routing on later events
and enter `needs_input` when review is actually handed to a person. Verify the
installed harness's own routing fields, events and resolution signals rather
than assuming another harness's schema applies.

For example, Codex's `PermissionRequest` alone is not evidence of a human wait. Distinguish
`approvals_reviewer=user` from `auto_review` / `guardian_subagent`; automatic
review remains work in progress. Unknown routing must not imply human attention.
If transcript metadata is used as a fallback, scope it to the current turn,
handle delayed/missing/changed records, and never retain transcript bodies.
At `Stop`, clear tool permission waits while preserving explicit questions and
task errors.

## Delivery and lifecycle

- Monitoring failures must not stop work, change tool arguments, or make an
  approval decision. Use a short timeout (for example 650 ms for a command hook)
  and preserve the harness's required hook response/exit behavior.
- HTTP 202 means accepted and published; 422 means invalid payload; 503 means
  MQTT is unavailable. Check `/health` for `mqtt_connected`. A validation-only
  check is not evidence of MQTT or hardware delivery.
- Retry transient failures in the background with a delay, retaining only the
  latest snapshot per session. Serialize writes per session so an older request
  cannot overwrite a newer state. Do not spin or keep a hook subprocess alive
  indefinitely to retry. Without a background owner, skip retry and send again
  on the next native event.
- Heartbeat about every 30 seconds only while an in-process integration is
  attached, or an external collector can verify the source PID and creation
  time. A hook subprocess being alive is not proof the agent is alive. Send
  fresh timestamps, stop heartbeats after shutdown, and rely on the monitor's
  stale timeout for hard crashes. Heartbeat means liveness, not model progress.
- Send only display-safe summaries. Do not copy prompts, commands, tool
  arguments, output, credentials or raw provider error messages into detail.

## Generate and verify an integration

Inspect accepted snapshots through the Web UI at `/` (two-second refresh),
`GET /v1/agents` (`agents`, `total`, `mqtt_connected`), or
`GET /v1/agents/{agent_id}` (the protocol ID; 404 if absent). API documentation
is at `/docs`. Reads remain available with last-known data during MQTT outages;
check `mqtt_connected` and do not treat HTTP success as proof of current data
or hardware delivery. Use one Uvicorn worker to share the in-memory registry.

Use [the integration skill](skills/integrate-agent-monitor/SKILL.md) with an
agent operating in the target harness. Inspect the installed harness version
and its actual documented hook API before generating configuration. Reuse a
matching existing adapter when practical. Merge configuration while preserving
existing hooks; do not register both a reference adapter and a generated hook
for the same session.

From this repository root, after installing `.[test]`:

```powershell
python -m app.protocol validate status.json
python -m app.protocol schema --check status.schema.json
python -m pytest
```

`validate` accepts `-` for stdin, emits normalized JSON and exits zero on
success. It performs no network calls. To regenerate the schema, write stdout
from `python -m app.protocol schema` to `status.schema.json` as UTF-8.

Test a native event sequence: session start, request, overlapping tools,
permission wait/resolution, turn completion, error/abort and shutdown. Also test
bridge outage and verify the harness continues normally. Validate captured
messages locally before sending a disposable test session to the bridge.
Use a separate test ID and finish it with `offline`. Report separately what
passed: payload validation, simulated event mapping, real harness callbacks,
HTTP/MQTT acceptance and hardware display. State unavailable checks explicitly.
