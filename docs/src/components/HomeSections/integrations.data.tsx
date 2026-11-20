import React from "react";
import { FaAws, FaMicrosoft } from "react-icons/fa";
import { VscAzure } from "react-icons/vsc";
import { TbBrandSlack, TbBrandTeams, TbPlugConnected } from "react-icons/tb";
import {
  SiApachekafka,
  SiAuth0,
  SiClaude,
  SiCrewai,
  SiCursor,
  SiDocker,
  SiFastapi,
  SiFirebase,
  SiGithubcopilot,
  SiGmail,
  SiGooglecloud,
  SiGooglepubsub,
  SiHelm,
  SiInstagram,
  SiKeycloak,
  SiKubernetes,
  SiLanggraph,
  SiMessenger,
  SiModelcontextprotocol,
  SiNatsdotio,
  SiNeo4J,
  SiOkta,
  SiOpenid,
  SiOpentelemetry,
  SiPydantic,
  SiRedis,
  SiTelegram,
  SiTerraform,
  SiTrino,
  SiWhatsapp,
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
const IDENTITY = "/docs/advanced/identity-and-access";

export const INTEGRATION_ROWS: IntegrationRow[] = [
  {
    title: "Agent frameworks & dev tools",
    items: [
      { name: "OpenAI Agents SDK", role: "Framework", href: "/docs/frameworks/openai", logo: "/img/integrations/openai.svg", mono: true },
      { name: "LangGraph", role: "Framework", href: "/docs/frameworks/langgraph", icon: <SiLanggraph /> },
      { name: "CrewAI", role: "Framework", href: "/docs/frameworks/crewai", icon: <SiCrewai /> },
      { name: "Google ADK", role: "Framework", href: "/docs/frameworks/google-adk", logo: "/img/integrations/adk.png" },
      { name: "Smolagents", role: "Framework", href: "/docs/frameworks/smolagents", logo: "/img/integrations/smolagents.svg" },
      { name: "Pydantic AI", role: "Framework", href: "/docs/frameworks/pydantic-ai", icon: <SiPydantic /> },
      // Drop /next after the Claude Agent SDK adapter is released.
      { name: "Claude Agent SDK", role: "Framework", href: "/docs/next/frameworks/claude-agent-sdk", icon: <SiClaude /> },
      { name: "Microsoft Agent Framework", role: "Framework", href: "/docs/next/frameworks/microsoft-agents", icon: <FaMicrosoft /> },
      { name: "Claude Code", role: "Agent skills", href: SKILLS, icon: <SiClaude /> },
      { name: "Cursor", role: "Agent skills", href: SKILLS, icon: <SiCursor /> },
      { name: "Codex", role: "Agent skills", href: SKILLS, logo: "/img/integrations/openai.svg", mono: true },
      { name: "Windsurf", role: "Agent skills", href: SKILLS, icon: <SiWindsurf /> },
      { name: "GitHub Copilot", role: "Agent skills", href: SKILLS, icon: <SiGithubcopilot /> },
    ],
  },
  {
    title: "Channels & protocols",
    items: [
      { name: "Slack", role: "Channel", href: "/docs/integrations/slack", icon: <TbBrandSlack /> },
      { name: "Microsoft Teams", role: "Channel", href: "/docs/integrations/teams", icon: <TbBrandTeams /> },
      { name: "WhatsApp", role: "Channel", href: "/docs/integrations/whatsapp", icon: <SiWhatsapp /> },
      { name: "Messenger", role: "Channel", href: "/docs/integrations/messenger", icon: <SiMessenger /> },
      { name: "Instagram", role: "Channel", href: "/docs/integrations/instagram", icon: <SiInstagram /> },
      { name: "Telegram", role: "Channel", href: "/docs/integrations/telegram", icon: <SiTelegram /> },
      { name: "Gmail", role: "Channel", href: "/docs/integrations/gmail", icon: <SiGmail /> },
      // Drop /next after the LiveKit integration is released.
      { name: "LiveKit", role: "Voice integration", href: "/docs/next/integrations/livekit", logo: "/img/integrations/livekit-mark.svg", mono: true },
      { name: "MCP", role: "Protocol", href: "/docs/api/mcp-server", icon: <SiModelcontextprotocol /> },
      { name: "A2A", role: "Protocol", href: "/docs/api/a2a-server", logo: "/img/integrations/a2a-white.svg", mono: true },
      { name: "AG-UI", role: "Protocol", href: "/docs/api/agui-server", logo: "/img/integrations/agui.svg", mono: true },
      { name: "REST & SSE", role: "API", href: "/docs/api/rest-api", icon: <SiFastapi /> },
      { name: "WebSocket", role: "API", href: "/docs/api/rest-api", icon: <TbPlugConnected /> },
    ],
  },
  {
    title: "Memory, knowledge & data",
    items: [
      { name: "Redis", role: "Memory", href: SESSION, icon: <SiRedis />, title: "Redis: session, thread, attachment, response, schedule and agent registry stores" },
      { name: "Valkey", role: "Memory", href: SESSION, logo: "/img/integrations/valkey.svg", mono: true, title: "Valkey: session, thread, response, schedule and agent registry stores" },
      { name: "Amazon DynamoDB", role: "Memory", href: SESSION, icon: <FaAws />, title: "Amazon DynamoDB: session, thread, attachment, response, schedule and agent registry stores" },
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
    items: [
      { name: "AWS Lambda", role: "Serverless", href: "/docs/deployment/aws-serverless", icon: <FaAws /> },
      { name: "Amazon ECS Fargate", role: "Containers", href: "/docs/deployment/aws-containerized", icon: <FaAws /> },
      { name: "Amazon API Gateway", role: "Gateway", href: "/docs/deployment/aws-serverless", icon: <FaAws /> },
      { name: "Azure Container Apps", role: "Containers", href: "/docs/deployment/azure-containerized", icon: <VscAzure /> },
      { name: "Azure API Management", role: "Gateway", href: "/docs/deployment/azure-containerized", icon: <VscAzure /> },
      { name: "Google Cloud Run", role: "Serverless & containers", href: "/docs/deployment/gcp-serverless", icon: <SiGooglecloud /> },
      { name: "GCP API Gateway", role: "Gateway", href: "/docs/deployment/gcp-serverless", icon: <SiGooglecloud /> },
      { name: "Kubernetes", role: "On-prem", href: K8S, icon: <SiKubernetes />, title: "Kubernetes: on-prem deployment and mounted Secrets" },
      { name: "Helm", role: "Chart", href: K8S, icon: <SiHelm /> },
      { name: "KEDA", role: "Autoscaling", href: K8S, logo: "/img/integrations/keda.svg" },
      { name: "Terraform", role: "Infrastructure as code", href: "/docs/deployment/overview", icon: <SiTerraform /> },
      { name: "Amazon SQS", role: "Queue", href: QUEUE, icon: <FaAws /> },
      { name: "Apache Kafka", role: "Queue", href: QUEUE, icon: <SiApachekafka /> },
      { name: "NATS JetStream", role: "Queue", href: QUEUE, icon: <SiNatsdotio /> },
      { name: "Google Cloud Pub/Sub", role: "Queue", href: QUEUE, icon: <SiGooglepubsub /> },
      { name: "Azure Service Bus", role: "Queue", href: QUEUE, icon: <VscAzure /> },
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
    items: [
      { name: "Langfuse", role: "Tracing", href: TRACE, logo: "/img/integrations/langfuse.png" },
      { name: "OpenLLMetry", role: "Tracing", href: TRACE, logo: "/img/integrations/traceloop.png" },
      { name: "Pydantic Logfire", role: "Tracing", href: TRACE, icon: <SiPydantic /> },
      { name: "Amazon CloudWatch", role: "Tracing", href: TRACE, icon: <FaAws /> },
      { name: "OpenTelemetry", role: "Tracing", href: TRACE, icon: <SiOpentelemetry /> },
      { name: "OpenAI Guardrails", role: "Guardrail", href: "/docs/advanced/guardrails-openai", logo: "/img/integrations/openai.svg", mono: true },
      { name: "Amazon Bedrock Guardrails", role: "Guardrail", href: "/docs/advanced/guardrails-bedrock", logo: "/img/integrations/bedrock.png" },
      { name: "Walled AI", role: "Guardrail", href: "/docs/advanced/guardrails-walledai", logo: "/img/integrations/walledai.svg" },
      { name: "OpenID Connect", role: "Identity", href: IDENTITY, icon: <SiOpenid />, title: "OpenID Connect: any OIDC issuer through the oidc identity provider" },
      { name: "Auth0", role: "Identity", href: IDENTITY, icon: <SiAuth0 />, title: "Auth0: an oidc identity provider configuration" },
      { name: "Okta", role: "Identity", href: IDENTITY, icon: <SiOkta />, title: "Okta: an oidc identity provider configuration" },
      { name: "Keycloak", role: "Identity", href: IDENTITY, icon: <SiKeycloak />, title: "Keycloak: an oidc identity provider configuration" },
      { name: "Amazon Cognito", role: "Identity", href: IDENTITY, icon: <FaAws /> },
      { name: "Microsoft Entra ID", role: "Identity", href: IDENTITY, icon: <FaMicrosoft /> },
      { name: "Firebase Authentication", role: "Identity", href: IDENTITY, icon: <SiFirebase /> },
      { name: "DeepEval", role: "Evaluator", href: TESTING, logo: "/img/integrations/deepeval.svg" },
      { name: "Opik", role: "Evaluator", href: TESTING, logo: "/img/integrations/opik.svg", mono: true, wide: true },
      { name: "TypeSafe JEV", role: "Evaluator", href: TESTING, logo: "/img/integrations/typesafe.png" },
      { name: "LiteLLM", role: "LLM gateway", href: "/docs/advanced/multimodal", logo: "/img/integrations/litellm.png", mono: true },
    ],
  },
];
