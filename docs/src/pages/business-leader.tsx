import { useEffect, useRef } from "react";
import gsap from "gsap";
import ScrollTrigger from "gsap/dist/ScrollTrigger";
import Link from "@docusaurus/Link";
import Layout from "@theme/Layout";
import {
  MdRocketLaunch,
  MdMessage,
  MdCloud,
} from "react-icons/md";
import styles from "./index.module.css";
import AgentExecutionFlowDiagram from "../components/AgentExecutionFlowDiagram";
import AgentKernelArchDiagram from "../components/AgentKernelArchDiagram";
import BusinessLeaderScenarios from "../components/BusinessLeaderScenarios";
import { StepTimeline } from "../components/StepTimeline";
import HeroAnimation from "../components/HeroAnimation";
import heroStyles from "../components/HeroAnimation/styles.module.css";
import { FaGithub } from "react-icons/fa";

export default function BusinessLeaderPage() {
  const contentRef = useRef<HTMLDivElement>(null);
  const sectionRef = useRef<HTMLElement>(null);

  useEffect(() => {
    gsap.registerPlugin(ScrollTrigger);

    if (!sectionRef.current || !contentRef.current) {
      return;
    }

    const context = gsap.context(() => {
      // Animate contentStep elements - Smooth fade and slide
      const steps =
        contentRef.current?.querySelectorAll(`.${styles.contentStep}`) || [];
      steps.forEach((step) => {
        gsap.fromTo(
          step,
          { opacity: 0, y: 30 },
          {
            opacity: 1,
            y: 0,
            duration: 1,
            ease: "power2.out",
            scrollTrigger: {
              trigger: step,
              start: "top 85%",
              toggleActions: "play none none reverse",
            },
          },
        );
      });

      // Animate contentCard elements - Subtle scale and fade
      const cards =
        contentRef.current?.querySelectorAll(`.${styles.contentCard}`) || [];
      cards.forEach((card, idx) => {
        gsap.fromTo(
          card,
          { opacity: 0, y: 25, scale: 0.95 },
          {
            opacity: 1,
            y: 0,
            scale: 1,
            duration: 0.9,
            ease: "power2.out",
            delay: idx * 0.08,
            scrollTrigger: {
              trigger: card,
              start: "top 88%",
              toggleActions: "play none none reverse",
            },
          },
        );
      });

      // Animate highlight cards - Smooth entrance with subtle scale
      const highlightCards =
        contentRef.current?.querySelectorAll(`.${styles.blHighlightCard}`) ||
        [];
      highlightCards.forEach((card) => {
        gsap.fromTo(
          card,
          { opacity: 0, y: 30, scale: 0.97 },
          {
            opacity: 1,
            y: 0,
            scale: 1,
            duration: 1.05,
            ease: "power2.out",
            scrollTrigger: {
              trigger: card,
              start: "top 82%",
              toggleActions: "play none none reverse",
            },
          },
        );
      });

      // Animate value cards
      const valueCards =
        contentRef.current?.querySelectorAll(`.${styles.blValueCard}`) || [];
      valueCards.forEach((card, idx) => {
        gsap.fromTo(
          card,
          { opacity: 0, y: 25, scale: 0.96 },
          {
            opacity: 1,
            y: 0,
            scale: 1,
            duration: 0.85,
            ease: "power2.out",
            delay: idx * 0.1,
            scrollTrigger: {
              trigger: card,
              start: "top 88%",
              toggleActions: "play none none reverse",
            },
          },
        );
      });

      // Animate tabs
      const blTabs =
        contentRef.current?.querySelectorAll(`.${styles.blTab}`) || [];
      blTabs.forEach((tab, idx) => {
        gsap.fromTo(
          tab,
          { opacity: 0, y: 15 },
          {
            opacity: 1,
            y: 0,
            duration: 0.7,
            ease: "power2.out",
            delay: idx * 0.06,
            scrollTrigger: {
              trigger: tab,
              start: "top 88%",
              toggleActions: "play none none reverse",
            },
          },
        );
      });

      // Animate scenario content
      const scenarioContent = contentRef.current?.querySelector(
        `.${styles.blScenarioContent}`,
      );
      if (scenarioContent) {
        gsap.fromTo(
          scenarioContent,
          { opacity: 0, y: 30, scale: 0.97 },
          {
            opacity: 1,
            y: 0,
            scale: 1,
            duration: 0.95,
            ease: "power2.out",
            scrollTrigger: {
              trigger: scenarioContent,
              start: "top 85%",
              toggleActions: "play none none reverse",
            },
          },
        );
      }

      // Animate scenario columns
      const scenarioCols =
        contentRef.current?.querySelectorAll(`.${styles.blScenarioCol}`) || [];
      scenarioCols.forEach((col, idx) => {
        gsap.fromTo(
          col,
          { opacity: 0, y: 25, scale: 0.95 },
          {
            opacity: 1,
            y: 0,
            scale: 1,
            duration: 0.85,
            ease: "power2.out",
            delay: idx * 0.1,
            scrollTrigger: {
              trigger: col,
              start: "top 88%",
              toggleActions: "play none none reverse",
            },
          },
        );
      });

      // Animate architecture wrapper
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

      // Add professional hover animations to cards
      const allAnimatedCards =
        contentRef.current?.querySelectorAll(
          `.${styles.contentCard}, .${styles.blValueCard}`,
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
    }, sectionRef);

    return () => {
      context.revert();
    };
  }, []);

  return (
    <Layout
      title="Agent Kernel for Business Leaders"
      description="Learn how Agent Kernel helps business leaders implement AI agents that scale across their organization."
    >
      {/* <HeroAnimation
        badge="Business Leaders"
        title="Scale AI Agents Across Your Organization"
        subtitle="Agent Kernel helps business teams move from AI experimentation to production outcomes. Launch compliant AI agents quickly, connect to real channels, and deploy across AWS, Azure, GCP, or your own infrastructure without rebuilding your platform each time."
      /> */}
      <section ref={sectionRef} className={styles.blPageSection}>
        <StepTimeline levelId="01" contentRef={contentRef} />
        <div className="container">
          <div ref={contentRef} className={styles.levelContent}>
            {/* ── STEP 01 ── */}
            <div className={styles.blStepBlock} data-step="bl-01">
              <div className={styles.contentStep}>
                <p className={styles.stepLabel}>Step 01 / Identify the gap</p>
                <h1 className={styles.contentTitle}>
                  Where is the gap in your business?
                </h1>
                <p className={styles.contentDescription}>
                  Most businesses have processes that still depend too much on
                  people. They are repetitive, slow, and hard to scale. The gap
                  looks different depending on where you are.
                </p>
              </div>

              <div className={styles.contentGrid}>
                <div className={styles.contentCard}>
                  <h3 className={styles.contentCardLabel}>SaaS / Product</h3>
                  <p className={styles.contentCardTitle}>
                    Do you have an existing product?
                  </p>
                  <ul className={styles.bulletList}>
                    <li>Users still do too much manually inside your app</li>
                    <li>
                      Support tickets pile up for questions your product could
                      answer
                    </li>
                    <li>
                      Repetitive workflows require human involvement every time
                    </li>
                  </ul>
                </div>
                <div className={styles.contentCard}>
                  <h3 className={styles.contentCardLabel}>
                    Enterprise / Large Org
                  </h3>
                  <p className={styles.contentCardTitle}>
                    Do you run complex operations?
                  </p>
                  <ul className={styles.bulletList}>
                    <li>
                      Thousands of customer queries handled by an overstretched
                      team
                    </li>
                    <li>Knowledge locked across systems and documents</li>
                    <li>Cross-team hand-offs are slow and error-prone</li>
                  </ul>
                </div>
                <div className={styles.contentCard}>
                  <h3 className={styles.contentCardLabel}>
                    Building Something New
                  </h3>
                  <p className={styles.contentCardTitle}>
                    Do you have a product idea?
                  </p>
                  <ul className={styles.bulletList}>
                    <li>
                      You see an opportunity for an AI-powered service in your
                      industry
                    </li>
                    <li>You're not sure which AI technology to commit to</li>
                    <li>
                      Building from scratch feels like months before anything
                      reaches users
                    </li>
                    <li>
                      You want to build a prototype / proof-of-concept quickly
                      without having to invest too much on it
                    </li>
                  </ul>
                </div>
              </div>
            </div>

            {/* ── STEP 02 ── */}
            <div style={{ marginTop: "2rem" }} data-step="bl-02">
              <p className={styles.stepLabel}>Step 02 / Meet the solution</p>
              <h2 className={styles.contentTitle}>
                <span>An AI agent doesn't just answer,</span>
                  {' '}<br/>
                <span>it gets things done.</span>
              </h2>

              <AgentExecutionFlowDiagram />
            </div>

            {/* ── STEP 03 ── */}
            <div style={{ marginTop: "2rem" }} data-step="bl-03">
              <p className={styles.stepLabel}>Step 03 / Agent Kernel</p>
              <h2 className={styles.contentTitle}>
                <span>Agent Kernel is the engine that powers it at scale to run</span>
                  {' '}
                <span>compliant AI agents</span>
              </h2>

              {/* OS analogy highlight card */}
              <div className={styles.blHighlightCard}>
                <p className={styles.blHighlightEyebrow}>For Your Business</p>
                <h3 className={styles.blHighlightTitle}>
                  Agent Kernel is like the Operating System for AI agents.
                </h3>
                <p className={styles.blHighlightBody}>
                  You don't need to understand how an operating system works to
                  use the Internet. It runs behind the scenes, powering websites,
                  servers, and cloud systems.
                </p>
                <p className={styles.blHighlightBody}>
                  Agent Kernel does the same thing for AI agents. It's a
                  powerful platform that runs your AI agents in the background,
                  handling all the complex infrastructure so that you focus on
                  building the features that matter to your business.
                </p>
              </div>

              {/* 3 value props */}
              <div className={styles.blValueGrid}>
                <div className={styles.blValueCard}>
                  <div className={styles.blValueIcon}>
                    <MdRocketLaunch />
                  </div>
                  <h4 className={styles.blValueTitle}>Days, not months</h4>
                  <p className={styles.blValueBody}>
                    No one must build agent infrastructure from scratch. Go from
                    idea to enterprise-grade working scalable AI agents in days.
                  </p>
                </div>
                <div className={styles.blValueCard}>
                  <div className={styles.blValueIcon}>
                    <MdMessage />
                  </div>
                  <h4 className={styles.blValueTitle}>Works where you are</h4>
                  <p className={styles.blValueBody}>
                    Pre-built messaging connectors such as Slack, WhatsApp,
                    Instagram, Telegrams, Gmail, and Teams. No custom wiring
                    required.
                  </p>
                </div>
                <div className={styles.blValueCard}>
                  <div className={styles.blValueIcon}>
                    <MdCloud />
                  </div>
                  <h4 className={styles.blValueTitle}>Runs on any cloud</h4>
                  <p className={styles.blValueBody}>
                    Deploy on AWS, GCP, Azure, or your own on-prem Docker. No
                    vendor lock-in. You stay in control of your data and
                    infrastructure.
                  </p>
                </div>
              </div>
            </div>

            {/* ── STEP 04 ── */}
            <div style={{ marginTop: "2rem" }} data-step="bl-04">
              <p className={styles.stepLabel}>Step 04 / See it in action</p>
              <h2 className={styles.contentTitle}>
                <span>See your Agent Kernel in action</span>
              </h2>
              <p className={styles.contentDescription}>
                Curious what your agent can actually do? Here are some real
                starting points across industries.
              </p>

              <BusinessLeaderScenarios />
            </div>

            {/* ── STEP 05 — Architecture Overview ── */}
            <div style={{ marginTop: "3rem" }} data-step="bl-05">
              <p className={styles.stepLabel}>Step 05 / How it works</p>
              <h2 className={styles.contentTitle}>
                <span>Agent Kernel is the engine that powers it all</span>
              </h2>
              <p className={styles.contentDescription}>
                You write your AI agent's logic. Agent Kernel handles everything
                else: the infrastructure, the cloud deployment, memory, knowledge
                bases, hooks, observability & traceability, LLM cost tracking,
                the integrations so your agent is live and talking to real users
                in days.
              </p>

              <div className={styles.devArchitectureWrapper}>
                <AgentKernelArchDiagram accentColor="#8E5DFF" />
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
              <Link
                className={styles.goDeeperCard}
                to="/features"
                style={{ '--card-accent': '#6F45CC' } as React.CSSProperties}
              >
                <h3 className={styles.goDeeperCardTitle}>Features</h3>
                <p className={styles.goDeeperCardBody}>
                  Explore the core runtime, memory, guardrails, testing,
                  integrations, and deployment capabilities that make Agent
                  Kernel production-ready.
                </p>
                <span className={styles.goDeeperCardCta}>Read More</span>
              </Link>

              <Link
                className={styles.goDeeperCard}
                to="/use-cases"
                style={{ '--card-accent': '#6F45CC' } as React.CSSProperties}
              >
                <h3 className={styles.goDeeperCardTitle}>Use Cases</h3>
                <p className={styles.goDeeperCardBody}>
                  See how teams use Agent Kernel to build assistants,
                  automate workflows, monitor systems, and ship reliable AI
                  agents faster.
                </p>
                <span className={styles.goDeeperCardCta}>Read More</span>
              </Link>
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
