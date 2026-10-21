import { Type } from "typebox";
import { hostname } from "node:os";
import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";
import { LatestPublisher, makeStatus, postStatus, type AgentStatus, type State } from "./adapter.js";

const HEARTBEAT_MS = 30_000;
const bridgeUrl = () => process.env.AGENT_MONITOR_BRIDGE_URL || "http://127.0.0.1:8000";
const hostName = () => process.env.COMPUTERNAME || process.env.HOSTNAME || hostname() || "localhost";
const isReportTool = (name: string) => name.toLowerCase().replaceAll("-", "_") === "report_status";

export default function agentMonitor(pi: ExtensionAPI): void {
  let activeContext: ExtensionContext | undefined;
  let activeSessionId: string | undefined;
  let current: AgentStatus | undefined;
  let state: State = "idle";
  let manualSticky: "needs_input" | "error" | undefined;
  let manualDetail = "";
  const activeTools = new Map<string, string>();
  const publisher = new LatestPublisher((payload) => postStatus(payload, bridgeUrl()));
  let heartbeat: ReturnType<typeof setInterval> | undefined;

  const sessionIdOf = (ctx: ExtensionContext) => ctx.sessionManager.getSessionId();
  const update = (next: State, detail = ""): void => {
    if (!activeContext) return;
    const sid = sessionIdOf(activeContext);
    if (!sid) return;
    activeSessionId = sid;
    state = next;
    current = makeStatus(sid, activeContext.cwd, hostName(), state, detail);
    publisher.publish(current);
  };
  const heartbeatTick = () => {
    if (current && state !== "offline") {
      current = { ...current, timestamp: Math.floor(Date.now() / 1000) };
      publisher.publish(current);
    }
  };
  const startSession = (ctx: ExtensionContext) => {
    const nextId = sessionIdOf(ctx);
    if (current && activeSessionId && nextId && activeSessionId !== nextId) {
      publisher.publish({ ...current, state: "offline", detail: "Session switched", timestamp: Math.floor(Date.now() / 1000) });
    }
    activeContext = ctx;
    activeSessionId = nextId;
    manualSticky = undefined;
    manualDetail = "";
    activeTools.clear();
    update("idle", "Pi session active");
    if (!heartbeat) {
      heartbeat = setInterval(heartbeatTick, HEARTBEAT_MS);
      heartbeat.unref?.();
    }
  };

  // Pi represents new/resume/fork replacements with shutdown followed by start.
  pi.on("session_start", async (_event, ctx) => startSession(ctx));

  pi.on("agent_start", async () => {
    manualSticky = undefined;
    activeTools.clear();
    update("thinking", "Working on request");
  });

  pi.on("tool_execution_start", async (event) => {
    if (isReportTool(event.toolName)) return;
    activeTools.set(event.toolCallId, event.toolName);
    update("tool_running", event.toolName);
  });

  pi.on("tool_execution_end", async (event) => {
    if (isReportTool(event.toolName)) return;
    activeTools.delete(event.toolCallId);
    // Tool errors (including non-zero shell exits) are tool outcomes, not proof the task failed.
    if (manualSticky) update(manualSticky, manualDetail);
    else if (activeTools.size) update("tool_running", [...activeTools.values()].at(-1) || "Running tool");
    else update("thinking", "Working on request");
  });

  pi.on("agent_end", async (event) => {
    if (manualSticky) update(manualSticky, manualDetail);
    else {
      const lastAssistant = [...event.messages].reverse().find((message) => message.role === "assistant");
      if (lastAssistant?.role === "assistant" && lastAssistant.stopReason === "error") {
        manualSticky = "error";
        manualDetail = "Pi reported an agent error";
        update("error", manualDetail);
      } else if (lastAssistant?.role === "assistant" && lastAssistant.stopReason === "aborted") {
        update("idle", "Run aborted");
      } else update("turn_complete", "Turn complete");
    }
    activeTools.clear();
  });

  pi.on("session_shutdown", async () => {
    if (heartbeat) clearInterval(heartbeat);
    heartbeat = undefined;
    if (current) {
      const offline = { ...current, state: "offline" as const, detail: "Pi session ended", timestamp: Math.floor(Date.now() / 1000) };
      current = offline;
      state = "offline";
      publisher.publish(offline);
    }
    activeContext = undefined;
    activeSessionId = undefined;
  });

  pi.registerTool({
    name: "report_status",
    label: "Report agent status",
    description: "Manually report a task status to Agent Monitor when the user asks for input or a task has clearly failed.",
    promptSnippet: "Report a confirmed task status to Agent Monitor",
    parameters: Type.Object({
      state: Type.Union([Type.Literal("needs_input"), Type.Literal("error")]),
      detail: Type.String({ description: "Brief reason, without prompts, command output, or tool results." }),
    }),
    async execute(_id, params, _signal, _onUpdate, ctx: ExtensionContext) {
      if (!activeContext) activeContext = ctx;
      const reportedState = params.state as "needs_input" | "error";
      manualSticky = reportedState;
      manualDetail = params.detail || "";
      update(reportedState, manualDetail);
      return { content: [{ type: "text", text: "Status reported to Agent Monitor." }], details: undefined };
    },
  });
}
