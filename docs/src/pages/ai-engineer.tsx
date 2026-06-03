import React, { useEffect, useRef, useState, useCallback } from "react";
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
import FrameworkSelector from "../components/FrameworkSelector";
import heroStyles from "../components/HeroAnimation/styles.module.css";
import { FaGithub } from "react-icons/fa";

export default function AIEngineerPage() {
  const contentRef = useRef<HTMLDivElement>(null);
  const [activeTab, setActiveTab] = useState<"building" | "running" | "kernel">("building");
  const [displayedTab, setDisplayedTab] = useState<"building" | "running" | "kernel">("building");
  const arrowRef = useRef<HTMLDivElement>(null);
  const panelRef = useRef<HTMLDivElement>(null);
  const tabRefs = useRef<(HTMLButtonElement | null)[]>([]);
  const isAnimating = useRef(false);
  

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

    const textClass =
      cell.status === "positive"
        ? styles.akCompareTextPos
        : styles.akCompareTextNeg;

    return (
      <span className={styles.akCompareCellValue}>
        <Icon className={iconClass} aria-hidden />
        {cell.text ? <span className={textClass}>{cell.text}</span> : null}
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
          body: "Easy interfacing your agents on your laptop via Agent Kernel's command line interface.",
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

  const TABS = [
    {
      id: "building" as const,
      title: "Building AI Agents",
      body: "Designing a compliant multi-agent architecture carries multiple components.",
      Icon: MdSmartToy,
      Diagram: BuildingAgentsFlowDiagram,
    },
    {
      id: "running" as const,
      title: "Running AI Agents",
      body: "Running a production-grade AI agent requires considering several design aspects and information flows.",
      Icon: MdBolt,
      Diagram: RunningAgentsFlowDiagram,
    },
    {
      id: "kernel" as const,
      title: "How Agent Kernel Sit In",
      body: "Agent Kernel handles everything except the actual agent logic (number of agents, their capabilities and their prompts) while providing a deterministic test framework as well.",
      Icon: MdAutoAwesome,
      Diagram: AgentKernelSitsInFlowDiagram,
    },
  ] as const;

  const moveArrowTo = useCallback((tabIndex: number, animate = true) => {
    const tab = tabRefs.current[tabIndex];
    const arrow = arrowRef.current;
    const sectionEl = document.querySelector('[data-step="ai-06"]') as HTMLElement | null;
    if (!tab || !arrow || !sectionEl) return;
    const tabRect = tab.getBoundingClientRect();
    const containerRect = sectionEl.getBoundingClientRect();
    const targetX = tabRect.left - containerRect.left + tabRect.width / 2 - arrow.offsetWidth / 2;
    if (animate) {
      gsap.to(arrow, { x: targetX, duration: 0.45, ease: "power3.out" });
    } else {
      gsap.set(arrow, { x: targetX });
    }
  }, []);

  const handleTabChange = useCallback((tabId: "building" | "running" | "kernel", tabIndex: number) => {
    if (tabId === activeTab || isAnimating.current) return;
    isAnimating.current = true;
    setActiveTab(tabId);
    moveArrowTo(tabIndex, true);
    const panel = panelRef.current;
    if (!panel) { setDisplayedTab(tabId); isAnimating.current = false; return; }
    gsap.to(panel, {
      opacity: 0, y: 12, duration: 0.2, ease: "power2.in",
      onComplete: () => {
        setDisplayedTab(tabId);
        gsap.fromTo(panel, { opacity: 0, y: -12 }, {
          opacity: 1, y: 0, duration: 0.35, ease: "power3.out",
          onComplete: () => { isAnimating.current = false; },
        });
      },
    });
  }, [activeTab, moveArrowTo]);

  useEffect(() => {
    const raf = requestAnimationFrame(() => moveArrowTo(0, false));
    return () => cancelAnimationFrame(raf);
  }, [moveArrowTo]);

  useEffect(() => {
    gsap.registerPlugin(ScrollTrigger);
    if (!contentRef.current) return;

    const context = gsap.context(() => {
      const root = contentRef.current!;

      // ─── Utility: fade-up a single element ───────────────────────────────
      function fadeUp(
        el: Element,
        opts: { delay?: number; duration?: number; y?: number; start?: string } = {}
      ) {
        const { delay = 0, duration = 0.85, y = 28, start = "top 88%" } = opts;
        gsap.fromTo(
          el,
          { opacity: 0, y },
          {
            opacity: 1,
            y: 0,
            duration,
            delay,
            ease: "power2.out",
            scrollTrigger: {
              trigger: el,
              start,
              toggleActions: "play none none reverse",
            },
          }
        );
      }

      // ─── Step 01: Analogy ─────────────────────────────────────────────────
      const step01 = root.querySelector('[data-step="ai-01"]');
      if (step01) fadeUp(step01, { y: 36, duration: 1 });

      // ─── Step 02: Architecture layers (slide from left, one by one) ───────
      root
        .querySelectorAll(`[data-step="ai-02"] .${styles.aiEngineeringLayerGroup}`)
        .forEach((layer, i) => {
          gsap.fromTo(
            layer,
            { opacity: 0, x: -50 },
            {
              opacity: 1,
              x: 0,
              duration: 0.9,
              delay: i * 0.1,
              ease: "power2.out",
              scrollTrigger: {
                trigger: layer,
                start: "top 88%",
                toggleActions: "play none none reverse",
              },
            }
          );
        });

      // ─── Step 03: Compare section ─────────────────────────────────────────
      const step03 = root.querySelector('[data-step="ai-03"]');
      if (step03) fadeUp(step03, { y: 36, duration: 1 });

      // ─── Step 04: Feature cards (scoped strictly to ai-04) ───────────────
      root
        .querySelectorAll(`[data-step="ai-04"] .${styles.aiEngineerFeatureCard}`)
        .forEach((card, i) => {
          gsap.fromTo(
            card,
            { opacity: 0, y: 20, scale: 0.97 },
            {
              opacity: 1,
              y: 0,
              scale: 1,
              duration: 0.75,
              delay: (i % 4) * 0.07,
              ease: "power2.out",
              scrollTrigger: {
                trigger: card,
                start: "top 90%",
                toggleActions: "play none none reverse",
              },
            }
          );
        });

      // ─── Step 05: Framework section ──────────────────────────────────────
      const step05 = root.querySelector('[data-step="ai-05"]');
      if (step05) fadeUp(step05, { y: 36, duration: 1 });

      root
        .querySelectorAll(`[data-step="ai-05"] .${styles.devFrameworkButton}`)
        .forEach((btn, i) => {
          gsap.fromTo(
            btn,
            { opacity: 0, y: 16, scale: 0.95 },
            {
              opacity: 1,
              y: 0,
              scale: 1,
              duration: 0.65,
              delay: i * 0.07,
              ease: "power2.out",
              scrollTrigger: {
                trigger: btn,
                start: "top 92%",
                toggleActions: "play none none reverse",
              },
            }
          );
        });

      root
        .querySelectorAll(`[data-step="ai-05"] .${styles.devFrameworkCodeBlock}`)
        .forEach((block, i) => {
          gsap.fromTo(
            block,
            { opacity: 0, x: 28, scale: 0.98 },
            {
              opacity: 1,
              x: 0,
              scale: 1,
              duration: 0.9,
              delay: i * 0.1,
              ease: "power2.out",
              scrollTrigger: {
                trigger: block,
                start: "top 90%",
                toggleActions: "play none none reverse",
              },
            }
          );
        });

      // ─── Step 06: Build subsections ───────────────────────────────────────
      const step06 = root.querySelector('[data-step="ai-06"]');
      if (step06) fadeUp(step06, { y: 36, duration: 1 });

      // ─── Step 07: Architecture section ────────────────────────────────────
      const step07 = root.querySelector('[data-step="ai-07"]');
      if (step07) fadeUp(step07, { y: 36, duration: 1 });

      // ─── Step 08: Memory + hook cards (scoped strictly to ai-08) ─────────
      root
        .querySelectorAll(`[data-step="ai-08"] .${styles.aiEngineerFeatureCard}`)
        .forEach((card, i) => {
          gsap.fromTo(
            card,
            { opacity: 0, y: 20, scale: 0.97 },
            {
              opacity: 1,
              y: 0,
              scale: 1,
              duration: 0.75,
              delay: (i % 3) * 0.08,
              ease: "power2.out",
              scrollTrigger: {
                trigger: card,
                start: "top 90%",
                toggleActions: "play none none reverse",
              },
            }
          );
        });

      root
        .querySelectorAll(`[data-step="ai-08"] .${styles.devHookPipelineConnector}`)
        .forEach((connector, i) => {
          gsap.fromTo(
            connector,
            { opacity: 0, scale: 0.9 },
            {
              opacity: 1,
              scale: 1,
              duration: 0.5,
              delay: i * 0.06,
              ease: "power2.out",
              scrollTrigger: {
                trigger: connector,
                start: "top 92%",
                toggleActions: "play none none reverse",
              },
            }
          );
        });
    }, contentRef);

    return () => context.revert();
  }, []);

  return (
    <Layout
      title="Agent Kernel for AI Engineers"
      description="Learn how Agent Kernel provides production-ready infrastructure for AI engineers building sophisticated AI agent systems."
    >
      {/* <HeroAnimation
        badge="AI Engineers"
        title="Run Advanced Agent Systems on a Unified Runtime"
        subtitle="Bring your existing agentic code and operate it with production discipline. Agent Kernel unifies execution, memory, hooks, observability, integrations, and multi-cloud deployment so AI engineering teams can ship compliant, scalable systems faster."
      /> */}
      <section ref={contentRef} className={styles.aiEngineerSection}>
        <StepTimeline levelId="03" contentRef={contentRef} />
        <div className="container">
          {/* Step 01 — AI Engineer Analogy */}
          <div
            className={`${styles.developerAnalogy} ${styles.aiEngineerBlock}`}
            data-step="ai-01"
          >
            <p className={styles.aiStepLabel}>Step 01 | Analogy</p>
            <h2 className={styles.aiTitle}>
              {/* <span>Unify Your Existing Agents On A Compliant</span>
                {' '}
                <span>Enterprise Runtime</span> */}
              Bring your already existing agentic AI code onto a unified Operating System and Deployment Infrastructure for your AI Agents while making it enterprise ready and compliant.
            </h2>
            <div className={styles.aiDescription}>
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
                  className={styles.aiEngineeringLayerGroup}
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

          {/* Step 03 — What Makes Agent Kernel Stand Out */}
          <div
            className={`${styles.akStandOutSection} ${styles.developerBlock}`}
            data-step="ai-03"
          >
            <p className={styles.aiStepLabel}>Step 02 | Stand Out</p>
            <h2 className={styles.aiTitle}>
              <span>What Makes Agent Kernel Stand Out</span>
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
                      <th scope="col" className={styles.akCompareFeatureCol} />
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
                        <th scope="row" className={styles.akCompareFeatureCell}>
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

          {/* Step 04 — Available Features */}
          <div className={styles.devFeatureSection} data-step="ai-04">
            <p className={styles.aiStepLabel}>
              Step 03 | Features
            </p>
            <h2 className={styles.aiTitle}>
              <span>All Enterprise Features Available</span>
                {' '}<br/>
              <span>Free And Open-Source</span>
            </h2>

            <p className={styles.aiDescription}>
              Focus on Agent Logic. We Handle the Rest.
            </p>    

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
                          className={styles.aiEngineerFeatureCard}
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

          {/* Step 05 — Framework Selection */}
          <div
            className={`${styles.devFrameworkSection} ${styles.developerBlock}`}
            data-step="ai-05"
          >
            <p className={styles.aiStepLabel}>
              Step 04 | Frameworks
            </p>
            <h2 className={styles.aiTitle}>
              <span>Use The Framework You Prefer</span>
            </h2>

            <FrameworkSelector showTitle={false} showDescription={true} accentColor="#26A64D" />
          </div>

          {/* Step 06 — Production-ready compliant agents */}
          <div
            className={`${styles.aiEngineerBuildSection} ${styles.developerBlock}`}
            data-step="ai-06"
          >
            <p className={styles.aiStepLabel}>Step 05 | Build Agents</p>
            <h2 className={styles.aiTitle}>
              <span>How Agent Kernel Helps You Build Production-Ready Compliant AI Agents</span>
            </h2>

            {/* Tab Cards Row */}
            <div className={styles.aiBuildTabsRow}>
              {TABS.map((tab, i) => {
                const TabIcon = tab.Icon;
                return (
                  <button
                    key={tab.id}
                    ref={(el) => { tabRefs.current[i] = el; }}
                    className={`${styles.aiBuildTabCard} ${activeTab === tab.id ? styles.aiBuildTabCardActive : ""}`}
                    onClick={() => handleTabChange(tab.id, i)}
                    type="button"
                  >
                    <span className={styles.aiBuildTabIcon} aria-hidden="true">
                      <TabIcon style={{ width: 18, height: 18 }} />
                    </span>
                    <h3 className={styles.aiBuildTabTitle}>{tab.title}</h3>
                    <p className={styles.aiBuildTabBody}>{tab.body}</p>
                  </button>
                );
              })}
            </div>

            {/* Arrow indicator */}
            <div className={styles.aiBuildArrowTrack}>
              <div ref={arrowRef} className={styles.aiBuildArrow} aria-hidden="true">
                <svg width="22" height="14" viewBox="0 0 22 14" fill="none">
                  <path d="M11 0L22 14H0L11 0Z" fill="#22c55e" />
                </svg>
              </div>
            </div>

            {/* Expanded Panel */}
            {(() => {
              const activeTabData = TABS.find((t) => t.id === displayedTab)!;
              const { Diagram: ActiveDiagram, Icon: PanelIcon } = activeTabData;
              return (
                <div ref={panelRef} className={styles.aiBuildPanel}>
                  <div className={styles.aiBuildPanelHeader}>
                    <span className={styles.aiBuildTabIcon} aria-hidden="true">
                      <PanelIcon style={{ width: 18, height: 18 }} />
                    </span>
                    <h3 className={styles.aiBuildPanelTitle}>{activeTabData.title}</h3>
                  </div>
                  <div className={styles.aiBuildPanelDiagramWrap}>
                    <ActiveDiagram />
                  </div>
                </div>
              );
            })()}
          </div>

          {/* Step 07 — How Agent Kernel Fits In */}
          <div
            className={`${styles.devArchitectureSection} ${styles.developerBlock}`}
            data-step="ai-07"
          >
            <p className={styles.aiStepLabel}>Step 06 | Complete Picture</p>
            <h2 className={styles.aiTitle}>
              <span>How Agent Kernel Fits In</span>
            </h2>

            <p className={styles.aiDescription}>
              You write your AI agent's logic. Agent Kernel handles
              everything else: the infrastructure, the cloud deployment,
              memory, knowledge bases, hooks, observability & traceability,
              LLM cost tracking, the integrations so your agent is live and
              talking to real users in days.
            </p>

            <div className={styles.devArchitectureWrapper}>
              <AgentKernelArchDiagram accentColor="#26A64D" />
            </div>
          </div>

          {/* Step 08 — Why Agent Kernel is a Powerful Operating System */}
          <div
            className={`${styles.devFeatureSection} ${styles.developerBlock}`}
            data-step="ai-08"
          >
            <p className={styles.aiStepLabel}>Step 07 | Operating system depth</p>
            <h2 className={styles.aiTitle}>
              <span>Why Agent Kernel is a Powerful</span>
                {' '}<br/>
              <span>Operating System</span>
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
                        className={styles.aiEngineerFeatureCard}
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
                            className={`${styles.aiEngineerFeatureCard} ${
                              step.highlight
                                ? styles.devFeatureCardHighlight
                                : ""
                            }`}
                          >
                            <div className={styles.devFeatureCardBadgeSlot}>
                              {"badge" in step && step.badge ? (
                                <span
                                  className={styles.devFeatureHighlightBadge}
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
                              <span className={styles.devHookPipelineArrowH}>
                                →
                              </span>
                              <span className={styles.devHookPipelineArrowV}>
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
        </div>
      </section>

      <section className={styles.goDeeperSection}>
        <div className={styles.topGlow} />

        <div className="container">
          <div className={styles.goDeeperInner}>
            <div className={styles.Badge}>
              <span className={styles.badgeStar}>✦</span>
              Continue Exploring
            </div>
            <h2 className={styles.goDeeperTitle}>
              Go deeper with Agent Kernel
            </h2>
            <p className={styles.goDeeperSubtitle}>
              Explore the platform capabilities and real-world workflows behind secure,
              production-ready AI agents.
            </p>

            <div className={styles.goDeeperGrid}>
              <a
                className={styles.goDeeperCard}
                href="/features"
                style={{ '--card-accent': '#26A64D' } as React.CSSProperties}
              >
                <h3 className={styles.goDeeperCardTitle}>Features</h3>
                <p className={styles.goDeeperCardBody}>
                  Explore the core runtime, memory, guardrails, testing,
                  integrations, and deployment capabilities that make Agent
                  Kernel production-ready.
                </p>
                <span className={styles.goDeeperCardCta}>Read More</span>
              </a>

              <a
                className={styles.goDeeperCard}
                href="/use-cases"
                style={{ '--card-accent': '#26A64D' } as React.CSSProperties}
              >
                <h3 className={styles.goDeeperCardTitle}>Use Cases</h3>
                <p className={styles.goDeeperCardBody}>
                  See how teams use Agent Kernel to build assistants,
                  automate workflows, monitor systems, and ship reliable AI
                  agents faster.
                </p>
                <span className={styles.goDeeperCardCta}>Read More</span>
              </a>
            </div>
          </div>
        </div>
      </section>

      <section className={styles.ctaSection}>
        <div className={styles.topGlow} />
        <div className="container">
          <div className={styles.ctaContent}>
            <h2 className={styles.ctaTitle}>
              Ready to Ship Your
              <br />
              First{" "}
              <span className={styles.ctaTitleGradient}>Agent</span>?
            </h2>
            <p className={styles.ctaSubtitle}>
              Free, open-source, Apache 2.0. No licensing costs, no vendor
              lock-in. Join hundreds of developers building production AI agents
              with Agent Kernel.
            </p>
            <div className={styles.ctaButtons}>
              <Link
                className={`button button--primary button--lg ${styles.btnPrimary}`}
                to="/docs"
              >
                <span className={styles.btnIcon}>→</span>
                Get Started Free
              </Link>
              <Link
                className={`button button--secondary button--lg ${styles.btnSecondary}`}
                to="https://github.com/yaalalabs/agent-kernel"
                target="_blank"
                rel="noopener noreferrer"
              >
                <span className={styles.btnIconSecondary}>
                  <FaGithub />
                </span>
                View On GitHub
              </Link>
            </div>

            <div className={styles.ctaImageWrapper}>
              <img
                src="/img/cta-bg.png"
                alt="Agent Kernel"
                className={styles.ctaImage}
              />
            </div>
          </div>
        </div>
      </section>
    </Layout>
  );
}