import { useState, useEffect, useRef, useCallback, useLayoutEffect } from 'react';
import Link from '@docusaurus/Link';
import Layout from '@theme/Layout';
import styles from './use-cases.module.css';
import indexStyles from './index.module.css';
import UseCaseJourneyMap from '../components/UseCaseJourneyMap';
import gsap from 'gsap';
import { ScrollTrigger } from 'gsap/dist/ScrollTrigger';
import {
  MdBusiness,
  MdAutoAwesome,
  MdRocketLaunch,
  MdGroup,
  MdCheck,
  MdSwapHoriz,
  MdCloud,
  MdCode,
  MdSecurity,
  MdMessage,
  MdSpeed,
  MdNetworkCheck,
} from 'react-icons/md';
import { FaGithub, FaLock } from 'react-icons/fa';
import PlantParticlesBackground from '../components/PlantParticlesBackground';

gsap.registerPlugin(ScrollTrigger);

type ParticleBackgroundHandle = {
  triggerScatterOut: () => void;
  triggerScatterIn: () => void;
  triggerReverseScatterIn: () => void;
  triggerScatterFloat: () => void;
  triggerFloatReform: () => void;
};

/* ─── Hero ──────────────────────────────────────────────────────────────── */

function Hero() {
  const titleRef = useRef<HTMLHeadingElement>(null);
  const subtitleRef = useRef<HTMLParagraphElement>(null);
  const buttonsRef = useRef<HTMLDivElement>(null);
  const badgeRef = useRef<HTMLDivElement>(null);

  // Aurora refs
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const mouseRef = useRef({ x: 0.5, y: 0.5 });
  const targetMouseRef = useRef({ x: 0.5, y: 0.5 });
  const animFrameRef = useRef<number>(0);
  const idleTimerRef = useRef<NodeJS.Timeout | null>(null);
  const isIdleRef = useRef(false);
  const isAnimatingRef = useRef(true);

  /* ── Aurora canvas animation ── */
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext('2d')!;

    const resize = () => {
      canvas.width = canvas.offsetWidth;
      canvas.height = canvas.offsetHeight;
    };
    resize();
    window.addEventListener('resize', resize);

    // Track mouse over the section
    const section = canvas.parentElement!;
    const onMove = (e: MouseEvent) => {
      const rect = section.getBoundingClientRect();
      targetMouseRef.current = {
        x: (e.clientX - rect.left) / rect.width,
        y: (e.clientY - rect.top) / rect.height,
      };
      
      // Reset idle state on mouse movement
      isIdleRef.current = false;
      if (idleTimerRef.current) {
        clearTimeout(idleTimerRef.current);
      }
      idleTimerRef.current = setTimeout(() => {
        isIdleRef.current = true;
      }, 2000); // 2 seconds of inactivity before idle animation
    };
    section.addEventListener('mousemove', onMove);
    
    // Initialize idle timer
    idleTimerRef.current = setTimeout(() => {
      isIdleRef.current = true;
    }, 1000);

    let t = 0;

    const draw = () => {
      // Only animate if the hero section is not covered
      if (isAnimatingRef.current) {
        t++;

        // If idle, animate the target position in a circular motion
        if (isIdleRef.current) {
          const slowTime = t * 0.005; // Idle animation movement
          const radius = 0.25;
          targetMouseRef.current = {
            x: 0.5 + Math.cos(slowTime) * radius,
            y: 0.5 + Math.sin(slowTime) * radius,
          };
        }

        // Smoothly lerp mouse position
        const m = mouseRef.current;
        const tm = targetMouseRef.current;
        m.x += (tm.x - m.x) * 0.04;
        m.y += (tm.y - m.y) * 0.04;

        const W = canvas.width;
        const H = canvas.height;

        // Clear with deep dark base
        ctx.clearRect(0, 0, W, H);
        ctx.fillStyle = '#010002';
        ctx.fillRect(0, 0, W, H);

        // Cursor spotlight — a tight bright glow that follows the mouse
        const sx = m.x * W;
        const sy = m.y * H;
        const spotR = Math.max(W, H) * 0.5;
        const spot = ctx.createRadialGradient(sx, sy, 0, sx, sy, spotR);
        spot.addColorStop(0,   'rgba(0,119,255,0.10)');
        spot.addColorStop(0.5, 'rgba(0,119,255,0.05)');
        spot.addColorStop(1,   'rgba(0,119,255,0.00)');
        ctx.globalCompositeOperation = 'screen';
        ctx.fillStyle = spot;
        ctx.fillRect(0, 0, W, H);

        // Reset composite
        ctx.globalCompositeOperation = 'source-over';
      }

      animFrameRef.current = requestAnimationFrame(draw);
    };

    draw();

    return () => {
      cancelAnimationFrame(animFrameRef.current);
      window.removeEventListener('resize', resize);
      section.removeEventListener('mousemove', onMove);
      if (idleTimerRef.current) {
        clearTimeout(idleTimerRef.current);
      }
    };
  }, []);

  /* ── Existing GSAP entrance animation ── */
  useEffect(() => {
    const tl = gsap.timeline();

    gsap.set([badgeRef.current, titleRef.current, subtitleRef.current, buttonsRef.current], {
      opacity: 0,
      y: 18,
    });

    tl.to(badgeRef.current, {
      opacity: 1,
      y: 0,
      duration: 0.45,
      ease: 'power2.out',
    })
      .to(
        titleRef.current,
        {
          opacity: 1,
          y: 0,
          duration: 0.8,
          ease: 'power2.out',
        },
        '-=0.3',
      )
      .to(
        subtitleRef.current,
        {
          opacity: 1,
          y: 0,
          duration: 0.6,
          ease: 'power2.out',
        },
        '-=0.45',
      )
      .to(
        buttonsRef.current,
        {
          opacity: 1,
          y: 0,
          duration: 0.5,
          ease: 'power2.out',
        },
        '-=0.25',
      );
  }, []);

  /* ── Stop animations when hero is covered ── */
  useEffect(() => {
    const handleScroll = () => {
      // Check if hero is covered by scrolling down past 100vh
      if (window.scrollY > window.innerHeight * 0.8) {
        isAnimatingRef.current = false;
      } else {
        isAnimatingRef.current = true;
      }
    };

    window.addEventListener('scroll', handleScroll, { passive: true });
    return () => window.removeEventListener('scroll', handleScroll);
  }, []);

  return (
    <section className={styles.hero}>
      {/* Aurora canvas — sits behind everything */}
      <canvas
        ref={canvasRef}
        style={{
          position: 'absolute',
          inset: 0,
          width: '100%',
          height: '100%',
          pointerEvents: 'none',
          zIndex: 0,
        }}
      />

      <div className="container" style={{ position: 'relative', zIndex: 1 }}>
        <div className={styles.heroContent}>
          <div ref={badgeRef} className={styles.Badge}>
            <span className={styles.badgeStar}>✦</span>
            Use Cases
          </div>
          <h1 ref={titleRef} className={styles.heroTitle}>
            Who Is Agent Kernel Built For?
          </h1>
          <p ref={subtitleRef} className={styles.heroSubtitle}>
            Agent Kernel is an open-source runtime that lets you build, test, and deploy AI agents
            to production in days instead of months. It works with any major AI framework (OpenAI,
            LangGraph, CrewAI, Google ADK) and can run agents from multiple frameworks together in
            a single runtime. It deploys to AWS, Azure, or your own servers with zero platform code.
          </p>
          <div ref={buttonsRef} className={styles.heroButtons}>
            <Link className={`button button--primary button--lg ${styles.btnPrimary}`} to="/docs">
              <span className={styles.btnIcon}>→</span>
              Get Started
            </Link>
            <Link className={`button button--secondary button--lg ${styles.btnSecondary}`} to="/features">
              <span className={styles.btnIconSecondary}>→</span>
              Explore Features
            </Link>
          </div>
        </div>
      </div>
    </section>
  );
}

/* ─── Segments data ─────────────────────────────────────────────────────── */

const segments = [
  {
    id: 'software-services',
    icon: <MdBusiness />,
    accent: 'cyan',
    title: 'Established Software Companies',
    subtitle: 'Services / Dev Houses',
    profile: 'Development houses and IT services firms with existing clients who are asking for AI-powered solutions. They have developers on staff but lack AI agent platform expertise.',
    diagramLeft:  { label: 'Client AI Request', desc: 'Existing clients asking for agents' },
    diagramRight: { label: 'Shipped in Weeks', desc: 'Production agents, on time' },
    painPoints: [
      'Need to stand up AI agent capabilities quickly without a 6-month R&D cycle',
      'Building the platform layer (deployment, session management, integrations) from scratch is expensive',
      'Every project reinvents the same infrastructure — zero leverage across clients',
      'Hard to demo capabilities rapidly without working integrations',
    ],
    valueProps: [
      'Jump-start agentic AI service offerings with a production-ready platform',
      'Focus developer time on client-specific agent logic, not infrastructure',
      'Deliver multi-cloud solutions (AWS, Azure) from day one',
      'Battle-tested runtime reduces project risk vs. building from scratch',
      'Built-in integrations (Slack, WhatsApp, etc.) enable rapid demos and delivery',
    ],
    keyMessage: '"Ship AI agent solutions to your clients in weeks, not months. Agent Kernel handles the platform — you focus on the intelligence."',
    cta: '/docs',
    ctaLabel: 'Get Started →',
  },
  {
    id: 'software-products',
    icon: <MdAutoAwesome />,
    accent: 'violet',
    title: 'Software Companies Enhancing Products',
    subtitle: 'SaaS / Enterprise Software',
    profile: 'Product companies with existing SaaS or enterprise software who want to embed conversational AI, intelligent automation, or agent-driven workflows into their products.',
    diagramLeft:  { label: 'Existing SaaS', desc: 'Your current product' },
    diagramRight: { label: 'AI-Enhanced Product', desc: 'Agents embedded, zero lock-in' },
    painPoints: [
      'Need to add AI agent capabilities without massive re-architecture',
      "Framework lock-in is a real risk — the AI landscape changes fast, and picking the wrong framework today could mean expensive rewrites tomorrow",
      'Compliance and enterprise requirements demand guardrails, observability, and fault tolerance',
      'Customer cloud strategies span AWS and Azure — vendor lock-in is unacceptable',
    ],
    valueProps: [
      'Embed AI agents into existing products with minimal disruption',
      'Framework-agnostic design eliminates lock-in — swap frameworks without touching product code',
      'Run agents from multiple frameworks side by side in a single runtime',
      'REST API mode drops into existing architectures seamlessly',
      'Pluggable session backends integrate with existing database infrastructure',
      'Enterprise features (guardrails, observability, fault tolerance) meet compliance requirements',
    ],
    keyMessage: '"Future-proof your product\'s AI capabilities. Add intelligent agents today, switch frameworks tomorrow — your platform code never changes."',
    cta: '/docs',
    ctaLabel: 'Get Started →',
  },
  {
    id: 'ai-startups',
    icon: <MdRocketLaunch />,
    accent: 'cyan',
    title: 'AI Startups',
    subtitle: 'Early to Growth Stage',
    profile: 'Early to growth-stage startups building AI-native products. Small engineering teams that need to move fast and can\'t afford to build platform infrastructure.',
    diagramLeft:  { label: 'MVP Idea', desc: 'Prototype stage, lean team' },
    diagramRight: { label: 'Production in Days', desc: 'Multi-cloud, fully deployed' },
    painPoints: [
      'Engineering bandwidth is the scarcest resource — every hour on infrastructure is an hour not spent on core AI',
      "Can't afford platform engineering before finding product-market fit",
      'Need to reach users on popular messaging platforms (Slack, WhatsApp, etc.) quickly',
      'Must scale from MVP to multi-AZ production without rewrites',
    ],
    valueProps: [
      'Go from prototype to production deployment in days',
      'Open-source and free — no licensing costs eating into runway',
      'Full deployment infrastructure (Terraform, Docker) out of the box',
      'Built-in integrations let you reach users on Slack, WhatsApp, Instagram from day one',
      'Scales from single Lambda functions to multi-AZ container clusters as you grow',
      'Multi-cloud from the start — never locked into one provider',
    ],
    keyMessage: '"Your AI startup\'s unfair advantage. Go from idea to production-deployed, multi-cloud AI agents in days — not quarters. Save your engineering bandwidth for what makes you unique."',
    cta: '/docs/quick-start',
    ctaLabel: 'Quick Start →',
  },
  {
    id: 'domain-experts',
    icon: <MdGroup />,
    accent: 'violet',
    title: 'Domain Experts',
    subtitle: 'Finance, Healthcare, Legal, Education…',
    profile: 'Subject matter experts or small teams with deep domain knowledge who want to build AI products but lack (or want to minimize) expensive software engineering overhead.',
    diagramLeft:  { label: 'Domain Knowledge', desc: 'Your expertise and use case' },
    diagramRight: { label: 'AI Product', desc: 'Deployed without a DevOps team' },
    painPoints: [
      'Know what they want their AI agent to do — but building the software platform around it requires expensive engineering',
      "APIs, cloud deployments, database integrations, messaging connectors — require a fulltime DevOps team they can't afford",
      'Vendor lock-in with expensive proprietary platforms erodes product margins',
      'No standard way to validate that agent behavior matches domain requirements',
    ],
    valueProps: [
      'Dramatically reduces the "software engineering surface area" — define agent logic, Agent Kernel handles everything else',
      'Simple Python-based agent definition accessible to technical domain experts',
      'Pre-built deployment to AWS and Azure — no DevOps expertise required',
      'Built-in messaging integrations mean products can reach end-users through familiar channels immediately',
      'Testing framework lets domain experts validate agent behavior with simple test scenarios',
      'Open-source means no vendor lock-in and no surprise pricing',
    ],
    keyMessage: '"You bring the expertise. Agent Kernel brings the platform. Build production-grade AI products without a fulltime engineering team."',
    cta: '/docs',
    ctaLabel: 'Get Started →',
  },
];

/* ─── Segment Modal ─────────────────────────────────────────────────────── */

function SegmentModal({ segment, onClose }: { segment: typeof segments[0]; onClose: () => void }) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose(); };
    document.addEventListener('keydown', onKey);
    document.body.style.overflow = 'hidden';
    return () => {
      document.removeEventListener('keydown', onKey);
      document.body.style.overflow = '';
    };
  }, [onClose]);

  return (
    <div
      className={styles.modalOverlay}
      onClick={onClose}
      role="dialog"
      aria-modal="true"
      aria-label={segment.title}
    >
      <div className={styles.modalContainer} onClick={e => e.stopPropagation()}>
        <button className={styles.modalClose} onClick={onClose} aria-label="Close">×</button>

        {/* Header */}
        <div className={styles.modalHeader}>
          <div className={`${styles.segmentIconWrapper} ${styles[`iconAccent_${segment.accent}`]}`}>
            {segment.icon}
          </div>
          <div>
            <h2 className={styles.modalTitle}>{segment.title}</h2>
            <p className={styles.modalSubtitle}>{segment.subtitle}</p>
          </div>
        </div>

        {/* Diagram */}
        <div className={styles.modalDiagram}>
          <div className={styles.diagramStep}>
            <div className={styles.diagramStepLabel}>{segment.diagramLeft.label}</div>
            <div className={styles.diagramStepDesc}>{segment.diagramLeft.desc}</div>
          </div>
          <div className={styles.diagramArrow}>→</div>
          <div className={`${styles.diagramStep} ${styles.diagramStepCenter}`}>
            <img
              src="/img/branding/agent-kernel-icon-color.svg"
              alt="Agent Kernel"
              className={styles.diagramStepIcon}
            />
            <div className={styles.diagramStepLabel}>Agent Kernel</div>
            <div className={styles.diagramStepDesc}>Runtime · Deploy · Integrate</div>
          </div>
          <div className={styles.diagramArrow}>→</div>
          <div className={styles.diagramStep}>
            <div className={styles.diagramStepLabel}>{segment.diagramRight.label}</div>
            <div className={styles.diagramStepDesc}>{segment.diagramRight.desc}</div>
          </div>
        </div>

        {/* Profile */}
        <p className={styles.segmentProfile}>{segment.profile}</p>

        {/* Pain points + value props */}
        <div className={styles.segmentBody}>
          <div className={styles.segmentColumn}>
            <h4 className={styles.segmentColumnTitle}>Pain Points</h4>
            <ul className={styles.painList}>
              {segment.painPoints.map((p, j) => (
                <li key={j}>
                  <span className={styles.painIcon}>✕</span>
                  {p}
                </li>
              ))}
            </ul>
          </div>
          <div className={styles.segmentColumn}>
            <h4 className={styles.segmentColumnTitle}>Agent Kernel Value</h4>
            <ul className={styles.valueList}>
              {segment.valueProps.map((v, j) => (
                <li key={j}>
                  <MdCheck className={styles.valueIcon} />
                  {v}
                </li>
              ))}
            </ul>
          </div>
        </div>

        {/* Quote */}
        <div className={`${styles.segmentQuote} ${styles[`accent_${segment.accent}`]}`}>
          <blockquote>{segment.keyMessage}</blockquote>
        </div>

        {/* CTA */}
        <Link
          to={segment.cta}
          className={`button button--primary ${styles[`ctaAccent_${segment.accent}`]}`}
          onClick={onClose}
        >
          {segment.ctaLabel}
        </Link>
      </div>
    </div>
  );
}


const ORBIT_CARDS = [
  {
    icon: <MdSwapHoriz />,
    color: '#00DDFF',
    title: 'Framework-Neutral',
    desc: 'The only runtime that lets you bring inswap between  agents written from OpenAI Agents,  CrewAI, LangGraph, and Google ADK, Smolagents, LiveKit with near-zero code change — and run all of them simultaneously in a single runtime.',
  },
  {
    icon: <MdCloud />,
    color: '#00DDFF',
    title: 'Multi-Cloud Native',
    desc: 'Same agent code deploys to AWS and Azure out of the box. No other AI agent runtime offers this out of the box.',
  },
  {
    icon: <MdSpeed />,
    color: '#00DDFF',
    title: 'Full Lifecycle',
    desc: 'Build → Test → Deploy → Monitor. One tool that takes you from a Python script to a multi-AZ production cluster.',
  },
  {
    icon: <MdCode />,
    color: '#00DDFF',
    title: 'Lightweight',
    desc: 'A thin adapter layer, not a heavy abstraction. Bring your existing agent code and wrap it in minutes, not days.',
  },
  {
    icon: <MdSecurity />,
    color: '#00DDFF',
    title: 'Production-Ready',
    desc: 'Fault tolerance, guardrails, observability, and session management built in from day one — not bolted on later.',
  },
  {
    icon: <MdMessage />,
    color: '#00DDFF',
    title: 'Built-in Messaging',
    desc: 'Slack, WhatsApp, Instagram, Telegram, Messenger, Gmail — ship working integrations on day one, not months later.',
  },
  {
    icon: <FaLock />,
    color: '#00DDFF',
    title: 'Open-Source',
    desc: 'No usage fees, no proprietary lock-in. Community-driven with full codebase access — fork it, extend it, contribute back.',
  },
  {
    icon: <MdNetworkCheck />,
    color: '#00DDFF',
    title: 'Protocol Support',
    desc: 'MCP and A2A server modes for future-proof agent architectures and full ecosystem compatibility out of the box.',
  },
];

function IconCell({ color, children }: { color: string; children: React.ReactNode }) {
  return (
    <div
      className={styles.iconCell}
      style={{ '--icon-color': color } as React.CSSProperties}
    >
      <div className={styles.iconCellBg} />
      <span className={styles.iconCellGlyph}>{children}</span>
    </div>
  );
}

const REAL_WORLD_USE_CASES = [
  {
    title: 'Agentic AI Assisted Market Surveillance',
    description:
      'A scalable surveillance system for monitor real-time order and trade feeds of a carbon credit market. Agent Kernel enables, AI agents to monitor orders and flag potential / suspicious trades which violate regulations.',
    link: '#',
  },
  {
    title: 'AI First SDLC',
    description:
      'A team of Agents looking at various artifacts at each phase of the SDLC and orchestrate humans to unblock for a smooth transition. Can overcome the speedbumps created by the weakest links (i.e., humans) in the SDLC chain.',
    link: '#',
  },
  {
    title: 'Troubleshooter Agent',
    description:
      'A system troubleshooter (L1 to L3) which can give a comprehensive issue analysis, root-cause determination and resolution of a complex, distributed trading system. Responds to a system alert by looking at application logs, resource and related metrics. AI agent is able to improve the issue resolution time 20x.',
    link: '#',
  },
];

function RealWorldUseCases() {
  const sectionRef = useRef<HTMLElement>(null);

  useLayoutEffect(() => {
    const section = sectionRef.current;
    if (!section) return;

    const reducedMotion =
      typeof window !== 'undefined' &&
      window.matchMedia('(prefers-reduced-motion: reduce)').matches;

    const header = section.querySelector(`.${styles.realWorldSectionHeader}`);
    const grid = section.querySelector(`.${styles.featuresGrid}`);
    const cells = Array.from(
      section.querySelectorAll(`.${styles.featureGridCell}`),
    );

    if (!header || !grid || !cells.length) return;

    if (reducedMotion) {
      gsap.set([header, grid, cells], { opacity: 1, y: 0, scale: 1 });
      return;
    }

    gsap.set(header, { opacity: 0, y: 24 });
    gsap.set(grid, { opacity: 0, y: 20 });
    gsap.set(cells, { opacity: 0, y: 28, scale: 0.98 });

    const tl = gsap.timeline({
      scrollTrigger: {
        trigger: section,
        start: 'top 88%',
        toggleActions: 'play none none reverse',
      },
    });

    tl.to(header, { opacity: 1, y: 0, duration: 0.5, ease: 'power2.out' })
      .to(
        grid,
        { opacity: 1, y: 0, duration: 0.38, ease: 'power2.out' },
        '-=0.1',
      )
      .to(
        cells,
        { opacity: 1, y: 0, scale: 1, duration: 0.42, stagger: 0.04, ease: 'power2.out' },
        '-=0.14',
      );

    return () => {
      tl.scrollTrigger?.kill();
      tl.kill();
    };
  }, []);

  return (
    <section className={styles.realWorldSection} ref={sectionRef}>
      <div className="container">
        <div className={styles.realWorldSectionHeader}>
          <div className={styles.Badge}>
            <span className={styles.badgeStar}>✦</span>
            Use Cases
          </div>
          <h2 className={styles.realWorldSectionTitle}>Real world use cases</h2>
        </div>
        <ul className={styles.featuresGrid}>
          {REAL_WORLD_USE_CASES.map((useCase, i) => (
            <li key={useCase.title} className={styles.featureGridCell}>
              <Link to={useCase.link} className={styles.featureCard}>
                <div className={styles.featureCardHeader}>
                  <span className={styles.featureIndex}>
                    {String(i + 1).padStart(2, '0')}
                  </span>
                </div>
                <div className={styles.featureCardBody}>
                  <h3 className={styles.featureTitle}>{useCase.title}</h3>
                  <p className={styles.featureDescription}>{useCase.description}</p>
                </div>
                <div className={styles.featureCardFooter}>
                  <span className={styles.featureLink}>Read More</span>
                </div>
              </Link>
            </li>
          ))}
        </ul>
      </div>
    </section>
  );
}

function Differentiators({ backgroundRef }: { backgroundRef: React.RefObject<ParticleBackgroundHandle | null> }) {
  const containerRef = useRef<HTMLDivElement>(null);
  const hubRef = useRef<HTMLDivElement>(null);
  const observerStateRef = useRef(false);



  useEffect(() => {
    if (!backgroundRef.current || !containerRef.current) return;

    const observer = new IntersectionObserver(
      ([entry]) => {
        if (entry.isIntersecting && !observerStateRef.current) {
          observerStateRef.current = true;
          backgroundRef.current?.triggerScatterOut();
        } else if (!entry.isIntersecting && observerStateRef.current) {
          observerStateRef.current = false;
          backgroundRef.current?.triggerScatterIn();
        }
      },
      { threshold: 0.0 },
    );

    observer.observe(containerRef.current);

    return () => {
      observer.disconnect();
    };
  }, [backgroundRef]);

  useEffect(() => {
    const hub = containerRef.current?.querySelector(`.${styles.orbitHub}`);
    const hubImg = containerRef.current?.querySelector(`.${styles.orbitHubIcon}`);
    const cards = containerRef.current?.querySelectorAll(`.${styles.orbitCard}`);
    if (!containerRef.current || !hub || !hubImg || !cards?.length) return;

    // set initial state for cards only (leave hub/video static)
    gsap.set(Array.from(cards), { opacity: 0, scale: 0.88 });

    const tl = gsap.timeline({
      scrollTrigger: {
        trigger: containerRef.current,
        start: 'top 75%',
        // ensure enter/leave both play and reverse so hub image reverses too
        toggleActions: 'play reverse play reverse',
      },
    });

    // Reveal cards sequentially; keep hub (video) static — no hub animation
    tl.to(cards, { opacity: 1, scale: 1, duration: 0.4, stagger: 0.20, ease: 'back.out(1.2)' });
  }, []);

  return (
    <section className={styles.diffSection}>
      <div className="container">
        <div className={styles.sectionHeader}>
          <div className={styles.Badge}>
            <span className={styles.badgeStar}>✦</span>
            Trust
          </div>
          <h2 className={styles.sectionTitle}>Why Teams Choose Agent Kernel</h2>
          <p className={styles.sectionSubtitle}>
            What makes Agent Kernel different from rolling your own or using other platforms.
          </p>
        </div>

        <div ref={containerRef} className={styles.orbitScene}>
          {/* 8 surrounding cards */}
          {ORBIT_CARDS.map((card, i) => (
            <div
              key={i}
              className={`${styles.orbitCard} ${styles[`orbitPos${i}`]}`}
              style={{ '--card-color': card.color } as React.CSSProperties}
            >
              <IconCell color={card.color}>{card.icon}</IconCell>
              <h3 className={styles.bentoTitle}>{card.title}</h3>
              <p className={styles.bentoDesc}>{card.desc}</p>
            </div>
          ))}

          {/* Central hub */}
          <div ref={hubRef} className={styles.orbitHub}>
            <video
              src="/video/hero.mp4"
              aria-label="Agent Kernel"
              className={styles.orbitHubIcon}
              autoPlay
              loop
              muted
              playsInline
              preload="metadata"
            />
          </div>
        </div>
      </div>
    </section>
  );
}

interface CommunityProps {
  sectionRef?: React.Ref<HTMLElement>;
}

function Community({ sectionRef }: CommunityProps) {
  return (
    <section ref={sectionRef} className={indexStyles.ctaSection}>
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
              className={`button button--primary button--lg ${indexStyles.btnPrimary}`}
              to="/docs"
            >
              <span className={indexStyles.btnIcon}>→</span>
              Get Started Free
            </Link>
            <Link
              className={`button button--secondary button--lg ${indexStyles.btnSecondary}`}
              to="https://github.com/yaalalabs/agent-kernel"
              target="_blank"
              rel="noopener noreferrer"
            >
              <span className={indexStyles.btnIconSecondary}>
                <FaGithub />
              </span>
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

export default function UseCases() {
  const [activeSegment, setActiveSegment] = useState<typeof segments[0] | null>(null);
  const backgroundRef = useRef<ParticleBackgroundHandle | null>(null);

  useEffect(() => {
    const footer = document.querySelector('footer');
    if (footer) {
      footer.style.position = 'relative';
      footer.style.zIndex = '10';
    }
  }, []);

  return (
    <Layout
      title="Use Cases"
      description="Who is Agent Kernel built for? Explore use cases for software companies, AI startups, domain experts, and product teams building production AI agents.">
    
      <div style={{ position: 'fixed', top: 0, left: 0, width: '100%', height: '100vh', zIndex: 0, pointerEvents: 'auto' }}>
        <Hero />
      </div>
      
      <div style={{ height: '100vh' }} />
      
      {/* Content that scroll over the hero section */}
      <main style={{ position: 'relative', zIndex: 10, backgroundColor: '#010002' }}>
        <UseCaseJourneyMap />
        <RealWorldUseCases />
        <Differentiators backgroundRef={backgroundRef} />
        <Community />
      </main>
      
      {activeSegment && (
        <SegmentModal segment={activeSegment} onClose={() => setActiveSegment(null)} />
      )}
    </Layout>
  );
}
