import React from 'react';
import clsx from 'clsx';
import Link from '@docusaurus/Link';
import Layout from '@theme/Layout';
import { TbCloud, TbMessageCircle, TbRocket } from 'react-icons/tb';
import PageHero from '@site/src/components/ui/PageHero';
import LevelStack from '@site/src/components/LevelStack';
import { ClosingPanel } from '@site/src/components/HomeSections';
import type { Step } from '@site/src/components/StepTimeline';
import { DocLinks, Journey, OtherLevels, PersonaSection } from '@site/src/components/PersonaKit';
import AgentExecutionFlowDiagram from '@site/src/components/AgentExecutionFlowDiagram';
import BusinessLeaderScenarios from '@site/src/components/BusinessLeaderScenarios';
import styles from './persona.module.css';

const STEPS: Step[] = [
  { id: 'gap', label: 'The gap' },
  { id: 'agent', label: 'The agent' },
  { id: 'platform', label: 'The platform' },
  { id: 'industry', label: 'Your industry' },
  { id: 'commitment', label: 'The commitment' },
];

const GAPS = [
  {
    audience: 'You have a product',
    question: 'Do your users still do the work by hand?',
    points: [
      'Users do too much manually inside your app',
      'Support tickets pile up for questions the product could answer',
      'Repetitive workflows need a person every time',
    ],
  },
  {
    audience: 'You run large operations',
    question: 'Is your team the bottleneck?',
    points: [
      'Thousands of customer queries reach an overstretched team',
      'Knowledge is locked in separate systems and documents',
      'Hand-offs between teams are slow and error-prone',
    ],
  },
  {
    audience: 'You are building something new',
    question: 'Do you have an idea and no platform?',
    points: [
      'You see room for an AI-powered service in your industry',
      'You are not sure which AI technology to commit to',
      'You want a working proof of concept before a large investment',
    ],
  },
];

const VALUES = [
  {
    Icon: TbRocket,
    title: 'Days, not months',
    body: 'Nobody has to build agent infrastructure first. The API, memory, safety checks and deployment are already there, so the work goes into what the agent does.',
  },
  {
    Icon: TbMessageCircle,
    title: 'Works where your people are',
    body: 'Connectors for Slack, WhatsApp, Teams, Telegram, Gmail, Messenger and Instagram are built in. The same agent can answer on each of them.',
  },
  {
    Icon: TbCloud,
    title: 'Runs on the cloud you already use',
    body: 'Deploy on AWS, Azure, Google Cloud or your own Kubernetes cluster, and move later without rewriting the agent.',
  },
];

const QUESTIONS = [
  {
    question: 'What does it cost?',
    answer:
      'OAK is open source under the Apache 2.0 licence, with no licence fee. You pay for the cloud resources your agents run on and for the AI models they call.',
  },
  {
    question: 'Are we locked in?',
    answer:
      'No. Agents written with any of eight agent frameworks run side by side, and the same agent deploys to AWS, Azure, Google Cloud or your own Kubernetes cluster. Each choice is a setting, not a rewrite.',
  },
  {
    question: 'Where does it run?',
    answer:
      'In your own cloud account or on your own cluster, set up with the Terraform modules and the Helm chart that come with OAK. Conversation history is kept in a data store you choose.',
  },
  {
    question: 'How do we keep agents in line?',
    answer:
      'Guardrails check what goes into an agent and what comes out of it, and every run can be traced, so that you can see what an agent did and why.',
  },
];

export default function BusinessLeaderPage(): JSX.Element {
  return (
    <Layout
      title="Open Agent Kernel for business leaders"
      description="What AI agents change for a business, what Open Agent Kernel is in plain words, and what adopting it commits you to."
    >
      <PageHero
        back={{ to: '/#levels', label: 'Back to path selection' }}
        art={<LevelStack active={0} />}
        label="Level 01 / Business leaders"
        title="Put AI agents to work across your business"
        lead="Open Agent Kernel (OAK) is the open-source platform that takes an AI agent from a demo to a service your customers and staff can rely on. This page explains what that means for a business, without the engineering detail."
        actions={
          <>
            <Link to="#industry" className="ak-btn ak-btn--primary">
              See it in your industry
            </Link>
            <Link to="/use-cases" className="ak-link">
              Browse use cases
            </Link>
          </>
        }
      />
      <Journey steps={STEPS}>
        <PersonaSection
          id="gap"
          index="01"
          label="The gap"
          title="Where agents pay off"
          lead="Most businesses have work that still depends too much on people: repetitive, slow and hard to scale. The gap looks different depending on where you stand."
        >
          <div className={styles.grid3}>
            {GAPS.map((gap) => (
              <div key={gap.audience} className={clsx('ak-card', styles.card)}>
                <p className="ak-label">{gap.audience}</p>
                <h3 className="ak-h4">{gap.question}</h3>
                <ul className={styles.points}>
                  {gap.points.map((point) => (
                    <li key={point}>{point}</li>
                  ))}
                </ul>
              </div>
            ))}
          </div>
        </PersonaSection>

        <PersonaSection
          id="agent"
          index="02"
          label="The agent"
          title="An agent does not just answer, it gets the work done"
          lead="A chatbot replies to a question. An agent is given a goal, and works towards it in a loop until the job is finished."
        >
          <AgentExecutionFlowDiagram />
          <p className={clsx('ak-small', styles.caption)}>
            The loop an agent runs: it takes a goal, makes a plan, checks the plan, acts, gathers feedback and observes
            the result, improves, and goes round again.
          </p>
        </PersonaSection>

        <PersonaSection
          id="platform"
          index="03"
          label="The platform"
          title="OAK is the operating system underneath"
          lead="One agent on a laptop is a demo. Agents that serve real users, day after day, need a platform under them. OAK is that platform."
        >
          <div className={styles.split}>
            <div className={styles.stack}>
              <p className="ak-body">
                You do not need to know how an operating system works to use a computer. It runs behind the scenes and
                takes care of everything the applications have in common.
              </p>
              <p className="ak-body">
                OAK does the same for AI agents. It runs them in the background and handles what every agent needs:
                conversations that are remembered, connections to the channels people use, safety checks, and room to
                grow from a handful of users to thousands. Your team works on what the agent should do.
              </p>
              <Link to="/features" className="ak-link">
                See everything OAK handles
              </Link>
            </div>
            <ul className={styles.values}>
              {VALUES.map(({ Icon, title, body }) => (
                <li key={title} className={styles.value}>
                  <Icon className={styles.valueIcon} aria-hidden="true" />
                  <div className={styles.valueText}>
                    <h3 className="ak-h4">{title}</h3>
                    <p className="ak-body">{body}</p>
                  </div>
                </li>
              ))}
            </ul>
          </div>
        </PersonaSection>

        <PersonaSection
          id="industry"
          index="04"
          label="Your industry"
          title="What it looks like in your industry"
          lead="Six starting points. Each one is an agent a team could put in front of real users, on the channels they already use."
        >
          <BusinessLeaderScenarios />
        </PersonaSection>

        <PersonaSection
          id="commitment"
          index="05"
          label="The commitment"
          title="What adopting OAK commits you to"
          lead="The questions a leader asks before saying yes, answered plainly."
        >
          <dl className={styles.qa}>
            {QUESTIONS.map((item) => (
              <div key={item.question} className={styles.qaItem}>
                <dt className="ak-h4">{item.question}</dt>
                <dd className="ak-body">{item.answer}</dd>
              </div>
            ))}
          </dl>
          <div className={styles.blockSmall}>
            <DocLinks
              links={[
                { label: 'Deployment options', to: '/docs/deployment/overview' },
                { label: 'Guardrails', to: '/docs/advanced/guardrails' },
                { label: 'Tracing', to: '/docs/advanced/traceability' },
              ]}
            />
          </div>
        </PersonaSection>
      </Journey>

      <OtherLevels current="business-leader" />
      <ClosingPanel />
    </Layout>
  );
}
