import React, { useEffect, useRef } from "react";
import gsap from "gsap";
import ScrollTrigger from "gsap/dist/ScrollTrigger";
import Link from "@docusaurus/Link";
import Layout from "@theme/Layout";
import { useHistory } from "@docusaurus/router";
import {
  MdTerminal,
  MdBolt,
  MdCode,
  MdAutoAwesome,
  MdSmartToy,
  MdLink,
  MdPermMedia,
  MdSecurity,
  MdCloud,
  MdLanguage,
  MdMessage,
  MdScience,
  MdVisibility,
} from "react-icons/md";
import styles from "./index.module.css";
import AgentKernelArchDiagram from "../components/AgentKernelArchDiagram";
import { StepTimeline } from "../components/StepTimeline";
import HeroAnimation from "../components/HeroAnimation";
import FrameworkSelector from "../components/FrameworkSelector";
import heroStyles from "../components/HeroAnimation/styles.module.css";
import { FaGithub } from "react-icons/fa";

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

export default function DeveloperPage() {
  const history = useHistory();
  const contentRef = useRef<HTMLDivElement>(null);
  const sectionRef = useRef<HTMLElement>(null);

  useEffect(() => {
    gsap.registerPlugin(ScrollTrigger);

    if (!sectionRef.current || !contentRef.current) {
      return;
    }

    const context = gsap.context(() => {
      // Animate developer analogy section
      const devAnalogy = contentRef.current?.querySelector(
        `.${styles.developerAnalogy}`,
      );
      if (devAnalogy) {
        gsap.fromTo(
          devAnalogy,
          { opacity: 0, y: 35 },
          {
            opacity: 1,
            y: 0,
            duration: 1.1,
            ease: "power2.out",
            scrollTrigger: {
              trigger: devAnalogy,
              start: "top 75%",
              toggleActions: "play none none reverse",
            },
          },
        );
      }

      // Animate Architecture Wrapper
      const archWrappers =
        contentRef.current?.querySelectorAll(
          `.${styles.devArchitectureWrapper}`,
        ) || [];
      archWrappers.forEach((wrapper) => {
        gsap.fromTo(
          wrapper,
          { opacity: 0, y: 40, scale: 0.95 },
          {
            opacity: 1,
            y: 0,
            scale: 1,
            duration: 1.1,
            ease: "power2.out",
            scrollTrigger: {
              trigger: wrapper,
              start: "top 80%",
              toggleActions: "play none none reverse",
            },
          },
        );
      });

      // Animate architecture layers - Slide from left
      const layers =
        contentRef.current?.querySelectorAll(
          `.${styles.developerArchitectureLayerGroup}`,
        ) || [];
      layers.forEach((layer, index) => {
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

      // Animate feature cards
      const devFeatureCard =
        contentRef.current?.querySelectorAll(`.${styles.devFeatureCard}`) || [];
      devFeatureCard.forEach((card, idx) => {
        gsap.fromTo(
          card,
          { opacity: 0, y: 25, scale: 0.96 },
          {
            opacity: 1,
            y: 0,
            scale: 1,
            duration: 0.95,
            ease: "power2.out",
            delay: (idx % 3) * 0.1,
            scrollTrigger: {
              trigger: card,
              start: "top 88%",
              toggleActions: "play none none reverse",
            },
          },
        );
      });

      // Animate framework section
      const devFrameworkSection = contentRef.current?.querySelector(
        `.${styles.devFrameworkSection}`,
      );
      if (devFrameworkSection) {
        gsap.fromTo(
          devFrameworkSection,
          { opacity: 0, y: 40 },
          {
            opacity: 1,
            y: 0,
            duration: 1.1,
            ease: "power2.out",
            scrollTrigger: {
              trigger: devFrameworkSection,
              start: "top 60%",
              toggleActions: "play none none reverse",
            },
          },
        );
      }

      // Animate framework buttons
      const frameworkButtons =
        contentRef.current?.querySelectorAll(`.${styles.devFrameworkButton}`) ||
        [];
      frameworkButtons.forEach((btn, idx) => {
        gsap.fromTo(
          btn,
          { opacity: 0, y: 15, scale: 0.95 },
          {
            opacity: 1,
            y: 0,
            scale: 1,
            duration: 0.7,
            ease: "power2.out",
            delay: idx * 0.08,
            scrollTrigger: {
              trigger: btn,
              start: "top 85%",
              toggleActions: "play none none reverse",
            },
          },
        );
      });

      // Animate code blocks
      const codeBlocks =
        contentRef.current?.querySelectorAll(
          `.${styles.devFrameworkCodeBlock}`,
        ) || [];
      codeBlocks.forEach((block, idx) => {
        gsap.fromTo(
          block,
          { opacity: 0, x: 30, scale: 0.98 },
          {
            opacity: 1,
            x: 0,
            scale: 1,
            duration: 0.95,
            ease: "power2.out",
            delay: idx * 0.12,
            scrollTrigger: {
              trigger: block,
              start: "top 83%",
              toggleActions: "play none none reverse",
            },
          },
        );
      });

      // Add professional hover animations to cards
      const allAnimatedCards =
        contentRef.current?.querySelectorAll(
          `.${styles.devFeatureCard}`,
        ) || [];
      allAnimatedCards.forEach((card: any) => {
        card.addEventListener("mouseenter", () => {
          gsap.to(card, {
            y: -6,
            scale: 1.02,
            boxShadow: "0 16px 32px rgba(0,0,0,0.12)",
            duration: 0.25,
            ease: "power2.out",
          });
        });
        card.addEventListener("mouseleave", () => {
          gsap.to(card, {
            y: 0,
            scale: 1,
            boxShadow: "0 4px 12px rgba(0,0,0,0.05)",
            duration: 0.25,
            ease: "power2.out",
          });
        });
      });

      // Add hover animations to framework buttons
      frameworkButtons.forEach((btn: any) => {
        btn.addEventListener("mouseenter", () => {
          gsap.to(btn, {
            scale: 1.05,
            duration: 0.15,
            ease: "power2.out",
          });
        });
        btn.addEventListener("mouseleave", () => {
          gsap.to(btn, {
            scale: 1,
            duration: 0.15,
            ease: "power2.out",
          });
        });
      });
    }, sectionRef);

    return () => {
      context.revert();
    };
  }, []);

  return (
    <Layout
      title="Agent Kernel for Developers"
      description="Learn how Agent Kernel helps developers build and deploy AI agents quickly without reinventing the wheel."
    >
      {/* <HeroAnimation
        badge="Developers"
        title="Build AI Agents Without Rebuilding Infrastructure"
        subtitle="Agent Kernel gives developers a production-ready runtime so you can focus on agent logic. Use your preferred framework, expose agents through API or messaging channels, and deploy to cloud environments fast with enterprise-grade building blocks included."
      /> */}
      <StepTimeline levelId="02" contentRef={contentRef} />
      <section ref={sectionRef} className={styles.devPageSection}>
        <div className="container">
          <div ref={contentRef} className={styles.developerContent}>
            {/* Step 01 — Developer Analogy */}
            <div
              className={`${styles.developerAnalogy} ${styles.developerBlock}`}
              data-step="dev-01"
            >
              <p className={styles.devStepLabel}>Step 01: Analogy</p>
              <h1 className={styles.devTitle}>
                <span>Building blocks and deployment infrastructure</span>
                {' '}
                <span>for your AI Agent.</span>
              </h1>
              <div className={styles.devDescription}>
                <p className={styles.devIntro}>
                  Agent Kernel is like the operating system for the AI
                  assistants, think Linux for your agents.
                </p>
                <div className={styles.devBulletList}>
                  <div className={styles.devBulletItem}>
                    <span className={styles.devBullet} />
                    <span className={styles.devBulletText}>
                      Install it on your laptop, server, or cloud and run AI
                      agents hassle-free.
                    </span>
                  </div>
                  <div className={styles.devBulletItem}>
                    <span className={styles.devBullet} />
                    <span className={styles.devBulletText}>
                      No need to build infrastructure, APIs, or messaging and
                      other integrations.
                    </span>
                  </div>
                  <div className={styles.devBulletItem}>
                    <span className={styles.devBullet} />
                    <span className={styles.devBulletText}>
                      Everything works out of the box.
                    </span>
                  </div>
                  <div className={styles.devBulletItem}>
                    <span className={styles.devBullet} />
                    <span className={styles.devBulletText}>
                      Scales from single execution to thousands of agent
                      invocations in parallel.
                    </span>
                  </div>
                  <div className={styles.devBulletItem}>
                    <span className={styles.devBullet} />
                    <span className={styles.devBulletText}>
                      Interacts with the real world automatically.
                    </span>
                  </div>
                  <div className={styles.devBulletItem}>
                    <span className={styles.devBullet} />
                    <span className={styles.devBulletText}>
                      Just define what your agent should do.
                    </span>
                  </div>
                </div>
              </div>
            </div>

            {/* Architecture flow — 8 stacked layers */}
            <div
              className={`${styles.architectureWrapper} ${styles.developerBlock}`}
              data-step="dev-02"
            >
              <div className={styles.architectureStack}>
                {[
                  {
                    num: "01",
                    label: "Your Agent Logic",
                    items: ["Instructions", "Tools", "Framework SDK"],
                  },
                  {
                    num: "02",
                    label: "Agent Kernel Runtime",
                    items: [
                      "Agents",
                      "Agent Runner",
                      "Session Management",
                      "Hooks",
                    ],
                  },
                  {
                    num: "03",
                    label: "Storage & Memory",
                    items: [
                      "In-Memory",
                      "Redis",
                      "DynamoDB",
                      "CosmosDB",
                      "Firestore",
                    ],
                  },
                  {
                    num: "04",
                    label: "Knowledge Bases",
                    items: ["ChromaDB", "Neo4j", "Starburst", "SQLDB"],
                  },
                  {
                    num: "05",
                    label: "Observability",
                    items: ["LangFuse", "OpenLLMetry"],
                  },
                  {
                    num: "06",
                    label: "Cloud Infrastructure",
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
                    num: "07",
                    label: "Interfacing",
                    items: ["CLI", "MCP", "A2A", "REST API"],
                  },
                  {
                    num: "08",
                    label: "Channels",
                    items: [
                      "Slack",
                      "Teams",
                      "WhatsApp",
                      "Telegram",
                      "Messenger",
                      "Instagram",
                      "Gmail",
                    ],
                  },
                ].map((layer, i, arr) => (
                  <div
                    key={layer.label}
                    className={styles.developerArchitectureLayerGroup}
                  >
                    {/* Step number */}
                    <div className={styles.layerNumberWrapper}>
                      <div className={styles.layerNumberCircle}>
                        {layer.num}
                      </div>
                      {i < arr.length - 1 && (
                        <div className={styles.layerConnector} />
                      )}
                    </div>
                    {/* Content */}
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

            {/* Step 02 — Available Features */}
            <div className={styles.devFeatureSection} data-step="dev-03">
              <p className={styles.devStepLabel}>
                Step 02: Features
              </p>
              <h2 className={styles.devTitle}>
                <span>
                  All Enterprise Features Available
                </span><br />
                <span>
                  Free And Open-Source
                </span>
              </h2>

              <div className={styles.devFeatureGroups}>
                {DEV_FEATURE_GROUPS.map((group) => (
                  <div key={group.title} className={styles.devFeatureGroup}>
                    <h3 className={styles.devFeatureGroupTitle}>
                      {group.title}
                    </h3>
                    <div
                      className={`${styles.devFeaturesGrid} ${group.cols === 4
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

            {/* Step 03 — Framework Selection */}
            <div
              className={`${styles.devFrameworkSection} ${styles.developerBlock}`}
              data-step="dev-04"
            >
              <p className={styles.devStepLabel}>Step 03: Framework</p>
              <h2 className={styles.devTitle}>
                <span>
                  Use The Framework You Prefer
                </span>
              </h2>

              <FrameworkSelector showTitle={false} showDescription={true} />
            </div>

            {/* Step 04 — How Agent Kernel Fits In */}
            <div className={styles.devArchitectureSection} data-step="dev-05">
              <p className={styles.devStepLabel}>Step 04: How It Works</p>
              <h2 className={styles.devTitle}>
                <span>How Agent Kernel Fits In</span>
              </h2>

              <p className={styles.devFrameworkBody}>
                You write your AI agent's logic. Agent Kernel handles everything
                else: the infrastructure, the cloud deployment, memory, knowledge
                bases, hooks, observability & traceability, LLM cost tracking,
                the integrations so your agent is live and talking to real users
                in days.
              </p>

              <div className={styles.devArchitectureWrapper}>
                <AgentKernelArchDiagram accentColor="#CC7D21" />
              </div>
            </div>

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
                      style={{ '--card-accent': '#CC7D21' } as React.CSSProperties}
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
                      style={{ '--card-accent': '#CC7D21' } as React.CSSProperties}
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

                  <div style={{ marginTop: '4rem', display: 'flex', justifyContent: 'center' }}>
                    <button
                      type="button"
                      className={`button button--primary button--md ${styles.terraformLink}`}
                      onClick={() => {
                        history.push('/');
                        setTimeout(() => {
                          document.getElementById('levels')?.scrollIntoView({ behavior: 'smooth' });
                        }, 100);
                      }}
                    >
                      Back to Path Selection
                    </button>
                  </div>
                </div>
              </div>
            </section>
          </div>
        </div>
      </section>

      <section className={styles.ctaSection}>
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
                className={`button button--primary button--lg ${styles.heroBtnSecondary}`}
                to="/docs"
              >
                Get Started Free
              </Link>
              <Link
                className={styles.heroBtnLink}
                to="https://github.com/yaalalabs/agent-kernel"
                target="_blank"
                rel="noopener noreferrer"
              >
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
