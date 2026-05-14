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
} from 'react-icons/md';
import { FaSlack, FaWhatsapp, FaInstagram, FaTelegram, FaGithub } from 'react-icons/fa';
import { SiGmail } from 'react-icons/si';
import { FaFacebookMessenger } from 'react-icons/fa6';
import PlantParticlesBackground from '../components/PlantParticlesBackground';

/** Stable fragment ids for in-page navigation (diagram + deep links). */
const FEATURE_ANCHORS = {
  problem: 'features-problem',
  core: 'features-core',
  frameworks: 'features-frameworks',
  testing: 'features-testing',
  messaging: 'features-messaging',
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
    anchor: 'cta',
    number: '06',
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
  const bottomRow = FEATURE_PAGE_MAP.slice(3, 6);

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

  const COL_X = [143, 450, 757] as const;

  // Top strip
  const topLines = COL_X.map((x, i) => ({
    id: `${gradId}T${i}`,
    d: `M ${x} 0 L 450 60`,
    len: Math.round(Math.sqrt(Math.pow(x - 450, 2) + 3600)),
    delay: 0.20 + i * 0.07,
  }));

  // Bottom strip
  const botLines = COL_X.map((x, i) => ({
    id: `${gradId}B${i}`,
    d: `M 450 0 L ${x} 60`,
    len: Math.round(Math.sqrt(Math.pow(x - 450, 2) + 3600)),
    delay: 0.41 + i * 0.07,
  }));

  const topGlowId = `${gradId}TGlow`;
  const botGlowId = `${gradId}BGlow`;

  const topParticles = [
    { pathId: `${gradId}T0`, delay: '0.9s', dur: '1.8s', color: '#4f7df7' },
    { pathId: `${gradId}T1`, delay: '1.5s', dur: '1.4s', color: '#00d4ff' },
    { pathId: `${gradId}T2`, delay: '1.2s', dur: '1.8s', color: '#8b5cf6' },
  ];
  const botParticles = [
    { pathId: `${gradId}B0`, delay: '2.0s', dur: '1.8s', color: '#4f7df7' },
    { pathId: `${gradId}B1`, delay: '2.5s', dur: '1.4s', color: '#00d4ff' },
    { pathId: `${gradId}B2`, delay: '1.8s', dur: '1.8s', color: '#8b5cf6' },
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
            Six production-ready capabilities — explore any area below.
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
              <filter id={topGlowId} x="-50%" y="-50%" width="200%" height="200%">
                <feGaussianBlur stdDeviation="2" result="blur" />
                <feMerge><feMergeNode in="blur" /><feMergeNode in="SourceGraphic" /></feMerge>
              </filter>
              {topLines.map(l => <path key={l.id} id={l.id} d={l.d} />)}
            </defs>
            {topLines.map(l => (
              <path key={l.id} d={l.d} fill="none"
                stroke="rgba(79, 125, 247, 0.4)" strokeWidth="1.5"
                strokeDasharray={l.len} strokeDashoffset={visible ? 0 : l.len}
                style={{ transition: `stroke-dashoffset 0.55s cubic-bezier(0.22, 1, 0.36, 1) ${l.delay}s` }}
              />
            ))}
            {visible && !reducedMotion && topParticles.map((p, i) => (
              <circle key={i} r="3" fill={p.color} filter={`url(#${topGlowId})`} opacity="0.9">
                <animateMotion dur={p.dur} repeatCount="indefinite" begin={p.delay}>
                  <mpath href={`#${p.pathId}`} />
                </animateMotion>
              </circle>
            ))}
          </svg>

          {/* ── Hub ── */}
          <div className={`${styles.pageMapHub} ${visible ? styles.pageMapHubIn : ''}`}>
            <span className={styles.pageMapHubLabel}>Overview</span>
          </div>

          {/* ── Connector: hub → bottom nodes ── */}
          <svg className={styles.pageMapConnector} viewBox="0 0 900 60" preserveAspectRatio="none" aria-hidden>
            <defs>
              <filter id={botGlowId} x="-50%" y="-50%" width="200%" height="200%">
                <feGaussianBlur stdDeviation="2" result="blur" />
                <feMerge><feMergeNode in="blur" /><feMergeNode in="SourceGraphic" /></feMerge>
              </filter>
              {botLines.map(l => <path key={l.id} id={l.id} d={l.d} />)}
            </defs>
            {botLines.map(l => (
              <path key={l.id} d={l.d} fill="none"
                stroke="rgba(79, 125, 247, 0.4)" strokeWidth="1.5"
                strokeDasharray={l.len} strokeDashoffset={visible ? 0 : l.len}
                style={{ transition: `stroke-dashoffset 0.55s cubic-bezier(0.22, 1, 0.36, 1) ${l.delay}s` }}
              />
            ))}
            {visible && !reducedMotion && botParticles.map((p, i) => (
              <circle key={i} r="3" fill={p.color} filter={`url(#${botGlowId})`} opacity="0.9">
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
      description: 'Agent, Runner, Session, Module, Runtime, and Tools — a unified API across all frameworks. Build once, run on any supported framework.',
      highlights: ['Unified Python API', 'Framework adapters for 4 SDKs', 'Portable tool functions via ToolBuilder', 'Framework-agnostic hooks'],
      link: '/docs/core-concepts/overview',
    },
    {
      icon: <MdSwapHoriz />,
      title: 'Framework-Agnostic Runtime',
      description: 'OpenAI Agents, LangGraph, CrewAI, and Google ADK — run them all simultaneously in one runtime. Switch frameworks by changing 2 import lines.',
      highlights: ['OpenAI Agents SDK', 'LangGraph', 'CrewAI', 'Google ADK'],
      link: '/docs/frameworks/overview',
    },
    {
      icon: <MdSettings />,
      title: 'Execution Hooks',
      description: 'Pre and post-execution hooks give you surgical control over every agent request — for any framework.',
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
      icon: <MdCloud />,
      title: 'Multi-Cloud Deployment',
      description: 'One agent codebase deploys to AWS and Azure with full Terraform modules. No vendor lock-in, ever.',
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
            Everything you need to build, run, and scale production AI agents — without building platform code.
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
  const frameworks = [
    {
      name: 'OpenAI Agents SDK',
      description: 'Official OpenAI agents framework with full support for tools, handoffs, and streaming.',
      link: '/docs/frameworks/openai',
    },
    {
      name: 'LangGraph',
      description: 'Graph-based agent orchestration for complex stateful multi-actor applications.',
      link: '/docs/frameworks/langgraph',
    },
    {
      name: 'Google ADK',
      description: "Google's Agent Development Kit for advanced agent capabilities and Gemini integration.",
      link: '/docs/frameworks/google-adk',
    },
    {
      name: 'CrewAI',
      description: 'Role-based multi-agent framework for orchestrating collaborative AI workflows.',
      link: '/docs/frameworks/crewai',
    },
    {
      name: 'Multi-Framework',
      description: 'Run agents from multiple frameworks simultaneously in a single runtime — no glue code required.',
      link: '/docs/frameworks/multi-framework',
      featured: true,
    },
  ];

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
        <div className={styles.frameworksGrid}>
          {frameworks.map((f, i) => (
            <Link
              key={i}
              to={f.link}
              className={`${styles.frameworkCard} ${f.featured ? styles.frameworkFeatured : ''}`}>
              <h3 className={styles.frameworkName}>{f.name}</h3>
              <p className={styles.frameworkDescription}>{f.description}</p>
              <span className={styles.frameworkLink}>Learn more →</span>
            </Link>
          ))}
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
      description: 'Tries fuzzy first, falls back to judge. The default — best of both worlds.',
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
        <CTASection />
      </main>
    </Layout>
  );
}
