import SectionHeader from '@site/src/components/ui/SectionHeader';
import { CapabilityRail, ClosingPanel, CompatibilityMatrix, TrustMarks } from '@site/src/components/HomeSections';
import { PersonaArt, type PersonaKind } from '@site/src/components/BrandArt';
import OakMark from '@site/src/components/OakMark';
import React, { useRef, useEffect, useState } from "react";
import Link from "@docusaurus/Link";
import useDocusaurusContext from "@docusaurus/useDocusaurusContext";
import Layout from "@theme/Layout";
import styles from "./index.module.css";
import gsap from "gsap";
import { ScrambleTextPlugin } from "gsap/dist/ScrambleTextPlugin";
import { ScrollTrigger } from "gsap/dist/ScrollTrigger";
import { StepTimeline } from "../components/StepTimeline";
import PlantParticlesBackground from "../components/PlantParticlesBackground";
import FAQ from "../components/FAQ";
import ArchitectureOverview from "../components/ArchitectureOverview";
import {
  MdCheck,
  MdContentCopy,
  MdNorthEast,
} from "react-icons/md";
import {
  FaAws,
  FaMicrosoft,
} from "react-icons/fa";
import { SiTerraform, SiGooglecloud, SiKubernetes, SiHelm } from "react-icons/si";

/* ─── What's New Banner ─────────────────────────────────────────────────── */

function WhatsNewBanner() {
  const bannerRef = useRef<HTMLDivElement>(null);
  const iconRef = useRef<HTMLSpanElement>(null);
  const textRef = useRef<HTMLSpanElement>(null);
  const linkRef = useRef<HTMLAnchorElement>(null);

  useEffect(() => {
    gsap.registerPlugin(ScrollTrigger);

    const tl = gsap.timeline({
      scrollTrigger: {
        trigger: bannerRef.current,
        start: "top 90%",
        toggleActions: "play none none none",
      },
    });

    tl.fromTo(
      bannerRef.current,
      { autoAlpha: 0, y: -16 },
      { autoAlpha: 1, y: 0, duration: 0.5, ease: "power3.out" }
    ).fromTo(
      [iconRef.current, textRef.current, linkRef.current],
      { autoAlpha: 0, y: 8 },
      { autoAlpha: 1, y: 0, duration: 0.4, stagger: 0.08, ease: "power2.out" },
      "-=0.25"
    );

    return () => {
      tl.kill();
    };
  }, []);

  return (
    <div ref={bannerRef} className={styles.whatsNewBanner}>
      <div className={styles.whatsNewInner}>
        <span ref={iconRef} className={styles.whatsNewIconWrap}>
          <svg
            xmlns="http://www.w3.org/2000/svg"
            width="16"
            height="16"
            viewBox="0 0 24 24"
            fill="currentColor"
            stroke="currentColor"
            strokeWidth="2"
            strokeLinecap="round"
            strokeLinejoin="round"
          >
            <path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9" />
            <path d="M13.73 21a2 2 0 0 1-3.46 0" />
          </svg>
        </span>
        <span ref={textRef} className={styles.whatsNewText}>
          <strong>Fetch spans back for evaluation</strong> - read agent, LLM
          and tool spans back from Langfuse, Logfire, OpenLLMetry or
          CloudWatch with one filter, to grade production traffic.
        </span>
        <Link
          to="/docs/advanced/traceability#fetching-spans-back"
          className={styles.whatsNewLink}
          ref={linkRef}
        >
          Read More →
        </Link>
      </div>
    </div>
  );
}

/* ─── Hero ──────────────────────────────────────────────────────────────── */

function Hero() {
  const installCommand = "pip install agentkernel";
  const [copied, setCopied] = useState(false);

  const handleCopy = async () => {
    if (typeof navigator === "undefined" || !navigator.clipboard) {
      return;
    }
    try {
      await navigator.clipboard.writeText(installCommand);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1800);
    } catch {
      // Clipboard may be unavailable due to permissions or non-secure context.
    }
  };

  return (
    <section className={styles.homeHero}>
      <div className={`ak-container ${styles.homeHeroGrid}`}>
        <div className={styles.homeHeroCopy}>
          <div className={styles.homeHeroHeading}>
            <p className="ak-label">Open-source agent runtime</p>
            <h1 className="ak-display">
              The operating system for enterprise{" "}
              <span className="ak-accent-text">AI agents</span>
            </h1>
            <p className="ak-lead">
              Open Agent Kernel (OAK) is the open-source runtime for scalable, compliant
              agents. Build in the framework you already use and run on any cloud.
            </p>
          </div>

          <div className={styles.homeHeroActions}>
            <Link className="ak-btn ak-btn--primary" to="/docs/quick-start">
              Quick start
            </Link>
            <Link
              className="ak-btn ak-btn--secondary"
              to="https://github.com/yaalalabs/agent-kernel"
              target="_blank"
              rel="noopener noreferrer"
            >
              View on GitHub
            </Link>
          </div>

          <div className={styles.homeHeroInstall}>
            <code className={styles.homeHeroCommand}>
              <span className={styles.homeHeroPrompt} aria-hidden="true">$</span>
              {installCommand}
            </code>
            <button
              type="button"
              className={styles.homeHeroCopyButton}
              onClick={handleCopy}
              aria-label="Copy install command"
              title={copied ? "Copied" : "Copy command"}
            >
              {copied ? <MdCheck aria-hidden="true" /> : <MdContentCopy aria-hidden="true" />}
            </button>
          </div>

          {/* The id keeps old #agent-skills links landing here. */}
          <p id="agent-skills" className={`ak-small ${styles.homeHeroNote}`}>
            Using a coding assistant?{" "}
            <Link to="/docs/agent-skills" className="ak-link">
              Install the OAK agent skills
            </Link>
          </p>
        </div>

        <div className={styles.homeHeroArt}>
          <OakMark variant="hero" />
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
          icon: <SiTerraform className={styles.terraformIcon} />,
          name: "AWS Serverless",
          url: "https://registry.terraform.io/modules/yaalalabs/ak-serverless/aws",
        },
        {
          icon: <SiTerraform className={styles.terraformIcon} />,
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
          icon: <SiTerraform className={styles.terraformIcon} />,
          name: "Azure Serverless",
          url: "https://registry.terraform.io/modules/yaalalabs/ak-serverless/azurerm",
        },
        {
          icon: <SiTerraform className={styles.terraformIcon} />,
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
        "Cloud Run serverless or containerized deployments with Firestore session storage.",
      modes: [
        "Cloud Run (Serverless)",
        "Cloud Run (Containerized)",
      ],
      modules: [
        {
          icon: <SiTerraform className={styles.terraformIcon} />,
          name: "GCP Serverless",
          url: "https://registry.terraform.io/modules/yaalalabs/ak-serverless/google",
        },
        {
          icon: <SiTerraform className={styles.terraformIcon} />,
          name: "GCP Containerized",
          url: "https://registry.terraform.io/modules/yaalalabs/ak-containerized/google",
        },
      ],
      comingSoon: false,
    },
    {
      icon: <SiKubernetes className={styles.cloudIconSvg} />,
      name: "On-Prem Kubernetes",
      description:
        "Official Helm chart for any Kubernetes cluster",
      modes: [
        "Bare Metal / Self-Hosted Cluster",
        "AWS EKS (Pod Identity, SQS / NATS / Kafka)",
        "KEDA autoscaling on queue depth",
        "Air-gapped installs (mirrored images)",
      ],
      modules: [
        {
          icon: <SiHelm className={styles.terraformIcon} />,
          name: "Helm Chart",
          url: "https://github.com/yaalalabs/agent-kernel/pkgs/container/charts%2Fagent-kernel",
        },
      ],
      comingSoon: false,
    },
  ];

  return (
    <section className={styles.deploySection}>
      <div className="ak-container">
        <SectionHeader
          index="04"
          label="Deployment"
          title="Deploy anywhere"
          lead="Run the same agent code on AWS, Azure, GCP or your own Kubernetes cluster. Terraform modules and a Helm chart are included."
        />

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
                    <MdCheck className={styles.checkmark} />
                    {m}
                  </li>
                ))}
              </ul>

              {/* Terraform module / Helm chart links, styled as "Read More" buttons */}
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
                      {m.icon}
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

/* ─── Levels ────────────────────────────────────────────────────────────── */

interface Level {
  id: string;
  title: string;
  art: PersonaKind;
  description: string;
  accent: string;
  tag: string;
  expertise: number;
}

function Levels() {
  const sectionRef = useRef<HTMLElement>(null);
  const titleRef = useRef<HTMLHeadingElement>(null);
  const subtitleRef = useRef<HTMLParagraphElement>(null);
  const badgeRef = useRef<HTMLDivElement>(null);
  const cardsWrapRef = useRef<HTMLDivElement>(null);
  const particleCanvasRef = useRef<HTMLCanvasElement>(null);

  const levels: Level[] = [
    {
      id: "01",
      title: "Business Leader",
      art: "business",
      description:
        "You run or work in a business/enterprise and want to incorporate AI agents that actually work into your business workflows without needing to handle the complexities of the tech.",
      accent: "var(--ak-primary)",
      tag: "No code required",
      expertise: 1,
    },
    {
      id: "02",
      title: "Developer",
      art: "developer",
      description:
        "You build software but haven't built AI agents yet. You want to ship something robust and real without learning a new stack from scratch.",
      accent: "var(--ak-primary)",
      tag: "Some coding",
      expertise: 2,
    },
    {
      id: "03",
      title: "AI Engineer",
      art: "engineer",
      description:
        "You already work with LLMs and agentic frameworks. You need a production-grade AI agent execution framework that doesn't get in your way.",
      accent: "var(--ak-primary)",
      tag: "Deep tech",
      expertise: 3,
    },
  ];

  const levelPages: { [key: string]: string } = {
    "01": "/business-leader",
    "02": "/developer",
    "03": "/ai-engineer",
  };

  useEffect(() => {
    gsap.registerPlugin(ScrollTrigger);

    const section = sectionRef.current;
    const cards = cardsWrapRef.current?.children;

    if (!section || !cards || cards.length === 0) return;

    const tl = gsap.timeline({
      scrollTrigger: {
        trigger: section,
        start: "top 80%",
        toggleActions: "play none none none",
        once: true,
      },
    });

    tl.fromTo(
      [badgeRef.current],
      { opacity: 0, y: 20 },
      {
        opacity: 1,
        y: 0,
        duration: 0.6,
        stagger: 0.1,
        ease: "power3.out",
      }
    );

    tl.fromTo(
      Array.from(cards),
      { opacity: 0, y: 30 },
      {
        opacity: 1,
        y: 0,
        duration: 0.6,
        stagger: 0.12,
        ease: "power3.out",
      },
      "-=0.4"
    );

    return () => {
      tl.kill();
      if (tl.scrollTrigger) {
        tl.scrollTrigger.kill();
      }
    };
  }, []);

  /* ── Cosmic waves background ── */
  useEffect(() => {
    const canvas = particleCanvasRef.current;
    const section = sectionRef.current;
    if (!canvas || !section) return;
    if (
      typeof window !== "undefined" &&
      window.matchMedia("(prefers-reduced-motion: reduce)").matches
    ) {
      return;
    }

    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    let dpr = Math.min(window.devicePixelRatio || 1, 2);
    let width = 0;
    let height = 0;
    let rafId = 0;
    let running = false;
    let t = 0;

    // Layered cosmic wave bands (color, vertical anchor %, amplitude, wavelength, speed)
    const waves = [
      { color: "0,221,255", anchor: 0.62, amp: 34, len: 0.0042, speed: 0.0006, alpha: 0.16 },
      { color: "167,139,250", anchor: 0.7, amp: 46, len: 0.0031, speed: 0.00045, alpha: 0.16 },
      { color: "255,181,71", anchor: 0.8, amp: 30, len: 0.0052, speed: 0.0008, alpha: 0.11 },
      { color: "56,189,248", anchor: 0.88, amp: 56, len: 0.0026, speed: 0.00035, alpha: 0.13 },
    ];

    const resize = () => {
      const rect = section.getBoundingClientRect();
      width = rect.width;
      height = rect.height;
      dpr = Math.min(window.devicePixelRatio || 1, 2);
      canvas.width = Math.floor(width * dpr);
      canvas.height = Math.floor(height * dpr);
      canvas.style.width = `${width}px`;
      canvas.style.height = `${height}px`;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    };

    const drawWave = (w: (typeof waves)[number]) => {
      const baseY = height * w.anchor;
      ctx.beginPath();
      ctx.moveTo(0, height);
      ctx.lineTo(0, baseY);
      for (let x = 0; x <= width; x += 6) {
        const y =
          baseY +
          Math.sin(x * w.len + t * w.speed * 60) * w.amp +
          Math.sin(x * w.len * 0.5 + t * w.speed * 38) * w.amp * 0.4;
        ctx.lineTo(x, y);
      }
      ctx.lineTo(width, height);
      ctx.closePath();

      const grad = ctx.createLinearGradient(0, baseY - w.amp, 0, height);
      grad.addColorStop(0, `rgba(${w.color},${w.alpha})`);
      grad.addColorStop(0.6, `rgba(${w.color},${w.alpha * 0.35})`);
      grad.addColorStop(1, `rgba(${w.color},0)`);
      ctx.fillStyle = grad;
      ctx.fill();

      // glowing crest line
      ctx.beginPath();
      for (let x = 0; x <= width; x += 6) {
        const y =
          baseY +
          Math.sin(x * w.len + t * w.speed * 60) * w.amp +
          Math.sin(x * w.len * 0.5 + t * w.speed * 38) * w.amp * 0.4;
        if (x === 0) ctx.moveTo(x, y);
        else ctx.lineTo(x, y);
      }
      ctx.strokeStyle = `rgba(${w.color},${Math.min(0.5, w.alpha * 2.4)})`;
      ctx.lineWidth = 1.2;
      ctx.stroke();
    };

    const draw = () => {
      t += 1;
      ctx.clearRect(0, 0, width, height);

      // cosmic waves (additive glow)
      ctx.globalCompositeOperation = "lighter";
      for (const w of waves) drawWave(w);
      ctx.globalCompositeOperation = "source-over";

      rafId = requestAnimationFrame(draw);
    };

    const start = () => {
      if (running) return;
      running = true;
      draw();
    };
    const stop = () => {
      running = false;
      cancelAnimationFrame(rafId);
    };

    resize();
    window.addEventListener("resize", resize);

    const io = new IntersectionObserver(
      ([entry]) => {
        if (entry.isIntersecting) start();
        else stop();
      },
      { threshold: 0.05 }
    );
    io.observe(section);

    return () => {
      stop();
      io.disconnect();
      window.removeEventListener("resize", resize);
    };
  }, []);

  return (
    <section ref={sectionRef} className={styles.levelsSection}>
      {/* Top border + gradient glow */}
      <div className={styles.topGlow} />

      {/* Cosmic waves animated background */}
      <canvas
        ref={particleCanvasRef}
        className={styles.levelsParticles}
        aria-hidden="true"
      />
      <div className={styles.levelsAurora} aria-hidden="true" />

      <div className={styles.levelsFrameContainer}>
        <div ref={badgeRef}>
          <SectionHeader
            index="05"
            label="Choose your path"
            title="OAK, explained for your level of expertise"
            lead="Three guided tours of the same runtime. Pick the one that fits you."
          />
        </div>

        <div className={styles.levelsOuterContainer}>
          <div ref={cardsWrapRef} className={styles.levelsGrid}>
            {levels.map((level) => (
              <Link
                key={level.id}
                to={levelPages[level.id]}
                className={styles.pathCard}
                style={{ ["--accent" as any]: level.accent }}
              >
                <div className={styles.pathCardTop}>
                  <span className={styles.pathCardNumber}>{level.id}</span>
                  <div
                    className={styles.pathCardMeter}
                    title={`Expertise: ${level.tag}`}
                    aria-label={`Expertise: ${level.tag}`}
                  >
                    {[1, 2, 3].map((dot) => (
                      <span
                        key={dot}
                        className={`${styles.pathMeterDot} ${
                          dot <= level.expertise ? styles.pathMeterDotOn : ""
                        }`}
                      />
                    ))}
                  </div>
                </div>

                <div className={styles.pathCardImageArea}>
                  <PersonaArt kind={level.art} className={styles.pathCardImage} />
                </div>

                <span className={styles.pathCardTag}>{level.tag}</span>
                <h3 className={styles.pathCardTitle}>{level.title}</h3>
                <p className={styles.pathCardDesc}>{level.description}</p>

                <span className={styles.pathCardCta}>
                  Choose this path
                  <MdNorthEast
                    className={styles.pathCardCtaIcon}
                    aria-hidden="true"
                  />
                </span>
              </Link>
            ))}
          </div>
        </div>
      </div>
    </section>
  );
}

/* ─── Page Export ───────────────────────────────────────────────────────── */

/** Render the landing page using the configured site title and tagline. */
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
      title={`${siteConfig.title} - ${siteConfig.tagline}`}
      description="OAK is the open-source operating system for scalable, compliant enterprise AI agents. Build, test, and deploy with OpenAI, LangGraph, CrewAI, Google ADK, Smolagents, Pydantic AI, Microsoft Agent Framework, or the Claude Agent SDK to AWS, Azure, or GCP, with built-in messaging, memory, knowledge bases, guardrails, sandboxed code execution, and observability (Langfuse, OpenLLMetry, Pydantic Logfire, AWS CloudWatch)."
    >
      {/* <PlantParticlesBackground ref={backgroundRef} /> */}
      <WhatsNewBanner />
      <Hero />
      <main>
        <TrustMarks />
        <CapabilityRail />
        <ArchitectureOverview />
        <CompatibilityMatrix />
        <Deployment />
        <div ref={levelsRef} id="levels">
          <Levels />
        </div>
        <FAQ />
        <ClosingPanel />
      </main>
    </Layout>
  );
}
