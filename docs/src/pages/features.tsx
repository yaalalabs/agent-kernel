import React, { useId, useState, useEffect, useRef } from 'react';
import Link from '@docusaurus/Link';
import Layout from '@theme/Layout';
import styles from './features.module.css';
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
  MdMenuBook,
  MdExtension,
  MdHub,
} from 'react-icons/md';
import { FaSlack, FaWhatsapp, FaInstagram, FaTelegram, FaGithub } from 'react-icons/fa';
import { SiGmail, SiGooglegemini, SiLangchain, SiHuggingface } from 'react-icons/si';
import { FaFacebookMessenger } from 'react-icons/fa6';
import { TbBrandTeams } from 'react-icons/tb';
import PlantParticlesBackground from '../components/PlantParticlesBackground';

/** Stable fragment ids for in-page navigation (diagram + deep links). */
const FEATURE_ANCHORS = {
  problem: 'features-problem',
  core: 'features-core',
  frameworks: 'features-frameworks',
  testing: 'features-testing',
  messaging: 'features-messaging',
  protocols: 'features-protocols',
  cta: 'features-cta',
} as const;

type FeatureAnchorKey = keyof typeof FEATURE_ANCHORS;

const FEATURE_PAGE_MAP: {
  anchor: FeatureAnchorKey;
  number: string;
  title: string;
  hint: string;
}[] = [
  {
    anchor: 'problem',
    number: '01',
    title: 'The Problem',
    hint: 'What Agent Kernel solves',
  },
  {
    anchor: 'core',
    number: '02',
    title: 'Core Capabilities',
    hint: 'Runtime, memory, hooks, and more',
  },
  {
    anchor: 'frameworks',
    number: '03',
    title: 'Framework Support',
    hint: 'One runtime, any framework',
  },
  {
    anchor: 'testing',
    number: '04',
    title: 'Testing',
    hint: 'CLI, pytest, comparison modes',
  },
  {
    anchor: 'messaging',
    number: '05',
    title: 'Messaging',
    hint: 'Slack, WhatsApp, and more',
  },
  {
    anchor: 'protocols',
    number: '06',
    title: 'Protocol Support',
    hint: 'MCP and A2A out of the box',
  },
  {
    anchor: 'cta',
    number: '07',
    title: 'Get Started',
    hint: 'Docs, use cases, GitHub',
  },
];

function scrollToFeaturesSection(anchor: FeatureAnchorKey) {
  const id = FEATURE_ANCHORS[anchor];
  const el = typeof document !== 'undefined' ? document.getElementById(id) : null;
  el?.scrollIntoView({ behavior: 'smooth', block: 'start' });
}

/* ─── Hero ──────────────────────────────────────────────────────────────── */

function Hero() {
  return (
    <section className={styles.hero}>
      <div className="container">
        <div className={styles.heroContent}>
          <h1 className={styles.heroTitle}>Everything You Need to Build,<br />Run, and Scale AI Agents</h1>
          <p className={styles.heroSubtitle}>
            From runtime and memory to guardrails, observability, testing, and multi-cloud deployment.
          </p>
          <div className={styles.heroButtons}>
            <Link className={`button button--primary button--lg ${styles.btnPrimary}`} to="/docs">
              <span className={styles.btnIcon}>→</span>
              Get Started
            </Link>
            <Link className={`button button--secondary button--lg ${styles.btnSecondary}`} to="/use-cases">
              <span className={styles.btnIconSecondary}>→</span>
              Find Your Use Case
            </Link>
          </div>
        </div>
      </div>
    </section>
  );
}

/* ─── Page map (diagram) ────────────────────────────────────────────────── */

function FeaturesPageMap() {
  const gradId = useId().replace(/:/g, '');
  const sectionRef = useRef<HTMLDivElement>(null);
  const [visible, setVisible] = useState(false);
  const topRow = FEATURE_PAGE_MAP.slice(0, 3);
  const bottomRow = FEATURE_PAGE_MAP.slice(3, 7);

  useEffect(() => {
    if (
      typeof window !== 'undefined' &&
      window.matchMedia('(prefers-reduced-motion: reduce)').matches
    ) {
      setVisible(true);
      return;
    }
    const el = sectionRef.current;
    if (!el) return;
    const observer = new IntersectionObserver(
      ([entry]) => {
        if (entry.isIntersecting) {
          setVisible(true);
          observer.disconnect();
        }
      },
      { threshold: 0.1 }
    );
    observer.observe(el);
    return () => observer.disconnect();
  }, []);

  const reducedMotion =
    typeof window !== 'undefined' &&
    window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  const COL_X_TOP = [143, 450, 757] as const;
  const COL_X_BOT = [113, 338, 563, 788] as const;

  // Top strip
  const topLines = COL_X_TOP.map((x, i) => ({
    id: `${gradId}T${i}`,
    d: `M ${x} 0 L 450 60`,
    len: Math.round(Math.sqrt(Math.pow(x - 450, 2) + 3600)),
    delay: 0.20 + i * 0.07,
  }));

  // Bottom strip
  const botLines = COL_X_BOT.map((x, i) => ({
    id: `${gradId}B${i}`,
    d: `M 450 0 L ${x} 60`,
    len: Math.round(Math.sqrt(Math.pow(x - 450, 2) + 3600)),
    delay: 0.41 + i * 0.07,
  }));

  const topGlowId = `${gradId}TGlow`;
  const botGlowId = `${gradId}BGlow`;

  const TEAL      = 'rgba(0,213,190,1)';
  const TEAL_LINE = 'rgba(0,213,190,0.28)';
  const TEAL_HALO = 'rgba(0,213,190,0.1)';

  const topParticles = [
    { pathId: `${gradId}T0`, delay: '0.9s',  dur: '1.8s', color: TEAL },
    { pathId: `${gradId}T1`, delay: '1.5s',  dur: '1.4s', color: TEAL },
    { pathId: `${gradId}T2`, delay: '1.2s',  dur: '1.8s', color: TEAL },
  ];
  const botParticles = [
    { pathId: `${gradId}B0`, delay: '2.0s', dur: '1.8s', color: TEAL },
    { pathId: `${gradId}B1`, delay: '2.35s', dur: '1.4s', color: TEAL },
    { pathId: `${gradId}B2`, delay: '2.1s', dur: '1.8s', color: TEAL },
    { pathId: `${gradId}B3`, delay: '2.55s', dur: '1.5s', color: TEAL },
  ];

  return (
    <div ref={sectionRef} className={styles.pageMapSection} role="region" aria-labelledby="features-page-map-heading">
      <div className="container">
        <div className={styles.sectionHeader}>
          <span className={styles.sectionNumber}>Feature Map</span>
          <h2 id="features-page-map-heading" className={styles.sectionTitle}>
            Everything Agent Kernel Does
          </h2>
          <p className={styles.sectionSubtitle}>
            Seven production-ready capabilities — explore any area below.
          </p>
        </div>

        <div className={styles.pageMapDiagram}>

          {/* ── Layer 1: top row nodes ── */}
          <div className={styles.pageMapTopRow}>
            {topRow.map((item, i) => (
              <button
                key={item.anchor}
                type="button"
                className={`${styles.pageMapNode} ${visible ? styles.pageMapNodeIn : ''}`}
                style={{ '--node-delay': `${i * 80}ms` } as React.CSSProperties}
                onClick={() => scrollToFeaturesSection(item.anchor)}>
                <span className={styles.pageMapNodeNumber}>{item.number}</span>
                <span className={styles.pageMapNodeTitle}>{item.title}</span>
                <span className={styles.pageMapNodeHint}>{item.hint}</span>
              </button>
            ))}
          </div>

          {/* ── Connector: top nodes → hub ── */}
          <svg className={styles.pageMapConnector} viewBox="0 0 900 60" preserveAspectRatio="none" aria-hidden>
            <defs>
              <filter id={topGlowId} x="-80%" y="-80%" width="260%" height="260%">
                <feGaussianBlur stdDeviation="4" result="blur" />
                <feMerge><feMergeNode in="blur" /><feMergeNode in="SourceGraphic" /></feMerge>
              </filter>
              <filter id={`${topGlowId}Halo`} x="-80%" y="-80%" width="260%" height="260%">
                <feGaussianBlur stdDeviation="5" result="blur" />
                <feMerge><feMergeNode in="blur" /><feMergeNode in="SourceGraphic" /></feMerge>
              </filter>
              {topLines.map(l => <path key={l.id} id={l.id} d={l.d} />)}
            </defs>
            {/* Halo lines */}
            {topLines.map(l => (
              <path key={`halo-${l.id}`} d={l.d} fill="none"
                stroke={TEAL_HALO} strokeWidth="8"
                filter={`url(#${topGlowId}Halo)`}
              />
            ))}
            {/* Main lines */}
            {topLines.map(l => (
              <path key={l.id} d={l.d} fill="none"
                stroke={TEAL_LINE} strokeWidth="1.5"
                strokeDasharray={l.len} strokeDashoffset={visible ? 0 : l.len}
                style={{ transition: `stroke-dashoffset 0.55s cubic-bezier(0.22, 1, 0.36, 1) ${l.delay}s` }}
              />
            ))}
            {visible && !reducedMotion && topParticles.map((p, i) => (
              <circle key={i} r="3.5" fill={p.color} filter={`url(#${topGlowId})`} opacity="0.9">
                <animateMotion dur={p.dur} repeatCount="indefinite" begin={p.delay}>
                  <mpath href={`#${p.pathId}`} />
                </animateMotion>
              </circle>
            ))}
          </svg>

          {/* ── Hub ── */}
          <div className={`${styles.pageMapHub} ${visible ? styles.pageMapHubIn : ''}`}>
            <img
              src="/img/branding/agent-kernel-icon-color.svg"
              alt="Agent Kernel"
              className={styles.pageMapHubIcon}
            />
          </div>

          {/* ── Connector: hub → bottom nodes ── */}
          <svg className={styles.pageMapConnector} viewBox="0 0 900 60" preserveAspectRatio="none" aria-hidden>
            <defs>
              <filter id={botGlowId} x="-80%" y="-80%" width="260%" height="260%">
                <feGaussianBlur stdDeviation="4" result="blur" />
                <feMerge><feMergeNode in="blur" /><feMergeNode in="SourceGraphic" /></feMerge>
              </filter>
              <filter id={`${botGlowId}Halo`} x="-80%" y="-80%" width="260%" height="260%">
                <feGaussianBlur stdDeviation="5" result="blur" />
                <feMerge><feMergeNode in="blur" /><feMergeNode in="SourceGraphic" /></feMerge>
              </filter>
              {botLines.map(l => <path key={l.id} id={l.id} d={l.d} />)}
            </defs>
            {/* Halo lines */}
            {botLines.map(l => (
              <path key={`halo-${l.id}`} d={l.d} fill="none"
                stroke={TEAL_HALO} strokeWidth="8"
                filter={`url(#${botGlowId}Halo)`}
              />
            ))}
            {/* Main lines */}
            {botLines.map(l => (
              <path key={l.id} d={l.d} fill="none"
                stroke={TEAL_LINE} strokeWidth="1.5"
                strokeDasharray={l.len} strokeDashoffset={visible ? 0 : l.len}
                style={{ transition: `stroke-dashoffset 0.55s cubic-bezier(0.22, 1, 0.36, 1) ${l.delay}s` }}
              />
            ))}
            {visible && !reducedMotion && botParticles.map((p, i) => (
              <circle key={i} r="3.5" fill={p.color} filter={`url(#${botGlowId})`} opacity="0.9">
                <animateMotion dur={p.dur} repeatCount="indefinite" begin={p.delay}>
                  <mpath href={`#${p.pathId}`} />
                </animateMotion>
              </circle>
            ))}
          </svg>

          {/* ── Layer 3: bottom row nodes ── */}
          <div className={styles.pageMapBottomRow}>
            {bottomRow.map((item, i) => (
              <button
                key={item.anchor}
                type="button"
                className={`${styles.pageMapNode} ${visible ? styles.pageMapNodeIn : ''}`}
                style={{ '--node-delay': `${300 + i * 80}ms` } as React.CSSProperties}
                onClick={() => scrollToFeaturesSection(item.anchor)}>
                <span className={styles.pageMapNodeNumber}>{item.number}</span>
                <span className={styles.pageMapNodeTitle}>{item.title}</span>
                <span className={styles.pageMapNodeHint}>{item.hint}</span>
              </button>
            ))}
          </div>

        </div>
      </div>
    </div>
  );
}

/* ─── Problem Table ─────────────────────────────────────────────────────── */

function ProblemTable() {
  const rows = [
    {
      problem: 'Platform engineering',
      without: 'Build REST APIs, auth, session management, deployment pipelines from scratch',
      with: 'All included out of the box',
    },
    {
      problem: 'Framework lock-in',
      without: 'Rewrite everything if you switch from LangGraph to OpenAI',
      with: 'Change 2 import lines — everything else stays',
    },
    {
      problem: 'Cloud lock-in',
      without: 'AWS-specific code everywhere',
      with: 'Same code deploys to AWS, Azure, or on-prem',
    },
    {
      problem: 'Memory & state',
      without: 'Build your own conversation tracking, caching, and persistence',
      with: 'Built-in with multiple backends',
    },
    {
      problem: 'Knowledge Bases',
      without: 'Build your own database connectors. Handle data complexity, separate tools for storage and retrieval',
      with: 'Built-in with multiple knowledge sources',
    },
    {
      problem: 'Messaging integrations',
      without: 'Build custom Slack/WhatsApp bots from scratch',
      with: 'Built-in handlers, plug and play',
    },
    {
      problem: 'Testing',
      without: 'No standard way to test AI agents',
      with: 'pytest-integrated test framework',
    },
    {
      problem: 'Observability',
      without: 'Manual instrumentation',
      with: 'LangFuse/OpenLLMetry with one config line',
    },
    {
      problem: 'Guardrails & safety',
      without: 'Build custom content filters',
      with: 'OpenAI and Bedrock guardrails built in',
    },
    {
      problem: 'Deployment',
      without: 'Write Terraform/CDK yourself',
      with: 'Pre-built Terraform modules for AWS & Azure',
    },
    {
      problem: 'Time to production',
      without: 'Months',
      with: 'Days to weeks',
      highlight: true,
    },
  ];

  return (
    <section id={FEATURE_ANCHORS.problem} className={`${styles.section} ${styles.pageAnchor}`}>
      <div className="container">
        <div className={styles.sectionHeader}>
          <span className={styles.sectionNumber}>01</span>
          <h2 className={styles.sectionTitle}>The Problem Agent Kernel Solves</h2>
          <p className={styles.sectionSubtitle}>
            Building production AI agents today involves solving many hard problems that have nothing
            to do with the actual agent intelligence.
          </p>
        </div>
        <div className={styles.problemTable}>
          <div className={styles.problemTableHeader}>
            <div className={styles.problemCol}>Area</div>
            <div className={styles.problemCol}>Without Agent Kernel</div>
            <div className={styles.problemCol}>With Agent Kernel</div>
          </div>
          {rows.map((row, i) => (
            <div key={i} className={`${styles.problemRow} ${row.highlight ? styles.problemRowHighlight : ''}`}>
              <div className={`${styles.problemColLabel}`}>{row.problem}</div>
              <div className={styles.problemColBad}>
                <span className={styles.xIcon}>✕</span>
                {row.without}
              </div>
              <div className={styles.problemColGood}>
                <span className={styles.checkIcon}><MdCheck /></span>
                {row.with}
              </div>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}

/* ─── Core Features ─────────────────────────────────────────────────────── */

function CoreFeatures() {
  const features = [
    {
      icon: <MdCode />,
      title: 'Six Core Abstractions',
      description: 'Agent, Runner, Session, Module, Runtime, and Tools, a unified API across all frameworks. Build once, run on any supported framework.',
      highlights: ['Unified Python API', 'Framework adapters for 4 SDKs', 'Portable tool functions via ToolBuilder', 'Framework-agnostic hooks'],
      link: '/docs/core-concepts/overview',
    },
    {
      icon: <MdSwapHoriz />,
      title: 'Framework-Neutral Runtime',
      description: 'OpenAI Agents, LangGraph, CrewAI, and Google ADK, run them all simultaneously in one runtime. Switch frameworks by changing 2 import lines.',
      highlights: ['OpenAI Agents SDK', 'LangGraph', 'CrewAI', 'Google ADK'],
      link: '/docs/frameworks/overview',
    },
    {
      icon: <MdSettings />,
      title: 'Execution Hooks',
      description: 'Pre and post-execution hooks give you surgical control over every agent request, for any framework.',
      highlights: ['Pre-hooks: guardrails, RAG, auth, validation', 'Post-hooks: moderation, disclaimers, analytics', 'Hook chaining and composition', 'Early termination with custom responses'],
      link: '/docs/integrations/hooks',
    },
    {
      icon: <MdMemory />,
      title: 'Smart Memory Management',
      description: 'Volatile and non-volatile caching with identical APIs but different lifecycles. Swap backends with just environment variables.',
      highlights: ['Volatile: request-scoped, auto-clears', 'Non-volatile: session-persistent', 'Backends: In-memory, Redis, DynamoDB, Cosmos DB', 'Clean prompts, reduced token usage'],
      link: '/docs/architecture/memory-management',
    },
    {
      icon: <MdMenuBook />,
      title: 'Knowledge Bases',
      description:
        'Built-in retrieval for curated knowledge sources and storage for agent reinforcement learning. Neo4j, Starburst Galaxy, ChromaDB, and custom SQL data sources.',
      highlights: ['ChromaDB — vector/semantic search','Neo4j — entity and relationship graphs','Starburst Galaxy — SQL over MongoDB, Sheets, PostgreSQL','semantic_map keeps agent prompts portable',],
      link: '/docs/architecture/memory-management',
    },
    {
      icon: <MdCloud />,
      title: 'Multi-Cloud Deployment',
      description: 'One agent codebase deploys to AWS, and Azure and GCP with full Terraform modules. No vendor lock-in, ever.',
      highlights: ['AWS Lambda (Serverless)', 'AWS ECS/Fargate (Containerized)', 'Azure Functions (Serverless)', 'Azure Container Apps (Containerized)'],
      link: '/docs/deployment/overview',
    },
    {
      icon: <MdHealthAndSafety />,
      title: 'Fault Tolerance',
      description: 'Production-grade resilience with multi-AZ deployments, auto-recovery, health monitoring, and rolling deployments.',
      highlights: ['Multi-AZ for high availability', 'Automatic failure recovery', 'Health monitoring', 'Zero-downtime deployments'],
      link: '/docs/core-concepts/fault-tolerance',
    },
    {
      icon: <MdVisibility />,
      title: 'Observability',
      description: 'Full visibility into agent execution, LLM calls, and tool invocations. One config line to enable.',
      highlights: ['LangFuse integration', 'OpenLLMetry (OpenTelemetry-based)', 'Multi-level verbosity', 'Cost and latency tracking'],
      link: '/docs/advanced/traceability',
    },
    {
      icon: <MdSecurity />,
      title: 'Content Safety & Guardrails',
      description: 'Input and output guardrails that protect users and ensure compliance. Plugs in via execution hooks.',
      highlights: ['PII detection and redaction', 'Jailbreak prevention', 'Content moderation', 'Off-topic filtering'],
      link: '/docs/advanced/guardrails',
    },
    {
      icon: <MdNetworkCheck />,
      title: 'MCP & A2A Protocols',
      description: 'Expose agents as MCP tools or enable agent-to-agent communication via A2A protocol.',
      highlights: ['MCP Server mode', 'A2A Server mode', 'Cross-agent coordination', 'Protocol-future-proofed'],
      link: '/docs/api/mcp-server',
    },
  ];

  return (
    <section id={FEATURE_ANCHORS.core} className={`${styles.section} ${styles.pageAnchor}`}>
      <div className="container">
        <div className={styles.sectionHeader}>
          <span className={styles.sectionNumber}>02</span>
          <h2 className={styles.sectionTitle}>Core Capabilities</h2>
          <p className={styles.sectionSubtitle}>
            Everything you need to build, run, and scale production AI agents without building platform code.
          </p>
        </div>
        <div className={styles.featuresGrid}>
          {features.map((f, i) => (
            <div key={i} className={styles.featureCard}>
              <div className={styles.featureIcon}>{f.icon}</div>
              <h3 className={styles.featureTitle}>{f.title}</h3>
              <p className={styles.featureDescription}>{f.description}</p>
              <ul className={styles.featureHighlights}>
                {f.highlights.map((h, j) => <li key={j}>{h}</li>)}
              </ul>
              {f.link && (
                <Link to={f.link} className={styles.featureLink}>Learn more →</Link>
              )}
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}

/* ─── Framework Support ─────────────────────────────────────────────────── */

function FrameworkSupport() {
  const integrations = [
    {
      key: 'openai',
      name: 'OpenAI Agents SDK',
      description: 'Official OpenAI agents framework with full support for tools, handoffs, and streaming.',
      link: '/docs/frameworks/openai',
      logo: (
        <img
          src="/img/integrations/openai.svg"
          alt=""
          className={`${styles.frameworkLogoImg} ${styles.frameworkLogoImgInvert}`}
          width={120}
          height={32}
        />
      ),
    },
    {
      key: 'langgraph',
      name: 'LangGraph',
      description: 'Graph-based agent orchestration for complex stateful multi-actor applications.',
      link: '/docs/frameworks/langgraph',
      logo: (
        <SiLangchain
          className={`${styles.frameworkLogoIcon} ${styles.frameworkLogoLangchain}`}
          aria-hidden
        />
      ),
    },
    {
      key: 'google-adk',
      name: 'Google ADK',
      description: "Google's Agent Development Kit for advanced agent capabilities and Gemini integration.",
      link: '/docs/frameworks/google-adk',
      logo: (
        <SiGooglegemini
          className={`${styles.frameworkLogoIcon} ${styles.frameworkLogoGemini}`}
          aria-hidden
        />
      ),
    },
    {
      key: 'crewai',
      name: 'CrewAI',
      description: 'Role-based multi-agent framework for orchestrating collaborative AI workflows.',
      link: '/docs/frameworks/crewai',
      logo: (
        <img
          src="/img/integrations/crewai.svg"
          alt=""
          className={styles.frameworkLogoImg}
          width={140}
          height={48}
        />
      ),
    },
    {
      key: 'smolagents',
      name: 'Smolagents',
      description:
        "Hugging Face's Smolagents with first-class support for writing your own coding agents.",
      link: 'https://huggingface.co/docs/smolagents/index',
      external: true,
      logo: (
        <SiHuggingface
          className={`${styles.frameworkLogoIcon} ${styles.frameworkLogoHf}`}
          aria-hidden
        />
      ),
    },
    {
      key: 'livekit',
      name: 'LiveKit',
      description: 'LiveKit provides the complete stack for voice-based AI agents.',
      link: 'https://docs.livekit.io/',
      external: true,
      logo: (
        <img
          src="/img/integrations/livekit-mark.svg"
          alt=""
          className={styles.frameworkLogoImg}
          width={38}
          height={38}
        />
      ),
    },
  ];

  const multiFramework = {
    name: 'Multi-Framework',
    description: 'Run agents from multiple frameworks simultaneously in a single runtime — no glue code required.',
    link: '/docs/frameworks/multi-framework',
    badge: 'Agent Kernel',
    logo: (
      <img
        src="/img/branding/agent-kernel-icon-color.svg"
        alt=""
        className={styles.frameworkLogoImg}
        width={48}
        height={48}
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
      <span className={`${styles.frameworkLink} ${styles.frameworkLinkInline}`}>Learn more →</span>
    </>
  );

  const featuredInner = (
    <>
      <div className={styles.frameworkFeaturedAccent} aria-hidden />
      <div className={styles.frameworkFeaturedContent}>
        <div className={styles.frameworkFeaturedMain}>
          <div className={styles.frameworkFeaturedMark}>{multiFramework.logo}</div>
          <div className={styles.frameworkFeaturedText}>
            <p className={styles.frameworkFeaturedBadge}>{multiFramework.badge}</p>
            <h3 className={styles.frameworkFeaturedHeading}>{multiFramework.name}</h3>
            <p className={styles.frameworkFeaturedLead}>{multiFramework.description}</p>
          </div>
        </div>
        <span className={`${styles.frameworkLink} ${styles.frameworkFeaturedCta}`}>Learn more →</span>
      </div>
    </>
  );

  return (
    <section id={FEATURE_ANCHORS.frameworks} className={`${styles.section} ${styles.pageAnchor}`}>
      <div className="container">
        <div className={styles.sectionHeader}>
          <span className={styles.sectionNumber}>03</span>
          <h2 className={styles.sectionTitle}>One Runtime. Any Framework.</h2>
          <p className={styles.sectionSubtitle}>
            Use the best framework for each job — and run them all together in a single deployment.
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
                    rel="noopener noreferrer">
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

          <Link to={multiFramework.link} className={styles.frameworkFeaturedRow}>
            {featuredInner}
          </Link>
        </div>
      </div>
    </section>
  );
}

/* ─── Testing Section ───────────────────────────────────────────────────── */

function TestingSection() {
  const modes = [
    {
      icon: <MdSpeed />,
      name: 'Fuzzy Mode',
      description: 'Fast string matching with configurable thresholds using RapidFuzz. Ideal for deterministic outputs.',
      link: '/docs/testing/cli-testing#fuzzy-mode',
    },
    {
      icon: <MdBugReport />,
      name: 'Judge Mode',
      description: 'LLM-based semantic evaluation using Ragas. Handles paraphrasing and AI-generated variation.',
      link: '/docs/testing/cli-testing#judge-mode',
    },
    {
      icon: <MdTimer />,
      name: 'Fallback Mode',
      description: 'Tries fuzzy first, falls back to judge. The default -best of both worlds.',
      link: '/docs/testing/cli-testing#fallback-mode-default',
    },
  ];

  return (
    <section id={FEATURE_ANCHORS.testing} className={`${styles.section} ${styles.pageAnchor}`}>
      <div className="container">
        <div className={styles.sectionHeader}>
          <span className={styles.sectionNumber}>04</span>
          <h2 className={styles.sectionTitle}>Testing Framework</h2>
          <p className={styles.sectionSubtitle}>
            Test your agents like any other code. CLI testing for development, automated suites for CI/CD.
            Three comparison modes for every use case.
          </p>
        </div>
        <div className={styles.testingLayout}>
          <Link to="/docs/testing/cli-testing" className={styles.testingCard}>
            <MdTerminal className={styles.testingBigIcon} />
            <h3>CLI Testing</h3>
            <p>Interactive sessions for rapid development iteration and multi-agent testing.</p>
            <ul>
              <li>Interactive chat sessions</li>
              <li>Real-time feedback</li>
              <li>Persistent CLI sessions</li>
              <li>Multi-agent support</li>
            </ul>
            <span className={styles.featureLink}>Learn more →</span>
          </Link>
          <Link to="/docs/testing/automated-testing" className={styles.testingCard}>
            <MdCode className={styles.testingBigIcon} />
            <h3>Automated Tests</h3>
            <p>pytest-integrated test suites that run in CI/CD with session-scoped fixtures.</p>
            <ul>
              <li>pytest integration</li>
              <li>Session-scoped fixtures</li>
              <li>Ordered test execution</li>
              <li>CI/CD ready</li>
            </ul>
            <span className={styles.featureLink}>Learn more →</span>
          </Link>
        </div>
        <div className={styles.modesGrid}>
          {modes.map((m, i) => (
            <Link key={i} to={m.link} className={styles.modeCard}>
              <div className={styles.modeIcon}>{m.icon}</div>
              <h4 className={styles.modeName}>{m.name}</h4>
              <p className={styles.modeDescription}>{m.description}</p>
            </Link>
          ))}
        </div>
      </div>
    </section>
  );
}

/* ─── Messaging Section ─────────────────────────────────────────────────── */

function MessagingSection() {
  const platforms = [
    { name: 'Slack', icon: <FaSlack />, color: '#4A154B', link: '/docs/integrations/slack' },
    { name: 'Microsoft Teams', icon: <TbBrandTeams />, color: '#6264A7', link: '/docs/integrations/teams' },
    { name: 'WhatsApp', icon: <FaWhatsapp />, color: '#25D366', link: '/docs/integrations/whatsapp' },
    { name: 'Messenger', icon: <FaFacebookMessenger />, color: '#0084FF', link: '/docs/integrations/messenger' },
    { name: 'Telegram', icon: <FaTelegram />, color: '#0088CC', link: '/docs/integrations/telegram' },
    { name: 'Instagram', icon: <FaInstagram />, color: '#E4405F', link: '/docs/integrations/instagram' },
    { name: 'Gmail', icon: <SiGmail />, color: '#EA4335', link: '/docs/integrations/gmail' },
  ];

  return (
    <section id={FEATURE_ANCHORS.messaging} className={`${styles.section} ${styles.pageAnchor}`}>
      <div className="container">
        <div className={styles.sectionHeader}>
          <span className={styles.sectionNumber}>05</span>
          <h2 className={styles.sectionTitle}>Messaging Integrations</h2>
          <p className={styles.sectionSubtitle}>
            Built-in handlers for the world's most popular messaging platforms.
            No custom bot code required — just plug and play.
          </p>
        </div>
        <div className={styles.messagingGrid}>
          {platforms.map((p, i) => (
            <Link key={i} to={p.link} className={styles.messagingCard}>
              <div className={styles.messagingIcon} style={{ color: p.color }}>{p.icon}</div>
              <h3 className={styles.messagingName}>{p.name}</h3>
            </Link>
          ))}
        </div>
        <div className={styles.sectionFooter}>
          <Link to="/docs/integrations/overview" className={styles.sectionLink}>
            View integration docs →
          </Link>
        </div>
      </div>
    </section>
  );
}

/* ─── Protocol Support ──────────────────────────────────────────────────── */

function ProtocolSupport() {
  return (
    <section id={FEATURE_ANCHORS.protocols} className={`${styles.section} ${styles.pageAnchor}`}>
      <div className="container">
        <div className={styles.sectionHeader}>
          <span className={styles.sectionNumber}>06</span>
          <h2 className={styles.sectionTitle}>Protocol Support</h2>
          <p className={styles.sectionSubtitle}>
            Standard protocols for tool connectivity and multi-agent coordination — wired into the runtime.
          </p>
        </div>
        <div className={styles.testingLayout}>
          <Link to="/docs/api/mcp-server" className={styles.testingCard}>
            <MdExtension className={styles.testingBigIcon} />
            <h3>MCP — Model Context Protocol</h3>
            <p>
              Model Context Protocol (MCP) is a standardized interface that lets AI models connect to external
              tools, data sources, and services in a structured, consistent way. It acts as a bridge between an
              AI&apos;s reasoning and real-world actions, enabling agents to retrieve information and execute tasks
              reliably. Agent Kernel natively supports running an MCP server, including exposing your agents as MCP
              tools.
            </p>
            <span className={styles.featureLink}>MCP server docs →</span>
          </Link>
          <Link to="/docs/api/a2a-server" className={styles.testingCard}>
            <MdHub className={styles.testingBigIcon} />
            <h3>A2A — Agent-to-Agent</h3>
            <p>
              Agent-to-Agent (A2A) is a communication pattern where multiple AI agents interact directly with each
              other to share context, delegate tasks, and coordinate decisions. It enables complex workflows by
              allowing specialized agents to collaborate instead of relying on a single monolithic system. Agent
              Kernel natively supports exposing any agent over the A2A protocol by switching configuration.
            </p>
            <span className={styles.featureLink}>A2A server docs →</span>
          </Link>
        </div>
      </div>
    </section>
  );
}

/* ─── CTA ───────────────────────────────────────────────────────────────── */

function CTASection() {
  return (
    <section id={FEATURE_ANCHORS.cta} className={`${styles.ctaSection} ${styles.pageAnchor}`}>
      <div className={styles.ctaGlow} />
      <div className="container">
        <div className={styles.ctaContent}>
          <h2 className={styles.ctaTitle}>Ready to Build Your AI Agents?</h2>
          <p className={styles.ctaSubtitle}>
            Free, open-source, Apache 2.0. Whether you're an AI startup, an established software company,
            or a domain expert — Agent Kernel has a path for you.
          </p>
          <div className={styles.ctaButtons}>
            <Link className={`button button--primary button--lg ${styles.btnPrimary}`} to="/docs">
              <span className={styles.btnIcon}>→</span>
              Get Started
            </Link>
            <Link className={`button button--secondary button--lg ${styles.btnSecondary}`} to="/use-cases">
              <span className={styles.btnIconSecondary}>→</span>
              Find Your Use Case
            </Link>
            <Link
              className={`button button--secondary button--lg ${styles.btnSecondary}`}
              to="https://github.com/yaalalabs/agent-kernel"
              target="_blank"
              rel="noopener noreferrer">
              <span className={styles.btnIconSecondary}><FaGithub /></span>
              View on GitHub
            </Link>
          </div>
        </div>
      </div>
    </section>
  );
}

/* ─── Page Export ───────────────────────────────────────────────────────── */

export default function Features() {
  return (
    <Layout
      title="Features"
      description="Comprehensive overview of Agent Kernel features — framework-agnostic, multi-cloud AI agent runtime with built-in testing, observability, guardrails, and messaging integrations.">
      <PlantParticlesBackground />
      <Hero />
      <main>
        <FeaturesPageMap />
        <ProblemTable />
        <CoreFeatures />
        <FrameworkSupport />
        <TestingSection />
        <MessagingSection />
        <ProtocolSupport />
        <CTASection />
      </main>
    </Layout>
  );
}
