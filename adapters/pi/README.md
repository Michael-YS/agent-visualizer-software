# Pi Agent Monitor adapter

This package is a native Pi coding-agent extension. It observes Pi's session and tool lifecycle and sends compact status snapshots to the local Agent Monitor bridge at `POST /v1/agents/state`.

## Install and build

The package pins the current `@earendil-works/pi-coding-agent` release and compiles against its extension declarations. From this directory:

```sh
npm install
npm run build
```

Pi can load `./src/extension.ts` directly with `--extension` or through this package's `pi.extensions` manifest. Build the generated JavaScript with `npm run build` when you want to validate the TypeScript outside Pi.

Set `AGENT_MONITOR_BRIDGE_URL` to override the bridge base URL. The default is `http://127.0.0.1:8000`; the adapter appends `/v1/agents/state`. Requests use a one-second timeout and never delay Pi lifecycle callbacks. Failed sends retain only the latest state for each session and retry in the background; active sessions also send heartbeats every 30 seconds.

## Reported state

The payload contains only `id`, `name`, `host`, `state`, `detail`, and Unix-second `timestamp`. Session IDs are stable hashes of `host|pi|<Pi session id>`. Names and hosts are capped at 96 UTF-8 bytes, details at 512 UTF-8 bytes, and the serialized JSON body at 1024 bytes. No prompts, commands, tool arguments, or tool output are collected.

The pinned Pi 1.0.0 event declarations define `session_start`, `session_shutdown`, `agent_start`, `agent_end`, and `tool_execution_start`/`tool_execution_end`. There is no `session_switch` event: replacement emits shutdown for the old session and start for the new session. The adapter reports `offline` on shutdown, `idle` on session start or abort, `thinking` while the agent works, `tool_running` while one or more tools execute, and `turn_complete` after a normal agent end. A final assistant message with `stopReason: "error"` reports a static `error` detail; the provider's error text is never forwarded. Parallel tool calls are tracked independently. A tool's `isError` field is not treated as task failure because it can mean a command or tool failed while the task continues.

The model-callable `report_status` tool lets Pi explicitly report `needs_input` or a confirmed task-level `error`. Manual states remain until a new agent run starts or the session changes. The adapter does not infer `needs_input` from a missing response or emit a synthetic user prompt.

If Pi crashes before shutdown can be reported, the monitor will mark the entry stale/offline after its configured stale threshold (currently 120 seconds in the hardware firmware). Heartbeats maintain a live entry while Pi is attached.

## Validation

`npm test` compiles against the pinned Pi extension types, then runs Node tests over mocked Pi callbacks and a fake HTTP transport. It covers event transitions, parallel tools, manual state persistence, stable IDs, byte limits, and latest-per-session publication under overlapping requests.

## Interface sources

- [Pi extension documentation](https://github.com/earendil-works/pi/blob/main/packages/coding-agent/docs/extensions.md)
- [Pi extension type declarations](https://github.com/earendil-works/pi/blob/main/packages/coding-agent/src/core/extensions/types.ts)
- [npm package and version history for `@earendil-works/pi-coding-agent`](https://www.npmjs.com/package/@earendil-works/pi-coding-agent)

The adapter pins 1.0.0, which was the npm `latest` dist-tag when checked on 2026-10-02. The package requires Node.js 22.19 or newer.
