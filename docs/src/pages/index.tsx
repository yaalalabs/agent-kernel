import React from 'react';
import Link from '@docusaurus/Link';
import useDocusaurusContext from '@docusaurus/useDocusaurusContext';
import Layout from '@theme/Layout';
import styles from './index.module.css';
import {
  MdMenuBook,
  MdArticle,
  MdLink,
  MdBusiness,
  MdPower,
  MdRocket,
  MdHandshake,
  MdFlashOn,
  MdStar,
  MdChat,
  MdCode,
  MdConstruction,
  MdHealthAndSafety
} from 'react-icons/md';
import { FaGithub, FaDiscord, FaPython, FaSlack, FaWhatsapp, FaInstagram, FaTelegram } from 'react-icons/fa';
import { SiTerraform, SiGmail } from 'react-icons/si';
import { FaFacebookMessenger } from 'react-icons/fa6';

function HomepageHeader() {
  const { siteConfig } = useDocusaurusContext();
  return (
    <header className={styles.heroBanner}>
      <div className="container">
        <div className={styles.heroContent}>
          <img
            src="/img/logo.svg"
            alt="Agent Kernel Logo"
            className={styles.heroLogo}
          />
          <h1 className={styles.heroTitle}>{siteConfig.title}</h1>
          <p className={styles.heroTagline}>{siteConfig.tagline}</p>
          <div className={styles.heroButtons}>
            <Link
              className="button button--primary button--lg"
              to="/docs">
              Get Started →
            </Link>
            <Link
              className={`button button--secondary button--lg ${styles.featuresButton}`}
              to="/features">
              Explore Features
            </Link>
            <Link
              className="button button--secondary button--lg"
              to="https://github.com/yaalalabs/agent-kernel">
              View on GitHub
            </Link>
          </div>
        </div>
      </div>
    </header>
  );
}

function NavigationSection() {
  const navigationCards = [
    {
      title: 'Documentation',
      icon: <MdMenuBook />,
      description: 'Explore comprehensive guides, API references, and tutorials to get the most out of Agent Kernel.',
      link: '/docs',
      linkText: 'Browse Documentation',
      color: 'blue',
    },
    {
      title: 'Blog',
      icon: <MdArticle />,
      description: 'Stay updated with the latest news, release announcements, and technical articles from the team.',
      link: '/blog',
      linkText: 'Read Blog Posts',
      color: 'green',
    },
    {
      title: 'Links',
      icon: <MdLink />,
      description: 'Connect with our community and explore related resources across different platforms.',
      link: '#community',
      linkText: 'Explore Links',
      color: 'purple',
    },
    {
      title: 'Yaala Labs',
      icon: <MdBusiness />,
      description: 'Learn more about Yaala Labs and our expertise in building mission-critical market infrastructure.',
      link: 'https://www.yaalalabs.com/',
      linkText: 'Visit Yaala Labs',
      color: 'orange',
      external: true,
    },
  ];

  return (
    <section className={styles.navigationSection}>
      <div className="container">
        <h2 className={styles.sectionTitle}>Navigate</h2>
        <div className={styles.cardGrid}>
          {navigationCards.map((card, idx) => (
            <div key={idx} className={`${styles.card} ${styles[card.color]}`}>
              <div className={styles.cardIcon}>{card.icon}</div>
              <h3 className={styles.cardTitle}>{card.title}</h3>
              <p className={styles.cardDescription}>{card.description}</p>
              <Link
                className={styles.cardLink}
                to={card.link}
                {...(card.external ? { target: '_blank', rel: 'noopener noreferrer' } : {})}>
                {card.linkText} →
              </Link>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}

function IntegrationsSection() {
  const frameworks = [
    {
      name: 'OpenAI Agents SDK',
      logo: '/img/integrations/openai.svg',
      link: '/docs/frameworks/openai',
    },
    {
      name: 'LangGraph',
      logo: '/img/integrations/langgraph.png',
      link: '/docs/frameworks/langgraph',
    },
    {
      name: 'CrewAI',
      logo: '/img/integrations/crewai.svg',
      link: '/docs/frameworks/crewai',
    },
    {
      name: 'Google ADK',
      logo: '/img/integrations/adk.png',
      link: '/docs/frameworks/google-adk',
    },
  ];

  const traceability = [
    {
      name: 'LangFuse',
      logo: '/img/integrations/langfuse.png',
      link: '/docs/advanced/traceability',
    },
    {
      name: 'TraceLoop OpenLLMetry',
      logo: '/img/integrations/traceloop.png',
      link: '/docs/advanced/traceability',
    },
  ];

  return (
    <section className={styles.integrationsSection}>
      <div className="container">
        <div className={styles.integrationsHeader}>
          <h2 className={styles.integrationsSectionTitle}>Production Runtime for Leading Agentic Frameworks</h2>
          <p className={styles.integrationsSectionSubtitle}>
            Deploy and scale LangGraph, OpenAI Agents SDK, Google ADK and CrewAI with Agent Kernel.
            A framework-agnostic runtime with enterprise-grade features.
          </p>
        </div>

        <div className={styles.integrationsContainer}>
          <div className={styles.integrationsCategory}>
            <h3 className={styles.integrationsCategoryTitle}>Agentic Frameworks</h3>
            <div className={styles.integrationsGrid}>
              {frameworks.map((framework, idx) => (
                <Link
                  key={idx}
                  to={framework.link}
                  className={styles.integrationCard}
                  style={{ animationDelay: `${idx * 0.1}s` }}>
                  <div className={styles.integrationLogoWrapper}>
                    <img
                      src={framework.logo}
                      alt={framework.name}
                      className={styles.integrationLogo}
                    />
                  </div>
                  <h4 className={styles.integrationName}>{framework.name}</h4>
                </Link>
              ))}
            </div>
          </div>

          <div className={styles.integrationsCategory}>
            <h3 className={styles.integrationsCategoryTitle}>Traceability & Observability</h3>
            <div className={styles.integrationsGrid}>
              {traceability.map((tool, idx) => (
                <Link
                  key={idx}
                  to={tool.link}
                  className={styles.integrationCard}
                  style={{ animationDelay: `${(frameworks.length + idx) * 0.1}s` }}>
                  <div className={styles.integrationLogoWrapper}>
                    <img
                      src={tool.logo}
                      alt={tool.name}
                      className={styles.integrationLogo}
                    />
                  </div>
                  <h4 className={styles.integrationName}>{tool.name}</h4>
                </Link>
              ))}
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}

function MessagingIntegrationsSection() {
  const activeIntegrations = [
    {
      name: 'Slack',
      icon: <FaSlack />,
      description: 'Build AI agents for Slack workspaces',
      status: 'active',
      color: '#4A154B',
      link: '/docs/integrations/slack',
    },
    {
      name: 'WhatsApp',
      icon: <FaWhatsapp />,
      description: 'Deploy agents on WhatsApp Business',
      status: 'active',
      color: '#25D366',
      link: '/docs/integrations/whatsapp',
    },
    {
      name: 'Messenger',
      icon: <FaFacebookMessenger />,
      description: 'Integrate with Facebook Messenger',
      status: 'active',
      color: '#0084FF',
      link: '/docs/integrations/messenger',
    },
  ];

  const comingSoonIntegrations = [
    {
      name: 'Instagram',
      icon: <FaInstagram />,
      description: 'Instagram messaging integration',
      status: 'coming-soon',
      color: '#E4405F',
    },
    {
      name: 'Gmail',
      icon: <SiGmail />,
      description: 'Email conversation handling with Gmail',
      status: 'coming-soon',
      color: '#EA4335',
    },
    {
      name: 'Telegram',
      icon: <FaTelegram />,
      description: 'Build Telegram bots with agents',
      status: 'coming-soon',
      color: '#0088CC',
    },
  ];

  return (
    <section className={styles.messagingIntegrationsSection}>
      <div className="container">
        <div className={styles.integrationsHeader}>
          <h2 className={styles.integrationsSectionTitle}>Messaging Platform Integrations</h2>
          <p className={styles.integrationsSectionSubtitle}>
            Connect your AI agents to popular messaging platforms and reach your users where they are
          </p>
        </div>

        <div className={styles.messagingIntegrationsContainer}>
          <div className={styles.messagingIntegrationsGrid}>
            {/* First set of cards */}
            {activeIntegrations.map((platform, idx) => (
              <Link
                key={`active-1-${idx}`}
                to={platform.link}
                className={styles.messagingIntegrationCard}>
                <div
                  className={styles.messagingIntegrationIcon}
                  style={{ color: platform.color }}>
                  {platform.icon}
                </div>
                <h4 className={styles.messagingIntegrationName}>{platform.name}</h4>
                <p className={styles.messagingIntegrationDescription}>{platform.description}</p>
                <span className={styles.integrationStatusBadge}>Available</span>
              </Link>
            ))}
            {comingSoonIntegrations.map((platform, idx) => (
              <div
                key={`coming-1-${idx}`}
                className={`${styles.messagingIntegrationCard} ${styles.comingSoon}`}>
                <div
                  className={styles.messagingIntegrationIcon}
                  style={{ color: platform.color }}>
                  {platform.icon}
                </div>
                <h4 className={styles.messagingIntegrationName}>{platform.name}</h4>
                <p className={styles.messagingIntegrationDescription}>{platform.description}</p>
                <span className={`${styles.integrationStatusBadge} ${styles.comingSoonBadge}`}>Coming Soon</span>
              </div>
            ))}
            {/* Duplicate set for seamless loop */}
            {activeIntegrations.map((platform, idx) => (
              <Link
                key={`active-2-${idx}`}
                to={platform.link}
                className={styles.messagingIntegrationCard}>
                <div
                  className={styles.messagingIntegrationIcon}
                  style={{ color: platform.color }}>
                  {platform.icon}
                </div>
                <h4 className={styles.messagingIntegrationName}>{platform.name}</h4>
                <p className={styles.messagingIntegrationDescription}>{platform.description}</p>
                <span className={styles.integrationStatusBadge}>Available</span>
              </Link>
            ))}
            {comingSoonIntegrations.map((platform, idx) => (
              <div
                key={`coming-2-${idx}`}
                className={`${styles.messagingIntegrationCard} ${styles.comingSoon}`}>
                <div
                  className={styles.messagingIntegrationIcon}
                  style={{ color: platform.color }}>
                  {platform.icon}
                </div>
                <h4 className={styles.messagingIntegrationName}>{platform.name}</h4>
                <p className={styles.messagingIntegrationDescription}>{platform.description}</p>
                <span className={`${styles.integrationStatusBadge} ${styles.comingSoonBadge}`}>Coming Soon</span>
              </div>
            ))}
          </div>
        </div>
      </div>
    </section>
  );
}

function FeaturesSection() {
  const features = [
    {
      title: 'Framework Agnostic',
      icon: <MdPower />,
      description: 'Support for LangGraph, OpenAI Agents SDK, Google ADK, and custom frameworks.',
    },
    {
      title: 'Production Ready',
      icon: <MdRocket />,
      description: 'Built-in state management, monitoring, and scalability for enterprise deployments.',
    },
    {
      title: 'Fault Tolerant',
      icon: <MdHealthAndSafety />,
      description: 'Multi-AZ deployments with automatic recovery, health monitoring, and zero downtime.',
    },
    {
      title: 'Multi-Agent Systems',
      icon: <MdHandshake />,
      description: 'Native support for agent-to-agent communication and orchestration.',
    },
    {
      title: 'Easy Deployment',
      icon: <MdFlashOn />,
      description: 'Deploy to AWS, containerized environments, or serverless with Terraform modules.',
    },
  ];

  return (
    <section className={styles.featuresSection}>
      <div className="container">
        <h2 className={styles.sectionTitle}>Why Agent Kernel?</h2>
        <div className={styles.featuresGrid}>
          {features.map((feature, idx) => (
            <div key={idx} className={styles.feature}>
              <div className={styles.featureIcon}>{feature.icon}</div>
              <h3 className={styles.featureTitle}>{feature.title}</h3>
              <p className={styles.featureDescription}>{feature.description}</p>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}

function CommunitySection() {
  const communityLinks = [
    {
      name: 'GitHub',
      description: 'Star our repository and contribute',
      icon: <FaGithub />,
      url: 'https://github.com/yaalalabs/agent-kernel',
    },
    {
      name: 'Discord',
      description: 'Join our community chat',
      icon: <FaDiscord />,
      url: 'https://discord.gg/snrPzb46uu',
    },
    {
      name: 'PyPI',
      description: 'Install via pip',
      icon: <FaPython />,
      url: 'https://pypi.org/project/agentkernel/',
    },
    {
      name: 'Terraform',
      description: 'Deploy with Terraform',
      icon: <SiTerraform />,
      url: 'https://registry.terraform.io/modules/yaalalabs',
    },
  ];

  return (
    <section id="community" className={styles.communitySection}>
      <div className="container">
        <h2 className={styles.sectionTitle}>Join Our Community</h2>
        <div className={styles.communityGrid}>
          {communityLinks.map((link, idx) => (
            <Link
              key={idx}
              to={link.url}
              className={styles.communityCard}
              target="_blank"
              rel="noopener noreferrer">
              <div className={styles.communityIcon}>{link.icon}</div>
              <h3 className={styles.communityName}>{link.name}</h3>
              <p className={styles.communityDescription}>{link.description}</p>
            </Link>
          ))}
        </div>
      </div>
    </section>
  );
}

export default function Home() {
  const { siteConfig } = useDocusaurusContext();
  return (
    <Layout
      title={`${siteConfig.title} - ${siteConfig.tagline}`}
      description="Production-ready agentic framework runtime. Deploy LangGraph, OpenAI Agents SDK, Google ADK, and CrewAI with enterprise features. Framework-agnostic alternative to Semantic Kernel for AI agent deployment, orchestration, and monitoring.">
      <div className={styles.animatedBackground}></div>
      <div className={styles.gridOverlay}></div>
      <div className={styles.particle}></div>
      <div className={styles.particle}></div>
      <div className={styles.particle}></div>
      <div className={styles.particle}></div>
      <div className={styles.particle}></div>
      <div className={styles.beam}></div>
      <div className={styles.beam}></div>
      <div className={styles.beam}></div>
      <div className={styles.beam}></div>
      <div className={styles.beam}></div>
      <div className={styles.beam}></div>
      <HomepageHeader />
      <main>
        <NavigationSection />
        <IntegrationsSection />
        <MessagingIntegrationsSection />
        <FeaturesSection />
        <CommunitySection />
      </main>
    </Layout>
  );
}
