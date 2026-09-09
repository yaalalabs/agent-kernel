# Smart Cooling Agent

A multi-agent AI system built on [Agent Kernel](https://github.com/yaalalabs/agent-kernel) that monitors industrial cooling tower telemetry, flags energy waste, and recommends corrective action — built for the IDEALIZE hackathon (SDG hardware track).

## Problem Statement

Industrial cooling systems (cooling towers, HVAC plant, data center chillers) are a major source of avoidable energy waste. Fans and pumps are frequently left running at high speed even when temperatures are within safe operating range, and threshold breaches often go unnoticed until they cause hardware stress or a spike in the energy bill. Facilities teams need a fast, conversational way to check live sensor status and get an immediate, actionable read on whether energy is being wasted — without digging through a dashboard or waiting on a scheduled report.

This ties into SDG 7 (Affordable and Clean Energy) and SDG 12 (Responsible Consumption and Production) by helping facilities catch and correct energy waste in near real time.

## Solution Overview

Smart Cooling Agent is a three-agent pipeline orchestrated with Agent Kernel's Google ADK integration:

| Agent | Role |
|---|---|
| **Triage Agent** | Entry point. Reads the user's question and routes it to the right specialist agent. |
| **Intake Agent** | Fetches live sensor telemetry (temperature, fan speed, threshold status) via a `get_system_status` tool, simulating a LoRa telemetry bridge to the cooling tower hardware. |
| **Analysis Agent** | Evaluates the returned data. If temperature exceeds the safe threshold (35°C), it warns the user of energy waste and hardware risk, and recommends lowering the threshold. |

The agents run on Google's Gemini models via LiteLLM, wired together and served through Agent Kernel's `GoogleADKModule`, and are currently exposed through an interactive CLI.

**Example interaction:**
```
(triage) >> Check the status of CoolingTower1
→ Triage routes to Intake Agent
→ Intake Agent reports: 38°C, fan at 100%, threshold breached
→ Triage routes to Analysis Agent
→ Analysis Agent warns of energy waste and recommends lowering the threshold
```

## Setup Instructions

### Prerequisites
- Python 3.11+
- [uv](https://docs.astral.sh/uv/) package manager
- A Gemini API key ([Google AI Studio](https://aistudio.google.com/app/apikey))

### Installation

1. Clone your fork of the Agent Kernel repo and navigate to this project:
   ```bash
   cd use-cases/use_cases/smart_cooling_agent
   ```

2. Install dependencies:
   ```bash
   uv sync
   ```

3. Set your Gemini API key as an environment variable (do **not** hardcode it in the script):
   ```bash
   export GEMINI_API_KEY="your_gemini_api_key_here"
   ```

## How to Run

Make sure `GEMINI_API_KEY` is exported in your **current terminal session** (env vars don't persist across new terminal windows — re-export if you switch shells):

```bash
export GEMINI_API_KEY="your_gemini_api_key_here"
uv run python cooling_agent.py
```

This starts the Agent Kernel CLI. Once you see the prompt, try:

```
(triage) >> Check the status of CoolingTower1
```

Type `!help` to see available CLI commands, or `!quit` to exit.

> **Security note:** `cooling_agent.py` does not set `GEMINI_API_KEY` internally — it's read from your environment only. Never hardcode API keys directly in the script; GitHub's push protection will (correctly) block a commit containing a live key. If a key is ever accidentally committed, treat it as compromised and regenerate it in [Google AI Studio](https://aistudio.google.com/app/apikey), even if the push itself was rejected.

## Known Limitations / Next Steps

- **User-facing interface**: Currently CLI-only. A Slack integration (via Agent Kernel's built-in `AgentSlackRequestHandler`) was implemented and reached a working `/slack/events` endpoint returning `200 OK`, but local webhook verification was blocked by tunneling constraints in the dev environment (free-tier tunnel latency exceeding Slack's challenge-response timeout). This is the next planned integration.
- **Telemetry source**: `get_system_status` currently returns simulated data for a single sensor (`CoolingTower1`). A production version would connect to a real LoRa gateway or MQTT broker.
- **Session persistence**: Uses Agent Kernel's default in-memory session store; no persistence across restarts.


