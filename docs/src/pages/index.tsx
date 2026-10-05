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
import FAQ from "../components/FAQ";
import IntegrationsMarquee from "../components/IntegrationsMarquee";
import ArchitectureOverview from "../components/ArchitectureOverview";
import FeatureExplorer from "../components/FeatureExplorer";
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
import { useHistory } from "@docusaurus/router";

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
          <strong>Agent Kernel on Kubernetes</strong> - an official Helm chart
          deploys the full pipeline to any cluster: bare metal, EKS, or
          air-gapped.
        </span>
        <Link
          to="/blog/kubernetes-on-prem-helm-chart"
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
  const installCommands = ["pip install agentkernel", "ak skill install"];
  const leftRef = useRef(null);
  const titleRef = useRef(null);
  const subtitleRef = useRef(null);
  const buttonsRef = useRef(null);
  const videoRef = useRef(null);
  const scrollLabelRef = useRef(null);
  const [copiedInstall, setCopiedInstall] = useState(false);

  const handleCopyInstall = async () => {
    if (typeof navigator === "undefined" || !navigator.clipboard) {
      return;
    }

    try {
      await navigator.clipboard.writeText(installCommands.join("\n"));
      setCopiedInstall(true);
      window.setTimeout(() => setCopiedInstall(false), 1800);
    } catch {
      // Clipboard may be unavailable due to permissions or non-secure context.
    }
  };

  const subtitleLines = [
    "Agent Kernel is the open source platform for building and deploying enterprise AI agents seamlessly at scale.",
    "Agent Kernel reduces months of engineering work to minutes.",
    "Works with any major Agentic technology, runs on any cloud, interfaces with all mainstream communication channels seamlessly out of the box, no framework/platform lock-in, production ready from day one.",
  ];

  // Reading speed: ~200 words/minute → ~3ms per char is a safe hold duration floor
  // Line 1: ~16 words → ~4.8s hold | Line 2: ~9 words → ~3s hold | Line 3: ~29 words → ~8.5s hold
  const holdDurations = [4.8, 3.0, 8.5];

  useLayoutEffect(() => {
    const tl = gsap.timeline({ defaults: { ease: "power3.out" } });

    gsap.set(
      [
        titleRef.current,
        subtitleRef.current,
        buttonsRef.current,
        videoRef.current,
        scrollLabelRef.current,
      ],
      { opacity: 0, y: 28 }
    );

    tl.to(titleRef.current, { opacity: 1, y: 0, duration: 0.85 })
      .to(subtitleRef.current, { opacity: 1, y: 0, duration: 0.6 }, "-=0.5")
      .to(buttonsRef.current, { opacity: 1, y: 0, duration: 0.55 }, "-=0.35")
      .to(videoRef.current, { opacity: 1, y: 0, duration: 0.9 }, "-=0.7")
      .to(scrollLabelRef.current, { opacity: 1, y: 0, duration: 0.5 }, "-=0.4");

    const reducedMotion =
      typeof window !== "undefined" &&
      window.matchMedia("(prefers-reduced-motion: reduce)").matches;

    let pulse: any = null;
    if (!reducedMotion && scrollLabelRef.current) {
      pulse = gsap.to(scrollLabelRef.current, {
        y: 6,
        repeat: -1,
        yoyo: true,
        ease: "power1.inOut",
        duration: 1.1,
        delay: 1.2,
      });
    }

    // ── Cycling subtitle animation ───────────────────────────────
    const subtitleEl = subtitleRef.current as HTMLElement | null;
    let cycleTimeout: ReturnType<typeof setTimeout>;
    let currentIndex = 0;
    let cycleKilled = false;

    const fadeDuration = 0.45; // seconds for fade in / fade out

    const showLine = (index: number) => {
      if (cycleKilled || !subtitleEl) return;

      const text = subtitleLines[index];
      const hold = holdDurations[index];

      // Set new text while invisible
      gsap.set(subtitleEl, { opacity: 0, y: 10 });
      subtitleEl.textContent = text;

      // Fade in + slide up
      gsap.to(subtitleEl, {
        opacity: 1,
        y: 0,
        duration: fadeDuration,
        ease: "power2.out",
        onComplete: () => {
          if (cycleKilled) return;
          // Hold for reading, then fade out and advance
          cycleTimeout = setTimeout(() => {
            if (cycleKilled) return;
            gsap.to(subtitleEl, {
              opacity: 0,
              y: -8,
              duration: fadeDuration,
              ease: "power2.in",
              onComplete: () => {
                if (cycleKilled) return;
                currentIndex = (index + 1) % subtitleLines.length;
                showLine(currentIndex);
              },
            });
          }, hold * 1000);
        },
      });
    };

    // Kick off the cycle once the entry animation has brought the subtitle into view.
    // The entry tl finishes roughly 2.2s in; we wait a touch longer for comfort.
    const startDelay = setTimeout(() => {
      if (!cycleKilled) showLine(0);
    }, 2400);

    return () => {
      tl.kill();
      if (pulse) pulse.kill();
      cycleKilled = true;
      clearTimeout(cycleTimeout);
      clearTimeout(startDelay);
      gsap.killTweensOf(subtitleEl);
    };
  }, []);

  return (
    <section className={styles.hero}>
      <div className={styles.inner}>
        {/* ── LEFT ───────────────────────────────── */}
        <div ref={leftRef} className={styles.left}>
          <h1 ref={titleRef} className={styles.title}>
            <span className={styles.titleDim}>The Operating System</span>
            <br />
            <span className={styles.titleDim}>for</span> Scalable & Compliant
            <br />
            Enterprise AI{" "}
            <span className={styles.gradientWord}>Agents</span>
          </h1>

          <p ref={subtitleRef} className={styles.subtitle}>
            Agent Kernel is the open source platform for building and deploying
            enterprise AI agents seamlessly at scale.
          </p>

          <div ref={buttonsRef} className={styles.heroActions}>
            <div className={styles.heroButtons}>
              <Link
                className={`button button--secondary button--sm ${styles.heroBtnPrimary}`}
                to="/docs/quick-start"
              >
                Quick Start
                <MdNorthEast className={styles.quickStartIcon} aria-hidden="true" />
              </Link>
            </div>

            {/* Agent Skills: deliberately low-key; the id keeps old #agent-skills links landing here. */}
            <div id="agent-skills" className={styles.heroSkills}>
              <div className={styles.heroSkillsHead}>
                <span className={styles.heroSkillsLabel}>Agent Skills</span>
                <span className={styles.heroSkillsHint}>
                  Claude Code · Cursor · Codex · Windsurf · Copilot
                </span>
              </div>
              <div className={styles.heroSkillsCmds}>
                {installCommands.map((command) => (
                  <code key={command} className={styles.heroSkillsCmd}>
                    <span className={styles.heroInstallPrompt} aria-hidden="true">$</span>
                    {command}
                  </code>
                ))}
                <button
                  type="button"
                  className={`${styles.heroInstallCopy} ${styles.heroSkillsCopy} ${
                    copiedInstall ? styles.heroInstallCopied : ""
                  }`}
                  onClick={handleCopyInstall}
                  aria-label="Copy install commands"
                  title={copiedInstall ? "Copied" : "Copy commands"}
                >
                  {copiedInstall ? (
                    <MdCheck className={styles.heroInstallCopyIcon} aria-hidden="true" />
                  ) : (
                    <MdContentCopy className={styles.heroInstallCopyIcon} aria-hidden="true" />
                  )}
                </button>
              </div>
              <p className={styles.heroSkillsText}>
                Guides your coding assistant follows to scaffold, extend, test and deploy
                Agent Kernel agents.{" "}
                <Link to="/docs/agent-skills" className={styles.heroSkillsLink}>
                  Learn more <span aria-hidden="true">→</span>
                </Link>
              </p>
            </div>
          </div>
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
          <div className={styles.scrollLabelInner}>
            <span className={styles.scrollLine} />
            <span className={styles.scrollText}>
              Agent OS for
              <br />
              <strong>Enterprise AI</strong>
            </span>
          </div>
        </div>
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
      {/* Top border + gradient glow */}
      <div className={styles.topGlow} />

      <div className="container">
        <div className={styles.deployHeader}>
          <div className={styles.Badge}>
            <span className={styles.badgeStar}>✦</span>
            Deployment
          </div>
          <h2 className={styles.deployTitle}>Deploy Anywhere</h2>
          <p className={styles.deploySubtitle}>
            Run the same agent code on AWS, Azure, GCP, or your own Kubernetes cluster. Zero rewrites.
            <br />
            Includes production-ready Terraform modules and a Helm chart with best practices baked in.
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

/* ─── Trust / Compliance ─────────────────────────────────────────────────── */

function TrustSection() {
  const sectionRef = useRef(null);
  const badgeRef = useRef(null);
  const labelRef = useRef(null);
  const rowRef = useRef(null);

  useEffect(() => {
    gsap.registerPlugin(ScrollTrigger);

    gsap.set([badgeRef.current, labelRef.current], { opacity: 0, y: 16 });
    gsap.set(rowRef.current?.children || [], { opacity: 0, y: 24 });

    const tl = gsap.timeline({
      scrollTrigger: {
        trigger: sectionRef.current,
        start: "top 85%",
        toggleActions: "play none none none",
        once: true,
      },
    });

    tl.to(badgeRef.current, { opacity: 1, y: 0, duration: 0.5, ease: "power2.out" })
      .to(labelRef.current, { opacity: 1, y: 0, duration: 0.5, ease: "power2.out" }, "-=0.3")
      .to(
        rowRef.current?.children || [],
        { opacity: 1, y: 0, duration: 0.4, ease: "power2.out", stagger: 0.1 },
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
    <section ref={sectionRef} className={styles.trustSection}>
      <div className={styles.topGlow} />

      <div ref={badgeRef} className={styles.Badge}>
        <span className={styles.badgeStar}>✦</span>
        Security &amp; Compliance
      </div>

      <p ref={labelRef} className={styles.trustLabel}>
        Built on a certified ISO 27001 and SOC 2 environment.
      </p>

      <div ref={rowRef} className={styles.trustCertRow}>
        <div className={styles.trustCertTile} tabIndex={0}>
          <img src="/img/iso.png" alt="ISO 27001 Certified" className={styles.trustCertLogo} />
          <p className={styles.trustCertDesc}>
            Information Security Management System certified to the international standard.
          </p>
        </div>
        <div className={styles.trustCertTile} tabIndex={0}>
          <img src="/img/soc.png" alt="SOC 2 Type 2 Audited" className={styles.trustCertLogo} />
          <p className={styles.trustCertDesc}>
            Security, availability, and confidentiality independently audited against the AICPA SOC 2 framework.
          </p>
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
              className={`button button--primary button--lg ${styles.heroBtnSecondary}`}
              to="/docs/quick-start"
            >
              Quick Start
              <MdNorthEast className={styles.quickStartIcon} aria-hidden="true" />
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
  );
}

/* ─── Levels ────────────────────────────────────────────────────────────── */

interface Level {
  id: string;
  title: string;
  image: string;
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
      image: "/img/business_leader.png",
      description:
        "You run or work in a business/enterprise and want to incorporate AI agents that actually work into your business workflows without needing to handle the complexities of the tech.",
      accent: "#ffb547",
      tag: "No code required",
      expertise: 1,
    },
    {
      id: "02",
      title: "Developer",
      image: "/img/developer.png",
      description:
        "You build software but haven't built AI agents yet. You want to ship something robust and real without learning a new stack from scratch.",
      accent: "#00ddff",
      tag: "Some coding",
      expertise: 2,
    },
    {
      id: "03",
      title: "AI Engineer",
      image: "/img/ai.png",
      description:
        "You already work with LLMs and agentic frameworks. You need a production-grade AI agent execution framework that doesn't get in your way.",
      accent: "#a78bfa",
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
      [badgeRef.current, titleRef.current, subtitleRef.current],
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
        <div className={styles.levelsHeader}>
          <div ref={badgeRef} className={styles.Badge}>
            <span className={styles.badgeStar}>✦</span>
            Built for Every Level of Expertise
          </div>
          <h2 ref={titleRef} className={styles.levelsTitle}>
            <span>Agent Kernel, Explained</span>
            {" "}
            <span>For Your Level of Expertise</span>
          </h2>
          <p ref={subtitleRef} className={styles.levelsSubtitle}>
            Pick the path that fits you best
          </p>
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
                  <img
                    src={level.image}
                    alt={level.title}
                    className={styles.pathCardImage}
                  />
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
      description="Agent Kernel is the open-source operating system for scalable, compliant enterprise AI agents. Build, test, and deploy with OpenAI, LangGraph, CrewAI, Google ADK, Smolagents, or Pydantic AI to AWS, Azure, or GCP, with built-in messaging, memory, knowledge bases, guardrails, sandboxed code execution, and observability (Langfuse, OpenLLMetry, Pydantic Logfire)."
    >
      {/* <PlantParticlesBackground ref={backgroundRef} /> */}
      <WhatsNewBanner />
      <Hero />
      <main>
        <ArchitectureOverview />
        <div ref={levelsRef} id="levels">
          <Levels />
        </div>
        <FeatureExplorer />
        <Deployment />
        <IntegrationsMarquee />
        <TrustSection />
        <FAQ />
        <Community sectionRef={communityRef} />
      </main>
    </Layout>
  );
}
