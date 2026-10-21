import { createHash } from "node:crypto";

export const STATES = ["offline", "idle", "thinking", "tool_running", "needs_input", "turn_complete", "error"] as const;
export type State = (typeof STATES)[number];
export interface AgentStatus {
  id: string;
  name: string;
  host: string;
  state: State;
  detail: string;
  timestamp: number;
}

export const utf8Limit = (value: unknown, maxBytes: number): string => {
  const text = String(value ?? "");
  const bytes = Buffer.from(text, "utf8");
  if (bytes.length <= maxBytes) return text;
  const decoder = new TextDecoder("utf-8", { fatal: true });
  for (let end = maxBytes; end > 0; end--) {
    try {
      return decoder.decode(bytes.subarray(0, end));
    } catch {
      // Move back to the previous complete UTF-8 code point.
    }
  }
  return "";
};

const safeText = (value: unknown, maxBytes: number): string =>
  utf8Limit(String(value ?? "").replace(/[\u0000-\u001f\u007f]/g, " "), maxBytes);

export function makeStatus(sessionId: string, cwd: string, hostName: string, state: State, detail = ""): AgentStatus {
  const host = safeText(hostName.trim() || "localhost", 96);
  const shortSession = sessionId.slice(-8) || "session";
  const project = cwd.replace(/[\\/]+$/, "").split(/[\\/]/).filter(Boolean).at(-1) || "session";
  const digest = createHash("sha256").update(`${host}|pi|${sessionId}`, "utf8").digest("hex").slice(0, 20);
  return {
    id: `pi-${digest}`,
    name: safeText(`Pi / ${project} / ${shortSession}`, 96),
    host,
    state,
    detail: safeText(detail, 512),
    timestamp: Math.floor(Date.now() / 1000),
  };
}

export type Transport = (payload: AgentStatus) => Promise<void>;

interface PublishQueue {
  current?: AgentStatus;
  revision: number;
  sending: boolean;
  offlineSince?: number;
  retryTimer?: ReturnType<typeof setTimeout>;
}

/** Last-write-wins serialized publisher per Pi session. */
export class LatestPublisher {
  private readonly queues = new Map<string, PublishQueue>();
  constructor(private readonly send: Transport) {}

  publish(payload: AgentStatus): void {
    let queue = this.queues.get(payload.id);
    if (!queue) {
      queue = { revision: 0, sending: false };
      this.queues.set(payload.id, queue);
    }
    queue.current = payload;
    queue.offlineSince = payload.state === "offline" ? queue.offlineSince ?? performance.now() : undefined;
    queue.revision++;
    if (queue.retryTimer) clearTimeout(queue.retryTimer);
    queue.retryTimer = undefined;
    void this.drain(payload.id, queue);
  }

  private async drain(id: string, queue: PublishQueue): Promise<void> {
    if (queue.sending) return;
    queue.sending = true;
    try {
      while (queue.current) {
        if (queue.offlineSince !== undefined && performance.now() - queue.offlineSince >= 300_000) {
          queue.current = undefined;
          break;
        }
        const revision = queue.revision;
        const snapshot = queue.current;
        try {
          await this.send(snapshot);
        } catch {
          // Keep latest state and retry later without a tight failure loop.
          if (revision === queue.revision) {
            queue.retryTimer = setTimeout(() => {
              queue.retryTimer = undefined;
              void this.drain(id, queue);
            }, 5000);
            queue.retryTimer.unref?.();
            break;
          }
          continue;
        }
        if (revision === queue.revision) queue.current = undefined;
      }
    } finally {
      queue.sending = false;
      if (!queue.current && !queue.retryTimer) this.queues.delete(id);
    }
  }
}

export async function postStatus(payload: AgentStatus, baseUrl: string): Promise<void> {
  // The field caps leave room for protocol keys. Still enforce the wire limit in case
  // future metadata changes or JSON escaping increase the serialized size.
  let body = JSON.stringify(payload);
  if (Buffer.byteLength(body, "utf8") > 1024) {
    let low = 0;
    let high = Buffer.byteLength(payload.detail, "utf8");
    while (low < high) {
      const mid = Math.ceil((low + high) / 2);
      const candidate = { ...payload, detail: utf8Limit(payload.detail, mid) };
      if (Buffer.byteLength(JSON.stringify(candidate), "utf8") <= 1024) low = mid;
      else high = mid - 1;
    }
    body = JSON.stringify({ ...payload, detail: utf8Limit(payload.detail, low) });
    if (Buffer.byteLength(body, "utf8") > 1024) throw new Error("Agent Monitor payload exceeds 1024 bytes");
  }
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 1000);
  try {
    const response = await fetch(`${baseUrl.replace(/\/$/, "")}/v1/agents/state`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body,
      signal: controller.signal,
    });
    if (!response.ok) throw new Error(`Bridge returned HTTP ${response.status}`);
  } finally {
    clearTimeout(timeout);
  }
}
