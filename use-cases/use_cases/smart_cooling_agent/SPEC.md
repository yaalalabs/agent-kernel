# SPEC — Smart Cooling Agent

## 1. Purpose

Automate first-line monitoring and triage of industrial cooling tower telemetry, so facilities staff can query system status conversationally and get an immediate, actionable energy-waste assessment instead of manually checking dashboards or logs.

## 2. Scope

**In scope:**
- Conversational query of a single simulated cooling tower sensor (`CoolingTower1`)
- Automated routing between a data-fetch agent and an analysis agent
- Threshold-based energy waste / hardware risk warnings

**Out of scope (for this hackathon build):**
- Real hardware/LoRa gateway integration (currently mocked)
- Multi-sensor / multi-site support
- Persistent history or alerting outside of a live chat session
- Automated remediation (e.g. actually adjusting fan speed or threshold values)

## 3. Architecture

```
User
  │
  ▼
Triage Agent  ──(status/check request)──▶  Intake Agent ──▶ get_system_status() tool
  │                                              │
  │                                              ▼
  └──(analysis request)──▶  Analysis Agent ◀── sensor reading
                                  │
                                  ▼
                         Energy waste / risk verdict
```

- **Framework**: [Agent Kernel](https://github.com/yaalalabs/agent-kernel) (`GoogleADKModule`), wrapping Google ADK's `Agent` / `LlmAgent` classes
- **Model routing**: `LiteLlm` targeting Gemini (`gemini/gemini-3.6-flash`)
- **Interface**: Agent Kernel CLI (`agentkernel.cli.CLI`)
- **Runtime**: Local, via `uv run python cooling_agent.py`

## 4. Agents

### Triage Agent
- **Type**: `LlmAgent`
- **Responsibility**: Classify the incoming user question and hand off to the correct specialist agent.
- **Routing rules**:
  - "get/check status" → `intake`
  - "analyze" → `analysis`

### Intake Agent
- **Type**: `Agent`
- **Tool**: `get_system_status(sensor_id: str) -> str`
- **Responsibility**: Return current telemetry for a named sensor. Currently hardcoded to simulate `CoolingTower1`; returns a "not found" message for any other sensor ID.
- **Simulated data**: 38°C, fan speed 100%, threshold breach flag (>35°C)

### Analysis Agent
- **Type**: `Agent`
- **Responsibility**: Evaluate temperature readings against the 35°C safety/efficiency threshold. If breached, warn of energy waste and hardware risk, and recommend lowering the threshold.

## 5. Data Flow

1. User sends a natural-language message to the Triage Agent.
2. Triage Agent determines intent and transfers control to Intake or Analysis.
3. Intake Agent calls `get_system_status`, returns structured telemetry as text.
4. If the user's original ask requires analysis, Triage routes the intake result onward to the Analysis Agent.
5. Analysis Agent returns a verdict and recommendation to the user.

## 6. Environment & Configuration

| Variable | Purpose |
|---|---|
| `GEMINI_API_KEY` | Auth for Gemini model calls via LiteLLM |
| `ADK_SUPPRESS_GEMINI_LITELLM_WARNINGS` | Suppresses ADK's native-Gemini-integration nudge warning |

No `config.yaml` is currently required; Agent Kernel falls back to defaults when absent.

`GEMINI_API_KEY` must be supplied externally (shell export or CI/CD secret store) and is never hardcoded in `cooling_agent.py` or committed to source control — GitHub's secret-scanning push protection enforces this on push.

## 7. Testing Notes

- Manual verification via CLI: `Check the status of CoolingTower1` → confirms triage → intake → analysis handoff completes end-to-end.
- No automated test suite yet — a natural next step given `use-cases`/`examples` in the Agent Kernel repo include test scaffolding.

## 8. Roadmap

1. Replace mocked telemetry with a real MQTT/LoRa gateway integration.
2. Complete the Slack front-end (`AgentSlackRequestHandler`) as the primary user-facing interface, satisfying the "Agent Kernel supported integration" judging criterion.
3. Support multiple sensors/towers with per-sensor threshold configuration.
4. Add persistent session storage (Redis/DynamoDB) for history across restarts.
