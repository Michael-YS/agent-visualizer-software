# Integrate any agent harness

The contract is [status.schema.json](status.schema.json), generated from the
bridge's `app.models.AgentStatus`. Build the smallest native hook, plugin or
extension for the installed harness. Existing [adapters](adapters/README.md)
are optional reference implementations; they are not dependencies.

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
  "detail": "Waiting for a user decision",
  "timestamp": 1792530000
}
```

`id`, `name`, `host`, and `state` are required. Omitted `detail` becomes `""`;
omitted `timestamp` becomes the bridge's current Unix time in seconds. Send a
fresh timestamp on each update and heartbeat. Extra fields are rejected.

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
| `needs_input` | Confirmed approval request or explicit task-level request for a human answer |
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
