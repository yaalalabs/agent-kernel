import React, { useRef, useEffect } from 'react';
import Link from '@docusaurus/Link';
import useDocusaurusContext from '@docusaurus/useDocusaurusContext';
import Layout from '@theme/Layout';
import styles from './index.module.css';
import gsap from 'gsap';
import { ScrollTrigger } from 'gsap/dist/ScrollTrigger';
import AgentKernelArchDiagram from '../components/AgentKernelArchDiagram';
import ParticleSphere from '../components/ParticleSphere';
import {
  MdRocketLaunch,
  MdSwapHoriz,
  MdCloud,
  MdMemory,
  MdSecurity,
  MdVisibility,
  MdCode,
  MdBugReport,
  MdSettings,
  MdBusiness,
  MdGroup,
  MdAutoAwesome,
  MdTerminal,
  MdBuild,
  MdExtension,
  MdIntegrationInstructions,
  MdCloudUpload,
} from 'react-icons/md';
import { FaGithub, FaDiscord, FaPython, FaSlack, FaWhatsapp, FaInstagram, FaTelegram, FaAws, FaMicrosoft } from 'react-icons/fa';
import { SiTerraform, SiGmail, SiGooglecloud } from 'react-icons/si';
import { FaFacebookMessenger } from 'react-icons/fa6';

/* ─── Hero ──────────────────────────────────────────────────────────────── */

function Hero() {
  const titleRef = useRef(null);
  const taglineRef = useRef(null);
  const bodyRef = useRef(null);
  const buttonsRef = useRef(null);

  useEffect(() => {
    const tl = gsap.timeline();

    // Set initial states
    gsap.set([titleRef.current, taglineRef.current, bodyRef.current, buttonsRef.current], {
      opacity: 0,
      y: 30
    });

    // Animate elements in sequence
    tl.to(titleRef.current, {
      opacity: 1,
      y: 0,
      duration: 0.8,
      ease: "power2.out"
    })
    .to(taglineRef.current, {
      opacity: 1,
      y: 0,
      duration: 0.6,
      ease: "power2.out"
    }, "-=0.4")
    .to(bodyRef.current, {
      opacity: 1,
      y: 0,
      duration: 0.6,
      ease: "power2.out"
    }, "-=0.3")
    .to(buttonsRef.current, {
      opacity: 1,
      y: 0,
      duration: 0.5,
      ease: "power2.out"
    }, "-=0.2");

  }, []);

  return (
    <section className={styles.hero}>
      {/* <div className={styles.heroOrb} /> */}
      {/* <div className={styles.heroGrid} /> */}
      <div className="container">
        <div className={styles.heroContent}>
          {/* <img src="/img/branding/agent-kernel-icon-color.svg" alt="Agent Kernel" className={styles.heroLogo} /> */}
          <h1 ref={titleRef} className={styles.heroTitle}>Agent Kernel</h1>
          <p ref={taglineRef} className={styles.heroTagline}>From Agent Logic to Production in Minutes.</p>
          <p ref={bodyRef} className={styles.heroBody}>
            Agent Kernel is the open-source platform for building and deploying AI-powered assistants without months of engineering work. Works with any major AI technology, runs on any cloud, connects to Slack, WhatsApp, and more out of the box.
          </p>
          <div ref={buttonsRef} className={styles.heroButtons}>
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
            <Link className={`button button--primary button--lg ${styles.btnPrimary}`} to="/features">
              Explore Features
            </Link>
          </div>
        </div>
      </div>
    </section>
  );
}

/* ─── Frameworks Strip ──────────────────────────────────────────────────── */

function FrameworksStrip() {
  const frameworksRef = useRef(null);
  const labelRef = useRef(null);
  const rowRef = useRef(null);

  const frameworks = [
    { name: 'ChatGPT OpenAI Agents', logo: '/img/integrations/chatgpt.png', link: '/docs/frameworks/openai' },
    { name: 'LangGraph', logo: '/img/integrations/langgraph.png', link: '/docs/frameworks/langgraph' },
    { name: 'CrewAI', logo: '/img/integrations/crewai.png', link: '/docs/frameworks/crewai' },
    { name: 'Google ADK', logo: '/img/integrations/googleADK.png', link: '/docs/frameworks/google-adk' },
  ];

  useEffect(() => {
    gsap.registerPlugin(ScrollTrigger);

    // Set initial states
    gsap.set(labelRef.current, {
      opacity: 0,
      y: 20
    });

    gsap.set(rowRef.current?.children || [], {
      opacity: 0,
      y: 20
    });

    // Create scroll-triggered animation
    const tl = gsap.timeline({
      scrollTrigger: {
        trigger: frameworksRef.current,
        start: "top 85%",
        toggleActions: "play none none none"
      }
    });

    // Animate label first
    tl.to(labelRef.current, {
      opacity: 1,
      y: 0,
      duration: 0.6,
      ease: "power2.out"
    });

    // Then animate framework items with stagger
    tl.to(rowRef.current?.children || [], {
      opacity: 1,
      y: 0,
      duration: 0.4,
      ease: "power2.out",
      stagger: 0.08
    }, "-=0.3");

    // Add hover animations to framework items
    const frameworkItems = rowRef.current?.querySelectorAll(`.${styles.frameworkItem}`) || [];
    frameworkItems.forEach((item) => {
      const img = item.querySelector('img');
      if (img) {
        item.addEventListener('mouseenter', () => {
          gsap.to(img, {
            scale: 1.05,
            duration: 0.2,
            ease: "power1.out"
          });
        });

        item.addEventListener('mouseleave', () => {
          gsap.to(img, {
            scale: 1,
            duration: 0.2,
            ease: "power1.out"
          });
        });
      }
    });

    // Cleanup
    return () => {
      ScrollTrigger.getAll().forEach(trigger => trigger.kill());
    };

  }, []);

  return (
    <section ref={frameworksRef} className={styles.frameworksStrip}>
      <p ref={labelRef} className={styles.frameworksLabel}>Works with the frameworks you already use</p>
      <div ref={rowRef} className={styles.frameworksRow}>
        {frameworks.map((framework, index) => (
          <Link key={framework.name} to={framework.link} className={styles.frameworkItem}>
            <div className={styles.frameworkLogoContainer}>
              <img
                src={framework.logo}
                alt={framework.name}
                className={styles.frameworkLogo}
              />
            </div>
            {index < frameworks.length - 1 && (
              <span className={styles.frameworkSeparator}>●</span>
            )}
          </Link>
        ))}
      </div>
    </section>
  );
}

/* ─── Affiliations Strip ────────────────────────────────────────────────── */

function AffiliationsStrip() {
  return (
    <section className={styles.affiliationsStrip}>
      <div className="container">
        <p className={styles.affiliationsLabel}>Member of</p>
        <div className={styles.affiliationsRow}>
          <a
            href="https://www.linuxfoundation.org"
            target="_blank"
            rel="noopener noreferrer"
            className={styles.affiliationItem}>
            <img src="/img/lf_membership.svg" alt="Linux Foundation Member" className={styles.affiliationLogo} />
          </a>
          <a
            href="https://aaif.io"
            target="_blank"
            rel="noopener noreferrer"
            className={styles.affiliationItem}>
            <img src="/img/aaif_membership.svg" alt="Agentic AI Foundation Member" className={styles.affiliationLogo} />
          </a>
        </div>
      </div>
    </section>
  );
}

/* ─── Value Proposition ─────────────────────────────────────────────────── */

function ValueProp() {
  const items = [
    { problem: 'Months of platform engineering', solution: 'Production-ready in days' },
    { problem: 'Framework lock-in', solution: 'Switch with 2 import lines' },
    { problem: 'Cloud lock-in', solution: 'AWS + Azure, same code' },
    { problem: 'Build session management', solution: 'Multi-backend, built-in' },
    { problem: 'Wire messaging platforms', solution: 'Slack, WhatsApp, 6+ out of the box' },
    { problem: 'No testing standard', solution: 'pytest-integrated test framework' },
  ];

  return (
    <section className={styles.section}>
      <div className="container">
        <div className={styles.sectionHeader}>
          <h2 className={styles.sectionTitle}>Stop Building Plumbing.</h2>
          <h2 className={`${styles.sectionTitle} ${styles.gradientText}`}>Start Building Intelligence.</h2>
          <p className={styles.sectionSubtitle}>
            Every hour your team spends on infrastructure is an hour not spent on your core AI product.
            Agent Kernel handles the entire platform layer so you don't have to.
          </p>
        </div>
        <div className={styles.valuePropGrid}>
          {items.map((item, i) => (
            <div key={i} className={styles.valuePropCard}>
              <div className={styles.valueProblem}>
                <span className={styles.xMark}>✕</span>
                {item.problem}
              </div>
              <div className={styles.valueArrow}>→</div>
              <div className={styles.valueSolution}>
                <span className={styles.checkMark}>✓</span>
                {item.solution}
              </div>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}

/* ─── Who It's For ──────────────────────────────────────────────────────── */

function WhoItsFor() {
  const segments = [
    {
      icon: <MdBusiness />,
      title: 'Software Companies\n(Services)',
      tagline: 'Ship AI agent solutions to clients in weeks, not months.',
      href: '/use-cases',
      accent: 'cyan',
    },
    {
      icon: <MdAutoAwesome />,
      title: 'Software Companies\n(Products)',
      tagline: 'Add intelligent agents to your SaaS without framework lock-in.',
      href: '/use-cases',
      accent: 'violet',
    },
    {
      icon: <MdRocketLaunch />,
      title: 'AI Startups',
      tagline: 'Go from prototype to production in days, not quarters.',
      href: '/use-cases',
      accent: 'cyan',
    },
    {
      icon: <MdGroup />,
      title: 'Domain Experts',
      tagline: 'Build production AI products without a full engineering team.',
      href: '/use-cases',
      accent: 'violet',
    },
  ];

  return (
    <section className={styles.section}>
      <div className="container">
        <div className={styles.sectionHeader}>
          <h2 className={styles.sectionTitle}>Built for Teams Who Move Fast</h2>
          <p className={styles.sectionSubtitle}>
            From AI service agencies to domain experts — Agent Kernel meets you where you are.
          </p>
        </div>
        <div className={styles.segmentsGrid}>
          {segments.map((s, i) => (
            <Link key={i} to={s.href} className={`${styles.segmentCard} ${styles[`accent_${s.accent}`]}`}>
              <div className={styles.segmentIcon}>{s.icon}</div>
              <h3 className={styles.segmentTitle}>{s.title}</h3>
              <p className={styles.segmentTagline}>{s.tagline}</p>
              <span className={styles.segmentCta}>Learn more →</span>
            </Link>
          ))}
        </div>
        <div className={styles.sectionFooter}>
          <Link to="/use-cases" className={styles.sectionLink}>
            See all use cases and market segments →
          </Link>
        </div>
      </div>
    </section>
  );
}

/* ─── Key Features ──────────────────────────────────────────────────────── */

function KeyFeatures() {
  const features = [
    {
      icon: <MdSwapHoriz />,
      title: 'Framework-Agnostic',
      description: 'Run OpenAI, LangGraph, CrewAI, and Google ADK side by side in one runtime. Switch frameworks with 2 import lines.',
      size: 'wide',
      link: '/docs/frameworks/overview',
    },
    {
      icon: <MdCloud />,
      title: 'Multi-Cloud',
      description: 'Same agent code deploys to AWS Lambda, ECS, Azure Functions, or Container Apps. Zero vendor lock-in.',
      size: 'normal',
      link: '/docs/deployment/overview',
    },
    {
      icon: <MdMemory />,
      title: 'Session & Memory',
      description: 'Built-in volatile and non-volatile caching. Backends: Redis, DynamoDB, Cosmos DB, in-memory.',
      size: 'normal',
      link: '/docs/architecture/memory-management',
    },
    {
      icon: <MdSettings />,
      title: 'Execution Hooks',
      description: 'Pre/post-execution hooks for guardrails, RAG injection, analytics, and response moderation. Works across all frameworks.',
      size: 'normal',
      link: '/docs/integrations/hooks',
    },
    {
      icon: <FaSlack />,
      title: 'Messaging Integrations',
      description: 'Slack, WhatsApp, Messenger, Instagram, Telegram, Gmail — built-in. Plug and play.',
      size: 'normal',
      link: '/docs/integrations/overview',
    },
    {
      icon: <MdBugReport />,
      title: 'Testing Framework',
      description: 'pytest-integrated agent testing with fuzzy, semantic, and fallback comparison modes. CI/CD ready.',
      size: 'wide',
      link: '/docs/testing/overview',
    },
    {
      icon: <MdSecurity />,
      title: 'Guardrails',
      description: 'OpenAI and AWS Bedrock guardrails for PII detection, jailbreak prevention, and content moderation. Enforce safety policies without touching agent logic.',
      size: 'wide',
      link: '/docs/advanced/guardrails',
    },
    {
      icon: <MdVisibility />,
      title: 'Observability & Tracing',
      description: 'LangFuse and OpenLLMetry tracing with one config line. Full visibility into every agent, tool, and LLM call — in development and production.',
      size: 'wide',
      link: '/docs/advanced/traceability',
    },
  ];

  return (
    <section className={styles.section}>
      <div className="container">
        <div className={styles.sectionHeader}>
          <h2 className={styles.sectionTitle}>Everything You Need in Production</h2>
          <p className={styles.sectionSubtitle}>
            No more cobbling together deployment pipelines, session stores, and integration glue.
            Agent Kernel gives you the full stack from day one.
          </p>
        </div>
        <div className={styles.bentoGrid}>
          {features.map((f, i) => (
            <Link
              key={i}
              to={f.link}
              className={`${styles.bentoCard} ${f.size === 'wide' ? styles.bentoWide : ''}`}>
              <div className={styles.bentoIcon}>{f.icon}</div>
              <h3 className={styles.bentoTitle}>{f.title}</h3>
              <p className={styles.bentoDescription}>{f.description}</p>
            </Link>
          ))}
        </div>
        <div className={styles.sectionFooter}>
          <Link to="/features" className={styles.sectionLink}>View all features →</Link>
        </div>
      </div>
    </section>
  );
}

/* ─── Deployment ────────────────────────────────────────────────────────── */

function Deployment() {
  const clouds = [
    {
      icon: <FaAws />,
      name: 'Amazon AWS',
      color: '#FF9900',
      description: 'Serverless or containerized deployments with Terraform modules.',
      modes: ['AWS Lambda (Serverless)', 'AWS ECS/Fargate (Containerized)'],
      modules: [
        { name: 'AWS Serverless', url: 'https://registry.terraform.io/modules/yaalalabs/ak-serverless/aws' },
        { name: 'AWS Containerized', url: 'https://registry.terraform.io/modules/yaalalabs/ak-containerized/aws' },
      ],
      comingSoon: false,
    },
    {
      icon: <FaMicrosoft />,
      name: 'Microsoft Azure',
      color: '#0078D4',
      description: 'Functions or Container Apps with Cosmos DB session storage.',
      modes: ['Azure Functions (Serverless)', 'Azure Container Apps (Containerized)'],
      modules: [
        { name: 'Azure Serverless', url: 'https://registry.terraform.io/modules/yaalalabs/ak-serverless/azurerm' },
        { name: 'Azure Containerized', url: 'https://registry.terraform.io/modules/yaalalabs/ak-containerized/azurerm' },
      ],
      comingSoon: false,
    },
    {
      icon: <SiGooglecloud />,
      name: 'Google Cloud',
      color: '#4285F4',
      description: 'Cloud Run and Cloud Functions deployments — Terraform modules in progress.',
      modes: ['Cloud Run (Containerized)', 'Cloud Functions (Serverless)'],
      modules: [],
      comingSoon: true,
    },
  ];

  return (
    <section className={styles.section}>
      <div className="container">
        <div className={styles.sectionHeader}>
          <h2 className={styles.sectionTitle}>Deploy Anywhere</h2>
          <p className={styles.sectionSubtitle}>
            AWS, Azure, or on-prem Docker. Same agent code — zero platform rewrites.
            Full Terraform modules with production best practices baked in.
          </p>
        </div>
        <div className={styles.cloudGrid}>
          {clouds.map((c, i) => (
            <div key={i} className={`${styles.cloudCard} ${c.comingSoon ? styles.cloudCardComingSoon : ''}`}>
              <div className={styles.cloudIcon} style={{ color: c.color }}>{c.icon}</div>
              <div className={styles.cloudNameRow}>
                <h3 className={styles.cloudName}>{c.name}</h3>
                {c.comingSoon && <span className={styles.cloudComingSoonBadge}>Coming Soon</span>}
              </div>
              <p className={styles.cloudDescription}>{c.description}</p>
              <ul className={styles.cloudModes}>
                {c.modes.map((m, j) => <li key={j}>{m}</li>)}
              </ul>
              {!c.comingSoon && (
                <div className={styles.cloudModules}>
                  {c.modules.map((m, j) => (
                    <Link
                      key={j}
                      to={m.url}
                      className={styles.terraformLink}
                      target="_blank"
                      rel="noopener noreferrer">
                      <SiTerraform className={styles.terraformIcon} />
                      {m.name} →
                    </Link>
                  ))}
                </div>
              )}
            </div>
          ))}
        </div>
        <div className={styles.sectionFooter}>
          <Link to="/docs/deployment/overview" className={styles.sectionLink}>View deployment docs →</Link>
        </div>
      </div>
    </section>
  );
}

/* ─── Messaging Integrations ────────────────────────────────────────────── */

function MessagingIntegrations() {
  const platforms = [
    { name: 'Slack', icon: <FaSlack />, color: '#4A154B', link: '/docs/integrations/slack' },
    { name: 'WhatsApp', icon: <FaWhatsapp />, color: '#25D366', link: '/docs/integrations/whatsapp' },
    { name: 'Messenger', icon: <FaFacebookMessenger />, color: '#0084FF', link: '/docs/integrations/messenger' },
    { name: 'Instagram', icon: <FaInstagram />, color: '#E4405F', link: '/docs/integrations/instagram' },
    { name: 'Telegram', icon: <FaTelegram />, color: '#0088CC', link: '/docs/integrations/telegram' },
    { name: 'Gmail', icon: <SiGmail />, color: '#EA4335', link: '/docs/integrations/gmail' },
  ];

  return (
    <section className={styles.messagingSection}>
      <div className="container">
        <div className={styles.sectionHeader}>
          <h2 className={styles.sectionTitle}>Reach Users Where They Are</h2>
          <p className={styles.sectionSubtitle}>
            Built-in integrations for the world's most popular messaging platforms.
            No custom bots to build — just plug and play.
          </p>
        </div>
        <div className={styles.messagingTrackWrapper}>
          <div className={styles.messagingTrack}>
            {[...platforms, ...platforms].map((p, i) => (
              <Link
                key={i}
                to={p.link}
                className={styles.messagingCard}
                style={{ '--platform-color': p.color } as React.CSSProperties}>
                <div className={styles.messagingIcon} style={{ color: p.color }}>{p.icon}</div>
                <span className={styles.messagingName}>{p.name}</span>
              </Link>
            ))}
          </div>
        </div>
        <div className={styles.comingSoonRow}>
          <div className={`${styles.messagingCard} ${styles.comingSoonCard}`}>
            <MdCode className={styles.messagingIcon} style={{ color: '#6264A7' } as React.CSSProperties} />
            <span className={styles.messagingName}>Teams</span>
            <span className={styles.comingSoonBadge}>Coming Soon</span>
          </div>
        </div>
      </div>
    </section>
  );
}

/* ─── Agent Skills ──────────────────────────────────────────────────────── */

function AgentSkills() {
  const skills = [
    { icon: <MdRocketLaunch />, name: 'ak-init', label: 'Scaffold', description: 'Create a new project from scratch — any framework, any deployment mode' },
    { icon: <MdBuild />, name: 'ak-build', label: 'Build', description: 'Add tools, agents, and handoffs — context-aware, framework-specific' },
    { icon: <MdExtension />, name: 'ak-add-capabilities', label: 'Capabilities', description: 'Guardrails, tracing, sessions, MCP, A2A, hooks, multimodal' },
    { icon: <MdIntegrationInstructions />, name: 'ak-add-integration', label: 'Integrate', description: 'Slack, WhatsApp, Messenger, Instagram, Telegram, Gmail' },
    { icon: <MdCloudUpload />, name: 'ak-cloud-deploy', label: 'Deploy', description: 'AWS Lambda, ECS, Azure Functions, Container Apps — full Terraform' },
    { icon: <MdBugReport />, name: 'ak-test', label: 'Test', description: 'Fuzzy, judge, and fallback test modes + debugging playbook' },
  ];

  return (
    <section className={styles.skillsSection}>
      <div className={styles.skillsGlow} />
      <div className="container">
        <div className={styles.sectionHeader}>
          <p className={styles.skillsBadge}>
            <MdTerminal style={{ fontSize: '0.85rem' }} /> Agent Skills
          </p>
          <h2 className={styles.sectionTitle}>
            Your Coding Assistant,{' '}
            <span className={styles.gradientText}>Supercharged.</span>
          </h2>
          <p className={styles.sectionSubtitle}>
            Install Agent Kernel skills and your coding assistant — Copilot, Claude, Cursor, or Windsurf
            — becomes an expert at building production AI agents. No more hallucinated APIs.
          </p>
        </div>

        <div className={styles.skillsInstall}>
          <div className={styles.skillsTerminal}>
            <div className={styles.terminalBar}>
              <span className={styles.terminalDot} />
              <span className={styles.terminalDot} />
              <span className={styles.terminalDot} />
              <span className={styles.terminalTitle}>Terminal</span>
            </div>
            <div className={styles.terminalBody}>
              <code>
                <span className={styles.terminalComment}># Install the CLI</span>{'\n'}
                <span className={styles.terminalPrompt}>$</span> pip install agentkernel{'\n\n'}
                <span className={styles.terminalComment}># Install skills for your coding assistant</span>{'\n'}
                <span className={styles.terminalPrompt}>$</span> ak skill install{'\n\n'}
                <span className={styles.terminalComment}># Or for a specific assistant</span>{'\n'}
                <span className={styles.terminalPrompt}>$</span> ak skill install --assistant claude
              </code>
            </div>
          </div>
        </div>

        <div className={styles.skillsGrid}>
          {skills.map((s, i) => (
            <div key={i} className={styles.skillCard}>
              <div className={styles.skillIcon}>{s.icon}</div>
              <div className={styles.skillInfo}>
                <div className={styles.skillName}>{s.name}</div>
                <div className={styles.skillDesc}>{s.description}</div>
              </div>
            </div>
          ))}
        </div>

        <div className={styles.skillsFlow}>
          <span className={styles.flowStep}>ak-init</span>
          <span className={styles.flowArrow}>→</span>
          <span className={styles.flowStep}>ak-build</span>
          <span className={styles.flowArrowRepeat}>↻</span>
          <span className={styles.flowArrow}>→</span>
          <span className={styles.flowStep}>ak-cloud-deploy</span>
          <span className={styles.flowArrow}>→</span>
          <span className={styles.flowStep}>ak-test</span>
        </div>

        <div className={styles.sectionFooter}>
          <Link to="/docs/next/agent-skills" className={styles.sectionLink}>
            Learn more about Agent Skills →
          </Link>
        </div>
      </div>
    </section>
  );
}

/* ─── Community / CTA ───────────────────────────────────────────────────── */

function Community() {
  const links = [
    { icon: <FaGithub />, name: 'GitHub', description: 'Star us and contribute', url: 'https://github.com/yaalalabs/agent-kernel' },
    { icon: <FaDiscord />, name: 'Discord', description: 'Join the community', url: 'https://discord.gg/snrPzb46uu' },
    { icon: <FaPython />, name: 'PyPI', description: 'pip install agentkernel', url: 'https://pypi.org/project/agentkernel/' },
    { icon: <SiTerraform />, name: 'Terraform', description: 'Official registry modules', url: 'https://registry.terraform.io/modules/yaalalabs' },
  ];

  return (
    <section className={styles.ctaSection}>
      {/* <div className={styles.ctaGlow} /> */}
      <div className="container">
        <div className={styles.ctaContent}>
          <h2 className={styles.ctaTitle}>Ready to Ship Your First Agent?</h2>
          <p className={styles.ctaSubtitle}>
            Free, open-source, Apache 2.0. No licensing costs, no vendor lock-in.
            Join hundreds of developers building production AI agents with Agent Kernel.
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
          <div className={styles.communityLinks}>
            {links.map((l, i) => (
              <Link
                key={i}
                to={l.url}
                className={styles.communityLink}
                target="_blank"
                rel="noopener noreferrer">
                <span className={styles.communityLinkIcon}>{l.icon}</span>
                <div>
                  <div className={styles.communityLinkName}>{l.name}</div>
                  <div className={styles.communityLinkDesc}>{l.description}</div>
                </div>
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
  return (
    <Layout
      title={`${siteConfig.title} — ${siteConfig.tagline}`}
      description="Agent Kernel is an open-source, framework-agnostic, multi-cloud runtime for production AI agents. Build, test, and deploy with OpenAI, LangGraph, CrewAI, or Google ADK to AWS or Azure — in days, not months.">
      <ParticleSphere />
      <Hero />
      <main>
        {/* <AffiliationsStrip /> */}
        <FrameworksStrip />
        {/* <AgentKernelArchDiagram />
        <KeyFeatures />
        <AgentSkills />
        <Deployment />
        <MessagingIntegrations /> */}
        <Community />
      </main>
    </Layout>
  );
}
