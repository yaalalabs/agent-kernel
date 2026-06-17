import React, { useState } from "react";
import styles from "./styles.module.css";
import pageStyles from "../../pages/index.module.css";

interface FAQItem {
  id: string;
  question: string;
  answer: string;
}

const FAQ_ITEMS: FAQItem[] = [
  {
    id: "what-is",
    question: "What is Agent Kernel?",
    answer:
      "Agent Kernel is an open-source operating system that makes it straightforward to build, test, and deploy AI agents at scale. It works with the AI frameworks you already know (OpenAI Agents, LangGraph, CrewAI, Google ADK, Smolagents, LiveKit) and gives you a single runtime with messaging, memory, knowledge bases, guardrails, and observability baked in. Write your agent code once and deploy it to AWS, Google Cloud, Azure, or on-prem without any rewrites.",
  },
  {
    id: "do-i-need-team",
    question: "Do I need an AI team to use Agent Kernel?",
    answer:
      "Not at all. Agent Kernel is built for developers at all skill levels, from beginners to seasoned practitioners. Whether you're working solo, at a startup, or inside a large enterprise, it adapts to your situation. Pre-built integrations and sensible abstractions take care of the heavy lifting so you can focus on building.",
  },
  {
    id: "technical-expertise",
    question: "Do I need deep technical expertise to use it?",
    answer:
      "Not really. Agent Kernel handles a lot of the underlying complexity for you. If you know basic Python and have some familiarity with AI concepts, you can start building agents pretty quickly. And if you need to go deeper, the advanced features are there when you're ready.",
  },
  {
    id: "non-technical",
    question: "Is Agent Kernel suitable for non-technical users?",
    answer:
      "Honestly, Agent Kernel is built for developers and technical teams. That said, non-technical users can still get value from it through low-code/no-code interfaces, our published skills (which plug into any coding agent), or by teaming up with developers who can build what they need. Pre-built skills make it possible to deploy common agent patterns without writing code.",
  },
  {
    id: "costs",
    question: "What are the costs involved?",
    answer:
      "Agent Kernel itself is completely free and open-source under the Apache 2.0 license. No licensing fees, no vendor lock-in. The costs you will see are for the infrastructure you choose to run your agents on (AWS, Azure, GCP), the LLM API calls you make (OpenAI, Anthropic, etc.), and optionally any managed services like vector databases or memory backends. You stay in control of what you spend.",
  },
  {
    id: "stands-out",
    question: "What makes Agent Kernel special?",
    answer:
      "A few things set it apart. It's framework-agnostic, so you can run OpenAI Agents, LangGraph, CrewAI, and more in a single runtime. It's built for multi-cloud from day one, with pre-built Terraform modules for AWS, Azure, and GCP. It's production-first, with testing, observability, guardrails, and session management included. It's genuinely open-source under Apache 2.0, with no hidden enterprise editions. And the developer experience is a real priority: fast deployments, broad integrations, and minimal boilerplate.",
  },
  {
    id: "frameworks-support",
    question: "Does Agent Kernel work with my favorite AI framework?",
    answer:
      "Yes. Agent Kernel works with OpenAI Agents, LangGraph, CrewAI, Google ADK, Smolagents, and LiveKit out of the box. You can even mix frameworks in a single runtime. Our docs have integration guides and examples for each one.",
  },
  {
    id: "how-long-deploy",
    question: "How long does it take to deploy an agent to production?",
    answer:
      "Faster than you might expect. We have ready-made Terraform modules for AWS, Azure, and GCP, plus Docker support for containerized deployments. There's no complex infrastructure setup to wade through. Write your agent logic and we handle getting it live.",
  },
  {
    id: "observability",
    question: "How can I monitor and debug my agents in production?",
    answer:
      "Agent Kernel comes with built-in observability through LangFuse and OpenLLMetry. You get detailed logs, trace tracking, and metrics without any extra setup. Need something more custom? You can wire up hooks for your own analytics, monitoring, and alerting too.",
  },
  {
    id: "mcp-support",
    question: "Does Agent Kernel support MCP servers?",
    answer:
      "Yes. Agent Kernel has native MCP (Model Context Protocol) support, so your agents can use any MCP-compatible tools and resources without extra configuration.",
  },
  {
    id: "open-source",
    question: "Is Agent Kernel truly open source?",
    answer:
      "Yes, completely. Agent Kernel is Apache 2.0 licensed and developed in the open on GitHub. There are no hidden enterprise tiers or proprietary add-ons. Fork it, contribute to it, or use it in your own projects however you like.",
  },
  {
    id: "deployment-options",
    question: "What deployment options are available?",
    answer:
      "There are several options depending on your setup. You can go serverless with AWS Lambda, Azure Functions, or Google Cloud Functions. You can containerize with Docker or Kubernetes on any cloud. You can use our Terraform modules for a full multi-cloud deployment. Or you can run a hybrid setup with some parts local and some in the cloud. Pick what works best for your architecture.",
  },
];

export default function FAQ() {
  const [expandedId, setExpandedId] = useState<string | null>(null);

  const toggleItem = (id: string) => {
    setExpandedId(expandedId === id ? null : id);
  };

  return (
    <section className={styles.faqSection}>
      <div className={pageStyles.topGlow} />
      <div className="container">
        <div className={styles.faqHeader}>
          <div className={styles.faqBadge}>
            <span className={styles.badgeStar}>✦</span>
            Frequently Asked Questions
          </div>
          <h2 className={styles.faqTitle}>Questions We Hear a Lot</h2>
          <p className={styles.faqSubtitle}>
            Explore answers to common questions about Agent Kernel, its capabilities,
            costs, deployment, and more.
          </p>
        </div>

        <div className={styles.faqContainer}>
          {FAQ_ITEMS.map((item) => (
            <div key={item.id} className={styles.faqItem}>
              <button
                id={`question-${item.id}`}
                type="button"
                className={`${styles.faqQuestion} ${
                  expandedId === item.id ? styles.expanded : ""
                }`}
                onClick={() => toggleItem(item.id)}
                aria-expanded={expandedId === item.id}
                aria-controls={`faq-${item.id}`}
              >
                <span className={styles.questionText}>{item.question}</span>
                <span className={styles.toggleIcon} aria-hidden="true">
                  <svg
                    width="20"
                    height="20"
                    viewBox="0 0 24 24"
                    fill="none"
                    stroke="currentColor"
                    strokeWidth="2"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                  >
                    <polyline points="6 9 12 15 18 9" />
                  </svg>
                </span>
              </button>
              {expandedId === item.id && (
                <div
                  id={`faq-${item.id}`}
                  className={styles.faqAnswer}
                  role="region"
                  aria-labelledby={`question-${item.id}`}
                >
                  <p>{item.answer}</p>
                </div>
              )}
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}
