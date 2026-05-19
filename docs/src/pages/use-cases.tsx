import { useState, useEffect, useRef, useCallback } from 'react';
import Link from '@docusaurus/Link';
import Layout from '@theme/Layout';
import styles from './use-cases.module.css';
import featureStyles from './features.module.css';
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
};

/* ─── Hero ──────────────────────────────────────────────────────────────── */

function Hero() {
  const titleRef = useRef<HTMLHeadingElement>(null);
  const subtitleRef = useRef<HTMLParagraphElement>(null);
  const buttonsRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const tl = gsap.timeline();

    gsap.set([titleRef.current, subtitleRef.current, buttonsRef.current], {
      opacity: 0,
      y: 30,
    });

    tl.to(titleRef.current, {
      opacity: 1,
      y: 0,
      duration: 0.8,
      ease: 'power2.out',
    })
      .to(
        subtitleRef.current,
        {
          opacity: 1,
          y: 0,
          duration: 0.6,
          ease: 'power2.out',
        },
        '-=0.4',
      )
      .to(
        buttonsRef.current,
        {
          opacity: 1,
          y: 0,
          duration: 0.5,
          ease: 'power2.out',
        },
        '-=0.2',
      );
  }, []);

  return (
    <section className={styles.hero}>
      <div className="container">
        <div className={styles.heroContent}>
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
    color: '#40BBDE',
    title: 'Framework-Neutral',
    desc: 'The only runtime that lets you bring inswap between  agents written from OpenAI Agents,  CrewAI, LangGraph, and Google ADK, Smolagents, LiveKit with near-zero code change — and run all of them simultaneously in a single runtime.',
  },
  {
    icon: <MdCloud />,
    color: '#8E5DFF',
    title: 'Multi-Cloud Native',
    desc: 'Same agent code deploys to AWS and Azure out of the box. No other AI agent runtime offers this out of the box.',
  },
  {
    icon: <MdSpeed />,
    color: '#F7A544',
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
    color: '#DB4444',
    title: 'Production-Ready',
    desc: 'Fault tolerance, guardrails, observability, and session management built in from day one — not bolted on later.',
  },
  {
    icon: <MdMessage />,
    color: '#73D0EB',
    title: 'Built-in Messaging',
    desc: 'Slack, WhatsApp, Instagram, Telegram, Messenger, Gmail — ship working integrations on day one, not months later.',
  },
  {
    icon: <FaLock />,
    color: '#B391FF',
    title: 'Open-Source',
    desc: 'No usage fees, no proprietary lock-in. Community-driven with full codebase access — fork it, extend it, contribute back.',
  },
  {
    icon: <MdNetworkCheck />,
    color: '#F7BC77',
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
  return (
    <section
      className={`${featureStyles.section} ${featureStyles.coreFeaturesSection} ${styles.realWorldSection}`}
    >
      <div className="container">
        <div className={featureStyles.sectionHeader}>
          <h2 className={featureStyles.sectionTitle}>Real world use cases</h2>
        </div>
        <ul className={`${featureStyles.featuresGrid} ${styles.realWorldCasesGrid}`}>
          {REAL_WORLD_USE_CASES.map((useCase, i) => (
            <li key={useCase.title} className={featureStyles.featureGridCell}>
              <Link
                to={useCase.link}
                className={`${featureStyles.featureCard} ${styles.realWorldCardLink}`}
              >
                <div className={featureStyles.featureCardHeader}>
                  <span className={featureStyles.featureIndex}>{String(i + 1).padStart(2, '0')}</span>
                </div>
                <div className={featureStyles.featureCardBody}>
                  <h3 className={featureStyles.featureTitle}>{useCase.title}</h3>
                  <p className={featureStyles.featureDescription}>{useCase.description}</p>
                </div>
                <span className={featureStyles.featureLink}>Read blog →</span>
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
  const cardRefs = useRef<(HTMLDivElement | null)[]>([]);
  const svgRef = useRef<SVGSVGElement>(null);
  const observerStateRef = useRef(false);

  const drawLines = useCallback(() => {
    const container = containerRef.current;
    const hub = hubRef.current;
    const svg = svgRef.current;
    if (!container || !hub || !svg) return;

    const cRect = container.getBoundingClientRect();
    const hRect = hub.getBoundingClientRect();
    const hx = hRect.left + hRect.width / 2 - cRect.left;
    const hy = hRect.top + hRect.height / 2 - cRect.top;

    svg.setAttribute('viewBox', `0 0 ${cRect.width} ${cRect.height}`);

    svg.innerHTML = `
      <defs>
        <filter id="lineGlow" x="-80%" y="-80%" width="260%" height="260%">
          <feGaussianBlur stdDeviation="5" result="blur"/>
          <feMerge><feMergeNode in="blur"/><feMergeNode in="SourceGraphic"/></feMerge>
        </filter>
        <filter id="dotGlow" x="-300%" y="-300%" width="700%" height="700%">
          <feGaussianBlur stdDeviation="4" result="blur"/>
          <feMerge><feMergeNode in="blur"/><feMergeNode in="SourceGraphic"/></feMerge>
        </filter>
      </defs>`;

    const durations = [2.8, 3.4, 2.5, 3.1, 2.9, 3.6, 2.6, 3.2];

    cardRefs.current.forEach((card, i) => {
      if (!card) return;
      const r = card.getBoundingClientRect();
      if (r.width === 0) return;
      const cx = r.left + r.width / 2 - cRect.left;
      const cy = r.top + r.height / 2 - cRect.top;

      // Quadratic bezier with a slight perpendicular curve
      const midX = (hx + cx) / 2;
      const midY = (hy + cy) / 2;
      const dx = cx - hx;
      const dy = cy - hy;
      const len = Math.sqrt(dx * dx + dy * dy) || 1;
      const cpX = midX + (-dy / len) * 35;
      const cpY = midY + (dx / len) * 35;
      const pathD = `M ${hx} ${hy} Q ${cpX} ${cpY} ${cx} ${cy}`;
      const pathId = `op${i}`;

      // Halo line
      const haloPath = document.createElementNS('http://www.w3.org/2000/svg', 'path');
      haloPath.setAttribute('d', pathD);
      haloPath.setAttribute('stroke', 'rgba(0,221,255,0.1)');
      haloPath.setAttribute('stroke-width', '8');
      haloPath.setAttribute('fill', 'none');
      haloPath.setAttribute('filter', 'url(#lineGlow)');
      svg.appendChild(haloPath);

      // Main line
      const path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
      path.setAttribute('id', pathId);
      path.setAttribute('d', pathD);
      path.setAttribute('stroke', 'rgba(0,221,255,0.28)');
      path.setAttribute('stroke-width', '1.5');
      path.setAttribute('fill', 'none');
      svg.appendChild(path);

      // Endpoint dot
      const endDot = document.createElementNS('http://www.w3.org/2000/svg', 'circle');
      endDot.setAttribute('cx', String(cx));
      endDot.setAttribute('cy', String(cy));
      endDot.setAttribute('r', '4');
      endDot.setAttribute('fill', 'rgba(0,221,255,0.55)');
      endDot.setAttribute('filter', 'url(#dotGlow)');
      svg.appendChild(endDot);

      // Traveling dot
      const traveler = document.createElementNS('http://www.w3.org/2000/svg', 'circle');
      traveler.setAttribute('r', '3.5');
      traveler.setAttribute('fill', '#00DDFF');
      traveler.setAttribute('filter', 'url(#dotGlow)');
      const motion = document.createElementNS('http://www.w3.org/2000/svg', 'animateMotion');
      motion.setAttribute('dur', `${durations[i]}s`);
      motion.setAttribute('repeatCount', 'indefinite');
      motion.setAttribute('begin', `${i * 0.38}s`);
      const mpath = document.createElementNS('http://www.w3.org/2000/svg', 'mpath');
      mpath.setAttribute('href', `#${pathId}`);
      motion.appendChild(mpath);
      traveler.appendChild(motion);
      svg.appendChild(traveler);
    });
  }, []);

  useEffect(() => {
    const timer = setTimeout(drawLines, 80);
    const ro = new ResizeObserver(drawLines);
    if (containerRef.current) ro.observe(containerRef.current);
    window.addEventListener('resize', drawLines);
    return () => {
      clearTimeout(timer);
      ro.disconnect();
      window.removeEventListener('resize', drawLines);
    };
  }, [drawLines]);

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
    const els = containerRef.current?.querySelectorAll(
      `.${styles.orbitCard}, .${styles.orbitHub}`
    );
    if (!els?.length) return;
    gsap.fromTo(
      els,
      { opacity: 0, scale: 0.88 },
      {
        opacity: 1,
        scale: 1,
        duration: 0.5,
        stagger: 0.07,
        ease: 'back.out(1.2)',
        scrollTrigger: {
          trigger: containerRef.current,
          start: 'top 75%',
          once: true,
        },
        onComplete: drawLines,
      }
    );
  }, [drawLines]);

  return (
    <section className={styles.diffSection}>
      <div className="container">
        <div className={styles.sectionHeader}>
          <h2 className={styles.sectionTitle}>Why Teams Choose Agent Kernel</h2>
          <p className={styles.sectionSubtitle}>
            What makes Agent Kernel different from rolling your own or using other platforms.
          </p>
        </div>

        <div ref={containerRef} className={styles.orbitScene}>
          {/* SVG connector lines — drawn dynamically */}
          <svg ref={svgRef} className={styles.orbitSvg} aria-hidden="true" />

          {/* 8 surrounding cards */}
          {ORBIT_CARDS.map((card, i) => (
            <div
              key={i}
              ref={el => { cardRefs.current[i] = el; }}
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
            <div className={styles.orbitHubGlowCore} />
            <img
              src="/img/branding/agent-kernel-icon-color.svg"
              alt="Agent Kernel"
              className={styles.orbitHubIcon}
            />
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

  return (
    <Layout
      title="Use Cases"
      description="Who is Agent Kernel built for? Explore use cases for software companies, AI startups, domain experts, and product teams building production AI agents.">
      <PlantParticlesBackground ref={backgroundRef} modelUrl='models/brain.glb' />
      <Hero />
      <main>
        <UseCaseJourneyMap />
        <RealWorldUseCases />
        <Differentiators backgroundRef={backgroundRef} />
      </main>
      {activeSegment && (
        <SegmentModal segment={activeSegment} onClose={() => setActiveSegment(null)} />
      )}
    </Layout>
  );
}
