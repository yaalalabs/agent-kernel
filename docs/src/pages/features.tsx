import React, {
  useId,
  useState,
  useEffect,
  useLayoutEffect,
  useRef,
} from "react";
import Link from "@docusaurus/Link";
import Layout from "@theme/Layout";
import styles from "./features.module.css";
import indexStyles from "./index.module.css";
import {
  MdMemory,
  MdSwapHoriz,
  MdCloud,
  MdSpeed,
  MdSecurity,
  MdVisibility,
  MdCode,
  MdNetworkCheck,
  MdTerminal,
  MdBugReport,
  MdTimer,
  MdSettings,
  MdHealthAndSafety,
  MdCheck,
  MdClose,
  MdMenuBook,
  MdExtension,
  MdHub,
  MdMessage,
  MdCloudUpload,
} from "react-icons/md";
import {
  FaSlack,
  FaWhatsapp,
  FaInstagram,
  FaTelegram,
  FaGithub,
} from "react-icons/fa";
import {
  SiGmail,
  SiGooglegemini,
  SiLangchain,
  SiHuggingface,
} from "react-icons/si";
import { FaFacebookMessenger } from "react-icons/fa6";
import { TbBrandTeams } from "react-icons/tb";
import PlantParticlesBackground from "../components/PlantParticlesBackground";
import AgentKernelRuntimeFlowDiagram from "../components/AgentKernelRuntimeFlowDiagram";
import HeroAnimation from "../components/HeroAnimation";
import gsap from "gsap";
import { ScrollTrigger } from "gsap/dist/ScrollTrigger";

gsap.registerPlugin(ScrollTrigger);

/** Stable fragment ids for in-page navigation (diagram + deep links). */
const FEATURE_ANCHORS = {
  problem: "features-problem",
  core: "features-core",
  frameworks: "features-frameworks",
  testing: "features-testing",
  messaging: "features-messaging",
  protocols: "features-protocols",
  cta: "features-cta",
} as const;

type FeatureAnchorKey = keyof typeof FEATURE_ANCHORS;

const FEATURE_PAGE_MAP: {
  anchor: FeatureAnchorKey;
  number: string;
  title: string;
  hint: string;
}[] = [
    {
      anchor: "problem",
      number: "01",
      title: "The Problem",
      hint: "What Agent Kernel solves",
    },
    {
      anchor: "core",
      number: "02",
      title: "Core Capabilities",
      hint: "Runtime, memory, hooks, and more",
    },
    {
      anchor: "frameworks",
      number: "03",
      title: "Framework Support",
      hint: "One runtime, any framework",
    },
    {
      anchor: "testing",
      number: "04",
      title: "Testing",
      hint: "CLI, pytest, comparison modes",
    },
    {
      anchor: "messaging",
      number: "05",
      title: "Messaging",
      hint: "Slack, WhatsApp, and more",
    },
    {
      anchor: "protocols",
      number: "06",
      title: "Protocol Support",
      hint: "MCP and A2A out of the box",
    },
  ];

function scrollToFeaturesSection(anchor: FeatureAnchorKey) {
  const id = FEATURE_ANCHORS[anchor];
  const el =
    typeof document !== "undefined" ? document.getElementById(id) : null;
  el?.scrollIntoView({ behavior: "smooth", block: "start" });
}

type PlantParticlesBackgroundHandle = React.ElementRef<
  typeof PlantParticlesBackground
>;

/* ─── Why Agent Kernel (hero) ───────────────────────────────────────────── */

function WhyAgentKernel() {
  const labelRef = useRef<HTMLParagraphElement>(null);
  const titleRef = useRef<HTMLHeadingElement>(null);
  const subtitleRef = useRef<HTMLParagraphElement>(null);
  const diagramRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const tl = gsap.timeline();

    gsap.set(
      [
        labelRef.current,
        titleRef.current,
        subtitleRef.current,
        diagramRef.current,
      ],
      {
        opacity: 0,
        y: 30,
      },
    );

    tl.to(labelRef.current, {
      opacity: 1,
      y: 0,
      duration: 0.6,
      ease: "power2.out",
    })
      .to(
        titleRef.current,
        {
          opacity: 1,
          y: 0,
          duration: 0.8,
          ease: "power2.out",
        },
        "-=0.35",
      )
      .to(
        subtitleRef.current,
        {
          opacity: 1,
          y: 0,
          duration: 0.6,
          ease: "power2.out",
        },
        "-=0.45",
      )
      .to(
        diagramRef.current,
        {
          opacity: 1,
          y: 0,
          duration: 0.7,
          ease: "power2.out",
        },
        "-=0.3",
      );
  }, []);

  return (
    <section className={styles.whyHero}>
      <div className="container">
        <div className={styles.whyHeroBlock}>
          <p ref={labelRef} className={styles.sectionLabel}>
            Why Agent Kernel
          </p>
          <h2 ref={titleRef} className={styles.sectionTitle}>
            Everything You Need to Build, Run and Scale AI Agents
          </h2>
          <p ref={subtitleRef} className={styles.sectionSubtitle}>
            From runtime and memory to guardrails, observability, testing, and
            multi-cloud deployment.
          </p>
          <div ref={diagramRef} className={styles.whyHeroDiagram}>
            <AgentKernelRuntimeFlowDiagram />
          </div>
        </div>
      </div>
    </section>
  );
}

/* ─── Page map (diagram) ────────────────────────────────────────────────── */

function FeaturesPageMap({
  plantParticlesBackgroundRef,
}: {
  plantParticlesBackgroundRef: React.RefObject<PlantParticlesBackgroundHandle>;
}) {
  const gradId = useId().replace(/:/g, "");
  const sectionRef = useRef<HTMLDivElement>(null);
  const [visible, setVisible] = useState(false);
  const topRow = FEATURE_PAGE_MAP.slice(0, 3);
  const bottomRow = FEATURE_PAGE_MAP.slice(3);

  useEffect(() => {
    if (
      typeof window !== "undefined" &&
      window.matchMedia("(prefers-reduced-motion: reduce)").matches
    ) {
      setVisible(true);
      return;
    }
    const el = sectionRef.current;
    if (!el) return;
    const shouldAnimateParticles =
      typeof window !== "undefined" &&
      !window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    const triggerScatterOut = () => {
      if (shouldAnimateParticles) {
        plantParticlesBackgroundRef.current?.triggerScatterOut();
      }
    };
    const triggerScatterIn = () => {
      if (shouldAnimateParticles) {
        plantParticlesBackgroundRef.current?.triggerScatterIn();
      }
    };
    const scrollTrigger = ScrollTrigger.create({
      trigger: el,
      start: "top 60%",
      end: "bottom 40%",
      onEnter: () => {
        setVisible(true);
        triggerScatterOut();
      },
      onEnterBack: () => {
        setVisible(true);
        triggerScatterOut();
      },
      onLeave: () => {
        triggerScatterIn();
      },
      onLeaveBack: () => {
        setVisible(false);
        triggerScatterIn();
      },
    });

    return () => scrollTrigger.kill();
  }, []);

  const reducedMotion =
    typeof window !== "undefined" &&
    window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  const COL_X_TOP = [143, 450, 757] as const;
  const COL_X_BOT = [143, 450, 757] as const;

  // Top strip
  const topLines = COL_X_TOP.map((x, i) => ({
    id: `${gradId}T${i}`,
    d: `M ${x} 0 L 450 60`,
    len: Math.round(Math.sqrt(Math.pow(x - 450, 2) + 3600)),
    delay: 0.2 + i * 0.07,
  }));

  // Bottom strip
  const botLines = COL_X_BOT.map((x, i) => ({
    id: `${gradId}B${i}`,
    d: `M 450 0 L ${x} 60`,
    len: Math.round(Math.sqrt(Math.pow(x - 450, 2) + 3600)),
    delay: 0.41 + i * 0.07,
  }));

  const TEAL = "rgba(0,221,255,1)";

  return (
    <div
      ref={sectionRef}
      className={styles.pageMapSection}
      role="region"
      aria-labelledby="features-page-map-heading"
    >
      <div className="container">
        {/* Top border + gradient glow */}
        <div className={styles.topGlow} />

        <div className={styles.sectionHeader}>
          <div className={styles.Badge}>
            <span className={styles.badgeStar}>✦</span>
            Feature Map
          </div>
          <h2 id="features-page-map-heading" className={styles.sectionTitle}>
            Everything Agent Kernel Does
          </h2>
          <p className={styles.sectionSubtitle}>
            Six production-ready capabilities. Explore any area below.
          </p>
        </div>

        <div className={styles.pageMapDiagram}>
          {/* ── Layer 1: top row nodes ── */}
          <div className={styles.pageMapTopRow}>
            {topRow.map((item, i) => (
              <button
                key={item.anchor}
                type="button"
                className={`${styles.pageMapNode} ${visible ? styles.pageMapNodeIn : ""}`}
                style={{ "--node-delay": `${i * 80}ms` } as React.CSSProperties}
                onClick={() => scrollToFeaturesSection(item.anchor)}
              >
                <div className={styles.pageMapNodeHeader}>
                  <span className={styles.pageMapNodeNumber}>{item.number}</span>
                  <span className={styles.pageMapNodeTitle}>{item.title}</span>
                </div>
                <span className={styles.pageMapNodeHint}>{item.hint}</span>
              </button>
            ))}
          </div>

          {/* ── Connector: top nodes → hub ── */}
          <svg
            className={styles.pageMapConnector}
            viewBox="0 0 900 60"
            preserveAspectRatio="none"
            aria-hidden
          >
            <defs>
              {topLines.map((l, i) => (
                <linearGradient
                  key={`grad-${l.id}`}
                  id={`grad-${l.id}`}
                  gradientUnits="userSpaceOnUse"
                  x1={COL_X_TOP[i]}
                  y1="0"
                  x2="450"
                  y2="60"
                >
                  <stop offset="0%" stopColor={TEAL} stopOpacity="0" />
                  <stop offset="50%" stopColor={TEAL} stopOpacity="1" />
                  <stop offset="100%" stopColor={TEAL} stopOpacity="0.3" />
                </linearGradient>
              ))}
            </defs>

            {topLines.map((l, i) => (
              <g
                key={l.id}
                className={visible && !reducedMotion ? styles.lineBreath : undefined}
                style={{
                  opacity: visible ? undefined : 0,
                  "--breath-dur": `${2.2 + i * 0.4}s`,
                  "--breath-delay": `${i * 0.3}s`,
                } as React.CSSProperties}
              >
                <path
                  d={l.d}
                  fill="none"
                  stroke={`url(#grad-${l.id})`}
                  strokeWidth="1.5"
                />
              </g>
            ))}
          </svg>

          {/* ── Hub ── */}
          <div
            className={`${styles.pageMapHub} ${visible ? styles.pageMapHubIn : ""}`}
            style={{ backgroundColor: "#010002" }}
          >
            <video
              src="/video/hero.mp4"
              className={styles.pageMapHubIcon}
              autoPlay
              loop
              muted
              playsInline
            />
          </div>

          {/* ── Connector: hub → bottom nodes ── */}
          <svg
            className={styles.pageMapConnector}
            viewBox="0 0 900 60"
            preserveAspectRatio="none"
            aria-hidden
          >
            <defs>
              {botLines.map((l, i) => (
                <linearGradient
                  key={`grad-${l.id}`}
                  id={`grad-${l.id}`}
                  gradientUnits="userSpaceOnUse"
                  x1="450"
                  y1="0"
                  x2={COL_X_BOT[i]}
                  y2="60"
                >
                  <stop offset="0%" stopColor={TEAL} stopOpacity="0.3" />
                  <stop offset="50%" stopColor={TEAL} stopOpacity="1" />
                  <stop offset="100%" stopColor={TEAL} stopOpacity="0" />
                </linearGradient>
              ))}
            </defs>

            {botLines.map((l, i) => (
              <g
                key={l.id}
                className={visible && !reducedMotion ? styles.lineBreath : undefined}
                style={{
                  opacity: visible ? undefined : 0,
                  "--breath-dur": `${2.2 + i * 0.4}s`,
                  "--breath-delay": `${0.5 + i * 0.3}s`,
                } as React.CSSProperties}
              >
                <path
                  d={l.d}
                  fill="none"
                  stroke={`url(#grad-${l.id})`}
                  strokeWidth="1.5"
                />
              </g>
            ))}
          </svg>

          {/* ── Layer 3: bottom row nodes ── */}
          <div className={styles.pageMapBottomRow}>
            {bottomRow.map((item, i) => (
              <button
                key={item.anchor}
                type="button"
                className={`${styles.pageMapNode} ${visible ? styles.pageMapNodeIn : ""}`}
                style={
                  { "--node-delay": `${300 + i * 80}ms` } as React.CSSProperties
                }
                onClick={() => scrollToFeaturesSection(item.anchor)}
              >
                <div className={styles.pageMapNodeHeader}>
                  <span className={styles.pageMapNodeNumber}>{item.number}</span>
                  <span className={styles.pageMapNodeTitle}>{item.title}</span>
                </div>
                <span className={styles.pageMapNodeHint}>{item.hint}</span>
              </button>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}

/* ─── Problem comparison (orbit-style UI) ─────────────────────────────────── */

function ProblemTable() {
  const sectionRef = useRef<HTMLElement>(null);
  const rows = [
    {
      problem: "Platform engineering",
      without:
        "Build REST APIs, auth, session management, deployment pipelines from scratch",
      with: "All included out of the box",
    },
    {
      problem: "Framework lock-in",
      without: "Rewrite everything if you switch from LangGraph to OpenAI",
      with: "Change 2 import lines — everything else stays",
    },
    {
      problem: "Cloud lock-in",
      without: "AWS-specific code everywhere",
      with: "Same code deploys to AWS, Azure, or on-prem",
    },
    {
      problem: "Memory & state",
      without: "Build your own conversation tracking, caching, and persistence",
      with: "Built-in with multiple backends",
    },
    {
      problem: "Knowledge Bases",
      without:
        "Build your own database connectors. Handle data complexity, separate tools for storage and retrieval",
      with: "Built-in with multiple knowledge sources",
    },
    {
      problem: "Messaging integrations",
      without: "Build custom Slack/WhatsApp bots from scratch",
      with: "Built-in handlers, plug and play",
    },
    {
      problem: "Testing",
      without: "No standard way to test AI agents",
      with: "pytest-integrated test framework",
    },
    {
      problem: "Observability",
      without: "Manual instrumentation",
      with: "LangFuse/OpenLLMetry with one config line",
    },
    {
      problem: "Guardrails & safety",
      without: "Build custom content filters",
      with: "OpenAI and Bedrock guardrails built in",
    },
    {
      problem: "Deployment",
      without: "Write Terraform/CDK yourself",
      with: "Pre-built Terraform modules for AWS & Azure",
    },
  ];

  const [active, setActive] = useState(0);
  const activeRow = rows[active];

  const problemChipIcons = [
    MdHub,
    MdSwapHoriz,
    MdCloud,
    MdMemory,
    MdMenuBook,
    MdMessage,
    MdBugReport,
    MdVisibility,
    MdSecurity,
    MdCloudUpload,
  ] as const;

  const ActiveIcon = problemChipIcons[active];

  useLayoutEffect(() => {
    const section = sectionRef.current;
    if (!section) {
      return;
    }

    const reducedMotion =
      typeof window !== "undefined" &&
      window.matchMedia("(prefers-reduced-motion: reduce)").matches;

    const allHeaders = section.querySelectorAll(`.${styles.sectionHeader}`);
    const header1 = allHeaders[0];
    const header2 = allHeaders[1];
    const topicButtons = Array.from(
      section.querySelectorAll(`.${styles.problemTopicBtn}`),
    );
    const comparePanel = section.querySelector(`.${styles.problemComparePanelOuter}`);

    if (reducedMotion) {
      gsap.set([header1, header2, ...topicButtons, comparePanel], {
        opacity: 1,
        y: 0,
      });
      return;
    }

    gsap.set(header1, {
      opacity: 0,
      y: 24,
    });
    gsap.set(comparePanel, {
      opacity: 0,
      y: 24,
    });
    gsap.set(topicButtons, {
      opacity: 0,
      y: 16,
    });

    const tl1 = gsap.timeline({
      scrollTrigger: {
        trigger: header1,
        start: "top 75%",
        toggleActions: "play none none reverse",
      },
    });

    tl1.to(header1, {
      opacity: 1,
      y: 0,
      duration: 0.6,
      ease: "power2.out",
    })
      .to(
        comparePanel,
        {
          opacity: 1,
          y: 0,
          duration: 0.6,
          ease: "power2.out",
        },
        "-=0.35",
      )
      .to(
        topicButtons,
        {
          opacity: 1,
          y: 0,
          duration: 0.4,
          stagger: 0.03,
          ease: "power2.out",
        },
        "-=0.4",
      );

    return () => {
      tl1.scrollTrigger?.kill();
      tl1.kill();
    };
  }, []);

  useEffect(() => {
    const timer = setTimeout(() => {
      ScrollTrigger.refresh();
    }, 250);
    return () => clearTimeout(timer);
  }, []);

  return (
    <section
      id={FEATURE_ANCHORS.problem}
      className={`${styles.section} ${styles.problemSection} ${styles.pageAnchor}`}
      ref={sectionRef}
    >
      <div className="container">
        <div className={styles.sectionHeader}>
          <p className={styles.sectionLabel}>01 | The Problem</p>
          <h2 className={styles.sectionTitle}>The Problem Agent Kernel Solves</h2>
          <p className={styles.sectionSubtitle}>
            Building production AI agents today involves solving many hard
            problems that have nothing to do with the actual agent intelligence.
          </p>
        </div>
        <div className={styles.problemBlock}>
          <div className={styles.problemComparePanelOuter}>
            <ul
              className={styles.problemTopicGrid}
              role="tablist"
              aria-label="Areas to compare"
            >
              {rows.map((row, i) => {
                const ChipIcon = problemChipIcons[i];
                return (
                  <li key={row.problem} className={styles.problemTopicCell}>
                    <button
                      type="button"
                      role="tab"
                      id={`feature-problem-tab-${i}`}
                      aria-selected={active === i}
                      aria-controls="feature-problem-panel"
                      className={`${styles.problemTopicBtn} ${active === i ? styles.problemTopicBtnActive : ""}`}
                      onClick={() => setActive(i)}
                    >
                      <span
                        className={styles.problemTopicIconWrap}
                        aria-hidden="true"
                      >
                        <ChipIcon className={styles.problemTopicIcon} />
                      </span>
                      <span className={styles.problemTopicLabel}>
                        {row.problem}
                      </span>
                    </button>
                  </li>
                );
              })}
            </ul>
            <div
              id="feature-problem-panel"
              role="tabpanel"
              aria-labelledby={`feature-problem-tab-${active}`}
              className={styles.problemComparePanel}
            >
              <div key={active} className={styles.problemComparePanelInner}>
                <div className={styles.problemComparePanelHeader}>
                  <span
                    className={styles.problemComparePanelIconWrap}
                    aria-hidden="true"
                  >
                    <ActiveIcon className={styles.problemComparePanelIcon} />
                  </span>
                  <div>
                    <h3 className={styles.problemComparePanelTitle}>
                      {activeRow.problem}
                    </h3>
                    <p className={styles.problemComparePanelMeta}>
                      Without vs with Agent Kernel
                    </p>
                  </div>
                </div>
                <div className={styles.problemCompareGrid}>
                  <article
                    className={`${styles.problemCompareSide} ${styles.problemCompareSideNeg}`}
                  >
                    <p className={styles.problemCompareSideLabel}>
                      Without Agent Kernel
                    </p>
                    <p className={styles.problemCompareSideSub}>
                      What you take on today
                    </p>
                    <div
                      className={`${styles.problemCompareBody} ${styles.problemCompareBodyNeg}`}
                    >
                      <span
                        className={styles.problemCompareBodyIcon}
                        aria-hidden="true"
                      >
                        <ActiveIcon />
                      </span>
                      <p className={styles.problemCompareBodyText}>
                        {activeRow.without}
                      </p>
                    </div>
                  </article>
                  <article
                    className={`${styles.problemCompareSide} ${styles.problemCompareSidePos}`}
                  >
                    <p className={styles.problemCompareSideLabel}>
                      With Agent Kernel
                    </p>
                    <p className={styles.problemCompareSideSub}>
                      What the platform covers
                    </p>
                    <div
                      className={`${styles.problemCompareBody} ${styles.problemCompareBodyPos}`}
                    >
                      <span
                        className={styles.problemCompareBodyIcon}
                        aria-hidden="true"
                      >
                        <ActiveIcon />
                      </span>
                      <p className={styles.problemCompareBodyText}>
                        {activeRow.with}
                      </p>
                    </div>
                  </article>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}

/* ─── Core Features ─────────────────────────────────────────────────────── */

function CoreFeatures() {
  const sectionRef = useRef<HTMLElement>(null);

  const features = [
    {
      icon: <MdCode />,
      title: "Six Core Abstractions",
      description:
        "Agent, Runner, Session, Module, Runtime, and Tools, a unified API across all frameworks. Build once, run on any supported framework.",
      highlights: [
        "Unified Python API",
        "Framework adapters for 4 SDKs",
        "Portable tool functions via ToolBuilder",
        "Framework-agnostic hooks",
      ],
      link: "/docs/core-concepts/overview",
    },
    {
      icon: <MdSwapHoriz />,
      title: "Framework-Neutral Runtime",
      description:
        "OpenAI Agents, LangGraph, CrewAI, and Google ADK, run them all simultaneously in one runtime. Switch frameworks by changing 2 import lines.",
      highlights: ["OpenAI Agents SDK", "LangGraph", "CrewAI", "Google ADK"],
      link: "/docs/frameworks/overview",
    },
    {
      icon: <MdSettings />,
      title: "Execution Hooks",
      description:
        "Pre and post-execution hooks give you surgical control over every agent request, for any framework.",
      highlights: [
        "Pre-hooks: guardrails, RAG, auth, validation",
        "Post-hooks: moderation, disclaimers, analytics",
        "Hook chaining and composition",
        "Early termination with custom responses",
      ],
      link: "/docs/integrations/hooks",
    },
    {
      icon: <MdMemory />,
      title: "Smart Memory Management",
      description:
        "Volatile and non-volatile caching with identical APIs but different lifecycles. Swap backends with just environment variables.",
      highlights: [
        "Volatile: request-scoped, auto-clears",
        "Non-volatile: session-persistent",
        "Backends: In-memory, Redis, DynamoDB, Cosmos DB",
        "Clean prompts, reduced token usage",
      ],
      link: "/docs/architecture/memory-management",
    },
    {
      icon: <MdMenuBook />,
      title: "Knowledge Bases",
      description:
        "Built-in retrieval for curated knowledge sources and storage for agent reinforcement learning. Neo4j, Starburst Galaxy, ChromaDB, and custom SQL data sources.",
      highlights: [
        "ChromaDB — vector/semantic search",
        "Neo4j — entity and relationship graphs",
        "Starburst Galaxy — SQL over MongoDB, Sheets, PostgreSQL",
        "semantic_map keeps agent prompts portable",
      ],
      link: "/docs/architecture/knowledge-bases",
    },
    {
      icon: <MdCloud />,
      title: "Multi-Cloud Deployment",
      description:
        "One agent codebase deploys to AWS, and Azure and GCP with full Terraform modules. No vendor lock-in, ever.",
      highlights: [
        "AWS Lambda (Serverless)",
        "AWS ECS/Fargate (Containerized)",
        "Azure Functions (Serverless)",
        "Azure Container Apps (Containerized)",
      ],
      link: "/docs/deployment/overview",
    },
    {
      icon: <MdHealthAndSafety />,
      title: "Fault Tolerance",
      description:
        "Production-grade resilience with multi-AZ deployments, auto-recovery, health monitoring, and rolling deployments.",
      highlights: [
        "Multi-AZ for high availability",
        "Automatic failure recovery",
        "Health monitoring",
        "Zero-downtime deployments",
      ],
      link: "/docs/core-concepts/fault-tolerance",
    },
    {
      icon: <MdVisibility />,
      title: "Observability",
      description:
        "Full visibility into agent execution, LLM calls, and tool invocations. One config line to enable.",
      highlights: [
        "LangFuse integration",
        "OpenLLMetry (OpenTelemetry-based)",
        "Multi-level verbosity",
        "Cost and latency tracking",
      ],
      link: "/docs/advanced/traceability",
    },
    {
      icon: <MdSecurity />,
      title: "Content Safety & Guardrails",
      description:
        "Input and output guardrails that protect users and ensure compliance. Plugs in via execution hooks.",
      highlights: [
        "PII detection and redaction",
        "Jailbreak prevention",
        "Content moderation",
        "Off-topic filtering",
      ],
      link: "/docs/advanced/guardrails",
    },
    {
      icon: <MdNetworkCheck />,
      title: "MCP & A2A Protocols",
      description:
        "Expose agents as MCP tools or enable agent-to-agent communication via A2A protocol.",
      highlights: [
        "MCP Server mode",
        "A2A Server mode",
        "Cross-agent coordination",
        "Protocol-future-proofed",
      ],
      link: "/docs/api/mcp-server",
    },
  ];

  useLayoutEffect(() => {
    const section = sectionRef.current;
    if (!section) return;

    const reducedMotion =
      typeof window !== "undefined" &&
      window.matchMedia("(prefers-reduced-motion: reduce)").matches;

    const header = section.querySelector(`.${styles.sectionHeader}`);
    const cardEls = Array.from(
      section.querySelectorAll(`.${styles.featureGridCell}`),
    ) as HTMLElement[];

    if (!header || !cardEls.length) return;

    if (reducedMotion) {
      gsap.set([header, ...cardEls], { opacity: 1, y: 0, scale: 1 });
      return;
    }

    // Header: fade + slide up
    gsap.set(header, { opacity: 0, y: 24 });
    const headerTween = gsap.to(header, {
      opacity: 1,
      y: 0,
      duration: 0.65,
      ease: "power2.out",
      scrollTrigger: {
        trigger: header,
        start: "top 70%",
        toggleActions: "play none none reverse",
      },
    });

    // Group cards into rows by actual DOM top position (layout-agnostic)
    const rows: HTMLElement[][] = [];
    let currentRowTop = -1;
    let currentRow: HTMLElement[] = [];

    cardEls.forEach((card) => {
      const top = Math.round(card.getBoundingClientRect().top);
      if (Math.abs(top - currentRowTop) > 4) {
        if (currentRow.length) rows.push(currentRow);
        currentRow = [card];
        currentRowTop = top;
      } else {
        currentRow.push(card);
      }
    });
    if (currentRow.length) rows.push(currentRow);

    const rowTweens: gsap.core.Tween[] = [];

    // Animate each row when its first card scrolls into view
    rows.forEach((rowCards) => {
      gsap.set(rowCards, {
        opacity: 0,
        y: 32,
        scale: 0.88,
        transformOrigin: "center bottom",
      });

      const tween = gsap.to(rowCards, {
        opacity: 1,
        y: 0,
        scale: 1,
        duration: 0.52,
        stagger: 0.07,
        ease: "back.out(1.5)",
        scrollTrigger: {
          trigger: rowCards[0],
          start: "top 75%",
          toggleActions: "play none none reverse",
        },
      });
      rowTweens.push(tween);
    });

    return () => {
      headerTween.scrollTrigger?.kill();
      headerTween.kill();
      rowTweens.forEach((t) => {
        t.scrollTrigger?.kill();
        t.kill();
      });
    };
  }, []);

  return (
    <section
      id={FEATURE_ANCHORS.core}
      className={`${styles.section} ${styles.coreFeaturesSection} ${styles.pageAnchor}`}
      ref={sectionRef}
    >
      <div className="container">
        <div className={styles.sectionHeader}>
          <p className={styles.sectionLabel}>02 | Core Capabilities</p>
          <h2 className={styles.sectionTitle}>Core Capabilities</h2>
          <p className={styles.sectionSubtitle}>
            Everything you need to build, run, and scale production AI agents
            without building platform code.
          </p>
        </div>
        <ul className={styles.featuresGrid}>
          {features.map((f, i) => (
            <li key={f.title} className={styles.featureGridCell}>
              <article className={styles.featureCard}>
                <div className={styles.featureCardHeader}>
                  <div className={styles.featureIconWrap} aria-hidden="true">
                    {f.icon}
                  </div>
                  <h3 className={styles.featureTitle}>{f.title}</h3>
                </div>
                <div className={styles.featureCardBody}>
                  <p className={styles.featureDescription}>{f.description}</p>
                  <ul className={styles.featureHighlights}>
                    {f.highlights.map((h) => (
                      <li key={h}>{h}</li>
                    ))}
                  </ul>
                </div>
                {f.link ? (
                  <Link to={f.link} className={styles.featureLink}>
                    Learn More
                  </Link>
                ) : null}
              </article>
            </li>
          ))}
        </ul>
      </div>
    </section>
  );
}

/* ─── Framework Support ─────────────────────────────────────────────────── */

function FrameworkSupport() {
  const sectionRef = useRef<HTMLElement>(null);

  const integrations = [
    {
      key: "openai",
      name: "OpenAI Agents SDK",
      description:
        "Official OpenAI agents framework with full support for tools, handoffs, and streaming.",
      link: "/docs/frameworks/openai",
      logo: (
        <img
          src="/img/integrations/chatgpt.png"
          alt=""
          className={`${styles.frameworkLogoImg} ${styles.frameworkLogoImgInvert}`}
          width={145}
          height={45}
        />
      ),
    },
    {
      key: "langgraph",
      name: "LangGraph",
      description:
        "Graph-based agent orchestration for complex stateful multi-actor applications.",
      link: "/docs/frameworks/langgraph",
      logo: (
        <img
          src="/img/integrations/langgraph.png"
          alt=""
          className={`${styles.frameworkLogoImg} ${styles.frameworkLogoImgInvert}`}
          width={150}
          height={50}
        />
      ),
    },
    {
      key: "google-adk",
      name: "Google ADK",
      description:
        "Google's Agent Development Kit for advanced agent capabilities and Gemini integration.",
      link: "/docs/frameworks/google-adk",
      logo: (
        <img
          src="/img/integrations/googleADK.png"
          alt=""
          className={`${styles.frameworkLogoImg} ${styles.frameworkLogoImgInvert}`}
          width={150}
          height={50}
        />
      ),
    },
    {
      key: "crewai",
      name: "CrewAI",
      description:
        "Role-based multi-agent framework for orchestrating collaborative AI workflows.",
      link: "/docs/frameworks/crewai",
      logo: (
        <img
          src="/img/integrations/crewai.png"
          alt=""
          className={styles.frameworkLogoImg}
          width={168}
          height={58}
        />
      ),
    },
    {
      key: "smolagents",
      name: "Smolagents",
      description:
        "Hugging Face's Smolagents with first-class support for writing your own coding agents.",
      link: "https://huggingface.co/docs/smolagents/index",
      external: true,
      logo: (
        <img
          src="/img/integrations/smolagents.png"
          alt=""
          className={styles.frameworkLogoImg}
          width={150}
          height={50}
        />
      ),
    },
    {
      key: "livekit",
      name: "LiveKit",
      description:
        "LiveKit provides the complete stack for voice-based AI agents.",
      link: "https://docs.livekit.io/",
      external: true,
      logo: (
        <img
          src="/img/integrations/livekit.png"
          alt=""
          className={styles.frameworkLogoImg}
          width={38}
          height={38}
        />
      ),
    },
  ];

  const multiFramework = {
    name: "Multi-Framework",
    description:
      "Run agents from multiple frameworks simultaneously in a single runtime — no glue code required.",
    link: "/docs/frameworks/multi-framework",
    badge: "Agent Kernel",
    logo: (
      <img
        src="/img/branding/agent-kernel-icon-color.svg"
        alt=""
        className={styles.frameworkLogoImg}
        width={100}
        height={100}
      />
    ),
  };

  const cardInner = (f: (typeof integrations)[number]) => (
    <>
      <div className={styles.frameworkCardHeader}>
        <div className={styles.frameworkLogo}>{f.logo}</div>
        <h3 className={styles.frameworkName}>{f.name}</h3>
      </div>
      <p className={styles.frameworkDescription}>{f.description}</p>
      <span className={`${styles.frameworkLink} ${styles.frameworkLinkInline}`}>
        Learn More
      </span>
    </>
  );

  const featuredInner = (
    <>
      <div className={styles.frameworkFeaturedContent}>
        <div className={styles.frameworkFeaturedMain}>
          <div className={styles.frameworkFeaturedMark}>
            <div className={styles.frameworkFeaturedIconCircle}>
              {multiFramework.logo}
            </div>
          </div>
          <div className={styles.frameworkFeaturedText}>
            <p className={styles.frameworkFeaturedBadge}>
              {multiFramework.badge}
            </p>
            <h3 className={styles.frameworkFeaturedHeading}>
              {multiFramework.name}
            </h3>
            <p className={styles.frameworkFeaturedLead}>
              {multiFramework.description}
            </p>
          </div>
        </div>
        <span
          className={`${styles.frameworkLink} ${styles.frameworkFeaturedCta}`}
        >
          Learn More
        </span>
      </div>
    </>
  );

  useLayoutEffect(() => {
    const section = sectionRef.current;
    if (!section) {
      return;
    }

    const reducedMotion =
      typeof window !== "undefined" &&
      window.matchMedia("(prefers-reduced-motion: reduce)").matches;

    const header = section.querySelector(`.${styles.sectionHeader}`);
    const block = section.querySelector(`.${styles.frameworkBlock}`);
    const cards = Array.from(
      section.querySelectorAll(`.${styles.frameworkGridCell}`),
    );
    const featuredRow = section.querySelector(`.${styles.frameworkFeaturedRow}`);

    if (!header || !block || !cards.length || !featuredRow) {
      return;
    }

    if (reducedMotion) {
      gsap.set([header, block, ...cards, featuredRow], {
        opacity: 1,
        y: 0,
        scale: 1,
      });
      return;
    }

    gsap.set(header, { opacity: 0, y: 24 });
    gsap.set(cards, { opacity: 0, y: 28, scale: 0.95 });
    gsap.set(featuredRow, { opacity: 0, y: 28, scale: 0.98 });

    const tl = gsap.timeline({
      scrollTrigger: {
        trigger: header,
        start: "top 75%",
        toggleActions: "play none none reverse",
      },
    });

    tl.to(header, {
      opacity: 1,
      y: 0,
      duration: 0.6,
      ease: "power2.out",
    })
      .to(
        cards,
        {
          opacity: 1,
          y: 0,
          scale: 1,
          duration: 0.5,
          stagger: 0.05,
          ease: "power2.out",
        },
        "-=0.35",
      )
      .to(
        featuredRow,
        {
          opacity: 1,
          y: 0,
          scale: 1,
          duration: 0.5,
          ease: "power2.out",
        },
        "-=0.25",
      );

    return () => {
      tl.scrollTrigger?.kill();
      tl.kill();
    };
  }, []);

  return (
    <section
      id={FEATURE_ANCHORS.frameworks}
      className={`${styles.section} ${styles.pageAnchor}`}
      ref={sectionRef}
    >
      <div className="container">
        <div className={styles.sectionHeader}>
          <p className={styles.sectionLabel}>03 | Framework Support</p>
          <h2 className={styles.sectionTitle}>One Runtime, Any Framework</h2>
          <p className={styles.sectionSubtitle}>
            Use the best framework for each job, and run them all together in a
            single deployment.
          </p>
        </div>

        <div className={styles.frameworkBlock}>
          <ul className={styles.frameworksGrid}>
            {integrations.map((f) => (
              <li key={f.key} className={styles.frameworkGridCell}>
                {f.external ? (
                  <a
                    href={f.link}
                    className={styles.frameworkCard}
                    target="_blank"
                    rel="noopener noreferrer"
                  >
                    {cardInner(f)}
                  </a>
                ) : (
                  <Link to={f.link} className={styles.frameworkCard}>
                    {cardInner(f)}
                  </Link>
                )}
              </li>
            ))}
          </ul>

          <Link
            to={multiFramework.link}
            className={styles.frameworkFeaturedRow}
          >
            {featuredInner}
          </Link>
        </div>
      </div>
    </section>
  );
}

/* ─── Testing Section ───────────────────────────────────────────────────── */

function TestingSection() {
  const sectionRef = useRef<HTMLElement>(null);

  const approaches = [
    {
      key: "cli",
      icon: <MdTerminal />,
      title: "CLI Testing",
      description:
        "Interactive sessions for rapid development iteration and multi-agent testing.",
      highlights: [
        "Interactive chat sessions",
        "Real-time feedback",
        "Persistent CLI sessions",
        "Multi-agent support",
      ],
      link: "/docs/testing/cli-testing",
    },
    {
      key: "automated",
      icon: <MdCode />,
      title: "Automated Tests",
      description:
        "pytest-integrated test suites that run in CI/CD with session-scoped fixtures.",
      highlights: [
        "pytest integration",
        "Session-scoped fixtures",
        "Ordered test execution",
        "CI/CD ready",
      ],
      link: "/docs/testing/automated-testing",
    },
  ];

  const modes = [
    {
      key: "fuzzy",
      icon: <MdSpeed />,
      name: "Fuzzy Mode",
      description:
        "Fast string matching with configurable thresholds using RapidFuzz. Ideal for deterministic outputs.",
      link: "/docs/testing/cli-testing#fuzzy-mode",
    },
    {
      key: "judge",
      icon: <MdBugReport />,
      name: "Judge Mode",
      description:
        "LLM-based semantic evaluation using Ragas. Handles paraphrasing and AI-generated variation.",
      link: "/docs/testing/cli-testing#judge-mode",
    },
    {
      key: "fallback",
      icon: <MdTimer />,
      name: "Fallback Mode",
      description:
        "Tries fuzzy first, falls back to judge. The default — best of both worlds.",
      link: "/docs/testing/cli-testing#fallback-mode-default",
    },
  ];

  useLayoutEffect(() => {
    const section = sectionRef.current;
    if (!section) {
      return;
    }

    const reducedMotion =
      typeof window !== "undefined" &&
      window.matchMedia("(prefers-reduced-motion: reduce)").matches;

    const header = section.querySelector(`.${styles.sectionHeader}`);
    const block = section.querySelector(`.${styles.testingBlock}`);
    const approachCards = Array.from(
      section.querySelectorAll(`.${styles.testingApproachCell}`),
    );
    const modePanel = section.querySelector(`.${styles.testingModesPanel}`);
    const modeCards = Array.from(
      section.querySelectorAll(`.${styles.testingModeCell}`),
    );

    if (!header || !block || !approachCards.length || !modePanel || !modeCards.length) {
      return;
    }

    if (reducedMotion) {
      gsap.set([header, block, ...approachCards, modePanel, ...modeCards], {
        opacity: 1,
        y: 0,
        scale: 1,
      });
      return;
    }

    gsap.set(header, { opacity: 0, y: 24 });
    gsap.set(approachCards, { opacity: 0, y: 28, scale: 0.95 });
    gsap.set(modeCards, { opacity: 0, y: 22, scale: 0.96 });

    const tl = gsap.timeline({
      scrollTrigger: {
        trigger: header,
        start: "top 75%",
        toggleActions: "play none none reverse",
      },
    });

    tl.to(header, {
      opacity: 1,
      y: 0,
      duration: 0.5,
      ease: "power2.out",
    })
      .to(
        approachCards,
        {
          opacity: 1,
          y: 0,
          scale: 1,
          duration: 0.45,
          stagger: 0.06,
          ease: "power2.out",
        },
        "-=0.3",
      )
      .to(
        modeCards,
        {
          opacity: 1,
          y: 0,
          scale: 1,
          duration: 0.4,
          stagger: 0.05,
          ease: "power2.out",
        },
        "-=0.25",
      );

    return () => {
      tl.scrollTrigger?.kill();
      tl.kill();
    };
  }, []);

  return (
    <section
      id={FEATURE_ANCHORS.testing}
      className={`${styles.section} ${styles.testingSection} ${styles.pageAnchor}`}
      ref={sectionRef}
    >
      <div className="container">
        <div className={styles.sectionHeader}>
          <p className={styles.sectionLabel}>04 | Testing</p>
          <h2 className={styles.sectionTitle}>Testing Framework</h2>
          <p className={styles.sectionSubtitle}>
            Test your agents like any other code. CLI testing for development,
            automated suites for CI/CD, and three comparison modes for every use
            case.
          </p>
        </div>
        <div className={styles.testingBlock}>
          <ul className={styles.testingApproachesGrid}>
            {approaches.map((a) => (
              <li key={a.key} className={styles.testingApproachCell}>
                <article className={styles.testingApproachCard}>
                  <div className={styles.testingApproachHeader}>
                    <div className={styles.testingIconWrap} aria-hidden="true">
                      {a.icon}
                    </div>
                    <h3 className={styles.testingApproachTitle}>{a.title}</h3>
                  </div>
                  <p className={styles.testingApproachDescription}>
                    {a.description}
                  </p>
                  <ul className={styles.testingHighlights}>
                    {a.highlights.map((h) => (
                      <li key={h}>{h}</li>
                    ))}
                  </ul>
                  <Link to={a.link} className={styles.testingLink}>
                    Learn More
                  </Link>
                </article>
              </li>
            ))}
          </ul>

          <div className={styles.testingModesPanel}>
            <p className={styles.testingGroupLabel}>Comparison modes</p>
            <ul className={styles.testingModesGrid}>
              {modes.map((m) => (
                <li key={m.key} className={styles.testingModeCell}>
                  <Link to={m.link} className={styles.testingModeCard}>
                    <div className={styles.testingModeHeader}>
                      <div
                        className={styles.testingIconWrap}
                        aria-hidden="true"
                      >
                        {m.icon}
                      </div>
                      <h4 className={styles.testingModeName}>{m.name}</h4>
                    </div>
                    <p className={styles.testingModeDescription}>
                      {m.description}
                    </p>
                  </Link>
                </li>
              ))}
            </ul>
          </div>
        </div>
      </div>
    </section>
  );
}

const MESSAGING_PLATFORMS = [
  {
    name: "Slack",
    icon: <img src="/img/integrations/slack-logo.png" alt="" width={28} height={28} />,
    color: "#EC407A",
    link: "/docs/integrations/slack",
  },
  {
    name: "Microsoft Teams",
    icon: <img src="/img/integrations/teams-logo.png" alt="" width={28} height={24} />,
    color: "#A8B2FF",
    link: "/docs/next/integrations/teams",
  },
  {
    name: "WhatsApp",
    icon: <img src="/img/integrations/whatsapp-logo.png" alt="" width={28} height={28} />,
    color: "#3DFF9A",
    link: "/docs/integrations/whatsapp",
  },
  {
    name: "Messenger",
    icon: <img src="/img/integrations/messenger-logo.png" alt="" width={28} height={28} />,
    color: "#1AACFF",
    link: "/docs/integrations/messenger",
  },
  {
    name: "Telegram",
    icon: <img src="/img/integrations/telegram-logo.png" alt="" width={28} height={28} />,
    color: "#40BFFF",
    link: "/docs/integrations/telegram",
  },
  {
    name: "Instagram",
    icon: <img src="/img/integrations/instagram-logo.png" alt="" width={26} height={26} />,
    color: "#FF6BA3",
    link: "/docs/integrations/instagram",
  },
  {
    name: "Gmail",
    icon: <img src="/img/integrations/gmail-logo.png" alt="" width={26} height={20} />,
    color: "#FF7B6E",
    link: "/docs/integrations/gmail",
  },
] as const;

/* ─── Messaging Section ─────────────────────────────────────────────────── */

function MessagingSection() {
  const sectionRef = useRef<HTMLElement>(null);
  const sceneRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const reducedMotion =
      typeof window !== 'undefined' &&
      window.matchMedia('(prefers-reduced-motion: reduce)').matches;

    const ctx = gsap.context(() => {
      const header = sectionRef.current?.querySelector(`.${styles.sectionHeader}`);
      const cards = sceneRef.current?.querySelectorAll(
        `.${styles.msgChannelCard}`,
      );
      if (!cards?.length) return;

      if (reducedMotion) {
        if (header) gsap.set(header, { opacity: 1, y: 0 });
        gsap.set(cards, { opacity: 1, y: 0 });
        return;
      }

      if (header) gsap.set(header, { opacity: 0, y: 24 });
      gsap.set(cards, { opacity: 0, y: 18 });

      const tl = gsap.timeline({
        scrollTrigger: {
          trigger: header || sceneRef.current,
          start: "top 75%",
          toggleActions: "play none none reverse",
        },
      });

      if (header) {
        tl.to(header, { opacity: 1, y: 0, duration: 0.6, ease: "power2.out" });
      }

      tl.to(
        cards,
        {
          opacity: 1,
          y: 0,
          duration: 0.45,
          stagger: 0.04,
          ease: "power2.out",
        },
        header ? "-=0.35" : "0",
      );
    }, sectionRef);

    return () => ctx.revert();
  }, []);

  return (
    <section
      id={FEATURE_ANCHORS.messaging}
      className={`${styles.section} ${styles.pageAnchor} ${styles.messagingSection}`}
      ref={sectionRef}
    >
      <div className="container">
        <div className={styles.sectionHeader}>
          <p className={styles.sectionLabel}>05 | Messaging</p>
          <h2 className={styles.sectionTitle}>Messaging Integrations</h2>
          <p className={styles.sectionSubtitle}>
            Your agents meet users on the channels they already use. Every
            integration routes through the same Agent Kernel runtime. Pick a
            channel below for setup steps.
          </p>
        </div>

        <div ref={sceneRef} className={styles.msgChannelScene}>
          <ul className={styles.msgChannelGrid}>
            {MESSAGING_PLATFORMS.slice(0, 4).map((p) => (
              <li key={p.name} className={styles.msgChannelCell}>
                <Link
                  to={p.link}
                  className={`${styles.msgChannelCard}${(p as { featured?: boolean }).featured ? ` ${styles.msgChannelCardFeatured}` : ""}`}
                  style={{ "--msg-brand": p.color } as React.CSSProperties}
                >
                  {(p as { featured?: boolean }).featured && (
                    <span className={styles.msgFeaturedBadge}>Popular</span>
                  )}
                  <div className={styles.msgChannelTop}>
                    <span className={styles.msgChannelIcon} aria-hidden>
                      {p.icon}
                    </span>
                    <span className={styles.msgChannelName}>{p.name}</span>
                  </div>
                  <span className={styles.msgChannelCta}>Step Guide</span>
                </Link>
              </li>
            ))}
          </ul>

          <ul className={styles.msgChannelGrid}>
            {MESSAGING_PLATFORMS.slice(4).map((p) => (
              <li key={p.name} className={styles.msgChannelCell}>
                <Link
                  to={p.link}
                  className={`${styles.msgChannelCard}${(p as { featured?: boolean }).featured ? ` ${styles.msgChannelCardFeatured}` : ""}`}
                  style={{ "--msg-brand": p.color } as React.CSSProperties}
                >
                  {(p as { featured?: boolean }).featured && (
                    <span className={styles.msgFeaturedBadge}>Popular</span>
                  )}
                  <div className={styles.msgChannelTop}>
                    <span className={styles.msgChannelIcon} aria-hidden>
                      {p.icon}
                    </span>
                    <span className={styles.msgChannelName}>{p.name}</span>
                  </div>
                  <span className={styles.msgChannelCta}>Step Guide</span>
                </Link>
              </li>
            ))}
          </ul>
        </div>

        <div className={styles.msgChannelFooter}>
          <Link
            to="/docs/integrations/overview"
            className={`button button--primary button--md ${indexStyles.terraformLink}`}
          >
            Full integrations overview
          </Link>
        </div>
      </div>
    </section>
  );
}

/* ─── Protocol Support ──────────────────────────────────────────────────── */

function ProtocolSupport() {
  const sectionRef = useRef<HTMLElement>(null);
  const protocols = [
    {
      key: "mcp",
      icon: <MdExtension />,
      title: "MCP - Model Context Protocol",
      description:
        "Model Context Protocol (MCP) is a standardized interface that lets AI models connect to external tools, data sources, and services in a structured, consistent way. It acts as a bridge between an AI's reasoning and real-world actions, enabling agents to retrieve information and execute tasks reliably. Agent Kernel natively supports running an MCP server, including exposing your agents as MCP tools.",
      link: "/docs/api/mcp-server",
      linkLabel: "MCP Server Docs",
    },
    {
      key: "a2a",
      icon: <MdHub />,
      title: "A2A - Agent-to-Agent",
      description:
        "Agent-to-Agent (A2A) is a communication pattern where multiple AI agents interact directly with each other to share context, delegate tasks, and coordinate decisions. It enables complex workflows by allowing specialized agents to collaborate instead of relying on a single monolithic system. Agent Kernel natively supports exposing any agent over the A2A protocol by switching configuration.",
      link: "/docs/api/a2a-server",
      linkLabel: "A2A Server Docs",
    },
  ];
  useLayoutEffect(() => {
    const section = sectionRef.current;
    if (!section) return;

    const reducedMotion =
      typeof window !== 'undefined' &&
      window.matchMedia('(prefers-reduced-motion: reduce)').matches;

    const header = section.querySelector(`.${styles.sectionHeader}`);
    const grid = section.querySelector(`.${styles.protocolGrid}`);
    const cells = Array.from(section.querySelectorAll(`.${styles.protocolCell}`));

    if (!header || !grid || !cells.length) return;

    if (reducedMotion) {
      gsap.set([header, grid, cells], { opacity: 1, y: 0, scale: 1 });
      return;
    }

    gsap.set(header, { opacity: 0, y: 24 });
    gsap.set(cells, { opacity: 0, y: 28, scale: 0.98 });

    const tl = gsap.timeline({
      scrollTrigger: {
        trigger: header,
        start: 'top 75%',
        toggleActions: 'play none none reverse',
      },
    });

    tl.to(header, { opacity: 1, y: 0, duration: 0.5, ease: 'power2.out' })
      .to(
        cells,
        { opacity: 1, y: 0, scale: 1, duration: 0.45, stagger: 0.05, ease: 'power2.out' },
        '-=0.3',
      );

    return () => {
      tl.scrollTrigger?.kill();
      tl.kill();
    };
  }, []);

  return (
    <section
      id={FEATURE_ANCHORS.protocols}
      className={`${styles.section} ${styles.protocolSection} ${styles.pageAnchor}`}
      ref={sectionRef}
    >
      <div className="container">
        <div className={styles.sectionHeader}>
          <p className={styles.sectionLabel}>06 | Protocol</p>
          <h2 className={styles.sectionTitle}>Protocol Support</h2>
          <p className={styles.sectionSubtitle}>
            Standard protocols for tool connectivity and multi-agent
            coordination. Wired into the runtime.
          </p>
        </div>
        <ul className={styles.protocolGrid}>
          {protocols.map((p) => (
            <li key={p.key} className={styles.protocolCell}>
              <article className={styles.protocolCard}>
                <div className={styles.protocolCardHeader}>
                  <div className={styles.protocolIconWrap} aria-hidden="true">
                    {p.icon}
                  </div>
                  <h3 className={styles.protocolTitle}>{p.title}</h3>
                </div>
                <p className={styles.protocolDescription}>{p.description}</p>
                <Link to={p.link} className={styles.protocolLink}>
                  {p.linkLabel}
                </Link>
              </article>
            </li>
          ))}
        </ul>
      </div>
    </section>
  );
}

/* ─── CTA ───────────────────────────────────────────────────────────────── */

function CTASection({
  sectionRef,
}: {
  sectionRef: React.RefObject<HTMLElement>;
}) {
  return (
    <section
      ref={sectionRef}
      id={FEATURE_ANCHORS.cta}
      className={`${indexStyles.ctaSection} ${styles.pageAnchor}`}
    >
      <div className="container">
        <div className={indexStyles.ctaContent}>
          <h2 className={indexStyles.ctaTitle}>
            Ready to Ship Your
            <br />
            First <span className={indexStyles.ctaTitleGradient}>Agent</span>?
          </h2>
          <p className={indexStyles.ctaSubtitle}>
            Free, open-source, Apache 2.0. No licensing costs, no vendor
            lock-in. Join hundreds of developers building production AI agents
            with Agent Kernel.
          </p>
          <div className={indexStyles.ctaButtons}>
            <Link
              className={`button button--primary button--lg ${indexStyles.heroBtnSecondary}`}
              to="/docs"
            >
              Get Started Free
            </Link>
            <Link
              className={indexStyles.heroBtnLink}
              to="https://github.com/yaalalabs/agent-kernel"
              target="_blank"
              rel="noopener noreferrer"
            >
              View On GitHub
            </Link>
          </div>

          <div className={indexStyles.ctaImageWrapper}>
            <img src="/img/cta-bg.png" alt="Agent Kernel" className={indexStyles.ctaImage} />
          </div>
        </div>
      </div>
    </section>
  );
}

/* ─── Page Export ───────────────────────────────────────────────────────── */

export default function Features() {
  const plantParticlesBackgroundRef = useRef<PlantParticlesBackgroundHandle>(
    null,
  );
  const ctaRef = useRef<HTMLElement>(null);
  const ctaObserverStateRef = useRef<boolean>(false);

  useEffect(() => {
    if (!plantParticlesBackgroundRef.current || !ctaRef.current) return;

    const observer = new IntersectionObserver(
      ([entry]) => {
        if (entry.isIntersecting && !ctaObserverStateRef.current) {
          ctaObserverStateRef.current = true;
          plantParticlesBackgroundRef.current?.triggerReverseScatterIn();
        } else if (!entry.isIntersecting && ctaObserverStateRef.current) {
          ctaObserverStateRef.current = false;
          plantParticlesBackgroundRef.current?.triggerScatterIn();
        }
      },
      { threshold: 0.4 },
    );

    observer.observe(ctaRef.current);

    return () => {
      observer.disconnect();
    };
  }, []);

  return (
    <Layout
      title="Features"
      description="Comprehensive overview of Agent Kernel features — framework-agnostic, multi-cloud AI agent runtime with built-in testing, observability, guardrails, and messaging integrations."
    >
      {/* <div style={{ position: 'fixed', top: 0, left: 0, width: '100%', height: '100vh', zIndex: 0, pointerEvents: 'auto' }}>
        <HeroAnimation
          badge="Features"
          title="Everything to Build AI Agents"
          subtitle="From framework-neutral runtime and smart memory to guardrails, observability, testing and multi-cloud deployment. Everything needed to build and ship production agents without platform engineering overhead."
          primaryCtaLabel="Get Started"
          primaryCtaTo="/docs"
          secondaryCtaLabel="Explore Use Cases"
          secondaryCtaTo="/use-cases"
        />
      </div> */}

      {/* <div style={{ height: '100vh' }} /> */}

      <main className={indexStyles.featuresPageSection} style={{ position: 'relative', zIndex: 10 }}>
        <WhyAgentKernel />
        <FeaturesPageMap
          plantParticlesBackgroundRef={plantParticlesBackgroundRef}
        />
        <ProblemTable />
        <CoreFeatures />
        <FrameworkSupport />
        <TestingSection />
        <MessagingSection />
        <ProtocolSupport />
      </main>

      <CTASection sectionRef={ctaRef} />
    </Layout>
  );
}
