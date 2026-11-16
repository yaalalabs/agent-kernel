# Table-stakes expectations for an agent development studio (testing, evaluation, tracing, deployment, interoperability), November 2026

Research date: 2026-11-16. Sources are a mix of vendor docs (primary) and third-party blogs (marked "third-party"). Where a source predates 2026 it is flagged as possibly outdated. "AK Studio" means the planned Phase 1 Electron app described in the brief; nothing here was checked against AK code.

## 1. Local debugging and tracing: what do the leading studios offer, and is OTel GenAI the standard?

### Takeaway
A local "run the agent, chat with it, see every model call and tool call as a span tree with latency and tokens" loop is now table stakes and is shipped by every major vendor dev tool (LangSmith Studio, ADK web, Mastra Studio, Foundry Toolkit Agent Inspector, AgentCore Agent Inspector). The differentiators above that floor are time travel and state editing (LangGraph only), replaying a single span in a prompt playground (Phoenix, Langfuse), breakpoints in the agent code (Foundry Toolkit), and per-span token and cost figures. OpenTelemetry GenAI semantic conventions are the de facto direction for span shape, but as of November 2026 every GenAI surface is still at "Development" status, so "OTel GenAI compatible" means "emits roughly the right span names and is ready for churn", not "conforms to a stable standard".

### Cited Findings

Local run loop (the floor)
- LangSmith Studio is a free visual interface for developing and testing agents from the local machine; it connects to a locally running Agent Server and shows prompts sent to the model, tool calls and results, intermediate state and final output ([LangChain docs: Studio](https://docs.langchain.com/oss/python/langchain/studio)).
- `langgraph dev` runs a lightweight in-memory Agent Server with no Docker, in watch mode with auto-restart on code changes, reachable at `http://127.0.0.1:2024` for API and Studio; Studio requires a LangSmith API key, and setting `LANGSMITH_TRACING=false` keeps data local ([LangChain docs: local server](https://docs.langchain.com/langsmith/local-server)). `langgraph up` runs a Docker stack that mirrors production ([same](https://docs.langchain.com/langsmith/local-server)).
- Google ADK's `adk web` dev UI has separate Events, Tracing, Artifacts and Evaluations panels ([google/adk-web GitHub](https://github.com/google/adk-web)); ADK docs say local agent behaviour is inspected via the Trace view in the ADK web UI ([adk.dev Cloud Trace](https://adk.dev/integrations/cloud-trace/)).
- Mastra Studio (localhost:4111) lets developers test agents, workflows and tools locally; its Observability tab shows traces highlighting model calls and tool use, and scorers can be run against historical traces inside Studio ([Mastra docs: Studio](https://mastra.ai/docs/getting-started/studio); [Mastra docs: evals overview](https://mastra.ai/docs/evals/overview)).
- Microsoft Foundry Toolkit for VS Code (GA in 2026) ships an Agent Inspector that sends requests to a local agent, supports breakpoints and step-through debugging in agent code (F5 launches it), has an Events tab of parsed Responses events with search and filter, a Tools tab grouping tool calls by run, an Overview tab with a latency waterfall and run timeline, a Tokens tab with reported token usage, workflow graph visualization for Microsoft Agent Framework workflows (explicitly not for LangGraph), MCP tool approval UI (Approve, Deny, Approve all, Deny all), OAuth consent handling, JSONL export of events, and a "prepare failure prompt for GitHub Copilot Chat" action ([VS Code docs: Agent Inspector](https://code.visualstudio.com/docs/intelligentapps/agent-inspector); [Foundry Toolkit GA post](https://techcommunity.microsoft.com/blog/azuredevcommunityblog/microsoft-foundry-toolkit-for-vs-code-is-now-generally-available/4511831)).
- The same Foundry Toolkit runs a local OTLP collector; apps export telemetry to it and developers compare recorded model, tool and agent spans; the docs stress that live Inspector protocol events and stored OTLP traces are separate data sources ([VS Code docs: Tracing in Foundry Toolkit](https://code.visualstudio.com/docs/intelligentapps/tracing)).
- AWS replaced the Python AgentCore starter toolkit with a Node.js AgentCore CLI (`npm install -g @aws/agentcore`); `agentcore dev` runs the agent locally with uv dependency resolution and uvicorn hot reload, and `agentcore dev --mode browser` opens an "Agent Inspector" UI ([AWS docs: get started with AgentCore CLI](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/agentcore-get-started-cli.html); [aws/agentcore-cli README](https://github.com/aws/agentcore-cli)). The README does not describe the Inspector's trace features in detail.

Advanced debugging (above the floor)
- LangGraph time travel has two operations, replay and fork; a fork is created by `update_state` on a prior checkpoint and then invoking with `None`; in Studio's Graph mode the user picks "edit node state", changes a node's output and clicks "fork"; editing a human message creates a forked conversation; interrupts re-trigger during time travel; you cannot time travel to a point between nodes inside a default subgraph ([LangChain docs: HITL and time travel in Studio](https://docs.langchain.com/langsmith/human-in-the-loop-time-travel); [LangGraph docs: use time travel](https://docs.langchain.com/oss/python/langgraph/use-time-travel)). This depends on LangGraph's checkpointer, so it is framework-specific.
- Arize Phoenix "Span Replay" loads LLM spans stored in Phoenix into the Prompt Playground to re-run one step of a multi-step chain with modifications and compare prompts and models side by side ([Phoenix docs: Span Replay](https://arize.com/docs/phoenix/prompt-engineering/overview-prompts/span-replay)).
- Langfuse's trace view shows token counts, timing and cost per node, with a Tree and a Timeline view; costs are computed automatically from model name plus token counts ([Langfuse docs overview](https://langfuse.com/docs)). Third-party listings claim Langfuse lets users jump from a trace directly into the playground to re-run real inputs; I did not confirm this on an official page ([third-party: Respan](https://www.respan.ai/articles/langfuse-alternatives); [third-party: inference.net](https://inference.net/content/langfuse-alternatives/)).
- W&B Weave now models sessions, turns, steps, tools and sub-agents as first-class concepts in agent tracing, and offers a Playground for testing models against production traces ([W&B Weave product page](https://site.wandb.ai/weave/); [W&B traces page](https://site.wandb.ai/traces/)).

OpenTelemetry GenAI status
- As of an article updated 3 November 2026: "Every GenAI-specific surface remains in Development status"; the conventions moved to a dedicated repository in 2026 (core v1.42.0 deprecated and moved all `gen_ai.*` content); that repo has no tagged releases, so you can only pin a commit ([third-party: John Hodge, Nov 2026 update](https://john-hodge.com/blog/opentelemetry-genai-semantic-conventions/)). A separate analysis titles itself "0 of 63 are stable" ([third-party: Particula](https://particula.tech/blog/opentelemetry-genai-semantic-conventions-stable)).
- Agent span names in the conventions include `invoke_agent` (CLIENT for out-of-process agents, INTERNAL for in-process), `create_agent`, `execute_tool`, `invoke_workflow`, `plan`, `retrieval` and `memory`; token attributes moved from `prompt_tokens`/`completion_tokens` to `gen_ai.usage.input_tokens`/`output_tokens` (v1.27.0), cache attributes arrived in v1.40.0, and `gen_ai.client.token.usage` was removed on main in September 2026; content capture is governed by `OTEL_INSTRUMENTATION_GENAI_CAPTURE_CONTENT` defaulting to `NO_CONTENT`; `OTEL_SEMCONV_STABILITY_OPT_IN=gen_ai_latest_experimental` selects newer conventions ([third-party: John Hodge](https://john-hodge.com/blog/opentelemetry-genai-semantic-conventions/)).
- Framework support is uneven: Pydantic AI emits the current structured format by default; Strands defaults to v1.36-era output; Vercel AI SDK 7 uses `gen_ai.provider.name`; LangSmith's OTel ingestion accepts both generations; the OpenAI Agents SDK "does not emit the OpenTelemetry (OTel) GenAI conventions natively" ([third-party: John Hodge](https://john-hodge.com/blog/opentelemetry-genai-semantic-conventions/)).
- Coding agents (VS Code Copilot, OpenAI Codex, Claude Code in beta) reportedly already emit GenAI-convention traces ([third-party: DEV Community, azena-ai](https://dev.to/azena-ai/opentelemetrys-genai-semantic-conventions-are-not-stable-yet-heres-what-actually-shipped-in-2026-3mke)).
- MCP semantic conventions were folded into the same GenAI repo ([third-party: DEV Community, azena-ai](https://dev.to/azena-ai/opentelemetrys-genai-semantic-conventions-are-not-stable-yet-heres-what-actually-shipped-in-2026-3mke)).

Practitioner adoption
- LangChain's State of Agent Engineering survey (fielded 18 Nov to 2 Dec 2025, 1,340 responses; vendor-run, skews to tech and small companies) found 89% have some observability (94% among teams with agents in production) and 62% have detailed step and tool-call tracing (71.5% among production teams) ([LangChain: State of Agent Engineering](https://www.langchain.com/state-of-agent-engineering)). Data is from late 2025, so possibly understates 2026 adoption.

### Inferences
- Floor that AK Studio Phase 1 meets: start local server, chat, see a trace, approve or deny HITL pauses. Every competitor dev tool has this, so it is necessary but not differentiating.
- Where Phase 1 misses the bar:
  - Run-level timing only for non-streaming frameworks is below the floor; every competitor shows per-tool-call and per-model-call spans. Building the trace from the stream rather than from OTel spans is the weak point. AK already wires OpenLLMetry and Logfire, so a local OTLP receiver in Studio (the Foundry Toolkit pattern) would give span-level detail for all eight frameworks independent of streaming support.
  - No per-span token and cost display (Langfuse, Foundry Inspector Tokens tab, LangSmith all show it).
  - No "replay this model call in a playground" (Phoenix, Langfuse, Weave).
  - No time travel, fork or state edit. This is a LangGraph-only feature, so its absence is defensible for a framework-neutral tool, but users coming from LangGraph Studio will notice.
  - No breakpoints in agent code; the Foundry Toolkit sets this bar by piggybacking on the IDE debugger, which an Electron app cannot easily match.
- Where Phase 1 exceeds: one UI over eight frameworks. LangGraph Studio, ADK web, Mastra Studio and Foundry Inspector are each tied to their own framework or protocol (Foundry Inspector explicitly lacks graph view for LangGraph).
- Recommendation implied by the evidence: emit and consume OTel GenAI span names (`invoke_agent`, `execute_tool`, `chat`) behind a version flag, because attribute names are still churning.

### Gaps
- I did not find official docs confirming Langfuse's "open in playground from span" action; only third-party listings.
- Pydantic Logfire's local or dev-time trace UI and OpenAI's Traces dashboard features were not researched in depth.
- I could not confirm which observability backends (Langfuse, Phoenix, Datadog, Logfire, Braintrust) fully support the latest GenAI conventions; the main source did not cover them.
- AgentCore Agent Inspector's exact feature list (trace view, HITL) is not documented in the README I read.

## 2. Evaluation: what is now expected and who leads?

### Takeaway
By late 2026 the expected evaluation loop is: build datasets (often from real traces or saved sessions), score with built-in and custom LLM-as-judge evaluators plus code checks, run experiments and compare them side by side against a baseline, simulate multi-turn users, run the same suite in CI as a regression gate, and sample live traffic for online evals. LangSmith, Braintrust, Langfuse, Confident AI/DeepEval, Logfire, Weave and the cloud platforms (AgentCore Evaluations, ADK/Vertex) all ship most of this. OpenAI exited the hosted evals market in 2026 and pointed users to Promptfoo, which reinforces code-first, open-source evals as the norm.

### Cited Findings

Adoption baseline
- 52.4% of respondents run offline evals on test sets, 37.3% run online evals (44.8% among production teams), 29.5% do not evaluate at all; human review is used by 59.8% and LLM-as-judge by 53.3%; quality is the top production blocker at 32%, latency second at 20% ([LangChain: State of Agent Engineering](https://www.langchain.com/state-of-agent-engineering), data from Nov to Dec 2025).

Datasets from traces or sessions
- ADK web's Eval tab: "Create Evaluation Set", then "Add current session to the evalset", then "Run Evaluation" with adjustable metrics; failing cases show actual vs expected and which score fell below threshold ([Google codelab: Evaluating Agents with ADK](https://codelabs.developers.google.com/adk-eval/instructions)).
- Logfire datasets are reusable collections of test cases created in the web UI or pushed from code with `push_dataset(...)`, and local YAML datasets also show in the Evals tab ([Pydantic Logfire docs: evaluate](https://pydantic.dev/docs/logfire/evaluate/overview/)).
- OpenAI AgentKit (October 2025) shipped datasets, trace grading, automated prompt optimization and third-party model support in Evals ([OpenAI: Introducing AgentKit](https://openai.com/index/introducing-agentkit/)); see the deprecation finding below.

Experiments and side-by-side comparison
- Braintrust stores each run as an experiment, aligns test cases across experiments, shows per-row score deltas against a baseline and classifies results as improvement, regression, tradeoff or tie ([Braintrust docs: run experiments](https://www.braintrust.dev/docs/guides/experiments/run)).
- Confident AI documents comparing two or more test runs side by side to spot regressions ([Confident AI docs: multi-turn evals](https://www.confident-ai.com/docs/llm-evaluation/no-code-evals/multi-turn-evals); vendor claim).
- Mastra supports running experiments with scorers to compare quality across prompts, models or code changes ([Mastra docs: evals overview](https://mastra.ai/docs/evals/overview)).

Multi-turn and simulated users
- LangSmith documents simulating multi-turn interactions with a simulated user (one message per turn) via the open-source `openevals` package, runnable inside LangSmith experiments ([LangChain docs: multi-turn simulation](https://docs.langchain.com/langsmith/multi-turn-simulation)); LangSmith also launched thread-level Multi-turn Evals and an Insights Agent that clusters usage patterns ([LangChain blog](https://blog.langchain.com/insights-agent-multiturn-evals-langsmith/)).
- Google ADK added User Simulation: each scenario is a starting prompt plus a natural-language conversation plan (a goal, not a script), with an LLM-backed simulator, a turn budget (`max_allowed_invocations`) and rubric judges including `rubric_based_multi_turn_trajectory_quality_v1` ([Google Developers Blog: User Simulation in ADK Evaluation](https://developers.googleblog.com/announcing-user-simulation-in-adk-evaluation/)); live and voice agents can be evaluated with an `llm_audio` simulator ([adk.dev: evaluation for live agents](https://adk.dev/live/evaluation/)).
- DeepEval ships an open-source conversation simulator for multi-turn evaluation without hand-coded turns ([DeepEval blog](https://deepeval.com/blog/how-to-evaluate-conversational-agent)).

CI regression gating
- AgentCore Evaluations (GA 31 March 2026) has 13 built-in evaluators (response quality, safety, task completion, tool usage), online evaluation by sampling live traces, and on-demand evaluation "supporting regression testing in CI/CD pipelines"; custom LLM-judge evaluators and code evaluators in Python or JavaScript via Lambda; ground truth via reference answers, session-level behavioral assertions and expected tool sequences ([AWS What's New](https://aws.amazon.com/about-aws/whats-new/2026/03/agentcore-evaluations-generally-available)). Built-in evaluators are referenced as `Builtin.<Name>` and cannot be modified ([AWS docs: built-in evaluators](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/built-in-evaluators-overview.html)).
- Braintrust provides `braintrustdata/eval-action` for running evals on pull requests and `bt eval` for other CI systems ([Braintrust article: eval pipeline with GitHub Actions](https://www.braintrust.dev/articles/llm-eval-pipeline-github-actions)); Braintrust marketing says merges block when scores drop below threshold, which a third-party comparison disputes (see Gaps).
- DeepEval is pytest-based (`deepeval test run`) and works offline without an account, with optional push to Confident AI dashboards ([third-party: mer.vin, June 2026](https://mer.vin/2026/06/deepeval-explained-pytest-style-llm-evals-for-agents-rag-and-ci-cd/?amp=1)).
- A competitor (Braintrust) claims W&B Weave has no native CI integration that blocks deployments on eval results ([Braintrust: vs W&B](https://www.braintrust.dev/articles/braintrust-vs-weights-and-biases); competitor claim).

Online evals
- Pydantic Logfire added online evals in April 2026 (sampled production scoring with configurable judges, built on OpenTelemetry), with results on a Live Monitoring page ([Pydantic: online evals in Logfire](https://pydantic.dev/articles/online-evals-pydantic-logfire.md)).
- W&B Weave has online evals in preview to score live traces, plus an Evaluation Playground, annotation queues and monitors ([W&B Weave product page](https://site.wandb.ai/weave/)).
- AgentCore online evaluation results land in the CloudWatch-backed AgentCore Observability dashboard ([AWS What's New](https://aws.amazon.com/about-aws/whats-new/2026/03/agentcore-evaluations-generally-available)).

OpenAI exits hosted evals
- OpenAI's deprecations page lists, on 3 June 2026, the deprecation of Agent Builder and the Evals platform; existing evals become read-only on 31 October 2026 and Agent Builder shuts down 30 November 2026; migration guidance points to the Agents SDK or ChatGPT Workspace Agents, and for Evals to Promptfoo ([OpenAI API docs: Deprecations](https://developers.openai.com/api/docs/deprecations)). The AgentKit announcement page carries an "Update on June 3, 2026: OpenAI is winding down the Agent Builder and Evals products" note ([OpenAI: Introducing AgentKit](https://openai.com/index/introducing-agentkit/); page returned 403 to my fetch, quote taken from search snippet).
- OpenAI announced on 9 March 2026 it is acquiring Promptfoo, integrating it into OpenAI Frontier for continuous security evaluation; Promptfoo stays open source under its current license ([OpenAI: to acquire Promptfoo](https://openai.com/blog/openai-to-acquire-promptfoo); [TechCrunch](https://www.techcrunch.com/2026/03/09/openai-acquires-promptfoo-to-secure-its-ai-agents/)).

### Inferences
- Bar for an agent studio's eval surface: (a) save a session as a test case, (b) per-metric scores with thresholds, (c) run history and side-by-side comparison against a baseline, (d) simulated multi-turn users, (e) the same suite runnable headless in CI, (f) online sampling once deployed.
- AK Studio Phase 1 meets (a) directly (save chat scenarios as test cases mirrors ADK's "Add current session to evalset") and meets (e) indirectly because AK's test framework is plain pytest and already runs in CI outside Studio.
- AK Studio Phase 1 misses (b) if it only shows pass/fail squares without the judge scores and reasons; misses (c) because evaluation history is deferred (Braintrust, Confident AI, LangSmith, Mastra all lead with comparison); misses (d) unless AK's test framework already has a user simulator (not verified here); defers (f), which is acceptable for a local-only tool but means AK has no answer to AgentCore, Logfire, Weave and LangSmith online evals in Phase 1.
- AK's choice of DeepEval and Opik judges inside pytest aligns with where the market moved (OpenAI itself pointed users from a hosted evals UI to the open-source Promptfoo); "evals as code in the repo, UI as a viewer" is a defensible positioning.
- Cheap upgrades that would reach the bar: show judge score and reason per square, keep the last N runs locally for a diff view, and template a simulated-user scenario (goal plus starting prompt, ADK style).

### Gaps
- Braintrust merge-gating: Braintrust marketing says merges block automatically on score drops, while a third-party 2026 comparison reportedly found no threshold input in the eval-action manifest; I could not resolve this from primary docs.
- Galileo, Arize AX online evals and Vertex AI Gen AI evaluation service were not researched individually.
- Whether AK's own test framework already supports multi-turn simulation was out of scope.

## 3. Deployment from a dev tool: how do studios deploy, does anyone run Terraform locally, and what about environments, rollback and secrets?

### Takeaway
Every vendor studio deploys with one command to its own managed runtime (`agentcore deploy`, `adk deploy agent_engine`, `langgraph deploy`, `crewai deploy`, `azd deploy`, git-push for Mastra Cloud). Under the hood they run IaC from the developer's machine: AgentCore CLI uses CDK, Google's Agent Starter Pack runs Terraform locally, and Azure's `azd` can generate and run Terraform. So a dev tool running Terraform for the user is not novel, but the bar includes remote state by default, multiple targets or environments (dev, staging, prod), generated CI/CD so production goes through a pipeline, revision history and rollback, and some secrets transfer. Practitioner consensus is that production applies should not come from laptops.

### Cited Findings

One-command deploys
- AgentCore CLI commands: `create`, `add`, `dev`, `build`, `deploy`, `status`, `invoke`, `logs`, `traces`, `eval`, plus `runtime`, `harness`, `gateway`, `memory`, `identity`; global `--json` for scripts, coding agents and CI; an interactive TUI ([aws/agentcore-cli README](https://github.com/aws/agentcore-cli)). The older Python starter toolkit (`agentcore configure`, `agentcore launch`) is deprecated and its binary name collides with the new CLI ([AWS docs: starter toolkit](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/getting-started-starter-toolkit.html); [AWS docs: AgentCore CLI](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/agentcore-get-started-cli.html)).
- ADK deploys with `adk deploy agent_engine --project=... --region=... path/to/agent/`, which packages code, uploads to Cloud Storage and creates an Agent Engine instance ([adk.dev: deploy to Agent Engine](https://adk.dev/deploy/agent-engine/deploy/); [third-party tutorial](https://dev.to/aryanirani123/how-to-deploy-adk-agents-to-vertex-ai-agent-engine-447g)). A third-party skills page says Agent Engine has been renamed Agent Runtime in newer `agents-cli` tooling ([third-party](https://mcpservers.org/hi/agent-skills/google/google-agents-cli-deploy); unverified).
- LangSmith Deployment: `langgraph deploy` creates a deployment whose first revision is created automatically; re-running it pushes a new revision; `langgraph deploy list` shows IDs; the CLI can only update deployments it created ([LangChain docs: deployment revisions](https://docs.langchain.com/langsmith/deployment-revisions)).
- CrewAI AMP: `crewai deploy create` reads the local `.env`, prompts the user to confirm detected variables (e.g. `OPENAI_API_KEY`) and stores them with the deployment; `crewai deploy push` updates, `crewai deploy remove <id>` deletes ([CrewAI docs: deploy to AMP](https://docs.crewai.com/en/enterprise/guides/deploy-to-amp)).
- Mastra Cloud (public beta) is GitHub-driven: pushes to a selected branch trigger deploys and each deployment is an atomic snapshot of agents and workflows; `mastra studio deploy` separately packages and deploys Studio to a cloud sandbox ([Mastra docs: Mastra Cloud deploying](https://mastra.ai/docs/mastra-cloud/deploying)).

Dev tools that run IaC locally
- AgentCore CLI projects include an AWS CDK app under `agentcore/cdk/` built on `@aws/agentcore-cdk`, and deployment targets (account plus region) are defined in `agentcore/aws-targets.json` ([aws/agentcore-cli README](https://github.com/aws/agentcore-cli)).
- Google Agent Starter Pack: `uvx agent-starter-pack setup-cicd` "automates the deployment of your complete Terraform infrastructure and configures your Google Cloud projects in a single operation", creates a GitHub repo, connects Cloud Build or GitHub Actions, and configures triggers; Terraform state goes to a GCS bucket by default with `--local-state` as an opt-out ([Agent Starter Pack: setup-cicd](https://googlecloudplatform.github.io/agent-starter-pack/cli/setup_cicd); [Agent Starter Pack: deployment guide](https://googlecloudplatform.github.io/agent-starter-pack/guide/deployment)). After setup, pushing to the repo deploys to staging first, then production ([adk.dev: Agent Starter Pack](https://adk.dev/deploy/agent-engine/asp)). A dev-only path uses `make setup-dev-env` (Terraform) and `make deploy` ([same](https://googlecloudplatform.github.io/agent-starter-pack/guide/deployment)). ADK docs say full production setup (Terraform, CI/CD, IAM) needs Owner role while a simple Agent Engine deploy needs only Vertex AI User ([adk.dev: ASP](https://adk.dev/deploy/agent-engine/asp)).
- Azure Developer CLI: `azd ai agent init --infra=terraform` (or Bicep) generates infrastructure for a Foundry hosted agent; Terraform manages supporting Azure resources while `azd deploy` creates the hosted-agent version, so Terraform does not manage agent versions in that path; Terraform provider auth is separate from azd auth ([Microsoft Learn: hosted agent infrastructure with azd](https://learn.microsoft.com/en-us/azure/foundry/agents/concepts/cli-infrastructure); [Microsoft Learn: CI/CD for hosted agents with azd](https://learn.microsoft.com/en-us/azure/foundry/agents/how-to/set-up-ci-cd-cli)). Alternatively the agent itself can be a Terraform resource via `azapi_data_plane_resource` (`Microsoft.Foundry/agents@v1`) ([Microsoft Learn: deploy hosted agent with Terraform](https://learn.microsoft.com/en-us/azure/foundry/agents/how-to/deploy-hosted-agent-terraform)).
- Foundry Toolkit's Agent Inspector does not deploy; it defers to "the existing hosted-agent deployment procedure" ([VS Code docs: Agent Inspector](https://code.visualstudio.com/docs/intelligentapps/agent-inspector)).

Environments, versioning, rollback, secrets
- Multi-target or multi-environment is built in: AgentCore `aws-targets.json` (multiple account and region targets) ([aws/agentcore-cli](https://github.com/aws/agentcore-cli)); Agent Starter Pack staging and production projects ([adk.dev: ASP](https://adk.dev/deploy/agent-engine/asp)).
- Revisions: LangSmith keeps a revisions table per deployment ([LangChain docs](https://docs.langchain.com/langsmith/deployment-revisions)); Mastra Cloud deploys are atomic snapshots ([Mastra docs](https://mastra.ai/docs/mastra-cloud/deploying)); Foundry hosted agents manage versions, images and traffic weights via azd or the Foundry SDK ([Microsoft Tech Community](https://techcommunity.microsoft.com/blog/azuredevcommunityblog/devops-for-microsoft-hosted-agents-from-terraform-apply-to-production-grade-agen/4523740)). I found no official LangSmith CLI rollback command; only a third-party skill wraps the control-plane API for rollback ([third-party skill](https://skills.cat/skills/lubu-labs/langchain-agent-skills/langsmith-deployment)).
- Prompt-level rollback is also expected: Langfuse prompt versions are immutable, labels (e.g. `production`, `staging`) can be moved to roll back, admins can protect labels, and clients pick up changes within a 60 second default cache TTL ([Langfuse docs: prompt version control](https://langfuse.com/docs/prompt-management/features/prompt-version-control)).
- Secrets: CrewAI transfers `.env` values on deploy with a confirmation prompt ([CrewAI docs](https://docs.crewai.com/en/enterprise/guides/deploy-to-amp)); AgentCore CLI has an `identity` resource group ([aws/agentcore-cli](https://github.com/aws/agentcore-cli)).

Practitioner view on laptop deploys vs GitOps
- Atlantis' "Terraform and the dangers of applying locally" argues for PR-driven plan and apply ([Atlantis blog, 2018](https://www.runatlantis.io/blog/2018/terraform-and-the-dangers-of-applying-locally); old but still widely cited).
- 2026 practitioner write-ups: production applies "should not come from a developer's laptop" and should run through CI with approval gates; changes flow through PRs, automated plan and controlled apply; locking must live in the state backend (S3 plus DynamoDB, GCS), never `-lock=false` for apply or destroy ([third-party: freeCodeCamp](https://www.freecodecamp.org/news/how-enterprise-teams-manage-infrastructure-at-scale-with-terraform); [third-party: "When running Terraform from your laptop stops being enough"](https://cicd-ariefw.pages.dev/articles/26-6-when-running-terraform-from-your-laptop-stops-being-enough/)). These are tutorials, not surveys.

### Inferences
- AK Studio Phase 1 meets the "one action to deploy from the dev tool" bar, and its plan-review step (parsed Terraform plan before apply), account-name confirmation and typed destroy confirmation match or exceed the safety UX of vendor CLIs, which mostly do not show a resource-level plan.
- AK Studio Phase 1 exceeds on breadth: three clouds and six targets from one UI. Every vendor tool above targets only its own cloud or managed runtime.
- AK Studio Phase 1 misses on:
  - Remote state by default. Agent Starter Pack defaults to a GCS backend and makes local state the opt-out; AK inverts this (local by default with a warning).
  - Environments. AgentCore (targets file) and Agent Starter Pack (staging and prod) assume more than one target; "one target per project" is below the bar.
  - CI/CD handoff. Agent Starter Pack and azd both generate pipelines so production goes through CI, matching practitioner consensus; "no CI" leaves AK as a laptop-apply tool. Even a "generate the GitHub Actions workflow for this Terraform" export would close most of the gap.
  - Revisions and rollback. LangSmith, Mastra and Foundry expose versions; AK Phase 1 has redeploy only.
  - Secrets. The brief does not mention how API keys reach the deployed agent; CrewAI's ".env detected, confirm upload" UX is the minimum users will expect. AK's runtime already has secret providers (env, aws_ssm, kubernetes), so wiring Studio to them is the natural fit.
- The deprecation of the AgentCore starter toolkit within a year shows vendor CLIs churn quickly; AK generating plain Terraform the user owns is a durability argument worth stating.

### Gaps
- Vercel, Modal and Vertex AI Agent Engine versioning or rollback details were not researched.
- No survey data found on how many teams deploy agents from laptops vs CI; practitioner material is opinion and tutorials.
- I did not verify whether AgentCore CLI's `deploy` shows a CDK diff before applying.

## 4. Interoperability expected in 2026: MCP, A2A, AG-UI, A2UI, ACP, AGENTS.md, Agent Skills

### Takeaway
MCP (client and remote server) is universal and assumed; the 2026-07-28 spec made it stateless. A2A reached v1.0 and moved into the Linux Foundation's Agentic AI Foundation (AAIF) alongside MCP and AGENTS.md. AG-UI hit 1.0 and is the de facto agent-to-frontend event protocol with integrations in nearly every framework AK wraps; A2UI layers generative UI on top. ACP is the editor-to-coding-agent protocol (Zed, JetBrains) and is less relevant to an agent runtime studio. AGENTS.md and Agent Skills (SKILL.md) are how coding agents learn a repo. Studios surface these selectively: AgentCore CLI scaffolds runtimes by protocol (HTTP, MCP, A2A, AG-UI), Foundry Inspector surfaces MCP approvals.

### Cited Findings
- MCP 2026-07-28 specification: release candidate locked 21 May 2026; the revision centres on a stateless protocol core and also covers an Extensions framework, Tasks, MCP Apps, authorization hardening and a formal deprecation policy ([MCP blog: 2026-07-28 release candidate](https://blog.modelcontextprotocol.io/posts/2026-07-28-release-candidate/)). Third-party summaries say it removes the initialize handshake and `Mcp-Session-Id`, adds a `server/discover` RPC, and lets remote servers sit behind plain round-robin load balancers ([Google Developers Blog](https://developers.googleblog.com/scaling-ai-agent-infrastructure-with-the-mcp-stateless-updates/); [third-party: Digital Applied](https://www.digitalapplied.com/blog/mcp-2026-07-28-stateless-spec-agent-infrastructure-2026)). Server Cards (`.well-known` metadata for discovery) appear to be a separate working-group effort not confirmed as part of the final spec ([third-party: bex.co](https://bex.co/blog/2026/09/04/mcp-server-cards-stateless-agent-deploy)).
- A2A: v1.0 shipped 12 March 2026 as the first stable spec (Signed Agent Cards, multi-tenancy, multiple transports, backward compatibility with v0.3); A2A joined AAIF in August 2026 ([AAIF blog: A2A joins AAIF](https://aaif.io/blog/a2a-joins-aaif)). Secondary sources disagree on the exact join date (17, 18 or 27 August) and report a v1.0.1 patch on 28 May 2026 ([third-party: tobira.ai](https://blog.tobira.ai/a2a-mcp-agentic-ai-foundation/)).
- AAIF hosted projects per a 22 October 2026 Linux Foundation announcement include A2A, MCP, AGENTS.md, goose, agentgateway and Agent Router, with a draft AI Catalog spec in progress (secondary report, [third-party: baeseokjae](https://baeseokjae.github.io/posts/linux-foundation-agentic-ai-foundation-2026/); not confirmed on linuxfoundation.org).
- AG-UI 1.0 announced as a stable spec, adopted by Google, Microsoft, Amazon and Oracle ([CopilotKit: AG-UI 1.0](https://www.copilotkit.ai/blog/ag-ui-1.0); vendor post). The AG-UI docs list integrations including Microsoft Agent Framework, Google ADK, AWS Strands, Mastra, Pydantic AI, Claude Agent SDK, CrewAI and LangGraph ([AG-UI docs](https://docs.ag-ui.com/introduction)).
- A2UI is Google's open project for agent-generated UI that renders across Lit, Angular and Flutter ([Google Developers Blog: Introducing A2UI](https://developers.googleblog.com/introducing-a2ui-an-open-project-for-agent-driven-interfaces/)); AG-UI is the transport and A2UI the UI description carried in the AG-UI event stream ([third-party: OpenUI State of Generative UI 2026](https://www.openui.com/blog/state-of-generative-ui-report)). Version status conflicts: one report says v0.9.1 in June 2026 with 1.0 at RC, a CopilotKit-linked post says 1.0 stable in November 2026 (unverified).
- AgentCore CLI runtimes accept `--protocol` values HTTP (default), MCP, A2A and AGUI, with templates `a2a-python-strands` and `agui-python-strands` ([aws/agentcore-cli README](https://github.com/aws/agentcore-cli)).
- Foundry Agent Inspector surfaces MCP tool approvals and OAuth consent, and detects the Responses or Invocations protocol; it does not mention AG-UI ([VS Code docs: Agent Inspector](https://code.visualstudio.com/docs/intelligentapps/agent-inspector)).
- Agent Client Protocol: created by Zed in 2025; JetBrains co-develops it and shipped beta support in December 2025 ([JetBrains AI blog, Dec 2025](https://blog.jetbrains.com/ai/2025/12/bring-your-own-ai-agent-to-jetbrains-ides/); [Zed blog](https://zed.dev/blog/jetbrains-on-acp)); an ACP Registry beta launched 28 January 2026 ([third-party: gihyo.jp](https://gihyo.jp/article/2026/01/acp-registry)). Agent counts vary by source (25+ in March, about 50 by June 2026) and are unverified.
- Agent Skills (SKILL.md) was released as an open standard at agentskills.io in December 2025 and reportedly adopted by 30+ AI coding tools by April 2026; security researchers report hundreds of malicious skills ([third-party: noqta.tn](https://www.noqta.tn/en/news/skill-md-open-standard-30-ai-coding-tools-adoption-2026); [third-party: DEV Community](https://dev.to/breachprotocol/agent-skills-quietly-became-a-package-format-and-github-is-warning-about-what-that-means-4fp9)).

### Inferences
- Phase 1 as briefed does not surface any protocol in the UI. Against the bar:
  - MCP: expected. A studio should at least list the MCP servers an agent uses, show MCP tool calls as spans, and route MCP approval requests into the HITL UI (Foundry Inspector does exactly this).
  - AG-UI: the strongest fit for AK Studio's chat pane. Since AG-UI integrations exist for most of AK's eight frameworks, a Studio chat that speaks AG-UI would get tool-call, state and interrupt events in a standard shape and could fill the "frameworks without streaming" gap where AG-UI adapters exist.
  - A2A: expected at the runtime level (AgentCore scaffolds it); a studio could show the Agent Card and let users call the agent over A2A. Not table stakes for a Phase 1 desktop tool.
  - ACP: relevant only if AK Studio wants to host coding agents; not table stakes.
  - AGENTS.md and Agent Skills: AK already bundles user skills; having Studio scaffold AGENTS.md and the AK skills into new projects is cheap and matches what developers now expect from a project template.

### Gaps
- MCP Registry (official registry and sub-registries) status and whether any studio surfaces it in UI was not researched.
- Exact A2A AAIF join date and A2UI 1.0 status could not be confirmed from primary sources.
- I did not verify which of AK's eight frameworks have first-party vs community AG-UI adapters.

## 5. Cost and model management: token/cost tracking, model comparison, local models, prompt versioning

### Takeaway
Per-span token counts and cost are standard in hosted tracers (Langfuse, LangSmith) and appear in local tools (Foundry Inspector Tokens tab). Model comparison happens in playgrounds (Phoenix, Langfuse, Weave) and in experiments. Local models are a first-class option in IDE toolkits (Foundry Toolkit supports Ollama and Foundry Local). Prompt versioning with environment labels and instant rollback (Langfuse) is a mature, expected feature in platforms, though less common in local studios. Multi-model use is the norm.

### Cited Findings
- Langfuse computes cost automatically from model plus token counts and shows cost on every trace node and in a timeline view ([Langfuse docs](https://langfuse.com/docs)).
- Foundry Agent Inspector has a Tokens tab with reported token usage ([VS Code docs: Agent Inspector](https://code.visualstudio.com/docs/intelligentapps/agent-inspector)).
- Foundry Toolkit's model catalog includes local models via ONNX, Ollama and Foundry Local, and supports evaluating models, prompts and agents with datasets and built-in or custom evaluators, locally or in Foundry ([VS Code docs: Foundry Toolkit overview](https://code.visualstudio.com/docs/intelligentapps/overview); [Microsoft Learn: get started in VS Code](https://learn.microsoft.com/en-us/azure/foundry/how-to/develop/get-started-projects-vs-code)).
- Phoenix Prompt Playground supports side-by-side prompt and model comparison ([Phoenix docs: Span Replay](https://arize.com/docs/phoenix/prompt-engineering/overview-prompts/span-replay)); Weave Playground tests new LLMs against production traces ([W&B Weave](https://site.wandb.ai/weave/)).
- Langfuse prompt management: immutable versions, labels for environments or A/B variants, protected labels, rollback by moving a label, 60 second SDK cache TTL; the playground supports variables, tool definitions with mocked responses and structured outputs ([Langfuse docs: prompt version control](https://langfuse.com/docs/prompt-management/features/prompt-version-control)).
- AgentCore CLI templates support Bedrock, Anthropic, OpenAI, OpenAI-compatible endpoints, Gemini and LiteLLM ([aws/agentcore-cli](https://github.com/aws/agentcore-cli)).
- Over three quarters of survey respondents use multiple models; about a third invest in infrastructure to run their own models; cost was cited less often as a barrier than in previous years ([LangChain: State of Agent Engineering](https://www.langchain.com/state-of-agent-engineering)).
- OpenAI's reusable Prompts API (v1/prompts) is reported by several third parties to shut down on 30 November 2026 alongside Agent Builder ([third-party: ecorpit](https://ecorpit.com/openai-agent-builder-evals-prompts-shutdown-november-2026/); not confirmed on OpenAI's page).

### Inferences
- AK Studio Phase 1 misses this area almost entirely: no token or cost per span, no model switcher or comparison, no local-model affordance, no prompt versioning. Token and cost per span is the cheapest and most expected of these and should be in Phase 1 if traces are in Phase 1.
- Local-model support (Ollama, LM Studio via OpenAI-compatible endpoints) is a natural fit for a desktop app and is something Foundry Toolkit already offers; a "swap model to local" toggle in the chat pane would be a visible differentiator against cloud-first studios.
- Prompt management with labels is a platform feature; deferring it fits Phase 1, but since prompts in AK live in code or config, a Git-backed view (diff of agent config between runs) may be a lighter-weight answer.

### Gaps
- No primary source found on LM Studio integration in any studio, or on Langfuse's support for Ollama connections in its playground.
- Braintrust and LangSmith cost features were not checked against primary docs this round.

## 6. Safety and governance in dev tools: guardrail testing, red-teaming, PII, approval workflows

### Takeaway
Red-teaming moved from niche to mainstream in 2026, signalled by OpenAI acquiring Promptfoo and directing former OpenAI Evals users to it. The common toolchain is Promptfoo for CI-friendly assertions and red-team scans, plus garak (probe library) or PyRIT (multi-turn orchestrator). Cloud eval services include safety evaluators (AgentCore: harmfulness, stereotyping). Approval workflows in dev tools are mostly human-in-the-loop tool approvals (Foundry Inspector MCP approvals, LangGraph interrupts). Content-capture defaults in OTel GenAI (`NO_CONTENT`) reflect PII sensitivity in tracing.

### Cited Findings
- OpenAI is acquiring Promptfoo (announced 9 March 2026) to add agentic security testing and continuous security evaluation to OpenAI Frontier; Promptfoo stays open source and is used by more than 25% of Fortune 500 companies ([OpenAI](https://openai.com/blog/openai-to-acquire-promptfoo); [TechCrunch](https://www.techcrunch.com/2026/03/09/openai-acquires-promptfoo-to-secure-its-ai-agents/)).
- OpenAI's Evals deprecation guidance points to "Moving from OpenAI Evals to Promptfoo" ([OpenAI API docs: Deprecations](https://developers.openai.com/api/docs/deprecations)).
- Third-party comparisons describe Promptfoo as CLI-first and strongest for CI fit, garak (NVIDIA) as the mature probe-library scanner but weaker for multi-step agent flows, and PyRIT (Microsoft) as the orchestrator for multi-turn and multimodal attacks with the heaviest setup; the usual advice is to combine a probe tool, a CI assertion runner and a runtime guardrail ([third-party: Future AGI](https://futureagi.com/blog/open-source-llm-red-team-frameworks-compared-2026/); [third-party: AppSec Santa](https://appsecsanta.com/ai-security-tools/llm-red-teaming)).
- AgentCore Evaluations built-in evaluators cover safety categories including harmfulness and stereotyping detection ([AWS What's New](https://aws.amazon.com/about-aws/whats-new/2026/03/agentcore-evaluations-generally-available); category names from [AWS ML blog](https://aws.amazon.com/blogs/machine-learning/build-reliable-ai-agents-with-amazon-bedrock-agentcore-evaluations)).
- W&B Weave lists guardrails for blocking prompt attacks and harmful outputs as a platform feature ([W&B Weave](https://site.wandb.ai/weave/)).
- Foundry Agent Inspector's approval UI covers MCP tool approval (Approve, Deny, Approve all, Deny all) and OAuth consent requiring both browser authorization and an Inspector confirmation ([VS Code docs: Agent Inspector](https://code.visualstudio.com/docs/intelligentapps/agent-inspector)).
- OTel GenAI content capture is opt-in with default `NO_CONTENT` ([third-party: John Hodge](https://john-hodge.com/blog/opentelemetry-genai-semantic-conventions/)); LangSmith Studio can run with tracing disabled so no data leaves the local server ([LangChain docs: local server](https://docs.langchain.com/langsmith/local-server)).
- Security was cited as a production barrier by 24.9% of enterprises with 2,000+ employees ([LangChain: State of Agent Engineering](https://www.langchain.com/state-of-agent-engineering)).
- Hundreds of malicious Agent Skills were reported in early 2026, a supply-chain risk for skill-bundling tools ([third-party: noqta.tn](https://www.noqta.tn/en/news/skill-md-open-standard-30-ai-coding-tools-adoption-2026)).

### Inferences
- AK Studio Phase 1 meets the approval-workflow bar (approve or deny HITL pauses) and its typed confirmations on deploy and destroy go beyond what vendor deploy CLIs show.
- AK Studio Phase 1 misses guardrail testing and red-teaming in the UI, even though AK's runtime has guardrails (OpenAI Guardrails, Bedrock Guardrails, Walled AI). A "guardrail fired" marker on trace spans and a canned red-team scenario pack (or a Promptfoo export of saved scenarios) would turn an existing runtime strength into a visible studio feature.
- A desktop app that keeps traces local by default is a privacy positive relative to hosted tracers; stating "no data leaves the machine" (as LangSmith Studio documents) is worth doing explicitly.

### Gaps
- No primary source on PII redaction features in local studios (as opposed to hosted platforms).
- Galileo's guardrail and safety tooling was not researched.

## 7. Where does AK Studio Phase 1 meet, miss or exceed the late-2026 bar? (synthesis)

### Takeaway
Phase 1 clears the floor for local run, chat, trace, HITL and run-the-tests, and it is ahead of the field on framework neutrality (eight frameworks) and multi-cloud Terraform deploy with a reviewed plan. It falls short of table stakes on span-level traces for non-streaming frameworks, token and cost per span, eval scores and run comparison, environments, CI handoff, remote state default, rollback, secrets and any visible protocol support (MCP, AG-UI).

### Cited Findings
- Floor features shipped by competitors: LangSmith Studio ([docs](https://docs.langchain.com/oss/python/langchain/studio)), ADK web ([adk-web](https://github.com/google/adk-web)), Mastra Studio ([docs](https://mastra.ai/docs/getting-started/studio)), Foundry Agent Inspector ([docs](https://code.visualstudio.com/docs/intelligentapps/agent-inspector)), AgentCore Agent Inspector ([AWS docs](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/agentcore-get-started-cli.html)).
- Single-framework or single-cloud nature of competitors: Foundry Inspector graph view not supported for LangGraph ([docs](https://code.visualstudio.com/docs/intelligentapps/agent-inspector)); LangGraph time travel depends on LangGraph checkpoints ([docs](https://docs.langchain.com/oss/python/langgraph/use-time-travel)); AgentCore CLI deploys via CDK to AWS only ([README](https://github.com/aws/agentcore-cli)); Agent Starter Pack targets Google Cloud ([docs](https://googlecloudplatform.github.io/agent-starter-pack/cli/setup_cicd)).
- Deployment bar items (remote state default, staging and prod, CI generation): Agent Starter Pack ([setup-cicd](https://googlecloudplatform.github.io/agent-starter-pack/cli/setup_cicd)); azd CI/CD ([Microsoft Learn](https://learn.microsoft.com/en-us/azure/foundry/agents/how-to/set-up-ci-cd-cli)); revisions ([LangSmith](https://docs.langchain.com/langsmith/deployment-revisions)).
- Eval bar items (session to dataset, simulation, comparison, CI, online): see section 2 sources.

### Inferences
Scorecard (meets / misses / exceeds), based on the cited findings above:

| Area | Table-stakes item (who sets it) | AK Studio Phase 1 |
|---|---|---|
| Local loop | Start local server, chat, trace view (all vendors) | Meets |
| Local loop | Span per model call and tool call for every run (all vendors) | Misses for non-streaming frameworks (run-level timing only) |
| Local loop | Token and cost per span (Langfuse, Foundry Inspector) | Misses |
| Local loop | HITL approve or deny (Foundry Inspector, LangGraph Studio) | Meets |
| Local loop | Time travel, fork, state edit (LangGraph Studio) | Misses (LangGraph-specific, defensible) |
| Local loop | Replay span in playground (Phoenix, Langfuse) | Misses |
| Local loop | Breakpoints in agent code (Foundry Toolkit) | Misses (hard for a non-IDE app) |
| Local loop | Many frameworks in one UI | Exceeds (8 frameworks; competitors are single-framework) |
| Tracing standard | OTel GenAI span shape, local OTLP receiver (Foundry Toolkit) | Misses in Studio (AK runtime already exports via OpenLLMetry and Logfire) |
| Eval | Save session as test case (ADK web) | Meets |
| Eval | Run suite from UI with results (ADK web, Mastra) | Meets (pass/fail only) |
| Eval | Judge scores and reasons, thresholds (all eval tools) | Partial at best |
| Eval | Run history and side-by-side comparison (Braintrust, LangSmith, Confident AI) | Misses (deferred) |
| Eval | Simulated multi-turn users (LangSmith, ADK, DeepEval) | Misses in Studio |
| Eval | CI regression run (Braintrust, AgentCore, DeepEval) | Meets indirectly (pytest runs in CI outside Studio) |
| Eval | Online evals (AgentCore, Logfire, Weave, LangSmith) | Deferred |
| Deploy | One-action deploy from dev tool (all vendors) | Meets |
| Deploy | Plan preview and explicit confirmation | Exceeds most vendor CLIs |
| Deploy | Multi-cloud from one tool | Exceeds (vendors are single-cloud) |
| Deploy | Remote state by default (Agent Starter Pack) | Misses (local default with warning) |
| Deploy | Multiple environments or targets (AgentCore targets, ASP staging and prod) | Misses (one target per project) |
| Deploy | Generated CI/CD so prod goes through a pipeline (ASP, azd) | Misses (no CI) |
| Deploy | Revisions and rollback (LangSmith, Mastra, Foundry) | Misses (redeploy only) |
| Deploy | Secrets transfer on deploy (CrewAI AMP) | Not specified in brief |
| Interop | MCP visible (servers, tool spans, approvals) (Foundry Inspector) | Not specified |
| Interop | AG-UI or A2A protocol options (AgentCore CLI) | Not specified |
| Interop | AGENTS.md and Agent Skills in templates | Not specified (AK already bundles skills) |
| Cost and models | Model switch, local models (Foundry Toolkit: Ollama, Foundry Local) | Misses |
| Cost and models | Prompt versioning with labels (Langfuse) | Misses (platform feature, deferrable) |
| Safety | Guardrail and red-team testing in UI (Promptfoo, PyRIT, garak) | Misses in Studio (AK runtime has guardrails) |
| Safety | Local-only traces by default | Likely exceeds hosted tracers (state it explicitly) |

- Highest-leverage additions for Phase 1, judged by how universal the competitor feature is and how much AK already has underneath: (1) local OTLP receiver so every framework gets span-level traces with tokens and cost; (2) show judge score and reason per test and keep local run history for a diff; (3) offer remote backend and a generated CI workflow as the default path for any non-dev target, with laptop apply framed as "dev environment"; (4) list MCP servers and route MCP approvals into the existing HITL UI.
- The OpenAI Agent Builder and Evals shutdown (30 November 2026) and the AgentCore starter toolkit deprecation both show hosted visual builders and vendor CLIs are volatile; a local, code-first, framework-neutral studio that writes plain pytest and plain Terraform into the user's repo is a credible counter-position.

### Gaps
- This synthesis assumes the Phase 1 feature list in the brief is complete; items marked "not specified" may already be planned.
- No user research on which of the missing features AK's own users rank highest.
