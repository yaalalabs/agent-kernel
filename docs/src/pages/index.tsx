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
        toggleActions: "play none none none",
        once: true,
      },
    });

    tl.to(badgeRef.current, { opacity: 1, y: 0, duration: 0.5, ease: "power2.out" })
      .to(labelRef.current, { opacity: 1, y: 0, duration: 0.5, ease: "power2.out" }, "-=0.3")
      .to(
        rowRef.current?.children || [],
        { opacity: 1, y: 0, duration: 0.4, ease: "power2.out", stagger: 0.07 },
        "-=0.2"
      );

    return () => {
      tl.kill();
      if (tl.scrollTrigger) {
        tl.scrollTrigger.kill();
      }
    };
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
        once: true,
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
  bullets: string[];
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
  const stickyRef = useRef<HTMLDivElement>(null);
  const titleRef = useRef<HTMLHeadingElement>(null);
  const subtitleRef = useRef<HTMLParagraphElement>(null);
  const badgeRef = useRef<HTMLDivElement>(null);
  const cardsWrapRef = useRef<HTMLDivElement>(null);
  const history = useHistory();
 
  const levels: Level[] = [
    {
      id: "01",
      title: "Business Leader",
      image: "/img/business_leader.png",
      description:
        "Scaffold production-ready agents in minutes using the frameworks and languages you already know. Ship faster without learning an entirely new development stack.",
      bullets: [
        "Zero-config CLI with guided project setup",
        "Seamless integration with your existing CI pipelines",
        "Built-in retry and fallback routing logic",
      ],
    },
    {
      id: "02",
      title: "Developer",
      image: "/img/developer.png",
      description:
        "Scaffold production-ready agents in minutes using the frameworks and languages you already know. Ship faster without learning an entirely new development stack.",
      bullets: [
        "Zero-config CLI with guided project setup",
        "Seamless integration with your existing CI pipelines",
        "Built-in retry and fallback routing logic",
      ],
    },
    {
      id: "03",
      title: "AI Engineer",
      image: "/img/ai.png",
      description:
        "Scaffold production-ready agents in minutes using the frameworks and languages you already know. Ship faster without learning an entirely new development stack.",
      bullets: [
        "Zero-config CLI with guided project setup",
        "Seamless integration with your existing CI pipelines",
        "Built-in retry and fallback routing logic",
      ],
    },
  ];
 
  const handleLevelSelect = (levelId: string) => {
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
    gsap.registerPlugin(ScrollTrigger);
 
    const section = sectionRef.current;
    const sticky = stickyRef.current;
    const cardEls = cardsWrapRef.current?.querySelectorAll<HTMLElement>(
      `.${styles.levelWindowCard}`
    );
 
    if (!section || !sticky || !cardEls || cardEls.length === 0) return;
 
    // Set all cards invisible initially except the first
    gsap.set(Array.from(cardEls), { autoAlpha: 0, y: 40 });
    gsap.set(cardEls[0], { autoAlpha: 1, y: 0 });
 
    // Header fade in
    gsap.fromTo(
      [badgeRef.current, titleRef.current, subtitleRef.current],
      { opacity: 0, y: 20 },
      {
        opacity: 1,
        y: 0,
        duration: 0.8,
        stagger: 0.1,
        ease: "power3.out",
        scrollTrigger: {
          trigger: section,
          start: "top 80%",
          toggleActions: "play none none none",
        },
      }
    );
 
    // Pin the section; each scroll step reveals the next card
    const STEP = window.innerHeight * 0.6;
    const totalScroll = (levels.length - 1) * STEP;
 
    const pin = ScrollTrigger.create({
      trigger: section,
      start: "top top",
      end: `+=${totalScroll}`,
      pin: sticky,
      pinSpacing: true,
      anticipatePin: 1,
      onUpdate: (self) => {
        const progress = self.progress;
        const totalCards = cardEls.length;
        const floatIdx = progress * (totalCards - 1);
 
        cardEls.forEach((card, i) => {
          if (i === 0) {
            const opacity = i < floatIdx ? Math.max(0, 1 - (floatIdx - i)) : 1;
            gsap.set(card, {
              autoAlpha: opacity,
              y: i < floatIdx ? -20 * (floatIdx - i) : 0,
            });
          } else {
            const fadeIn = Math.min(1, Math.max(0, (floatIdx - (i - 1)) / 0.5));
            const fadeOut =
              i < totalCards - 1
                ? Math.max(0, 1 - Math.max(0, (floatIdx - i) / 0.5))
                : 1;
            const opacity = fadeIn * fadeOut;
            const yOffset = 40 * (1 - fadeIn);
            gsap.set(card, { autoAlpha: opacity, y: yOffset });
          }
        });
      },
    });
 
    return () => {
      pin.kill();
      ScrollTrigger.getAll().forEach((st) => {
        if (st.vars.trigger === section) st.kill();
      });
    };
  }, []);
 
  return (
    <section
      ref={sectionRef}
      className={styles.levelsSection}
      style={{ position: "relative", isolation: "isolate", overflow: "hidden" }}
    >
      {/* Sticky container — this gets pinned */}
      <div
        ref={stickyRef}
        className={styles.levelsStickyInner}
        style={{ position: "relative", zIndex: 1, overflow: "hidden" }}
      >
        {/* Background video */}
        <video
          autoPlay
          muted
          loop
          playsInline
          preload="none"
          className={styles.levelsSectionVideo}
          style={{
            position: "absolute",
            inset: 0,
            width: "100%",
            height: "100%",
            objectFit: "cover",
            zIndex: 0,
            opacity: 0.6,
            pointerEvents: "none",
            transform: "scale(1.2)",
            transformOrigin: "center center",
          }}
        >
          <source src="/video/path-bg.mp4" type="video/mp4" />
        </video>
 
        {/* Header */}
        <div className={styles.levelsFrameContainer}>
          <div className={styles.levelsHeader}>
            <div ref={badgeRef} className={styles.levelsPathBadge}>
              <span className={styles.levelsPathBadgePlus}>+</span> Built for Everyone
            </div>
            <h2 ref={titleRef} className={styles.levelsTitle}>
              Choose Your Path to Production
            </h2>
            <p ref={subtitleRef} className={styles.levelsSubtitle}>
              Select the role that fits you
            </p>
          </div>
  
          {/* Cards stack */}
          <div ref={cardsWrapRef} className={styles.levelsWindowStack}>
            {levels.map((level) => (
              <div key={level.id} className={styles.levelWindowCard}>
                {/* macOS window chrome */}
                <div className={styles.levelWindowChrome}>
                  <div className={styles.levelWindowDots}>
                    <span className={`${styles.levelWindowDot} ${styles.dotRed}`} />
                    <span className={`${styles.levelWindowDot} ${styles.dotYellow}`} />
                    <span className={`${styles.levelWindowDot} ${styles.dotGreen}`} />
                  </div>
                  <div className={styles.levelWindowActions}>
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                      <rect x="3" y="3" width="18" height="18" rx="2" />
                      <path d="M9 3v18" />
                    </svg>
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                      <circle cx="11" cy="11" r="8" />
                      <path d="m21 21-4.35-4.35" />
                    </svg>
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                      <polyline points="15 3 21 3 21 9" />
                      <polyline points="9 21 3 21 3 15" />
                      <line x1="21" y1="3" x2="14" y2="10" />
                      <line x1="3" y1="21" x2="10" y2="14" />
                    </svg>
                  </div>
                </div>
  
                {/* Card body */}
                <div className={styles.levelWindowBody}>
                  {/* Left: image area */}
                  <div className={styles.levelWindowImageArea}>
                    <img
                      src={level.image}
                      alt={level.title}
                      className={styles.levelWindowImage}
                    />
                  </div>
  
                  {/* Right: content */}
                  <div className={styles.levelWindowContent}>
                    <h3 className={styles.levelWindowTitle}>{level.title}</h3>
                    <p className={styles.levelWindowDescription}>{level.description}</p>
                    <ul className={styles.levelWindowBullets}>
                      {level.bullets.map((bullet, i) => (
                        <li key={i} className={styles.levelWindowBulletItem}>
                          <span className={styles.levelWindowBulletCheck}>✓</span>
                          {bullet}
                        </li>
                      ))}
                    </ul>
                    <button
                      className={styles.levelWindowReadMore}
                      onClick={() => handleLevelSelect(level.id)}
                    >
                      Read More
                    </button>
                  </div>
                </div>
              </div>
            ))}
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
