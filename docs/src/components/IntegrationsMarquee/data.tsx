import React from "react";
import { FaAws } from "react-icons/fa";
import { VscAzure } from "react-icons/vsc";
import { TbPlugConnected } from "react-icons/tb";
import {
  SiApachekafka,
  SiClaude,
  SiCrewai,
  SiCursor,
  SiDocker,
  SiFastapi,
  SiFirebase,
  SiGithubcopilot,
  SiGooglecloud,
  SiHelm,
  SiKubernetes,
  SiLanggraph,
  SiModelcontextprotocol,
  SiNatsdotio,
  SiNeo4J,
  SiOpentelemetry,
  SiPydantic,
  SiRedis,
  SiTerraform,
  SiTrino,
  SiWindsurf,
} from "react-icons/si";

export interface IntegrationItem {
  /** Display name on the tile. */
  name: string;
  /** Short role label under the name, e.g. "Framework", "Channel", "Queue". */
  role: string;
  /** Docs page (site-relative) or external URL the tile links to. */
  href: string;
  /** Image under /img/integrations. Either `logo` or `icon` is required. */
  logo?: string;
  /** A react-icons glyph, used when no image asset exists. */
  icon?: React.ReactNode;
  /** Invert a black-on-transparent mark so it reads on the dark page. */
  mono?: boolean;
  /** A wordmark rather than a square mark; gets a wider logo slot. */
  wide?: boolean;
  /** Announced but not yet shipped. */
  soon?: boolean;
  /** Hover text; defaults to "name: role". Use it when the full role list is longer than the label. */
  title?: string;
}

export interface IntegrationRow {
  title: string;
  /** Scroll speed as seconds per tile (lower is faster); the component's default applies when omitted. */
  secondsPerTile?: number;
  items: IntegrationItem[];
}

const KB = "/docs/advanced/knowledge-bases";
const SESSION = "/docs/core-concepts/session";
const QUEUE = "/docs/advanced/queue-mode-guide";
const SANDBOX = "/docs/advanced/sandbox";
const TRACE = "/docs/advanced/traceability";
const TESTING = "/docs/testing/automated-testing";
const SKILLS = "/docs/agent-skills";
const K8S = "/docs/deployment/onprem-kubernetes";

export const INTEGRATION_ROWS: IntegrationRow[] = [
  {
    title: "Agent frameworks & dev tools",
    secondsPerTile: 3.0,
    items: [
      { name: "OpenAI Agents SDK", role: "Framework", href: "/docs/frameworks/openai", logo: "/img/integrations/openai.svg", mono: true },
      { name: "LangGraph", role: "Framework", href: "/docs/frameworks/langgraph", icon: <SiLanggraph /> },
      { name: "CrewAI", role: "Framework", href: "/docs/frameworks/crewai", icon: <SiCrewai /> },
      { name: "Google ADK", role: "Framework", href: "/docs/frameworks/google-adk", logo: "/img/integrations/adk.png" },
      { name: "Smolagents", role: "Framework", href: "/docs/frameworks/smolagents", logo: "/img/integrations/smolagents.svg" },
      { name: "Pydantic AI", role: "Framework", href: "/docs/frameworks/pydantic-ai", icon: <SiPydantic /> },
      { name: "Microsoft Agents", role: "Framework", href: "/docs/next/frameworks/microsoft-agents", logo: "https://upload.wikimedia.org/wikipedia/commons/4/44/Microsoft_logo.svg" },
      { name: "Claude Code", role: "Agent skills", href: SKILLS, icon: <SiClaude /> },
      { name: "Cursor", role: "Agent skills", href: SKILLS, icon: <SiCursor /> },
      { name: "Codex", role: "Agent skills", href: SKILLS, logo: "/img/integrations/openai.svg", mono: true },
      { name: "Windsurf", role: "Agent skills", href: SKILLS, icon: <SiWindsurf /> },
      { name: "GitHub Copilot", role: "Agent skills", href: SKILLS, icon: <SiGithubcopilot /> },
    ],
  },
  {
    title: "Channels & protocols",
    secondsPerTile: 4.2,
    items: [
      { name: "Slack", role: "Channel", href: "/docs/integrations/slack", logo: "/img/integrations/slack-logo.png" },
      { name: "Microsoft Teams", role: "Channel", href: "/docs/integrations/teams", logo: "/img/integrations/teams-logo.png" },
      { name: "WhatsApp", role: "Channel", href: "/docs/integrations/whatsapp", logo: "/img/integrations/whatsapp-logo.png" },
      { name: "Messenger", role: "Channel", href: "/docs/integrations/messenger", logo: "/img/integrations/messenger-logo.png" },
      { name: "Instagram", role: "Channel", href: "/docs/integrations/instagram", logo: "/img/integrations/instagram-logo.png" },
      { name: "Telegram", role: "Channel", href: "/docs/integrations/telegram", logo: "/img/integrations/telegram-logo.png" },
      { name: "Gmail", role: "Channel", href: "/docs/integrations/gmail", logo: "/img/integrations/gmail-logo.png" },
      { name: "LiveKit", role: "Voice & video", href: "https://docs.livekit.io/", logo: "/img/integrations/livekit-mark.svg", soon: true },
      { name: "MCP", role: "Protocol", href: "/docs/api/mcp-server", icon: <SiModelcontextprotocol /> },
      { name: "A2A", role: "Protocol", href: "/docs/api/a2a-server", logo: "/img/integrations/a2a-white.svg" },
      { name: "AG-UI", role: "Protocol", href: "/docs/api/agui-server", logo: "/img/integrations/agui.svg", mono: true },
      { name: "REST & SSE", role: "API", href: "/docs/api/rest-api", icon: <SiFastapi /> },
      { name: "WebSocket", role: "API", href: "/docs/api/rest-api", icon: <TbPlugConnected /> },
    ],
  },
  {
    title: "Memory, knowledge & data",
    secondsPerTile: 2.4,
    items: [
      { name: "Redis", role: "Memory", href: SESSION, icon: <SiRedis />, title: "Redis: session, thread, attachment, response and schedule stores" },
      { name: "Valkey", role: "Memory", href: SESSION, logo: "/img/integrations/valkey.svg", mono: true, title: "Valkey: session, thread, response and schedule stores" },
      { name: "Amazon DynamoDB", role: "Memory", href: SESSION, icon: <FaAws />, title: "Amazon DynamoDB: session, thread, attachment, response and schedule stores" },
      { name: "Azure Cosmos DB", role: "Memory", href: SESSION, icon: <VscAzure />, title: "Azure Cosmos DB: session and thread stores" },
      { name: "Google Firestore", role: "Memory", href: SESSION, icon: <SiFirebase />, title: "Google Firestore: session and thread stores" },
      { name: "Amazon S3", role: "Knowledge store", href: KB, icon: <FaAws /> },
      { name: "ChromaDB", role: "Vector knowledge", href: KB, logo: "/img/integrations/chroma.svg" },
      { name: "Neo4j", role: "Graph knowledge", href: KB, icon: <SiNeo4J /> },
      { name: "Starburst / Trino", role: "SQL knowledge", href: KB, icon: <SiTrino /> },
    ],
  },
  {
    title: "Cloud & infrastructure",
    secondsPerTile: 3.6,
    items: [
      { name: "AWS Lambda", role: "Serverless", href: "/docs/deployment/aws-serverless", icon: <FaAws /> },
      { name: "Amazon ECS Fargate", role: "Containers", href: "/docs/deployment/aws-containerized", icon: <FaAws /> },
      { name: "Amazon API Gateway", role: "Gateway", href: "/docs/deployment/aws-serverless", icon: <FaAws /> },
      { name: "Azure Functions", role: "Serverless", href: "/docs/deployment/azure-serverless", icon: <VscAzure /> },
      { name: "Azure Container Apps", role: "Containers", href: "/docs/deployment/azure-containerized", icon: <VscAzure /> },
      { name: "Azure API Management", role: "Gateway", href: "/docs/deployment/azure-serverless", icon: <VscAzure /> },
      { name: "Google Cloud Run", role: "Serverless & containers", href: "/docs/deployment/gcp-serverless", icon: <SiGooglecloud /> },
      { name: "GCP API Gateway", role: "Gateway", href: "/docs/deployment/gcp-serverless", icon: <SiGooglecloud /> },
      { name: "Kubernetes", role: "On-prem", href: K8S, icon: <SiKubernetes /> },
      { name: "Helm", role: "Chart", href: K8S, icon: <SiHelm /> },
      { name: "KEDA", role: "Autoscaling", href: K8S, logo: "/img/integrations/keda.svg" },
      { name: "Terraform", role: "Infrastructure as code", href: "/docs/deployment/overview", icon: <SiTerraform /> },
      { name: "Amazon SQS", role: "Queue", href: QUEUE, icon: <FaAws /> },
      { name: "Apache Kafka", role: "Queue", href: QUEUE, icon: <SiApachekafka /> },
      { name: "NATS JetStream", role: "Queue", href: QUEUE, icon: <SiNatsdotio /> },
      { name: "Amazon EventBridge", role: "Scheduler", href: "/docs/advanced/scheduling", icon: <FaAws /> },
      // The secrets page is only in the unreleased docs until the next release; drop `next` once it ships.
      { name: "AWS Systems Manager", role: "Secrets", href: "/docs/next/advanced/secrets", icon: <FaAws />, title: "AWS Systems Manager: Parameter Store secrets and EC2 sandbox attach" },
      { name: "Docker", role: "Sandbox", href: SANDBOX, icon: <SiDocker /> },
      { name: "E2B", role: "Sandbox", href: SANDBOX, logo: "/img/integrations/e2b.png" },
      { name: "Daytona", role: "Sandbox", href: SANDBOX, logo: "/img/integrations/daytona.png" },
    ],
  },
  {
    title: "Observability, safety & testing",
    secondsPerTile: 2.8,
    items: [
      { name: "Langfuse", role: "Tracing", href: TRACE, logo: "/img/integrations/langfuse.png" },
      { name: "OpenLLMetry", role: "Tracing", href: TRACE, logo: "/img/integrations/traceloop.png" },
      { name: "Pydantic Logfire", role: "Tracing", href: TRACE, icon: <SiPydantic /> },
      { name: "OpenTelemetry", role: "Tracing", href: TRACE, icon: <SiOpentelemetry /> },
      { name: "OpenAI Guardrails", role: "Guardrail", href: "/docs/advanced/guardrails-openai", logo: "/img/integrations/openai.svg", mono: true },
      { name: "Amazon Bedrock Guardrails", role: "Guardrail", href: "/docs/advanced/guardrails-bedrock", logo: "/img/integrations/bedrock.png" },
      { name: "Walled AI", role: "Guardrail", href: "/docs/advanced/guardrails-walledai", logo: "/img/integrations/walledai.svg" },
      { name: "DeepEval", role: "Evaluator", href: TESTING, logo: "/img/integrations/deepeval.svg" },
      { name: "Opik", role: "Evaluator", href: TESTING, logo: "/img/integrations/opik.svg", wide: true },
      { name: "TypeSafe JEV", role: "Evaluator", href: TESTING, logo: "/img/integrations/typesafe.png" },
      { name: "LiteLLM", role: "LLM gateway", href: "/docs/advanced/multimodal", logo: "/img/integrations/litellm.png" },
    ],
  },
];
