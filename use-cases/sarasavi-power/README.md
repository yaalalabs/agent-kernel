# Sarasavi Power ⚡

**A WhatsApp-first energy assistant that helps Sri Lankan households understand and reduce their electricity bill, built with [Agent Kernel](https://github.com/yaalalabs/agent-kernel).**

IDEALIZE 2026 mini-competition · **SDG 7** (Affordable and Clean Energy), with secondary contributions to SDG 12 and SDG 13.

## 1. Problem statement

Sri Lanka's domestic electricity tariff is difficult to reason about. Total consumption selects a tariff category, some category changes re-price the whole billing period, and block ceilings change with the exact number of billing days. A household can cross a boundary by only a few units and receive a much larger bill without knowing which appliance or habit caused it.

Sarasavi Power turns a household's appliance usage or typed meter reading into:

- an explainable kWh estimate and itemized LKR bill estimate,
- the appliances that contribute the most consumption,
- the most valuable lower tariff boundary to target, and
- concrete, safe actions with a simulated bill impact.

## 2. Solution overview

The product uses Agent Kernel as the runtime, session-memory layer, hooks pipeline, REST interface, and WhatsApp integration. Four Google ADK agents running on Gemini form a one-way transfer graph:

```text
WhatsApp / Agent Kernel CLI / Agent Kernel REST
                    |
             orchestrator
          /         |          \
      intake     analysis   recommendation
          \         |          /
               typed tools
                    |
     deterministic consumption + tariff engine
```

- `orchestrator` classifies each message and transfers it to one specialist. Specialists set `disallow_transfer_to_parent` / `disallow_transfer_to_peers`, so routing stays one-way and the next turn restarts at the orchestrator.
- `intake` obtains storage consent and records the household, appliances, or a typed meter reading.
- `analysis` explains usage and computes the current bill.
- `recommendation` finds tariff-boundary opportunities and simulates changes.
- Agent Kernel non-volatile session memory retains one consent-controlled household profile.
- Agent Kernel pre/post hooks block unsafe electrical instructions and append localized estimate disclaimers.
- The LLM never calculates kWh or money. Every number comes from the pure-Python engine in `engine/`.

The primary integration is Meta WhatsApp Cloud API. A terminal client, REST endpoint, and keyless deterministic demo make the submission reviewable before Meta credentials are added.

### Languages

Sarasavi Power supports **English, Sinhala, and Tamil** throughout onboarding, analysis, recommendations, safety refusals, and estimate disclaimers.

- English is the default.
- Sinhala or Tamil script is detected automatically.
- After consent, the detected preference is stored in the same Agent Kernel session profile and follows specialist transfers.
- Users can switch explicitly by saying `English`, `සිංහල`, or `தமிழ்`.
- Appliance display names and curated saving tips come from committed translations, while keys and numeric calculations remain language-independent.

## 3. Setup instructions

Prerequisites:

- Python 3.12+
- [`uv`](https://docs.astral.sh/uv/)
- a Google Gemini API key for conversational modes (free tier at [AI Studio](https://aistudio.google.com/apikey))
- Meta credentials only when enabling WhatsApp

From `use-cases/sarasavi-power/`:

```bash
uv sync
cp .env.example .env
```

On PowerShell, use `Copy-Item .env.example .env` instead of `cp` if needed.

Set `GOOGLE_API_KEY` in `.env` to run the Agent Kernel conversation (`SARASAVI_MODEL` defaults to `gemini-2.5-flash`; any Gemini model your key can reach works). Leave the four `AK_WHATSAPP__*` values as placeholders until your Meta app is ready; they are not required by the keyless demo, CLI, REST server, or tests.

To use Vertex AI instead of an AI Studio key, set `GOOGLE_GENAI_USE_VERTEXAI=TRUE` and provide the usual Google Cloud credentials; startup then stops asking for `GOOGLE_API_KEY`.

## 4. How to run the solution

### A. Instant keyless demo

This is the fastest judge path. It needs no API keys and exercises the same deterministic engine used by the agents:

```bash
uv run python offline_demo.py
uv run python offline_demo.py --units 61 --days 30
uv run python offline_demo.py --language si
uv run python offline_demo.py --language ta
```

Custom appliance profile:

```bash
uv run python offline_demo.py \
  --appliance refrigerator:24 \
  --appliance air_conditioner:5 \
  --appliance led_bulb:5:6
```

Use `--list-appliances` to see valid keys and `--json` for machine-readable output.

### B. Agent Kernel terminal conversation

Requires only `GOOGLE_API_KEY`:

```bash
uv run python demo.py
```

The client selects `orchestrator`, prints a progress message while multi-agent
transfers run, and stops an individual request after 60 seconds rather than waiting
forever. Set `SARASAVI_RESPONSE_TIMEOUT` in `.env` to change the 5-300 second limit.

Suggested demo conversation:

1. “Hi, I want to estimate my electricity bill.”
2. Give explicit consent when asked.
3. “Monthly bill, 30 days. I have a fridge running all day, two fans for 8 hours, and six LED bulbs for 5 hours.”
4. “What is my estimated bill?”
5. “How can I reduce it?”
6. “What if I use the fans for 6 hours?”

### C. Local Agent Kernel REST API

```bash
uv run python rest.py
```

Then call:

```bash
curl -X POST http://localhost:8000/api/v1/chat \
  -H "Content-Type: application/json" \
  -d '{"agent":"orchestrator","session_id":"demo-1","prompt":"Hi"}'
```

Keep the same `session_id` across requests so Agent Kernel can retain consent and the household profile.

### D. WhatsApp after Meta credentials are available

Fill these values in `.env`:

```dotenv
AK_WHATSAPP__VERIFY_TOKEN=...
AK_WHATSAPP__ACCESS_TOKEN=...
AK_WHATSAPP__PHONE_NUMBER_ID=...
AK_WHATSAPP__APP_SECRET=...
```

Where each value comes from in the Meta app dashboard:

| `.env` key | Meta dashboard value |
| --- | --- |
| `AK_WHATSAPP__VERIFY_TOKEN` | any string you choose; paste the same one into the webhook config |
| `AK_WHATSAPP__ACCESS_TOKEN` | the permanent (system-user) access token |
| `AK_WHATSAPP__PHONE_NUMBER_ID` | WhatsApp → API Setup → Phone number ID |
| `AK_WHATSAPP__APP_SECRET` | App settings → Basic → App Secret |

The App ID and WhatsApp Business Account ID are used inside the Meta dashboard only; Agent Kernel does not read them.

Then run:

```bash
uv run python app.py
```

Expose the server through HTTPS and configure the Meta webhook as:

```text
https://YOUR_PUBLIC_HOST/whatsapp/webhook
```

Use the same verify token in Meta and `.env`, subscribe the app to WhatsApp messages, and send a message to the connected test or production number. Startup rejects missing or placeholder Meta values with an actionable message.

## 5. Voice: WhatsApp calls and voice notes

Sarasavi Power answers **WhatsApp voice calls** and **voice notes** in Sinhala, Tamil, and English.

### Voice notes (works on any number)

Send a voice note to the business number: the audio rides to Gemini natively (no separate STT), the reply arrives as text **and** as a synthesized voice note (Gemini TTS). No extra Meta setup beyond the normal `messages` webhook.

### Live calls (WhatsApp Business Calling API)

Architecture: `calls` webhook → SDP answer via aiortc (WebRTC/Opus) → **Gemini Live API native speech-to-speech** (the approach proven in [Amathum-AI](https://github.com/kalanas210/Amathum-AI)) → the same deterministic tools and the same session profile the chat uses. Consent given on a call is honoured in chat, and the chat can reference `last_voice_call`.

One-time Meta setup:

1. Subscribe the app webhook to the **`calls`** field (keep `messages`).
2. Enable calling on the number:

```bash
uv run python devtools/enable_calling.py
```

3. Sandbox testing: claim a Calling sandbox account, add tester numbers, and on each tester's phone open the business chat → **Business Calling Permission** → **Allow calls**. Sandbox numbers are exempt from the 2,000-recipient messaging-tier requirement.

Dev harness (needs only `GOOGLE_API_KEY`):

```bash
uv run python devtools/voice_loopback.py --text "How can I cut my bill?"
uv run python devtools/voice_loopback.py --wav sinhala_question.wav
uv run python devtools/voice_browser.py    # mic-to-ear via a local browser page
```

Voice env keys (see `.env.example`): `SARASAVI_VOICE_ENABLED`, `SARASAVI_VOICE_MODEL`, `SARASAVI_VOICE_NAME`, `SARASAVI_TTS_MODEL`, `SARASAVI_TTS_VOICE`, `SARASAVI_MAX_CALLS`, `SARASAVI_CALL_MAX_SECONDS`.

## 6. AWS deployment (Terraform, free tier)

`deploy/ec2/` provisions one **t4g.small** (free-tier promo) with an Elastic IP, a DynamoDB session table (sessions survive restarts), Caddy auto-HTTPS on an `sslip.io` hostname, and the UDP range WebRTC media needs:

```bash
cd deploy/ec2
terraform init
terraform apply
./deploy.ps1        # Windows; ships the code, writes Caddyfile, starts services
```

Then fill `GOOGLE_API_KEY` + `AK_WHATSAPP__*` in `/opt/sarasavi/.env` on the instance, restart the service, and paste the `webhook_url` output into the Meta dashboard. Lambda is unsuitable here: the WhatsApp router and the live call bridge both need a persistent process.

## Verification

```bash
uv run pytest -q
uv run python -m engine.golden_vectors
uv run black --check .
```

The regression suite covers official tariff anchors, billing-day proration, the 60-to-61-unit cliff, appliance estimates, consent and deletion, tool errors, hooks, agent transfers, startup configuration, and the keyless demo.
It also covers language detection, consent-aware preference persistence, and localized appliance/tip output for English, Sinhala, and Tamil.

## Tariff data and correctness

The committed table is the PUCSL domestic block tariff effective **11 May 2026**. Values and the above-180 revision were checked against the [official PUCSL tariff decision](https://www.pucsl.gov.lk/wp-content/uploads/2026/05/Full-Final_Decision-on-Electricity-Tariffs-May-2026.pdf) and [official domestic calculator](https://www.pucsl.gov.lk/calculator/) on 16 July 2026.

- Block ceilings are floor-prorated to the actual billing days.
- The selected category's fixed charge is applied once per bill.
- Exact meter units take priority over an appliance estimate.
- Source URLs, effective date, and verification status live beside the rates in `engine/data/tariff_ceb_domestic.json`.

Tariffs can change. Update the dated JSON and golden vectors before using a later tariff period.

## Privacy and safety

- Household details are stored only after explicit consent.
- Revoking consent erases the profile; export and delete tools are available.
- No Meta or Google secret is committed. `.env` is ignored by Git.
- Unsafe meter, wiring, and repair instructions are refused by deterministic pre/post hooks.
- Every monetary response is an estimate, not an official CEB/LECO bill.

## Repository layout

```text
sarasavi-power/
├── engine/              deterministic consumption and tariff engine + dated data
├── tests/               focused regression suite
├── agent.py             orchestrator and three specialist agents
├── tool.py              typed Agent Kernel tool adapters
├── state.py             consent-controlled Agent Kernel session profile
├── hooks.py             safety and localized disclaimer hooks
├── offline_demo.py      complete keyless product demonstration
├── demo.py              Agent Kernel terminal client
├── rest.py              Agent Kernel local REST server
├── app.py               WhatsApp webhook server
├── lambda.py            optional Agent Kernel AWS Lambda entrypoint
├── whatsapp_ext/        WhatsApp handler subclass: voice notes + calls routing + media send
├── voice/               WhatsApp Calling API <-> Gemini Live bridge (aiortc + tools)
├── devtools/            voice loopback harness + one-shot Meta calling enablement
├── deploy/ec2/          Terraform: EC2 + DynamoDB + Caddy HTTPS + WebRTC ports
├── localization.py      English/Sinhala/Tamil names, tips, detection, and UI labels
├── config.yaml          session, logging, and WhatsApp configuration
├── SPEC.md              implementation specification
└── AGENTS.md            coding-agent guidance
```

## Current scope

The build supports typed appliance usage, typed meter/bill units, voice notes, and live WhatsApp voice calls, with an optional Terraform EC2 deployment. Bill-photo OCR, proactive WhatsApp template messages, and automatic tariff ingestion remain intentionally out of scope. They do not block the complete onboarding → estimate → bill → savings → simulation flow in chat or on a call.
