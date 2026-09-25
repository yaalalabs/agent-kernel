# Coding Guide for Sarasavi Power

## Scope

Keep all solution changes inside `use-cases/sarasavi-power/`. Do not modify Agent Kernel core to make this use case work.

## Architecture invariants

- Put all numeric electricity logic in `engine/`; tools remain thin state/validation adapters.
- Keep `engine/` framework-independent: no Agent Kernel, LLM SDK, network, or environment dependencies.
- Access household state only through `state.py` and keep the canonical key `household_profile`.
- Require storage consent for profile writes and preserve immediate erase-on-revocation behavior.
- Keep specialist transfers one-way from `orchestrator`; specialists answer directly and keep `disallow_transfer_to_parent` / `disallow_transfer_to_peers` set.
- Attach safety and disclaimer hooks to every registered agent in every conversational entrypoint.
- Keep user-facing English, Sinhala, and Tamil vocabulary in `localization.py`; do not put translated strings in the numeric engine.
- Never commit `.env`, access tokens, app secrets, phone IDs, session data, or personal bill data.

## Tariff updates

When PUCSL changes the tariff:

1. Add the effective date and official URLs to `engine/data/tariff_ceb_domestic.json`.
2. Update only the dated values, not calculation logic, unless the official methodology changed.
3. Recalculate official anchors from the PUCSL calculator.
4. Update `tests/test_tariff.py` and `engine/golden_vectors.py` together.
5. Run the complete acceptance checks in `SPEC.md`.

## Required validation

Run from this directory:

```bash
uv run pytest -q
uv run python -m engine.golden_vectors
uv run black --check .
```

Tests must stay keyless and must not call Meta, Google, PUCSL, or any other network service.
