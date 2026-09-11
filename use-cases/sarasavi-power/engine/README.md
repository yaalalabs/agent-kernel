# Sarasavi Power — Domain Engine

The **deterministic, framework-agnostic core** of Sarasavi Power. Every rupee and
kWh the product shows a user is computed here — never by an LLM. It has **zero
`agentkernel` imports**, so it runs and validates standalone; the Agent Kernel
tool wrappers in `tool.py` call into this and never re-implement it.

## Modules

| File | Purpose |
|------|---------|
| `tariff.py` | CEB/LECO domestic **retroactive-slab** bill engine: `compute_bill`, `boundary_opportunities`, `simulate_reduction`. |
| `consumption.py` | The single canonical **duty-cycle + standby** consumption model: `appliance_kwh`, `estimate_total`. |
| `data/tariff_ceb_domestic.json` | Dated PUCSL domestic tariff table (values only). |
| `data/appliances.json` | Appliance wattage / duty-cycle reference. |
| `golden_vectors.py` | Correctness validation against official calculator anchors. |

## The core idea (validated)

The tariff is **retroactive**: total period units pick one slab, and that slab's
fixed charge + rate ladder price the *whole* period. Crossing a boundary re-prices
every unit. The biggest cliff is at **60 units** on a 30-day bill:

```
60 units -> LKR 630     (slab B)
61 units -> LKR 1260    (slab C)   # +630 for ONE unit — the bill doubles
```

`boundary_opportunities(61)` returns *"cut 1 unit → save LKR 630"*. That lever is
the product's whole reason to exist.

Billing periods other than 30 days floor-prorate the official block ceilings
(`floor(base × days / 30)`). Fixed charges are applied once and are not doubled
for 60-day rural cycles.

## Run the validation

```bash
cd use-cases/sarasavi-power
uv run python -m engine.golden_vectors     # exit 0 = all invariants hold
uv run pytest -q
```

## Data status

Tariff numbers are **verified against the official PUCSL domestic calculator**
effective **11 May 2026** (checked 2026-07-16). Sources:

- https://www.pucsl.gov.lk/calculator/
- https://www.pucsl.gov.lk/electricity-tariff-revision-2026-may/

## Standards

Python 3.12+, `black` + `isort` formatting (per the Agent Kernel `DEVELOPER_GUIDE`).
This directory drops into a fork at `agent-kernel/use-cases/sarasavi-power/`.
