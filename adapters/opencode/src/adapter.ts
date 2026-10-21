import { createHash } from "node:crypto";
import { hostname } from "node:os";

export const BRIDGE_DEFAULT = "http://127.0.0.1:8000";
export const HEARTBEAT_MS = 30_000;
const REQUEST_TIMEOUT_MS = 1_500;
const RETRY_MS = 1_000;

export type AgentState =
  | "offline"
  | "idle"
  | "thinking"
  | "tool_running"
  | "needs_input"
  | "turn_complete"
  | "error";

export interface AgentStatus {
  id: string;
  name: string;
  host: string;
  detail: string;
  state: AgentState;
  timestamp: number;
}

type OpenCodeEvent = {
  type?: unknown;
  properties?: unknown;
};

type SessionRecord = {
  id: string;
  status: AgentStatus;
  busy: boolean;
  errored: boolean;
  activeTools: Set<string>;
  pendingInputs: Set<string>;
  offlineSince?: number;
};

export function truncateUtf8(value: string, maxBytes: number): string {
  const normalized = value.replace(/[\u0000-\u001f\u007f]/g, " ");
  const bytes = Buffer.from(normalized, "utf8");
  if (bytes.byteLength <= maxBytes) return normalized;
  let end = maxBytes;
  while (end > 0 && (bytes[end] & 0xc0) === 0x80) end -= 1;
  return bytes.subarray(0, end).toString("utf8");
}

export function stableAgentId(host: string, sessionID: string): string {
  const digest = createHash("sha256")
    .update(`${host}|opencode|${sessionID}`, "utf8")
    .digest("hex")
    .slice(0, 20);
  return `opencode-${digest}`;
}

function object(value: unknown): Record<string, unknown> | undefined {
  return value !== null && typeof value === "object"
    ? (value as Record<string, unknown>)
    : undefined;
}

function nonEmptyString(value: unknown): string | undefined {
  return typeof value === "string" && value.length > 0 ? value : undefined;
}

export class OpenCodeStateTracker {
  readonly host: string;
  private readonly sessions = new Map<string, SessionRecord>();
  private readonly name: string;

  constructor(hostName = hostname(), displayName = "OpenCode") {
    this.host = truncateUtf8(hostName || "unknown", 96);
    this.name = truncateUtf8(displayName, 96);
  }

  getAttachedStatuses(): AgentStatus[] {
    this.collectExpired();
    return [...this.sessions.values()]
      .filter((session) => session.status.state !== "offline")
      .map((session) => ({ ...session.status, timestamp: nowSeconds() }));
  }

  collectExpired(now = performance.now()): number {
    let removed = 0;
    for (const [id, session] of this.sessions) {
      if (session.offlineSince !== undefined && now - session.offlineSince >= 300_000) {
        this.sessions.delete(id);
        removed++;
      }
    }
    return removed;
  }

  process(event: OpenCodeEvent): AgentStatus | undefined {
    const type = nonEmptyString(event.type);
    const properties = object(event.properties);
    if (!type || !properties) return undefined;

    const info = object(properties.info);
    const part = object(properties.part);
    const sessionID =
      nonEmptyString(properties.sessionID) ??
      nonEmptyString(part?.sessionID) ??
      nonEmptyString(info?.id);
    if (!sessionID) return undefined;

    if (type === "session.created") {
      return this.ensureSession(sessionID).status;
    }
    if (type === "session.updated") {
      return this.sessions.has(sessionID) ? undefined : this.ensureSession(sessionID).status;
    }

    const knownEvent = new Set([
      "session.status",
      "session.idle",
      "session.error",
      "session.deleted",
      "session.updated",
      "permission.asked",
      "permission.updated",
      "permission.replied",
      "question.asked",
      "question.replied",
      "question.rejected",
      "message.part.updated",
    ]).has(type);
    if (!knownEvent) return undefined;
    const session = this.ensureSession(sessionID);

    switch (type) {
      case "session.deleted":
        session.activeTools.clear();
        session.pendingInputs.clear();
        session.busy = false;
        return this.commit(session, "offline", "Session ended");

      case "session.status": {
        const status = object(properties.status);
        if (status?.type === "busy") {
          session.busy = true;
          session.errored = false;
          return this.commit(session, session.activeTools.size ? "tool_running" : "thinking", session.activeTools.size ? "Running tool" : "Working");
        }
        if (status?.type === "idle") {
          session.busy = false;
          if (session.errored) return this.commit(session, "error", "OpenCode reported an error");
          if (session.pendingInputs.size) return this.commit(session, "needs_input", "Waiting for user input");
          if (session.activeTools.size) return this.commit(session, "tool_running", "Running tool");
          return this.commit(session, "turn_complete", "Turn complete");
        }
        if (status?.type === "retry") {
          session.busy = true;
          session.errored = false;
          return this.commit(session, "thinking", "Retrying");
        }
        return undefined;
      }

      case "session.idle":
        session.busy = false;
        if (session.errored) return this.commit(session, "error", "OpenCode reported an error");
        if (session.pendingInputs.size) return this.commit(session, "needs_input", "Waiting for user input");
        if (session.activeTools.size) return this.commit(session, "tool_running", "Running tool");
        return this.commit(session, "turn_complete", "Turn complete");

      case "session.error":
        session.busy = false;
        session.errored = true;
        return this.commit(session, "error", "OpenCode reported an error");

      case "permission.asked":
      case "permission.updated": {
        const id = nonEmptyString(properties.id) ?? nonEmptyString(properties.requestID);
        if (!id) return undefined;
        session.pendingInputs.add(`permission:${id}`);
        session.errored = false;
        return this.commit(session, "needs_input", "Waiting for permission");
      }

      case "permission.replied": {
        const permissionID = nonEmptyString(properties.permissionID) ?? nonEmptyString(properties.requestID) ?? nonEmptyString(properties.id);
        if (permissionID) session.pendingInputs.delete(`permission:${permissionID}`);
        if (session.errored) return this.commit(session, "error", "OpenCode reported an error");
        if (session.pendingInputs.size) return this.commit(session, "needs_input", "Waiting for user input");
        return this.commit(session, session.activeTools.size ? "tool_running" : session.busy ? "thinking" : "idle", session.activeTools.size ? "Running tool" : session.busy ? "Working" : "Ready");
      }

      case "question.asked": {
        const id = nonEmptyString(properties.requestID) ?? nonEmptyString(properties.id);
        if (!id) return undefined;
        session.pendingInputs.add(`question:${id}`);
        session.errored = false;
        return this.commit(session, "needs_input", "Waiting for user input");
      }

      case "question.replied":
      case "question.rejected": {
        const id = nonEmptyString(properties.requestID) ?? nonEmptyString(properties.id);
        if (id) session.pendingInputs.delete(`question:${id}`);
        if (session.errored) return this.commit(session, "error", "OpenCode reported an error");
        if (session.pendingInputs.size) return this.commit(session, "needs_input", "Waiting for user input");
        return this.commit(session, session.activeTools.size ? "tool_running" : session.busy ? "thinking" : "idle", session.activeTools.size ? "Running tool" : session.busy ? "Working" : "Ready");
      }

      case "message.part.updated": {
        if (part?.type !== "tool" || part.sessionID !== sessionID) return undefined;
        const callID = nonEmptyString(part.callID) ?? nonEmptyString(part.id);
        const toolState = object(part.state);
        if (!callID || !toolState) return undefined;
        if (toolState.status === "running" || toolState.status === "pending") {
          session.activeTools.add(callID);
          session.errored = false;
          if (!session.pendingInputs.size) return this.commit(session, "tool_running", "Running tool");
          return this.commit(session, "needs_input", "Waiting for user input");
        }
        if (toolState.status === "completed" || toolState.status === "error") {
          session.activeTools.delete(callID);
          if (session.pendingInputs.size) return this.commit(session, "needs_input", "Waiting for user input");
          if (session.activeTools.size) return this.commit(session, "tool_running", "Running tool");
          return this.commit(session, session.busy ? "thinking" : "turn_complete", session.busy ? "Working" : "Turn complete");
        }
        return undefined;
      }

      default:
        return undefined;
    }
  }

  private ensureSession(sessionID: string): SessionRecord {
    const existing = this.sessions.get(sessionID);
    if (existing) return existing;
    const status: AgentStatus = {
      id: stableAgentId(this.host, sessionID),
      name: this.name,
      host: this.host,
      detail: "Ready",
      state: "idle",
      timestamp: nowSeconds(),
    };
    const session: SessionRecord = {
      id: sessionID,
      status,
      busy: false,
      errored: false,
      activeTools: new Set(),
      pendingInputs: new Set(),
    };
    this.sessions.set(sessionID, session);
    return session;
  }

  private commit(session: SessionRecord, state: AgentState, detail: string): AgentStatus {
    session.offlineSince = state === "offline" ? session.offlineSince ?? performance.now() : undefined;
    session.status = {
      ...session.status,
      state,
      detail: truncateUtf8(detail, 512),
      timestamp: nowSeconds(),
    };
    return { ...session.status };
  }
}

function nowSeconds(): number {
  return Math.floor(Date.now() / 1000);
}

/** Serializes bridge writes and coalesces any backlog to the newest status. */
export class LatestStatusPublisher {
  private readonly latest = new Map<string, AgentStatus>();
  private readonly offlineSince = new Map<string, number>();
  private running = false;
  private retryTimer: ReturnType<typeof setTimeout> | undefined;

  constructor(
    private readonly baseUrl: string,
    private readonly fetcher: typeof fetch = fetch,
    private readonly timeoutMs = REQUEST_TIMEOUT_MS,
  ) {}

  offer(status: AgentStatus): void {
    if (status.state === "offline") {
      if (!this.offlineSince.has(status.id)) this.offlineSince.set(status.id, performance.now());
    } else {
      this.offlineSince.delete(status.id);
    }
    this.latest.set(status.id, { ...status, timestamp: nowSeconds() });
    this.pump();
  }

  close(): void {
    if (this.retryTimer) clearTimeout(this.retryTimer);
    this.retryTimer = undefined;
  }

  private pump(): void {
    if (this.running || this.retryTimer) return;
    for (const [id, since] of this.offlineSince) {
      if (performance.now() - since >= 300_000) {
        this.latest.delete(id);
        this.offlineSince.delete(id);
      }
    }
    const next = this.latest.entries().next();
    if (next.done) return;
    const [id, status] = next.value;
    this.latest.delete(id);
    this.running = true;
    void this.send(status)
      .then((ok) => {
        if (!ok) this.latest.set(id, this.latest.get(id) ?? status);
      })
      .catch(() => {
        this.latest.set(id, this.latest.get(id) ?? status);
      })
      .finally(() => {
        this.running = false;
        if (!this.latest.has(id)) this.offlineSince.delete(id);
        if (this.latest.size) {
          this.retryTimer = setTimeout(() => {
            this.retryTimer = undefined;
            this.pump();
          }, RETRY_MS);
          this.retryTimer.unref?.();
        }
      });
  }

  private async send(status: AgentStatus): Promise<boolean> {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), this.timeoutMs);
    timeout.unref?.();
    try {
      const response = await this.fetcher(`${this.baseUrl.replace(/\/$/, "")}/v1/agents/state`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: serializeStatus(status),
        signal: controller.signal,
      });
      return response.ok;
    } finally {
      clearTimeout(timeout);
    }
  }
}

export function serializeStatus(status: AgentStatus): string {
  const bounded: AgentStatus = {
    ...status,
    id: truncateUtf8(status.id, 96),
    name: truncateUtf8(status.name, 96),
    host: truncateUtf8(status.host, 96),
    detail: truncateUtf8(status.detail, 512),
  };
  let body = JSON.stringify(bounded);
  while (Buffer.byteLength(body, "utf8") > 1024 && bounded.detail.length > 0) {
    bounded.detail = truncateUtf8(bounded.detail, Math.max(0, Buffer.byteLength(bounded.detail, "utf8") - 32));
    body = JSON.stringify(bounded);
  }
  while (Buffer.byteLength(body, "utf8") > 1024 && bounded.name.length > 0) {
    bounded.name = truncateUtf8(bounded.name, Math.max(0, Buffer.byteLength(bounded.name, "utf8") - 16));
    body = JSON.stringify(bounded);
  }
  while (Buffer.byteLength(body, "utf8") > 1024 && bounded.host.length > 0) {
    bounded.host = truncateUtf8(bounded.host, Math.max(0, Buffer.byteLength(bounded.host, "utf8") - 16));
    body = JSON.stringify(bounded);
  }
  if (Buffer.byteLength(body, "utf8") > 1024) throw new Error("Agent status exceeds the bridge payload limit");
  return body;
}
