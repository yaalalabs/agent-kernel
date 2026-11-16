# Visual low-code and open-source agent/workflow builders (state as of 16 November 2026)

Notes for the AK Studio Phase 1 competitive landscape. Each finding has an inline source. GitHub star counts, licenses, archive flags and push dates were read directly from the GitHub REST API on 2026-11-16 (cited as "GitHub API"). Claims that came only from a search-engine summary (not a fetched page) are marked "(search summary)", and third-party or vendor-adjacent claims are marked "(third-party)". Anything dated before 2026 is flagged as possibly outdated.

## Product-by-product: overlap with AK Studio Phase 1, form factor, license, pricing, adoption, status

### Takeaway
The category split sharply in 2026. Two visual builders exited: Flowise (wound down by its Workday-owned team in July/August 2026) and OpenAI Agent Builder (deprecated June 2026, shutting down 30 November 2026), and both exits point people toward code and coding agents. Meanwhile the large open-source players (n8n, Dify, Langflow, Sim) grew and are bolting on CLIs, git workflows and MCP endpoints so coding agents like Claude Code can drive them. Vellum moved toward a consumer "personal intelligence" assistant, Stack AI was bought by Asana, and Rivet is effectively in maintenance.

### Cited Findings

**Langflow (incl. Langflow Desktop)**
- Status: active. 156,696 GitHub stars, MIT license, pushed 2026-11-16. ([GitHub API](https://github.com/langflow-ai/langflow))
- Ownership: Langflow came with DataStax, which IBM agreed to acquire on 25 Feb 2025 and closed on 28 May 2025. IBM said Langflow would add middleware to watsonx.ai and that it would keep supporting the Langflow community (possibly outdated, 2025). ([Techzine](https://www.techzine.eu/news/data-management/129066/ibm-strengthens-ai-portfolio-with-acquisition-of-datastax); [I-Connect007](https://iconnect007.com/article/145543/ibm-officially-closes-deal-acquiring-datastax/145540/smt))
- 2026 release cadence: OSS 1.12 on 1 Sep 2026 added OpenTelemetry traces, metrics and logs for the Langflow service plus "extension bundles" (default install ships a curated provider set, others installed as `langflow[bundles]` or `lfx-*` packages). ([Langflow 1.12 blog](https://langflow.org/blog/langflow-1-12))
- OSS 1.13 (22 Oct 2026) added append-only audit logging (`LANGFLOW_AUDIT_ENABLED`), reusable OAuth "Connections" for Google Workspace, Microsoft 365 and Slack, and concurrent-editing protection. It made auth on by default (`LANGFLOW_AUTO_LOGIN=false`) and moved local Knowledge and Memory from Chroma to SQLite. ([Langflow 1.13 blog](https://langflow.org/blog/langflow-1-13); [Langflow release notes](https://docs.langflow.org/release-notes))
- 1.13 also brought user/team/role administration through the API and a `langflow admin` CLI, plus a guided instance-migration workflow. ([Langflow release notes](https://docs.langflow.org/release-notes))
- Langflow Desktop ships about one release per OSS minor: 1.9 Desktop on 24 Apr 2026, 1.10 on 18 Jun 2026, 1.12 on 16 Sep 2026, 1.13 on 2 Nov 2026. Upgrades happen in the app. ([Langflow 1.9 Desktop](https://www.langflow.org/blog/langflow-1-9-desktop); [Langflow 1.10 Desktop](https://langflow.org/blog/langflow-1-10-desktop)). Desktop and OSS share major and minor versions but can differ on patch. ([Langflow release notes](https://docs.langflow.org/release-notes))
- Desktop platforms: macOS Apple Silicon, macOS Intel and Windows x64. Windows Arm is "coming soon" and no Linux build is listed. A form must be filled in before download. macOS needs 13 or later, and Windows may need a C++ compiler. Shareable Playground and Voice Mode are not available in Desktop. ([Langflow download page](https://langflow.org/download); [Langflow install docs 1.9](https://docs.langflow.org/1.9.0/get-started-installation)) (search summary)
- Overlap with AK Studio: local desktop app, visual canvas, an AI assistant that builds flows, MCP, git-friendly flow files through the `lfx` toolkit, tracing. Langflow's runtime is its own component graph, not a mainstream agent framework (details in later sections).

**Flowise (acquired by Workday, then wound down)**
- Workday announced the acquisition of Flowise on 14 Aug 2025 (terms undisclosed). It positioned Flowise as the agent builder for its platform, focused on HR and finance. ([Workday press release PDF](https://s21.q4cdn.com/950027458/files/doc_news/Workday-Acquires-Flowise-Bringing-Powerful-AI-Agent-Builder-Capabilities-to-the-Workday-Platform-08-14-2025-2025.pdf); [SiliconANGLE](https://siliconangle.com/2025/08/15/workday-acquires-flowise-boost-ai-powered-workflows/))
- Wind-down: on 13 Aug 2026 the Flowise co-founder posted "The Future of Flowise", saying "we've decided to wind down our operations for Flowise". The timeline was: code freeze and announcement on 29 Jul 2026, repository archival on 13 Aug 2026 (npm packages and Docker images marked deprecated), and end of life on 31 Aug 2026. ([GitHub discussion #6727](https://github.com/FlowiseAI/Flowise/discussions/6727))
- Stated reason: "As AI models become more capable at reasoning, we've noticed that developers are increasingly relying on new coding agents to handle complex tasks. The typical rigid workflow low-code approach quickly hits the limit when it comes to complexity." ([GitHub discussion #6727](https://github.com/FlowiseAI/Flowise/discussions/6727)). The official sunset page names "Claude Code and OpenClaw" as the coding agents. ([Flowise sunset page](https://flowiseai.com/sunset))
- Date conflict: the sunset page gives 10 Aug 2026 for repository archival ([Flowise sunset page](https://flowiseai.com/sunset)). The GitHub discussion says 13 Aug 2026, and the API shows the last push on 2026-08-13. ([GitHub discussion #6727](https://github.com/FlowiseAI/Flowise/discussions/6727); [GitHub API](https://github.com/FlowiseAI/Flowise))
- Repository state: archived, 55,570 stars, README headed "Flowise has been archived". The last release was flowise@3.1.4 on 2026-07-29. All companion repos (FlowiseChatEmbed, FlowiseDocs, FlowiseEmbedReact) are also archived. ([GitHub API](https://github.com/FlowiseAI/Flowise))
- The code stays available under Apache 2.0 and teams are encouraged to fork it. ([Flowise sunset page](https://flowiseai.com/sunset))
- Third-party commentary links the shutdown to coding agents ("Coding Agents Just Killed the Visual AI Builder"). ([AgentMarketCap, third-party, search summary](https://agentmarketcap.ai/blog/2026/07/30/flowise-sunset-low-code-agent-builders); [zeli.app, third-party, search summary](https://zeli.app/story/49176920))

**Dify**
- Status: very active. 161,258 GitHub stars, pushed 2026-11-16. ([GitHub API](https://github.com/langgenius/dify))
- License: "a modified version of the Apache License 2.0". Running a multi-tenant service needs written authorization, and the logo and copyright in the frontend cannot be removed. ([Dify LICENSE](https://github.com/langgenius/dify/blob/main/LICENSE))
- Funding: $30M Series Pre-A at a $180M valuation, announced 9 Mar 2026 and led by HSG. Dify says it runs on more than 1.4M machines, has more than 2,000 teams and 280 enterprises on commercial versions, and names Maersk, ETS, Anker Innovations and Novartis as customers. ([VentureBeat / BusinessWire](https://venturebeat.com/business/dify-raises-30-million-series-pre-a-to-power-enterprise-grade-agentic-workflows))
- 2026 releases:
  - 1.13.0 (Feb 2026): Human-in-the-Loop.
  - 1.14.0 (29 Apr 2026): real-time multi-user workflow collaboration and a HITL Service API.
  - 1.15.0 (25 Jun 2026): `difyctl` CLI.
  - 1.16.0 (17 Jul 2026): "Dify Agent" beta, a shell-based agent in a Linux sandbox with Skills, plus "an agent that helps you build Dify Agents".
  - 1.16.1: Agent DSL export "to back up or version-control agent configurations".
  - 1.17.0 (25 Aug 2026): E2B sandbox backend.
  - 1.18.0 (23 Oct 2026): agents that route workflow branches, portable app packages, OpenAPI.
  - 1.19.0 (4 Nov 2026): nested workflow tracing into external observability tools.

  ([Dify releases](https://github.com/langgenius/dify/releases); [1.16.0](https://github.com/langgenius/dify/releases/tag/1.16.0); [1.18.0](https://github.com/langgenius/dify/releases/tag/1.18.0); [1.19.0](https://github.com/langgenius/dify/releases/tag/1.19.0))
- Form factor: self-hosted web with Docker Compose (one docker-compose.e2b.yaml ships the E2B stack), plus Dify Cloud and an Enterprise edition. ([Dify 1.17.0 release](https://github.com/langgenius/dify/releases/tag/1.17.0); [Dify enterprise releases](https://ee.dify.ai/releases))

**n8n (AI agent nodes and AI Workflow Builder)**
- Status: the largest in the category. 210,626 GitHub stars, pushed 2026-11-16. ([GitHub API](https://github.com/n8n-io/n8n))
- License: fair-code "Sustainable Use License", not OSI open source. Files with `.ee.` in their name or directory need an n8n Enterprise License. ([n8n LICENSE.md](https://github.com/n8n-io/n8n/blob/master/LICENSE.md))
- Funding:
  - Mar 2025: $60M (possibly outdated). ([TechCrunch](https://techcrunch.com/2025/03/24/fair-code-pioneer-n8n-raises-60m-for-ai-powered-workflow-automation))
  - Oct 2025: $180M Series C at about $2.5B (third-party). ([Salestools, third-party](https://salestools.io/en/report/n8n-raises-180m-series-c))
  - 2026: SAP strategic investment that doubled the valuation to $5.2B, with plans to embed n8n in SAP Joule Studio. ([Highland Europe](https://www.highlandeurope.com/n8n-valuation-doubles-to-5-2bn-as-sap-makes-strategic-investment-and-plans-to-embed-the-ai-platform-into-joule-studio/); [Dealroom, 3 Jun 2026](https://dealroom.co/news/132833-n8ns-valuation-doubles-to-5-2b-with-sap-strategic-investment/))
  - Sacra estimates about $100M ARR as of Apr 2026 (estimate, third-party). ([Sacra](https://sacra.com/c/n8n/))
- Pricing (annual billing, EUR):
  - Starter €20/mo: 2.5K executions, 1,600 AI assistant credits.
  - Pro €50/mo: 10K executions, up to 9,600 credits.
  - Business €667/mo: 40K executions, Git and environments, SSO, listed as self-hosted.
  - Enterprise: custom, includes Git and environments.
  - The self-hosted Community Edition is on GitHub.

  ([n8n pricing](https://n8n.io/pricing/))
- n8n 2.0 shipped in Dec 2025 as a security-hardening release: code moved into a separate "Task Runner" process and legacy options were removed (third-party, possibly outdated). ([wotai migration guide, third-party](https://wotai.co/blog/n8n-v2-migration-guide))

**Rivet (Ironclad)**
- What it is: an open-source visual AI programming environment that Ironclad built for its Contract AI. It was beta tested with AssemblyAI, Attentive, Bento, Willow and Sourcegraph before public release in Sep 2023 (outdated origin facts). ([Ironclad blog](https://ironcladapp.com/blog/meet-rivet/); [Rivet site](https://rivet.ironcladapp.com/))
- Graphs are saved as YAML so they can be versioned in git. A TypeScript library, `@ironclad/rivet-core`, runs graphs inside an application. ([Rivet site](https://rivet.ironcladapp.com/)) (search summary)
- Status: effectively in maintenance. 4,731 stars, MIT. The last app release was app-v1.11.3 on 2025-08-08 and the last core release v1.25.0 on 2025-06-30. The only 2026 commits found are Dependabot merges to the Tauri (`src-tauri`) desktop app, dated 2026-08-26. ([GitHub API](https://github.com/Ironclad/rivet))

**Sim (formerly Sim Studio)**
- Status: active and fast-moving. 30,146 stars, Apache-2.0, pushed 2026-11-16, near-daily releases (v0.9.58 on 2026-11-15). ([GitHub API](https://github.com/simstudioai/sim); [Sim releases](https://github.com/simstudioai/sim/releases))
- Funding: $7M Series A (reported Nov 2025) led by Standard Capital, with Perplexity Fund, SV Angel and Y Combinator (YC X25). ([StartupHub](https://startuphub.ai/news/sim-lands-7m-for-its-open-source-ai-workflow-builder); [Ry Walker research, third-party](https://rywalker.com/research/sim-ai))
- Positioning: "A workspace to build, deploy and manage AI agents and workflows".
  - Integrations: 270+ integrations with 5,400+ actions and 520+ triggers.
  - Building: "Build agents visually, conversationally, or with code".
  - Data: Tables, Files and Knowledge.
  - Enterprise: SOC 2 Type II and ISO 27001, SSO, SCIM, audit logs.

  ([Sim README](https://github.com/simstudioai/sim))
- Form factor: Sim Cloud, a self-hosted install (`npx sim-setup` wizard on Docker Compose, plus a Helm chart for Kubernetes), and a macOS desktop app. ([Sim README](https://github.com/simstudioai/sim); [Sim releases (helm-chart-1.11.20)](https://github.com/simstudioai/sim/releases))
- In Mar 2026 a launch called "Mothership" repositioned Sim from a workflow builder to a full AI workspace (third-party). ([Ry Walker research, third-party](https://rywalker.com/research/sim-ai))
- Pricing: open-source core free to self-host. One review says Sim Cloud's free tier had 1,000 one-time credits when read on 10 Nov 2026, and enterprise pricing is unpublished. Other third-party listings conflict. ([Beri review, third-party](https://www.beri.net/tools/sim-ai))

**Vellum**
- Workflows SDK: open source under MIT and runnable locally. A CLI syncs edits both ways between code and the Vellum UI, and "All Displayable Nodes support bidirectional synchronization between the Vellum UI and your SDK code" (push and pull). ([Vellum Workflows SDK docs](https://docs.vellum.ai/developers/workflows-sdk/introduction); [Vellum SDK GA blog](https://website.vellum.ai/blog/vellum-workflows-sdk-is-generally-available)) (search summary)
- Agent Builder: "Describe what you want to build, and Agent Builder will generate the underlying Python code and a visual graph representation using the Vellum SDK." ([Vellum Agent Builder blog](https://www.vellum.ai/blog/introducing-vellum-copilot)) (search summary)
- Status change in 2026: the homepage now reads "Vellum: Your Personal Intelligence", "A personal AI assistant for your busywork". It is free to download, and Vellum Cloud plans are $30/$100/$200 per month (Mighty/Super/Ultra). The homepage does not mention the agent builder, SDK or evaluations. ([Vellum homepage](https://www.vellum.ai/))
- Third-party pricing guides describe a 2026 move to compute plus credit pricing with the old developer-platform tiers retired ([eesel, third-party](https://www.eesel.ai/blog/vellum-ai-pricing)). Another listing still shows a $25/month Pro plan verified in Oct 2026 ([Toolradar, third-party](https://toolradar.com/tools/vellum-ai/pricing)). These conflict.
- Funding: $20M Series A in Jul 2025 led by Leaders Fund (possibly outdated). No 2026 round found. ([Dealroom](https://app.dealroom.co/news/feed/vellum-secures-20m-for-ai-development))

**Relevance AI**
- Funding: $24M Series B in May 2025 led by Bessemer, about $37M total (possibly outdated). No 2026 round found. The company launched "Workforce" (multi-agent teams) and "Invent" (plain-language agent builder) at that time. ([TechCrunch](https://techcrunch.com/2025/05/06/relevance-ai-raises-24m-series-b-to-help-anyone-build-teams-of-ai-agents/))
- Invent 2.0 targets building and testing autonomous agent workforces. A third-party review says Invent creates agents, tools and evals automatically from a description. ([Webull news item](https://www.webull.com/news/15661795987047424); [11x guide, third-party](https://www.11x.ai/guides/relevance-ai-pricing))
- Pricing: reports conflict. Several third-party guides say the free plan disappeared between Apr and May 2026 and the page now shows Enterprise only ("Talk to sales"). Another lists a $19/month plan as of 2 Oct 2026. Unverified against Relevance AI's own site. ([11x guide, third-party](https://www.11x.ai/guides/relevance-ai-pricing); [Toolradar, third-party](https://toolradar.com/tools/relevance-ai))

**Stack AI**
- Acquired by Asana in late May 2026 for a reported $75M. It was Asana's first acquisition in 18 years. About 55 staff and the founders joined Asana. Stack AI had raised just under $20M (mostly a $16M Series A). The stated rationale: Stack AI agents reach external ERP, CRM and ITSM systems, while Asana AI Studio works only inside Asana. ([The Next Web](https://thenextweb.com/news/asana-acquires-stack-ai-agent-builder-saas); [Fortune](https://fortune.com/2026/05/29/asana-was-battered-by-the-ai-age-now-its-betting-its-future-on-humans-and-agents-working-together/); [Reworked](https://reworked.co/digital-workplace/asana-buys-stackai-to-power-agent-orchestration/))
- Asana declined to confirm the price, so $75M is a reported figure. (search summary of the coverage above)

**Botpress**
- Funding: $25M Series B in Jun 2025 led by FRAMEWORK, about $45M total and a reported $120M post-money valuation (possibly outdated). No 2026 round found. ([Botpress blog](https://botpress.com/blog/series-b); [BetaKit](https://betakit.com/botpress-closes-34-million-cad-series-b-to-help-companies-build-and-deploy-ai-agents/))
- ADK v2: "a CLI tool and development framework for building AI agents on Botpress", in TypeScript. Each primitive lives in its own auto-discovered file: conversations, workflows, tools, actions, tables, knowledge, triggers, evals. `adk dev` runs locally with a Dev Console and hot reload. `adk deploy` ships to "your production bot on Botpress Cloud". ([Botpress ADK v2 docs](https://botpress.com/docs/adk-v2/get-started/introduction/))
- The open-source repository (MIT, 15,000 stars) still describes itself as "The open-source hub to build & deploy GPT/LLM Agents". Its last tagged release is v12.30.9 from Jun 2023, so the current product is the cloud platform. ([GitHub API](https://github.com/botpress/botpress))

**Voiceflow**
- V4 platform: unveiled 18 Feb 2026 and available to every user on 12 May 2026. It combines "Playbooks" (goal plus tools, autonomous) with "Workflows", where "Every step, every branch, every condition is explicitly defined on a visual canvas". MCP is a tool type alongside API calls and JavaScript functions, and guardrails sit in the global prompt. ([Voiceflow V4 launch](https://www.voiceflow.com/stories/everything-we-launched-v4))
- Further 2026 items: the Voiceflow Core model (May), simulated-persona testing (Jun), environment protection (Jul), the Atlas copilot beta (Aug). ([Voiceflow changelog](https://www.voiceflow.com/docs/changelog)) (search summary)
- Recognition: G2 Fall 2026 Leader, named in Gartner's Innovation Guide for AI Agents. ([Voiceflow G2 story](https://www.voiceflow.com/stories/voiceflow-g2-fall-2026-leader)) (search summary)

**Gumloop**
- Funding: $50M Series B announced Mar 2026, led by Benchmark with Shopify Ventures, Y Combinator and others, about $70M total. ([SiliconANGLE](https://siliconangle.com/2026/03/13/gumloop-reels-50m-ai-automation-platform/); [Gumloop blog](https://gumloop.com/blog/series-b))
- Product: drag-and-drop builder with "several hundred prepackaged connectors", Skills plug-ins, a visual editor that chains agents into workflows, and a Chrome extension. "Gumstack" is an admin, policy and secrets layer that monitors agent data access. ([SiliconANGLE](https://siliconangle.com/2026/03/13/gumloop-reels-50m-ai-automation-platform/))
- The company had 24 employees at the raise. ([BetaKit, search summary](https://betakit.com/?p=401984))

**Notable 2025/2026 entrants and exits**
- OpenAI Agent Builder (part of AgentKit, launched Oct 2025):
  - Status: "Deprecated", notice 3 Jun 2026, shutdown 30 Nov 2026.
  - Replacement: "Agents SDK or ChatGPT Workspace Agents". "ChatKit remains available".
  - OpenAI Evals (dashboard, API, graders) went read-only on the same timeline, with migration to Promptfoo.

  ([OpenAI deprecations page](https://developers.openai.com/api/docs/deprecations))
- LangSmith Agent Builder (LangChain): a no-code agent builder that entered public beta on 2 Dec 2025, reached GA on 13 Jan 2026, and is available on all LangSmith plans including free. It has since been renamed "LangSmith Fleet". ([LangChain blog](https://www.langchain.com/blog/langsmith-agent-builder-generally-available); [LangSmith Fleet docs](https://docs.langchain.com/langsmith/fleet)) It builds prompt-plus-tools agents rather than visual graph workflows. ([LangChain "Not Another Workflow Builder"](https://www.langchain.com/blog/not-another-workflow-builder))
- Activepieces (open-source automation, often listed next to n8n): 25,553 stars, pushed 2026-11-16. ([GitHub API](https://github.com/activepieces/activepieces))

### Inferences
- "Visual builder" is no longer a safe standalone category. Two well-known products (Flowise, OpenAI Agent Builder) exited in 2026, and both point users to code (forks, Agents SDK) or coding agents. This directly supports AK Studio's choice to keep code files as the source of truth and add a canvas on top, rather than the reverse.
- The survivors (n8n, Dify, Langflow, Sim) are big communities: n8n about 211K stars, Dify about 161K, Langflow about 157K. Their pull comes from integrations and a hosted runtime, not from the canvas alone. AK Studio will not beat them on connector breadth. Its niche is developers who want real framework code (OpenAI Agents SDK, LangGraph, CrewAI and the others AK wraps) plus visual comprehension and cloud deploy.
- Several vendors moved upmarket or were absorbed (Stack AI into Asana, Flowise into Workday then shut down, Relevance AI reportedly Enterprise-only, Vellum pivoting to a consumer assistant). There is less of an independent, developer-focused visual tool in the market than in 2024 and 2025.

### Gaps
- Flowise Cloud shutdown date: one third-party source claims 30 Nov 2026, but the official sunset page does not mention Flowise Cloud. Unverified.
- Whether Workday still ships a Flowise-based builder inside its own platform after the OSS wind-down: not found.
- Current Langflow Desktop Linux support: the official download page lists only macOS and Windows, and a generated `llms-full.txt` claiming Linux was judged unreliable.
- Relevance AI, Gumloop, Voiceflow and Botpress 2026 pricing: not verified from primary pricing pages (fetches not attempted, or reports conflicted).
- Vellum: whether the developer platform (Workflows SDK, evaluations, deployments) is still sold after the "Personal Intelligence" repositioning is unclear. The homepage no longer mentions it.
- Not researched here, possibly covered by other researchers: Microsoft Copilot Studio and Foundry, Google Agent Builder and Opal, Zapier Agents, Lindy, CrewAI Studio/AMP, Mastra.

## Canvas model: source of truth, export to real framework code, version control

### Takeaway
In every product reviewed, the canvas's own JSON/YAML/DSL graph is the source of truth, and it runs only on the vendor's runtime. None export to a mainstream agent framework, except OpenAI Agent Builder's lossy Agents SDK export, which is now being shut down. Vellum is the closest to "code and canvas in sync", but only for its own SDK. Version control is mostly bolted on: Langflow's `lfx` push/pull, n8n's overwrite-on-pull Git, Dify's DSL export and version history.

### Cited Findings
- **Langflow:** flows are JSON. The Flow DevOps SDK (`lfx`) stores them as JSON files in a `flows/` directory:
  - Commands: `lfx init`, `lfx pull`, `lfx push --env <name>`, `lfx status` (CREATED / UPDATED / Unchanged by hash of the flow JSON), `lfx validate`.
  - Environments: named environments (`local`, `staging`, `production`) live in `.lfx/environments.yaml`.
  - Scaffold: GitHub workflows (`langflow-push.yml`, `langflow-test.yml`, `langflow-validate.yml`) and `tests/test_flows.py`.
  - Not covered: the page does not describe exporting flows to Python code.

  ([Langflow Flow DevOps SDK docs](https://docs.langflow.org/flow-devops-sdk))
- **Langflow** `lfx run flow.json "input"` and `lfx serve flow.json` (FastAPI, POST /flows/{id}/run) run flow JSON statelessly, with no database or UI. Stateful operations such as saving flows, storing messages or managing users do not persist. Newer `lfx serve` builds accept a `.py` script as well. ([lfx overview](https://docs.langflow.org/lfx-overview); [lfx serve](https://docs.langflow.org/lfx-serve)) (search summary)
- **Langflow** 1.13 adds an audit log, but "This is an audit log, not version control". The release notes describe no git integration or Python code export. ([Langflow release notes](https://docs.langflow.org/release-notes))
- **Langflow (third-party):** its output "doesn't translate into production-ready framework code", and moving to a code framework is left to the team. ([Blck Alpaca comparison, third-party](https://blckalpaca.at/en/knowledge-base/ai-agents/ai-agent-frameworks-comparison/langflow-vs-flowise-vs-n8n)) (search summary)
- **n8n Git:**
  - Diff view: workflow diffs compare the instance with the latest version in the connected Git repo, with a JSON diff for modified nodes.
  - Not full version control: n8n says it "doesn't implement all Git functionality" and its source control should not be seen as full version control. Pull requests and merges happen outside n8n.
  - Pulls overwrite: a pull overwrites local changes not stored in Git, and n8n "can't detect conflicts on workflows". Pulling an active workflow briefly deactivates it.

  ([n8n source control docs](https://docs.n8n.io/administer/use-source-control-and-environments); [n8n compare versions](https://docs.n8n.io/administer/use-source-control-and-environments/compare-versions)) (search summary; partly from a docs mirror)
- **n8n Git and environments** are only on Business (€667/mo, self-hosted) and Enterprise. ([n8n pricing](https://n8n.io/pricing/))
- **Dify:** version control (publish history, restore into draft) is "only available for Chatflow and Workflow apps", and restoring replaces the current draft completely. ([Dify version control docs](https://docs.dify.ai/en/use-dify/build/version-control.md)) (search summary). Agent apps gained "Export Agent DSL" as YAML "to back up or version-control agent configurations" in 1.16.1, and 1.18.0 added "portable app packages" and the `difyctl` CLI. ([Dify releases](https://github.com/langgenius/dify/releases))
- **Vellum:** a CLI does bidirectional push/pull sync between the Vellum UI and Python SDK code, for its own MIT-licensed SDK. ([Vellum Workflows SDK docs](https://docs.vellum.ai/developers/workflows-sdk/introduction)) (search summary). A competitor claims GitHub can't natively track changes made in Vellum's visual editor. ([Activepieces, competitor, search summary](https://www.activepieces.com/blog/vellum-vs-open-source-automation-for-ai-workflows))
- **Rivet:** graphs saved as YAML files that can be committed and reviewed in git, and run via `@ironclad/rivet-core` in a TypeScript app. ([Rivet site](https://rivet.ironcladapp.com/)) (search summary)
- **Botpress ADK:** agents are TypeScript files, one per primitive, auto-discovered. This is code-first but deploys only to Botpress Cloud. ([Botpress ADK v2 docs](https://botpress.com/docs/adk-v2/get-started/introduction/))
- **OpenAI Agent Builder export:**
  - Forum users report consistent bugs in the TypeScript export (template string escaping, state typing, property naming). ([OpenAI community forum](https://community.openai.com/t/bugs-in-agent-builder-exported-code-typescript-template-string-escaping-state-typing-and-property-naming/1362119))
  - A forum commenter noted "Agents SDK is a little safer as you get the code; ChatKit unfortunately is only a Workflow ID". ([OpenAI community forum](https://community.openai.com/t/agentbuilder-a-novelty-or-a-tool/1361895)) (search summary)
  - The product's own replacement is the code-first Agents SDK. ([OpenAI deprecations page](https://developers.openai.com/api/docs/deprecations))

### Inferences
- None of the reviewed products renders a canvas over code written in mainstream frameworks (OpenAI Agents SDK, LangGraph, CrewAI and so on). Each canvas is a vendor graph format (Langflow JSON, n8n JSON, Dify DSL YAML, Rivet YAML, Vellum SDK). "The canvas is a view of real framework code in a normal git repo" therefore looks like an open, differentiated position for AK Studio. The closest analogues are Vellum (bidirectional, but proprietary SDK and now de-emphasised) and Botpress ADK (code-first, but Botpress Cloud only).
- The 2026 trend is canvas-first products adding code-ish escape hatches: Langflow `lfx`, Dify `difyctl` and DSL export, n8n Git. That confirms demand for git workflows. But their git stories are weak: overwrite-on-pull, no merge, diffs of large JSON blobs. AK Studio gets git, diffs, PR review and branching for free by keeping plain source files.
- The OpenAI export bugs show the risk of generating code from a canvas model in one direction. AK Studio's reverse direction (parse code into a view) avoids divergence but carries its own risk: hand-written code the canvas cannot represent. The spec should define behaviour for unrepresentable constructs.

### Gaps
- Whether Langflow Assistant or `lfx` can emit framework-native Python (for example LangChain/LangGraph code) from a flow: no evidence found either way.
- Sim's workflow storage format and git story: not found (README describes deployment versions and an MCP API, but not git or file export).
- Dify, Langflow and Sim merge/conflict semantics for concurrent edits: only Langflow 1.13 "concurrent editing checks" and Dify 1.14 real-time collaboration found. Git-level merge was not documented.

## Desktop or fully local operation, and deployment options

### Takeaway
Only three reviewed products ship a desktop app: Langflow Desktop (macOS and Windows, local), Sim Desktop (macOS only, a native shell over a cloud or self-hosted Sim server), and Rivet (Tauri desktop, now stale). None offers Linux desktop builds or deploys to customer clouds through Terraform. Deployment almost always means "run on our runtime": vendor cloud, Docker or Helm self-host, an API endpoint, or exposure as an MCP server.

### Cited Findings
- **Langflow Desktop:** macOS (Apple Silicon and Intel) and Windows x64. No Linux listed. Bundles dependencies so no Python setup is needed. In-app upgrades. ([Langflow download page](https://langflow.org/download); [Langflow release notes](https://docs.langflow.org/release-notes)) (download page via search summary)
- **Langflow deployment:** OSS Python package, Docker image (env file plus named volume), or Desktop ([Langflow 1.13 blog](https://langflow.org/blog/langflow-1-13)). Individual flows can be served headless with `lfx serve` as a FastAPI app ([lfx serve docs](https://docs.langflow.org/lfx-serve)). Flows can be served as MCP tools, with project-level MCP servers managed on the Projects page ([Langflow concepts: flows](https://docs.langflow.org/concepts-flows)) (search summary).
- **Sim Desktop:**
  - Platform: macOS 12+ only ("Use the web app on other platforms").
  - Connected, not local: it opens your Sim workspace from Sim Cloud or a self-hosted server.
  - Local features: browser tabs, a local terminal (tmux), read-only approved folders, and opt-in Computer Use (macOS 14+).
  - Data flow: content read locally is sent to "your Sim deployment and model".

  ([Sim Desktop docs](https://docs.sim.ai/desktop))
- **Sim deployment:** Sim Cloud, `npx sim-setup` self-hosting on Docker Compose (needs Node 20+ and Docker, 12GB+ RAM per the README setup prompt), a Kubernetes mode, and a Helm chart. Workflows deploy as APIs, chat interfaces or MCP tools (third-party). ([Sim README](https://github.com/simstudioai/sim); [Ry Walker research, third-party](https://rywalker.com/research/sim-ai))
- **Rivet:** a desktop app built on Tauri (`packages/app/src-tauri` in the repo), with the last app release in Aug 2025. ([GitHub API](https://github.com/Ironclad/rivet))
- **n8n:** n8n Cloud or self-hosted. The Business plan is "self-hosted only". ([n8n pricing](https://n8n.io/pricing/)) The MCP Server Trigger node exposes workflows as MCP tools for Claude Desktop or Cursor. ([n8n 2.30/2.31 release notes via newreleases.io](https://newreleases.io/project/github/n8n-io/n8n/release/n8n@2.31.0)) (search summary)
- **Dify:** Docker Compose self-host (an E2B variant compose file in 1.17.0), Dify Cloud, and Enterprise. Apps are exposed through Service APIs and OpenAPI (1.18.0). ([Dify releases](https://github.com/langgenius/dify/releases))
- **Botpress:** `adk dev` runs locally, but production deploys go only to Botpress Cloud. ([Botpress ADK v2 docs](https://botpress.com/docs/adk-v2/get-started/introduction/))
- **OpenAI Agent Builder:** workflows hosted on OpenAI and embedded via ChatKit by workflow ID. Hosted workflows go away at shutdown on 30 Nov 2026. ([OpenAI deprecations page](https://developers.openai.com/api/docs/deprecations); [Refonte Learning on shutdown lock-in, third-party](https://www.refontelearning.com/blog/openai-agent-builder-shutdown-vendor-lock-in)) (second source via search summary)

### Inferences
- AK Studio's desktop app on Windows, macOS and Linux would be the only cross-platform desktop option including Linux among the reviewed products. Langflow Desktop (no Linux) is the most direct desktop competitor, and it is a local runner for Langflow's own runtime.
- No reviewed product deploys the user's agent into the user's own AWS, Azure or GCP account through Terraform. They deploy onto their own runtime: cloud, Docker or Helm. "Deploy to one of six cloud targets with locally run Terraform" is a clear differentiator. It is also an expectation gap: competitors offer one-click hosted endpoints, which AK Studio Phase 1 will not.
- Sim Desktop's local terminal and computer-use features show desktop builders becoming coding-agent-like workspaces. That trend points toward AK Studio's "Build with AI drives Claude Code" approach.

### Gaps
- Rivet desktop platform list (macOS, Windows, Linux) was not verified for 2026.
- Whether Langflow Desktop can run fully offline with local models: not confirmed.
- No reviewed product was found exporting a deployable infrastructure-as-code package. A dedicated search was not run, so this is absence of evidence only.

## Testing, evaluation, tracing and debugging

### Takeaway
Tracing and per-node run inspection are standard. Structured evaluation is uneven:
- n8n has a built-in evaluations feature.
- Voiceflow has in-app evals and simulated personas.
- Botpress ADK has automated conversation tests.
- Langflow ships a pytest scaffold and OpenTelemetry.
- Dify focuses on tracing, now nested into Workflow Tools.

OpenAI deprecated its own Evals product in favour of Promptfoo.

### Cited Findings
- **Langflow:**
  - Tracing: 1.12 emits OpenTelemetry traces, metrics and logs about the Langflow service itself, to any OTLP backend (NewRelic and Instana named). ([Langflow 1.12 blog](https://langflow.org/blog/langflow-1-12))
  - Testing: the `lfx` scaffold includes `tests/test_flows.py` with a `flow_runner` fixture, a `langflow-test.yml` CI workflow, and `lfx validate`. ([Langflow Flow DevOps SDK docs](https://docs.langflow.org/flow-devops-sdk))
- **Dify:**
  - 1.19.0: "nested workflow tracing to your observability tools". It follows a workflow into the Workflow Tools it calls, inspecting steps and keeping LLM context alongside the execution tree. ([Dify 1.19.0](https://github.com/langgenius/dify/releases/tag/1.19.0))
  - 1.16.1: Workflow Node Locator (click a node_id in run logs to highlight it on canvas) and Knowledge Tracing. ([Dify releases](https://github.com/langgenius/dify/releases))
  - Dify markets debugging and observability as core platform capabilities. ([VentureBeat / BusinessWire](https://venturebeat.com/business/dify-raises-30-million-series-pre-a-to-power-enterprise-grade-agentic-workflows))
- **n8n:**
  - Evaluations: lets users test prompt or model changes by running inputs and checking outputs against custom metrics (third-party description).
  - Later releases: webhook notifications for evaluation results (2.6.0) and a multi-config evaluations backend (2.21.0).

  ([n8n evaluations blog via Plushcap, search summary](https://www.plushcap.com/content/n8n/blog/introducing-evaluations-for-ai-workflows); [n8n 2.21.0](https://newreleases.io/project/github/n8n-io/n8n/release/n8n@2.21.0))
- **n8n Insights** retention scales by plan: 7 days on Pro, 30 on Business, 365 on Enterprise. ([n8n pricing](https://n8n.io/pricing/))
- **Voiceflow V4:** "In-app evaluations let you test models against your own conversations before going live". The Observability Suite covers Transcripts, Evaluations and Analytics ([Voiceflow V4 launch](https://www.voiceflow.com/stories/everything-we-launched-v4)). Simulated-persona testing was added Jun 2026 and environment protection Jul 2026 ([Voiceflow changelog](https://www.voiceflow.com/docs/changelog), search summary).
- **Botpress ADK:** evals are "Automated conversation tests". The navigation lists logs and traces, analytics and an "Agent Map". ([Botpress ADK v2 docs](https://botpress.com/docs/adk-v2/get-started/introduction/))
- **Relevance AI Invent** reportedly generates evals automatically along with agents and tools (third-party). ([11x guide, third-party](https://www.11x.ai/guides/relevance-ai-pricing))
- **Sim:** "Monitor runs, logs, schedules, and workflow activity", with audit logs on Enterprise. ([Sim README](https://github.com/simstudioai/sim))
- **OpenAI Evals** (dashboard, API, graders): "Read-only", shutdown 30 Nov 2026, migration to Promptfoo. ([OpenAI deprecations page](https://developers.openai.com/api/docs/deprecations))
- **Third-party practitioner view:** production systems needing version control and testing tend to move from visual tools to code, and visual builders suit prototyping. ([ZenML, third-party, search summary](https://www.zenml.io/blog/langflow-alternatives))

### Inferences
- AK Studio's planned "local run with chat, trace view and test runs" is at parity with the stronger competitors. Linking plain-language business rules to the code, config and tests that enforce them was not found in any reviewed product, so it is a potential differentiator (absence of evidence, not a targeted search).
- Competitors' tests live in vendor-specific eval UIs or scaffolds. AK's test framework runs as ordinary code in the repo, so it fits CI naturally. Langflow's `lfx` CI scaffold shows competitors see the same need.

### Gaps
- Step-through debugging (breakpoints, pause and resume per node) was not confirmed for any product in 2026. Rivet historically had graph-level execution visualisation, but no 2026 evidence was found.
- A/B testing of prompts or models in production: not found for any reviewed product.
- Dify's built-in evaluation datasets (as opposed to tracing): not found.

## AI-assisted building (describe-to-build copilots)

### Takeaway
Describe-to-build is now table stakes:
- In-product copilots: Langflow Assistant, the n8n AI Workflow Builder, Dify's agent-building agent, Sim's Copilot and Mothership, Vellum Agent Builder, Relevance AI Invent, the Voiceflow Atlas beta.
- The newer pattern is exposing the platform as an MCP server so external coding agents (Claude Code, Codex, Cursor) can build and run flows. n8n, Sim and Langflow all did this in 2026.

### Cited Findings
- **Langflow Assistant:** can generate components and "create a flow from a single prompt", presenting a diagram of the proposed flow before approval. Building a flow "reads and writes the entire Langflow graph on every turn", which can use significantly more tokens. ([Langflow Assistant docs](https://docs.langflow.org/langflow-assistant)) (search summary)
- **Langflow `lfx-mcp`** (`uvx --from lfx lfx-mcp`): lets an external MCP client (for example Claude Code) hand an instruction to Langflow Assistant via a `run_assistant` tool, or create flows from starter projects. ([lfx-mcp docs](https://docs.langflow.org/lfx-mcp)) (search summary)
- **n8n AI Workflow Builder:**
  - Creates, refines and debugs workflows from natural language, handling node selection, placement and configuration.
  - Each create or modify message costs one credit, and failed generations are not charged.
  - It sends prompts, node definitions, parameters, connections, the current workflow and any loaded mock execution data to the LLM, but not credentials or past executions.

  ([n8n AI Workflow Builder docs](https://docs.n8n.io/advanced-ai/ai-workflow-builder/))
- **n8n instance-level MCP server:** a built-in MCP server (endpoint `/mcp-server/http`) that Claude Code connects to over streamable HTTP with OAuth, to search, run and build workflows. One guide says building over MCP requires n8n 2.13.0+, and access is not scoped per MCP client. ([MindStudio, third-party](https://www.mindstudio.ai/blog/n8n-mcp-server-claude-code-workflows)) (search summary). A practitioner post is titled "Claude can now build n8n workflows: the hard part is reviewing them". ([Medium, third-party](https://medium.com/@creativeaininja/claude-can-now-build-n8n-workflows-the-hard-part-is-reviewing-them-0355bee76eb5)) (title only, via search)
- **Sim:**
  - MCP: Claude, Claude Code, Codex or any MCP client can connect to `https://mcp.sim.ai/mcp` to "manage workspaces, run and deploy workflows, and work with tables, knowledge bases, files, and logs".
  - Building: "Build agents visually, conversationally, or with code".
  - The enterprise tier includes an "on-prem Copilot" (search summary).

  ([Sim README](https://github.com/simstudioai/sim); [Sim funding coverage](https://startuphub.ai/news/sim-lands-7m-for-its-open-source-ai-workflow-builder))
- **Dify 1.16.0:** "We also provide an agent that helps you build Dify Agents. Through conversation, it can configure the Linux sandbox environment, install required" packages. ([Dify 1.16.0](https://github.com/langgenius/dify/releases/tag/1.16.0))
- **Vellum Agent Builder:** generates Python SDK code plus a visual graph from a description. ([Vellum Agent Builder blog](https://www.vellum.ai/blog/introducing-vellum-copilot)) (search summary)
- **Relevance AI Invent:** a plain-language agent builder (2025, possibly outdated), with Invent 2.0 later. ([TechCrunch](https://techcrunch.com/2025/05/06/relevance-ai-raises-24m-series-b-to-help-anyone-build-teams-of-ai-agents/); [Webull news item](https://www.webull.com/news/15661795987047424))
- **Voiceflow:** Atlas copilot beta, Aug 2026. ([Voiceflow changelog](https://www.voiceflow.com/docs/changelog)) (search summary)

### Inferences
- Competitors' copilots edit the vendor's graph model, either with their own embedded LLM (credit-metered in n8n) or by letting an external coding agent call an MCP API. AK Studio drives the user's own Claude Code against real files, with approval cards and per-change accept/revert. That is architecturally closer to what Flowise's team said developers were moving to. It also sidesteps credit metering, because the user brings their own Claude Code subscription.
- The "hard part is reviewing them" theme matches AK Studio's per-change accept/revert and canvas-as-view. Reviewing a diff of real code plus seeing it on a canvas is a stronger review story than reviewing an LLM-mutated JSON graph.

### Gaps
- Whether any competitor's copilot offers per-change accept/revert or approval cards comparable to AK Studio's: not found. Langflow Assistant shows a proposed diagram before approval, the nearest equivalent.
- Gumloop's AI flow-building assistant: not confirmed from fetched sources.

## Integrations breadth: MCP, channels, knowledge/RAG, guardrails, human-in-the-loop

### Takeaway
Competitors lead heavily on integration breadth: n8n's node library, Sim's 270+ integrations and 5,400+ actions, Gumloop's "several hundred" connectors. MCP client and server support is nearly universal. HITL is now explicit in Dify and n8n. Messaging channels are strongest in the conversational platforms (Botpress, Voiceflow) and Gumloop (Slack, Teams, email). Guardrails are mostly prompt-level or delegated to providers.

### Cited Findings
- **Sim:** 270+ integrations (5,400+ actions, 520+ triggers), including Slack, Notion, HubSpot, Salesforce and databases. Knowledge bases, Tables and Files are built in. ([Sim README](https://github.com/simstudioai/sim))
- **Dify:**
  - HITL: Human-in-the-Loop in 1.13.0, a HITL Service API in 1.14.0, markdown HITL emails in 1.13.1. ([Dify releases](https://github.com/langgenius/dify/releases))
  - Knowledge and agent features: dataset-scoped knowledge-base API keys (1.17.1), an opt-in Agent Knowledge Base (1.18.0), E2B sandboxes and Skill management (1.17.0). ([Dify releases](https://github.com/langgenius/dify/releases))
- **Langflow:**
  - Connections: 1.13 adds reusable OAuth "Connections" for Google Workspace, Microsoft 365 and Slack. These are tool connections, not chat channels.
  - Knowledge: local Knowledge and Memory moved to SQLite.

  ([Langflow release notes](https://docs.langflow.org/release-notes))
- **Langflow MCP:** flows can be served as MCP tools, and projects have MCP servers. ([Langflow concepts: flows](https://docs.langflow.org/concepts-flows)) (search summary)
- **n8n:** MCP Server Trigger node, with 2026 fixes for idle-session eviction (2.30.0) and queue-mode persistence (2.31.0). Separately, there is an instance-level MCP server. ([n8n 2.31.0 notes](https://newreleases.io/project/github/n8n-io/n8n/release/n8n@2.31.0); [MindStudio, third-party](https://www.mindstudio.ai/blog/n8n-mcp-server-claude-code-workflows)) (search summary)
- **Voiceflow V4:** MCP as a tool type, and guardrails defined in the global prompt. ([Voiceflow V4 launch](https://www.voiceflow.com/stories/everything-we-launched-v4))
- **Botpress:** the ADK abstracts "hosting, scaling, and channel delivery", with knowledge, tables and triggers as primitives. ([Botpress ADK v2 docs](https://botpress.com/docs/adk-v2/get-started/introduction/))
- **Gumloop:**
  - Channels: Gumloop Agents deploy across workplace tools including Slack, Teams and email. ([IT Brief, search summary](https://itbrief.co.uk/story/gumloop-raises-usd-50m-to-scale-workplace-ai-agents))
  - Governance: Gumstack sets per-department tool-access policies and handles secrets management. ([SiliconANGLE](https://siliconangle.com/2026/03/13/gumloop-reels-50m-ai-automation-platform/))
  - Gumstack also logs and audits tool calls from Claude Code, ChatGPT and Cursor. ([IT Brief, search summary](https://itbrief.co.uk/story/gumloop-raises-usd-50m-to-scale-workplace-ai-agents))
- **Stack AI's** value to Asana was connectors into ERP, CRM and ITSM systems. ([The Next Web](https://thenextweb.com/news/asana-acquires-stack-ai-agent-builder-saas))

### Inferences
- AK (the runtime) already covers channels (Slack, WhatsApp, Messenger, Instagram, Telegram, Teams, Gmail), guardrail providers, knowledge bases and memory in code. AK Studio Phase 1 deliberately leaves out dedicated config pages for tools/MCP, knowledge, guardrails and memory, so those surface only through the canvas, the Code tab and Config-as-forms. Users comparing it with Sim, n8n or Dify will see far fewer point-and-click integrations. Positioning should stress "any Python library or MCP server, in code" rather than compete on connector counts.
- Guardrails as a first-class canvas object (AK Studio's plan) is stronger than Voiceflow's prompt-level guardrails. No reviewed visual builder was found with a dedicated guardrail-provider node (absence of evidence).

### Gaps
- WhatsApp and web-widget channel support was not verified for each product (Dify web app embed, Langflow embedded chat, Botpress and Voiceflow channel lists).
- Dedicated guardrail nodes in Dify, n8n or Langflow (for example moderation or PII nodes) were not researched in 2026 docs.

## Practitioner criticism and market signals relevant to "canvas as a view of real code"

### Takeaway
The strongest 2026 evidence is behavioural, not anecdotal. Flowise's makers shut it down, saying low-code "quickly hits the limit when it comes to complexity" and that developers are moving to coding agents. OpenAI retired its visual Agent Builder in favour of the code-first Agents SDK. LangChain's CEO publicly argued visual workflow builders are "getting squeezed from both directions". Recurring practitioner criticisms are spaghetti graphs at scale, weak git and merge, hard-to-test flows, lossy or no export to real code, and vendor lock-in when a hosted builder shuts down.

### Cited Findings
- **Flowise team:** "The typical rigid workflow low-code approach quickly hits the limit when it comes to complexity". Developers "are increasingly relying on new coding agents". ([GitHub discussion #6727](https://github.com/FlowiseAI/Flowise/discussions/6727); [Flowise sunset page](https://flowiseai.com/sunset))
- **Harrison Chase** (LangChain, 7 Oct 2025, possibly outdated but still cited in 2026 coverage):
  - "I do not think the world needs yet another workflow builder."
  - "The issue with no code workflow builders are that I think they are getting squeezed from both directions."
  - Beyond some complexity "you end up with a mess of nodes and edges that you need to manage in the UI."
  - He proposes that high-complexity work belongs in code workflows (LangGraph), that simple agents should be no-code prompt plus tools, and that cheaper code generation will push complex work to code.

  ([LangChain blog](https://www.langchain.com/blog/not-another-workflow-builder))
- **OpenAI Agent Builder** deprecated after about 8 months (launched Oct 2025, notice Jun 2026, shutdown 30 Nov 2026), pointing users to the Agents SDK. ([OpenAI deprecations page](https://developers.openai.com/api/docs/deprecations)) Commentary frames it as a vendor lock-in warning: hosted workflows disappear, and ChatKit embeds reference only a workflow ID. ([Refonte Learning, third-party, search summary](https://www.refontelearning.com/blog/openai-agent-builder-shutdown-vendor-lock-in); [OpenAI community forum, search summary](https://community.openai.com/t/agentbuilder-a-novelty-or-a-tool/1361895))
- **Spaghetti and maintainability (third-party):** heavily tangled visual workflows end up "harder to maintain than actual code", and "restructuring a complex graph is genuinely painful". ([ZenML, third-party](https://www.zenml.io/blog/langflow-alternatives); [Blck Alpaca, third-party](https://blckalpaca.at/en/knowledge-base/ai-agents/ai-agent-frameworks-comparison/langflow-vs-flowise-vs-n8n)) (search summaries)
- **Code-node escape hatch (third-party):** when logic gets bespoke, developers push heavy computation into n8n Code nodes, and the visual builder's advantage shrinks. ([n8nlab, third-party, search summary](https://n8nlab.io/blog/langgraph-vs-n8n))
- **Ownership trade-off:** a 2026 explainer frames no-code builders around what you give up versus code (ownership, portability). ([AgentsIndex, third-party, search summary](https://agentsindex.ai/blog/no-code-ai-agent-builders-ownership-tradeoff))
- **Version control limits:** n8n states its source control should not be viewed as full version control, cannot detect workflow conflicts, and pulls overwrite unsaved local changes. ([n8n source control docs](https://docs.n8n.io/administer/use-source-control-and-environments)) (search summary)
- **Counter-signal:** n8n's valuation doubled to $5.2B in 2026 with SAP embedding it ([Highland Europe](https://www.highlandeurope.com/n8n-valuation-doubles-to-5-2bn-as-sap-makes-strategic-investment-and-plans-to-embed-the-ai-platform-into-joule-studio/)). Dify raised $30M ([VentureBeat](https://venturebeat.com/business/dify-raises-30-million-series-pre-a-to-power-enterprise-grade-agentic-workflows)), and Gumloop $50M from Benchmark ([SiliconANGLE](https://siliconangle.com/2026/03/13/gumloop-reels-50m-ai-automation-platform/)). Commentary argues visual builders survive in operational automation and regulated workflows ([Flowise shutdown coverage, third-party, search summary](https://agentmarketcap.ai/blog/2026/07/30/flowise-sunset-low-code-agent-builders)).

### Inferences
- The evidence favours AK Studio's design choice. The failure modes practitioners cite (spaghetti at scale, weak git, no real-code export, lock-in) all come from the canvas being a separate proprietary model. A canvas derived from real framework files in git avoids lock-in and git problems by construction. Pairing it with Claude Code matches where Flowise and OpenAI said users were going.
- The risk sits on the other side of the squeeze. The commercial winners (n8n, Dify, Gumloop, Sim) win on integrations, hosted runtimes and non-developer accessibility. AK Studio Phase 1 has no sign-in, teams, hosted runtime or dashboards, so it should be pitched at developers and technical teams who would otherwise write framework code by hand. It is not a fit for business users choosing n8n.
- "Spaghetti at scale" can still affect AK Studio, because a view can be as cluttered as an editor. Grouping, collapsing and filtering by agent or channel will matter for large projects.

### Gaps
- Reddit (r/LangChain, r/AI_Agents, r/n8n) and Hacker News threads could not be retrieved directly: the search tool blocked reddit.com and returned no HN hits. Practitioner sentiment above therefore comes from vendor statements, an OpenAI forum and third-party blogs rather than first-hand Reddit or HN threads.
- No quantitative data (surveys, churn rates) was found on teams migrating from visual builders to code in 2026.
