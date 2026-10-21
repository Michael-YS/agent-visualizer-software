import type { Plugin } from "@opencode-ai/plugin";
import { BRIDGE_DEFAULT, HEARTBEAT_MS, LatestStatusPublisher, OpenCodeStateTracker } from "./adapter.js";

const AgentMonitorOpenCodePlugin: Plugin = async () => {
  const tracker = new OpenCodeStateTracker();
  const bridgeUrl = process.env.AGENT_MONITOR_BRIDGE_URL || BRIDGE_DEFAULT;
  const publisher = new LatestStatusPublisher(bridgeUrl);
  let closed = false;

  const heartbeat = setInterval(() => {
    if (closed) return;
    for (const status of tracker.getAttachedStatuses()) publisher.offer(status);
  }, HEARTBEAT_MS);
  heartbeat.unref?.();
  process.once("exit", () => {
    closed = true;
    clearInterval(heartbeat);
    publisher.close();
  });

  return {
    async event({ event }) {
      if (closed) return;
      try {
        const status = tracker.process(event);
        if (status) publisher.offer(status);
      } catch {
        // Monitoring must not interfere with OpenCode event delivery.
      }
    },
  };
};

export default AgentMonitorOpenCodePlugin;
