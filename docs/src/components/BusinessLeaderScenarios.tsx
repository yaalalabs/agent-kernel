import React, { useState } from "react";
import styles from "../pages/index.module.css";

export default function BusinessLeaderScenarios() {
  const [activeTab, setActiveTab] = useState<string>("ecommerce");

  const tabs = [
    { id: "ecommerce", label: "E-Commerce" },
    { id: "sales", label: "Sales" },
    { id: "itops", label: "IT & Ops" },
    { id: "insurance", label: "Insurance" },
    { id: "logistics", label: "Logistics" },
    { id: "hr", label: "HR & Recruiting" },
  ];

  const scenarios: Record<
    string,
    {
      title: string;
      channels: string;
      problem: { heading: string; sub: string; body: string };
      agent: { heading: string; sub: string; body: string };
      whyAk: { heading: string; sub: string; body: string };
    }
  > = {
    ecommerce: {
      title: "Order Management Agent",
      channels: "Website / WhatsApp / Instagram",
      problem: {
        heading: "The Problem",
        sub: "Why it's painful",
        body: 'Customers ask "where\'s my order?" across your website, WhatsApp, and Instagram - and your team copies tracking numbers between systems all day.',
      },
      agent: {
        heading: "The Agent",
        sub: "What it actually does",
        body: "The agent connects to the order system, shipping carriers, and payment gateway. It looks up orders in real time, tracks shipments, processes returns or exchanges, triggers refunds, and keeps the conversation memory across communication channels and sessions.",
      },
      whyAk: {
        heading: "Why Agent Kernel",
        sub: "The Agent Kernel advantage",
        body: "One agent can serve many channels with built-in session memory, guardrails, and cloud deployment flexibility.",
      },
    },
    sales: {
      title: "Lead Qualification Agent",
      channels: "Website / Slack / Email",
      problem: {
        heading: "The Problem",
        sub: "Why it's painful",
        body: "Leads come in from your website, ads, and events - but they sit in a spreadsheet until someone manually qualifies them and books a meeting.",
      },
      agent: {
        heading: "The Agent",
        sub: "What it actually does",
        body: "The agent qualifies leads, scores them, creates CRM contacts, books discovery calls, tags not-ready leads for follow-up, logs notes, and updates deal stages. Specialized agents can split conversation, CRM work, and scheduling.",
      },
      whyAk: {
        heading: "Why Agent Kernel",
        sub: "The Agent Kernel advantage",
        body: "This proves multi-agent collaboration, easy API integrations, and persistent knowledge of a returning lead.",
      },
    },
    itops: {
      title: "IT Help Desk Agent",
      channels: "Slack / Teams / Email",
      problem: {
        heading: "The Problem",
        sub: "Why it's painful",
        body: "Employees submit IT tickets for password resets, software access, and VPN issues - then wait hours for a human to do something that takes 30 seconds.",
      },
      agent: {
        heading: "The Agent",
        sub: "What it actually does",
        body: "The agent works in Slack and Microsoft Teams. It resets passwords through the identity provider, provisions software, restarts services, checks status dashboards, and creates escalation tickets when a human is needed.",
      },
      whyAk: {
        heading: "Why Agent Kernel",
        sub: "The Agent Kernel advantage",
        body: "Customizable workflows via hooks, guardrails, and audit-ready session tracking make action-taking safe and traceable.",
      },
    },
    insurance: {
      title: "Claims Intake Agent",
      channels: "Website / WhatsApp / Email",
      problem: {
        heading: "The Problem",
        sub: "Why it's painful",
        body: "Filing an insurance claim means phone trees, paper forms, and weeks of back-and-forth before anything happens.",
      },
      agent: {
        heading: "The Agent",
        sub: "What it actually does",
        body: "The agent accepts vehicle-damage photos over WhatsApp or Telegram, analyzes them with multimodal support, creates the claim, checks policy details, routes it to the right adjuster, updates the customer, and can trigger payment for straightforward claims.",
      },
      whyAk: {
        heading: "Why Agent Kernel",
        sub: "The Agent Kernel advantage",
        body: "This use case proves multimodal (images and files) input, multi-agent pipelines, guardrails for regulated data, and persistent, long running user sessions.",
      },
    },
    logistics: {
      title: "Shipment Tracking Agent",
      channels: "WhatsApp / Telegram / Email",
      problem: {
        heading: "The Problem",
        sub: "Why it's painful",
        body: "Your operations team juggles dashboards, carrier portals, and a shared inbox to keep shipments on track - and customers still get surprised by delays.",
      },
      agent: {
        heading: "The Agent",
        sub: "What it actually does",
        body: "The agent monitors carrier APIs, spots delays, reroutes shipments, updates ETAs, notifies customers on their preferred channel, and alerts internal teams in Slack. Different agents can monitor, communicate, and coordinate operations.",
      },
      whyAk: {
        heading: "Why Agent Kernel",
        sub: "The Agent Kernel advantage",
        body: "This shows multi-channel notifications, multi-agent coordination, cloud flexibility, and observability of every decision.",
      },
    },
    hr: {
      title: "Recruiting Screener Agent",
      channels: "Email / Slack / Website",
      problem: {
        heading: "The Problem",
        sub: "Why it's painful",
        body: "Your hiring pipeline is bottlenecked by scheduling, reminders, interviewer feedback, and stage updates rather than by finding candidates.",
      },
      agent: {
        heading: "The Agent",
        sub: "What it actually does",
        body: "When a candidate enters the interview stage, the agent checks availability, sends scheduling links over email, confirms bookings, creates meeting rooms, sends reminders, prompts interviewers for feedback in Slack, compiles summaries, and updates the Application Tracking System (ATS).",
      },
      whyAk: {
        heading: "Why Agent Kernel",
        sub: "The Agent Kernel advantage",
        body: "This demonstrates Gmail integration, Slack coordination, ATS and calendar tool use, and long-running session memory across the candidate journey.",
      },
    },
  };

  const active = scenarios[activeTab];

  return (
    <div className={styles.blScenarios}>
      {/* ── Tab buttons — horizontally scrollable on mobile ── */}
      <div
        className={styles.blTabBar}
        role="tablist"
        aria-label="Industry scenarios"
      >
        {tabs.map((t) => (
          <button
            key={t.id}
            role="tab"
            aria-selected={activeTab === t.id}
            onClick={() => setActiveTab(t.id)}
            className={`${styles.blTab} ${activeTab === t.id ? styles.blTabActive : ""}`}
          >
            {t.label}
          </button>
        ))}
      </div>

      {/* ── Scenario content ── */}
      <div className={styles.blScenarioContent}>
        <h3 className={styles.blScenarioTitle}>{active.title}</h3>
        <p className={styles.blScenarioChannels}>{active.channels}</p>

        <div className={styles.blScenarioCols}>
          {[active.problem, active.agent, active.whyAk].map((col) => (
            <div key={col.heading} className={styles.blScenarioCol}>
              <p className={styles.blScenarioColHeading}>{col.heading}</p>
              <p className={styles.blScenarioColSub}>{col.sub}</p>
              <p className={styles.blScenarioColBody}>{col.body}</p>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
