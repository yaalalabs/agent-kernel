# Parked briefs (later phases)

These briefs describe screens that are **not in Phase 1**. They were written for the hosted product and are
kept so the work is not lost. Do not design from them yet. Each one needs a revision against the current
[project brief](../00-project-brief.md) first: the shell, the fixture data and the navigation all changed when
Phase 1 became a local desktop app.

| File | Screen | Why it is parked | What Phase 1 offers instead |
|------|--------|------------------|-----------------------------|
| [L01-sign-in.md](L01-sign-in.md) | Sign in, sign up, SSO | No accounts in a local app | The Welcome screen opens a folder |
| [L03-dashboard.md](L03-dashboard.md) | Dashboard | Dashboards observe a deployed system | The canvas is the overview |
| [L09-agent-detail.md](L09-agent-detail.md) | Agents: list and detail | Deep configuration page | The canvas inspector tabs |
| [L10-tools-and-mcp.md](L10-tools-and-mcp.md) | Tools, MCP and sandbox | Deep configuration page | Tool nodes, the Code tab, the Config tab |
| [L11-knowledge-bases.md](L11-knowledge-bases.md) | Knowledge bases | Deep configuration page | Knowledge nodes and the Config tab |
| [L12-channels-and-protocols.md](L12-channels-and-protocols.md) | Channels and protocols | Deep configuration page, with live events | Channel nodes and the Config tab |
| [L13-guardrails-and-policies.md](L13-guardrails-and-policies.md) | Guardrails, hooks, sandbox policy, authentication | Deep configuration page, with live activity | Guardrail nodes and the Config tab |
| [L14-memory-and-state.md](L14-memory-and-state.md) | Memory and state | Browses live sessions and threads | Store nodes and the Config tab |
| [L15-playground.md](L15-playground.md) | Playground | Tests a deployed environment, with history | The Test & Trace tab, against the local run |
| [L16-conversations.md](L16-conversations.md) | Conversations | Post-deployment | None |
| [L17-traces.md](L17-traces.md) | Traces | Post-deployment, reads a tracing provider | The trace of the current local run |
| [L18-evaluations.md](L18-evaluations.md) | Evaluations | Suite history and gates across environments | The test strip in Test & Trace |
| [L19-schedules.md](L19-schedules.md) | Schedules | Schedules are created against a running system | None |
| [L20-deployments.md](L20-deployments.md) | Deployments | Monitoring, topology and history | The Deploy tab: plan, apply, outputs |
| [L21-settings.md](L21-settings.md) | Workspace settings | Members, roles, API keys, billing | App settings on this computer (brief 09) |

## Reading the numbers inside these files

The files keep their original text. A reference such as "brief 13" means the file whose name starts with `L13`
in this folder. References to briefs 04 to 08 mean the Phase 1 briefs of the same number, one folder up.
References to "brief 22" mean [01-app-components.md](../01-app-components.md), and "brief 02" means
[03-new-project.md](../03-new-project.md).

Artboard names in these files were chosen before Phase 1. Some, such as the `Settings-` names, now collide with
Phase 1 artboards and must be renamed when a brief is revived.
