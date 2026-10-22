# Agent Monitor Software

FastAPI service accepts six-field agent status messages and publishes MQTT
snapshots for an ESP32. The same registry powers the Web UI and read API.

## Entry points and commands

- `README.md`: installation, configuration, run and test commands.
- Run bridge: `python -m uvicorn app.main:app --host 0.0.0.0 --port 8000`.
- Test bridge: `python -m pytest` from this directory.
- Test adapters from their own directories; they are independent packages.
- `app/`: Python, FastAPI, Pydantic, paho-mqtt; `app/web/`: plain HTML/CSS/JS.
- `status.schema.json` is generated from `app.models.AgentStatus`.

## Integration and documentation

- `AGENT_SETUP.md` must work when forwarded alone to another agent.
- Keep it, `INTEGRATION.md`, and `skills/integrate-agent-monitor/SKILL.md`
  aligned when integration behavior or verification endpoints change.
- Generated onboarding integrations preserve the user-confirmed `name` and
  put task summaries, progress and safe titles in `detail`.
- Reference adapters may use automatic names; document the difference rather
  than claiming their defaults meet the fixed-name onboarding contract.
- Preserve the six-field wire protocol and its UTF-8 and total payload limits.
- Use one bridge worker; the status registry is in memory.
- Distinguish local tests from installed hooks, live services and hardware proof.

## Current scope

The bridge provides a Web UI, list/single-agent read APIs and offline cleanup.
The Codex reference adapter reads local session titles. Deployment status must
be checked independently; inspect the current Git diff before further edits.
