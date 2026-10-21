import test from "node:test";
import assert from "node:assert/strict";
import {
  LatestStatusPublisher,
  OpenCodeStateTracker,
  serializeStatus,
  stableAgentId,
  truncateUtf8,
} from "../dist/test-utils.js";
import * as pluginModule from "../dist/index.js";

const ev = (type, properties) => ({ type, properties });

test("offline sessions expire while attached and revived sessions survive", () => {
  const tracker = new OpenCodeStateTracker("host");
  tracker.process(ev("session.created", { info: { id: "old" } }));
  tracker.process(ev("session.created", { info: { id: "live" } }));
  tracker.process(ev("session.deleted", { info: { id: "old" } }));
  const since = tracker.sessions.get("old").offlineSince;
  assert.equal(tracker.collectExpired(since + 299_999), 0);
  tracker.process(ev("session.deleted", { info: { id: "old" } }));
  assert.equal(tracker.collectExpired(since + 300_000), 1);
  assert.equal(tracker.sessions.size, 1);
  assert.equal(tracker.getAttachedStatuses().length, 1);
  tracker.process(ev("session.created", { info: { id: "old" } }));
  tracker.process(ev("session.deleted", { info: { id: "old" } }));
  tracker.process(ev("session.status", { sessionID: "old", status: { type: "busy" } }));
  assert.equal(tracker.collectExpired(performance.now() + 300_000), 0);
  assert.equal(tracker.sessions.size, 2);
});

test("publisher reclaims expired offline backlog during bridge failure", async () => {
  const publisher = new LatestStatusPublisher("http://bridge", async () => ({ ok: false }));
  publisher.offer({ id: "old", name: "old", host: "host", state: "offline", detail: "", timestamp: 0 });
  await new Promise((resolve) => setImmediate(resolve));
  publisher.close();
  publisher.offlineSince.set("old", performance.now() - 300_000);
  publisher.pump();
  assert.equal(publisher.latest.size, 0);
  assert.equal(publisher.offlineSince.size, 0);
});

test("build emits one OpenCode plugin function export", () => {
  assert.deepEqual(Object.keys(pluginModule), ["default"]);
  assert.equal(typeof pluginModule.default, "function");
});

test("maps documented OpenCode event payload shape into bridge state", () => {
  const tracker = new OpenCodeStateTracker("opencode-host");
  const created = tracker.process(ev("session.created", { info: { id: "ses-a" } }));
  assert.equal(created.state, "idle");
  assert.equal(created.id, stableAgentId("opencode-host", "ses-a"));

  assert.equal(tracker.process(ev("session.status", {
    sessionID: "ses-a", status: { type: "busy" },
  })).state, "thinking");

  assert.equal(tracker.process(ev("message.part.updated", {
    part: {
      id: "prt-1", callID: "call-1", sessionID: "ses-a", type: "tool",
      state: { status: "running", input: { command: "must not be sent" } },
    },
  })).state, "tool_running");

  assert.equal(tracker.process(ev("message.part.updated", {
    part: {
      id: "prt-1", callID: "call-1", sessionID: "ses-a", type: "tool",
      state: { status: "completed", output: "must not be sent" },
    },
  })).state, "thinking");
});

test("tracks permission waits, completion, errors, and deletion", () => {
  const tracker = new OpenCodeStateTracker("h");
  tracker.process(ev("session.created", { info: { id: "s" } }));
  assert.equal(tracker.process(ev("permission.asked", {
    id: "perm-1", sessionID: "s", permission: "bash", patterns: ["secret command"],
  })).state, "needs_input");
  assert.equal(tracker.process(ev("question.asked", {
    id: "question-1", sessionID: "s", questions: [{ question: "private" }],
  })).detail, "Waiting for user input");
  assert.equal(tracker.process(ev("permission.replied", {
    sessionID: "s", permissionID: "perm-1", response: "once",
  })).state, "needs_input");
  assert.equal(tracker.process(ev("question.replied", {
    sessionID: "s", requestID: "question-1", answers: [],
  })).state, "idle");
  assert.equal(tracker.process(ev("session.idle", { sessionID: "s" })).state, "turn_complete");
  assert.equal(tracker.process(ev("session.error", { sessionID: "s", error: { message: "private" } })).detail,
    "OpenCode reported an error");
  const offline = tracker.process(ev("session.deleted", { info: { id: "s" } }));
  assert.equal(offline.state, "offline");
  assert.deepEqual(tracker.getAttachedStatuses(), []);
});

test("ignores unknown events and attaches sessions seen after plugin startup", () => {
  const tracker = new OpenCodeStateTracker("h");
  assert.equal(tracker.process(ev("unlisted.future.event", { sessionID: "s" })), undefined);
  assert.equal(tracker.process(ev("session.status", {
    sessionID: "already-running", status: { type: "busy" },
  })).state, "thinking");
  assert.equal(tracker.process(ev("session.updated", {
    info: { id: "resumed-session", title: "private title" },
  })).state, "idle");
  assert.equal(tracker.process(ev("permission.asked", { sessionID: "unknown", id: "p" })).state,
    "needs_input");
  assert.equal(tracker.process({ type: "session.status", properties: null }), undefined);
});

test("limits status strings in UTF-8 bytes and omits sensitive event content", () => {
  const clipped = truncateUtf8("🙂".repeat(40), 96);
  assert.ok(Buffer.byteLength(clipped, "utf8") <= 96);
  const tracker = new OpenCodeStateTracker("h", "🙂".repeat(40));
  const status = tracker.process(ev("session.created", { info: { id: "s" } }));
  assert.ok(Buffer.byteLength(status.name, "utf8") <= 96);
  const tool = tracker.process(ev("message.part.updated", {
    part: {
      id: "p", sessionID: "s", type: "tool", state: { status: "running" },
      input: { command: "do not disclose" },
    },
  }));
  assert.doesNotMatch(JSON.stringify(tool), /do not disclose/);
});

test("caps serialized bridge payload at 1024 UTF-8 bytes", () => {
  const body = serializeStatus({
    id: "id",
    name: "x".repeat(96),
    host: "h".repeat(96),
    detail: "line\n".repeat(300),
    state: "thinking",
    timestamp: 1,
  });
  assert.ok(Buffer.byteLength(body, "utf8") <= 1024);
  assert.doesNotMatch(body, /\\n/);
});

test("publisher serializes writes and retries only the latest status", async () => {
  const requests = [];
  let release;
  const gate = new Promise((resolve) => { release = resolve; });
  let calls = 0;
  const publisher = new LatestStatusPublisher("http://bridge/", async (_url, init) => {
    calls += 1;
    requests.push(JSON.parse(init.body));
    if (calls === 1) await gate;
    return new Response(null, { status: calls === 2 ? 503 : 200 });
  }, 500);
  const base = { id: "id", name: "OpenCode", host: "h", detail: "Working", timestamp: 0 };
  publisher.offer({ ...base, state: "thinking" });
  publisher.offer({ ...base, state: "tool_running" });
  release();
  await new Promise((resolve) => setTimeout(resolve, 20));
  assert.equal(requests.length, 1);
  await new Promise((resolve) => setTimeout(resolve, 1_050));
  assert.equal(requests.length, 2);
  assert.equal(requests[1].state, "tool_running");
  publisher.close();
});
