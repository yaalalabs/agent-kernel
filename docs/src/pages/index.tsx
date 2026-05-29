import React, { useRef, useEffect, useLayoutEffect, useState } from "react";
import Link from "@docusaurus/Link";
import useDocusaurusContext from "@docusaurus/useDocusaurusContext";
import Layout from "@theme/Layout";
import styles from "./index.module.css";
import gsap from "gsap";
import { ScrambleTextPlugin } from "gsap/dist/ScrambleTextPlugin";
import { ScrollTrigger } from "gsap/dist/ScrollTrigger";
import { StepTimeline } from "../components/StepTimeline";
import PlantParticlesBackground from "../components/PlantParticlesBackground";
import {
  MdRocketLaunch,
  MdBugReport,
  MdBuild,
  MdExtension,
  MdIntegrationInstructions,
  MdCloudUpload,
  MdCheck,
  MdClose, 
} from "react-icons/md";
import {
  FaGithub,
  FaAws,
  FaMicrosoft,
} from "react-icons/fa";
import { SiTerraform, SiGmail, SiGooglecloud } from "react-icons/si";
import { useHistory } from "@docusaurus/router";

/* ─── What's New Banner ─────────────────────────────────────────────────── */

function WhatsNewBanner() {
  return (
    <div className={styles.whatsNewBanner}>
      <div className={styles.whatsNewInner}>
        <span className={styles.whatsNewIconWrap}>
          <svg
            xmlns="http://www.w3.org/2000/svg"
            width="16"
            height="16"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
            strokeLinecap="round"
            strokeLinejoin="round"
          >
            <path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9" />
            <path d="M13.73 21a2 2 0 0 1-3.46 0" />
          </svg>
        </span>
        <span className={styles.whatsNewText}>
          <strong>Knowledge Base Support</strong> — ChromaDB, Neo4j &amp;
          Starburst Galaxy built-in, plus a <strong>custom adapter API</strong>{" "}
          to plug in any backend.
        </span>
        <Link
          to="/docs/next/architecture/memory-management"
          className={styles.whatsNewLink}
        >
          Read More →
        </Link>
      </div>
    </div>
  );
}

/* ─── Hero ──────────────────────────────────────────────────────────────── */

function Hero() {
  const leftRef = useRef(null);
  const titleRef = useRef(null);
  const subtitleRef = useRef(null);
  const buttonsRef = useRef(null);
  const bulletsRef = useRef(null);
  const videoRef = useRef(null);
  const scrollLabelRef = useRef(null);
 
  useLayoutEffect(() => {
    const tl = gsap.timeline({ defaults: { ease: "power3.out" } });
 
    gsap.set(
      [
        titleRef.current,
        subtitleRef.current,
        buttonsRef.current,
        bulletsRef.current,
        videoRef.current,
        scrollLabelRef.current,
      ],
      { opacity: 0, y: 28 }
    );
 
    tl.to(titleRef.current, { opacity: 1, y: 0, duration: 0.85 })
      .to(subtitleRef.current, { opacity: 1, y: 0, duration: 0.6 }, "-=0.5")
      .to(buttonsRef.current, { opacity: 1, y: 0, duration: 0.55 }, "-=0.35")
      .to(bulletsRef.current, { opacity: 1, y: 0, duration: 0.5 }, "-=0.3")
      .to(videoRef.current, { opacity: 1, y: 0, duration: 0.9 }, "-=0.7")
      .to(scrollLabelRef.current, { opacity: 1, y: 0, duration: 0.5 }, "-=0.4");
  }, []);
 
  return (
    <section className={styles.hero}>
      <div className={styles.inner}>
        {/* ── LEFT ───────────────────────────────── */}
        <div ref={leftRef} className={styles.left}>
          <h1 ref={titleRef} className={styles.title}>
            The Secure, Compliant
            <br />
            Runtime for
            <br />
            Enterprise AI{" "}
            <span className={styles.gradientWord}>Agents</span>
          </h1>
 
          <p ref={subtitleRef} className={styles.subtitle}>
            Orchestrate agent workflows, automate compliance, and
            <br className={styles.brDesktop} />
            deploy anywhere with zero vendor lock-in.
          </p>
 
          <div ref={buttonsRef} className={styles.heroButtons}>
            <Link
              className={`button button--primary button--lg ${styles.btnPrimary}`}
              to="/docs"
            >
              <span className={styles.btnIcon}>→</span>
              Get Started
            </Link>
            <button
              type="button"
              className={`button button--secondary button--lg ${styles.btnSecondary}`}
              onClick={() =>
                document
                  .getElementById("agent-skills")
                  ?.scrollIntoView({ behavior: "smooth", block: "start" })
              }
            >
              <span className={styles.btnIconSecondary}>→</span>
              Agent Skills
            </button>
          </div>
 
          <ul ref={bulletsRef} className={styles.bullets}>
            <li>
              <MdCheck className={styles.check} />
              Install in minutes
            </li>
            <li>
              <MdCheck className={styles.check} />
              Zero vendor lock-in
            </li>
            <li>
              <MdCheck className={styles.check} />
              Enterprise-grade observability
            </li>
          </ul>
        </div>
 
        {/* ── RIGHT – particle video ───────────── */}
        <div ref={videoRef} className={styles.right}>
          <video
            className={styles.heroVideo}
            src="/video/hero.mp4"
            autoPlay
            loop
            muted
            playsInline
          />
        </div>

        {/* ── Scroll label ────────────────────── */}
        <div ref={scrollLabelRef} className={styles.scrollLabel} aria-hidden="true">
          <span className={styles.scrollLine} />
          <span className={styles.scrollText}>Scroll down to <strong>Begin</strong></span>
        </div>
      </div>
    </section>
  );
}

/* ─── Frameworks Strip ──────────────────────────────────────────────────── */

function FrameworksStrip() {
  const frameworksRef = useRef(null);
  const labelRef = useRef(null);
  const badgeRef = useRef(null);
  const rowRef = useRef(null);

  const frameworks = [
    {
      name: "Open AI Agents SDK",
      logo: "/img/integrations/chatgpt.png",
      link: "/docs/frameworks/openai",
    },
    {
      name: "LangGraph",
      logo: "/img/integrations/langgraph.png",
      link: "/docs/frameworks/langgraph",
    },
    {
      name: "CrewAI",
      logo: "/img/integrations/crewai.png",
      link: "/docs/frameworks/crewai",
    },
    {
      name: "Google ADK",
      logo: "/img/integrations/googleADK.png",
      link: "/docs/frameworks/google-adk",
    },
    {
      name: "Smolagents",
      logo: "/img/integrations/smolagents.png",
      link: "https://huggingface.co/docs/smolagents/index",
    },
    {
      name: "LiveKit",
      logo: "/img/integrations/livekit.png",
      link: "https://docs.livekit.io/",
    },
  ];

  useEffect(() => {
    gsap.registerPlugin(ScrollTrigger);

    gsap.set([badgeRef.current, labelRef.current], { opacity: 0, y: 16 });
    gsap.set(rowRef.current?.children || [], { opacity: 0, y: 24 });

    const tl = gsap.timeline({
      scrollTrigger: {
        trigger: frameworksRef.current,
        start: "top 85%",
        toggleActions: "play none none reverse",
      },
    });

    tl.to(badgeRef.current, { opacity: 1, y: 0, duration: 0.5, ease: "power2.out" })
      .to(labelRef.current, { opacity: 1, y: 0, duration: 0.5, ease: "power2.out" }, "-=0.3")
      .to(
        rowRef.current?.children || [],
        { opacity: 1, y: 0, duration: 0.4, ease: "power2.out", stagger: 0.07 },
        "-=0.2"
      );

    return undefined;
  }, []);

  return (
    <section ref={frameworksRef} className={styles.frameworksStrip}>
      {/* Top border + gradient glow */}
      <div className={styles.topGlow} />

      <div ref={badgeRef} className={styles.Badge}>
        <span className={styles.badgeStar}>✦</span>
        Integrates Seamlessly
      </div>

      <p ref={labelRef} className={styles.frameworksLabel}>
        Works with your stack. No migration. One adapter line.
      </p>

      <div ref={rowRef} className={styles.frameworksRow}>
        {frameworks.map((framework) => (
          <Link
            key={framework.name}
            to={framework.link}
            className={styles.frameworkItem}
          >
            <img
              src={framework.logo}
              alt={framework.name}
              className={styles.frameworkLogo}
            />
          </Link>
        ))}
      </div>
    </section>
  );
}

/* ─── Affiliations Strip ────────────────────────────────────────────────── */

function AffiliationsStrip() {
  const sectionRef = useRef<HTMLElement>(null);

  useLayoutEffect(() => {
    const section = sectionRef.current;
    if (!section) return;

    const reducedMotion =
      typeof window !== "undefined" &&
      window.matchMedia("(prefers-reduced-motion: reduce)").matches;

    const label = section.querySelector(`.${styles.affiliationsLabel}`);
    const row = section.querySelector(`.${styles.affiliationsRow}`);

    if (!label || !row) return;

    if (reducedMotion) {
      gsap.set([label, row], { opacity: 1, y: 0, scale: 1 });
      return;
    }

    gsap.set([label, row], { opacity: 0, y: 18 });

    const tl = gsap.timeline({
      scrollTrigger: {
        trigger: section,
        start: "top 80%",
        toggleActions: "play none none reverse",
      },
    });

    tl.to(label, {
      opacity: 1,
      y: 0,
      duration: 0.45,
      ease: "power2.out",
    }).to(
      row,
      {
        opacity: 1,
        y: 0,
        duration: 0.5,
        ease: "power2.out",
      },
      "-=0.18",
    );

    return () => {
      tl.scrollTrigger?.kill();
      tl.kill();
    };
  }, []);

  return (
    <section ref={sectionRef} className={styles.affiliationsStrip}>
      <div className="container">
        <p className={styles.affiliationsLabel}>Member of</p>
        <div className={styles.affiliationsRow}>
          <a
            href="https://www.linuxfoundation.org"
            target="_blank"
            rel="noopener noreferrer"
            className={styles.affiliationItem}
          >
            <img
              src="/img/lf_membership.svg"
              alt="Linux Foundation Member"
              className={styles.affiliationLogo}
            />
          </a>
          <span className={styles.affiliationSeparator}>●</span>
          <a
            href="https://aaif.io"
            target="_blank"
            rel="noopener noreferrer"
            className={styles.affiliationItem}
          >
            <img
              src="/img/aaif_membership.svg"
              alt="Agentic AI Foundation Member"
              className={styles.affiliationLogo}
            />
          </a>
        </div>
      </div>
    </section>
  );
}

/* ─── Agent Skills ────────────────────────────────────────────────────── */

const AGENT_SKILLS = [
  {
    icon: MdRocketLaunch,
    name: "ak-init",
    description:
      "Scaffolds a clean, ready-to-build project structure so you can skip the setup and start building straight away. Works with any framework or deployment target.",
    pills: ["Any framework", "Any deployment target", "Guided setup"],
  },
  {
    icon: MdBuild,
    name: "ak-build",
    description:
      "Adds tools, agents, and task handoffs to your project. Your coding assistant understands your framework, so the code it generates actually works.",
    pills: ["Tool integration", "Agent handoffs", "Framework-aware"],
  },
  {
    icon: MdExtension,
    name: "ak-add-capabilities",
    description:
      "Plugs in production-grade features like guardrails, tracing, session memory, and multimodal support without having to build them from scratch.",
    pills: [
      "Guardrails",
      "Tracing",
      "Session memory",
      "MCP support",
      "Multimodal",
    ],
  },
  {
    icon: MdIntegrationInstructions,
    name: "ak-add-integration",
    description:
      "Connects your agent to the messaging platforms your users already rely on, with authentication and message handling taken care of for each one.",
    pills: ["Slack", "WhatsApp", "Messenger", "Instagram", "Telegram", "Gmail"],
  },
  {
    icon: MdCloudUpload,
    name: "ak-cloud-deploy",
    description:
      "Deploys your agent to the cloud with full Terraform configuration included. Pick your platform and it handles the infrastructure, no manual setup needed.",
    pills: [
      "AWS Lambda",
      "ECS",
      "Azure Functions",
      "Container Apps",
      "Full Terraform",
    ],
  },
  {
    icon: MdBugReport,
    name: "ak-test",
    description:
      "Tests your agent across multiple modes including fuzzy, judge, and fallback. When something breaks, a step-by-step debugging playbook helps you fix it fast.",
    pills: [
      "Fuzzy testing",
      "Judge mode",
      "Fallback testing",
      "Debugging playbook",
    ],
  },
] as const;

function AgentSkills() {
  const [activeSkillIndex, setActiveSkillIndex] = useState(0);
  const detailContentRef = useRef<HTMLDivElement>(null);
  const hasAnimatedSkillChangeRef = useRef(false);
  const ActiveIcon = AGENT_SKILLS[activeSkillIndex].icon;

  gsap.registerPlugin(ScrollTrigger, ScrambleTextPlugin);

  const cmd1Ref = useRef<HTMLSpanElement>(null);
  const cmd2Ref = useRef<HTMLSpanElement>(null);
  const cmd3Ref = useRef<HTMLSpanElement>(null);
  const commandsPanelRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const panel = commandsPanelRef.current;
    if (!panel) return;

    const targets = Array.from(
      panel.querySelectorAll(
        `.${styles.agentSkillsCodeComment}, .${styles.agentSkillsCodeArg}`,
      ),
    ) as HTMLElement[];

    targets.forEach((target) => {
      if (!target.dataset.finalText) {
        target.dataset.finalText = target.textContent ?? "";
      }
    });

    const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (reducedMotion) return;

    const playScramble = () => {
      targets.forEach((target, index) => {
        const text = target.dataset.finalText ?? target.textContent ?? "";
        gsap.killTweensOf(target);
        gsap.to(target, {
          scrambleText: {
            text,
            chars: "lowerCase",
            revealDelay: 0.25,
            tweenLength: false,
          },
          duration: 1.6,
          delay: index * 0.18,
          ease: "power2.out",
          overwrite: "auto",
          onComplete: () => {
            target.textContent = text;
          },
        });
      });
    };

    const observer = new IntersectionObserver(
      (entries) => {
        const entry = entries[0];
        if (!entry) return;
        if (entry.isIntersecting) playScramble();
      },
      { threshold: 0.35, rootMargin: "0px 0px -10% 0px" },
    );

    observer.observe(panel);

    const rect = panel.getBoundingClientRect();
    const isVisible = rect.top < window.innerHeight && rect.bottom > 0;
    if (isVisible) playScramble();

    return () => { observer.disconnect(); };
  }, []);

  useLayoutEffect(() => {
    if (!detailContentRef.current) return;

    if (!hasAnimatedSkillChangeRef.current) {
      hasAnimatedSkillChangeRef.current = true;
      return;
    }

    const content = detailContentRef.current;
    const motionTargets = content.querySelectorAll(
      `.${styles.agentSkillsSkillHeader}, .${styles.agentSkillsSkillBody}, .${styles.agentSkillsPill}`,
    );

    gsap.killTweensOf([content, motionTargets]);

    gsap.fromTo(
      content,
      { opacity: 0.55, y: 14, scale: 0.985, filter: "blur(4px)" },
      { opacity: 1, y: 0, scale: 1, filter: "blur(0px)", duration: 0.42, ease: "power3.out" },
    );

    gsap.fromTo(
      Array.from(motionTargets),
      { opacity: 0, y: 10 },
      { opacity: 1, y: 0, duration: 0.32, ease: "power2.out", stagger: 0.04, delay: 0.04 },
    );
  }, [activeSkillIndex]);

  return (
    <section id="agent-skills" className={styles.agentSkillsSection}>
      {/* Top border + gradient glow */}
      <div className={styles.topGlow} />

      <div className="container">
        <div className={styles.agentSkillsContainer}>
          <div className={styles.sectionHeader}>
            <div className={styles.Badge}>
              <span className={styles.badgeStar}>✦</span>
              Developer Experience
            </div>
            <h2 className={styles.sectionTitle}>
              Your coding assistant, supercharged.
            </h2>
          </div>

          <div className={styles.agentSkillsTopicsRow} role="tablist">
            {AGENT_SKILLS.map((skill, idx) => (
              <button
                key={skill.name}
                role="tab"
                aria-selected={activeSkillIndex === idx}
                className={`${styles.agentSkillsTopicButton} ${
                  activeSkillIndex === idx ? styles.agentSkillsTopicActive : ""
                }`}
                onClick={() => setActiveSkillIndex(idx)}
              >
                {skill.name}
              </button>
            ))}
          </div>

          <div className={styles.agentSkillsSplitGrid}>
            {/* Left — IDE-style code panel */}
            <div ref={commandsPanelRef} className={styles.agentSkillsPanel}>
              <div className={styles.agentSkillsIdeHeader}>
                <div className={styles.agentSkillsIdeDots}>
                  <span className={styles.agentSkillsDotRed} />
                  <span className={styles.agentSkillsDotYellow} />
                  <span className={styles.agentSkillsDotGreen} />
                </div>
                <div className={styles.agentSkillsIdeActions}>
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg>
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden><rect x="9" y="9" width="13" height="13" rx="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg>
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden><circle cx="18" cy="5" r="3"/><circle cx="6" cy="12" r="3"/><circle cx="18" cy="19" r="3"/><line x1="8.59" y1="13.51" x2="15.42" y2="17.49"/><line x1="15.41" y1="6.51" x2="8.59" y2="10.49"/></svg>
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden><polyline points="15 3 21 3 21 9"/><polyline points="9 21 3 21 3 15"/><line x1="21" y1="3" x2="14" y2="10"/><line x1="3" y1="21" x2="10" y2="14"/></svg>
                </div>
              </div>

              <div className={styles.agentSkillsIdeBody}>
                <div className={styles.agentSkillsLineNumbers}>
                  {Array.from({ length: 10 }, (_, i) => (
                    <span key={i}>{i + 1}</span>
                  ))}
                </div>
                <div className={styles.agentSkillsCodeBlock}>
                  <div className={styles.agentSkillsCodeComment}>
                    # 1. Install the CLI
                  </div>
                  <div>
                    <span className={styles.agentSkillsCodeCmd}>$</span>{" "}
                    <span ref={cmd1Ref} className={styles.agentSkillsCodeArg}>
                      pip install agentkernel
                    </span>
                  </div>
                  <br />
                  <div className={styles.agentSkillsCodeComment}>
                    # 2. Install skills for your coding assistant
                  </div>
                  <div>
                    <span className={styles.agentSkillsCodeCmd}>$</span>{" "}
                    <span ref={cmd2Ref} className={styles.agentSkillsCodeArg}>
                      ak skill install
                    </span>
                  </div>
                  <div className={styles.agentSkillsCodeComment}>
                    &nbsp;&nbsp;or target a specific assistant:
                  </div>
                  <div>
                    <span className={styles.agentSkillsCodeCmd}>$</span>{" "}
                    <span ref={cmd3Ref} className={styles.agentSkillsCodeArg}>
                      ak skill install --assistant claude
                    </span>
                  </div>
                </div>
              </div>
            </div>

            {/* Right — skill detail panel */}
            <div className={styles.agentSkillsPanel}>
              <div className={styles.agentSkillsSectionLabel}>
                What each skill does
              </div>
              <div className={styles.agentSkillsDetailWrap}>
                <div
                  ref={detailContentRef}
                  className={styles.agentSkillsDetailBox}
                >
                  <div className={styles.agentSkillsSkillHeader}>
                    <ActiveIcon
                      aria-hidden
                      className={styles.agentSkillsSkillIcon}
                    />
                    <p className={styles.agentSkillsSkillName}>
                      {AGENT_SKILLS[activeSkillIndex].name}
                    </p>
                  </div>
                  <p className={styles.agentSkillsSkillBody}>
                    {AGENT_SKILLS[activeSkillIndex].description}
                  </p>
                  <div className={styles.agentSkillsPillRow}>
                    {AGENT_SKILLS[activeSkillIndex].pills.map((pill) => (
                      <span key={pill} className={styles.agentSkillsPill}>
                        {pill}
                      </span>
                    ))}
                  </div>
                </div>
              </div>
            </div>
          </div>

          {/* Bottom row — subtitle left, CTA right */}
          <div className={styles.agentSkillsFooter}>
            <p className={styles.agentSkillsFooterText}>
              Agent Skills works with the tools you already use, like Copilot, Claude, Cursor, or Windsurf, to help you build and ship AI agents faster. No more guesswork, no more broken code suggestions.
            </p>
            <Link
              className={`button button--primary button--md ${styles.btnLinkPrimary} ${styles.agentSkillsCtaLink}`}
              to="/docs"
            >
              Learn more about Agent Skills
              <span className={styles.btnLinkIconPrimary}>→</span>
            </Link>
          </div>
        </div>
      </div>
    </section>
  );
}

/* ─── Deployment ────────────────────────────────────────────────────────── */

function Deployment() {
  const gridRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!gridRef.current) return;

    const cards = gridRef.current.querySelectorAll(`.${styles.cloudCard}`);
    const triggers: ScrollTrigger[] = [];

    gsap.fromTo(
      cards,
      { opacity: 0, y: 40 },
      {
        opacity: 1,
        y: 0,
        duration: 0.7,
        ease: "power3.out",
        stagger: 0.15,
        scrollTrigger: {
          trigger: gridRef.current,
          start: "top 80%",
          once: true,
          onToggle: (self) => triggers.push(self),
        },
      }
    );

    return () => {
      triggers.forEach((t) => t.kill());
    };
  }, []);

  const clouds = [
    {
      icon: <FaAws className={styles.cloudIconSvg} />,
      name: "Amazon AWS",
      description:
        "Serverless or containerized deployments with Terraform modules.",
      modes: ["AWS Lambda (Serverless)", "AWS ECS/Fargate (Containerized)"],
      modules: [
        {
          name: "AWS Serverless",
          url: "https://registry.terraform.io/modules/yaalalabs/ak-serverless/aws",
        },
        {
          name: "AWS Containerized",
          url: "https://registry.terraform.io/modules/yaalalabs/ak-containerized/aws",
        },
      ],
      comingSoon: false,
    },
    {
      icon: <FaMicrosoft className={styles.cloudIconSvg} />,
      name: "Microsoft Azure",
      description:
        "Functions or Container Apps with Cosmos DB session storage.",
      modes: [
        "Azure Functions (Serverless)",
        "Azure Container Apps (Containerized)",
      ],
      modules: [
        {
          name: "Azure Serverless",
          url: "https://registry.terraform.io/modules/yaalalabs/ak-serverless/azurerm",
        },
        {
          name: "Azure Containerized",
          url: "https://registry.terraform.io/modules/yaalalabs/ak-containerized/azurerm",
        },
      ],
      comingSoon: false,
    },
    {
      icon: <SiGooglecloud className={styles.cloudIconSvg} />,
      name: "Google Cloud",
      description:
        "Cloud Run and Cloud Functions deployments — Terraform modules in progress.",
      modes: ["Cloud Run (Containerized)", "Cloud Functions (Containerized)"],
      modules: [],
      comingSoon: true,
    },
  ];

  return (
    <section className={styles.deploySection}>
      {/* Top border + gradient glow */}
      <div className={styles.topGlow} />

      <div className="container">
        <div className={styles.deployHeader}>
          <div className={styles.Badge}>
            <span className={styles.badgeStar}>✦</span>
            Developer Experience
          </div>
          <h2 className={styles.deployTitle}>Deploy Anywhere</h2>
          <p className={styles.deploySubtitle}>
            Run the same agent code on AWS, Azure, or Google Cloud. Zero rewrites.
            <br />
            Production-ready Terraform modules with best practices baked in.
          </p>
        </div>

        <div className={styles.cloudGrid} ref={gridRef}>
          {clouds.map((c, i) => (
            <div key={i} className={styles.cloudCard}>

              {/* Icon + name row */}
              <div className={styles.cloudHeader}>
                <div className={styles.cloudIconWrap}>
                  {c.icon}
                </div>
                <div className={styles.cloudNameRow}>
                  <h3 className={styles.cloudName}>{c.name}</h3>
                  {c.comingSoon && (
                    <span className={styles.cloudComingSoonBadge}>
                      COMING SOON
                    </span>
                  )}
                </div>
              </div>

              {/* Description */}
              <p className={styles.cloudDescription}>{c.description}</p>

              {/* Mode bullets — checkmark style */}
              <ul className={styles.cloudModes}>
                {c.modes.map((m, j) => (
                  <li key={j}>
                    <span className={styles.checkmark}>✓</span>
                    {m}
                  </li>
                ))}
              </ul>

              {/* Terraform links — styled as "Read More" buttons */}
              <div className={styles.cloudModules}>
                {c.modules.length > 0 ? (
                  c.modules.map((m, j) => (
                    <Link
                      key={j}
                      to={m.url}
                      className={styles.terraformLink}
                      target="_blank"
                      rel="noopener noreferrer"
                    >
                      <SiTerraform className={styles.terraformIcon} />
                      <span>{m.name}</span>
                    </Link>
                  ))
                ) : (
                  <button className={styles.readMoreBtn} disabled>
                    Coming Soon
                  </button>
                )}
              </div>

            </div>
          ))}
        </div>
      </div>
    </section>
  );
}

/* ─── Community / CTA ───────────────────────────────────────────────────── */
interface CommunityProps {
  sectionRef?: React.Ref<HTMLElement>;
}

function Community({ sectionRef }: CommunityProps) {
  return (
    <section ref={sectionRef} className={styles.ctaSection}>
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
  );
}

/* ─── Levels ────────────────────────────────────────────────────────────── */

interface Level {
  id: string;
  title: string;
  image: string;
  description: string;
}

interface ScrollTriggerInstance {
  kill: () => void;
}

type AkCompareCellStatus = "positive" | "negative" | "partial";

interface AkCompareCell {
  status: AkCompareCellStatus;
  text?: string;
}

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

function Levels() {
  const sectionRef = useRef<HTMLElement>(null);
  const titleRef = useRef<HTMLHeadingElement>(null);
  const subtitleRef = useRef<HTMLParagraphElement>(null);
  const cardsRef = useRef<HTMLDivElement>(null);
  const contentRef = useRef<HTMLDivElement>(null);
  const [selectedLevel, setSelectedLevel] = useState<string | null>(null);
  const [isPinned, setIsPinned] = useState(true);
  const scrollTriggerRef = useRef<ScrollTriggerInstance | null>(null);
  const history = useHistory();

  const levels: Level[] = [
    {
      id: "01",
      title: "Business Leader",
      image: "/img/business_leader.png",
      description:
        "You run or work in a business / enterprise and want to incorporate AI agentsassistants that actually work into your business workflows without needing to understand the tech.",
    },
    {
      id: "02",
      title: "Developer",
      image: "/img/developer.png",
      description:
        "You buildwrite software but haven't built AI agents yet. You want to ship something robust and real without learning a new stack from scratch.",
    },
    {
      id: "03",
      title: "AI Engineer",
      image: "/img/ai.png",
      description:
        "You already work with LLMs and agentic frameworks. You need a production-grade AI agent execution framework runtime that doesn't get in your way.",
    },
  ];

  const handleLevelSelect = (levelId: string) => {
    // Navigate to the appropriate level page
    const levelPages: { [key: string]: string } = {
      "01": "/business-leader",
      "02": "/developer",
      "03": "/ai-engineer",
    };

    if (levelPages[levelId]) {
      history.push(levelPages[levelId]);
    }
  };

  useEffect(() => {
    const handleWheel = (e: WheelEvent) => {
      if (!isPinned) return;
      const rect = sectionRef.current?.getBoundingClientRect();
      if (rect && rect.top <= 0 && rect.bottom >= window.innerHeight) {
        if (e.deltaY > 0) {
          e.preventDefault();
        }
      }
    };

    const handleTouchMove = (e: TouchEvent) => {
      if (!isPinned) return;
      const rect = sectionRef.current?.getBoundingClientRect();
      if (rect && rect.top <= 0 && rect.bottom >= window.innerHeight) {
        e.preventDefault();
      }
    };

    const handleKeyDown = (e: KeyboardEvent) => {
      if (!isPinned) return;
      const rect = sectionRef.current?.getBoundingClientRect();
      if (rect && rect.top <= 0 && rect.bottom >= window.innerHeight) {
        if (e.key === "ArrowDown" || e.key === " " || e.key === "PageDown") {
          e.preventDefault();
        }
      }
    };

    const levelCards = Array.from(
      cardsRef.current?.querySelectorAll(`.${styles.levelCard}`) || [],
    ) as HTMLElement[];

    if (!selectedLevel) {
      gsap.registerPlugin(ScrollTrigger);

      const isDesktop = window.innerWidth > 996;
      const middleCard = levelCards[1];

      gsap.fromTo(
        [titleRef.current, subtitleRef.current, cardsRef.current],
        { opacity: 0, y: 30 },
        {
          opacity: 1,
          y: 0,
          duration: 1,
          ease: "power2.out",
          scrollTrigger: {
            trigger: sectionRef.current,
            start: "top 60%",
            toggleActions: "play none none reverse",
          },
        },
      );

      if (isDesktop) {
        gsap.set(sectionRef.current, { height: "100vh" });
        ScrollTrigger.refresh();

        if (levelCards.length === 3) {
          gsap.set(levelCards, {
            opacity: 0,
            y: 28,
            scale: 0.94,
            transformOrigin: "center center",
          });

          gsap.set(middleCard, {
            opacity: 1,
            y: 0,
            scale: 1.08,
            zIndex: 3,
          });

          gsap.set(levelCards[0], {
            x: 110,
            zIndex: 2,
          });

          gsap.set(levelCards[2], {
            x: -110,
            zIndex: 2,
          });
        }

        if (levelCards.length === 3) {
          const tl = gsap.timeline({ paused: true });

          tl.to(
            levelCards[0],
            {
              x: 0,
              y: 0,
              opacity: 1,
              scale: 1,
              duration: 0.8,
              ease: "power2.out",
            },
            0,
          )
            .to(
              middleCard,
              {
                y: 0,
                scale: 1,
                duration: 0.8,
                ease: "power2.out",
              },
              0,
            )
            .to(
              levelCards[2],
              {
                x: 0,
                y: 0,
                opacity: 1,
                scale: 1,
                duration: 0.8,
                ease: "power2.out",
              },
              0,
            );

          const scrollTrigger = ScrollTrigger.create({
            trigger: sectionRef.current,
            start: "top top",
            end: "+=100%",
            pin: true,
            pinSpacing: true,
            onEnter: () => tl.restart(),
            onEnterBack: () => tl.restart(),
          });

          scrollTriggerRef.current = scrollTrigger as ScrollTriggerInstance | null;

          window.addEventListener("wheel", handleWheel, { passive: false });
          window.addEventListener("touchmove", handleTouchMove, {
            passive: false,
          });
          window.addEventListener("keydown", handleKeyDown);
        }
      }
    }

    return () => {
      window.removeEventListener("wheel", handleWheel);
      window.removeEventListener("touchmove", handleTouchMove);
      window.removeEventListener("keydown", handleKeyDown);
      if (scrollTriggerRef.current) {
        scrollTriggerRef.current.kill();
      }
    };
  }, [isPinned, selectedLevel]);

  useEffect(() => {
    if (selectedLevel) {
      gsap.registerPlugin(ScrollTrigger);
      const levelCards = Array.from(
        cardsRef.current?.querySelectorAll(`.${styles.levelCard}`) || [],
      ) as HTMLElement[];
      const selectedCard = cardsRef.current?.querySelector(
        `[data-level="${selectedLevel}"]`,
      ) as HTMLElement | null;

      if (levelCards.length) {
        gsap.set(levelCards, { clearProps: "transform,opacity" });
      }

      if (selectedCard) {
        gsap.set(selectedCard, {
          opacity: 1,
          scale: 1.05,
          zIndex: 4,
        });
      }

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

      // Animate architecture layers - Slide from left
      const layers =
        contentRef.current?.querySelectorAll(
          `.${styles.architectureLayerGroup}`,
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

      // Animate capability/feature cards - Staggered fade and scale
      const capCards =
        contentRef.current?.querySelectorAll(
          `.${styles.capabilityCard}, .${styles.devFeatureCard}, .${styles.blValueCard}`,
        ) || [];
      capCards.forEach((card, idx) => {
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

      // Animate BusinessLeaderScenarios tabs
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

      // Animate AI Engineer comparison section
      const akStandOutSection = contentRef.current?.querySelector(
        `.${styles.akStandOutSection}`,
      );
      if (akStandOutSection) {
        const standOutLabel = akStandOutSection.querySelector(
          `.${styles.devStepLabel}`,
        );
        const standOutTitle = akStandOutSection.querySelector(
          `.${styles.devTitle}`,
        );
        const comparePanel = akStandOutSection.querySelector(
          `.${styles.akComparePanel}`,
        );
        const compareFooter = akStandOutSection.querySelector(
          `.${styles.akCompareFooter}`,
        );
        const compareTableHead = akStandOutSection.querySelector(
          `.${styles.akCompareTable} thead tr`,
        );
        const compareRows = akStandOutSection.querySelectorAll(
          `.${styles.akCompareTable} tbody tr`,
        );
        const compareMobileCards = akStandOutSection.querySelectorAll(
          `.${styles.akCompareMobileCard}`,
        );
        const isCompareMobile = window.matchMedia("(max-width: 640px)").matches;

        if (standOutLabel && standOutTitle) {
          gsap.fromTo(
            [standOutLabel, standOutTitle],
            { opacity: 0, y: 30 },
            {
              opacity: 1,
              y: 0,
              duration: 1,
              ease: "power2.out",
              stagger: 0.1,
              scrollTrigger: {
                trigger: akStandOutSection,
                start: "top 82%",
                toggleActions: "play none none reverse",
              },
            },
          );
        }

        if (comparePanel) {
          gsap.fromTo(
            comparePanel,
            { opacity: 0, scale: 0.98 },
            {
              opacity: 1,
              scale: 1,
              duration: 1.1,
              ease: "power2.out",
              scrollTrigger: {
                trigger: comparePanel,
                start: "top 85%",
                toggleActions: "play none none reverse",
              },
            },
          );
        }

        if (!isCompareMobile && comparePanel && compareRows.length > 0) {
          const tableRevealTargets = compareTableHead
            ? [compareTableHead, ...compareRows]
            : [...compareRows];
          gsap.set(tableRevealTargets, { opacity: 0 });

          const compareTl = gsap.timeline({
            scrollTrigger: {
              trigger: comparePanel,
              start: "top 80%",
              toggleActions: "play none none reverse",
            },
          });

          if (compareTableHead) {
            compareTl.to(compareTableHead, {
              opacity: 1,
              duration: 0.6,
              ease: "power2.out",
            });
          }

          compareTl.to(
            compareRows,
            {
              opacity: 1,
              duration: 0.55,
              ease: "power2.out",
              stagger: 0.06,
            },
            compareTableHead ? "-=0.2" : 0,
          );
        }

        if (isCompareMobile) {
          compareMobileCards.forEach((card, idx) => {
            gsap.fromTo(
              card,
              { opacity: 0, y: 25, scale: 0.96 },
              {
                opacity: 1,
                y: 0,
                scale: 1,
                duration: 0.85,
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
        }

        if (compareFooter) {
          gsap.fromTo(
            compareFooter,
            { opacity: 0, y: 20 },
            {
              opacity: 1,
              y: 0,
              duration: 0.9,
              ease: "power2.out",
              scrollTrigger: {
                trigger: compareFooter,
                start: "top 90%",
                toggleActions: "play none none reverse",
              },
            },
          );
        }

      }

      // Animate AI Engineer build flow section
      const aiBuildSection = contentRef.current?.querySelector(
        `.${styles.aiEngineerBuildSection}`,
      );
      if (aiBuildSection) {
        const buildLabel = aiBuildSection.querySelector(
          `.${styles.devStepLabel}`,
        );
        const buildTitle = aiBuildSection.querySelector(`.${styles.devTitle}`);
        if (buildLabel && buildTitle) {
          gsap.fromTo(
            [buildLabel, buildTitle],
            { opacity: 0, y: 30 },
            {
              opacity: 1,
              y: 0,
              duration: 1,
              ease: "power2.out",
              stagger: 0.1,
              scrollTrigger: {
                trigger: aiBuildSection,
                start: "top 82%",
                toggleActions: "play none none reverse",
              },
            },
          );
        }

        const buildSubsections = aiBuildSection.querySelectorAll(
          `.${styles.aiBuildSubsection}`,
        );
        buildSubsections.forEach((subsection) => {
          // Animate title/body only — opacity/transform on the subsection breaks
          // backdrop-filter on the diagram panel inside it.
          const buildCopy = subsection.querySelectorAll(
            `.${styles.aiBuildSubTitle}, .${styles.aiBuildSubBody}`,
          );
          if (buildCopy.length > 0) {
            gsap.fromTo(
              buildCopy,
              { opacity: 0, y: 28 },
              {
                opacity: 1,
                y: 0,
                duration: 0.95,
                ease: "power2.out",
                stagger: 0.08,
                scrollTrigger: {
                  trigger: subsection,
                  start: "top 85%",
                  toggleActions: "play none none reverse",
                },
                clearProps: "transform",
              },
            );
          }
        });
      }

      // Animate developer framework section
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
              start: "top 80%",
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
          `.${styles.contentCard}, .${styles.capabilityCard}, .${styles.devFeatureCard}, .${styles.blValueCard}`,
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
    }

    return () => {
      if (scrollTriggerRef.current) {
        scrollTriggerRef.current.kill();
        scrollTriggerRef.current = null;
      }
    };
  }, [selectedLevel, styles]);

  return (
    <section
      ref={sectionRef}
      className={`${styles.levelsSection} ${!selectedLevel ? styles.levelsPinned : ""}`}
    >
      <StepTimeline levelId={selectedLevel} contentRef={contentRef} />
      <div className="container">
        <div className={styles.levelsContainer}>
          <p ref={subtitleRef} className={styles.levelsSubtitle}>
            Which path describes you the best
          </p>

          <h2 ref={titleRef} className={styles.levelsTitle}>
            Agent Kernel is designed to adapt to your level of expertise
          </h2>

          <div ref={cardsRef} className={styles.levelsGrid}>
            {levels.map((level) => (
              <div
                key={level.id}
                data-level={level.id}
                onClick={() => handleLevelSelect(level.id)}
                className={`${styles.levelCard} ${selectedLevel === level.id ? styles.levelCardSelected : ""}`}
              >
                <div className={styles.levelImage}>
                  <img src={level.image} alt={level.title} />
                </div>

                <h3 className={styles.levelCardTitle}>{level.title}</h3>
                <p className={styles.levelCardDescription}>
                  {level.description}
                </p>
              </div>
            ))}
          </div>

          <div className={styles.levelsHint}>
            Select a path that best describes you to continue
          </div>
        </div>
      </div>
    </section>
  );
}

/* ─── Page Export ───────────────────────────────────────────────────────── */

export default function Home() {
  const { siteConfig } = useDocusaurusContext();
  const backgroundRef = useRef<{
    triggerScatterOut: () => void;
    triggerScatterIn: () => void;
    triggerReverseScatterIn: () => void;
    triggerScatterFloat: () => void;
    triggerFloatReform: () => void;
  }>(null);
  const levelsRef = useRef<HTMLDivElement>(null);
  const communityRef = useRef<HTMLElement>(null);
  const levelsObserverStateRef = useRef<boolean>(false);
  const communityObserverStateRef = useRef<boolean>(false);

  useEffect(() => {
    if (!backgroundRef.current || !levelsRef.current) return;

    // Trigger the scatter-out animation when the Levels section comes into view.
    const observer = new IntersectionObserver(
      ([entry]) => {
        if (entry.isIntersecting && !levelsObserverStateRef.current) {
          levelsObserverStateRef.current = true;
          backgroundRef.current?.triggerScatterOut();
        } else if (!entry.isIntersecting && levelsObserverStateRef.current) {
          levelsObserverStateRef.current = false;
          backgroundRef.current?.triggerScatterIn();
        }
      },
      { threshold: 0.0 },
    );

    observer.observe(levelsRef.current);

    return () => {
      observer.disconnect();
    };
  }, []);

  useEffect(() => {
    if (!backgroundRef.current || !communityRef.current) return;

    // Trigger the reverse scatter-in animation when the Community section comes into view.
    const observer = new IntersectionObserver(
      ([entry]) => {
        if (entry.isIntersecting && !communityObserverStateRef.current) {
          communityObserverStateRef.current = true;
          backgroundRef.current?.triggerReverseScatterIn();
        } else if (!entry.isIntersecting && communityObserverStateRef.current) {
          communityObserverStateRef.current = false;
          backgroundRef.current?.triggerScatterIn();
        }
      },
      { threshold: 0.4 },
    );

    observer.observe(communityRef.current);

    return () => {
      observer.disconnect();
    };
  }, []);

  return (
    <Layout
      title={`${siteConfig.title} — ${siteConfig.tagline}`}
      description="Agent Kernel is an open-source, framework-agnostic, multi-cloud runtime for production AI agents. Build, test, and deploy with OpenAI, LangGraph, CrewAI, or Google ADK to AWS or Azure — in days, not months."
    >
      {/* <PlantParticlesBackground ref={backgroundRef} /> */}
      {/* <WhatsNewBanner /> */}
      <Hero />
      <main>
        <FrameworksStrip />
        <div ref={levelsRef}>
          <Levels />
        </div>
        <AgentSkills />
        <Deployment />
        <Community sectionRef={communityRef} />
      </main>
    </Layout>
  );
}
