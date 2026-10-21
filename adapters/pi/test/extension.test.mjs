import test from "node:test";
import assert from "node:assert/strict";
import extension from "../dist/extension.js";

const tick = () => new Promise((resolve) => setTimeout(resolve, 5));

test("mock Pi callbacks publish lifecycle and parallel tool state without command errors", async (t) => {
  const originalFetch = globalThis.fetch;
  const sent = [];
  globalThis.fetch = async (_url, options) => {
    sent.push(JSON.parse(options.body));
    return { ok: true, status: 200 };
  };
  t.after(() => { globalThis.fetch = originalFetch; });

  const callbacks = new Map();
  let reportTool;
  const api = {
    on(name, callback) { callbacks.set(name, callback); },
    registerTool(definition) { reportTool = definition; },
  };
  extension(api);
  assert.ok(reportTool);
  const context = (id) => ({ cwd: "C:/workspace/sample", sessionManager: { getSessionId: () => id } });
  const emit = async (name, event = {}, ctx = context("session-a")) => callbacks.get(name)(event, ctx);

  await emit("session_start", { reason: "startup" });
  await emit("agent_start");
  await emit("tool_execution_start", { toolCallId: "a", toolName: "bash" });
  await emit("tool_execution_start", { toolCallId: "b", toolName: "read" });
  await emit("tool_execution_end", { toolCallId: "a", toolName: "bash", isError: true });
  await tick();
  assert.equal(sent.at(-1).state, "tool_running", "one sibling tool is still active");
  await emit("tool_execution_end", { toolCallId: "b", toolName: "read", isError: false });
  await tick();
  assert.equal(sent.at(-1).state, "thinking", "tool failure does not prove task failure");

  await emit("tool_execution_start", { toolCallId: "report", toolName: "report_status" });
  assert.equal(sent.at(-1).state, "thinking", "manual reporting tool does not flash tool_running");
  await reportTool.execute("call", { state: "needs_input", detail: "Need a choice" }, undefined, undefined, context("session-a"));
  await emit("tool_execution_end", { toolCallId: "report", toolName: "report_status", isError: false });
  await emit("agent_end", { messages: [] });
  await tick();
  assert.equal(sent.at(-1).state, "needs_input", "manual needs_input remains sticky after agent_end");
  assert.equal(sent.at(-1).detail, "Need a choice");

  await emit("session_shutdown", { reason: "new" });
  await tick();
  assert.equal(sent.at(-1).state, "offline");
  assert.equal(sent.at(-1).id, sent[0].id);

  await emit("session_start", { reason: "new" }, context("session-b"));
  await emit("agent_end", { messages: [{ role: "assistant", stopReason: "error", errorMessage: "private provider details" }] }, context("session-b"));
  await tick();
  assert.equal(sent.at(-1).state, "error");
  assert.equal(sent.at(-1).detail, "Pi reported an agent error", "provider error text is never forwarded");
  await emit("agent_start", {}, context("session-b"));
  await emit("agent_end", { messages: [{ role: "assistant", stopReason: "aborted" }] }, context("session-b"));
  await tick();
  assert.equal(sent.at(-1).state, "idle", "an aborted run is not reported as success or task error");
  await emit("session_shutdown", { reason: "quit" }, context("session-b"));
});

test("session_start after a replacement keeps stable per-session IDs and reports old session offline", async (t) => {
  const originalFetch = globalThis.fetch;
  const sent = [];
  globalThis.fetch = async (_url, options) => { sent.push(JSON.parse(options.body)); return { ok: true, status: 200 }; };
  t.after(() => { globalThis.fetch = originalFetch; });
  const callbacks = new Map();
  const api = { on(name, callback) { callbacks.set(name, callback); }, registerTool() {} };
  extension(api);
  const ctx = (id) => ({ cwd: "C:/repo", sessionManager: { getSessionId: () => id } });
  await callbacks.get("session_start")({ reason: "startup" }, ctx("one"));
  await callbacks.get("session_shutdown")({ reason: "new" }, ctx("one"));
  await callbacks.get("session_start")({ reason: "new" }, ctx("two"));
  await tick();
  assert.ok(sent.some((item) => item.id === sent[0].id && item.state === "offline"));
  assert.notEqual(sent.at(-1).id, sent[0].id);
  await callbacks.get("session_shutdown")({ reason: "quit" }, ctx("two"));
});
