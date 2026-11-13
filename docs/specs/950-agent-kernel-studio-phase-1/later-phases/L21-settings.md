# 21 · Settings

> **Parked for a later phase.** Written for the hosted product, before Phase 1 was scoped as a local desktop
> app. Revise it against the current project brief before designing from it. Brief numbers inside refer to
> the original numbering; see [README.md](README.md) in this folder.

| | |
|---|---|
| Artboards | `Settings-Secrets` (main), `Settings-CodingAgents`, `Settings-Members`, `Settings-ApiKeys`, `Settings-Billing` |
| Canvas page | Settings |
| Kind | Page with `AppShell`, fluid, drawn at 1440 wide |
| Fidelity | Static. The settings sub-navigation links the artboards. |
| Story moment | C, operating |
| Read first | [00-project-brief.md](../00-project-brief.md) |

## Job

Workspace administration. Secrets is the main artboard because it is the most specific to Agent Kernel: keys
are resolved at runtime from the environment first, then from a provider, and are never written back.

## Layout

- `AppShell` with Settings active. No environment switcher in the top bar.
- A `SubNav` on the left: Members and roles, Secrets (active), API keys, Coding agents, Billing.
- Content on the right in a readable column.

## Content

**`Settings-Secrets`**
- Header "Secrets", description "Keys are resolved at runtime: the process environment first, then the provider
  configured for the environment. Values are cached with a TTL and never written back to the environment."
- Card "Provider by environment", tabs Local, Staging, Production (active). Production: provider "AWS SSM
  Parameter Store"; "Prefix" `acme-prod-agents` with the helper "Resolved path:
  /ak/acme-prod-agents/<key in lowercase>"; "Cache TTL" 300 s; a line "Staging uses Kubernetes Secrets mounted
  into the pod · Local uses environment variables"; a control "Invalidate cache".
- Card "Keys": a search field, a primary "Add key", and a `DataTable`. Values are never shown.

| Key | Source | Used by | Last rotated | Status |
|-----|--------|---------|--------------|--------|
| OPENAI_API_KEY | AWS SSM | OpenAI Agents SDK, OpenAI Guardrails | 12 days ago | OK |
| ANTHROPIC_API_KEY | AWS SSM | LangGraph (claude-sonnet-4-5) | 12 days ago | OK |
| GOOGLE_API_KEY | AWS SSM | Google ADK | 30 days ago | OK |
| SLACK_BOT_TOKEN | AWS SSM | Slack | 87 days ago | Rotates in 3 days |
| SLACK_SIGNING_SECRET | AWS SSM | Slack | 87 days ago | OK |
| LANGFUSE_SECRET_KEY | AWS SSM | Langfuse | 5 days ago | OK |
| WALLED_API_KEY | AWS SSM | Walled AI | 40 days ago | OK |

**`Settings-CodingAgents`**
- One card per coding agent with its real mark, a status and a permissions row: toggles "Edit project files",
  "Run commands", "Install packages", "Deploy", and a select "Approval: Always ask / Allow listed commands".
- Claude Code: connected; skills ak-init, ak-build, ak-add-capabilities, ak-add-integration, ak-test,
  ak-cloud-deploy; all toggles on except Deploy.
- Codex: connected. Cursor, Windsurf, GitHub Copilot: a "Connect" button each.
- A note: "Coding agents act through the bundled Agent Kernel skills; destructive steps always pause for
  approval".

**`Settings-Members`**
- A `DataTable`: Name, Email, Role (Owner, Admin, Developer, Approver, Viewer), Last active; a primary "Invite
  member". Rows: Amitha D. (Owner) and Priya N. (Approver) from the fixture; further rows are placeholders
  `[MEMBER]`.
- A note: "Approvers can resolve paused runs and approve coding-agent actions".

**`Settings-ApiKeys`**
- A `DataTable` of workspace API keys: Name, Prefix, Scopes (chat, threads, schedules), Created, Last used; a
  primary "Create key"; an `InlineBanner` "Keys are shown once at creation".

**`Settings-Billing`**
- A plan card "`[PLAN]` · `[PRICE]`", three usage meters ("Runs", "Seats", "Environments") with placeholder
  limits, and "Manage plan".

## Behaviour

- The sub-navigation links the five artboards. A key row's "Used by" entries link to the screen that uses the
  key (Slack to `Connect-Channels`, Langfuse to `Operate-Traces-Provider`).

## Tweaks

- `subNav`: left column or top tabs.

## Handoff notes

- Secret providers are `env`, `aws_ssm` and `kubernetes`, plus a custom class path. The AWS path shape is the
  runtime's real one.
- Roles and their permissions are a product decision. "Approver" is the role BR-004 and BR-005 rely on.

## Open details

- Pricing, plan names and limits.
- "Workspace" and "Danger zone" sections are not briefed yet, so the sub-navigation leaves them out.
  Authentication settings live under Guardrails (brief 13).
