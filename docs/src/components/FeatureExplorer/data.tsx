/**
 * Feature catalogue for the landing page's tabbed explorer. Each tab mirrors one word of the
 * ArchitectureOverview flow line (Build · Connect · Remember · Guard · Scale · Observe).
 * Copy is condensed from the features page and the docs; `docs` is a site-relative docs path and
 * `example` a folder under examples/ in the GitHub repo.
 */

export interface FeatureCard {
  title: string;
  description: string;
  tags: string[];
  docs: string;
  example?: string;
}

export interface FeatureTab {
  key: string;
  label: string;
  description: string;
  cards: FeatureCard[];
}

export const EXAMPLES_BASE = "https://github.com/yaalalabs/agent-kernel/tree/develop/examples";

export const FEATURE_TABS: FeatureTab[] = [
  {
    key: "build",
    label: "Build",
    description:
      "Write agents in the framework you already know. Agent Kernel wraps them with one API for tools, hooks, sessions and structured output, so the agent logic stays yours.",
    cards: [
      {
        title: "Framework Adapters",
        description:
          "OpenAI Agents SDK, LangGraph, CrewAI, Google ADK, Smolagents and Pydantic AI run side by side in one runtime. Switch frameworks by changing two import lines.",
        tags: ["OpenAI", "LangGraph", "CrewAI", "ADK", "Smolagents", "Pydantic AI"],
        docs: "/docs/frameworks/overview",
        example: "cli/multi",
      },
      {
        title: "Portable Tools",
        description:
          "Write a tool once as a plain Python function and bind it to any framework through ToolBuilder. The tool context exposes the runtime, agent, session and request.",
        tags: ["ToolBuilder", "ToolContext", "Any framework"],
        docs: "/docs/core-concepts/tools",
      },
      {
        title: "Execution Hooks",
        description:
          "Pre- and post-hooks wrap every run: inject context, validate input, rewrite or halt replies, and filter streamed events as they are produced.",
        tags: ["Pre-hooks", "Post-hooks", "Stream events"],
        docs: "/docs/integrations/hooks",
        example: "api/hooks",
      },
      {
        title: "Structured Output",
        description:
          "Return typed JSON instead of prose. Pydantic schemas map to each framework's native structured-output mode and come back as one reply type.",
        tags: ["Pydantic", "JSON", "All frameworks"],
        docs: "/docs/core-concepts/runner",
        example: "cli/openai_structured",
      },
      {
        title: "Multimodal Input",
        description:
          "Images and files ride along with text. A vision model describes each attachment, stores it outside the session, and an analyze tool pulls details on demand.",
        tags: ["Images", "Files", "Vision LLM"],
        docs: "/docs/advanced/multimodal",
        example: "api/multimodal",
      },
      {
        title: "Multi-Agent Systems",
        description:
          "Compose specialist agents, even from different frameworks, in one runtime with handoffs and a shared session.",
        tags: ["Handoffs", "Multi-framework", "Shared session"],
        docs: "/docs/advanced/multi-agent",
        example: "cli/multi",
      },
    ],
  },
  {
    key: "connect",
    label: "Connect",
    description:
      "Reach users where they already are. Channels, protocols and APIs are adapters around the same runtime, so one agent serves them all.",
    cards: [
      {
        title: "Messaging Channels",
        description:
          "Slack, Microsoft Teams, WhatsApp, Messenger, Instagram, Telegram and Gmail. Each adapter verifies webhooks, downloads attachments and replies in-platform, with the agent running off the webhook turn.",
        tags: ["Slack", "Teams", "WhatsApp", "Messenger", "Instagram", "Telegram", "Gmail"],
        docs: "/docs/integrations/overview",
        example: "api/slack",
      },
      {
        title: "REST, WebSocket & Streaming",
        description:
          "A FastAPI server with sync, async and SSE streaming modes, a WebSocket gateway for push delivery, and multipart uploads for attachments.",
        tags: ["REST", "SSE", "WebSocket", "Multipart"],
        docs: "/docs/api/rest-api",
        example: "api/openai",
      },
      {
        title: "MCP Server",
        description:
          "Expose agents as MCP tools so any Model Context Protocol client can call them, with the same sessions and hooks as every other surface.",
        tags: ["MCP", "Tools", "FastMCP"],
        docs: "/docs/api/mcp-server",
        example: "api/mcp",
      },
      {
        title: "A2A Server",
        description:
          "Publish an agent card and serve agent-to-agent calls over the A2A protocol by switching configuration.",
        tags: ["A2A", "Agent card", "Delegation"],
        docs: "/docs/api/a2a-server",
        example: "api/a2a",
      },
      {
        title: "AG-UI Frontends",
        description:
          "Stream text, tool calls, steps and reasoning to AG-UI clients such as CopilotKit, with shared state and client context available to agents as tools.",
        tags: ["AG-UI", "CopilotKit", "Shared state"],
        docs: "/docs/api/agui-server",
        example: "api/agui",
      },
      {
        title: "Interactive CLI",
        description:
          "Select agents, start sessions and chat from the terminal for local development before anything is deployed.",
        tags: ["Interactive", "Multi-agent", "Sessions"],
        docs: "/docs/testing/cli-testing",
        example: "cli/openai",
      },
    ],
  },
  {
    key: "remember",
    label: "Remember",
    description:
      "State that survives the request. Sessions, threads, attachments and knowledge live in pluggable stores you select with configuration, not code.",
    cards: [
      {
        title: "Sessions & Memory",
        description:
          "Volatile and non-volatile caches with one API and different lifecycles. Framework state is stored per adapter, and the backend is a config switch.",
        tags: ["Volatile", "Non-volatile", "Framework state"],
        docs: "/docs/core-concepts/session",
        example: "memory/redis",
      },
      {
        title: "Pluggable Session Stores",
        description:
          "In-memory for development; Redis, Valkey, DynamoDB, Cosmos DB and Firestore for production. Shared drivers handle connection lifecycle and retries.",
        tags: ["Redis", "Valkey", "DynamoDB", "Cosmos DB", "Firestore"],
        docs: "/docs/architecture/memory-management",
        example: "memory/dynamodb",
      },
      {
        title: "Conversation Threads",
        description:
          "Persistent, named conversation threads keyed by session, readable over REST with cursor pagination and auto-named from the first prompt.",
        tags: ["Threads", "REST", "Auto-naming"],
        docs: "/docs/advanced/threads",
        example: "api/thread-openai",
      },
      {
        title: "Knowledge Bases",
        description:
          "Agents search, query, fetch and browse ChromaDB, Neo4j, Starburst/Trino and Open Knowledge Format bundles through capability-gated tools.",
        tags: ["ChromaDB", "Neo4j", "Trino", "OKF"],
        docs: "/docs/advanced/knowledge-bases",
        example: "cli/knowledgebase",
      },
      {
        title: "Attachment Storage",
        description:
          "Images and files are stored outside the session in Redis, DynamoDB or memory with TTLs, keeping prompts lean and history clean.",
        tags: ["Redis", "DynamoDB", "TTL"],
        docs: "/docs/advanced/multimodal",
      },
    ],
  },
  {
    key: "guard",
    label: "Guard",
    description:
      "Decide what goes in and what comes out. Guardrails, secrets, identity and sandbox policy are enforced by the runtime, not left to each agent.",
    cards: [
      {
        title: "Content Guardrails",
        description:
          "Input and output guardrails as system hooks: PII redaction, jailbreak prevention, moderation and off-topic filtering, with OpenAI Guardrails, Amazon Bedrock Guardrails and Walled AI built in.",
        tags: ["OpenAI", "Bedrock", "Walled AI", "PII"],
        docs: "/docs/advanced/guardrails",
        example: "cli/guardrail",
      },
      {
        title: "Secret Resolution",
        description:
          "Resolve API keys and tokens from the environment with fallback to a managed store such as AWS Systems Manager Parameter Store, cached with a TTL and never written back to the environment.",
        tags: ["env", "AWS SSM", "TTL cache"],
        docs: "/docs/next/advanced/secrets",
        example: "cli/openai-secret",
      },
      {
        title: "Authentication",
        description:
          "Bring your own validator for REST and WebSocket routes, with JWT and JWKS validation, cloud API gateway authorizers, and per-user scoping of threads and schedules.",
        tags: ["JWT", "JWKS", "Authorisers"],
        docs: "/docs/api/rest-api",
        example: "aws-serverless/openai-auth",
      },
      {
        title: "Sandbox Policy & Identity",
        description:
          "Fail-closed network, filesystem, CPU and memory policies for sandboxed code, executed as the agent or as the end user through RBAC impersonation.",
        tags: ["Fail-closed", "RBAC", "Per-user"],
        docs: "/docs/advanced/sandbox",
        example: "sandbox/policy",
      },
    ],
  },
  {
    key: "scale",
    label: "Scale",
    description:
      "From a laptop to a fleet. The same agent code runs serverless, containerized or on Kubernetes, with queue-backed execution that scales ingress and agents independently.",
    cards: [
      {
        title: "Multi-Cloud Deployment",
        description:
          "Terraform modules for AWS Lambda and ECS Fargate, Azure Functions and Container Apps, and Google Cloud Run. One codebase, no vendor lock-in.",
        tags: ["AWS", "Azure", "GCP", "Terraform"],
        docs: "/docs/deployment/overview",
        example: "aws-serverless/openai",
      },
      {
        title: "Kubernetes Helm Chart",
        description:
          "io-handler, agent-runner and WebSocket gateway Deployments for bare metal, EKS or air-gapped clusters, with KEDA autoscaling and declarative broker objects.",
        tags: ["Helm", "KEDA", "Bare metal", "EKS"],
        docs: "/docs/deployment/onprem-kubernetes",
        example: "k8s/openai-queue-mode",
      },
      {
        title: "Queue Pipeline",
        description:
          "Request handler, input queue, agent runner, output queue, response handler. In-memory locally; SQS, Kafka or NATS JetStream in production, with per-session FIFO, retries and dedup.",
        tags: ["SQS", "Kafka", "NATS", "FIFO"],
        docs: "/docs/advanced/queue-mode-guide",
        example: "transport/kafka",
      },
      {
        title: "Sandboxed Execution",
        description:
          "Agents run code, shell commands and file operations in isolated sandboxes: local subprocess, Docker, Kubernetes, E2B, Daytona or EC2 via SSM, in-process or over a queue to a worker fleet.",
        tags: ["Docker", "Kubernetes", "E2B", "Daytona"],
        docs: "/docs/advanced/sandbox",
        example: "sandbox/docker",
      },
      {
        title: "Scheduled Tasks",
        description:
          "Defer or repeat a chat request with an at or cron schedule. A local provider for one process, Amazon EventBridge Scheduler for durable fleets, and agent tools to manage schedules.",
        tags: ["Cron", "EventBridge", "202 Accepted"],
        docs: "/docs/advanced/scheduling",
        example: "api/schedule-openai",
      },
      {
        title: "Fault Tolerance",
        description:
          "Multi-AZ deployments, automatic recovery, health monitoring and zero-downtime rollouts across every deployment mode.",
        tags: ["Multi-AZ", "Auto-recovery", "Health checks"],
        docs: "/docs/core-concepts/fault-tolerance",
      },
    ],
  },
  {
    key: "observe",
    label: "Observe",
    description:
      "See every run and prove it works. Tracing and testing plug into the same runtime, so a trace and a test describe the same request.",
    cards: [
      {
        title: "Tracing",
        description:
          "One config line enables Langfuse, OpenLLMetry on OpenTelemetry, or Pydantic Logfire across agents, LLM calls and tool invocations, with cost and latency.",
        tags: ["Langfuse", "OpenLLMetry", "Logfire", "OpenTelemetry"],
        docs: "/docs/advanced/traceability",
        example: "cli/logfire",
      },
      {
        title: "Automated Testing",
        description:
          "pytest-integrated suites with session-scoped fixtures and ordered steps, in score, LLM-judge and fallback modes, ready for CI.",
        tags: ["pytest", "Score", "LLM judge", "CI"],
        docs: "/docs/testing/automated-testing",
      },
      {
        title: "Pluggable Evaluators",
        description:
          "Every comparison runs through an AKEvaluator. DeepEval, Opik and TypeSafe JEV are built in; bring your own with one line of config.",
        tags: ["DeepEval", "Opik", "JEV", "Custom"],
        docs: "/docs/testing/automated-testing",
        example: "cli/jev-evaluator",
      },
      {
        title: "Interactive CLI Testing",
        description:
          "Chat with agents in persistent CLI sessions for rapid iteration and multi-agent debugging, with real-time feedback.",
        tags: ["Sessions", "Multi-agent", "Real-time"],
        docs: "/docs/testing/cli-testing",
        example: "cli/multi",
      },
    ],
  },
];
