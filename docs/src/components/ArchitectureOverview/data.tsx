import React from "react";
import { FaAws } from "react-icons/fa";
import { VscAzure } from "react-icons/vsc";
import { SiGooglecloud } from "react-icons/si";
import { TbBrowser, TbClockHour4, TbDeviceMobile, TbTerminal2 } from "react-icons/tb";
import { INTEGRATION_ROWS, type IntegrationItem } from "../HomeSections/integrations.data";

/** One icon in a card's chip row. Vendor chips are picked from the marquee data so every logo lives in one place. */
export type Chip = Pick<IntegrationItem, "name" | "href" | "logo" | "icon" | "mono">;

export interface ArchCard {
  title: string;
  chips: Chip[];
}

export interface CorePill {
  label: string;
  href: string;
}

export interface FlowWord {
  word: string;
  /** Rendered in the accent colour, the way agentgateway highlights one word of its flow line. */
  accent?: boolean;
}

const ALL_INTEGRATIONS = INTEGRATION_ROWS.flatMap((row) => row.items);

/** Reuse marquee tiles by name. A typo fails the build (this runs during static rendering) instead of dropping a chip silently. */
function pick(...names: string[]): Chip[] {
  return names.map((name) => {
    const item = ALL_INTEGRATIONS.find((candidate) => candidate.name === name);
    if (!item) {
      throw new Error(`ArchitectureOverview: no integration named "${name}" in the integration data`);
    }
    return item;
  });
}

export const SOURCES_LABEL = "Sources · channels and clients";
export const CORE_LABEL = "The runtime";
export const DESTINATIONS_LABEL = "Destinations · agents, data and clouds";

export const SOURCES: ArchCard[] = [
  {
    title: "Messaging channels",
    chips: pick("Slack", "Microsoft Teams", "WhatsApp", "Messenger", "Instagram", "Telegram", "Gmail"),
  },
  {
    title: "Protocols and APIs",
    chips: pick("REST & SSE", "WebSocket", "MCP", "A2A", "AG-UI"),
  },
  {
    title: "Apps, voice and schedules",
    chips: [
      { name: "Web apps", href: "/docs/api/rest-api", icon: <TbBrowser /> },
      { name: "Mobile apps", href: "/docs/api/rest-api", icon: <TbDeviceMobile /> },
      { name: "CLI", href: "/docs/quick-start", icon: <TbTerminal2 /> },
      ...pick("LiveKit"),
      { name: "Scheduled tasks", href: "/docs/advanced/scheduling", icon: <TbClockHour4 /> },
    ],
  },
];

export const DESTINATIONS: ArchCard[] = [
  {
    title: "Agent frameworks",
    chips: pick("OpenAI Agents SDK", "LangGraph", "CrewAI", "Google ADK", "Smolagents", "Pydantic AI", "Microsoft Agent Framework", "Claude Agent SDK"),
  },
  {
    title: "Memory and knowledge",
    chips: pick("Redis", "Valkey", "Amazon DynamoDB", "Azure Cosmos DB", "Google Firestore", "ChromaDB", "Neo4j"),
  },
  {
    title: "Clouds and observability",
    chips: [
      { name: "AWS", href: "/docs/deployment/aws-serverless", icon: <FaAws /> },
      { name: "Microsoft Azure", href: "/docs/deployment/azure-serverless", icon: <VscAzure /> },
      { name: "Google Cloud", href: "/docs/deployment/gcp-serverless", icon: <SiGooglecloud /> },
      ...pick("Kubernetes", "Langfuse", "OpenTelemetry"),
    ],
  },
];

/** The four runtime capabilities shown around the core, clockwise from top-left. */
export const CORE_PILLS: CorePill[] = [
  { label: "Sessions and memory", href: "/docs/core-concepts/session" },
  { label: "Hooks and guardrails", href: "/docs/advanced/guardrails" },
  { label: "Sandbox and scheduling", href: "/docs/advanced/sandbox" },
  { label: "Queue pipeline and scaling", href: "/docs/advanced/queue-mode-guide" },
];

/** The four capabilities named around the core. */
export const FLOW_WORDS: FlowWord[] = [
  { word: "Build" },
  { word: "Connect" },
  { word: "Remember" },
  { word: "Guard" },
  { word: "Scale" },
  { word: "Observe" },
];
