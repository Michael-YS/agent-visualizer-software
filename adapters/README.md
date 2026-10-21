# Agent Monitor adapters

Each harness is an independent project. Install, build and test from its own
directory; no adapter imports code from a sibling. All publish the existing
six-field status protocol to the bridge at this repository root (`../` from this directory).

| Harness | Project | Integration | Runtime |
| --- | --- | --- | --- |
| Codex | [codex](codex/README.md) | Hooks + MCP + skill | Python collector, port 18765 |
| Claude Code | [claude-code](claude-code/README.md) | Command hooks + reporting skill | Python collector, port 18766 |
| OpenCode | [opencode](opencode/README.md) | Native plugin | Inside OpenCode |
| Pi coding agent | [pi](pi/README.md) | Native extension | Inside Pi |

The Python collectors and native extensions forward to
`http://127.0.0.1:8000/v1/agents/state` by default. Set
`AGENT_MONITOR_BRIDGE_URL` in the relevant adapter environment to change it.
Native extensions do not require the Codex or Claude collectors.

Each entry represents a native session; IDs incorporate the host, harness and
session so two harnesses cannot collide even when their native session IDs are
equal. States and display byte limits remain those of the HTTP bridge. The
adapter-specific README documents events, lifecycle limitations, installation
and verification commands.

Subprocess hook integrations only heartbeat sessions with a verified live
source process. In-process plugins heartbeat attached sessions; abrupt harness
termination relies on the monitor's stale timeout. A heartbeat is process
liveness, not proof that the model is making progress.

Code builds and event-fixture tests can run without installing the harness or
editing its configuration. Live harness installation and an MQTT-connected
hardware smoke test are separate verification steps.
