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
  const scrollTriggerRef = useRef<ScrollTriggerInstance | null>(null);

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
  };

  useEffect(() => {
    if (selectedLevel && contentRef.current) {
      gsap.registerPlugin(ScrollToPlugin);
      gsap.to(window, {
        duration: 1,
        scrollTo: { y: contentRef.current.offsetTop - 100 },
        ease: 'power2.out',
      });
    }
  }, [selectedLevel]);

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
          pinSpacing: false,
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
            </div>
          )}

          {/* ── DEVELOPER CONTENT ── */}
          {selectedLevel === '02' && (
            <div ref={contentRef} className={styles.levelContent}>
              <div className={styles.contentStep}>
                <p className={styles.stepLabel}>Developer Analogy</p>
                <h2 className={styles.contentTitle}>
                  Like an Operating System for AI Agents
                </h2>
                <p className={styles.contentBody}>
                  Agent Kernel is like an operating system for AI assistants. Install it on your laptop, server, or cloud, and run AI agents hassle-free. No infrastructure building required.
                </p>
                <ul className={styles.bulletListLarge}>
                  <li>No need to build APIs, integrations, or session stores</li>
                  <li>Everything works out of the box</li>
                  <li>Scales from single execution to thousands of agents in parallel</li>
                  <li>Interacts with the real world automatically</li>
                  <li>Just define what your assistant should do</li>
                </ul>
              </div>

              <div className={styles.contentStep}>
                <h2 className={styles.contentTitle}>Architecture Stack</h2>
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
                  ].map((layer) => (
                    <div key={layer.label} className={styles.architectureLayer}>
                      <div className={styles.layerNumber}>{layer.num}</div>
                      <div className={styles.layerContent}>
                        <h3 className={styles.layerLabel}>{layer.label}</h3>
                        <p className={styles.layerSub}>{layer.sub}</p>
                      </div>
                    </div>
                  ))}
                </div>
              </div>

              <div className={styles.contentStep}>
                <p className={styles.stepLabel}>Enterprise Features Included</p>
                <h2 className={styles.contentTitle}>
                  Everything You Need to Ship
                </h2>

                <div className={styles.featuresGrid}>
                  {[
                    {
                      icon: MdBolt,
                      title: 'REST API Server',
                      body: 'FastAPI-based server out of the box. No boilerplate.',
                    },
                    {
                      icon: MdAutoAwesome,
                      title: 'Multi-Framework',
                      body: 'OpenAI Agents, LangGraph, CrewAI, Google ADK.',
                    },
                    {
                      icon: MdSmartToy,
                      title: 'Session & Memory',
                      body: 'Redis, DynamoDB, Cosmos DB or in-memory—your choice.',
                    },
                    {
                      icon: MdCloud,
                      title: 'Cloud Deployment',
                      body: 'Pre-built Terraform for AWS, ECS, Azure, Container Apps.',
                    },
                    {
                      icon: FaSlack,
                      title: 'Messaging Integrations',
                      body: 'Slack, WhatsApp, Telegram, Gmail—plug and play.',
                    },
                    {
                      icon: MdScience,
                      title: 'Testing Framework',
                      body: 'pytest-integrated test runner for AI agents.',
                    },
                    {
                      icon: MdLink,
                      title: 'Execution Hooks',
                      body: 'Pre/post hooks for RAG, validation, moderation.',
                    },
                    {
                      icon: MdVisibility,
                      title: 'Observability',
                      body: 'Langfuse and OpenLLMetry tracing with one config line.',
                    },
                  ].map((feature) => {
                    const IconComponent = feature.icon;
                    return (
                      <div key={feature.title} className={styles.featureCard}>
                        <IconComponent className={styles.featureIcon} />
                        <h3 className={styles.featureTitle}>{feature.title}</h3>
                        <p className={styles.featureBody}>{feature.body}</p>
                      </div>
                    );
                  })}
                </div>
              </div>
            </div>
          )}

          {/* ── AI ENGINEER CONTENT ── */}
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
