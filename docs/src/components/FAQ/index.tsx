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
      "Agent Kernel is an open-source operating system for building, testing, and deploying scalable, compliant enterprise AI agents. It works with any major AI framework (OpenAI Agents, LangGraph, CrewAI, Google ADK, Smolagents, LiveKit) and provides a unified runtime with built-in messaging, memory management, knowledge bases, guardrails, and observability.",
  },
  {
    id: "do-i-need-team",
    question: "Do I need an AI team to use Agent Kernel?",
    answer:
      "No. Agent Kernel is designed for developers of all skill levels—from beginners to advanced practitioners. Whether you're a solo developer, part of a small startup, or in a large enterprise, Agent Kernel adapts to your needs. It provides pre-built integrations and abstractions that reduce the complexity of building production agents.",
  },
  {
    id: "technical-expertise",
    question: "Do I need deep technical expertise to use it?",
    answer:
      "Not necessarily. While Agent Kernel is a powerful framework for technical teams, it abstracts away much of the complexity of agent infrastructure. If you have basic Python knowledge and familiarity with AI concepts, you can start building agents quickly. Advanced features and customizations are available for those who need them.",
  },
  {
    id: "non-technical",
    question: "Is Agent Kernel suitable for non-technical users?",
    answer:
      "Agent Kernel is primarily designed for developers and technical teams. However, non-technical users can leverage the platform through low-code/no-code interfaces, Agent Kernel's published skills (which can be plugged into any coding agent), or by working with a technical team to build agents that serve their business needs. Our pre-built skills enable rapid deployment of common agent patterns without coding.",
  },
  {
    id: "costs",
    question: "What are the costs involved?",
    answer:
      "Agent Kernel itself is completely free and open-source under the Apache 2.0 license. There are no licensing costs or vendor lock-in. Your costs depend on: (1) Infrastructure (AWS, Azure, GCP) for running agents, (2) LLM API calls (OpenAI, Anthropic, etc.), (3) Optional: managed services like vector databases or memory backends. You control your infrastructure and costs.",
  },
  {
    id: "stands-out",
    question: "What makes Agent Kernel special?",
    answer:
      "Agent Kernel stands out by: (1) Framework-agnostic—works with OpenAI Agents, LangGraph, CrewAI, and more, in a single runtime; (2) Multi-cloud ready—deploy to AWS, Azure, or GCP with pre-built Terraform modules; (3) Production-first—includes built-in testing, observability, guardrails, and session management; (4) Truly open-source—no hidden enterprise versions, Apache 2.0 license; (5) Developer experience—rapid deployment, extensive integrations, and minimal platform code.",
  },
  {
    id: "frameworks-support",
    question: "Does Agent Kernel work with my favorite AI framework?",
    answer:
      "Agent Kernel is framework-agnostic and works with OpenAI Agents, LangGraph, CrewAI, Google ADK, Smolagents, and LiveKit. You can even run multiple frameworks together in a single runtime. If you have a specific framework in mind, our documentation covers integration patterns and examples.",
  },
  {
    id: "how-long-deploy",
    question: "How long does it take to deploy an agent to production?",
    answer:
      "With Agent Kernel, you can go from code to production in minutes. We provide ready-made Terraform modules for AWS, Azure, and GCP, plus Docker support for containerized deployments. There's no complex infrastructure setup required—focus on your agent logic, and we handle the deployment.",
  },
  {
    id: "observability",
    question: "How can I monitor and debug my agents in production?",
    answer:
      "Agent Kernel includes built-in observability with integrations for LangFuse and OpenLLMetry. You get detailed logging, trace tracking, and metrics out of the box. You can also set up custom hooks for analytics, monitoring, and alerting.",
  },
  {
    id: "mcp-support",
    question: "Does Agent Kernel support MCP servers?",
    answer:
      "Yes, Agent Kernel has native support for MCP (Model Context Protocol) servers, allowing your agents to use MCP-compatible tools and resources seamlessly.",
  },
  {
    id: "open-source",
    question: "Is Agent Kernel truly open source?",
    answer:
      "Yes. Agent Kernel is licensed under Apache 2.0 and developed transparently on GitHub. There are no hidden enterprise versions or proprietary extensions. You can contribute, fork, and use it freely in your projects.",
  },
  {
    id: "deployment-options",
    question: "What deployment options are available?",
    answer:
      "Agent Kernel supports multiple deployment patterns: (1) Serverless—AWS Lambda, Azure Functions, Google Cloud Functions; (2) Containerized—Docker, Kubernetes on any cloud; (3) Multi-cloud—Terraform modules for AWS, Azure, and GCP; (4) Hybrid—run parts locally and parts in the cloud. Choose what fits your architecture.",
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
