import React, { useState } from 'react';
import Link from '@docusaurus/Link';
import CodeBlock from '@theme/CodeBlock';
import clsx from 'clsx';
import SectionHeader from '@site/src/components/ui/SectionHeader';
import { CertSeal } from '@site/src/components/BrandArt';
import { StageMotion, type Stage as StageId } from '@site/src/components/VectorMotion';
import styles from './styles.module.css';

export { Announcement } from './Announcement';
export { Deployment } from './Deployment';
export { Hero } from './Hero';
export { Integrations } from './Integrations';
export { Levels } from './Levels';

/* ─── Trust marks ─────────────────────────────────────────────────────────
   One quiet row under the hero. It carries no figures: none are published yet.
   Add them here when real numbers exist. */

export function TrustMarks(): JSX.Element {
  return (
    <section className={styles.trust} aria-label="Licence, memberships and compliance">
      <ul className={clsx('ak-container', styles.trustRow)}>
        <li className={styles.trustItem}>
          <span className={styles.trustValue}>Apache 2.0</span>
          <span className={styles.trustLabel}>Open source</span>
        </li>
        <li className={styles.trustItem}>
          <a href="https://www.linuxfoundation.org" target="_blank" rel="noopener noreferrer" className={styles.trustLink}>
            <span className={styles.trustValue}>Linux Foundation</span>
            <span className={styles.trustLabel}>Member</span>
          </a>
        </li>
        <li className={styles.trustItem}>
          <a href="https://aaif.io" target="_blank" rel="noopener noreferrer" className={styles.trustLink}>
            <span className={styles.trustValue}>Agentic AI Foundation</span>
            <span className={styles.trustLabel}>Member</span>
          </a>
        </li>
        <li className={styles.trustItem}>
          <CertSeal shape="seal" className={styles.trustSeal} />
          <span className={styles.trustText}>
            <span className={styles.trustValue}>ISO 27001</span>
            <span className={styles.trustLabel}>Certified environment</span>
          </span>
        </li>
        <li className={styles.trustItem}>
          <CertSeal shape="shield" className={styles.trustSeal} />
          <span className={styles.trustText}>
            <span className={styles.trustValue}>SOC 2 Type 2</span>
            <span className={styles.trustLabel}>Audited environment</span>
          </span>
        </li>
      </ul>
    </section>
  );
}

/* ─── What OAK does: a rail of six stages ─────────────────────────────────
   Each stage shows one sentence, three points, and a plate that sets its line
   drawing beside the code or config that turns it on. The snippets are taken
   from the documentation. */

type Stage = {
  id: StageId;
  name: string;
  summary: string;
  points: string[];
  file: string;
  language: 'python' | 'yaml';
  code: string;
  docs: string;
};

const STAGES: Stage[] = [
  {
    id: 'build',
    name: 'Build',
    summary: 'Write agents in the framework you already know. OAK wraps them with one API, so the agent logic stays yours.',
    points: [
      'Adapters for eight agent frameworks, side by side in one runtime',
      'Tools written once as plain Python and bound to any framework',
      'Structured output, multimodal input and multi-agent handoffs',
    ],
    file: 'my_agent.py',
    language: 'python',
    code: `from agents import Agent as OpenAIAgent
from agentkernel.cli import CLI
from agentkernel.openai import OpenAIModule

assistant = OpenAIAgent(
    name="assistant",
    instructions="Give short and direct answers.",
)

# Register the agent with OAK
OpenAIModule([assistant])

if __name__ == "__main__":
    CLI.main()`,
    docs: '/docs/frameworks/overview',
  },
  {
    id: 'connect',
    name: 'Connect',
    summary: 'Reach users where they already are. Channels, protocols and APIs are adapters around the same runtime.',
    points: [
      'Slack, WhatsApp, Teams, Telegram, Gmail, Messenger and Instagram',
      'REST with streaming, WebSocket delivery and an interactive CLI',
      'MCP and A2A servers, and AG-UI for agent front ends',
    ],
    file: 'config.yaml',
    language: 'yaml',
    code: `slack:
  agent: assistant
  bot_token_key: SLACK_BOT_TOKEN
  signing_secret_key: SLACK_SIGNING_SECRET`,
    docs: '/docs/integrations/overview',
  },
  {
    id: 'remember',
    name: 'Remember',
    summary: 'State that survives the request. Sessions, threads and knowledge live in stores you select with configuration.',
    points: [
      'Session stores on Redis, Valkey, DynamoDB, Cosmos DB and Firestore',
      'Conversation threads with persisted history',
      'Knowledge bases behind one interface',
    ],
    file: 'config.yaml',
    language: 'yaml',
    code: `session:
  type: redis
  redis:
    url: redis://localhost:6379
    ttl: 604800  # 7 days in seconds`,
    docs: '/docs/core-concepts/session',
  },
  {
    id: 'guard',
    name: 'Guard',
    summary: 'Decide what goes in and what comes out. The runtime enforces policy, so it is not left to each agent.',
    points: [
      'Input and output guardrails from OpenAI, Bedrock or Walled AI',
      'One identity provider for every surface',
      'Secrets resolved from a managed store, and sandboxed code execution',
    ],
    file: 'config.yaml',
    language: 'yaml',
    code: `guardrail:
  input:
    enabled: true
    type: openai
  output:
    enabled: true
    type: openai`,
    docs: '/docs/advanced/guardrails',
  },
  {
    id: 'scale',
    name: 'Scale',
    summary: 'From a laptop to a fleet. The same agent code runs serverless, in containers or on Kubernetes.',
    points: [
      'A queued pipeline that scales request handling and agents separately',
      'SQS, Kafka, NATS JetStream, Pub/Sub and Service Bus transports',
      'Terraform modules and a Helm chart for every target',
    ],
    file: 'config.yaml',
    language: 'yaml',
    code: `execution:
  mode: rest_sync
  queues:
    type: sqs
    input:
      url: "https://sqs.us-east-1.amazonaws.com/123456789012/agent-input"`,
    docs: '/docs/advanced/queue-mode-guide',
  },
  {
    id: 'observe',
    name: 'Observe',
    summary: 'See every run and prove it works. A trace and a test describe the same request.',
    points: [
      'Tracing to Langfuse, OpenLLMetry, Pydantic Logfire or CloudWatch',
      'Spans read back through one provider-neutral call, for evaluation',
      'A test framework that plugs into pytest',
    ],
    file: 'config.yaml',
    language: 'yaml',
    code: `trace:
  enabled: true
  type: langfuse`,
    docs: '/docs/advanced/traceability',
  },
];

export function CapabilityRail(): JSX.Element {
  const [active, setActive] = useState(0);
  const stage = STAGES[active];

  const onKeyDown = (event: React.KeyboardEvent<HTMLDivElement>) => {
    if (event.key !== 'ArrowRight' && event.key !== 'ArrowLeft') return;
    event.preventDefault();
    const next = (active + (event.key === 'ArrowRight' ? 1 : STAGES.length - 1)) % STAGES.length;
    setActive(next);
    document.getElementById(`capability-tab-${STAGES[next].id}`)?.focus();
  };

  return (
    <section id="capabilities" className="ak-section">
      <div className="ak-container">
        <SectionHeader
          index="01"
          label="What OAK does"
          title="Six stages every agent request passes through"
          lead="Each one is switched on with a few lines of configuration, not built from scratch."
        />

        <div className={styles.rail} role="tablist" aria-label="Capabilities" onKeyDown={onKeyDown}>
          {STAGES.map((item, index) => (
            <button
              key={item.id}
              id={`capability-tab-${item.id}`}
              type="button"
              role="tab"
              aria-selected={index === active}
              aria-controls="capability-panel"
              tabIndex={index === active ? 0 : -1}
              className={clsx(styles.railStop, index === active && styles.railStopActive)}
              onClick={() => setActive(index)}
            >
              <span className={styles.railIndex}>{String(index + 1).padStart(2, '0')}</span>
              <span className={styles.railName}>{item.name}</span>
            </button>
          ))}
        </div>

        <div
          id="capability-panel"
          role="tabpanel"
          aria-labelledby={`capability-tab-${stage.id}`}
          className={styles.panel}
        >
          <div className={styles.panelIntro}>
            <div className={styles.panelCopy}>
              <h3 className="ak-h3">{stage.name}</h3>
              <p className="ak-body">{stage.summary}</p>
              <Link to={stage.docs} className="ak-link">
                Learn more
              </Link>
            </div>
            <ul className={styles.points}>
              {stage.points.map((point) => (
                <li key={point}>{point}</li>
              ))}
            </ul>
          </div>

          <div className={styles.plate}>
            <div className={styles.plateDrawing}>
              <StageMotion stage={stage.id} />
            </div>
            <div className={styles.plateCode}>
              <CodeBlock language={stage.language} title={stage.file}>
                {stage.code}
              </CodeBlock>
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}

/* ─── Closing panel ───────────────────────────────────────────────────────
   Pinned to the dark tokens, so it is a navy panel in both colour modes. */

export function ClosingPanel(): JSX.Element {
  return (
    <section className="ak-section">
      <div className="ak-container">
        <div className={clsx('ak-dark', styles.closing)}>
          <div className={styles.closingCopy}>
            <h2 className="ak-h2">Ship your first agent today</h2>
            <p className="ak-lead">
              Free and open source under Apache 2.0. No licensing costs and no lock-in.
            </p>
          </div>
          <div className={styles.closingActions}>
            <Link className="ak-btn ak-btn--primary" to="/docs/quick-start">
              Quick start
            </Link>
            <Link
              className="ak-btn ak-btn--secondary"
              to="https://github.com/yaalalabs/agent-kernel"
              target="_blank"
              rel="noopener noreferrer"
            >
              View on GitHub
            </Link>
          </div>
        </div>
      </div>
    </section>
  );
}
