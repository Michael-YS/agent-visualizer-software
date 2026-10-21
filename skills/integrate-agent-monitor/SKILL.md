---
name: integrate-agent-monitor
description: Connect an installed agent harness to Agent Monitor by generating native hooks, a plugin or an extension from the software repository's status contract. Use when setting up status reporting for a harness.
---

Read [INTEGRATION.md](../../INTEGRATION.md) and
[status.schema.json](../../status.schema.json) in this software checkout. Keep
this skill with the checkout so those references remain available; when
installing a copy elsewhere, retain a reference to the original checkout.

Follow [AGENT_SETUP.md](../../AGENT_SETUP.md): first ask the user what to call
this harness, wait for their answer, and use that exact value as `name` in every
report. Ask for a shorter name if it exceeds 96 UTF-8 bytes; do not silently
truncate or append a project/session suffix. Prefer native hooks/events when
available; consider MCP/skill only without hooks or to fill uncovered states.

Require `detail` to contain an agent-written task summary plus current progress
while a task exists. Cache it per session so tool callbacks and heartbeats keep
the summary; retain it with the outcome on completion and replace it for a new
task. If hooks lack this context, have the agent supply a safe summary at task
start or objective changes through a local interface or MCP/skill, without
replacing hook-driven lifecycle updates. Do not copy raw prompts, change `name`,
add protocol fields, or report only generic labels such as "Working".

Identify the installed harness, version, native session identifier and supported
lifecycle events from local declarations/help or official documentation. Do not
invent event names or borrow another harness's payload shapes. Inspect existing
configuration and reporting integrations before editing. Reuse a compatible
[reference adapter](../../adapters/README.md) if that is simpler.

Generate the smallest native integration that covers the available events and
the user's requested install scope. Merge existing hooks without removing them.
Preserve native permission/response semantics and bound monitoring latency.
Keep one stable monitor ID per host/harness/session, track parallel tools, and
distinguish turn completion, interruption, task error and session termination.
Document gaps when the harness lacks a lifecycle signal; do not fabricate one.

If explicit reports are needed, expose a skill or native tool that uses the
same session identity as hooks. Prefer reporting human waits and task failures
that hooks cannot observe. Prevent its own tool callbacks from undoing its report.
Do not introduce a background service merely to send unverified heartbeats.

Validate generated sample messages with `python -m app.protocol validate` from
the software checkout. Exercise normal work, parallel tools, input waits,
failure, shutdown and receiver unavailability. Use a separate disposable session
ID for live smoke tests and finish it with `offline`. Summarize installation,
removal and the exact checks completed; distinguish simulated callbacks from
real harness execution and MQTT/hardware verification.
