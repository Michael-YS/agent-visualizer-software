# Agent Monitor OpenCode plugin

This standalone TypeScript plugin reports OpenCode session state to the local
Agent Monitor bridge. It uses OpenCode's native `event` plugin hook and needs no
Python package or sibling adapter.

## Install

Build from this folder, then copy the bundled `dist/index.js` into OpenCode's
global plugin directory. The bundle is self-contained apart from Node built-ins,
so OpenCode sees just one plugin function export:

```powershell
npm install
npm run build
New-Item -ItemType Directory -Force "$HOME\.config\opencode\plugins"
Copy-Item .\dist\index.js "$HOME\.config\opencode\plugins\agent-monitor.js"
```

OpenCode loads JavaScript and TypeScript plugins from
`~/.config/opencode/plugins/` at startup. Restart OpenCode after copying the
plugin. The bridge must be running at `http://127.0.0.1:8000` or set
`AGENT_MONITOR_BRIDGE_URL` to its base URL before starting OpenCode.

Project-level installation is also supported: copy `dist/index.js` to
`.opencode/plugins/agent-monitor.js` in the project. The adapter is not enabled
until installed in one of those native plugin locations.

## State mapping

| OpenCode event | Monitor state |
| --- | --- |
| `session.created` | `idle` |
| `session.status` busy | `thinking` or `tool_running` when a tool part is active |
| `session.status` retry | `thinking` |
| `permission.asked` / permission update | `needs_input` |
| `permission.replied`, `question.replied`, or `question.rejected` | `idle`, `thinking`, or `tool_running` from tracked session state |
| `question.asked` | `needs_input` |
| `message.part.updated` tool pending/running | `tool_running` |
| `message.part.updated` tool completed/error | `thinking` or `turn_complete` |
| `session.idle` | `turn_complete` unless a permission/tool remains active |
| `session.error` | `error` |
| `session.deleted` | `offline` |

OpenCode's plugin event callback receives an object shaped as
`{ event: { type, properties } }`. The adapter is typed against
`@opencode-ai/plugin`'s SDK `Event` union, including the `question.*` events.
If a session is first observed through a later status or permission event, the
adapter attaches it then. Tool input and output are never used as
display text. Only the adapter's fixed labels, host name, and a stable hashed
session ID are sent. Status fields are limited to 96 UTF-8 bytes for name and
host and 512 bytes for detail.

Writes are serialized, bounded to 1.5 seconds, and coalesced to the latest
state during a bridge outage. The latest state is retried after a short delay.
A heartbeat is sent every 30 seconds only for sessions observed while the
plugin is attached. OpenCode provides no crash-end callback, so a hard process
termination cannot publish `offline`; use the monitor's stale-session timeout
for that case. The process exit listener only stops local timers; it cannot
reliably complete an asynchronous bridge request while the process is exiting.

## Build and test

```powershell
npm install
npm run build
npm test
```

The tests exercise OpenCode's event wrapper and representative current event
properties without starting OpenCode or the bridge.

## OpenCode API references

- [Plugin documentation](https://opencode.ai/docs/plugins/) — plugin loading,
  the event hook and documented event names.
- [OpenCode plugin event dispatch](https://github.com/anomalyco/opencode/blob/dev/packages/opencode/src/plugin/index.ts)
- [OpenCode SDK event types](https://github.com/anomalyco/opencode/blob/dev/packages/sdk/js/src/gen/types.gen.ts)
