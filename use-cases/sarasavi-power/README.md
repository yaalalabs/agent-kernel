# ⚡ Sarasavi Power

**An AI energy adviser for Sri Lankan households, on WhatsApp. Message it, send it a photo of your bill, or just call it and talk.**

IDEALIZE 2026 mini-competition · **SDG 7 — Affordable and Clean Energy** · built on [Agent Kernel](https://github.com/yaalalabs/agent-kernel)

---

# 💬 Try it now

# [**+94 77 407 5523**](https://wa.me/94774075523)

# 👉 [**wa.me/94774075523**](https://wa.me/94774075523)

**It is live right now.** No signup, no app, no form. Open WhatsApp and:

| Do this | And it will |
| --- | --- |
| 💬 **Send a message** | `27 units කීයද?` answers instantly, in your language |
| 📷 **Photograph your bill** | read the units off it and price it for you |
| 🎤 **Send a voice note** | listen, and reply with a voice note |
| 📞 **Press the call button** | pick up and hold a real conversation in Sinhala |

Speak **English, සිංහල or தமிழ்** — it follows whichever you use, and switches the moment you do.

---

## This is not a chatbot with a price list

Three things make it different, and each one is verifiable.

### 1. The AI is never allowed to do the arithmetic

An LLM that "calculates" a bill is guessing, and it will guess wrong on the number that matters most to a household. Here, **every rupee is computed by a deterministic Python engine** (`engine/`) that has no AI in it at all. The model's job is to understand the person and call a tool. It quotes results; it never produces them.

A hook re-checks the model's own output and **rewrites any bill figure it substituted**, so even a hallucinated number cannot reach the user.

### 2. The numbers are pinned to a real bill, not to a blog post

The tariff comes from the PUCSL decision effective **11 May 2026**, cross-checked against the official PUCSL calculator. Time-of-Use rates came from Annex 2 of that decision.

We then tested them against a **real CEB Time-of-Use bill**:

| | Printed on the bill | Our engine |
| --- | --- | --- |
| Charge | Rs 55,293.00 | **55,293.00** ✅ |
| SSC Levy | Rs 1,417.77 | **1,417.77** ✅ |
| Monthly Bill | Rs 56,710.77 | **56,710.77** ✅ |

Reproducing a printed bill to the cent is the only test that proves the rates, the fixed charge and the levy are all right *together*. That bill also revealed the SSC levy is 2.5% of the **final** bill, not of the energy charge — a detail most calculators get wrong.

### 3. It answers a phone call, in Sinhala

Not a menu tree. A real conversation: WhatsApp's Calling API → WebRTC → the **Gemini Live API** speaking natively, with the same tools the chat uses. Ask it about your bill out loud and it will look up your figures mid-sentence.

The call and the chat **share one memory**. Give consent on a call and the chat already knows. Hang up and you get a written summary of what was discussed and what was recorded.

---

## What it actually helps with

Sri Lanka's domestic tariff is **retroactive**: crossing a block boundary re-prices your *entire* month. Go one unit over 60 and the whole bill jumps. Most people never see this coming.

Sarasavi Power finds those cliffs for you:

- 📊 Estimates your monthly units from the appliances you own
- 🧾 Prices them on the correct tariff — standard blocks **or** Time-of-Use
- 🎯 Shows the nearest boundary and what it is worth to stay under it
- 🔌 Names the appliances actually driving your bill
- 🌙 On Time-of-Use, shows what shifting load to off-peak (22:30–05:30) saves
- 🤔 Answers both directions: *"27 units කීයද?"* and *"a Rs 3,400 bill is how many units?"*

---

## Built on Agent Kernel

```text
     WhatsApp:  text  ·  voice note  ·  bill photo  ·  live call
                              │
                    Agent Kernel runtime
                    (session memory, hooks)
                              │
                        orchestrator
             ┌────────────────┼────────────────┐
          intake           analysis      recommendation
             └────────────────┼────────────────┘
                         typed tools
                              │
              deterministic tariff + consumption engine
                       (no AI, no network)
```

Four Google ADK agents on Gemini, with one-way `sub_agents` routing. Agent Kernel provides the runtime, the consent-controlled session memory, the pre/post hook pipeline, the REST layer and the WhatsApp channel.

**Agent Kernel core is not modified.** Voice calls, voice notes and photo reading are all built on its documented extension points.

### Guarantees enforced in code, not in prompts

Prompts leak. These are hooks, so they hold regardless of what the model does:

- 🛡️ Unsafe wiring, meter or repair requests are refused, with the CEB fault line offered instead
- 🧮 A substituted bill figure is corrected back to the engine's number
- ⚖️ Every money reply carries the "not an official CEB bill" notice, once per conversation
- 📝 WhatsApp markup is normalised (WhatsApp is not Markdown — `**bold**` shows literal asterisks)

### Privacy

Nothing is stored until you say yes. Ask it to show or delete your data at any time, in plain language, and it does so immediately. Revoking consent erases the profile. Call audio is never recorded.

---

## Running it yourself

Prerequisites: Python 3.12+, [`uv`](https://docs.astral.sh/uv/), and a [Gemini API key](https://aistudio.google.com/apikey).

```bash
cd use-cases/sarasavi-power
uv sync
cp .env.example .env        # then set GOOGLE_API_KEY
```

**No API key at all?** This runs the whole engine offline and prints a full worked example:

```bash
uv run python offline_demo.py --units 61 --days 30
uv run python offline_demo.py --language si
```

**Talk to it in a terminal** (needs only `GOOGLE_API_KEY`):

```bash
uv run python demo.py
```

**Run the WhatsApp channel** (needs Meta credentials in `.env`):

```bash
uv run python app.py
```

Deploying: `deploy/ec2/` holds Terraform for a single EC2 host with automatic HTTPS and DynamoDB-backed sessions. See [SPEC.md](SPEC.md) for requirements and [AGENTS.md](AGENTS.md) for the architecture invariants.

## Verification

```bash
uv run pytest -q                       # 329 tests, no keys, no network
uv run python -m engine.golden_vectors # official tariff anchors
uv run black --check .
```

The suite covers the tariff anchors, billing-day proration, the 60-to-61-unit cliff, Time-of-Use against the real bill above, consent and deletion, the hooks, the WhatsApp/Meta SDP interop fix, and all three languages.

## Honest limitations

- The **SSC levy** is applied to Time-of-Use bills but not yet to standard block bills, so those read about 2.5% below a real bill.
- **Sinhala and Tamil** strings are first-pass translations and want a native speaker's review.
- Every figure is an **estimate against the published tariff**. This is an independent tool; it is not CEB, LECO or PUCSL, and it does not issue official bills.
- Tariffs change. `engine/data/tariff_ceb_domestic.json` is dated and carries its sources; update it and the golden vectors together.
