import React from 'react';
import clsx from 'clsx';
import { Tabs, type TabItem } from '@site/src/components/PersonaKit';
import styles from '@site/src/pages/persona.module.css';

type Scenario = {
  id: string;
  /** The industry, shown on the tab. */
  label: string;
  /** The agent this industry would start with. */
  title: string;
  channels: string[];
  problem: string;
  agent: string;
  why: string;
};

const SCENARIOS: Scenario[] = [
  {
    id: 'ecommerce',
    label: 'E-commerce',
    title: 'Order management agent',
    channels: ['Website', 'WhatsApp', 'Instagram'],
    problem:
      'Customers ask "where is my order?" on your website, WhatsApp and Instagram, and your team copies tracking numbers between systems all day.',
    agent:
      'It connects to the order system, the shipping carriers and the payment gateway. It looks up orders, tracks shipments, processes returns and exchanges, triggers refunds, and keeps the conversation going when the customer moves to another channel.',
    why: 'One agent serves every channel, with session memory, guardrails and a free choice of cloud built in.',
  },
  {
    id: 'sales',
    label: 'Sales',
    title: 'Lead qualification agent',
    channels: ['Website', 'Slack', 'Email'],
    problem:
      'Leads arrive from your website, ads and events, then wait in a spreadsheet until someone qualifies them by hand and books a meeting.',
    agent:
      'It qualifies and scores leads, creates CRM contacts, books discovery calls, tags leads that are not ready for follow-up, logs notes and updates deal stages. Specialist agents can split the conversation, the CRM work and the scheduling.',
    why: 'Agents work together in one runtime, tools call your CRM, and the session remembers a returning lead.',
  },
  {
    id: 'itops',
    label: 'IT and operations',
    title: 'IT help desk agent',
    channels: ['Slack', 'Teams', 'Email'],
    problem:
      'Employees raise tickets for password resets, software access and VPN issues, then wait hours for a human to do something that takes 30 seconds.',
    agent:
      'It works in Slack and Microsoft Teams. It resets passwords through the identity provider, provisions software, restarts services, checks status dashboards and opens an escalation ticket when a human is needed.',
    why: 'Hooks shape the workflow, guardrails limit what the agent may do, and every session can be traced for audit.',
  },
  {
    id: 'insurance',
    label: 'Insurance',
    title: 'Claims intake agent',
    channels: ['Website', 'WhatsApp', 'Email'],
    problem:
      'Filing a claim means phone trees, paper forms and weeks of back and forth before anything happens.',
    agent:
      'It accepts photos of vehicle damage over WhatsApp or Telegram, analyses them, creates the claim, checks the policy, routes it to the right adjuster, keeps the customer updated and can trigger payment for straightforward cases.',
    why: 'Images and files are handled in the runtime, guardrails protect regulated data, and long-running sessions persist.',
  },
  {
    id: 'logistics',
    label: 'Logistics',
    title: 'Shipment tracking agent',
    channels: ['WhatsApp', 'Telegram', 'Email'],
    problem:
      'Your operations team juggles dashboards, carrier portals and a shared inbox to keep shipments on track, and customers are still surprised by delays.',
    agent:
      'It watches carrier APIs, spots delays, reroutes shipments, updates arrival times, notifies customers on the channel they prefer and alerts internal teams in Slack. Separate agents can monitor, communicate and coordinate.',
    why: 'Notifications go out on several channels, agents coordinate with each other, and every decision is visible in a trace.',
  },
  {
    id: 'hr',
    label: 'HR and recruiting',
    title: 'Recruiting screener agent',
    channels: ['Email', 'Slack', 'Website'],
    problem:
      'Your hiring pipeline is held up by scheduling, reminders, interviewer feedback and stage updates, not by finding candidates.',
    agent:
      'When a candidate reaches the interview stage, it checks availability, sends scheduling links by email, confirms bookings, creates meeting rooms, sends reminders, prompts interviewers for feedback in Slack, compiles summaries and updates the stage.',
    why: 'Gmail and Slack are built-in integrations, tools reach your calendar and applicant tracking system, and session memory follows the candidate.',
  },
];

function ScenarioPanel({ scenario }: { scenario: Scenario }): JSX.Element {
  const columns = [
    { key: 'problem', label: 'The problem', body: scenario.problem, tone: undefined },
    { key: 'agent', label: 'What the agent does', body: scenario.agent, tone: styles.scenarioColNow },
    { key: 'why', label: 'Why OAK', body: scenario.why, tone: styles.scenarioColAfter },
  ];
  return (
    <div className={styles.scenario}>
      <div className={styles.scenarioHead}>
        <h3 className="ak-h3">{scenario.title}</h3>
        <ul className={clsx('ak-tag-row', styles.plainList)} aria-label="Channels">
          {scenario.channels.map((channel) => (
            <li key={channel} className="ak-tag">
              {channel}
            </li>
          ))}
        </ul>
      </div>
      <div className={styles.scenarioCols}>
        {columns.map((column) => (
          <div key={column.key} className={clsx(styles.scenarioCol, column.tone)}>
            <p className={clsx('ak-label', styles.scenarioLabel)}>{column.label}</p>
            <p className="ak-body">{column.body}</p>
          </div>
        ))}
      </div>
    </div>
  );
}

const ITEMS: TabItem[] = SCENARIOS.map((scenario) => ({
  id: scenario.id,
  label: scenario.label,
  content: <ScenarioPanel scenario={scenario} />,
}));

/** Six starting points by industry: the problem, what an agent does about it, and what OAK adds. */
export default function BusinessLeaderScenarios(): JSX.Element {
  return <Tabs name="scenario" label="Industries" items={ITEMS} />;
}
