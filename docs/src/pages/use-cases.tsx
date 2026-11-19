import React from 'react';
import Link from '@docusaurus/Link';
import Layout from '@theme/Layout';
import clsx from 'clsx';
import PageHero from '@site/src/components/ui/PageHero';
import SectionHeader from '@site/src/components/ui/SectionHeader';
import Reveal from '@site/src/components/ui/Reveal';
import { ClosingPanel } from '@site/src/components/HomeSections';
import styles from './use-cases.module.css';

/* The page answers "who uses OAK, and for what". Each entry leads somewhere concrete: a write-up,
   a project in the repository, or a guide with a working example. What the runtime can do is the
   Features page's job, and is not repeated here. */

const REPO = 'https://github.com/yaalalabs/agent-kernel/tree/develop';

type PageLink = { label: string; to: string };

/* ── Projects built on OAK ── */

type Project = {
  status: string;
  title: string;
  summary: string;
  /** The parts of OAK the project relies on, as its own write-up lists them. */
  uses: string[];
  links: PageLink[];
  /** A caveat the project states about itself. */
  note?: string;
};

const PROJECTS: Project[] = [
  {
    status: 'In production',
    title: 'Trade surveillance at Climate Impact X',
    summary:
      'Climate Impact X, an exchange for environmental products such as carbon credits, runs an agentic workflow on OAK inside its trade surveillance. Agents review potential issues beyond what rule-based alerts catch, and hand investigators structured context.',
    uses: [
      'Multi-agent orchestration',
      'Serverless deployment',
      'Durable session state',
      'Guardrails',
      'Tracing',
      'Behaviour tests',
    ],
    links: [{ label: 'Read the story', to: '/blog/agent-kernel-live-at-climate-impact-x' }],
  },
  {
    status: 'Prototype',
    title: 'Mathru, a maternal health companion',
    summary:
      'A WhatsApp agent for expectant mothers and the midwife assigned to them. Mothers register, ask about clinic visits and report symptoms, and a severe report is escalated to the midwife with its context.',
    uses: ['WhatsApp', 'Multi-agent handoffs', 'Session memory', 'Guardrails', 'Post-execution hooks'],
    links: [{ label: 'Browse the project', to: `${REPO}/use-cases/mathru-phm-companion` }],
    note: 'A competition prototype, not a clinical tool.',
  },
  {
    status: 'Sample project',
    title: 'Waste sorting assistant',
    summary:
      "A single agent that recommends how to dispose of an item under the user's local recycling rules. It was generated from a written spec by a coding assistant that follows the OAK agent skills.",
    uses: ['OpenAI Agents SDK', 'Tools', 'Session memory', 'AWS Lambda', 'DynamoDB'],
    links: [
      { label: 'Browse the project', to: `${REPO}/use-cases/waste-sorting-assistant` },
      { label: 'How it was built', to: `${REPO}/use-cases/README.md` },
    ],
  },
];

/* ── Scenarios: a need, the path a request takes, a guide and an example ── */

type RecipeNode = { label: string; yours?: boolean };

type Scenario = {
  title: string;
  need: string;
  /** The path of a request, left to right. One node is the part you write. */
  recipe: RecipeNode[];
  guide: PageLink;
  /** A folder in the repository, relative to its root. */
  example: string;
};

const SCENARIOS: Scenario[] = [
  {
    title: 'A support assistant where people already talk',
    need: 'Answer customers or colleagues in Slack, Teams, WhatsApp, Telegram, Messenger, Instagram or Gmail, with the conversation remembered between messages.',
    recipe: [{ label: 'Slack' }, { label: 'Channel adapter' }, { label: 'Session' }, { label: 'Your agent', yours: true }],
    guide: { label: 'Slack guide', to: '/docs/integrations/slack' },
    example: 'examples/api/slack',
  },
  {
    title: 'An assistant that answers from your own data',
    need: 'Ground replies in documents, graphs and SQL sources, without writing a connector for each store.',
    recipe: [
      { label: 'Your agent', yours: true },
      { label: 'Knowledge tools' },
      { label: 'ChromaDB · Neo4j · SQL' },
    ],
    guide: { label: 'Knowledge bases', to: '/docs/advanced/knowledge-bases' },
    example: 'examples/cli/knowledgebase/openai',
  },
  {
    title: 'A copilot inside your product',
    need: "Stream an agent's text, tool calls and state into your own frontend over AG-UI.",
    recipe: [{ label: 'Your frontend' }, { label: 'AG-UI server' }, { label: 'Your agent', yours: true }],
    guide: { label: 'AG-UI server', to: '/docs/api/agui-server' },
    example: 'examples/api/agui',
  },
  {
    title: 'An agent that waits for a person',
    need: 'Some actions should not happen until someone approves them. The run pauses, and continues when the answer arrives.',
    recipe: [
      { label: 'Your agent', yours: true },
      { label: 'Pause' },
      { label: 'A person decides' },
      { label: 'Resume' },
    ],
    guide: { label: 'Human in the loop', to: '/docs/advanced/human-in-the-loop' },
    example: 'examples/api/hitl',
  },
  {
    title: 'An agent that writes and runs code',
    need: 'Let an agent run code, shell commands and file operations in an isolated sandbox, not on your host.',
    recipe: [
      { label: 'Your agent', yours: true },
      { label: 'Sandbox tools' },
      { label: 'Execution Broker' },
      { label: 'Sandbox' },
    ],
    guide: { label: 'Sandbox guide', to: '/docs/advanced/sandbox' },
    example: 'examples/sandbox/basic',
  },
  {
    title: 'Work that runs on a schedule',
    need: 'Daily reports, reminders and follow-ups: register a chat to run later, or again and again.',
    recipe: [
      { label: 'Chat with a schedule' },
      { label: 'Task store' },
      { label: 'Input queue' },
      { label: 'Your agent', yours: true },
    ],
    guide: { label: 'Scheduled tasks', to: '/docs/advanced/scheduling' },
    example: 'examples/api/schedule-openai',
  },
  {
    title: 'A voice agent',
    need: 'Talk to an agent in a LiveKit room, with audio streamed in both directions.',
    recipe: [
      { label: 'LiveKit room' },
      { label: 'Edge gateway' },
      { label: 'Realtime runner' },
      { label: 'Your agent', yours: true },
    ],
    guide: { label: 'LiveKit voice', to: '/docs/integrations/livekit' },
    example: 'examples/api/livekit-voice',
  },
  {
    title: 'An agent that other agents and tools can call',
    need: 'Publish an agent as an MCP tool or an A2A peer, so assistants and other agents can use it.',
    recipe: [{ label: 'MCP client · A2A agent' }, { label: 'MCP · A2A server' }, { label: 'Your agent', yours: true }],
    guide: { label: 'MCP server', to: '/docs/api/mcp-server' },
    example: 'examples/api/mcp',
  },
  {
    title: 'One deployment, several frameworks',
    need: 'Keep the agent one team wrote in CrewAI beside the one another team wrote with the OpenAI Agents SDK.',
    recipe: [{ label: 'One API' }, { label: 'OAK runtime' }, { label: 'Agents in any framework', yours: true }],
    guide: { label: 'Multi-framework guide', to: '/docs/frameworks/multi-framework' },
    example: 'examples/cli/multi',
  },
  {
    title: 'A service that holds up under load',
    need: 'Put queues between ingress and the agents, so each side scales on its own.',
    recipe: [
      { label: 'Request handler' },
      { label: 'Input queue' },
      { label: 'Agent runner', yours: true },
      { label: 'Output queue' },
      { label: 'Response handler' },
    ],
    guide: { label: 'Queue mode guide', to: '/docs/advanced/queue-mode-guide' },
    example: 'examples/k8s/openai-queue-mode',
  },
];

/* ── Teams OAK fits ── */

type Team = {
  kind: string;
  title: string;
  profile: string;
  /** What the runtime takes on for this kind of team. */
  gains: string[];
  start: PageLink;
};

const TEAMS: Team[] = [
  {
    kind: 'Services and development houses',
    title: 'Teams that build agents for clients',
    profile: 'Developers are on staff and clients are asking for agents, but every project starts from the same missing platform.',
    gains: [
      'One runtime to reuse across client projects',
      'AWS, Azure, Google Cloud or Kubernetes, to match each client',
      'Channel integrations ready for the first demo',
    ],
    start: { label: 'See every feature', to: '/features' },
  },
  {
    kind: 'SaaS and enterprise software',
    title: 'Product teams adding agents to an existing product',
    profile: 'The product exists and the architecture is settled. Agents have to fit in without a rewrite, and without tying the product to one framework.',
    gains: [
      'A REST API that drops into an existing architecture',
      'Session stores on the databases you already run',
      'Guardrails, tracing and fault tolerance for enterprise reviews',
    ],
    start: { label: 'Read the REST API guide', to: '/docs/api/rest-api' },
  },
  {
    kind: 'Early to growth stage',
    title: 'AI startups',
    profile: 'A small team building an AI-native product, with no engineering time to spend on infrastructure before the product has found its market.',
    gains: [
      'Open source under Apache 2.0, with no licence cost',
      'Terraform modules and container images out of the box',
      'The same code from one Lambda function to a multi-AZ cluster',
    ],
    start: { label: 'Start with the quick start', to: '/docs/quick-start' },
  },
  {
    kind: 'Finance, healthcare, legal, education',
    title: 'Domain experts',
    profile: 'People who know what the agent should do, and want as little software engineering as possible between that knowledge and a working product.',
    gains: [
      'Agents defined in plain Python',
      'A coding assistant can scaffold the project from a written spec',
      'Tests that check agent behaviour against expected answers',
    ],
    start: { label: 'Build with agent skills', to: '/docs/agent-skills' },
  },
];

/* ── What you would otherwise build ── */

const WITHOUT: { label: string; detail: string }[] = [
  { label: 'Platform engineering', detail: 'Base infrastructure for an agent service' },
  { label: 'Framework setup', detail: 'Choose, configure, scaffold' },
  { label: 'Cloud configuration', detail: 'Regions, roles, networking' },
  { label: 'Session management', detail: 'Authentication, state, tokens' },
  { label: 'Integrations', detail: 'APIs, queues, data sources' },
  { label: 'Testing setup', detail: 'Harnesses, CI, coverage' },
  { label: 'Deploy pipeline', detail: 'Build, push, release gates' },
];

const WITH_OAK: { label: string; detail: string }[] = [
  { label: 'Write your agent logic', detail: 'What the agent does, in the framework you chose' },
  { label: 'Deploy', detail: 'Pick a target in configuration' },
];

function ProjectLinks({ links }: { links: PageLink[] }): JSX.Element {
  return (
    <div className={styles.projectLinks}>
      {links.map((link) => (
        <Link key={link.to} to={link.to} className="ak-link">
          {link.label}
        </Link>
      ))}
    </div>
  );
}

function Projects(): JSX.Element {
  const [lead, ...others] = PROJECTS;

  return (
    <section className="ak-section" aria-labelledby="built-with-oak">
      <div className="ak-container">
        <SectionHeader
          index="01"
          label="Built with OAK"
          title="Projects you can read"
          lead="One runs in production, and two are in the repository with their specs and code."
          id="built-with-oak"
        />
        <ul className={styles.projects}>
          {/* The production project leads: its story on the left, what OAK provided on the right */}
          <li className={clsx('ak-card', styles.project, styles.projectLead)}>
            <div className={styles.projectCopy}>
              <p className={clsx('ak-tag', styles.status, styles.statusLive)}>{lead.status}</p>
              <h3 className="ak-h3">{lead.title}</h3>
              <p className="ak-body">{lead.summary}</p>
              <ProjectLinks links={lead.links} />
            </div>
            <div className={styles.projectProvided}>
              <p className="ak-label">What OAK provided</p>
              <ul className={styles.gains}>
                {lead.uses.map((use) => (
                  <li key={use}>{use}</li>
                ))}
              </ul>
            </div>
          </li>
          {others.map((project) => (
            <li key={project.title} className={clsx('ak-card', styles.project)}>
              <p className={clsx('ak-tag', styles.status)}>{project.status}</p>
              <h3 className="ak-h4">{project.title}</h3>
              <p className="ak-body">{project.summary}</p>
              {project.note && <p className="ak-small">{project.note}</p>}
              <ul className={clsx('ak-tag-row', styles.uses)} aria-label="Parts of OAK it uses">
                {project.uses.map((use) => (
                  <li key={use} className="ak-tag">
                    {use}
                  </li>
                ))}
              </ul>
              <ProjectLinks links={project.links} />
            </li>
          ))}
        </ul>
      </div>
    </section>
  );
}

function Scenarios(): JSX.Element {
  return (
    <section className={clsx('ak-section', 'ak-section--raised')} aria-labelledby="scenarios">
      <div className="ak-container">
        <SectionHeader
          index="02"
          label="Scenarios"
          title="Start from what you need to build"
          lead="Each scenario shows the path a request takes, with the part you write marked. The guide explains it, and the example runs."
          id="scenarios"
        />
        <ol className={styles.scenarios}>
          {SCENARIOS.map((scenario, position) => (
            <Reveal as="li" key={scenario.title} className={styles.scenario}>
              <span className={styles.scenarioIndex} aria-hidden="true">
                {String(position + 1).padStart(2, '0')}
              </span>
              <div className={styles.scenarioCopy}>
                <h3 className="ak-h3">{scenario.title}</h3>
                <p className="ak-body">{scenario.need}</p>
                <div className={styles.scenarioLinks}>
                  <Link to={scenario.guide.to} className="ak-link">
                    {scenario.guide.label}
                  </Link>
                  <Link to={`${REPO}/${scenario.example}`} className={styles.exampleLink}>
                    Example on GitHub
                  </Link>
                </div>
              </div>
              <ol className={styles.recipe} aria-label="The path of a request">
                {scenario.recipe.map((node) => (
                  <li key={node.label} className={clsx(styles.recipeNode, node.yours && styles.recipeNodeYours)}>
                    <span>{node.label}</span>
                  </li>
                ))}
              </ol>
            </Reveal>
          ))}
        </ol>
        <p className={styles.scenariosMore}>
          <Link to="/docs/examples/overview" className="ak-link">
            Browse every example
          </Link>
        </p>
      </div>
    </section>
  );
}

function Teams(): JSX.Element {
  return (
    <section className="ak-section" aria-labelledby="teams">
      <div className="ak-container">
        <SectionHeader
          index="03"
          label="Who it is for"
          title="Four kinds of team"
          lead="OAK is the same runtime for each of them. What changes is the part of the work it removes."
          id="teams"
        />
        <ul className={styles.teams}>
          {TEAMS.map((team) => (
            <li key={team.title} className={clsx('ak-card', styles.team)}>
              <p className="ak-label">{team.kind}</p>
              <h3 className="ak-h4">{team.title}</h3>
              <p className="ak-body">{team.profile}</p>
              <ul className={styles.gains}>
                {team.gains.map((gain) => (
                  <li key={gain}>{gain}</li>
                ))}
              </ul>
              <Link to={team.start.to} className={clsx('ak-link', styles.teamStart)}>
                {team.start.label}
              </Link>
            </li>
          ))}
        </ul>
      </div>
    </section>
  );
}

function WhatYouSkip(): JSX.Element {
  return (
    <section className={clsx('ak-section', 'ak-section--raised')} aria-labelledby="what-you-skip">
      <div className="ak-container">
        <SectionHeader
          index="04"
          label="What you skip"
          title="Seven workstreams, or two"
          lead="Most of the work in a production agent is the platform around it. With that platform already built, the list on the right is what is left."
          id="what-you-skip"
        />
        <div className={styles.compare}>
          <div className={styles.track}>
            <p className="ak-label">Building the platform yourself</p>
            <ol className={styles.steps}>
              {WITHOUT.map((step) => (
                <li key={step.label} className={styles.step}>
                  <span className={styles.stepLabel}>{step.label}</span>
                  <span className={styles.stepDetail}>{step.detail}</span>
                </li>
              ))}
            </ol>
          </div>
          <div className={clsx(styles.track, styles.trackWith)}>
            <p className="ak-label">With OAK</p>
            <ol className={styles.steps}>
              {WITH_OAK.map((step) => (
                <li key={step.label} className={styles.step}>
                  <span className={styles.stepLabel}>{step.label}</span>
                  <span className={styles.stepDetail}>{step.detail}</span>
                </li>
              ))}
            </ol>
            <p className={styles.trackNote}>
              The runtime covers the rest of the left-hand list.{' '}
              <Link to="/features">See how, capability by capability</Link>.
            </p>
          </div>
        </div>
      </div>
    </section>
  );
}

export default function UseCases(): JSX.Element {
  return (
    <Layout
      title="Use cases"
      description="What teams build with Open Agent Kernel: a production deployment, projects in the repository, ten common scenarios with a guide and a working example for each, and the kinds of team OAK fits."
    >
      <main>
        <PageHero
          label="Use cases"
          title="What teams build with OAK"
          lead="A production deployment, two projects you can read end to end, and ten scenarios that each come with a guide and a working example."
          actions={
            <>
              <Link to="/docs/examples/overview" className="ak-btn ak-btn--secondary">
                Browse the examples
              </Link>
              <Link to="/features" className="ak-link">
                See every feature
              </Link>
            </>
          }
        />
        <Projects />
        <Scenarios />
        <Teams />
        <WhatYouSkip />
      </main>
      <ClosingPanel />
    </Layout>
  );
}
