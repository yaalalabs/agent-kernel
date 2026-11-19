import React from 'react';
import clsx from 'clsx';
import Link from '@docusaurus/Link';
import Layout from '@theme/Layout';
import { TbCheck, TbMinus, TbX } from 'react-icons/tb';
import PageHero from '@site/src/components/ui/PageHero';
import LevelStack from '@site/src/components/LevelStack';
import { ClosingPanel } from '@site/src/components/HomeSections';
import type { Step } from '@site/src/components/StepTimeline';
import {
  CodeSample,
  DocLinks,
  Journey,
  OtherLevels,
  PersonaSection,
  Tabs,
  type TabItem,
} from '@site/src/components/PersonaKit';
import BuildingAgentsFlowDiagram from '@site/src/components/BuildingAgentsFlowDiagram';
import RunningAgentsFlowDiagram from '@site/src/components/RunningAgentsFlowDiagram';
import AgentKernelSitsInFlowDiagram from '@site/src/components/AgentKernelSitsInFlowDiagram';
import styles from './persona.module.css';

const STEPS: Step[] = [
  { id: 'compare', label: 'Compare' },
  { id: 'placement', label: 'Placement' },
  { id: 'memory', label: 'Memory' },
  { id: 'hooks', label: 'Hooks' },
  { id: 'scale', label: 'Scale and evidence' },
];

/* ─── 01 Compare ──────────────────────────────────────────────────────────── */

type Verdict = 'yes' | 'no' | 'partial';
type Cell = { verdict: Verdict; text?: string };

const COMPARISON: Array<{ question: string; hint?: string; cloud: Cell; frameworks: Cell; oak: Cell }> = [
  {
    question: 'Switch cloud platform later?',
    cloud: { verdict: 'no', text: 'Rewrite' },
    frameworks: { verdict: 'yes', text: 'You build it' },
    oak: { verdict: 'yes', text: 'One config change' },
  },
  {
    question: 'Run agents from several frameworks together?',
    cloud: { verdict: 'no', text: 'Not possible' },
    frameworks: { verdict: 'no', text: 'Not possible' },
    oak: { verdict: 'yes', text: 'In one runtime' },
  },
  {
    question: 'Integrations out of the box?',
    hint: 'Slack, Teams, REST, A2A, MCP',
    cloud: { verdict: 'partial', text: 'Partial' },
    frameworks: { verdict: 'no', text: 'Build your own' },
    oak: { verdict: 'yes', text: 'Built in' },
  },
  {
    question: 'Sessions, memory and observability?',
    cloud: { verdict: 'yes', text: 'Proprietary' },
    frameworks: { verdict: 'no', text: 'Build your own' },
    oak: { verdict: 'yes', text: 'Built in and pluggable' },
  },
  {
    question: 'Knowledge bases?',
    cloud: { verdict: 'yes', text: 'Proprietary' },
    frameworks: { verdict: 'no', text: 'Build your own' },
    oak: { verdict: 'yes', text: 'Built in and pluggable' },
  },
  {
    question: 'Open source, with no licence fee?',
    cloud: { verdict: 'no' },
    frameworks: { verdict: 'yes' },
    oak: { verdict: 'yes', text: 'Apache 2.0' },
  },
  {
    question: 'Lift and shift an existing agent?',
    cloud: { verdict: 'no', text: 'Rewrite' },
    frameworks: { verdict: 'no', text: 'Rewrite' },
    oak: { verdict: 'yes', text: 'Wrap and ship' },
  },
];

const VERDICT = {
  yes: { Icon: TbCheck, word: 'Yes', tone: undefined },
  no: { Icon: TbX, word: 'No', tone: styles.cellNo },
  partial: { Icon: TbMinus, word: 'Partial', tone: styles.cellPartial },
} as const;

function CompareCell({ cell }: { cell: Cell }): JSX.Element {
  const { Icon, word, tone } = VERDICT[cell.verdict];
  return (
    <span className={clsx(styles.cell, tone)}>
      <Icon className={styles.cellIcon} aria-hidden="true" />
      {cell.text ?? word}
    </span>
  );
}

/* ─── 02 Placement ────────────────────────────────────────────────────────── */

const PLACEMENT: TabItem[] = [
  {
    id: 'building',
    label: 'What you build',
    content: (
      <figure className={styles.figure}>
        <BuildingAgentsFlowDiagram />
        <figcaption className={clsx('ak-small', styles.caption)}>
          A compliant multi-agent system has more parts than agents: guardrails on the way in and out, a supervisor,
          specialist agents, their tools and shared memory.
        </figcaption>
      </figure>
    ),
  },
  {
    id: 'running',
    label: 'What running it takes',
    content: (
      <figure className={styles.figure}>
        <RunningAgentsFlowDiagram />
        <figcaption className={clsx('ak-small', styles.caption)}>
          In production the agent logic runs behind an API, in a server, a container or a function, and reaches a
          memory store, the model, knowledge sources and other APIs on every request.
        </figcaption>
      </figure>
    ),
  },
  {
    id: 'kernel',
    label: 'Where OAK sits',
    content: (
      <figure className={styles.figure}>
        <AgentKernelSitsInFlowDiagram />
        <figcaption className={clsx('ak-small', styles.caption)}>
          OAK takes everything except the agent logic: how many agents there are, what they can do and how they are
          prompted stay yours.
        </figcaption>
      </figure>
    ),
  },
];

/* ─── 03 Memory ───────────────────────────────────────────────────────────── */

const MEMORY_LAYERS = [
  {
    tag: 'Session',
    title: 'Conversational state',
    line: 'The turns of the conversation, kept by the session store. This is what gives a chat its continuity.',
  },
  {
    tag: 'One request',
    title: 'Volatile cache',
    line: 'A scratchpad for a single request: retrieved passages, file reads, intermediate results. It clears after every reply.',
  },
  {
    tag: 'Session',
    title: 'Non-volatile cache',
    line: 'Supporting data that should outlive a request: user preferences, auth context, counters. Tools and hooks read it without spending model tokens.',
  },
];

const MEMORY_CODE = `from agentkernel import PreHook, Session
from agentkernel.core.memory import KeyValueCache

class MyHook(PreHook):
    async def on_run(self, session: Session, agent, requests):
        # Get caches from session
        v_cache: KeyValueCache = session.get_volatile_cache()
        nv_cache: KeyValueCache = session.get_non_volatile_cache()

        # Use the caches
        v_cache.set("temp_data", "value")
        user_pref = nv_cache.get("user_language")

        return requests`;

/* ─── 04 Hooks ────────────────────────────────────────────────────────────── */

const HOOK_STAGES = [
  {
    title: 'Before the run',
    line: 'A pre-hook receives the requests and may change them: redact, validate, add retrieved context or attach files.',
  },
  {
    title: 'After the run',
    line: 'A post-hook receives the reply, and each one sees what the hook before it returned: moderate, add a disclaimer, log for audit.',
  },
  {
    title: 'Stop early',
    line: 'A pre-hook that returns a reply ends the run before the model is called. Use it for input guardrails, rate limits and cached answers.',
  },
];

const HOOK_CODE = `from agentkernel.openai import OpenAIModule
from agents import Agent

# Create your agent
agent = Agent(name="assistant", instructions="...")

# Register agent and hooks using method chaining
OpenAIModule([agent]).pre_hook(agent, [
    RAGHook(),
    GuardRailHook(),
]).post_hook(agent, [
    ModerationHook(),
    DisclaimerHook(),
])`;

/* ─── 05 Scale and evidence ───────────────────────────────────────────────── */

const QUEUE_CHAIN = ['Request handler', 'Input queue', 'Agent runner', 'Output queue', 'Response handler'];

const TRANSPORTS = ['in_memory', 'sqs', 'kafka', 'nats', 'pubsub', 'servicebus'];

const TRACE_CODE = `from datetime import timedelta

from agentkernel.trace import SpanStatus, Trace

for trace in Trace.get().fetch_traces(session_id="session-123", last=timedelta(hours=24)):
    if trace.root is None:
        continue  # the root span isn't stored (yet), so there is no request to grade
    print(trace.trace_id, trace.user_input, trace.output, trace.usage.cost, trace.agent_names)
    failed = [span.name for span in trace.tool_spans if span.status == SpanStatus.ERROR]`;

export default function AIEngineerPage(): JSX.Element {
  return (
    <Layout
      title="Open Agent Kernel for AI engineers"
      description="How the Open Agent Kernel runtime compares, where it sits in a request, and the memory, hook and queue machinery you can build on."
    >
      <PageHero
        art={<LevelStack active={2} />}
        label="Level 03 / AI engineers"
        title="Inside the runtime that runs your agents"
        lead="Open Agent Kernel (OAK) sits between your agent code and the infrastructure it runs on. This page covers how it compares with the alternatives, where it sits in a request, and the memory, hook and queue machinery you can build on."
        actions={
          <>
            <Link to="/docs/architecture/overview" className="ak-btn ak-btn--primary">
              Read the architecture docs
            </Link>
            <Link to="/docs/architecture/execution-flow" className="ak-link">
              Execution flow
            </Link>
          </>
        }
      />
      <Journey steps={STEPS}>
        <PersonaSection
          id="compare"
          index="01"
          label="Compare"
          title="A runtime, without giving up the choice"
          lead="Managed platforms give you a runtime and take the choice of cloud and framework. Frameworks leave you the choice and no runtime. OAK is built to give you both."
        >
          <div className={styles.tableScroll} role="region" aria-label="Comparison table" tabIndex={0}>
            <table className={styles.compare}>
              <caption className={styles.srOnly}>
                Managed cloud platforms, agent frameworks and OAK, compared on seven questions
              </caption>
              <thead>
                <tr>
                  <th scope="col">
                    <span className={styles.srOnly}>Question</span>
                  </th>
                  <th scope="col">
                    Managed cloud platforms
                    <span className={styles.compareHint}>Bedrock AgentCore, Azure AI Foundry, Vertex AI</span>
                  </th>
                  <th scope="col">
                    Agent frameworks
                    <span className={styles.compareHint}>LangGraph, CrewAI, OpenAI Agents and others</span>
                  </th>
                  <th scope="col" className={styles.compareOak}>
                    OAK
                    <span className={styles.compareHint}>Open Agent Kernel</span>
                  </th>
                </tr>
              </thead>
              <tbody>
                {COMPARISON.map((row) => (
                  <tr key={row.question}>
                    <th scope="row">
                      {row.question}
                      {row.hint && <span className={styles.compareHint}>{row.hint}</span>}
                    </th>
                    <td>
                      <CompareCell cell={row.cloud} />
                    </td>
                    <td>
                      <CompareCell cell={row.frameworks} />
                    </td>
                    <td className={styles.compareOak}>
                      <CompareCell cell={row.oak} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </PersonaSection>

        <PersonaSection
          id="placement"
          index="02"
          label="Placement"
          title="Where OAK sits in an agent system"
          lead="Three views of one system: what you set out to build, what it takes to run it, and the part OAK takes over."
        >
          <Tabs name="placement" label="Views of an agent system" items={PLACEMENT} />
          <div className={styles.blockSmall}>
            <DocLinks
              links={[
                { label: 'Architecture overview', to: '/docs/architecture/overview' },
                { label: 'Multi-agent systems', to: '/docs/advanced/multi-agent' },
                { label: 'Running several frameworks', to: '/docs/frameworks/multi-framework' },
              ]}
            />
          </div>
        </PersonaSection>

        <PersonaSection
          id="memory"
          index="03"
          label="Memory"
          title="Three layers of memory, one context window"
          lead="Keep the conversation coherent, enrich a single request, and carry session data forward, without filling the model's context with it."
        >
          <div className={styles.split}>
            <div className={styles.stack}>
              <ul className={styles.rows}>
                {MEMORY_LAYERS.map((layer) => (
                  <li key={layer.title} className={styles.row}>
                    <p className="ak-label">{layer.tag}</p>
                    <h3 className="ak-h4">{layer.title}</h3>
                    <p className="ak-body">{layer.line}</p>
                  </li>
                ))}
              </ul>
              <DocLinks
                links={[
                  { label: 'Memory management', to: '/docs/architecture/memory-management' },
                  { label: 'Memory backends', to: '/docs/core-concepts/memory-backends' },
                ]}
              />
            </div>
            <CodeSample title="hooks.py" language="python">
              {MEMORY_CODE}
            </CodeSample>
          </div>
        </PersonaSection>

        <PersonaSection
          id="hooks"
          index="04"
          label="Hooks"
          title="Hooks around every run"
          lead="Control what reaches an agent and what leaves it, without touching the agent's own logic. Hooks work with every framework adapter."
        >
          <ol className={styles.chain} aria-label="The path of a request through the hooks">
            <li>
              <span className={styles.chainStop}>Request</span>
            </li>
            <li>
              <span className={clsx(styles.chainStop, styles.chainStopAccent)}>Pre-hooks</span>
            </li>
            <li>
              <span className={styles.chainStop}>Agent</span>
            </li>
            <li>
              <span className={clsx(styles.chainStop, styles.chainStopAccent)}>Post-hooks</span>
            </li>
            <li>
              <span className={styles.chainStop}>Reply</span>
            </li>
          </ol>
          <div className={clsx(styles.split, styles.blockSmall)}>
            <div className={styles.stack}>
              <ul className={styles.rows}>
                {HOOK_STAGES.map((stage) => (
                  <li key={stage.title} className={styles.row}>
                    <h3 className="ak-h4">{stage.title}</h3>
                    <p className="ak-body">{stage.line}</p>
                  </li>
                ))}
              </ul>
              <DocLinks links={[{ label: 'Execution hooks', to: '/docs/integrations/hooks' }]} />
            </div>
            <CodeSample title="my_agent.py" language="python">
              {HOOK_CODE}
            </CodeSample>
          </div>
        </PersonaSection>

        <PersonaSection
          id="scale"
          index="05"
          label="Scale and evidence"
          title="Scale it, then prove it works"
          lead="A queue between the caller and the agent sets how the system behaves under load. Traces you can read back tell you how it behaved."
        >
          <ol className={styles.chain} aria-label="The queue pipeline">
            {QUEUE_CHAIN.map((stop) => (
              <li key={stop}>
                <span className={clsx(styles.chainStop, stop.includes('queue') && styles.chainStopAccent)}>{stop}</span>
              </li>
            ))}
          </ol>
          <div className={clsx(styles.split, styles.blockSmall)}>
            <div className={styles.stack}>
              <h3 className="ak-h3">Queue mode</h3>
              <ul className={styles.points}>
                <li>The request path and the agent runners scale separately</li>
                <li>Turns of one session stay in order, while sessions run in parallel</li>
                <li>A message leaves the queue only when it is fully processed, so a crashed worker loses nothing</li>
                <li>The number of consumers, not the arrival rate, sets how hard the model provider is hit</li>
              </ul>
              <ul className={clsx('ak-tag-row', styles.plainList)} aria-label="Queue transports">
                {TRANSPORTS.map((transport) => (
                  <li key={transport} className="ak-tag">
                    {transport}
                  </li>
                ))}
              </ul>
              <DocLinks
                links={[
                  { label: 'Queue mode guide', to: '/docs/advanced/queue-mode-guide' },
                  { label: 'Fault tolerance', to: '/docs/core-concepts/fault-tolerance' },
                ]}
              />
            </div>
            <div className={styles.stack}>
              <h3 className="ak-h3">Traces you can read back</h3>
              <p className="ak-body">
                Spans written to Langfuse, OpenLLMetry, Pydantic Logfire or CloudWatch come back through one
                provider-neutral call, grouped into traces with their input, output, tool calls and usage. An
                evaluation job can grade real runs.
              </p>
              <CodeSample title="evaluate.py" language="python">
                {TRACE_CODE}
              </CodeSample>
              <DocLinks
                links={[
                  { label: 'Traceability', to: '/docs/advanced/traceability' },
                  { label: 'Testing overview', to: '/docs/testing/overview' },
                ]}
              />
            </div>
          </div>
        </PersonaSection>
      </Journey>

      <OtherLevels current="ai-engineer" />
      <ClosingPanel />
    </Layout>
  );
}
