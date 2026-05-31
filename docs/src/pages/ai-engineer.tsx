import React, { useEffect, useRef, useState } from "react";
import gsap from "gsap";
import ScrollTrigger from "gsap/dist/ScrollTrigger";
import Link from "@docusaurus/Link";
import Layout from "@theme/Layout";
import { StepTimeline } from "../components/StepTimeline";
import styles from "./index.module.css";
import {
  MdCloud,
  MdSecurity,
  MdVisibility,
  MdCode,
  MdAutoAwesome,
  MdTerminal,
  MdBolt,
  MdMessage,
  MdScience,
  MdLink,
  MdSmartToy,
  MdPermMedia,
  MdLanguage,
  MdCheck,
  MdClose,
  MdForum,
  MdCached,
  MdStorage,
  MdShield,
  MdStopCircle,
} from "react-icons/md";
import BuildingAgentsFlowDiagram from "../components/BuildingAgentsFlowDiagram";
import RunningAgentsFlowDiagram from "../components/RunningAgentsFlowDiagram";
import AgentKernelSitsInFlowDiagram from "../components/AgentKernelSitsInFlowDiagram";
import AgentKernelArchDiagram from "../components/AgentKernelArchDiagram";
import HeroAnimation from "../components/HeroAnimation";

export default function AIEngineerPage() {
  const contentRef = useRef<HTMLDivElement>(null);
  const [selectedFramework, setSelectedFramework] = useState<string>("openai");
  const [copiedCode, setCopiedCode] = useState<string | null>(null);

  const AI_ENGINEER_ARCH_LAYERS = [
    {
      num: "01",
      label: "Your Agent Logic",
      items: ["Domain-Specific Agent Code", "Business Rules", "Prompts & Tools"],
    },
    {
      num: "02",
      label: "Agent Kernel Core",
      items: [
        "Agent Module",
        "Agent Wrapper",
        "Framework-Specific Runner",
        "Session Manager",
        "Runtime",
        "Pre / Post Hooks",
      ],
    },
    {
      num: "03",
      label: "Framework Adapters",
      items: [
        "LangGraph",
        "OpenAI Agents",
        "CrewAI",
        "Google ADK",
        "Smolagents",
        "LiveKit",
        "Bring your own [advanced]",
      ],
    },
    {
      num: "04",
      label: "Storage & Memory",
      items: ["In-Memory", "Redis", "DynamoDB", "CosmosDB", "Firestore"],
    },
    {
      num: "05",
      label: "Knowledge Bases",
      items: ["ChromaDB", "Neo4j", "Starburst", "SQLDB"],
    },
    {
      num: "06",
      label: "Observability",
      items: ["LangFuse", "OpenLLMetry"],
    },
    {
      num: "07",
      label: "Execution Surface",
      items: [
        "AWS Lambda",
        "ECS",
        "Azure Functions",
        "Container Apps",
        "GCP Cloud Run",
        "GCP Cloud Run Functions",
      ],
    },
    {
      num: "08",
      label: "Interfacing",
      items: ["CLI", "MCP", "A2A", "REST API"],
    },
    {
      num: "09",
      label: "Channels",
      items: [
        "Slack",
        "Teams",
        "WhatsApp",
        "Telegram",
        "Messenger",
        "Instagram",
        "Gmail",
        "Redis",
        "DynamoDB",
      ],
    },
  ];

  const AI_ENGINEER_MEMORY_LAYERS = [
    {
      title: "Conversational State (Session)",
      icon: MdForum,
      bullets: [
        "The agent remembers the conversation naturally across turns.",
        "This is the memory that keeps chat continuity.",
      ],
    },
    {
      title: "Volatile Cache (Per Request)",
      icon: MdCached,
      bullets: [
        "A scratchpad for one request only.",
        "Great for RAG snippets, temporary file reads, and intermediate results.",
        "Auto-clears after every response.",
      ],
    },
    {
      title: "Non-Volatile Cache (Session)",
      icon: MdStorage,
      bullets: [
        "Session memory for supporting data that should persist.",
        "Perfect for user preferences, auth context, and running counters.",
        "Available to tools/hooks without spending LLM tokens.",
      ],
    },
  ] as const;
  
  const AI_ENGINEER_HOOK_PIPELINE = [
    {
      title: "Pre-Execution Hooks",
      icon: MdShield,
      bullets: [
        "Validate and enrich input before the LLM runs.",
        "Typical uses: guardrails, redaction, RAG injection, request shaping.",
      ],
      highlight: false,
    },
    {
      title: "Agent Execution",
      icon: MdSmartToy,
      bullets: ["Your existing framework logic runs as-is."],
      highlight: false,
    },
    {
      title: "Post-Execution Hooks",
      icon: MdSecurity,
      bullets: [
        "Apply output checks and final formatting before returning to users.",
        "Typical uses: moderation, compliance notes, analytics, audit logging.",
      ],
      highlight: false,
    },
    {
      title: "Early Termination",
      icon: MdStopCircle,
      badge: "Early termination",
      bullets: [
        "Stop unsafe or invalid requests early and return a controlled response.",
        "Useful for input guardrails, rate limits, cached shortcuts, and circuit breakers.",
      ],
      highlight: true,
    },
  ] as const;

  const AI_ENGINEER_COMPARE_COLUMNS = {
    cloud: "Bedrock AgentCore / Azure AI Foundry / Google Vertex AI",
    cloudShort: "Bedrock / Azure / Google",
    frameworks: "LangGraph · CrewAI · OpenAI Agents etc",
    frameworksShort: "LangGraph · CrewAI · OpenAI",
    agentKernel: "Agent Kernel",
  } as const;

  type AkCompareCellStatus = "positive" | "negative" | "partial";

  interface AkCompareCell {
    status: AkCompareCellStatus;
    text?: string;
  }

  const AI_ENGINEER_COMPARISON_ROWS: {
    feature: string;
    featureHint?: string;
    cloud: AkCompareCell;
    frameworks: AkCompareCell;
    agentKernel: AkCompareCell;
  }[] = [
    {
      feature: "Switch cloud platform later?",
      cloud: { status: "negative", text: "Rewrite" },
      frameworks: { status: "positive", text: "You build it" },
      agentKernel: { status: "positive", text: "One config change" },
    },
    {
      feature: "Multi-framework agent execution?",
      cloud: { status: "negative", text: "Not possible" },
      frameworks: { status: "negative", text: "Not possible" },
      agentKernel: { status: "positive", text: "Run in one runtime" },
    },
    {
      feature: "Out of Box integrations?",
      featureHint: "(i.e. Slack / Teams / REST / A2A / MCP)",
      cloud: { status: "partial", text: "Partial" },
      frameworks: { status: "negative", text: "DIY" },
      agentKernel: { status: "positive", text: "Built-in" },
    },
    {
      feature: "Sessions, memory, observability?",
      cloud: { status: "positive", text: "Proprietary" },
      frameworks: { status: "negative", text: "DIY" },
      agentKernel: { status: "positive", text: "Built-in and Pluggable" },
    },
    {
      feature: "Open-source / no licensing?",
      cloud: { status: "negative" },
      frameworks: { status: "positive" },
      agentKernel: { status: "positive", text: "Apache 2.0" },
    },
    {
      feature: "Knowledge bases?",
      cloud: { status: "positive", text: "Proprietary" },
      frameworks: { status: "negative", text: "DIY" },
      agentKernel: { status: "positive", text: "Built-in and Pluggable" },
    },
    {
      feature: "Lift-and-shift an existing agent?",
      cloud: { status: "negative", text: "Rewrite" },
      frameworks: { status: "negative", text: "Rewrite" },
      agentKernel: { status: "positive", text: "Wrap & ship" },
    },
  ];

  function AkCompareCellContent({ cell }: { cell: AkCompareCell }) {
    if (cell.status === "partial") {
      return <span className={styles.akComparePartial}>{cell.text}</span>;
    }

    const Icon = cell.status === "positive" ? MdCheck : MdClose;
    const iconClass =
      cell.status === "positive"
        ? styles.akCompareIconPos
        : styles.akCompareIconNeg;

    return (
      <span className={styles.akCompareCellValue}>
        <Icon className={iconClass} aria-hidden />
        {cell.text ? <span>{cell.text}</span> : null}
      </span>
    );
  }

  const DEV_FEATURE_GROUPS = [
    {
      title: "Build & Interface",
      cols: 4 as const,
      features: [
        {
          icon: MdTerminal,
          title: "CLI for Prototyping",
          body: "Easy interfacing your agents on your laptop via Agent Kernel’s command line interface.",
        },
        {
          icon: MdBolt,
          title: "REST API Server",
          body: "FastAPI-based server out of the box. No boilerplate. Just run your agent.",
        },
        {
          icon: MdCode,
          title: "Native MCP and A2A support",
          body: "Expose agents as tools (MCP) and enable agent-to-agent collaboration (A2A). Makes integration with external AI systems straightforward.",
        },
        {
          icon: MdAutoAwesome,
          title: "Multi-Framework Support",
          body: "Run OpenAI Agents, LangGraph, CrewAI, Google ADK, Smolagents, LiveKit side-by-side. Keep one runtime across teams while using the best framework per use case.",
        },
      ],
    },
    {
      title: "Runtime & Extensibility",
      cols: 3 as const,
      features: [
        {
          icon: MdSmartToy,
          title: "Pluggable Session & Memory",
          body: "Start local in-memory, scale to Redis, DynamoDB, or Cosmos DB in production. Switch via config, not code rewrites.",
        },
        {
          icon: MdLink,
          title: "Execution Hooks",
          body: "Pre/post hooks for RAG injection, input validation, response moderation, analytics.",
        },
        {
          icon: MdPermMedia,
          title: "Multimodal Support",
          body: "In-built framework-neutral multimodal support across all integration channels. Handle files/images cleanly and keep sessions lightweight. Additional voice and video support via LiveKit.",
        },
      ],
    },
    {
      title: "Ship & Secure",
      cols: 3 as const,
      features: [
        {
          icon: MdSecurity,
          title: "Guardrails and Content Safety",
          body: "Input and output protection in the same runtime pipeline. Supports policy checks for safety, PII handling, and jailbreak defense.",
        },
        {
          icon: MdCloud,
          title: "Cloud Deployment",
          body: "Pre-built Terraform modules for AWS Lambda, ECS, Azure Functions, Container Apps, GCP Cloud Run, GCP Cloud Run Functions.",
        },
        {
          icon: MdLanguage,
          title: "Reliability",
          body: "Built for resilient cloud deployments with health checks and failover patterns.",
        },
      ],
    },
    {
      title: "Integrate & Observe",
      cols: 3 as const,
      features: [
        {
          icon: MdMessage,
          title: "Messaging Integrations",
          body: "Slack, WhatsApp, Instagram, Telegram, Gmail, Teams, Messenger plug and play.",
        },
        {
          icon: MdScience,
          title: "Testing Framework",
          body: "pytest-integrated test runner. Write deterministic automated test scenarios for your AI agents like any other code.",
        },
        {
          icon: MdVisibility,
          title: "Observability",
          body: "Langfuse and OpenLLMetry tracing with one config line. No manual instrumentation. Trace requests, latency, tool calls, and token behavior.",
        },
      ],
    },
  ];

  const copyToClipboard = (code: string, id: string) => {
    navigator.clipboard.writeText(code);
    setCopiedCode(id);
    setTimeout(() => setCopiedCode(null), 2000);
  };

  useEffect(() => {
    gsap.registerPlugin(ScrollTrigger);

    if (!contentRef.current) {
      return;
    }

    const context = gsap.context(() => {
      const root = contentRef.current;
      if (!root) {
        return;
      }

      const animateSections = [
        `.${styles.developerAnalogy}`,
        `.${styles.architectureWrapper}`,
        `.${styles.akStandOutSection}`,
        `.${styles.devFeatureSection}`,
        `.${styles.devFrameworkSection}`,
        `.${styles.aiEngineerBuildSection}`,
        `.${styles.devArchitectureSection}`,
      ];

      animateSections.forEach((selector, index) => {
        const sections = root.querySelectorAll(selector);
        sections.forEach((section) => {
          gsap.fromTo(
            section,
            { opacity: 0, y: 36 },
            {
              opacity: 1,
              y: 0,
              duration: 1,
              ease: "power2.out",
              delay: index * 0.08,
              scrollTrigger: {
                trigger: section,
                start: "top 84%",
                toggleActions: "play none none reverse",
              },
            },
          );
        });
      });

      const architectureLayers = root.querySelectorAll(
        `.${styles.architectureLayerGroup}`,
      );
      architectureLayers.forEach((layer, index) => {
        gsap.fromTo(
          layer,
          { opacity: 0, x: -50 },
          {
            opacity: 1,
            x: 0,
            duration: 0.9,
            delay: index * 0.12,
            ease: "power2.out",
            scrollTrigger: {
              trigger: layer,
              start: "top 85%",
              toggleActions: "play none none reverse",
            },
          },
        );
      });

      const comparePanel = root.querySelector(`.${styles.akComparePanel}`);
      if (comparePanel) {
        gsap.fromTo(
          comparePanel,
          { opacity: 0, y: 30, scale: 0.98 },
          {
            opacity: 1,
            y: 0,
            scale: 1,
            duration: 0.95,
            ease: "power2.out",
            scrollTrigger: {
              trigger: comparePanel,
              start: "top 86%",
              toggleActions: "play none none reverse",
            },
          },
        );
      }

      const comparisonCards = root.querySelectorAll(
        `.${styles.akCompareMobileCard}`,
      );
      comparisonCards.forEach((card, index) => {
        gsap.fromTo(
          card,
          { opacity: 0, y: 24, scale: 0.97 },
          {
            opacity: 1,
            y: 0,
            scale: 1,
            duration: 0.85,
            ease: "power2.out",
            delay: index * 0.07,
            scrollTrigger: {
              trigger: card,
              start: "top 88%",
              toggleActions: "play none none reverse",
            },
          },
        );
      });

      const featureCards = root.querySelectorAll(`.${styles.devFeatureCard}`);
      featureCards.forEach((card, index) => {
        gsap.fromTo(
          card,
          { opacity: 0, y: 24, scale: 0.96 },
          {
            opacity: 1,
            y: 0,
            scale: 1,
            duration: 0.9,
            ease: "power2.out",
            delay: (index % 3) * 0.08,
            scrollTrigger: {
              trigger: card,
              start: "top 88%",
              toggleActions: "play none none reverse",
            },
          },
        );
      });

      const frameworkButtons = root.querySelectorAll(
        `.${styles.devFrameworkButton}`,
      );
      frameworkButtons.forEach((button, index) => {
        gsap.fromTo(
          button,
          { opacity: 0, y: 16, scale: 0.95 },
          {
            opacity: 1,
            y: 0,
            scale: 1,
            duration: 0.7,
            ease: "power2.out",
            delay: index * 0.08,
            scrollTrigger: {
              trigger: button,
              start: "top 90%",
              toggleActions: "play none none reverse",
            },
          },
        );
      });

      const codeBlocks = root.querySelectorAll(
        `.${styles.devFrameworkCodeBlock}`,
      );
      codeBlocks.forEach((block, index) => {
        gsap.fromTo(
          block,
          { opacity: 0, x: 28, scale: 0.98 },
          {
            opacity: 1,
            x: 0,
            scale: 1,
            duration: 0.95,
            ease: "power2.out",
            delay: index * 0.1,
            scrollTrigger: {
              trigger: block,
              start: "top 88%",
              toggleActions: "play none none reverse",
            },
          },
        );
      });

      const buildSubsections = root.querySelectorAll(
        `.${styles.aiBuildSubsection}`,
      );
      buildSubsections.forEach((subsection, index) => {
        gsap.fromTo(
          subsection,
          { opacity: 0, y: 28 },
          {
            opacity: 1,
            y: 0,
            duration: 0.9,
            ease: "power2.out",
            delay: index * 0.1,
            scrollTrigger: {
              trigger: subsection,
              start: "top 86%",
              toggleActions: "play none none reverse",
            },
          },
        );
      });

      const hookConnectors = root.querySelectorAll(
        `.${styles.devHookPipelineConnector}`,
      );
      hookConnectors.forEach((connector, index) => {
        gsap.fromTo(
          connector,
          { opacity: 0, scale: 0.9 },
          {
            opacity: 1,
            scale: 1,
            duration: 0.5,
            ease: "power2.out",
            delay: index * 0.06,
            scrollTrigger: {
              trigger: connector,
              start: "top 90%",
              toggleActions: "play none none reverse",
            },
          },
        );
      });
    }, contentRef);

    return () => {
      context.revert();
    };
  }, []);
 
  return (
    <Layout
      title="Agent Kernel for AI Engineers"
      description="Learn how Agent Kernel provides production-ready infrastructure for AI engineers building sophisticated AI agent systems."
    >
      <HeroAnimation
        badge="AI Engineers"
        title="Run Advanced Agent Systems on a Unified Runtime"
        subtitle="Bring your existing agentic code and operate it with production discipline. Agent Kernel unifies execution, memory, hooks, observability, integrations, and multi-cloud deployment so AI engineering teams can ship compliant, scalable systems faster."
      />
      <section ref={contentRef} className={styles.developerContent}>
        <StepTimeline levelId="03" contentRef={contentRef} />
        {/* Step 01 — AI Engineer Analogy */}
        <div
          className={`${styles.developerAnalogy} ${styles.developerBlock}`}
          data-step="ai-01"
        >
          <p className={styles.devStepLabel}>AI Engineer Analogy</p>
          <h2 className={styles.devTitle}>
            Bring your already existing agentic AI code onto a unified
            Operating System and Deployment Infrastructure for your AI
            Agents while making it enterprise ready and compliant.
          </h2>
          <div className={styles.devDescription}>
            <p className={styles.devIntro}>
              Agent Kernel is a unified, capable runtime for AI agents.
              Its pluggable architecture lets you attach capabilities to
              your agents effortlessly. A comprehensive list of pre-built
              connectors smooths the agent-building process—enabling a
              capability is a matter of setting configuration. All out of
              the box.
            </p>
            <p className={styles.devIntro}>
              Agent Kernel takes care of how agents run, scale from single
              execution to thousands of agent invocations in parallel, and
              interact with the real world.
            </p>
          </div>
        </div>

        {/* Architecture flow — 9 stacked layers */}
        <div
          className={`${styles.architectureWrapper} ${styles.developerBlock}`}
          data-step="ai-02"
        >
          <div className={styles.architectureStack}>
            {AI_ENGINEER_ARCH_LAYERS.map((layer, i, arr) => (
              <div
                key={layer.label}
                className={styles.architectureLayerGroup}
              >
                <div className={styles.layerNumberWrapper}>
                  <div className={styles.layerNumberCircle}>
                    {layer.num}
                  </div>
                  {i < arr.length - 1 && (
                    <div className={styles.layerConnector} />
                  )}
                </div>
                <div className={styles.layerContentWrapper}>
                  <div className={styles.layerContentBox}>
                    <h3 className={styles.layerLabel}>{layer.label}</h3>
                    <p className={styles.layerSub}>
                      {layer.items.map((item, idx) => (
                        <React.Fragment key={item}>
                          {idx > 0 && (
                            <span
                              className={styles.layerSubSep}
                              aria-hidden="true"
                            >
                              ●
                            </span>
                          )}
                          {item}
                        </React.Fragment>
                      ))}
                    </p>
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>

        {/* Step 02 — What Makes Agent Kernel Stand Out */}
        <div
          className={`${styles.akStandOutSection} ${styles.developerBlock}`}
          data-step="ai-03"
        >
          <p className={styles.devStepLabel}>Compare alternatives</p>
          <h2 className={styles.devTitle}>
            What Makes Agent Kernel Stand Out
          </h2>

          <div className={styles.akComparePanel}>
            <p className={styles.akCompareScrollHint} aria-hidden="true">
              Scroll horizontally to compare all columns
            </p>

            <div className={styles.akCompareTableWrap}>
              <table className={styles.akCompareTable}>
                <colgroup>
                  <col className={styles.akCompareColFeature} />
                  <col className={styles.akCompareColData} />
                  <col className={styles.akCompareColData} />
                  <col className={styles.akCompareColData} />
                </colgroup>
                <thead>
                  <tr>
                    <th
                      scope="col"
                      className={styles.akCompareFeatureCol}
                    />
                    <th
                      scope="col"
                      className={`${styles.akCompareHeadCell} ${styles.akCompareDataCol}`}
                    >
                      <span className={styles.akCompareHeadLong}>
                        {AI_ENGINEER_COMPARE_COLUMNS.cloud}
                      </span>
                      <span className={styles.akCompareHeadShort}>
                        {AI_ENGINEER_COMPARE_COLUMNS.cloudShort}
                      </span>
                    </th>
                    <th
                      scope="col"
                      className={`${styles.akCompareHeadCell} ${styles.akCompareDataCol}`}
                    >
                      <span className={styles.akCompareHeadLong}>
                        {AI_ENGINEER_COMPARE_COLUMNS.frameworks}
                      </span>
                      <span className={styles.akCompareHeadShort}>
                        {AI_ENGINEER_COMPARE_COLUMNS.frameworksShort}
                      </span>
                    </th>
                    <th
                      scope="col"
                      className={`${styles.akCompareHeadCell} ${styles.akCompareDataCol} ${styles.akCompareHeadCellHighlight}`}
                    >
                      {AI_ENGINEER_COMPARE_COLUMNS.agentKernel}
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {AI_ENGINEER_COMPARISON_ROWS.map((row, i) => (
                    <tr
                      key={row.feature}
                      className={
                        i % 2 === 1 ? styles.akCompareRowAlt : undefined
                      }
                    >
                      <th
                        scope="row"
                        className={styles.akCompareFeatureCell}
                      >
                        <span className={styles.akCompareFeatureText}>
                          {row.feature}
                        </span>
                        {row.featureHint ? (
                          <span className={styles.akCompareFeatureHint}>
                            {row.featureHint}
                          </span>
                        ) : null}
                      </th>
                      <td
                        className={`${styles.akCompareDataCell} ${styles.akCompareDataCol}`}
                      >
                        <AkCompareCellContent cell={row.cloud} />
                      </td>
                      <td
                        className={`${styles.akCompareDataCell} ${styles.akCompareDataCol}`}
                      >
                        <AkCompareCellContent cell={row.frameworks} />
                      </td>
                      <td
                        className={`${styles.akCompareDataCell} ${styles.akCompareDataCol} ${styles.akCompareDataCellHighlight}`}
                      >
                        <AkCompareCellContent cell={row.agentKernel} />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            <div className={styles.akCompareMobileList}>
              {AI_ENGINEER_COMPARISON_ROWS.map((row) => (
                <article
                  key={row.feature}
                  className={styles.akCompareMobileCard}
                >
                  <h3 className={styles.akCompareMobileFeature}>
                    {row.feature}
                    {row.featureHint ? (
                      <span className={styles.akCompareFeatureHint}>
                        {row.featureHint}
                      </span>
                    ) : null}
                  </h3>
                  <div className={styles.akCompareMobileRows}>
                    <div className={styles.akCompareMobileRow}>
                      <span className={styles.akCompareMobileLabel}>
                        {AI_ENGINEER_COMPARE_COLUMNS.cloudShort}
                      </span>
                      <AkCompareCellContent cell={row.cloud} />
                    </div>
                    <div className={styles.akCompareMobileRow}>
                      <span className={styles.akCompareMobileLabel}>
                        {AI_ENGINEER_COMPARE_COLUMNS.frameworksShort}
                      </span>
                      <AkCompareCellContent cell={row.frameworks} />
                    </div>
                    <div
                      className={`${styles.akCompareMobileRow} ${styles.akCompareMobileRowHighlight}`}
                    >
                      <span className={styles.akCompareMobileLabel}>
                        {AI_ENGINEER_COMPARE_COLUMNS.agentKernel}
                      </span>
                      <AkCompareCellContent cell={row.agentKernel} />
                    </div>
                  </div>
                </article>
              ))}
            </div>

            <p className={styles.akCompareFooter}>
              Bedrock / Foundry give you <strong>runtime</strong> but take
              your <strong>freedom</strong>. LangGraph gives you{" "}
              <strong>freedom</strong> but no <strong>runtime</strong>.
              Agent Kernel gives you <strong>both</strong>.
            </p>
          </div>
        </div>

        {/* Step 03 — Available Features */}
        <div className={styles.devFeatureSection} data-step="ai-04">
          <p className={styles.devFeatureLabel}>
            All Enterprise Features Available Free And Open-Source
          </p>
          <h2 className={styles.devFeatureTitle}>
            Focus on Agent Logic. We Handle the Rest.
          </h2>

          <div className={styles.devFeatureGroups}>
            {DEV_FEATURE_GROUPS.map((group) => (
              <div key={group.title} className={styles.devFeatureGroup}>
                <h3 className={styles.devFeatureGroupTitle}>
                  {group.title}
                </h3>
                <div
                  className={`${styles.devFeaturesGrid} ${
                    group.cols === 4
                      ? styles.devFeaturesGrid4
                      : styles.devFeaturesGrid3
                  }`}
                >
                  {group.features.map((feature) => {
                    const IconComponent = feature.icon;
                    return (
                      <div
                        key={feature.title}
                        className={styles.devFeatureCard}
                      >
                        <div className={styles.devFeatureCardHeader}>
                          <div className={styles.devFeatureIconWrap}>
                            <IconComponent
                              className={styles.devFeatureIcon}
                              aria-hidden
                            />
                          </div>
                          <h4 className={styles.devFeatureCardTitle}>
                            {feature.title}
                          </h4>
                        </div>
                        <p className={styles.devFeatureCardBody}>
                          {feature.body}
                        </p>
                      </div>
                    );
                  })}
                </div>
              </div>
            ))}
          </div>
        </div>

        {/* Step 04 — Framework Selection */}
        <div
          className={`${styles.devFrameworkSection} ${styles.developerBlock}`}
          data-step="ai-05"
        >
          <p className={styles.devFrameworkLabel}>
            No lock-in. Your choice
          </p>
          <h2 className={styles.devFrameworkTitle}>
            Use The Framework You Prefer
          </h2>

          <div className={styles.devFrameworkContainer}>
            {/* Left Column - Body & Buttons */}
            <div className={styles.devFrameworkButtonsCol}>
              <p className={styles.devFrameworkBody}>
                Choose a supported framework that fits your team, while
                Agent Kernel gives you a consistent production-ready layer
                for deployment, APIs, sessions, and integrations.
              </p>

              <div className={styles.devFrameworkButtonsGroup}>
                {[
                  { id: "openai", label: "OpenAI Agents" },
                  { id: "crewai", label: "CrewAI" },
                  { id: "langgraph", label: "LangGraph" },
                  { id: "adk", label: "Google ADK" },
                ].map((fw) => (
                  <button
                    key={fw.id}
                    onClick={() => setSelectedFramework(fw.id)}
                    className={`${styles.devFrameworkButton} ${
                      selectedFramework === fw.id
                        ? styles.devFrameworkButtonActive
                        : ""
                    }`}
                  >
                    {fw.label}
                  </button>
                ))}
              </div>
            </div>

            {/* Right Column - Code Display */}
            <div className={styles.devFrameworkCodeCol}>
              {selectedFramework === "openai" && (
                <div className={styles.devFrameworkCodeBlock}>
                  <div className={styles.devFrameworkCodeHeader}>
                    <p className={styles.devFrameworkCodeLabel}>
                      Installation:
                    </p>
                    <button
                      onClick={() =>
                        copyToClipboard(
                          "pip install agentkernel[openai]",
                          "openai-install",
                        )
                      }
                      className={styles.devFrameworkCopyBtn}
                      title="Copy code"
                    >
                      {copiedCode === "openai-install"
                        ? "✓ Copied"
                        : "Copy"}
                    </button>
                  </div>
                  <pre className={styles.devFrameworkCodePre}>
                    <code>pip install agentkernel[openai]</code>
                  </pre>
                  <div className={styles.devFrameworkCodeHeader}>
                    <p className={styles.devFrameworkCodeLabel}>
                      Basic Usage:
                    </p>
                    <button
                      onClick={() =>
                        copyToClipboard(
                          `from agents import Agent as OpenAIAgent
from agentkernel.cli import CLI
from agentkernel.openai import OpenAIModule

agent = OpenAIAgent(
name="assistant",
instructions="You are a helpful assistant.",
)

OpenAIModule([agent])

if __name__ == "__main__":
CLI.main()`,
                          "openai-usage",
                        )
                      }
                      className={styles.devFrameworkCopyBtn}
                      title="Copy code"
                    >
                      {copiedCode === "openai-usage"
                        ? "✓ Copied"
                        : "Copy"}
                    </button>
                  </div>
                  <pre className={styles.devFrameworkCodePre}>
                    <code>{`from agents import Agent as OpenAIAgent
from agentkernel.cli import CLI
from agentkernel.openai import OpenAIModule

agent = OpenAIAgent(
name="assistant",
instructions="You are a helpful assistant.",
)

OpenAIModule([agent])

if __name__ == "__main__":
CLI.main()`}</code>
                  </pre>
                  <Link
                    to="/docs/frameworks/openai"
                    className={styles.devFrameworkDocLink}
                  >
                    View Full Documentation →
                  </Link>
                </div>
              )}

              {selectedFramework === "crewai" && (
                <div className={styles.devFrameworkCodeBlock}>
                  <div className={styles.devFrameworkCodeHeader}>
                    <p className={styles.devFrameworkCodeLabel}>
                      Installation:
                    </p>
                    <button
                      onClick={() =>
                        copyToClipboard(
                          "pip install agentkernel[crewai]",
                          "crewai-install",
                        )
                      }
                      className={styles.devFrameworkCopyBtn}
                      title="Copy code"
                    >
                      {copiedCode === "crewai-install"
                        ? "✓ Copied"
                        : "Copy"}
                    </button>
                  </div>
                  <pre className={styles.devFrameworkCodePre}>
                    <code>pip install agentkernel[crewai]</code>
                  </pre>
                  <div className={styles.devFrameworkCodeHeader}>
                    <p className={styles.devFrameworkCodeLabel}>
                      Basic Usage:
                    </p>
                    <button
                      onClick={() =>
                        copyToClipboard(
                          `from crewai import Agent as CrewAgent
from agentkernel.cli import CLI
from agentkernel.crewai import CrewAIModule

agent = CrewAgent(
role="assistant",
goal="Help users with their questions",
backstory="You are a helpful AI assistant",
verbose=False,
)

CrewAIModule([agent])

if __name__ == "__main__":
CLI.main()`,
                          "crewai-usage",
                        )
                      }
                      className={styles.devFrameworkCopyBtn}
                      title="Copy code"
                    >
                      {copiedCode === "crewai-usage"
                        ? "✓ Copied"
                        : "Copy"}
                    </button>
                  </div>
                  <pre className={styles.devFrameworkCodePre}>
                    <code>{`from crewai import Agent as CrewAgent
from agentkernel.cli import CLI
from agentkernel.crewai import CrewAIModule

agent = CrewAgent(
role="assistant",
goal="Help users with their questions",
backstory="You are a helpful AI assistant",
verbose=False,
)

CrewAIModule([agent])

if __name__ == "__main__":
CLI.main()`}</code>
                  </pre>
                  <Link
                    to="/docs/frameworks/crewai"
                    className={styles.devFrameworkDocLink}
                  >
                    View Full Documentation →
                  </Link>
                </div>
              )}

              {selectedFramework === "langgraph" && (
                <div className={styles.devFrameworkCodeBlock}>
                  <div className={styles.devFrameworkCodeHeader}>
                    <p className={styles.devFrameworkCodeLabel}>
                      Installation:
                    </p>
                    <button
                      onClick={() =>
                        copyToClipboard(
                          "pip install agentkernel[langgraph]",
                          "langgraph-install",
                        )
                      }
                      className={styles.devFrameworkCopyBtn}
                      title="Copy code"
                    >
                      {copiedCode === "langgraph-install"
                        ? "✓ Copied"
                        : "Copy"}
                    </button>
                  </div>
                  <pre className={styles.devFrameworkCodePre}>
                    <code>pip install agentkernel[langgraph]</code>
                  </pre>
                  <div className={styles.devFrameworkCodeHeader}>
                    <p className={styles.devFrameworkCodeLabel}>
                      Basic Usage:
                    </p>
                    <button
                      onClick={() =>
                        copyToClipboard(
                          `from typing import TypedDict
from langgraph.graph import StateGraph, END
from agentkernel.cli import CLI
from agentkernel.langgraph import LangGraphModule

class State(TypedDict):
messages: list

def agent_node(state: State):
return {"messages": state["messages"] + ["response"]}

workflow = StateGraph(State)
workflow.add_node("agent", agent_node)
workflow.set_entry_point("agent")
workflow.add_edge("agent", END)

graph = workflow.compile()
graph.name = "assistant"

LangGraphModule([graph])

if __name__ == "__main__":
CLI.main()`,
                          "langgraph-usage",
                        )
                      }
                      className={styles.devFrameworkCopyBtn}
                      title="Copy code"
                    >
                      {copiedCode === "langgraph-usage"
                        ? "✓ Copied"
                        : "Copy"}
                    </button>
                  </div>
                  <pre className={styles.devFrameworkCodePre}>
                    <code>{`from typing import TypedDict
from langgraph.graph import StateGraph, END
from agentkernel.cli import CLI
from agentkernel.langgraph import LangGraphModule

class State(TypedDict):
messages: list

def agent_node(state: State):
return {"messages": state["messages"] + ["response"]}

workflow = StateGraph(State)
workflow.add_node("agent", agent_node)
workflow.set_entry_point("agent")
workflow.add_edge("agent", END)

graph = workflow.compile()
graph.name = "assistant"

LangGraphModule([graph])

if __name__ == "__main__":
CLI.main()`}</code>
                  </pre>
                  <Link
                    to="/docs/frameworks/langgraph"
                    className={styles.devFrameworkDocLink}
                  >
                    View Full Documentation →
                  </Link>
                </div>
              )}

              {selectedFramework === "adk" && (
                <div className={styles.devFrameworkCodeBlock}>
                  <div className={styles.devFrameworkCodeHeader}>
                    <p className={styles.devFrameworkCodeLabel}>
                      Installation:
                    </p>
                    <button
                      onClick={() =>
                        copyToClipboard(
                          "pip install agentkernel[adk]",
                          "adk-install",
                        )
                      }
                      className={styles.devFrameworkCopyBtn}
                      title="Copy code"
                    >
                      {copiedCode === "adk-install" ? "✓ Copied" : "Copy"}
                    </button>
                  </div>
                  <pre className={styles.devFrameworkCodePre}>
                    <code>pip install agentkernel[adk]</code>
                  </pre>
                  <div className={styles.devFrameworkCodeHeader}>
                    <p className={styles.devFrameworkCodeLabel}>
                      Basic Usage:
                    </p>
                    <button
                      onClick={() =>
                        copyToClipboard(
                          `from adk import Agent as ADKAgent
from agentkernel.cli import CLI
from agentkernel.adk import ADKModule

agent = ADKAgent(
name="assistant",
model="gemini-2.0-flash-exp",
instructions="You are a helpful AI assistant",
)

ADKModule([agent])

if __name__ == "__main__":
CLI.main()`,
                          "adk-usage",
                        )
                      }
                      className={styles.devFrameworkCopyBtn}
                      title="Copy code"
                    >
                      {copiedCode === "adk-usage" ? "✓ Copied" : "Copy"}
                    </button>
                  </div>
                  <pre className={styles.devFrameworkCodePre}>
                    <code>{`from adk import Agent as ADKAgent
from agentkernel.cli import CLI
from agentkernel.adk import ADKModule

agent = ADKAgent(
name="assistant",
model="gemini-2.0-flash-exp",
instructions="You are a helpful AI assistant",
)

ADKModule([agent])

if __name__ == "__main__":
CLI.main()`}</code>
                  </pre>
                  <Link
                    to="/docs/frameworks/google-adk"
                    className={styles.devFrameworkDocLink}
                  >
                    View Full Documentation →
                  </Link>
                </div>
              )}
            </div>
          </div>
        </div>

        {/* Step 05 — Production-ready compliant agents */}
        <div
          className={`${styles.aiEngineerBuildSection} ${styles.developerBlock}`}
          data-step="ai-06"
        >
          <p className={styles.devStepLabel}>Build with confidence</p>
          <h2 className={styles.devTitle}>
            How Agent Kernel Helps You Build Production-Ready Compliant AI
            Agents
          </h2>

          <article className={styles.aiBuildSubsection}>
            <h3 className={styles.aiBuildSubTitle}>Building AI Agents</h3>
            <p className={styles.aiBuildSubBody}>
              Designing a compliant multi-agent architecture carries
              multiple components.
            </p>
            <BuildingAgentsFlowDiagram />
          </article>

          <article className={styles.aiBuildSubsection}>
            <h3 className={styles.aiBuildSubTitle}>Running AI Agents</h3>
            <p className={styles.aiBuildSubBody}>
              Running a production-grade AI agent requires considering
              several design aspects and information flows.
            </p>
            <RunningAgentsFlowDiagram />
          </article>

          <article className={styles.aiBuildSubsection}>
            <h3 className={styles.aiBuildSubTitle}>
              How Agent Kernel Sit In
            </h3>
            <p className={styles.aiBuildSubBody}>
              Agent Kernel handles everything except the actual agent
              logic (number of agents, their capabilities and their
              prompts) while providing a deterministic test framework as
              well.
            </p>
            <AgentKernelSitsInFlowDiagram />
          </article>
        </div>

        {/* Step 06 — How Agent Kernel Fits In */}
        <div
          className={`${styles.devArchitectureSection} ${styles.developerBlock}`}
          data-step="ai-07"
        >
          <p className={styles.devStepLabel}>The complete picture</p>
          <h2 className={styles.devTitle}>How Agent Kernel Fits In</h2>

          <p className={styles.devFrameworkBody}>
            You write your AI agent’s logic. Agent Kernel handles
            everything else: the infrastructure, the cloud deployment,
            memory, knowledge bases, hooks, observability & traceability,
            LLM cost tracking, the integrations so your agent is live and
            talking to real users in days.
          </p>

          <div className={styles.devArchitectureWrapper}>
            <AgentKernelArchDiagram />
          </div>
        </div>

        {/* Step 07 - Why Agent Kernel is a Powerful Operating System */}
        <div
          className={`${styles.devFeatureSection} ${styles.developerBlock}`}
          data-step="ai-08"
        >
          <p className={styles.devStepLabel}>Operating system depth</p>
          <h2 className={styles.devTitle}>
            Why Agent Kernel is a Powerful Operating System
          </h2>

          <div className={styles.devFeatureGroups}>
            <div className={styles.devFeatureGroup}>
              <h3 className={styles.devFeatureGroupTitle}>
                Three-Layer Memory
              </h3>
              <p className={styles.devFeatureGroupHeadline}>
                Three Memory Layers, Zero Context Chaos
              </p>
              <p className={styles.devFeatureGroupIntro}>
                Keep conversations coherent, enrich each request, and
                carry useful session data forward without bloating the
                model context window.
              </p>

              <div
                className={`${styles.devFeaturesGrid} ${styles.devFeaturesGrid3}`}
              >
                {AI_ENGINEER_MEMORY_LAYERS.map((layer) => {
                  const IconComponent = layer.icon;
                  return (
                    <div
                      key={layer.title}
                      className={styles.devFeatureCard}
                    >
                      <div className={styles.devFeatureCardHeader}>
                        <div className={styles.devFeatureIconWrap}>
                          <IconComponent
                            className={styles.devFeatureIcon}
                            aria-hidden
                          />
                        </div>
                        <h4 className={styles.devFeatureCardTitle}>
                          {layer.title}
                        </h4>
                      </div>
                      <ul className={styles.devFeatureCardBodyList}>
                        {layer.bullets.map((bullet) => (
                          <li key={bullet}>{bullet}</li>
                        ))}
                      </ul>
                    </div>
                  );
                })}
              </div>
            </div>

            <div className={styles.devFeatureGroup}>
              <h3 className={styles.devFeatureGroupTitle}>
                Execution Hook Pipeline
              </h3>
              <p className={styles.devFeatureGroupHeadline}>
                Control Every Request Without Rewriting Agent Logic
              </p>
              <p className={styles.devFeatureGroupIntro}>
                Use hooks before and after agent execution to enforce
                safety, enrich inputs, and polish outputs.
              </p>

              <p
                className={styles.devHookPipelineScrollHint}
                aria-hidden="true"
              >
                Scroll horizontally to see the full pipeline
              </p>

              <div className={styles.devHookPipelineScroll}>
                <div className={styles.devHookPipeline}>
                  {AI_ENGINEER_HOOK_PIPELINE.map((step, index, arr) => {
                    const IconComponent = step.icon;
                    return (
                      <React.Fragment key={step.title}>
                        <div
                          className={`${styles.devFeatureCard} ${
                            step.highlight
                              ? styles.devFeatureCardHighlight
                              : ""
                          }`}
                        >
                          <div className={styles.devFeatureCardBadgeSlot}>
                            {"badge" in step && step.badge ? (
                              <span
                                className={
                                  styles.devFeatureHighlightBadge
                                }
                              >
                                {step.badge}
                              </span>
                            ) : null}
                          </div>
                          <div className={styles.devFeatureCardHeader}>
                            <div className={styles.devFeatureIconWrap}>
                              <IconComponent
                                className={styles.devFeatureIcon}
                                aria-hidden
                              />
                            </div>
                            <h4 className={styles.devFeatureCardTitle}>
                              {step.title}
                            </h4>
                          </div>
                          <ul className={styles.devFeatureCardBodyList}>
                            {step.bullets.map((bullet) => (
                              <li key={bullet}>{bullet}</li>
                            ))}
                          </ul>
                        </div>
                        {index < arr.length - 1 ? (
                          <div
                            className={styles.devHookPipelineConnector}
                            aria-hidden="true"
                          >
                            <span
                              className={styles.devHookPipelineArrowH}
                            >
                              →
                            </span>
                            <span
                              className={styles.devHookPipelineArrowV}
                            >
                              ↓
                            </span>
                          </div>
                        ) : null}
                      </React.Fragment>
                    );
                  })}
                </div>
              </div>
            </div>
          </div>
        </div>
      </section>
    </Layout>
  );
}
