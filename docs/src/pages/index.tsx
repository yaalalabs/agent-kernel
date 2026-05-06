import React, { useRef, useEffect, useState } from 'react';
import Link from '@docusaurus/Link';
import useDocusaurusContext from '@docusaurus/useDocusaurusContext';
import Layout from '@theme/Layout';
import styles from './index.module.css';
import gsap from 'gsap';
import { ScrollTrigger } from 'gsap/dist/ScrollTrigger';
import { ScrollToPlugin } from 'gsap/dist/ScrollToPlugin';
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
  MdGpsFixed,
  MdAssignment,
  MdBolt,
  MdTrendingUp,
  MdRefresh,
  MdMessage,
  MdScience,
  MdLink,
  MdSmartToy,
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

// /* ─── Key Features ──────────────────────────────────────────────────────── */

// function KeyFeatures() {
//   const features = [
//     {
//       icon: <MdSwapHoriz />,
//       title: 'Framework-Agnostic',
//       description: 'Run OpenAI, LangGraph, CrewAI, and Google ADK side by side in one runtime. Switch frameworks with 2 import lines.',
//       size: 'wide',
//       link: '/docs/frameworks/overview',
//     },
//     {
//       icon: <MdCloud />,
//       title: 'Multi-Cloud',
//       description: 'Same agent code deploys to AWS Lambda, ECS, Azure Functions, or Container Apps. Zero vendor lock-in.',
//       size: 'normal',
//       link: '/docs/deployment/overview',
//     },
//     {
//       icon: <MdMemory />,
//       title: 'Session & Memory',
//       description: 'Built-in volatile and non-volatile caching. Backends: Redis, DynamoDB, Cosmos DB, in-memory.',
//       size: 'normal',
//       link: '/docs/architecture/memory-management',
//     },
//     {
//       icon: <MdSettings />,
//       title: 'Execution Hooks',
//       description: 'Pre/post-execution hooks for guardrails, RAG injection, analytics, and response moderation. Works across all frameworks.',
//       size: 'normal',
//       link: '/docs/integrations/hooks',
//     },
//     {
//       icon: <FaSlack />,
//       title: 'Messaging Integrations',
//       description: 'Slack, WhatsApp, Messenger, Instagram, Telegram, Gmail — built-in. Plug and play.',
//       size: 'normal',
//       link: '/docs/integrations/overview',
//     },
//     {
//       icon: <MdBugReport />,
//       title: 'Testing Framework',
//       description: 'pytest-integrated agent testing with fuzzy, semantic, and fallback comparison modes. CI/CD ready.',
//       size: 'wide',
//       link: '/docs/testing/overview',
//     },
//     {
//       icon: <MdSecurity />,
//       title: 'Guardrails',
//       description: 'OpenAI and AWS Bedrock guardrails for PII detection, jailbreak prevention, and content moderation. Enforce safety policies without touching agent logic.',
//       size: 'wide',
//       link: '/docs/advanced/guardrails',
//     },
//     {
//       icon: <MdVisibility />,
//       title: 'Observability & Tracing',
//       description: 'LangFuse and OpenLLMetry tracing with one config line. Full visibility into every agent, tool, and LLM call — in development and production.',
//       size: 'wide',
//       link: '/docs/advanced/traceability',
//     },
//   ];

//   return (
//     <section className={styles.section}>
//       <div className="container">
//         <div className={styles.sectionHeader}>
//           <h2 className={styles.sectionTitle}>Everything You Need in Production</h2>
//           <p className={styles.sectionSubtitle}>
//             No more cobbling together deployment pipelines, session stores, and integration glue.
//             Agent Kernel gives you the full stack from day one.
//           </p>
//         </div>
//         <div className={styles.bentoGrid}>
//           {features.map((f, i) => (
//             <Link
//               key={i}
//               to={f.link}
//               className={`${styles.bentoCard} ${f.size === 'wide' ? styles.bentoWide : ''}`}>
//               <div className={styles.bentoIcon}>{f.icon}</div>
//               <h3 className={styles.bentoTitle}>{f.title}</h3>
//               <p className={styles.bentoDescription}>{f.description}</p>
//             </Link>
//           ))}
//         </div>
//         <div className={styles.sectionFooter}>
//           <Link to="/features" className={styles.sectionLink}>View all features →</Link>
//         </div>
//       </div>
//     </section>
//   );
// }

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

/* ─── Business Leader Scenarios ────────────────────────────────────────── */
function BusinessLeaderScenarios() {
  const [activeTab, setActiveTab] = useState<string>('ecommerce');
 
  const tabs = [
    { id: 'ecommerce', label: 'E-Commerce' },
    { id: 'sales', label: 'Sales' },
    { id: 'itops', label: 'IT & Ops' },
    { id: 'insurance', label: 'Insurance' },
    { id: 'logistics', label: 'Logistics' },
    { id: 'hr', label: 'HR & Recruiting' },
  ];
 
  const scenarios: Record<string, {
    title: string;
    channels: string;
    problem: { heading: string; sub: string; body: string };
    agent: { heading: string; sub: string; body: string };
    whyAk: { heading: string; sub: string; body: string };
  }> = {
    ecommerce: {
      title: 'Order Management Agent',
      channels: 'Website / WhatsApp / Instagram',
      problem: {
        heading: 'The Problem',
        sub: "Why it's painful",
        body: 'Customers ask "where\'s my order?" across your website, WhatsApp, and Instagram and your team copies tracking numbers between systems all day.',
      },
      agent: {
        heading: 'The Agent',
        sub: 'What it actually does',
        body: 'Connects to your order system, shipping carriers, and payment gateway. Looks up orders in real time, tracks shipments, processes returns or exchanges, triggers refunds, and keeps conversation memory across channels and sessions.',
      },
      whyAk: {
        heading: 'Why Agent Kernel',
        sub: 'The Agent Kernel advantage',
        body: 'One agent can serve many channels with built-in session memory, guardrails, and cloud deployment flexibility.',
      },
    },
    sales: {
      title: 'Lead Qualification Agent',
      channels: 'Website / Slack / Email',
      problem: {
        heading: 'The Problem',
        sub: "Why it's painful",
        body: 'Sales reps spend hours qualifying inbound leads manually, copying data into CRM, and scheduling demos — losing hot leads to slow follow-up.',
      },
      agent: {
        heading: 'The Agent',
        sub: 'What it actually does',
        body: 'Engages leads the moment they arrive, asks qualification questions, scores intent, updates your CRM automatically, and books demo calls — around the clock.',
      },
      whyAk: {
        heading: 'Why Agent Kernel',
        sub: 'The Agent Kernel advantage',
        body: 'Integrates with Slack alerts, Gmail follow-ups, and your CRM via hooks — deployed in days, not quarters.',
      },
    },
    itops: {
      title: 'IT Help Desk Agent',
      channels: 'Slack / Teams / Email',
      problem: {
        heading: 'The Problem',
        sub: "Why it's painful",
        body: 'Your IT team is buried in repetitive tickets — password resets, VPN access, software installs — while critical issues wait in the queue.',
      },
      agent: {
        heading: 'The Agent',
        sub: 'What it actually does',
        body: 'Handles Tier-1 requests autonomously: resets passwords, provisions access, runs diagnostics, and escalates only what truly needs a human.',
      },
      whyAk: {
        heading: 'Why Agent Kernel',
        sub: 'The Agent Kernel advantage',
        body: 'Works inside Slack or Teams with guardrails to prevent unauthorized actions and full observability on every step taken.',
      },
    },
    insurance: {
      title: 'Claims Intake Agent',
      channels: 'Website / WhatsApp / Email',
      problem: {
        heading: 'The Problem',
        sub: "Why it's painful",
        body: 'Claims intake is slow and error-prone — customers call, agents transcribe, documents get lost, and follow-ups fall through the cracks.',
      },
      agent: {
        heading: 'The Agent',
        sub: 'What it actually does',
        body: 'Guides claimants through intake, collects documents, validates policy coverage, creates claim records, and sends status updates automatically.',
      },
      whyAk: {
        heading: 'Why Agent Kernel',
        sub: 'The Agent Kernel advantage',
        body: 'PII guardrails and audit-grade tracing built in. Runs on your own cloud so sensitive data never leaves your infrastructure.',
      },
    },
    logistics: {
      title: 'Shipment Tracking Agent',
      channels: 'WhatsApp / Telegram / Email',
      problem: {
        heading: 'The Problem',
        sub: "Why it's painful",
        body: 'Dispatchers field hundreds of "where is my shipment?" calls a day while drivers, carriers, and customers all use different systems.',
      },
      agent: {
        heading: 'The Agent',
        sub: 'What it actually does',
        body: 'Unifies carrier APIs, answers tracking queries instantly, proactively alerts customers on delays, and updates ETAs across all channels.',
      },
      whyAk: {
        heading: 'Why Agent Kernel',
        sub: 'The Agent Kernel advantage',
        body: 'Multi-channel by default — WhatsApp, Telegram, email — with session memory so every customer gets a continuous conversation.',
      },
    },
    hr: {
      title: 'Recruiting Screener Agent',
      channels: 'Email / Slack / Website',
      problem: {
        heading: 'The Problem',
        sub: "Why it's painful",
        body: 'Recruiters spend 60% of their time on first-round screens, scheduling, and chasing candidates — before any real evaluation begins.',
      },
      agent: {
        heading: 'The Agent',
        sub: 'What it actually does',
        body: 'Reaches out to applicants, runs structured screening conversations, scores responses, schedules interviews with calendar integration, and summarizes for hiring managers.',
      },
      whyAk: {
        heading: 'Why Agent Kernel',
        sub: 'The Agent Kernel advantage',
        body: 'Semantic testing ensures agent responses stay on-script. Hooks let you inject role-specific rubrics without touching agent logic.',
      },
    },
  };
 
  const active = scenarios[activeTab];
 
  return (
    <div className={styles.blScenarios}>
 
      {/* ── Tab buttons — big rounded bordered buttons like in the image ── */}
      <div className={styles.blTabBar}>
        {tabs.map((t) => (
          <button
            key={t.id}
            onClick={() => setActiveTab(t.id)}
            className={`${styles.blTab} ${activeTab === t.id ? styles.blTabActive : ''}`}
          >
            {t.label}
          </button>
        ))}
      </div>
 
      {/* ── Scenario content ── */}
      <div className={styles.blScenarioContent}>
        <h3 className={styles.blScenarioTitle}>{active.title}</h3>
        <p className={styles.blScenarioChannels}>{active.channels}</p>
 
        <div className={styles.blScenarioCols}>
          {[active.problem, active.agent, active.whyAk].map((col) => (
            <div key={col.heading} className={styles.blScenarioCol}>
              <p className={styles.blScenarioColHeading}>{col.heading}</p>
              <p className={styles.blScenarioColSub}>{col.sub}</p>
              <p className={styles.blScenarioColBody}>{col.body}</p>
            </div>
          ))}
        </div>
      </div>
 
    </div>
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

function Levels() {
  const sectionRef = useRef<HTMLElement>(null);
  const titleRef = useRef<HTMLHeadingElement>(null);
  const subtitleRef = useRef<HTMLParagraphElement>(null);
  const cardsRef = useRef<HTMLDivElement>(null);
  const contentRef = useRef<HTMLDivElement>(null);
  const [selectedLevel, setSelectedLevel] = useState<string | null>(null);
  const [isPinned, setIsPinned] = useState(true);
  const [selectedFramework, setSelectedFramework] = useState<string>('openai');
  const [copiedCode, setCopiedCode] = useState<string | null>(null);
  const scrollTriggerRef = useRef<ScrollTriggerInstance | null>(null);

  const copyToClipboard = (code: string, id: string) => {
    navigator.clipboard.writeText(code);
    setCopiedCode(id);
    setTimeout(() => setCopiedCode(null), 2000);
  };

  const levels: Level[] = [
    {
      id: '01',
      title: 'Business Leader',
      image: '/img/business_leader.png',
      description: 'You run or work in a business and want AI assistants that actually work without needing to understand the tech.',
    },
    {
      id: '02',
      title: 'Developer',
      image: '/img/developer.png',
      description: 'You write software but haven\'t built AI agents yet. You want to ship something real without learning a new stack from scratch.',
    },
    {
      id: '03',
      title: 'AI Engineer',
      image: '/img/ai.png',
      description: 'You already work with LLMs and agentic frameworks. You need a production-grade runtime that doesn\'t get in your way.',
    },
  ];

  const handleLevelSelect = (levelId: string) => {
    setSelectedLevel(levelId);
    setIsPinned(false);

    if (scrollTriggerRef.current) {
      scrollTriggerRef.current.kill();
    }

    gsap.set(sectionRef.current, { height: 'auto', clearProps: 'height' });

    ScrollTrigger.refresh();

    ScrollTrigger.refresh();

    if (contentRef.current) {
      gsap.registerPlugin(ScrollToPlugin);
      gsap.to(window, {
        duration: 1,
        scrollTo: { y: contentRef.current.offsetTop - 100 },
        ease: 'power2.out',
      });
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
        if (e.key === 'ArrowDown' || e.key === ' ' || e.key === 'PageDown') {
          e.preventDefault();
        }
      }
    };

    if (!selectedLevel) {
      gsap.registerPlugin(ScrollTrigger);

      gsap.set(sectionRef.current, { height: '100vh' });
      ScrollTrigger.refresh();
      ScrollTrigger.refresh();

      gsap.fromTo(
        [titleRef.current, subtitleRef.current, cardsRef.current],
        { opacity: 0, y: 30 },
        {
          opacity: 1,
          y: 0,
          duration: 1,
          ease: 'power2.out',
          scrollTrigger: {
            trigger: sectionRef.current,
            start: 'top 60%',
            toggleActions: 'play none none reverse',
          },
        }
      );

      const tl = gsap.timeline({
        scrollTrigger: {
          trigger: sectionRef.current,
          start: 'top top',
          end: '+=100%',
          pin: true,
          pinSpacing: true,
          scrub: false,
        },
      });

      scrollTriggerRef.current = tl.scrollTrigger as ScrollTriggerInstance | null;

      window.addEventListener('wheel', handleWheel, { passive: false });
      window.addEventListener('touchmove', handleTouchMove, { passive: false });
      window.addEventListener('keydown', handleKeyDown);
    }

    return () => {
      window.removeEventListener('wheel', handleWheel);
      window.removeEventListener('touchmove', handleTouchMove);
      window.removeEventListener('keydown', handleKeyDown);
      if (scrollTriggerRef.current) {
        scrollTriggerRef.current.kill();
      }
    };
  }, [isPinned, selectedLevel]);

  return (
    <section
      ref={sectionRef}
      className={`${styles.levelsSection} ${!selectedLevel ? styles.levelsPinned : ''}`}
    >
      <div className="container">
        <div className={styles.levelsContainer}>
          <p ref={subtitleRef} className={styles.levelsSubtitle}>
            Choose your level
          </p>

          <h2 ref={titleRef} className={styles.levelsTitle}>
            Agent Kernel fits your experience
          </h2>

          <div ref={cardsRef} className={styles.levelsGrid}>
            {levels.map((level) => (
              <div
                key={level.id}
                data-level={level.id}
                onClick={() => handleLevelSelect(level.id)}
                className={`${styles.levelCard} ${selectedLevel === level.id ? styles.levelCardSelected : ''}`}
              >
                <div className={styles.levelNumber}>Level {level.id}</div>

                <div className={styles.levelImage}>
                  <img src={level.image} alt={level.title} />
                </div>

                <h3 className={styles.levelCardTitle}>{level.title}</h3>
                <p className={styles.levelCardDescription}>{level.description}</p>
              </div>
            ))}
          </div>

          <div className={styles.levelsHint}>
            Select a level to continue
          </div>

          {/* ── BUSINESS LEADER CONTENT ── */}
          {selectedLevel === '01' && (
            <div ref={contentRef} className={styles.levelContent}>
          
              {/* ── STEP 01 ── */}
              <div className={styles.contentStep}>
                <p className={styles.stepLabel}>Step 01 / Identify the gap</p>
                <h2 className={styles.contentTitle}>
                  Where is the gap in your business?
                </h2>
                <p className={styles.contentBody}>
                  Most businesses have processes that still depend too much on people. They are repetitive, slow, and hard to scale. The gap looks different depending on where you are.
                </p>
              </div>
          
              <div className={styles.contentGrid}>
                <div className={styles.contentCard}>
                  <h3 className={styles.contentCardLabel}>SaaS / Product</h3>
                  <p className={styles.contentCardTitle}>Do you have an existing product?</p>
                  <ul className={styles.bulletList}>
                    <li>Users still do too much manually inside your app</li>
                    <li>Support tickets pile up for questions your product could answer</li>
                    <li>Repetitive workflows require human involvement every time</li>
                  </ul>
                </div>
                <div className={styles.contentCard}>
                  <h3 className={styles.contentCardLabel}>Enterprise / Large Org</h3>
                  <p className={styles.contentCardTitle}>Do you run complex operations?</p>
                  <ul className={styles.bulletList}>
                    <li>Thousands of customer queries handled by an overstretched team</li>
                    <li>Knowledge locked across systems and documents</li>
                    <li>Cross-team hand offs are slow and error-prone</li>
                  </ul>
                </div>
                <div className={styles.contentCard}>
                  <h3 className={styles.contentCardLabel}>Building Something New</h3>
                  <p className={styles.contentCardTitle}>Do you have a product idea?</p>
                  <ul className={styles.bulletList}>
                    <li>You see an opportunity for an AI-powered service in your industry</li>
                    <li>You're not sure which AI technology to commit to</li>
                    <li>Building from scratch feels like months before anything reaches users</li>
                  </ul>
                </div>
              </div>
          
              {/* ── STEP 02 ── */}
              <div style={{ marginTop: '2rem' }}>
                <p className={styles.stepLabel}>Step 02 / Meet the solution</p>
                <h2 className={styles.contentTitle}>
                  An AI agent doesn't just answer, it gets things done.
                </h2>
          
                <div className={styles.agentFlow}>
                  <div className={styles.flowStep}>
                    <MdGpsFixed className={styles.flowIcon} />
                    <h4 className={styles.flowLabel}>Goal</h4>
                    <p className={styles.flowDesc}>Understand the goal</p>
                  </div>
                  <div className={styles.flowArrow}>→</div>
                  <div className={styles.flowStep}>
                    <MdAssignment className={styles.flowIcon} />
                    <h4 className={styles.flowLabel}>Plan</h4>
                    <p className={styles.flowDesc}>Plan steps</p>
                  </div>
                  <div className={styles.flowArrow}>→</div>
                  <div className={styles.flowStep}>
                    <MdBolt className={styles.flowIcon} />
                    <h4 className={styles.flowLabel}>Act</h4>
                    <p className={styles.flowDesc}>Take actions</p>
                  </div>
                  <div className={styles.flowArrow}>→</div>
                  <div className={styles.flowStep}>
                    <MdVisibility className={styles.flowIcon} />
                    <h4 className={styles.flowLabel}>Observe</h4>
                    <p className={styles.flowDesc}>Observe the results</p>
                  </div>
                  <div className={styles.flowArrow}>→</div>
                  <div className={styles.flowStep}>
                    <MdTrendingUp className={styles.flowIcon} />
                    <h4 className={styles.flowLabel}>Improve</h4>
                    <p className={styles.flowDesc}>Gets smarter</p>
                  </div>
                  <div className={styles.flowArrow}>→</div>
                  <div className={styles.flowStep}>
                    <MdRefresh className={styles.flowIcon} />
                    <h4 className={styles.flowLabel}>Repeat</h4>
                    <p className={styles.flowDesc}>Always on, always learning</p>
                  </div>
                </div>
              </div>
          
              {/* ── STEP 03 ── */}
              <div style={{ marginTop: '2rem' }}>
                <p className={styles.stepLabel}>Step 03 / Agent Kernel</p>
                <h2 className={styles.contentTitle}>
                  Agent Kernel is the engine that powers it at scale
                </h2>
          
                {/* OS analogy highlight card */}
                <div className={styles.blHighlightCard}>
                  <p className={styles.blHighlightEyebrow}>For Your Business</p>
                  <h3 className={styles.blHighlightTitle}>
                    Agent Kernel is like an Operating System for AI agents.
                  </h3>
                  <p className={styles.blHighlightBody}>
                    You don't need to understand how an operating system works to use the Internet. It runs behind the scenes, powering websites, servers, and cloud systems.
                  </p>
                  <p className={styles.blHighlightBody}>
                    Agent Kernel does the same thing for AI agents. It's a powerful platform that runs your AI agents in the background, handling all the complex infrastructure so that you focus on building the features that matter to your business.
                  </p>
                </div>
          
                {/* 3 value props */}
                <div className={styles.blValueGrid}>
                  <div className={styles.blValueCard}>
                    <div className={styles.blValueIcon}>
                      <MdRocketLaunch />
                    </div>
                    <h4 className={styles.blValueTitle}>Days, not months</h4>
                    <p className={styles.blValueBody}>
                      No one has to build agent infrastructure from scratch. Go from idea to enterprise-grade working agent ideas.
                    </p>
                  </div>
                  <div className={styles.blValueCard}>
                    <div className={styles.blValueIcon}>
                      <MdMessage />
                    </div>
                    <h4 className={styles.blValueTitle}>Works where you are</h4>
                    <p className={styles.blValueBody}>
                      Pre-built messaging connectors such as Slack, WhatsApp, Instagram, Telegrams, Gmail, and Teams. No custom wiring required.
                    </p>
                  </div>
                  <div className={styles.blValueCard}>
                    <div className={styles.blValueIcon}>
                      <MdCloud />
                    </div>
                    <h4 className={styles.blValueTitle}>Runs on any cloud</h4>
                    <p className={styles.blValueBody}>
                      Deploy on AWS, Azure, or your own on-prem Docker. No vendor lock-in. You stay in control of your data and infrastructure.
                    </p>
                  </div>
                </div>
              </div>
          
              {/* ── STEP 04 ── */}
              <div style={{ marginTop: '2rem' }}>
                <p className={styles.stepLabel}>Step 04 / See it in action</p>
                <h2 className={styles.contentTitle}>
                  See your Agent Kernel in action
                </h2>
                <p className={styles.contentBody}>
                  Curious what your agent can actually do? Here are some real starting points across industries.
                </p>
          
                <BusinessLeaderScenarios />
              </div>
          
            </div>
          )}

          {/* ── DEVELOPER CONTENT ── */}
          {selectedLevel === '02' && (
            <div ref={contentRef} className={styles.developerContent}>

              {/* Step 01 — Developer Analogy */}
              <div className={styles.developerAnalogy}>
                <p className={styles.devStepLabel}>Developer Analogy</p>
                <h2 className={styles.devTitle}>
                  Like an Operating System and Deployment Infrastructure for your AI Agent.
                </h2>
                <div className={styles.devDescription}>
                  <p className={styles.devIntro}>
                    Agent Kernel is like an operating system for AI assistants.
                  </p>
                  <div className={styles.devBulletList}>
                    <div className={styles.devBulletItem}>
                      <span className={styles.devBullet}>•</span>
                      <span className={styles.devBulletText}>Install it on your laptop, server, or cloud, and run AI agents hassle-free.</span>
                    </div>
                    <div className={styles.devBulletItem}>
                      <span className={styles.devBullet}>•</span>
                      <span className={styles.devBulletText}>No need to build infrastructure, APIs, or integrations.</span>
                    </div>
                    <div className={styles.devBulletItem}>
                      <span className={styles.devBullet}>•</span>
                      <span className={styles.devBulletText}>Everything works out of the box.</span>
                    </div>
                    <div className={styles.devBulletItem}>
                      <span className={styles.devBullet}>•</span>
                      <span className={styles.devBulletText}>Scales from single execution to thousands of agent invocations in parallel.</span>
                    </div>
                    <div className={styles.devBulletItem}>
                      <span className={styles.devBullet}>•</span>
                      <span className={styles.devBulletText}>Interacts with the real world automatically.</span>
                    </div>
                    <div className={styles.devBulletItem}>
                      <span className={styles.devBullet}>•</span>
                      <span className={styles.devBulletText}>Just define what your assistant should do.</span>
                    </div>
                  </div>
                </div>
              </div>

              {/* Architecture flow — 4 stacked layers */}
              <div className={styles.architectureWrapper}>
                <div className={styles.architectureStack}>
                  {[
                    {
                      num: '01',
                      label: 'Your Agent Logic',
                      sub: 'instructions · tools · framework SDK',
                    },
                    {
                      num: '02',
                      label: 'Agent Kernel Runtime',
                      sub: 'CLI · REST API · sessions · hooks · observability',
                    },
                    {
                      num: '03',
                      label: 'Cloud Infrastructure',
                      sub: 'AWS Lambda · ECS · Azure Functions · Container Apps',
                    },
                    {
                      num: '04',
                      label: 'Channels & Data',
                      sub: 'Slack · WhatsApp · Telegram · Gmail · Redis · DynamoDB',
                    },
                  ].map((layer, i, arr) => (
                    <div key={layer.label} className={styles.architectureLayerGroup}>
                      {/* Step number */}
                      <div className={styles.layerNumberWrapper}>
                        <div className={styles.layerNumberCircle}>
                          {layer.num}
                        </div>
                        {i < arr.length - 1 && (
                          <div className={styles.layerConnector} />
                        )}
                      </div>
                      {/* Content */}
                      <div className={styles.layerContentWrapper}>
                        <div className={styles.layerContentBox}>
                          <h3 className={styles.layerLabel}>{layer.label}</h3>
                          <p className={styles.layerSub}>{layer.sub}</p>
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
              
              {/* Step 02 — Available Features */}
              <div className={styles.devFeatureSection}>
                <p className={styles.devFeatureLabel}>All Enterprise Features Available Free And Open-Source</p>
                <h2 className={styles.devFeatureTitle}>
                  Focus on Agent Logic. We Handle the Rest.
                </h2>

                <div className={styles.devFeaturesGrid}>
                  {[
                    {
                      icon: MdBolt,
                      title: 'REST API Server',
                      body: 'FastAPI-based server out of the box. No boilerplate. Just run your agent.',
                      tag: 'FastAPI',
                    },
                    {
                      icon: MdAutoAwesome,
                      title: 'Multi-Framework Support',
                      body: 'OpenAI Agents, LangGraph, CrewAI, Google ADK.',
                      tag: '4 frameworks',
                    },
                    {
                      icon: MdSmartToy,
                      title: 'Session & Memory',
                      body: 'Built-in conversation state. Redis, DynamoDB, Cosmos DB or in-memory—your choice.',
                      tag: 'Pluggable',
                    },
                    {
                      icon: MdCloud,
                      title: 'Cloud Deployment',
                      body: 'Pre-built Terraform modules for AWS Lambda, ECS, Azure Functions, Container Apps.',
                      tag: 'Terraform',
                    },
                    {
                      icon: MdMessage,
                      title: 'Messaging Integrations',
                      body: 'Slack, WhatsApp, Instagram, Telegram, Gmail, Teams—plug and play.',
                      tag: '6+ channels',
                    },
                    {
                      icon: MdScience,
                      title: 'Testing Framework',
                      body: 'pytest-integrated test runner. Write automated tests for your AI agents like any other code.',
                      tag: 'pytest',
                    },
                    {
                      icon: MdLink,
                      title: 'Execution Hooks',
                      body: 'Pre/post hooks for RAG injection, input validation, response moderation, analytics.',
                      tag: 'Hooks',
                    },
                    {
                      icon: MdVisibility,
                      title: 'Observability',
                      body: 'Langfuse and OpenLLMetry tracing with one config line. No manual instrumentation.',
                      tag: '1 config line',
                    },
                  ].map((feature) => {
                    const IconComponent = feature.icon;
                    return (
                      <div key={feature.title} className={styles.devFeatureCard}>
                        <IconComponent className={styles.devFeatureIcon} />
                        <h3 className={styles.devFeatureCardTitle}>{feature.title}</h3>
                        <p className={styles.devFeatureCardBody}>{feature.body}</p>
                        <span className={styles.devFeatureTag}>
                          {feature.tag}
                        </span>
                      </div>
                    );
                  })}
                </div>
              </div>

              {/* Step 03 — Framework Selection */}
              <div className={styles.devFrameworkSection}>
                <p className={styles.devFrameworkLabel}>No lock-in. Your choice</p>
                <h2 className={styles.devFrameworkTitle}>Use The Framework You Prefer</h2>

                <div className={styles.devFrameworkContainer}>
                  {/* Left Column - Body & Buttons */}
                  <div className={styles.devFrameworkButtonsCol}>
                    <p className={styles.devFrameworkBody}>
                      Choose a supported framework that fits your team, while Agent Kernel gives you a consistent production-ready layer for deployment, APIs, sessions, and integrations.
                    </p>
                    
                    <div className={styles.devFrameworkButtonsGroup}>
                      {[
                        { id: 'openai', label: 'OpenAI Agents' },
                        { id: 'crewai', label: 'CrewAI' },
                        { id: 'langgraph', label: 'LangGraph' },
                        { id: 'adk', label: 'Google ADK' },
                      ].map((fw) => (
                        <button
                          key={fw.id}
                          onClick={() => setSelectedFramework(fw.id)}
                          className={`${styles.devFrameworkButton} ${
                            selectedFramework === fw.id ? styles.devFrameworkButtonActive : ''
                          }`}
                        >
                          {fw.label}
                        </button>
                      ))}
                    </div>
                  </div>

                  {/* Right Column - Code Display */}
                  <div className={styles.devFrameworkCodeCol}>
                    {selectedFramework === 'openai' && (
                      <div className={styles.devFrameworkCodeBlock}>
                        <div className={styles.devFrameworkCodeHeader}>
                          <p className={styles.devFrameworkCodeLabel}>Installation:</p>
                          <button
                            onClick={() => copyToClipboard('pip install agentkernel[openai]', 'openai-install')}
                            className={styles.devFrameworkCopyBtn}
                            title="Copy code"
                          >
                            {copiedCode === 'openai-install' ? '✓ Copied' : 'Copy'}
                          </button>
                        </div>
                        <pre className={styles.devFrameworkCodePre}>
                          <code>pip install agentkernel[openai]</code>
                        </pre>
                        <div className={styles.devFrameworkCodeHeader}>
                          <p className={styles.devFrameworkCodeLabel}>Basic Usage:</p>
                          <button
                            onClick={() => copyToClipboard(`from agents import Agent as OpenAIAgent
from agentkernel.cli import CLI
from agentkernel.openai import OpenAIModule

agent = OpenAIAgent(
    name="assistant",
    instructions="You are a helpful assistant.",
)

OpenAIModule([agent])

if __name__ == "__main__":
    CLI.main()`, 'openai-usage')}
                            className={styles.devFrameworkCopyBtn}
                            title="Copy code"
                          >
                            {copiedCode === 'openai-usage' ? '✓ Copied' : 'Copy'}
                          </button>
                        </div>
                        <pre className={styles.devFrameworkCodePre}>
                          <code>{`from agents import Agent as OpenAIAgent
from agentkernel.cli import CLI
from agentkernel.openai import OpenAIModule

agent = OpenAIAgent(
    name="assistant",
    instructions="You are a helpful assistant.",
)

OpenAIModule([agent])

if __name__ == "__main__":
    CLI.main()`}</code>
                        </pre>
                        <Link to="/docs/frameworks/openai" className={styles.devFrameworkDocLink}>
                          View Full Documentation →
                        </Link>
                      </div>
                    )}

                    {selectedFramework === 'crewai' && (
                      <div className={styles.devFrameworkCodeBlock}>
                        <div className={styles.devFrameworkCodeHeader}>
                          <p className={styles.devFrameworkCodeLabel}>Installation:</p>
                          <button
                            onClick={() => copyToClipboard('pip install agentkernel[crewai]', 'crewai-install')}
                            className={styles.devFrameworkCopyBtn}
                            title="Copy code"
                          >
                            {copiedCode === 'crewai-install' ? '✓ Copied' : 'Copy'}
                          </button>
                        </div>
                        <pre className={styles.devFrameworkCodePre}>
                          <code>pip install agentkernel[crewai]</code>
                        </pre>
                        <div className={styles.devFrameworkCodeHeader}>
                          <p className={styles.devFrameworkCodeLabel}>Basic Usage:</p>
                          <button
                            onClick={() => copyToClipboard(`from crewai import Agent as CrewAgent
from agentkernel.cli import CLI
from agentkernel.crewai import CrewAIModule

agent = CrewAgent(
    role="assistant",
    goal="Help users with their questions",
    backstory="You are a helpful AI assistant",
    verbose=False,
)

CrewAIModule([agent])

if __name__ == "__main__":
    CLI.main()`, 'crewai-usage')}
                            className={styles.devFrameworkCopyBtn}
                            title="Copy code"
                          >
                            {copiedCode === 'crewai-usage' ? '✓ Copied' : 'Copy'}
                          </button>
                        </div>
                        <pre className={styles.devFrameworkCodePre}>
                          <code>{`from crewai import Agent as CrewAgent
from agentkernel.cli import CLI
from agentkernel.crewai import CrewAIModule

agent = CrewAgent(
    role="assistant",
    goal="Help users with their questions",
    backstory="You are a helpful AI assistant",
    verbose=False,
)

CrewAIModule([agent])

if __name__ == "__main__":
    CLI.main()`}</code>
                        </pre>
                        <Link to="/docs/frameworks/crewai" className={styles.devFrameworkDocLink}>
                          View Full Documentation →
                        </Link>
                      </div>
                    )}

                    {selectedFramework === 'langgraph' && (
                      <div className={styles.devFrameworkCodeBlock}>
                        <div className={styles.devFrameworkCodeHeader}>
                          <p className={styles.devFrameworkCodeLabel}>Installation:</p>
                          <button
                            onClick={() => copyToClipboard('pip install agentkernel[langgraph]', 'langgraph-install')}
                            className={styles.devFrameworkCopyBtn}
                            title="Copy code"
                          >
                            {copiedCode === 'langgraph-install' ? '✓ Copied' : 'Copy'}
                          </button>
                        </div>
                        <pre className={styles.devFrameworkCodePre}>
                          <code>pip install agentkernel[langgraph]</code>
                        </pre>
                        <div className={styles.devFrameworkCodeHeader}>
                          <p className={styles.devFrameworkCodeLabel}>Basic Usage:</p>
                          <button
                            onClick={() => copyToClipboard(`from typing import TypedDict
from langgraph.graph import StateGraph, END
from agentkernel.cli import CLI
from agentkernel.langgraph import LangGraphModule

class State(TypedDict):
    messages: list

def agent_node(state: State):
    return {"messages": state["messages"] + ["response"]}

workflow = StateGraph(State)
workflow.add_node("agent", agent_node)
workflow.set_entry_point("agent")
workflow.add_edge("agent", END)

graph = workflow.compile()
graph.name = "assistant"

LangGraphModule([graph])

if __name__ == "__main__":
    CLI.main()`, 'langgraph-usage')}
                            className={styles.devFrameworkCopyBtn}
                            title="Copy code"
                          >
                            {copiedCode === 'langgraph-usage' ? '✓ Copied' : 'Copy'}
                          </button>
                        </div>
                        <pre className={styles.devFrameworkCodePre}>
                          <code>{`from typing import TypedDict
from langgraph.graph import StateGraph, END
from agentkernel.cli import CLI
from agentkernel.langgraph import LangGraphModule

class State(TypedDict):
    messages: list

def agent_node(state: State):
    return {"messages": state["messages"] + ["response"]}

workflow = StateGraph(State)
workflow.add_node("agent", agent_node)
workflow.set_entry_point("agent")
workflow.add_edge("agent", END)

graph = workflow.compile()
graph.name = "assistant"

LangGraphModule([graph])

if __name__ == "__main__":
    CLI.main()`}</code>
                        </pre>
                        <Link to="/docs/frameworks/langgraph" className={styles.devFrameworkDocLink}>
                          View Full Documentation →
                        </Link>
                      </div>
                    )}

                    {selectedFramework === 'adk' && (
                      <div className={styles.devFrameworkCodeBlock}>
                        <div className={styles.devFrameworkCodeHeader}>
                          <p className={styles.devFrameworkCodeLabel}>Installation:</p>
                          <button
                            onClick={() => copyToClipboard('pip install agentkernel[adk]', 'adk-install')}
                            className={styles.devFrameworkCopyBtn}
                            title="Copy code"
                          >
                            {copiedCode === 'adk-install' ? '✓ Copied' : 'Copy'}
                          </button>
                        </div>
                        <pre className={styles.devFrameworkCodePre}>
                          <code>pip install agentkernel[adk]</code>
                        </pre>
                        <div className={styles.devFrameworkCodeHeader}>
                          <p className={styles.devFrameworkCodeLabel}>Basic Usage:</p>
                          <button
                            onClick={() => copyToClipboard(`from adk import Agent as ADKAgent
from agentkernel.cli import CLI
from agentkernel.adk import ADKModule

agent = ADKAgent(
    name="assistant",
    model="gemini-2.0-flash-exp",
    instructions="You are a helpful AI assistant",
)

ADKModule([agent])

if __name__ == "__main__":
    CLI.main()`, 'adk-usage')}
                            className={styles.devFrameworkCopyBtn}
                            title="Copy code"
                          >
                            {copiedCode === 'adk-usage' ? '✓ Copied' : 'Copy'}
                          </button>
                        </div>
                        <pre className={styles.devFrameworkCodePre}>
                          <code>{`from adk import Agent as ADKAgent
from agentkernel.cli import CLI
from agentkernel.adk import ADKModule

agent = ADKAgent(
    name="assistant",
    model="gemini-2.0-flash-exp",
    instructions="You are a helpful AI assistant",
)

ADKModule([agent])

if __name__ == "__main__":
    CLI.main()`}</code>
                        </pre>
                        <Link to="/docs/frameworks/google-adk" className={styles.devFrameworkDocLink}>
                          View Full Documentation →
                        </Link>
                      </div>
                    )}
                  </div>
                </div>
              </div>
            </div>
          )}
          {selectedLevel === '03' && (
            <div ref={contentRef} className={styles.levelContent}>
              <div className={styles.contentStep}>
                <h2 className={styles.contentTitle}>
                  Advanced Capabilities for Production AI
                </h2>
                <p className={styles.contentBody}>
                  Agent Kernel gives you the production-grade features that enterprise AI systems need, without framework lock-in or vendor dependency.
                </p>
              </div>

              <div className={styles.contentStep}>
                <h2 className={styles.contentTitle}>Core Capabilities</h2>

                <div className={styles.capabilitiesGrid}>
                  {[
                    {
                      icon: MdSwapHoriz,
                      title: 'Framework Agnostic',
                      body: 'Run OpenAI Agents, LangGraph, CrewAI, and Google ADK side by side. Switch frameworks with 2 import lines.',
                    },
                    {
                      icon: MdCloud,
                      title: 'Multi-Cloud',
                      body: 'Same agent code deploys to AWS Lambda, ECS, Azure Functions, or Container Apps. Zero vendor lock-in.',
                    },
                    {
                      icon: MdMemory,
                      title: 'Session & Memory',
                      body: 'Built-in volatile and non-volatile caching. Backends: Redis, DynamoDB, Cosmos DB, in-memory.',
                    },
                    {
                      icon: MdSettings,
                      title: 'Execution Hooks',
                      body: 'Pre/post-execution hooks for guardrails, RAG injection, analytics, and response moderation.',
                    },
                    {
                      icon: FaSlack,
                      title: 'Messaging Integrations',
                      body: 'Slack, WhatsApp, Messenger, Instagram, Telegram, Gmail — built-in. Plug and play.',
                    },
                    {
                      icon: MdBugReport,
                      title: 'Testing Framework',
                      body: 'pytest-integrated agent testing with fuzzy, semantic, and fallback comparison modes.',
                    },
                    {
                      icon: MdSecurity,
                      title: 'Guardrails',
                      body: 'OpenAI and AWS Bedrock guardrails for PII detection, jailbreak prevention, and moderation.',
                    },
                    {
                      icon: MdVisibility,
                      title: 'Observability & Tracing',
                      body: 'LangFuse and OpenLLMetry tracing with one config line. Full visibility into every call.',
                    },
                  ].map((feature) => {
                    const IconComponent = feature.icon;
                    return (
                      <div key={feature.title} className={styles.capabilityCard}>
                        <IconComponent className={styles.capabilityIcon} />
                        <h3 className={styles.capabilityTitle}>{feature.title}</h3>
                        <p className={styles.capabilityBody}>{feature.body}</p>
                      </div>
                    );
                  })}
                </div>
              </div>

              <div className={styles.contentStep}>
                <h2 className={styles.contentTitle}>Production Deployment</h2>
                <p className={styles.contentBody}>
                  Deploy with full Terraform modules, pre-configured best practices, and zero cloud lock-in. Same code runs everywhere.
                </p>
              </div>
            </div>
          )}
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
        <Levels />
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
