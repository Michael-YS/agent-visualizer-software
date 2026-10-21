import test from "node:test";
import assert from "node:assert/strict";
import { LatestPublisher, makeStatus, postStatus, utf8Limit } from "../dist/adapter.js";

test("status identity is stable and string caps count complete UTF-8 bytes", () => {
  const first = makeStatus("native-session-12345678", "C:/work/repo", "host", "idle", "🧪".repeat(200));
  const second = makeStatus("native-session-12345678", "C:/other", "host", "thinking");
  assert.equal(first.id, second.id);
  assert.match(first.id, /^pi-[0-9a-f]{20}$/);
  assert.ok(Buffer.byteLength(first.name) <= 96);
  assert.ok(Buffer.byteLength(first.host) <= 96);
  assert.ok(Buffer.byteLength(first.detail) <= 512);
  assert.equal(utf8Limit("🙂x", 3), "");
  assert.equal(utf8Limit("🙂x", 4), "🙂");
});

test("publisher serializes same-session updates without acknowledging over newer state", async () => {
  let release;
  const sent = [];
  const publisher = new LatestPublisher(async (payload) => {
    sent.push(payload.detail);
    if (sent.length === 1) await new Promise((resolve) => { release = resolve; });
  });
  const one = makeStatus("s1", "repo", "host", "thinking", "one");
  publisher.publish(one);
  await new Promise((resolve) => setImmediate(resolve));
  publisher.publish({ ...one, detail: "two" });
  publisher.publish({ ...one, detail: "three" });
  release();
  await new Promise((resolve) => setTimeout(resolve, 10));
  assert.deepEqual(sent, ["one", "three"]);
});

test("different sessions keep separate pending offline state", async () => {
  let release;
  const sent = [];
  const publisher = new LatestPublisher(async (payload) => {
    sent.push(`${payload.id}:${payload.state}`);
    if (sent.length === 1) await new Promise((resolve) => { release = resolve; });
  });
  const old = makeStatus("old", "repo", "host", "idle");
  publisher.publish(old);
  await new Promise((resolve) => setImmediate(resolve));
  publisher.publish({ ...old, state: "offline" });
  publisher.publish(makeStatus("new", "repo", "host", "idle"));
  release();
  await new Promise((resolve) => setTimeout(resolve, 10));
  assert.ok(sent.includes(`${old.id}:offline`));
  assert.ok(sent.some((item) => item.endsWith(":idle")));
});

test("HTTP transport enforces total JSON payload limit and exact endpoint", async (t) => {
  const originalFetch = globalThis.fetch;
  let captured;
  globalThis.fetch = async (url, options) => {
    captured = { url, options };
    return { ok: true, status: 200 };
  };
  t.after(() => { globalThis.fetch = originalFetch; });
  const oversizedText = "\\\n\t".repeat(1000);
  const status = makeStatus("session", "repo", "host", "error", oversizedText);
  await postStatus(status, "http://127.0.0.1:8000/");
  assert.equal(captured.url, "http://127.0.0.1:8000/v1/agents/state");
  assert.ok(Buffer.byteLength(captured.options.body, "utf8") <= 1024);
  assert.equal(captured.options.method, "POST");
});
