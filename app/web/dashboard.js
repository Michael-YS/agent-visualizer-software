"use strict";

const labels = {offline: "离线", idle: "空闲", thinking: "思考中", tool_running: "执行工具", needs_input: "等待输入", turn_complete: "本轮完成", error: "错误"};
const priority = {error: 0, needs_input: 1, tool_running: 2, thinking: 3, idle: 4, turn_complete: 5, offline: 6};
const el = (id) => document.getElementById(id);
let agents = [];
let loaded = false;

function node(tag, className, text) {
  const element = document.createElement(tag);
  element.className = className;
  element.textContent = text;
  return element;
}

function render() {
  const query = el("search").value.trim().toLocaleLowerCase();
  const state = el("state").value;
  const visible = agents.filter((agent) => (!state || agent.state === state) &&
    [agent.name, agent.host, agent.id].some((value) => value.toLocaleLowerCase().includes(query)));
  visible.sort((a, b) => (priority[a.state] - priority[b.state]) || a.name.localeCompare(b.name));
  el("cards").replaceChildren(...visible.map((agent) => {
    const card = node("article", "card", "");
    const heading = node("div", "card-head", "");
    const badge = node("span", "badge", labels[agent.state] || agent.state);
    badge.dataset.state = agent.state;
    heading.append(node("h3", "", agent.name), badge);
    const time = node("div", "time", "更新于 " + new Date(agent.timestamp * 1000).toLocaleString());
    card.append(heading, node("p", "meta", agent.host + " · " + agent.id),
      node("p", "detail", agent.detail || "暂无状态详情"), time);
    return card;
  }));
  el("empty").hidden = visible.length > 0 || !loaded;
  el("empty").textContent = agents.length ? "没有匹配的 agent，请调整搜索或筛选条件。" : "暂无 agent。接收到状态上报后会自动显示在这里。";
}

async function refresh() {
  try {
    const response = await fetch("/v1/agents", {cache: "no-store", signal: AbortSignal.timeout(5000)});
    if (!response.ok) throw new Error("HTTP " + response.status);
    const data = await response.json();
    agents = data.agents;
    loaded = true;
    el("total").textContent = data.total;
    el("active").textContent = agents.filter((a) => ["thinking", "tool_running"].includes(a.state)).length;
    el("attention").textContent = agents.filter((a) => ["needs_input", "error"].includes(a.state)).length;
    el("offline").textContent = agents.filter((a) => a.state === "offline").length;
    el("connection").dataset.ok = String(data.mqtt_connected);
    el("connection").textContent = data.mqtt_connected ? "● MQTT 已连接 · 正在接收状态" : "● MQTT 已断开 · 显示最后已知状态，更新可能延迟";
    el("updated").textContent = "刷新于 " + new Date().toLocaleTimeString() + " · 每 2 秒";
    el("error").hidden = true;
    render();
  } catch (error) {
    el("connection").dataset.ok = "false";
    el("connection").textContent = "● 无法连接状态服务";
    el("error").textContent = "状态读取失败，正在自动重试。" + (loaded ? "下方保留最后一次成功读取的数据。" : "");
    el("error").hidden = false;
    if (!loaded) el("empty").textContent = "等待服务恢复…";
  } finally {
    setTimeout(refresh, 2000);
  }
}

el("search").addEventListener("input", render);
el("state").addEventListener("change", render);
refresh();
