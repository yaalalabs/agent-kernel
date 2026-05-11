import React, { useState, useEffect, useRef } from 'react';
import Link from '@docusaurus/Link';
import Layout from '@theme/Layout';
import styles from './use-cases.module.css';
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
  MdVisibility,
  MdMessage,
  MdSpeed,
  MdNetworkCheck,
} from 'react-icons/md';
import { FaGithub, FaLock } from 'react-icons/fa';
import ParticleSphere from '../components/ParticleSphere';

gsap.registerPlugin(ScrollTrigger);

/* ─── Hero ──────────────────────────────────────────────────────────────── */

function Hero() {
  return (
    <section className={styles.hero}>
      {/* <div className={styles.heroOrb} />
      <div className={styles.heroGrid} /> */}
      <div className="container">
        <div className={styles.heroContent}>
          <h1 className={styles.heroTitle}>Who Is Agent Kernel Built For?</h1>
          <p className={styles.heroSubtitle}>
            Agent Kernel is an open-source runtime that lets you build, test, and deploy AI agents
            to production in days instead of months. It works with any major AI framework — OpenAI,
            LangGraph, CrewAI, Google ADK — and can run agents from multiple frameworks together in
            a single runtime. It deploys to AWS, Azure, or your own servers with zero platform code.
          </p>
          <div className={styles.heroButtons}>
            <Link className={`button button--primary button--lg ${styles.btnPrimary}`} to="/docs">
              Get Started →
            </Link>
            <Link className={`button button--secondary button--lg ${styles.btnSecondary}`} to="/features">
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

/* ─── Segment Tiles ─────────────────────────────────────────────────────── */

// function SegmentTilesSection({ onOpen }: { onOpen: (s: typeof segments[0]) => void }) {
//   return (
//     <section className={styles.tilesSection}>
//       <div className="container">
//         <div className={styles.tilesGrid}>
//           {segments.map(s => (
//             <div key={s.id} className={`${styles.tile} ${styles[`tile_${s.accent}`]}`}>
//               <div className={`${styles.tileIconWrap} ${styles[`tileIconWrap_${s.accent}`]}`}>
//                 {s.icon}
//               </div>
//               <h3 className={styles.tileTitle}>{s.title}</h3>
//               <p className={styles.tileSub}>{s.subtitle}</p>
//               <button
//                 className={`${styles.tileBtn} ${s.accent === 'violet' ? styles.tileBtn_violet : ''}`}
//                 onClick={() => onOpen(s)}
//               >
//                 Learn More
//               </button>
//             </div>
//           ))}
//         </div>
//       </div>
//     </section>
//   );
// }

function Differentiators() {
  const gridRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const cards = gridRef.current?.querySelectorAll(`.${styles.bentoCard}`);
    if (!cards || cards.length === 0) return;

    gsap.fromTo(
      cards,
      {
        opacity: 0,
        y: 30,
      },
      {
        opacity: 1,
        y: 0,
        duration: 0.6,
        stagger: 0.08,
        ease: 'cubic-bezier(0.22, 1, 0.36, 1)',
        scrollTrigger: {
          trigger: gridRef.current,
          start: 'top 70%',
          end: 'top 30%',
          scrub: false,
          once: true,
        },
      }
    );
  }, []);

  return (
    <section className={styles.diffSection}>
      <div className="container">
        <div className={styles.sectionHeader}>
          <h2 className={styles.sectionTitle}>Why Teams Choose Agent Kernel</h2>
          <p className={styles.sectionSubtitle}>
            What makes Agent Kernel different from rolling your own or using other platforms.
          </p>
        </div>
        <div className={styles.bentoGrid} ref={gridRef}>

          <div className={`${styles.bentoCard} ${styles.bentoWide}`}>
            <div className={styles.bentoIcon}><MdSwapHoriz /></div>
            <span className={styles.bentoTag}>Core differentiator</span>
            <h3 className={styles.bentoTitle}>Framework-Agnostic</h3>
            <p className={styles.bentoDesc}>The only runtime that lets you swap between OpenAI, CrewAI, LangGraph, and Google ADK with near-zero code change — and run all of them simultaneously in a single runtime.</p>
          </div>

          <div className={`${styles.bentoCard} ${styles.bentoNarrow}`}>
            <div className={styles.bentoIcon}><MdCloud /></div>
            <h3 className={styles.bentoTitle}>Multi-Cloud Native</h3>
            <p className={styles.bentoDesc}>Same agent code deploys to AWS and Azure out of the box. No other AI agent runtime offers this.</p>
          </div>

          <div className={`${styles.bentoCard} ${styles.bentoThird}`}>
            <div className={styles.bentoIcon}><MdSpeed /></div>
            <h3 className={styles.bentoTitle}>Full Lifecycle</h3>
            <p className={styles.bentoDesc}>Build → Test → Deploy → Monitor. One tool, from Python script to multi-AZ production cluster.</p>
          </div>

          <div className={`${styles.bentoCard} ${styles.bentoThird}`}>
            <div className={styles.bentoIcon}><MdCode /></div>
            <h3 className={styles.bentoTitle}>Lightweight</h3>
            <p className={styles.bentoDesc}>A thin adapter layer, not a heavy abstraction. Bring your existing agent code and wrap it in minutes.</p>
          </div>

          <div className={`${styles.bentoCard} ${styles.bentoThird}`}>
            <div className={styles.bentoIcon}><MdSecurity /></div>
            <h3 className={styles.bentoTitle}>Production-Ready from Day One</h3>
            <p className={styles.bentoDesc}>Fault tolerance, guardrails, observability, and session management built in — not bolted on later.</p>
          </div>

          <div className={`${styles.bentoCard} ${styles.bentoNarrow}`}>
            <div className={styles.bentoIcon}><MdMessage /></div>
            <h3 className={styles.bentoTitle}>Built-in Messaging</h3>
            <p className={styles.bentoDesc}>Slack, WhatsApp, Instagram, Telegram, Messenger, Gmail — reach users on day one, not after months of integration work.</p>
          </div>

          <div className={`${styles.bentoCard} ${styles.bentoWide}`}>
            <div className={styles.bentoIcon}><FaLock /></div>
            <span className={styles.bentoTag}>Apache 2.0</span>
            <h3 className={styles.bentoTitle}>Open-Source</h3>
            <p className={styles.bentoDesc}>No usage fees, no proprietary lock-in, community-driven. Full access to the codebase — fork it, extend it, contribute back.</p>
          </div>

          <div className={`${styles.bentoCard} ${styles.bentoFull}`}>
            <div className={styles.bentoIcon}><MdNetworkCheck /></div>
            <div>
              <h3 className={styles.bentoTitle}>Protocol Support</h3>
              <p className={styles.bentoDesc}>MCP (Model Context Protocol) server and A2A (Agent-to-Agent) server modes for future-proof agent architectures and ecosystem compatibility.</p>
            </div>
          </div>

        </div>
      </div>
    </section>
  );
}

/* ─── Final CTA ─────────────────────────────────────────────────────────── */

function FinalCTA() {
  return (
    <section className={styles.ctaSection}>
      <div className={styles.ctaGlow} />
      <div className="container">
        <div className={styles.ctaContent}>
          <h2 className={styles.ctaTitle}>Get started in minutes — it's free and open-source.</h2>
          <p className={styles.ctaSubtitle}>
            Apache 2.0 license. No usage fees. No vendor lock-in. Just install, build, and ship.
          </p>
          <div className={styles.ctaButtons}>
            <Link className={`button button--primary button--lg ${styles.btnPrimary}`} to="/docs">
              Get Started →
            </Link>
            <Link
              className={`button button--secondary button--lg ${styles.btnSecondary}`}
              to="https://github.com/yaalalabs/agent-kernel"
              target="_blank"
              rel="noopener noreferrer">
              <FaGithub style={{ marginRight: '8px' }} />
              View on GitHub
            </Link>
          </div>
        </div>
      </div>
    </section>
  );
}

/* ─── Page Export ───────────────────────────────────────────────────────── */

export default function UseCases() {
  const [activeSegment, setActiveSegment] = useState<typeof segments[0] | null>(null);

  return (
    <Layout
      title="Use Cases"
      description="Who is Agent Kernel built for? Explore use cases for software companies, AI startups, domain experts, and product teams building production AI agents.">
      <ParticleSphere />
      <Hero />
      <main>
        <UseCaseJourneyMap />
        <Differentiators />
        {/* <SegmentTilesSection onOpen={setActiveSegment} /> */}
        {/* <FinalCTA /> */}
      </main>
      {activeSegment && (
        <SegmentModal segment={activeSegment} onClose={() => setActiveSegment(null)} />
      )}
    </Layout>
  );
}
