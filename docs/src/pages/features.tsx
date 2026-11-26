import React, { useEffect, useRef, useState } from 'react';
import useBrokenLinks from '@docusaurus/useBrokenLinks';
import Link from '@docusaurus/Link';
import Layout from '@theme/Layout';
import clsx from 'clsx';
import PageHero from '@site/src/components/ui/PageHero';
import SectionHeader from '@site/src/components/ui/SectionHeader';
import Reveal from '@site/src/components/ui/Reveal';
import { ClosingPanel } from '@site/src/components/HomeSections';
import { StageMotion, type Stage as StageId } from '@site/src/components/VectorMotion';
import SandboxFlowDiagram from '@site/src/components/SandboxFlowDiagram';
import AccessFlowDiagram from '@site/src/components/AccessFlowDiagram';
import styles from './features.module.css';

/* The page is a reference: every capability of the runtime, grouped by the six stages the home
   page introduces, each with the guide to read next. The home page says what a stage is for;
   this page lists what is in it. A capability appears once, under the stage it belongs to. */

type DocLink = { label: string; to: string };

type Capability = {
  title: string;
  summary: string;
  /** What is included: short phrases, four at most. */
  points?: string[];
  /** The guide to read next. */
  guide: DocLink;
  /** Further pages on the same capability, listed by name. */
  more?: DocLink[];
};

type StageGroup = {
  id: StageId;
  name: string;
  title: string;
  lead: string;
  capabilities: Capability[];
};

const STAGES: StageGroup[] = [
  {
    id: 'build',
    name: 'Build',
    title: 'Agents, tools and frameworks',
    lead: 'What you write, and what the runtime wraps around it.',
    capabilities: [
      {
        title: 'Core abstractions',
        summary:
          'Agent, Runner, Session, Module, Runtime and Tools: six abstractions that give every framework the same Python API.',
        guide: { label: 'Core concepts', to: '/docs/core-concepts/overview' },
        more: [
          { label: 'Agent', to: '/docs/core-concepts/agent' },
          { label: 'Runner', to: '/docs/core-concepts/runner' },
          { label: 'Module', to: '/docs/core-concepts/module' },
          { label: 'Runtime', to: '/docs/core-concepts/runtime' },
        ],
      },
      {
        title: 'Framework adapters',
        summary:
          'Adapters for eight agent frameworks. An agent keeps its native code, and moving it to another framework changes the adapter import, not the platform around it.',
        guide: { label: 'Frameworks overview', to: '/docs/frameworks/overview' },
        more: [
          { label: 'OpenAI Agents SDK', to: '/docs/frameworks/openai' },
          { label: 'LangGraph', to: '/docs/frameworks/langgraph' },
          { label: 'CrewAI', to: '/docs/frameworks/crewai' },
          { label: 'Google ADK', to: '/docs/frameworks/google-adk' },
          { label: 'Smolagents', to: '/docs/frameworks/smolagents' },
          { label: 'Pydantic AI', to: '/docs/frameworks/pydantic-ai' },
          { label: 'Claude Agent SDK', to: '/docs/frameworks/claude-agent-sdk' },
          { label: 'Microsoft Agent Framework', to: '/docs/frameworks/microsoft-agents' },
        ],
      },
      {
        title: 'Several frameworks in one runtime',
        summary:
          'Register agents from different frameworks in the same process and reach them through one API, with no glue code between them.',
        guide: { label: 'Multi-framework guide', to: '/docs/frameworks/multi-framework' },
      },
      {
        title: 'Portable tools',
        summary:
          "Write a tool once as a plain Python function. ToolBuilder binds it to each framework's own tool type.",
        guide: { label: 'Tools', to: '/docs/core-concepts/tools' },
      },
      {
        title: 'Execution hooks',
        summary: 'Pre-hooks and post-hooks run around every agent request, on any framework.',
        points: [
          'Pre-hooks for guardrails, retrieval, authentication and validation',
          'Post-hooks for moderation, disclaimers and analytics',
          'Hooks chain, and a pre-hook can end a request with its own reply',
          'Run on realtime voice calls too',
        ],
        guide: { label: 'Hooks', to: '/docs/integrations/hooks' },
      },
      {
        title: 'Multi-agent systems',
        summary: 'Supervisor, peer-to-peer and pipeline patterns for agents that work together.',
        guide: { label: 'Multi-agent systems', to: '/docs/advanced/multi-agent' },
      },
      {
        title: 'Multimodal input',
        summary:
          "Users send images and files with their text. The runtime describes them, stores them and adds them to the agent's context.",
        guide: { label: 'Multimodal attachments', to: '/docs/advanced/multimodal' },
      },
      {
        title: 'Agent skills',
        summary:
          'Guides in the Agent Skills open standard that coding assistants such as Claude Code, GitHub Copilot and Codex follow to build, extend and deploy OAK agents.',
        guide: { label: 'Agent skills', to: '/docs/agent-skills' },
      },
      {
        title: 'Configuration',
        summary:
          'Stores, providers and execution modes are chosen in a YAML or JSON configuration file, or through environment variables. The agent code does not change.',
        guide: { label: 'Configuration', to: '/docs/core-concepts/configuration' },
      },
    ],
  },
  {
    id: 'connect',
    name: 'Connect',
    title: 'Channels, protocols and APIs',
    lead: 'The ways a request reaches an agent. Each one is an adapter around the same runtime.',
    capabilities: [
      {
        title: 'Messaging channels',
        summary: 'Built-in handlers for seven messaging platforms, each with its own setup guide.',
        guide: { label: 'Integrations overview', to: '/docs/integrations/overview' },
        more: [
          { label: 'Slack', to: '/docs/integrations/slack' },
          { label: 'Microsoft Teams', to: '/docs/integrations/teams' },
          { label: 'WhatsApp', to: '/docs/integrations/whatsapp' },
          { label: 'Messenger', to: '/docs/integrations/messenger' },
          { label: 'Telegram', to: '/docs/integrations/telegram' },
          { label: 'Instagram', to: '/docs/integrations/instagram' },
          { label: 'Gmail', to: '/docs/integrations/gmail' },
        ],
      },
      {
        title: 'Realtime voice',
        summary:
          "LiveKit rooms for OpenAI Agents SDK and Google ADK agents. The gateway sends the user's audio to the agent and plays the streamed reply back to the room.",
        guide: { label: 'LiveKit voice', to: '/docs/integrations/livekit' },
      },
      {
        title: 'REST API',
        summary: 'A built-in REST server for talking to agents.',
        points: [
          'Chat, agent listing and health endpoints',
          'Streaming replies',
          'Images and files as input',
          'Custom routes and authentication',
        ],
        guide: { label: 'REST API', to: '/docs/api/rest-api' },
      },
      {
        title: 'Agent registry and catalog',
        summary:
          'Every agent carries one descriptor, declared in code or in configuration. The agent catalog, A2A cards, MCP tools and the AG-UI listing are all built from it.',
        points: [
          'Name, version, description, owner, tags, skills and tools',
          'A catalog at GET /api/v1/agents, with a tag filter and pagination',
          'Each agent chooses the surfaces it is served on',
          'In-memory, Redis, Valkey or DynamoDB backend',
        ],
        // The agent registry is only in the unreleased docs until the next release: drop `next` once it ships.
        guide: { label: 'Agent registry', to: '/docs/next/core-concepts/configuration#agent-registry' },
      },
      {
        title: 'MCP server',
        summary:
          'Expose agents as Model Context Protocol tools, each described by the text you declare for its agent, so any MCP client can call them.',
        guide: { label: 'MCP server', to: '/docs/api/mcp-server' },
      },
      {
        title: 'A2A server',
        summary:
          'Serve agents over the Agent-to-Agent protocol, with a card for each agent built from its registry descriptor, so other agents can delegate work to them.',
        guide: { label: 'A2A server', to: '/docs/api/a2a-server' },
      },
      {
        title: 'AG-UI',
        summary:
          'Serve agents over AG-UI, the event-based protocol for user-facing frontends such as CopilotKit or a client of your own.',
        guide: { label: 'AG-UI server', to: '/docs/api/agui-server' },
        more: [{ label: 'AG-UI integration', to: '/docs/integrations/agui' }],
      },
      {
        title: 'A2UI',
        summary:
          'An agent can answer with an interface in place of prose. OAK labels the A2UI payload and carries it intact over REST, MCP and AG-UI, and your client draws it with its own components.',
        guide: { label: 'A2UI', to: '/docs/advanced/a2ui' },
      },
    ],
  },
  {
    id: 'remember',
    name: 'Remember',
    title: 'Sessions, memory and knowledge',
    lead: 'State that outlives a request, kept in stores you select in configuration.',
    capabilities: [
      {
        title: 'Sessions',
        summary: 'Conversation history and agent state, kept across turns in the store you choose.',
        points: ['In-memory, Redis, Valkey, DynamoDB, Cosmos DB and Firestore'],
        guide: { label: 'Session', to: '/docs/core-concepts/session' },
        more: [{ label: 'Choosing a memory backend', to: '/docs/core-concepts/memory-backends' }],
      },
      {
        title: 'Volatile and non-volatile caches',
        summary:
          'Two caches with one API. The volatile cache clears after each request, and the non-volatile cache lasts for the session. Both hold data without sending it to the model.',
        guide: { label: 'Memory management', to: '/docs/architecture/memory-management' },
      },
      {
        title: 'Conversation threads',
        summary:
          "Every exchange is recorded against its session and can be read back over REST, so an interface can show a user's conversations and their history.",
        guide: { label: 'Conversation threads', to: '/docs/advanced/threads' },
      },
      {
        title: 'Knowledge bases',
        summary: 'Retrieval over curated knowledge sources, behind one interface.',
        points: [
          'ChromaDB for vector and semantic search',
          'Neo4j for entity and relationship graphs',
          'Starburst Galaxy for SQL over MongoDB, Sheets and PostgreSQL',
          'Open Knowledge Format: markdown bundles, with no database to run',
        ],
        guide: { label: 'Knowledge bases', to: '/docs/advanced/knowledge-bases' },
      },
    ],
  },
  {
    id: 'guard',
    name: 'Guard',
    title: 'Guardrails, identity and sandboxes',
    lead: 'Policy the runtime enforces on every request, so it is not rebuilt in each agent.',
    capabilities: [
      {
        title: 'Guardrails',
        summary: 'Input and output guardrails, applied through the execution hooks.',
        points: ['PII detection and redaction', 'Jailbreak prevention', 'Content moderation and off-topic filtering'],
        guide: { label: 'Guardrails', to: '/docs/advanced/guardrails' },
        more: [
          { label: 'OpenAI', to: '/docs/advanced/guardrails-openai' },
          { label: 'Amazon Bedrock', to: '/docs/advanced/guardrails-bedrock' },
          { label: 'Walled AI', to: '/docs/advanced/guardrails-walledai' },
        ],
      },
      {
        title: 'Identity and access',
        summary:
          'One identity provider, set in configuration, authenticates every surface and gives tools, hooks and threads the caller as a principal.',
        points: [
          'Any OpenID Connect issuer, such as Auth0, Keycloak or Okta',
          'Amazon Cognito, Microsoft Entra ID and Firebase',
          'REST, WebSocket, AG-UI, MCP, A2A, the CLI and messaging',
        ],
        guide: { label: 'Identity and access', to: '/docs/advanced/identity-and-access' },
      },
      {
        title: 'Authorization',
        summary:
          'Grants in configuration decide which agents each caller may run and see, and which of their tools. A caller is listed only its own agents, and an agent hidden from it answers like one that does not exist.',
        points: [
          'Grants for users, groups, roles and messaging senders, at read, write or admin',
          'Private, internal and public agents',
          'The same answer on REST, A2A, MCP and AG-UI',
          'A tool policy every framework adapter enforces, voice calls included',
        ],
        // Drop `next` from the path once a release carries the Authorization section.
        guide: { label: 'Authorization', to: '/docs/next/advanced/identity-and-access#authorization' },
      },
      {
        title: 'Secret resolution',
        summary:
          'Code asks for a key by name. It comes from the environment on a laptop, from AWS SSM Parameter Store on AWS, and from Kubernetes Secrets in a cluster, with only the configuration changing.',
        guide: { label: 'Secret resolution', to: '/docs/advanced/secrets' },
      },
      {
        title: 'Human in the loop',
        summary:
          "A run can pause for a person's decision and continue from the answer minutes or hours later, on whichever replica receives it.",
        guide: { label: 'Human in the loop', to: '/docs/advanced/human-in-the-loop' },
      },
      {
        title: 'Sandboxed code execution',
        summary:
          'Agents run code, shell commands and file operations in isolated sandboxes. The Execution Broker routes each execution to a policy-governed provider.',
        points: [
          'Six providers: local_subprocess, docker, kubernetes, e2b, daytona and ec2_ssm',
          'A queue broker for executions that outlive the agent turn',
          'Fail-closed network, filesystem, CPU and memory policies',
        ],
        guide: { label: 'Sandbox', to: '/docs/advanced/sandbox' },
        more: [{ label: 'A closer look, below', to: '#sandbox' }],
      },
    ],
  },
  {
    id: 'scale',
    name: 'Scale',
    title: 'Deployment, queues and resilience',
    lead: 'The same agent code, from one process on a laptop to a queue-backed fleet.',
    capabilities: [
      {
        title: 'Deployment targets',
        summary:
          'Terraform modules for AWS, Azure and Google Cloud, and a Helm chart for Kubernetes on your own infrastructure.',
        guide: { label: 'Deployment overview', to: '/docs/deployment/overview' },
        more: [
          { label: 'Local', to: '/docs/deployment/local' },
          { label: 'AWS Lambda', to: '/docs/deployment/aws-serverless' },
          { label: 'Amazon ECS Fargate', to: '/docs/deployment/aws-containerized' },
          { label: 'Azure Container Apps', to: '/docs/deployment/azure-containerized' },
          { label: 'Cloud Run, serverless', to: '/docs/deployment/gcp-serverless' },
          { label: 'Cloud Run, containers', to: '/docs/deployment/gcp-containerized' },
          { label: 'Kubernetes', to: '/docs/deployment/onprem-kubernetes' },
        ],
      },
      {
        title: 'Queue mode',
        summary:
          'A chat request can travel through queues: request handler, input queue, agent runner, output queue, response handler. Ingress and agent execution then scale separately.',
        points: ['SQS, Kafka, NATS JetStream, Google Cloud Pub/Sub and Azure Service Bus transports'],
        guide: { label: 'Queue mode guide', to: '/docs/advanced/queue-mode-guide' },
        more: [{ label: 'Queue mode on AWS', to: '/docs/deployment/aws-queue-mode-scalability' }],
      },
      {
        title: 'Fault tolerance',
        summary:
          'Resilience in every deployment mode: multi-AZ deployments, automatic recovery, health monitoring and zero-downtime rollouts, with conversation state preserved across failures.',
        guide: { label: 'Fault tolerance', to: '/docs/core-concepts/fault-tolerance' },
      },
      {
        title: 'Scheduled tasks',
        summary:
          'A chat request that carries a schedule is registered, not run. When an occurrence is due, the stored prompt enters the normal execution path.',
        guide: { label: 'Scheduled tasks', to: '/docs/advanced/scheduling' },
      },
      {
        title: 'Execution flow',
        summary: 'How a request moves through the runtime: synchronously, streamed, or through queues.',
        guide: { label: 'Execution flow', to: '/docs/architecture/execution-flow' },
      },
    ],
  },
  {
    id: 'observe',
    name: 'Observe',
    title: 'Tracing, testing and evaluation',
    lead: 'See what an agent did, and test it like any other code.',
    capabilities: [
      {
        title: 'Tracing',
        summary: 'Traces of agent runs, model calls and tool calls, switched on in configuration.',
        points: [
          'Langfuse, OpenLLMetry, Pydantic Logfire and AWS CloudWatch',
          'Latency, token usage and cost per run',
          'Spans can be fetched back for evaluation',
        ],
        guide: { label: 'Traceability', to: '/docs/advanced/traceability' },
      },
      {
        title: 'CLI testing',
        summary: 'Interactive chat sessions against one agent or several, for quick iteration during development.',
        guide: { label: 'CLI testing', to: '/docs/testing/cli-testing' },
      },
      {
        title: 'Automated tests',
        summary:
          'Test suites that plug into pytest and run in CI, with session-scoped fixtures and ordered execution.',
        guide: { label: 'Automated testing', to: '/docs/testing/automated-testing' },
      },
      {
        title: 'Comparison modes',
        summary: 'Three ways to compare a reply with the expected answer.',
        points: [
          'Score: deterministic and offline, with no model call',
          'LLM: a model judges whether the reply means the same',
          'Fallback: score first, then LLM. This is the default',
        ],
        guide: { label: 'Testing overview', to: '/docs/testing/overview' },
        more: [
          { label: 'Score mode', to: '/docs/testing/cli-testing#score-mode' },
          { label: 'LLM mode', to: '/docs/testing/cli-testing#llm-mode' },
          { label: 'Fallback mode', to: '/docs/testing/cli-testing#fallback-mode-default' },
        ],
      },
      {
        title: 'Pluggable evaluators',
        summary:
          'Every comparison runs through an evaluator. DeepEval, Opik and JEV are built in, and your own AKEvaluator subclass is selected in test-config.yaml.',
        guide: { label: 'Bring your own evaluator', to: '/docs/testing/cli-testing#bring-your-own-evaluator' },
      },
    ],
  },
];

const STAGE_IDS = STAGES.map((stage) => stage.id);
const CAPABILITY_COUNT = STAGES.reduce((sum, stage) => sum + stage.capabilities.length, 0);

/** The stage whose section is under the reader's eye, for the page index. */
function useStageInView(): StageId {
  const [inView, setInView] = useState<StageId>(STAGE_IDS[0]);

  useEffect(() => {
    if (!('IntersectionObserver' in window)) return undefined;
    // A thin band a quarter of the way down the view: the section that crosses it is the current one.
    const seen = new IntersectionObserver(
      (entries) => {
        const crossing = entries.find((entry) => entry.isIntersecting);
        if (crossing) setInView(crossing.target.id as StageId);
      },
      { rootMargin: '-25% 0px -70% 0px' },
    );
    STAGE_IDS.forEach((id) => {
      const section = document.getElementById(id);
      if (section) seen.observe(section);
    });
    return () => seen.disconnect();
  }, []);

  return inView;
}

function StageIndex({ current }: { current: StageId }): JSX.Element {
  const list = useRef<HTMLOListElement>(null);

  // On a small screen the index is one row that scrolls sideways: keep the current stage in it.
  // The row is moved directly, so the page itself never scrolls.
  useEffect(() => {
    const row = list.current;
    const link = row?.querySelector<HTMLElement>('[aria-current="true"]');
    if (!row || !link || row.scrollWidth <= row.clientWidth) return;
    const left = link.offsetLeft - row.offsetLeft;
    if (left < row.scrollLeft || left + link.offsetWidth > row.scrollLeft + row.clientWidth) {
      const still = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
      row.scrollTo({ left: Math.max(0, left - 16), behavior: still ? 'auto' : 'smooth' });
    }
  }, [current]);

  return (
    <nav className={styles.index} aria-label="Stages on this page">
      <p className="ak-label">On this page</p>
      <ol ref={list} className={styles.indexList}>
        {STAGES.map((stage, position) => (
          <li key={stage.id}>
            <a
              href={`#${stage.id}`}
              className={clsx(styles.indexLink, stage.id === current && styles.indexLinkCurrent)}
              aria-current={stage.id === current ? 'true' : undefined}
            >
              <span className={styles.indexNumber}>{String(position + 1).padStart(2, '0')}</span>
              <span>{stage.name}</span>
              <span className={styles.indexCount} aria-label={`${stage.capabilities.length} capabilities`}>
                {stage.capabilities.length}
              </span>
            </a>
          </li>
        ))}
      </ol>
    </nav>
  );
}

function CapabilityEntry({ item }: { item: Capability }): JSX.Element {
  return (
    <li className={styles.capability}>
      <h3 className="ak-h4">{item.title}</h3>
      <p className={styles.summary}>{item.summary}</p>
      {item.points && (
        <ul className={styles.points}>
          {item.points.map((point) => (
            <li key={point}>{point}</li>
          ))}
        </ul>
      )}
      {item.more && (
        <ul className={styles.more} aria-label={`${item.title}: more pages`}>
          {item.more.map((link) => (
            <li key={link.to}>
              <Link to={link.to}>{link.label}</Link>
            </li>
          ))}
        </ul>
      )}
      <Link to={item.guide.to} className={clsx('ak-link', styles.guide)}>
        {item.guide.label}
      </Link>
    </li>
  );
}

function StageSection({ stage, position }: { stage: StageGroup; position: number }): JSX.Element {
  return (
    <Reveal as="section" id={stage.id} className={styles.stage}>
      <div className={styles.stageHead}>
        <SectionHeader
          index={String(position + 1).padStart(2, '0')}
          label={stage.name}
          title={stage.title}
          lead={stage.lead}
        />
        <StageMotion stage={stage.id} className={styles.stageArt} />
      </div>
      <ul className={styles.capabilities}>
        {stage.capabilities.map((item) => (
          <CapabilityEntry key={item.title} item={item} />
        ))}
      </ul>
    </Reveal>
  );
}

/** Two capabilities get a diagram: the sandbox and access control are the ones whose moving parts need a picture. */
function SandboxCloserLook(): JSX.Element {
  // Tell the build that this id exists, so links to it are checked.
  useBrokenLinks().collectAnchor('sandbox');
  return (
    <section id="sandbox" className={clsx('ak-section', 'ak-section--raised', styles.closer)}>
      <div className="ak-container">
        <SectionHeader
          label="A closer look"
          title="Where agent-written code runs"
          lead="Every execution goes through the Execution Broker to a provider you choose in configuration: in the agent process for CLI and REST deployments, or over a queue to a fleet of sandbox workers that keeps running after the agent turn ends."
        />
        <SandboxFlowDiagram detailed />
        <ul className={styles.closerLinks}>
          <li>
            <Link to="/docs/advanced/sandbox" className="ak-link">
              Sandbox guide
            </Link>
          </li>
          <li>
            <Link to="/docs/advanced/sandbox#the-queue-flavor" className="ak-link">
              The queue broker
            </Link>
          </li>
          <li>
            <Link to="/docs/architecture/sandbox-internals" className="ak-link">
              Sandbox internals
            </Link>
          </li>
        </ul>
      </div>
    </section>
  );
}

/** Authentication and authorization as one flow, below the sandbox's. */
function AccessCloserLook(): JSX.Element {
  // Tell the build that this id exists, so links to it are checked.
  useBrokenLinks().collectAnchor('access');
  return (
    <section id="access" className={clsx('ak-section', styles.closer)}>
      <div className="ak-container">
        <SectionHeader
          label="A closer look"
          title="Who may call what"
          lead="The identity provider turns a caller's credential into a principal. The access gate then decides, from the grants and the agent registry, which agents that principal may run and see and which of their tools it is offered: once where the request comes in and again where the run starts."
        />
        <AccessFlowDiagram />
        <ul className={styles.closerLinks}>
          {/* Drop `next` from these paths once a release carries the Authorization section. */}
          <li>
            <Link to="/docs/next/advanced/identity-and-access#how-it-fits-together" className="ak-link">
              Identity and access
            </Link>
          </li>
          <li>
            <Link to="/docs/next/advanced/identity-and-access#authorization" className="ak-link">
              Authorization
            </Link>
          </li>
          <li>
            <Link to="/docs/next/advanced/identity-and-access#where-a-denied-tool-is-stopped" className="ak-link">
              Where a denied tool is stopped
            </Link>
          </li>
        </ul>
      </div>
    </section>
  );
}

export default function Features(): JSX.Element {
  const current = useStageInView();

  return (
    <Layout
      title="Features"
      description="A reference to what Open Agent Kernel does: every capability of the runtime, grouped by stage, with a link to its guide. Framework adapters, channels and protocols, sessions and knowledge bases, guardrails, identity and sandboxes, deployment and queues, tracing and testing."
    >
      <main>
        <PageHero
          label="Features"
          title="Everything the runtime does, stage by stage"
          lead={`The home page introduces the six stages an agent request passes through. This page is the reference behind them: ${CAPABILITY_COUNT} capabilities, what each one includes, and the guide to read next.`}
          actions={
            <>
              <Link to="/docs" className="ak-btn ak-btn--secondary">
                Read the docs
              </Link>
              <Link to="/use-cases" className="ak-link">
                See what teams build
              </Link>
            </>
          }
        />

        <div className={clsx('ak-container', styles.reference)}>
          <StageIndex current={current} />
          <div className={styles.stages}>
            {STAGES.map((stage, position) => (
              <StageSection key={stage.id} stage={stage} position={position} />
            ))}
          </div>
        </div>

        <SandboxCloserLook />
        <AccessCloserLook />
      </main>
      <ClosingPanel />
    </Layout>
  );
}
