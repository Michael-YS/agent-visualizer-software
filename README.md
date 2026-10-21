# Agent Monitor Software

Small agent-agnostic service that accepts normalized status events over HTTP
and publishes retained MQTT messages for the ESP32 monitor.

## Repository layout

- [AGENT_SETUP.md](AGENT_SETUP.md): standalone instructions you can send directly
  to an agent to set up reporting for its harness.
- `app/`, `tests/`, and `pyproject.toml`: HTTP-to-MQTT bridge.
- [status.schema.json](status.schema.json) and [INTEGRATION.md](INTEGRATION.md):
  harness-independent contract and instructions for generating your own hooks.
- [skills/integrate-agent-monitor/](skills/integrate-agent-monitor/SKILL.md):
  give this skill to an agent in the target harness to implement and verify its integration.
- [adapters/](adapters/README.md): independently installable harness adapters.

Firmware, wiring and the device plan live in `agent-visualizer-hardware`.
Each repository builds independently and communicates through the MQTT topic
and status payload below. Run bridge commands from this repository root.

## Run locally

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[test]"
Copy-Item .env.example .env
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Set `MQTT_HOST` in `.env` to the broker reachable by both this service and the
ESP32. The service reconnects in the background and reports MQTT readiness at
`GET /health`.

The bridge marks agents offline after 120 seconds without an update and deletes
their retained MQTT messages after five continuous minutes offline. Cleanup runs
every second; failed MQTT writes are retried after reconnection. Incoming updates
cancel pending reclamation. Repeated offline updates do not reset the timer.
The bridge also reads retained messages on connection to reclaim old entries
after a restart. Configure `AGENT_STALE_SECONDS` and
`AGENT_OFFLINE_RETENTION_SECONDS` in `.env` to change these intervals.

Codex and Claude Code adapters reclaim offline session records after five minutes;
unbound sessions without updates first become offline after 120 seconds. Verified
live process bindings continue to heartbeat. OpenCode reclaims offline sessions
on its 30-second heartbeat sweep. Pi releases drained publication queues.

## Publish a state

```powershell
$body = @{
  id = "codex-m3u8"
  name = "Codex / M3U8"
  host = "desktop"
  state = "needs_input"
  detail = "Approve command"
} | ConvertTo-Json

Invoke-RestMethod `
  -Method Post `
  -Uri http://localhost:8000/v1/agents/state `
  -ContentType application/json `
  -Body $body
```

The bridge publishes the validated payload with QoS 1 and `retain=true` to:

```text
agent-monitor/v1/agents/<agent-id>/state
```

Allowed states: `offline`, `idle`, `thinking`, `tool_running`, `needs_input`,
`turn_complete`, and `error`.

The V1 API has no authentication or TLS. Keep it on a trusted LAN or place it
behind an authenticated reverse proxy; do not expose port 8000 directly to the
public internet.

## Test

```powershell
.\.venv\Scripts\python.exe -m pytest
```
