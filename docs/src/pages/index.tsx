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
  MdConstruction
} from 'react-icons/md';
import { FaGithub, FaDiscord, FaPython } from 'react-icons/fa';
import { SiTerraform } from 'react-icons/si';

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
        <h2 className={styles.sectionTitle}>Where would you like to go?</h2>
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
      url: 'https://discord.gg/k98XXq3N',
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
      description="Production-ready, framework-agnostic runtime for deploying and managing AI agents">
      <div className={styles.animatedBackground}></div>
      <div className={styles.gridOverlay}></div>
      <div className={styles.particle}></div>
      <div className={styles.particle}></div>
      <div className={styles.particle}></div>
      <div className={styles.particle}></div>
      <div className={styles.particle}></div>
      <HomepageHeader />
      <main>
        <NavigationSection />
        <FeaturesSection />
        <CommunitySection />
      </main>
    </Layout>
  );
}
