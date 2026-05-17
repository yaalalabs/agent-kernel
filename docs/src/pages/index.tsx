import React, { useRef, useEffect, useState } from 'react';
import Link from '@docusaurus/Link';
import useDocusaurusContext from '@docusaurus/useDocusaurusContext';
import Layout from '@theme/Layout';
import styles from './index.module.css';
import gsap from 'gsap';
import { ScrollTrigger } from 'gsap/dist/ScrollTrigger';
import { ScrollToPlugin } from 'gsap/dist/ScrollToPlugin';
import AgentKernelArchDiagram from '../components/AgentKernelArchDiagram';
import BuildingAgentsFlowDiagram from '../components/BuildingAgentsFlowDiagram';
import RunningAgentsFlowDiagram from '../components/RunningAgentsFlowDiagram';
import AgentKernelSitsInFlowDiagram from '../components/AgentKernelSitsInFlowDiagram';
import AgentExecutionFlowDiagram from '../components/AgentExecutionFlowDiagram';
import ParticleSphere from '../components/ParticleSphere';
import PlantParticlesBackground from '../components/PlantParticlesBackground';
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
  MdAutoAwesome,
  MdTerminal,
  MdBuild,
  MdExtension,
  MdIntegrationInstructions,
  MdCloudUpload,
  MdBolt,
  MdMessage,
  MdScience,
  MdLink,
  MdSmartToy,
  MdPermMedia,
  MdLanguage,
  MdCheck,
  MdClose,
  MdForum,
  MdCached,
  MdStorage,
  MdShield,
  MdStopCircle,
} from 'react-icons/md';
import { FaGithub, FaDiscord, FaPython, FaSlack, FaWhatsapp, FaInstagram, FaTelegram, FaAws, FaMicrosoft } from 'react-icons/fa';
import { SiTerraform, SiGmail, SiGooglecloud } from 'react-icons/si';
import { FaFacebookMessenger } from 'react-icons/fa6';

/* ─── What's New Banner ─────────────────────────────────────────────────── */

function WhatsNewBanner() {
  return (
    <div className={styles.whatsNewBanner}>
      <div className={styles.whatsNewInner}>
        <span className={styles.whatsNewIconWrap}>
          <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9"/>
            <path d="M13.73 21a2 2 0 0 1-3.46 0"/>
          </svg>
        </span>
        <span className={styles.whatsNewText}>
          <strong>Knowledge Base Support</strong> — ChromaDB, Neo4j &amp; Starburst Galaxy built-in, plus a <strong>custom adapter API</strong> to plug in any backend.
        </span>
        <Link to="/docs/next/architecture/knowledge-bases" className={styles.whatsNewLink}>
          Read More →
        </Link>
      </div>
    </div>
  );
}

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
      <div className="container">
        <div className={styles.heroContent}>
          <h1 ref={titleRef} className={styles.heroTitle}>Agent Kernel</h1>
          <p ref={taglineRef} className={styles.heroTagline}>
            An Open Source Operating System for
            <br />
            Scalable & Compliant Enterprise AI Agents.
          </p>
          <p ref={bodyRef} className={styles.heroBody}>
            Agent Kernel is the open source platform for building and deploying enterprise AI agents seamlessly at scale. Agent Kernel reduces months of engineering work to minutes. Works with any major Agentic technology, runs on any cloud, interfaces with all mainstream communication channels seamlessly out of the box, no framework / platform lock-in, production ready from day one.
          </p>
          <div ref={buttonsRef} className={styles.heroButtons}>
            <Link className={`button button--primary button--lg ${styles.btnPrimary}`} to="/docs">
              <span className={styles.btnIcon}>→</span>
              Get Started
            </Link>
            <button
              type="button"
              className={`button button--secondary button--lg ${styles.btnSecondary}`}
              onClick={() => document.getElementById('agent-skills')?.scrollIntoView({ behavior: 'smooth', block: 'start' })}
            >
              <span className={styles.btnIconSecondary}>→</span>
              Agent Skills
            </button>
            <Link
              className={`button button--secondary button--lg ${styles.btnSecondary}`}
              to="https://github.com/yaalalabs/agent-kernel"
              target="_blank"
              rel="noopener noreferrer">
              <span className={styles.btnIconSecondary}><FaGithub /></span>
              View on GitHub
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
    { name: 'Smolagents', logo: '/img/integrations/smolagents.png', link: 'https://huggingface.co/docs/smolagents/index' },
    { name: 'LiveKit', logo: '/img/integrations/livekit.png', link: 'https://docs.livekit.io/' },
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
          <span className={styles.affiliationSeparator}>●</span>
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

/* ─── Agent Skills ────────────────────────────────────────────────────── */

const AGENT_SKILLS = [
  {
    icon: MdRocketLaunch,
    name: 'ak-init',
    description:
      'Scaffolds a clean, ready-to-build project structure so you can skip the setup and start building straight away. Works with any framework or deployment target.',
    pills: ['Any framework', 'Any deployment target', 'Guided setup'],
  },
  {
    icon: MdBuild,
    name: 'ak-build',
    description:
      'Adds tools, agents, and task handoffs to your project. Your coding assistant understands your framework, so the code it generates actually works.',
    pills: ['Tool integration', 'Agent handoffs', 'Framework-aware'],
  },
  {
    icon: MdExtension,
    name: 'ak-add-capabilities',
    description:
      'Plugs in production-grade features like guardrails, tracing, session memory, and multimodal support without having to build them from scratch.',
    pills: ['Guardrails', 'Tracing', 'Session memory', 'MCP support', 'Multimodal'],
  },
  {
    icon: MdIntegrationInstructions,
    name: 'ak-add-integration',
    description:
      'Connects your agent to the messaging platforms your users already rely on, with authentication and message handling taken care of for each one.',
    pills: ['Slack', 'WhatsApp', 'Messenger', 'Instagram', 'Telegram', 'Gmail'],
  },
  {
    icon: MdCloudUpload,
    name: 'ak-cloud-deploy',
    description:
      'Deploys your agent to the cloud with full Terraform configuration included. Pick your platform and it handles the infrastructure, no manual setup needed.',
    pills: ['AWS Lambda', 'ECS', 'Azure Functions', 'Container Apps', 'Full Terraform'],
  },
  {
    icon: MdBugReport,
    name: 'ak-test',
    description:
      'Tests your agent across multiple modes including fuzzy, judge, and fallback. When something breaks, a step-by-step debugging playbook helps you fix it fast.',
    pills: ['Fuzzy testing', 'Judge mode', 'Fallback testing', 'Debugging playbook'],
  },
] as const;

function AgentSkills() {
  return (
    <section id="agent-skills" className={styles.agentSkillsSection}>
      <div className="container">
        <div className={styles.agentSkillsContainer}>
          <div className={styles.sectionHeader}>
            <h2 className={styles.sectionTitle}>Your coding assistant, supercharged.</h2>
            <p className={styles.sectionSubtitle}>
              Agent Skills works with the tools you already use, like Copilot, Claude, Cursor, or
              Windsurf, to help you build and ship AI agents faster. No more guesswork, no more
              broken code suggestions.
            </p>
          </div>

          <div className={styles.agentSkillsSectionLabel}>Get started in two commands</div>
          <div className={styles.agentSkillsCodeBlock}>
            <div className={styles.agentSkillsCodeComment}># 1. Install the CLI</div>
            <div>
              <span className={styles.agentSkillsCodeCmd}>$</span>{' '}
              <span className={styles.agentSkillsCodeArg}>pip install agentkernel</span>
            </div>
            <br />
            <div className={styles.agentSkillsCodeComment}># 2. Install skills for your coding assistant</div>
            <div>
              <span className={styles.agentSkillsCodeCmd}>$</span>{' '}
              <span className={styles.agentSkillsCodeArg}>ak skill install</span>
            </div>
            <div className={styles.agentSkillsCodeComment}>&nbsp;&nbsp;or target a specific assistant:</div>
            <div>
              <span className={styles.agentSkillsCodeCmd}>$</span>{' '}
              <span className={styles.agentSkillsCodeArg}>ak skill install --assistant claude</span>
            </div>
          </div>

          <div className={styles.agentSkillsSectionLabel}>What each skill does</div>
          <div className={styles.agentSkillsSkillList}>
            {AGENT_SKILLS.map((skill) => {
              const Icon = skill.icon;

              return (
                <article key={skill.name} className={styles.agentSkillsSkillCard}>
                  <div className={styles.agentSkillsSkillHeader}>
                    <Icon aria-hidden className={styles.agentSkillsSkillIcon} />
                    <p className={styles.agentSkillsSkillName}>{skill.name}</p>
                  </div>
                  <p className={styles.agentSkillsSkillBody}>{skill.description}</p>
                  <div className={styles.agentSkillsPillRow}>
                    {skill.pills.map((pill) => (
                      <span key={pill} className={styles.agentSkillsPill}>
                        {pill}
                      </span>
                    ))}
                  </div>
                </article>
              );
            })}
          </div>

          <div className={styles.agentSkillsFooter}>
            <Link className={styles.agentSkillsCtaLink} to="/docs">
              Learn more about Agent Skills <span aria-hidden>→</span>
            </Link>
          </div>
        </div>
      </div>
    </section>
  );
}

/* ─── Deployment ────────────────────────────────────────────────────────── */

function Deployment() {
  const clouds = [
    {
      icon: <FaAws className={styles.cloudIconSvg} />,
      name: 'Amazon AWS',
      description: 'Serverless or containerized deployments with Terraform modules.',
      modes: ['AWS Lambda (Serverless)', 'AWS ECS/Fargate (Containerized)'],
      modules: [
        { name: 'AWS Serverless', url: 'https://registry.terraform.io/modules/yaalalabs/ak-serverless/aws' },
        { name: 'AWS Containerized', url: 'https://registry.terraform.io/modules/yaalalabs/ak-containerized/aws' },
      ],
      comingSoon: false,
    },
    {
      icon: <FaMicrosoft className={styles.cloudIconSvg} />,
      name: 'Microsoft Azure',
      description: 'Functions or Container Apps with Cosmos DB session storage.',
      modes: ['Azure Functions (Serverless)', 'Azure Container Apps (Containerized)'],
      modules: [
        { name: 'Azure Serverless', url: 'https://registry.terraform.io/modules/yaalalabs/ak-serverless/azurerm' },
        { name: 'Azure Containerized', url: 'https://registry.terraform.io/modules/yaalalabs/ak-containerized/azurerm' },
      ],
      comingSoon: false,
    },
    {
      icon: <SiGooglecloud className={styles.cloudIconSvg} />,
      name: 'Google Cloud',
      description: 'Cloud Run and Cloud Functions deployments — Terraform modules in progress.',
      modes: ['Cloud Run (Containerized)', 'Cloud Functions (Containerized)'],
      modules: [],
      comingSoon: true,
    },
  ];

  return (
    <section className={styles.section}>
      <div>
        <div className={styles.sectionHeader}>
          <h2 className={styles.sectionTitle}>Deploy Anywhere</h2>
          <p className={styles.sectionSubtitle}>
            Run the same agent code on AWS, Azure, or your own on-prem Docker.{' '}
            <br />
            Zero rewrites. Includes production-ready Terraform modules with best practices baked in.
          </p>
        </div>

        <div className={styles.cloudGrid}>
          {clouds.map((c, i) => (
            <div key={i} className={styles.cloudCard}>
              {/* Logo */}
              <div className={styles.cloudIcon}>{c.icon}</div>

              {/* Name + badge */}
              <div className={styles.cloudNameRow}>
                <h3 className={styles.cloudName}>{c.name}</h3>
                {c.comingSoon && (
                  <span className={styles.cloudComingSoonBadge}>COMING SOON</span>
                )}
              </div>

              {/* Description */}
              <p className={styles.cloudDescription}>{c.description}</p>

              {/* Mode bullets */}
              <ul className={styles.cloudModes}>
                {c.modes.map((m, j) => (
                  <li key={j}>
                    <span className={styles.arrow}>→</span>
                    {m}
                  </li>
                ))}
              </ul>

              {/* Terraform links */}
              {c.modules.length > 0 && (
                <div className={styles.cloudModules}>
                  {c.modules.map((m, j) => (
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
                  ))}
                </div>
              )}
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}

/* ─── Community / CTA ───────────────────────────────────────────────────── */

function Community() {
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
              <span className={styles.btnIcon}>→</span>
              Get Started
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
        body: 'Customers ask "where\'s my order?" across your website, WhatsApp, and Instagram - and your team copies tracking numbers between systems all day.',
      },
      agent: {
        heading: 'The Agent',
        sub: 'What it actually does',
        body: 'The agent connects to the order system, shipping carriers, and payment gateway. It looks up orders in real time, tracks shipments, processes returns or exchanges, triggers refunds, and keeps the conversation memory across communication channels and sessions.',
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
        body: 'Leads come in from your website, ads, and events - but they sit in a spreadsheet until someone manually qualifies them and books a meeting.',
      },
      agent: {
        heading: 'The Agent',
        sub: 'What it actually does',
        body: 'The agent qualifies leads, scores them, creates CRM contacts, books discovery calls, tags not-ready leads for follow-up, logs notes, and updates deal stages. Specialized agents can split conversation, CRM work, and scheduling.',
      },
      whyAk: {
        heading: 'Why Agent Kernel',
        sub: 'The Agent Kernel advantage',
        body: 'This proves multi-agent collaboration, easy API integrations, and persistent knowledge of a returning lead.',
      },
    },
    itops: {
      title: 'IT Help Desk Agent',
      channels: 'Slack / Teams / Email',
      problem: {
        heading: 'The Problem',
        sub: "Why it's painful",
        body: 'Employees submit IT tickets for password resets, software access, and VPN issues - then wait hours for a human to do something that takes 30 seconds.',
      },
      agent: {
        heading: 'The Agent',
        sub: 'What it actually does',
        body: 'The agent works in Slack and Microsoft Teams. It resets passwords through the identity provider, provisions software, restarts services, checks status dashboards, and creates escalation tickets when a human is needed.',
      },
      whyAk: {
        heading: 'Why Agent Kernel',
        sub: 'The Agent Kernel advantage',
        body: 'Customizable workflows via hooks, guardrails, and audit-ready session tracking make action-taking safe and traceable.',
      },
    },
    insurance: {
      title: 'Claims Intake Agent',
      channels: 'Website / WhatsApp / Email',
      problem: {
        heading: 'The Problem',
        sub: "Why it's painful",
        body: 'Filing an insurance claim means phone trees, paper forms, and weeks of back-and-forth before anything happens.',
      },
      agent: {
        heading: 'The Agent',
        sub: 'What it actually does',
        body: 'The agent accepts vehicle-damage photos over WhatsApp or Telegram, analyzes them with multimodal support, creates the claim, checks policy details, routes it to the right adjuster, updates the customer, and can trigger payment for straightforward claims.',
      },
      whyAk: {
        heading: 'Why Agent Kernel',
        sub: 'The Agent Kernel advantage',
        body: 'This use case proves multimodal (images and files) input, multi-agent pipelines, guardrails for regulated data, and persistent, long running user sessions.',
      },
    },
    logistics: {
      title: 'Shipment Tracking Agent',
      channels: 'WhatsApp / Telegram / Email',
      problem: {
        heading: 'The Problem',
        sub: "Why it's painful",
        body: 'Your operations team juggles dashboards, carrier portals, and a shared inbox to keep shipments on track - and customers still get surprised by delays.',
      },
      agent: {
        heading: 'The Agent',
        sub: 'What it actually does',
        body: 'The agent monitors carrier APIs, spots delays, reroutes shipments, updates ETAs, notifies customers on their preferred channel, and alerts internal teams in Slack. Different agents can monitor, communicate, and coordinate operations.',
      },
      whyAk: {
        heading: 'Why Agent Kernel',
        sub: 'The Agent Kernel advantage',
        body: 'This shows multi-channel notifications, multi-agent coordination, cloud flexibility, and observability of every decision.',
      },
    },
    hr: {
      title: 'Recruiting Screener Agent',
      channels: 'Email / Slack / Website',
      problem: {
        heading: 'The Problem',
        sub: "Why it's painful",
        body: 'Your hiring pipeline is bottlenecked by scheduling, reminders, interviewer feedback, and stage updates rather than by finding candidates.',
      },
      agent: {
        heading: 'The Agent',
        sub: 'What it actually does',
        body: 'When a candidate enters the interview stage, the agent checks availability, sends scheduling links over email, confirms bookings, creates meeting rooms, sends reminders, prompts interviewers for feedback in Slack, compiles summaries, and updates the Application Tracking System (ATS).',
      },
      whyAk: {
        heading: 'Why Agent Kernel',
        sub: 'The Agent Kernel advantage',
        body: 'This demonstrates Gmail integration, Slack coordination, ATS and calendar tool use, and long-running session memory across the candidate journey.',
      },
    },
  };
 
  const active = scenarios[activeTab];
 
  return (
    <div className={styles.blScenarios}>
 
      {/* ── Tab buttons — horizontally scrollable on mobile ── */}
      <div className={styles.blTabBar} role="tablist" aria-label="Industry scenarios">
        {tabs.map((t) => (
          <button
            key={t.id}
            role="tab"
            aria-selected={activeTab === t.id}
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

const DEV_FEATURE_GROUPS = [
  {
    title: 'Build & Interface',
    cols: 4 as const,
    features: [
      {
        icon: MdTerminal,
        title: 'CLI for Prototyping',
        body: 'Easy interfacing your agents on your laptop via Agent Kernel’s command line interface.',
      },
      {
        icon: MdBolt,
        title: 'REST API Server',
        body: 'FastAPI-based server out of the box. No boilerplate. Just run your agent.',
      },
      {
        icon: MdCode,
        title: 'Native MCP and A2A support',
        body: 'Expose agents as tools (MCP) and enable agent-to-agent collaboration (A2A). Makes integration with external AI systems straightforward.',
      },
      {
        icon: MdAutoAwesome,
        title: 'Multi-Framework Support',
        body: 'Run OpenAI Agents, LangGraph, CrewAI, Google ADK, Smolagents, LiveKit side-by-side. Keep one runtime across teams while using the best framework per use case.',
      },
    ],
  },
  {
    title: 'Runtime & Extensibility',
    cols: 3 as const,
    features: [
      {
        icon: MdSmartToy,
        title: 'Pluggable Session & Memory',
        body: 'Start local in-memory, scale to Redis, DynamoDB, or Cosmos DB in production. Switch via config, not code rewrites.',
      },
      {
        icon: MdLink,
        title: 'Execution Hooks',
        body: 'Pre/post hooks for RAG injection, input validation, response moderation, analytics.',
      },
      {
        icon: MdPermMedia,
        title: 'Multimodal Support',
        body: 'In-built framework-neutral multimodal support across all integration channels. Handle files/images cleanly and keep sessions lightweight. Additional voice and video support via LiveKit.',
      },
    ],
  },
  {
    title: 'Ship & Secure',
    cols: 3 as const,
    features: [
      {
        icon: MdSecurity,
        title: 'Guardrails and Content Safety',
        body: 'Input and output protection in the same runtime pipeline. Supports policy checks for safety, PII handling, and jailbreak defense.',
      },
      {
        icon: MdCloud,
        title: 'Cloud Deployment',
        body: 'Pre-built Terraform modules for AWS Lambda, ECS, Azure Functions, Container Apps, GCP Cloud Run, GCP Cloud Run Functions.',
      },
      {
        icon: MdLanguage,
        title: 'Reliability',
        body: 'Built for resilient cloud deployments with health checks and failover patterns.',
      },
    ],
  },
  {
    title: 'Integrate & Observe',
    cols: 3 as const,
    features: [
      {
        icon: MdMessage,
        title: 'Messaging Integrations',
        body: 'Slack, WhatsApp, Instagram, Telegram, Gmail, Teams, Messenger plug and play.',
      },
      {
        icon: MdScience,
        title: 'Testing Framework',
        body: 'pytest-integrated test runner. Write deterministic automated test scenarios for your AI agents like any other code.',
      },
      {
        icon: MdVisibility,
        title: 'Observability',
        body: 'Langfuse and OpenLLMetry tracing with one config line. No manual instrumentation. Trace requests, latency, tool calls, and token behavior.',
      },
    ],
  },
];

const AI_ENGINEER_ARCH_LAYERS = [
  {
    num: '01',
    label: 'Your Agent Logic',
    items: ['Domain-Specific Agent Code', 'Business Rules', 'Prompts & Tools'],
  },
  {
    num: '02',
    label: 'Agent Kernel Core',
    items: [
      'Agent Module',
      'Agent Wrapper',
      'Framework-Specific Runner',
      'Session Manager',
      'Runtime',
      'Pre / Post Hooks',
    ],
  },
  {
    num: '03',
    label: 'Framework Adapters',
    items: [
      'LangGraph',
      'OpenAI Agents',
      'CrewAI',
      'Google ADK',
      'Smolagents',
      'LiveKit',
      'Bring your own [advanced]',
    ],
  },
  {
    num: '04',
    label: 'Storage & Memory',
    items: ['In-Memory', 'Redis', 'DynamoDB', 'CosmosDB', 'Firestore'],
  },
  {
    num: '05',
    label: 'Knowledge Bases',
    items: ['ChromaDB', 'Neo4j', 'Starburst', 'SQLDB'],
  },
  {
    num: '06',
    label: 'Observability',
    items: ['LangFuse', 'OpenLLMetry'],
  },
  {
    num: '07',
    label: 'Execution Surface',
    items: [
      'AWS Lambda',
      'ECS',
      'Azure Functions',
      'Container Apps',
      'GCP Cloud Run',
      'GCP Cloud Run Functions',
    ],
  },
  {
    num: '08',
    label: 'Interfacing',
    items: ['CLI', 'MCP', 'A2A', 'REST API'],
  },
  {
    num: '09',
    label: 'Channels',
    items: [
      'Slack',
      'Teams',
      'WhatsApp',
      'Telegram',
      'Messenger',
      'Instagram',
      'Gmail',
      'Redis',
      'DynamoDB',
    ],
  },
];

const AI_ENGINEER_MEMORY_LAYERS = [
  {
    title: 'Conversational State (Session)',
    icon: MdForum,
    bullets: [
      'The agent remembers the conversation naturally across turns.',
      'This is the memory that keeps chat continuity.',
    ],
  },
  {
    title: 'Volatile Cache (Per Request)',
    icon: MdCached,
    bullets: [
      'A scratchpad for one request only.',
      'Great for RAG snippets, temporary file reads, and intermediate results.',
      'Auto-clears after every response.',
    ],
  },
  {
    title: 'Non-Volatile Cache (Session)',
    icon: MdStorage,
    bullets: [
      'Session memory for supporting data that should persist.',
      'Perfect for user preferences, auth context, and running counters.',
      'Available to tools/hooks without spending LLM tokens.',
    ],
  },
] as const;

const AI_ENGINEER_HOOK_PIPELINE = [
  {
    title: 'Pre-Execution Hooks',
    icon: MdShield,
    bullets: [
      'Validate and enrich input before the LLM runs.',
      'Typical uses: guardrails, redaction, RAG injection, request shaping.',
    ],
    highlight: false,
  },
  {
    title: 'Agent Execution',
    icon: MdSmartToy,
    bullets: ['Your existing framework logic runs as-is.'],
    highlight: false,
  },
  {
    title: 'Post-Execution Hooks',
    icon: MdSecurity,
    bullets: [
      'Apply output checks and final formatting before returning to users.',
      'Typical uses: moderation, compliance notes, analytics, audit logging.',
    ],
    highlight: false,
  },
  {
    title: 'Early Termination',
    icon: MdStopCircle,
    badge: 'Early termination',
    bullets: [
      'Stop unsafe or invalid requests early and return a controlled response.',
      'Useful for input guardrails, rate limits, cached shortcuts, and circuit breakers.',
    ],
    highlight: true,
  },
] as const;

type AkCompareCellStatus = 'positive' | 'negative' | 'partial';

interface AkCompareCell {
  status: AkCompareCellStatus;
  text?: string;
}

const AI_ENGINEER_COMPARE_COLUMNS = {
  cloud: 'Bedrock AgentCore / Azure AI Foundry / Google Vertex AI',
  cloudShort: 'Bedrock / Azure / Google',
  frameworks: 'LangGraph · CrewAI · OpenAI Agents etc',
  frameworksShort: 'LangGraph · CrewAI · OpenAI',
  agentKernel: 'Agent Kernel',
} as const;

const AI_ENGINEER_COMPARISON_ROWS: {
  feature: string;
  featureHint?: string;
  cloud: AkCompareCell;
  frameworks: AkCompareCell;
  agentKernel: AkCompareCell;
}[] = [
  {
    feature: 'Switch cloud platform later?',
    cloud: { status: 'negative', text: 'Rewrite' },
    frameworks: { status: 'positive', text: 'You build it' },
    agentKernel: { status: 'positive', text: 'One config change' },
  },
  {
    feature: 'Multi-framework agent execution?',
    cloud: { status: 'negative', text: 'Not possible' },
    frameworks: { status: 'negative', text: 'Not possible' },
    agentKernel: { status: 'positive', text: 'Run in one runtime' },
  },
  {
    feature: 'Out of Box integrations?',
    featureHint: '(i.e. Slack / Teams / REST / A2A / MCP)',
    cloud: { status: 'partial', text: 'Partial' },
    frameworks: { status: 'negative', text: 'DIY' },
    agentKernel: { status: 'positive', text: 'Built-in' },
  },
  {
    feature: 'Sessions, memory, observability?',
    cloud: { status: 'positive', text: 'Proprietary' },
    frameworks: { status: 'negative', text: 'DIY' },
    agentKernel: { status: 'positive', text: 'Built-in and Pluggable' },
  },
  {
    feature: 'Open-source / no licensing?',
    cloud: { status: 'negative' },
    frameworks: { status: 'positive' },
    agentKernel: { status: 'positive', text: 'Apache 2.0' },
  },
  {
    feature: 'Knowledge bases?',
    cloud: { status: 'positive', text: 'Proprietary' },
    frameworks: { status: 'negative', text: 'DIY' },
    agentKernel: { status: 'positive', text: 'Built-in and Pluggable' },
  },
  {
    feature: 'Lift-and-shift an existing agent?',
    cloud: { status: 'negative', text: 'Rewrite' },
    frameworks: { status: 'negative', text: 'Rewrite' },
    agentKernel: { status: 'positive', text: 'Wrap & ship' },
  },
];

function AkCompareCellContent({ cell }: { cell: AkCompareCell }) {
  if (cell.status === 'partial') {
    return <span className={styles.akComparePartial}>{cell.text}</span>;
  }

  const Icon = cell.status === 'positive' ? MdCheck : MdClose;
  const iconClass =
    cell.status === 'positive' ? styles.akCompareIconPos : styles.akCompareIconNeg;

  return (
    <span className={styles.akCompareCellValue}>
      <Icon className={iconClass} aria-hidden />
      {cell.text ? <span>{cell.text}</span> : null}
    </span>
  );
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
      description: 'You run or work in a business / enterprise and want to incorporate AI agentsassistants that actually work into your business workflows without needing to understand the tech.',
    },
    {
      id: '02',
      title: 'Developer',
      image: '/img/developer.png',
      description: 'You buildwrite software but haven\'t built AI agents yet. You want to ship something robust and real without learning a new stack from scratch.',
    },
    {
      id: '03',
      title: 'AI Engineer',
      image: '/img/ai.png',
      description: 'You already work with LLMs and agentic frameworks. You need a production-grade AI agent execution framework runtime that doesn\'t get in your way.',
    },
  ];

  const handleLevelSelect = (levelId: string) => {
    setSelectedLevel(levelId);
    setIsPinned(false);

    if (scrollTriggerRef.current) {
      scrollTriggerRef.current.kill();
    }

    ScrollTrigger.getAll().forEach(trigger => trigger.kill());
    gsap.set(sectionRef.current, { height: 'auto', clearProps: 'height' });
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

      const isDesktop = window.innerWidth > 996;

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

      if (isDesktop) {
        gsap.set(sectionRef.current, { height: '100vh' });
        ScrollTrigger.refresh();

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

  useEffect(() => {
    if (selectedLevel) {
      gsap.registerPlugin(ScrollTrigger);

      // Animate contentStep elements - Smooth fade and slide
      const steps = contentRef.current?.querySelectorAll(`.${styles.contentStep}`) || [];
      steps.forEach((step) => {
        gsap.fromTo(
          step,
          { opacity: 0, y: 30 },
          {
            opacity: 1,
            y: 0,
            duration: 1,
            ease: 'power2.out',
            scrollTrigger: {
              trigger: step,
              start: 'top 85%',
              toggleActions: 'play none none none',
            },
          }
        );
      });

      // Animate contentCard elements - Subtle scale and fade
      const cards = contentRef.current?.querySelectorAll(`.${styles.contentCard}`) || [];
      cards.forEach((card, idx) => {
        gsap.fromTo(
          card,
          { opacity: 0, y: 25, scale: 0.95 },
          {
            opacity: 1,
            y: 0,
            scale: 1,
            duration: 0.9,
            ease: 'power2.out',
            delay: idx * 0.08,
            scrollTrigger: {
              trigger: card,
              start: 'top 88%',
              toggleActions: 'play none none none',
            },
          }
        );
      });

      // Animate architecture layers - Slide from left
      const layers = contentRef.current?.querySelectorAll(`.${styles.architectureLayerGroup}`) || [];
      layers.forEach((layer, index) => {
        gsap.fromTo(
          layer,
          { opacity: 0, x: -50 },
          {
            opacity: 1,
            x: 0,
            duration: 0.9,
            delay: index * 0.12,
            ease: 'power2.out',
            scrollTrigger: {
              trigger: layer,
              start: 'top 85%',
              toggleActions: 'play none none none',
            },
          }
        );
      });

      // Animate capability/feature cards - Staggered fade and scale
      const capCards = contentRef.current?.querySelectorAll(
        `.${styles.capabilityCard}, .${styles.devFeatureCard}, .${styles.blValueCard}`
      ) || [];
      capCards.forEach((card, idx) => {
        gsap.fromTo(
          card,
          { opacity: 0, y: 25, scale: 0.96 },
          {
            opacity: 1,
            y: 0,
            scale: 1,
            duration: 0.95,
            ease: 'power2.out',
            delay: (idx % 3) * 0.1,
            scrollTrigger: {
              trigger: card,
              start: 'top 88%',
              toggleActions: 'play none none none',
            },
          }
        );
      });

      // Animate highlight cards - Smooth entrance with subtle scale
      const highlightCards = contentRef.current?.querySelectorAll(
        `.${styles.blHighlightCard}`
      ) || [];
      highlightCards.forEach((card) => {
        gsap.fromTo(
          card,
          { opacity: 0, y: 30, scale: 0.97 },
          {
            opacity: 1,
            y: 0,
            scale: 1,
            duration: 1.05,
            ease: 'power2.out',
            scrollTrigger: {
              trigger: card,
              start: 'top 82%',
              toggleActions: 'play none none none',
            },
          }
        );
      });

      // Animate developer analogy section
      const devAnalogy = contentRef.current?.querySelector(`.${styles.developerAnalogy}`);
      if (devAnalogy) {
        gsap.fromTo(
          devAnalogy,
          { opacity: 0, y: 35 },
          {
            opacity: 1,
            y: 0,
            duration: 1.1,
            ease: 'power2.out',
            scrollTrigger: {
              trigger: devAnalogy,
              start: 'top 75%',
              toggleActions: 'play none none none',
            },
          }
        );
      }

      // Animate Architecture Wrapper
      const archWrappers = contentRef.current?.querySelectorAll(`.${styles.devArchitectureWrapper}`) || [];
      archWrappers.forEach((wrapper) => {
        gsap.fromTo(
          wrapper,
          { opacity: 0, y: 40, scale: 0.95 },
          {
            opacity: 1,
            y: 0,
            scale: 1,
            duration: 1.1,
            ease: 'power2.out',
            scrollTrigger: {
              trigger: wrapper,
              start: 'top 80%',
              toggleActions: 'play none none none',
            },
          }
        );
      });

      // Animate BusinessLeaderScenarios tabs
      const blTabs = contentRef.current?.querySelectorAll(`.${styles.blTab}`) || [];
      blTabs.forEach((tab, idx) => {
        gsap.fromTo(
          tab,
          { opacity: 0, y: 15 },
          {
            opacity: 1,
            y: 0,
            duration: 0.7,
            ease: 'power2.out',
            delay: idx * 0.06,
            scrollTrigger: {
              trigger: tab,
              start: 'top 88%',
              toggleActions: 'play none none none',
            },
          }
        );
      });

      // Animate scenario content
      const scenarioContent = contentRef.current?.querySelector(`.${styles.blScenarioContent}`);
      if (scenarioContent) {
        gsap.fromTo(
          scenarioContent,
          { opacity: 0, y: 30, scale: 0.97 },
          {
            opacity: 1,
            y: 0,
            scale: 1,
            duration: 0.95,
            ease: 'power2.out',
            scrollTrigger: {
              trigger: scenarioContent,
              start: 'top 85%',
              toggleActions: 'play none none none',
            },
          }
        );
      }

      // Animate scenario columns
      const scenarioCols = contentRef.current?.querySelectorAll(`.${styles.blScenarioCol}`) || [];
      scenarioCols.forEach((col, idx) => {
        gsap.fromTo(
          col,
          { opacity: 0, y: 25, scale: 0.95 },
          {
            opacity: 1,
            y: 0,
            scale: 1,
            duration: 0.85,
            ease: 'power2.out',
            delay: idx * 0.1,
            scrollTrigger: {
              trigger: col,
              start: 'top 88%',
              toggleActions: 'play none none none',
            },
          }
        );
      });

      // Animate AI Engineer comparison section
      const akStandOutSection = contentRef.current?.querySelector(`.${styles.akStandOutSection}`);
      if (akStandOutSection) {
        const standOutLabel = akStandOutSection.querySelector(`.${styles.devStepLabel}`);
        const standOutTitle = akStandOutSection.querySelector(`.${styles.devTitle}`);
        const comparePanel = akStandOutSection.querySelector(`.${styles.akComparePanel}`);
        const compareFooter = akStandOutSection.querySelector(`.${styles.akCompareFooter}`);
        const compareTableHead = akStandOutSection.querySelector(`.${styles.akCompareTable} thead tr`);
        const compareRows = akStandOutSection.querySelectorAll(`.${styles.akCompareTable} tbody tr`);
        const compareMobileCards = akStandOutSection.querySelectorAll(`.${styles.akCompareMobileCard}`);
        const isCompareMobile = window.matchMedia('(max-width: 640px)').matches;

        if (standOutLabel && standOutTitle) {
          gsap.fromTo(
            [standOutLabel, standOutTitle],
            { opacity: 0, y: 30 },
            {
              opacity: 1,
              y: 0,
              duration: 1,
              ease: 'power2.out',
              stagger: 0.1,
              scrollTrigger: {
                trigger: akStandOutSection,
                start: 'top 82%',
                toggleActions: 'play none none none',
              },
            }
          );
        }

        if (comparePanel) {
          gsap.fromTo(
            comparePanel,
            { opacity: 0, scale: 0.98 },
            {
              opacity: 1,
              scale: 1,
              duration: 1.1,
              ease: 'power2.out',
              scrollTrigger: {
                trigger: comparePanel,
                start: 'top 85%',
                toggleActions: 'play none none none',
              },
            }
          );
        }

        if (!isCompareMobile && comparePanel && compareRows.length > 0) {
          const tableRevealTargets = compareTableHead
            ? [compareTableHead, ...compareRows]
            : [...compareRows];
          gsap.set(tableRevealTargets, { opacity: 0 });

          const compareTl = gsap.timeline({
            scrollTrigger: {
              trigger: comparePanel,
              start: 'top 80%',
              toggleActions: 'play none none none',
            },
          });

          if (compareTableHead) {
            compareTl.to(compareTableHead, {
              opacity: 1,
              duration: 0.6,
              ease: 'power2.out',
            });
          }

          compareTl.to(
            compareRows,
            {
              opacity: 1,
              duration: 0.55,
              ease: 'power2.out',
              stagger: 0.06,
            },
            compareTableHead ? '-=0.2' : 0
          );
        }

        if (isCompareMobile) {
          compareMobileCards.forEach((card, idx) => {
            gsap.fromTo(
              card,
              { opacity: 0, y: 25, scale: 0.96 },
              {
                opacity: 1,
                y: 0,
                scale: 1,
                duration: 0.85,
                ease: 'power2.out',
                delay: idx * 0.08,
                scrollTrigger: {
                  trigger: card,
                  start: 'top 88%',
                  toggleActions: 'play none none none',
                },
              }
            );
          });
        }

        if (compareFooter) {
          gsap.fromTo(
            compareFooter,
            { opacity: 0, y: 20 },
            {
              opacity: 1,
              y: 0,
              duration: 0.9,
              ease: 'power2.out',
              scrollTrigger: {
                trigger: compareFooter,
                start: 'top 90%',
                toggleActions: 'play none none none',
              },
            }
          );
        }
      }

      // Animate AI Engineer build flow section
      const aiBuildSection = contentRef.current?.querySelector(`.${styles.aiEngineerBuildSection}`);
      if (aiBuildSection) {
        const buildLabel = aiBuildSection.querySelector(`.${styles.devStepLabel}`);
        const buildTitle = aiBuildSection.querySelector(`.${styles.devTitle}`);
        if (buildLabel && buildTitle) {
          gsap.fromTo(
            [buildLabel, buildTitle],
            { opacity: 0, y: 30 },
            {
              opacity: 1,
              y: 0,
              duration: 1,
              ease: 'power2.out',
              stagger: 0.1,
              scrollTrigger: {
                trigger: aiBuildSection,
                start: 'top 82%',
                toggleActions: 'play none none none',
              },
            }
          );
        }

        const buildSubsections = aiBuildSection.querySelectorAll(`.${styles.aiBuildSubsection}`);
        buildSubsections.forEach((subsection) => {
          // Animate title/body only — opacity/transform on the subsection breaks
          // backdrop-filter on the diagram panel inside it.
          const buildCopy = subsection.querySelectorAll(
            `.${styles.aiBuildSubTitle}, .${styles.aiBuildSubBody}`
          );
          if (buildCopy.length > 0) {
            gsap.fromTo(
              buildCopy,
              { opacity: 0, y: 28 },
              {
                opacity: 1,
                y: 0,
                duration: 0.95,
                ease: 'power2.out',
                stagger: 0.08,
                scrollTrigger: {
                  trigger: subsection,
                  start: 'top 85%',
                  toggleActions: 'play none none none',
                },
                clearProps: 'transform',
              }
            );
          }
        });
      }

      // Animate developer framework section
      const devFrameworkSection = contentRef.current?.querySelector(`.${styles.devFrameworkSection}`);
      if (devFrameworkSection) {
        gsap.fromTo(
          devFrameworkSection,
          { opacity: 0, y: 40 },
          {
            opacity: 1,
            y: 0,
            duration: 1.1,
            ease: 'power2.out',
            scrollTrigger: {
              trigger: devFrameworkSection,
              start: 'top 80%',
              toggleActions: 'play none none none',
            },
          }
        );
      }

      // Animate framework buttons
      const frameworkButtons = contentRef.current?.querySelectorAll(`.${styles.devFrameworkButton}`) || [];
      frameworkButtons.forEach((btn, idx) => {
        gsap.fromTo(
          btn,
          { opacity: 0, y: 15, scale: 0.95 },
          {
            opacity: 1,
            y: 0,
            scale: 1,
            duration: 0.7,
            ease: 'power2.out',
            delay: idx * 0.08,
            scrollTrigger: {
              trigger: btn,
              start: 'top 85%',
              toggleActions: 'play none none none',
            },
          }
        );
      });

      // Animate code blocks
      const codeBlocks = contentRef.current?.querySelectorAll(`.${styles.devFrameworkCodeBlock}`) || [];
      codeBlocks.forEach((block, idx) => {
        gsap.fromTo(
          block,
          { opacity: 0, x: 30, scale: 0.98 },
          {
            opacity: 1,
            x: 0,
            scale: 1,
            duration: 0.95,
            ease: 'power2.out',
            delay: idx * 0.12,
            scrollTrigger: {
              trigger: block,
              start: 'top 83%',
              toggleActions: 'play none none none',
            },
          }
        );
      });

      // Add professional hover animations to cards
      const allAnimatedCards = contentRef.current?.querySelectorAll(
        `.${styles.contentCard}, .${styles.capabilityCard}, .${styles.devFeatureCard}, .${styles.blValueCard}`
      ) || [];
      allAnimatedCards.forEach((card: any) => {
        card.addEventListener('mouseenter', () => {
          gsap.to(card, {
            y: -6,
            scale: 1.02,
            boxShadow: '0 16px 32px rgba(0,0,0,0.12)',
            duration: 0.25,
            ease: 'power2.out',
          });
        });
        card.addEventListener('mouseleave', () => {
          gsap.to(card, {
            y: 0,
            scale: 1,
            boxShadow: '0 4px 12px rgba(0,0,0,0.05)',
            duration: 0.25,
            ease: 'power2.out',
          });
        });
      });

      // Add hover animations to framework buttons
      frameworkButtons.forEach((btn: any) => {
        btn.addEventListener('mouseenter', () => {
          gsap.to(btn, {
            scale: 1.05,
            duration: 0.15,
            ease: 'power2.out',
          });
        });
        btn.addEventListener('mouseleave', () => {
          gsap.to(btn, {
            scale: 1,
            duration: 0.15,
            ease: 'power2.out',
          });
        });
      });

      return () => {
        ScrollTrigger.getAll().forEach(trigger => trigger.kill());
      };
    }
  }, [selectedLevel, styles]);

  return (
    <section
      ref={sectionRef}
      className={`${styles.levelsSection} ${!selectedLevel ? styles.levelsPinned : ''}`}
    >
      <div className="container">
        <div className={styles.levelsContainer}>
          <p ref={subtitleRef} className={styles.levelsSubtitle}>
            Which path describes you the best
          </p>

          <h2 ref={titleRef} className={styles.levelsTitle}>
            Agent Kernel is designed to adapt to your level of expertise
          </h2>

          <div ref={cardsRef} className={styles.levelsGrid}>
            {levels.map((level) => (
              <div
                key={level.id}
                data-level={level.id}
                onClick={() => handleLevelSelect(level.id)}
                className={`${styles.levelCard} ${selectedLevel === level.id ? styles.levelCardSelected : ''}`}
              >
                <div className={styles.levelImage}>
                  <img src={level.image} alt={level.title} />
                </div>

                <h3 className={styles.levelCardTitle}>{level.title}</h3>
                <p className={styles.levelCardDescription}>{level.description}</p>
              </div>
            ))}
          </div>

          <div className={styles.levelsHint}>
            Select a path that best describes you to continue
          </div>

          {/* ── BUSINESS LEADER CONTENT ── */}
          {selectedLevel === '01' && (
            <div ref={contentRef} className={styles.levelContent}>
          
              {/* ── STEP 01 ── */}
              <div className={styles.blStepBlock}>
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
                    <li>Cross-team hand-offs are slow and error-prone</li>
                  </ul>
                </div>
                <div className={styles.contentCard}>
                  <h3 className={styles.contentCardLabel}>Building Something New</h3>
                  <p className={styles.contentCardTitle}>Do you have a product idea?</p>
                  <ul className={styles.bulletList}>
                    <li>You see an opportunity for an AI-powered service in your industry</li>
                    <li>You're not sure which AI technology to commit to</li>
                    <li>Building from scratch feels like months before anything reaches users</li>
                    <li>You want to build a prototype / proof-of-concept quickly without having to invest too much on it</li>
                  </ul>
                </div>
                </div>
              </div>

              {/* ── STEP 02 ── */}
              <div style={{ marginTop: '2rem' }}>
                <p className={styles.stepLabel}>Step 02 / Meet the solution</p>
                <h2 className={styles.contentTitle}>
                  An AI agent doesn't just answer, it gets things done.
                </h2>
          
                <AgentExecutionFlowDiagram />
              </div>
          
              {/* ── STEP 03 ── */}
              <div style={{ marginTop: '2rem' }}>
                <p className={styles.stepLabel}>Step 03 / Agent Kernel</p>
                <h2 className={styles.contentTitle}>
                  Agent Kernel is the engine that powers it at scale to run compliant AI agents
                </h2>
          
                {/* OS analogy highlight card */}
                <div className={styles.blHighlightCard}>
                  <p className={styles.blHighlightEyebrow}>For Your Business</p>
                  <h3 className={styles.blHighlightTitle}>
                    Agent Kernel is like the Operating System for AI agents.
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
                       No one must build agent infrastructure from scratch. Go from idea to enterprise-grade working scalable AI agents in  days.
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
                      Deploy on AWS, GCP, Azure, or your own on-prem Docker. No vendor lock-in. You stay in control of your data and infrastructure.
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

              {/* ── STEP 05 — Architecture Overview ── */}
              <div style={{ marginTop: '3rem' }}>
                <p className={styles.stepLabel}>Step 05 / How it works</p>
                <h2 className={styles.contentTitle}>
                  Agent Kernel is the engine that powers it all
                </h2>
                <p className={styles.contentBody}>
                  You write your AI agent's logic. Agent Kernel handles everything else: the infrastructure, the cloud deployment, memory, knowledge bases, hooks, observability & traceability, LLM cost tracking, the integrations so your agent is live and talking to real users in days.
                </p>

                <div className={styles.devArchitectureWrapper}>
                  <AgentKernelArchDiagram />
                </div>
              </div>

            </div>
          )}

          {/* ── DEVELOPER CONTENT ── */}
          {selectedLevel === '02' && (
            <div ref={contentRef} className={styles.developerContent}>

              {/* Step 01 — Developer Analogy */}
              <div className={`${styles.developerAnalogy} ${styles.developerBlock}`}>
                <p className={styles.devStepLabel}>Developer Analogy</p>
                <h2 className={styles.devTitle}>
                  Building blocks and and deployment infrastructure for your AI Agent.
                </h2>
                <div className={styles.devDescription}>
                  <p className={styles.devIntro}>
                    Agent Kernel is like the operating system for the AI assistants, think Linux for your agents.
                  </p>
                  <div className={styles.devBulletList}>
                    <div className={styles.devBulletItem}>
                      <span className={styles.devBullet}>•</span>
                      <span className={styles.devBulletText}>Install it on your laptop, sever, or cloud and run AI agents hassle-free.</span>
                    </div>
                    <div className={styles.devBulletItem}>
                      <span className={styles.devBullet}>•</span>
                      <span className={styles.devBulletText}>No need to build infrastructure, APIs, or messaging and other integrations.</span>
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
                      <span className={styles.devBulletText}>Just define what your agent should do.</span>
                    </div>
                  </div>
                </div>
              </div>

              {/* Architecture flow — 4 stacked layers */}
              <div className={`${styles.architectureWrapper} ${styles.developerBlock}`}>
                <div className={styles.architectureStack}>
                  {[
                    {
                      num: '01',
                      label: 'Your Agent Logic',
                      items: ['Instructions', 'Tools', 'Framework SDK'],
                    },
                    {
                      num: '02',
                      label: 'Agent Kernel Runtime',
                      items: ['Agents', 'Agent Runner', 'Session Management', 'Hooks'],
                    },
                    {
                      num: '03',
                      label: 'Storage & Memory',
                      items: ['In-Memory', 'Redis', 'DynamoDB', 'CosmosDB', 'Firestore'],
                    },
                    {
                      num: '04',
                      label: 'Knowledge Bases',
                      items: ['ChromaDB', 'Neo4j', 'Starburst', 'SQLDB'],
                    },
                    {
                      num: '05',
                      label: 'Observability',
                      items: ['LangFuse', 'OpenLLMetry'],
                    },
                    {
                      num: '06',
                      label: 'Cloud Infrastructure',
                      items: [
                        'AWS Lambda',
                        'ECS',
                        'Azure Functions',
                        'Container Apps',
                        'GCP Cloud Run',
                        'GCP Cloud Run Functions',
                      ],
                    },
                    {
                      num: '07',
                      label: 'Interfacing',
                      items: ['CLI', 'MCP', 'A2A', 'REST API'],
                    },
                    {
                      num: '08',
                      label: 'Channels',
                      items: ['Slack', 'Teams', 'WhatsApp', 'Telegram', 'Messenger', 'Instagram', 'Gmail'],
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
                          <p className={styles.layerSub}>
                            {layer.items.map((item, idx) => (
                              <React.Fragment key={item}>
                                {idx > 0 && (
                                  <span className={styles.layerSubSep} aria-hidden="true">
                                    ●
                                  </span>
                                )}
                                {item}
                              </React.Fragment>
                            ))}
                          </p>
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

                <div className={styles.devFeatureGroups}>
                  {DEV_FEATURE_GROUPS.map((group) => (
                    <div key={group.title} className={styles.devFeatureGroup}>
                      <h3 className={styles.devFeatureGroupTitle}>{group.title}</h3>
                      <div
                        className={`${styles.devFeaturesGrid} ${
                          group.cols === 4 ? styles.devFeaturesGrid4 : styles.devFeaturesGrid3
                        }`}
                      >
                        {group.features.map((feature) => {
                          const IconComponent = feature.icon;
                          return (
                            <div key={feature.title} className={styles.devFeatureCard}>
                              <div className={styles.devFeatureCardHeader}>
                                <div className={styles.devFeatureIconWrap}>
                                  <IconComponent className={styles.devFeatureIcon} aria-hidden />
                                </div>
                                <h4 className={styles.devFeatureCardTitle}>{feature.title}</h4>
                              </div>
                              <p className={styles.devFeatureCardBody}>{feature.body}</p>
                            </div>
                          );
                        })}
                      </div>
                    </div>
                  ))}
                </div>
              </div>


              {/* Step 03 — Framework Selection */}
              <div className={`${styles.devFrameworkSection} ${styles.developerBlock}`}>
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

              {/* Step 04 — How Agent Kernel Fits In */}
              <div className={styles.devArchitectureSection}>
                <p className={styles.devStepLabel}>The complete picture</p>
                <h2 className={styles.devTitle}>How Agent Kernel Fits In</h2>

                <p className={styles.devFrameworkBody}>
                    You write your AI agent’s logic. Agent Kernel handles everything else: the infrastructure, the cloud deployment, memory, knowledge bases, hooks, observability & traceability, LLM cost tracking, the integrations so your agent is live and talking to real users in days.
                </p>

                <div className={styles.devArchitectureWrapper}>
                  <AgentKernelArchDiagram />
                </div>
              </div>
            </div>
          )}
          {selectedLevel === '03' && (
            <div ref={contentRef} className={styles.developerContent}>

              {/* Step 01 — AI Engineer Analogy */}
              <div className={`${styles.developerAnalogy} ${styles.developerBlock}`}>
                <p className={styles.devStepLabel}>AI Engineer Analogy</p>
                <h2 className={styles.devTitle}>
                  Bring your already existing agentic AI code onto a unified Operating System and Deployment Infrastructure for your AI Agents while making it enterprise ready and compliant.
                </h2>
                <div className={styles.devDescription}>
                  <p className={styles.devIntro}>
                    Agent Kernel is a unified, capable runtime for AI agents. Its pluggable architecture lets you attach capabilities to your agents effortlessly. A comprehensive list of pre-built connectors smooths the agent-building process—enabling a capability is a matter of setting configuration. All out of the box.
                  </p>
                  <p className={styles.devIntro}>
                    Agent Kernel takes care of how agents run, scale from single execution to thousands of agent invocations in parallel, and interact with the real world.
                  </p>
                </div>
              </div>

              {/* Architecture flow — 9 stacked layers */}
              <div className={`${styles.architectureWrapper} ${styles.developerBlock}`}>
                <div className={styles.architectureStack}>
                  {AI_ENGINEER_ARCH_LAYERS.map((layer, i, arr) => (
                    <div key={layer.label} className={styles.architectureLayerGroup}>
                      <div className={styles.layerNumberWrapper}>
                        <div className={styles.layerNumberCircle}>
                          {layer.num}
                        </div>
                        {i < arr.length - 1 && (
                          <div className={styles.layerConnector} />
                        )}
                      </div>
                      <div className={styles.layerContentWrapper}>
                        <div className={styles.layerContentBox}>
                          <h3 className={styles.layerLabel}>{layer.label}</h3>
                          <p className={styles.layerSub}>
                            {layer.items.map((item, idx) => (
                              <React.Fragment key={item}>
                                {idx > 0 && (
                                  <span className={styles.layerSubSep} aria-hidden="true">
                                    ●
                                  </span>
                                )}
                                {item}
                              </React.Fragment>
                            ))}
                          </p>
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              </div>

              {/* Step 02 — What Makes Agent Kernel Stand Out */}
              <div className={`${styles.akStandOutSection} ${styles.developerBlock}`}>
                <p className={styles.devStepLabel}>Compare alternatives</p>
                <h2 className={styles.devTitle}>What Makes Agent Kernel Stand Out</h2>

                <div className={styles.akComparePanel}>
                  <p className={styles.akCompareScrollHint} aria-hidden="true">
                    Scroll horizontally to compare all columns
                  </p>

                  <div className={styles.akCompareTableWrap}>
                    <table className={styles.akCompareTable}>
                      <colgroup>
                        <col className={styles.akCompareColFeature} />
                        <col className={styles.akCompareColData} />
                        <col className={styles.akCompareColData} />
                        <col className={styles.akCompareColData} />
                      </colgroup>
                      <thead>
                        <tr>
                          <th scope="col" className={styles.akCompareFeatureCol} />
                          <th
                            scope="col"
                            className={`${styles.akCompareHeadCell} ${styles.akCompareDataCol}`}
                          >
                            <span className={styles.akCompareHeadLong}>
                              {AI_ENGINEER_COMPARE_COLUMNS.cloud}
                            </span>
                            <span className={styles.akCompareHeadShort}>
                              {AI_ENGINEER_COMPARE_COLUMNS.cloudShort}
                            </span>
                          </th>
                          <th
                            scope="col"
                            className={`${styles.akCompareHeadCell} ${styles.akCompareDataCol}`}
                          >
                            <span className={styles.akCompareHeadLong}>
                              {AI_ENGINEER_COMPARE_COLUMNS.frameworks}
                            </span>
                            <span className={styles.akCompareHeadShort}>
                              {AI_ENGINEER_COMPARE_COLUMNS.frameworksShort}
                            </span>
                          </th>
                          <th
                            scope="col"
                            className={`${styles.akCompareHeadCell} ${styles.akCompareDataCol} ${styles.akCompareHeadCellHighlight}`}
                          >
                            {AI_ENGINEER_COMPARE_COLUMNS.agentKernel}
                          </th>
                        </tr>
                      </thead>
                      <tbody>
                        {AI_ENGINEER_COMPARISON_ROWS.map((row, i) => (
                          <tr
                            key={row.feature}
                            className={i % 2 === 1 ? styles.akCompareRowAlt : undefined}
                          >
                            <th scope="row" className={styles.akCompareFeatureCell}>
                              <span className={styles.akCompareFeatureText}>{row.feature}</span>
                              {row.featureHint ? (
                                <span className={styles.akCompareFeatureHint}>{row.featureHint}</span>
                              ) : null}
                            </th>
                            <td className={`${styles.akCompareDataCell} ${styles.akCompareDataCol}`}>
                              <AkCompareCellContent cell={row.cloud} />
                            </td>
                            <td className={`${styles.akCompareDataCell} ${styles.akCompareDataCol}`}>
                              <AkCompareCellContent cell={row.frameworks} />
                            </td>
                            <td
                              className={`${styles.akCompareDataCell} ${styles.akCompareDataCol} ${styles.akCompareDataCellHighlight}`}
                            >
                              <AkCompareCellContent cell={row.agentKernel} />
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>

                  <div className={styles.akCompareMobileList}>
                    {AI_ENGINEER_COMPARISON_ROWS.map((row) => (
                      <article key={row.feature} className={styles.akCompareMobileCard}>
                        <h3 className={styles.akCompareMobileFeature}>
                          {row.feature}
                          {row.featureHint ? (
                            <span className={styles.akCompareFeatureHint}>{row.featureHint}</span>
                          ) : null}
                        </h3>
                        <div className={styles.akCompareMobileRows}>
                          <div className={styles.akCompareMobileRow}>
                            <span className={styles.akCompareMobileLabel}>
                              {AI_ENGINEER_COMPARE_COLUMNS.cloudShort}
                            </span>
                            <AkCompareCellContent cell={row.cloud} />
                          </div>
                          <div className={styles.akCompareMobileRow}>
                            <span className={styles.akCompareMobileLabel}>
                              {AI_ENGINEER_COMPARE_COLUMNS.frameworksShort}
                            </span>
                            <AkCompareCellContent cell={row.frameworks} />
                          </div>
                          <div
                            className={`${styles.akCompareMobileRow} ${styles.akCompareMobileRowHighlight}`}
                          >
                            <span className={styles.akCompareMobileLabel}>
                              {AI_ENGINEER_COMPARE_COLUMNS.agentKernel}
                            </span>
                            <AkCompareCellContent cell={row.agentKernel} />
                          </div>
                        </div>
                      </article>
                    ))}
                  </div>

                  <p className={styles.akCompareFooter}>
                    Bedrock / Foundry give you <strong>runtime</strong> but take your{' '}
                    <strong>freedom</strong>. LangGraph gives you <strong>freedom</strong> but no{' '}
                    <strong>runtime</strong>. Agent Kernel gives you <strong>both</strong>.
                  </p>
                </div>
              </div>

              {/* Step 03 — Available Features */}
              <div className={styles.devFeatureSection}>
                <p className={styles.devFeatureLabel}>All Enterprise Features Available Free And Open-Source</p>
                <h2 className={styles.devFeatureTitle}>
                  Focus on Agent Logic. We Handle the Rest.
                </h2>

                <div className={styles.devFeatureGroups}>
                  {DEV_FEATURE_GROUPS.map((group) => (
                    <div key={group.title} className={styles.devFeatureGroup}>
                      <h3 className={styles.devFeatureGroupTitle}>{group.title}</h3>
                      <div
                        className={`${styles.devFeaturesGrid} ${
                          group.cols === 4 ? styles.devFeaturesGrid4 : styles.devFeaturesGrid3
                        }`}
                      >
                        {group.features.map((feature) => {
                          const IconComponent = feature.icon;
                          return (
                            <div key={feature.title} className={styles.devFeatureCard}>
                              <div className={styles.devFeatureCardHeader}>
                                <div className={styles.devFeatureIconWrap}>
                                  <IconComponent className={styles.devFeatureIcon} aria-hidden />
                                </div>
                                <h4 className={styles.devFeatureCardTitle}>{feature.title}</h4>
                              </div>
                              <p className={styles.devFeatureCardBody}>{feature.body}</p>
                            </div>
                          );
                        })}
                      </div>
                    </div>
                  ))}
                </div>
              </div>

              {/* Step 04 — Framework Selection */}
              <div className={`${styles.devFrameworkSection} ${styles.developerBlock}`}>
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

              {/* Step 05 — Production-ready compliant agents */}
              <div className={`${styles.aiEngineerBuildSection} ${styles.developerBlock}`}>
                <p className={styles.devStepLabel}>Build with confidence</p>
                <h2 className={styles.devTitle}>
                  How Agent Kernel Helps You Build Production-Ready Compliant AI Agents
                </h2>

                <article className={styles.aiBuildSubsection}>
                  <h3 className={styles.aiBuildSubTitle}>Building AI Agents</h3>
                  <p className={styles.aiBuildSubBody}>
                    Designing a compliant multi-agent architecture carries multiple components.
                  </p>
                  <BuildingAgentsFlowDiagram />
                </article>

                <article className={styles.aiBuildSubsection}>
                  <h3 className={styles.aiBuildSubTitle}>Running AI Agents</h3>
                  <p className={styles.aiBuildSubBody}>
                    Running a production-grade AI agent requires considering several design aspects and information flows.
                  </p>
                  <RunningAgentsFlowDiagram />
                </article>

                <article className={styles.aiBuildSubsection}>
                  <h3 className={styles.aiBuildSubTitle}>How Agent Kernel Sit In</h3>
                  <p className={styles.aiBuildSubBody}>
                    Agent Kernel handles everything except the actual agent logic (number of agents, their capabilities and their prompts) while providing a deterministic test framework as well.
                  </p>
                  <AgentKernelSitsInFlowDiagram />
                </article>
              </div>

              {/* Step 06 — How Agent Kernel Fits In */}
              <div className={`${styles.devArchitectureSection} ${styles.developerBlock}`}>
                <p className={styles.devStepLabel}>The complete picture</p>
                <h2 className={styles.devTitle}>How Agent Kernel Fits In</h2>

                <p className={styles.devFrameworkBody}>
                  You write your AI agent’s logic. Agent Kernel handles everything else: the infrastructure, the cloud deployment, memory, knowledge bases, hooks, observability & traceability, LLM cost tracking, the integrations so your agent is live and talking to real users in days.
                </p>

                <div className={styles.devArchitectureWrapper}>
                  <AgentKernelArchDiagram />
                </div>
              </div>

              {/* Step 07 - Why Agent Kernel is a Powerful Operating System */}
              <div className={`${styles.devFeatureSection} ${styles.developerBlock}`}>
                <p className={styles.devStepLabel}>Operating system depth</p>
                <h2 className={styles.devTitle}>
                  Why Agent Kernel is a Powerful Operating System
                </h2>

                <div className={styles.devFeatureGroups}>
                  <div className={styles.devFeatureGroup}>
                    <h3 className={styles.devFeatureGroupTitle}>Three-Layer Memory</h3>
                    <p className={styles.devFeatureGroupHeadline}>
                      Three Memory Layers, Zero Context Chaos
                    </p>
                    <p className={styles.devFeatureGroupIntro}>
                      Keep conversations coherent, enrich each request, and carry useful session data
                      forward without bloating the model context window.
                    </p>

                    <div className={`${styles.devFeaturesGrid} ${styles.devFeaturesGrid3}`}>
                      {AI_ENGINEER_MEMORY_LAYERS.map((layer) => {
                        const IconComponent = layer.icon;
                        return (
                          <div key={layer.title} className={styles.devFeatureCard}>
                            <div className={styles.devFeatureCardHeader}>
                              <div className={styles.devFeatureIconWrap}>
                                <IconComponent className={styles.devFeatureIcon} aria-hidden />
                              </div>
                              <h4 className={styles.devFeatureCardTitle}>{layer.title}</h4>
                            </div>
                            <ul className={styles.devFeatureCardBodyList}>
                              {layer.bullets.map((bullet) => (
                                <li key={bullet}>{bullet}</li>
                              ))}
                            </ul>
                          </div>
                        );
                      })}
                    </div>
                  </div>

                  <div className={styles.devFeatureGroup}>
                    <h3 className={styles.devFeatureGroupTitle}>Execution Hook Pipeline</h3>
                    <p className={styles.devFeatureGroupHeadline}>
                      Control Every Request Without Rewriting Agent Logic
                    </p>
                    <p className={styles.devFeatureGroupIntro}>
                      Use hooks before and after agent execution to enforce safety, enrich inputs,
                      and polish outputs.
                    </p>

                    <p className={styles.devHookPipelineScrollHint} aria-hidden="true">
                      Scroll horizontally to see the full pipeline
                    </p>

                    <div className={styles.devHookPipelineScroll}>
                      <div className={styles.devHookPipeline}>
                        {AI_ENGINEER_HOOK_PIPELINE.map((step, index, arr) => {
                          const IconComponent = step.icon;
                          return (
                            <React.Fragment key={step.title}>
                              <div
                                className={`${styles.devFeatureCard} ${
                                  step.highlight ? styles.devFeatureCardHighlight : ''
                                }`}
                              >
                                <div className={styles.devFeatureCardBadgeSlot}>
                                  {'badge' in step && step.badge ? (
                                    <span className={styles.devFeatureHighlightBadge}>
                                      {step.badge}
                                    </span>
                                  ) : null}
                                </div>
                                <div className={styles.devFeatureCardHeader}>
                                  <div className={styles.devFeatureIconWrap}>
                                    <IconComponent
                                      className={styles.devFeatureIcon}
                                      aria-hidden
                                    />
                                  </div>
                                  <h4 className={styles.devFeatureCardTitle}>{step.title}</h4>
                                </div>
                                <ul className={styles.devFeatureCardBodyList}>
                                  {step.bullets.map((bullet) => (
                                    <li key={bullet}>{bullet}</li>
                                  ))}
                                </ul>
                              </div>
                              {index < arr.length - 1 ? (
                                <div
                                  className={styles.devHookPipelineConnector}
                                  aria-hidden="true"
                                >
                                  <span className={styles.devHookPipelineArrowH}>→</span>
                                  <span className={styles.devHookPipelineArrowV}>↓</span>
                                </div>
                              ) : null}
                            </React.Fragment>
                          );
                        })}
                      </div>
                    </div>
                  </div>
                </div>
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
      <PlantParticlesBackground />
      <WhatsNewBanner />
      <Hero />
      <main>
        <FrameworksStrip />
        <AffiliationsStrip />
        <Levels />
        <AgentSkills />
        <Deployment />
        <Community />
      </main>
    </Layout>
  );
}
