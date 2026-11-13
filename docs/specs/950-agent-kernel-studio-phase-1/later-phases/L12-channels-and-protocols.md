# 12 · Channels and protocols

> **Parked for a later phase.** Written for the hosted product, before Phase 1 was scoped as a local desktop
> app. Revise it against the current project brief before designing from it. Brief numbers inside refer to
> the original numbering; see [README.md](README.md) in this folder.

| | |
|---|---|
| Artboards | `Connect-Channels` (main), `Connect-Channels-LiveKit`, `Connect-Channels-Add`, `Connect-Channels-A2ACards`, `Connect-Channels-RestDetail` |
| Canvas page | Connect |
| Kind | Page with `AppShell`, fluid, drawn at 1440 wide |
| Fidelity | Static with links |
| Story moment | C, operating |
| Read first | [00-project-brief.md](../00-project-brief.md) |

## Job

Everything that connects people and systems to the agents: the messaging channels, LiveKit voice, and the
protocol surfaces. A side panel configures one channel. Secrets are referenced, never typed in plain text.

## Layout

- `AppShell` with Channels active.
- Main area: a section "Messaging channels" as a grid of cards, then a section "Protocols and APIs" as a list.
- A configuration panel docked on the right for the selected channel.

## Content

**Messaging channels.** One card per channel with its real logo, a status and a summary.

| Channel | Status | Summary |
|---------|--------|---------|
| Slack (selected) | connected | #support · routed to triage · 1,204 messages today |
| WhatsApp | connected | routed to triage |
| Gmail | connected | polling every 30 s |
| LiveKit voice | beta | realtime · routed to triage |
| Microsoft Teams, Messenger, Instagram, Telegram | not connected | a "Connect" button each |

**Protocols and APIs.** One row each: an icon, a name, an endpoint, a status and a chevron.

| Protocol | Endpoint | Detail |
|----------|----------|--------|
| REST and SSE | `https://api.acme.example/api/v1/chat` | execution mode async · message type delta · a "Copy curl" control |
| WebSocket gateway | `wss://ws.acme.example/ws` | push auth configured |
| MCP server | `/mcp` | exposes 3 agents as tools |
| A2A | `/a2a` | 3 agent cards · link "View cards" |
| AG-UI | `/agui` | default agent triage · shared state on |

**Configuration panel · Slack.** Header with the Slack logo and "Connected". Fields:
- "Workspace": Acme Labs.
- "Bot token": a `SecretChip` "SLACK_BOT_TOKEN · AWS SSM" with "Change".
- "Signing secret": a `SecretChip` "SLACK_SIGNING_SECRET · AWS SSM".
- "Events URL": `https://api.acme.example/slack/events` with a copy control.
- "Routed agent": triage. "Reply chunking": 4000 characters.
- Toggles: "Acknowledge with typing indicator", "Download attachments (needs multimodal)", "Reply in thread".
- "Recent events": four rows (time, event type, channel, status).
- Footer: a danger "Disconnect" and a primary "Save".

## Behaviour

- Selecting LiveKit voice goes to `Connect-Channels-LiveKit`. "Connect" opens `Connect-Channels-Add`.
- "View cards" opens `Connect-Channels-A2ACards`. The REST row expands to `Connect-Channels-RestDetail`.

## States and variants

| Artboard | Pass | Shows |
|----------|------|-------|
| `Connect-Channels-LiveKit` | first | The panel for LiveKit voice: "LiveKit URL"; API key and secret as `SecretChip`s; "Voice agents" listing triage and billing, with a toggle "Allow handoffs between voice agents"; a fixed chip "Execution mode: realtime"; a primary "Join test room". |
| `Connect-Channels-Add` | first | A modal "Connect channel": the channel logos as a grid, Telegram selected; a "Bot token" field with a select "Store in: AWS SSM Parameter Store"; a "Routed agent" select; "Cancel" and "Connect". |
| `Connect-Channels-A2ACards` | second | A modal "Agent cards": a list of the three agents and the JSON card of triage (name, description, URL, skills, streaming capability), with "Copy JSON". |
| `Connect-Channels-RestDetail` | second | The REST row expanded: a curl request to `/api/v1/chat` with `session_id`, `prompt` and `agent`, beside a short SSE response. |

## Tweaks

- `panel`: docked or closed.

## Handoff notes

- Routing a channel to triage is what enforces BR-001.
- Each channel's fields come from its config block in `AKConfig` (`slack`, `whatsapp`, `gmail`, `livekit` and
  the others). Channels that need attachments require the multimodal capability.
- LiveKit voice is unreleased in the repository at the time of writing; keep the beta marker.
