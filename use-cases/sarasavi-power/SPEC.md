# Sarasavi Power Specification

## Product objective

Help a Sri Lankan domestic electricity customer understand current consumption and find the smallest practical change that can reduce the next bill. The solution must demonstrate meaningful Agent Kernel usage and remain reviewable without Meta credentials.

## Functional requirements

1. Obtain explicit consent before storing a household profile.
2. Accept a monthly, bimonthly, or exact-day billing period.
3. Add, update, or remove supported appliances with average daily hours and quantity.
4. Optionally record or clear exact typed units from a bill or meter.
5. Estimate period kWh with a deterministic duty-cycle and standby model.
6. Calculate the CEB/LECO domestic block tariff effective 11 May 2026.
7. Explain the highest-contributing appliances.
8. Find lower tariff-boundary opportunities and calculate their savings.
9. Simulate changing one recorded appliance's daily usage.
10. Export or delete the stored household profile and erase it when consent is revoked.
11. Refuse unsafe electrical, meter-tampering, or repair instructions.
12. Mark all bill and saving values as estimates.
13. Support English, Sinhala, and Tamil across conversation output, appliance names, saving tips, safety refusals, and disclaimers.
14. Detect Sinhala/Tamil Unicode script automatically and persist the preference only after consent.

## Agent Kernel requirements

- Register one `GoogleADKModule` containing `orchestrator`, `intake`, `analysis`, and `recommendation` agents.
- Route from the orchestrator to specialists with native Google ADK `sub_agents` transfers, keeping them one-way via `disallow_transfer_to_parent` / `disallow_transfer_to_peers`.
- Bind only the tools needed by each specialist through `GoogleADKToolBuilder`.
- Store one canonical `household_profile` object in Agent Kernel non-volatile session memory.
- Attach deterministic safety and disclaimer hooks to every agent.
- Expose the same agent graph through Agent Kernel CLI, REST, WhatsApp, and Lambda entrypoints.

## Deterministic engine requirements

- `engine/` must not import Agent Kernel or an LLM library.
- All kWh, tariff, and saving calculations must originate in `engine/`.
- Tariff values must live in a dated JSON file with official source URLs.
- Block ceilings must use floor proration by actual billing days.
- Metered units must take priority over an appliance estimate for current-bill and boundary calculations.
- Known official totals and boundary behavior must remain pinned by tests and golden vectors.

## Interfaces

- `offline_demo.py`: keyless deterministic product report.
- `demo.py`: interactive Agent Kernel CLI.
- `rest.py`: default Agent Kernel `POST /api/v1/chat` endpoint.
- `app.py`: Agent Kernel WhatsApp handler at `/whatsapp/webhook`.
- `lambda.py`: standard Agent Kernel AWS Lambda handler.

## Non-functional requirements

- Python 3.12 or later and `uv` dependency management.
- No committed credentials or user profiles.
- Human-readable startup errors for missing Gemini or Meta configuration.
- Concise WhatsApp-friendly responses.
- Regression tests must not make external API calls.

## Acceptance checks

```bash
uv sync
uv run pytest -q
uv run python -m engine.golden_vectors
uv run python offline_demo.py --units 61 --days 30
uv run black --check .
```

The 61-unit demo must select slab C, estimate LKR 1,260.00, and identify a one-unit reduction to 60 units saving LKR 630.00 under the committed tariff.
