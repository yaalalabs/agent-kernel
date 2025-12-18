import React, { useEffect, useState } from 'react';
import Link from '@docusaurus/Link';
import useDocusaurusContext from '@docusaurus/useDocusaurusContext';
import Layout from '@theme/Layout';
import styles from './features.module.css';
import { 
  MdMemory,
  MdShare,
  MdLayers,
  MdSwapHoriz,
  MdCloud,
  MdSpeed,
  MdSecurity,
  MdVisibility,
  MdApi,
  MdCode,
  MdStorage,
  MdNetworkCheck,
  MdTerminal,
  MdBugReport,
  MdTimer,
  MdScale,
  MdExtension,
  MdArchitecture,
  MdIntegrationInstructions,
  MdRocket,
  MdPower,
  MdGroup,
  MdMessage,
  MdSettings,
  MdHealthAndSafety
} from 'react-icons/md';
import { FaPython, FaAws, FaDocker, FaSlack, FaWhatsapp, FaInstagram, FaTelegram } from 'react-icons/fa';
import { SiTerraform, SiRedis, SiAmazondynamodb, SiOpenai, SiGmail } from 'react-icons/si';
import { FaFacebookMessenger } from 'react-icons/fa6';

function FeaturesHero() {
  return (
    <header className={styles.featuresHero}>
      <div className="container">
        <div className={styles.heroContent}>
          <div className={styles.announcement}>
            🎯 <strong>New:</strong> Execution Hooks & Smart Memory Management — 
            <Link to="/blog/hooks-and-smart-memory" style={{marginLeft: '8px', textDecoration: 'underline'}}>
              Read the announcement →
            </Link>
          </div>
          <h1 className={styles.heroTitle}>Why Agent Kernel Changes the Game</h1>
          <p className={styles.heroSubtitle}>
            Agent Kernel isn’t just a runtime; it’s your acceleration engine.
            Migrate any agent, unlock powerful execution and observability tools, and ship production-ready AI workflows with confidence.
          </p>
          <p className={styles.heroSubtitle}>
            It is a modular, framework-agnostic runtime designed for scalable agent execution. Bring your own agents,
            leverage built-in features, and deploy with production-grade performance and reliability.
          </p>
          <div className={styles.heroButtons}>
            <Link
              className="button button--primary button--lg"
              to="/docs">
              Get Started
            </Link>
          </div>
        </div>
      </div>
    </header>
  );
}

function OverviewSection() {
  return (
    <section id="overview" className={styles.section}>
      <div className="container">
        <div className={styles.sectionHeader}>
          <span className={styles.sectionNumber}>01</span>
          <h2 className={styles.sectionTitle}>Why Agent Kernel?</h2>
          <p className={styles.sectionSubtitle}>
            Built for developers who need flexibility without sacrificing power
          </p>
        </div>
        <div className={styles.overviewGrid}>
          <Link to="/docs/frameworks/overview" className={styles.overviewCard}>
            <div className={styles.overviewIcon}>
              <MdSwapHoriz />
            </div>
            <h3>Framework Agnostic</h3>
            <p>
              Build agents using any AI agentic framework and migrate them to Agent Kernel to benefit from 
              its execution framework capabilities. No vendor lock-in - seamlessly migrate between LangGraph, 
              OpenAI Agents SDK, Google ADK, CrewAI, and custom frameworks without rewriting your agent logic.
            </p>
          </Link>
          <Link to="/docs/core-concepts/overview" className={styles.overviewCard}>
            <div className={styles.overviewIcon}>
              <MdRocket />
            </div>
            <h3>Production Ready</h3>
            <p>
              Enterprise-grade features including built-in session management, conversational state tracking, 
              pluggable memory backends, comprehensive traceability with LangFuse and OpenLLMetry, and 
              multi-agent collaboration support. Deploy with confidence from day one.
            </p>
          </Link>
          <Link to="/docs/deployment/overview" className={styles.overviewCard}>
            <div className={styles.overviewIcon}>
              <MdSpeed />
            </div>
            <h3>Deploy Anywhere</h3>
            <p>
              From CLI testing for local development to REST API servers, AWS serverless, containerized environments, 
              or on-premise deployments. One codebase, multiple deployment options. Switch deployment modes 
              without changing your agent code.
            </p>
          </Link>
          <Link to="/docs/integrations/overview" className={styles.overviewCard}>
            <div className={styles.overviewIcon}>
              <MdIntegrationInstructions />
            </div>
            <h3>Versatile Integrations</h3>
            <p>
              Built-in integrations for popular messaging platforms including Slack, WhatsApp, Messenger, Instagram, and Telegram. 
              Support for MCP Server and A2A Server protocols. Easy-to-build custom integrations with pluggable architecture.
            </p>
          </Link>
        </div>
      </div>
    </section>
  );
}

function CoreFeaturesSection() {
  const features = [
    {
      icon: <MdCode />,
      title: 'Agent Design & Definition',
      description: 'Define agents with clear roles, capabilities, and behaviors using intuitive Python APIs. All framework adapters expose the same core abstractions: Agent, Runner, Session, Module, and Runtime.',
      highlights: ['Python-first SDK', 'Unified API across frameworks', 'Role-based design', 'Flexible configuration'],
      link: '/docs/frameworks/overview'
    },
    {
      icon: <MdExtension />,
      title: 'Tool Integration',
      description: 'Bind custom tools, APIs, and functionalities to your agents for enhanced capabilities. Publish tools via MCP Server for Model Context Protocol integration.',
      highlights: ['Custom tool support', 'API integrations', 'MCP tool publishing', 'Pluggable architecture'],
      link: '/docs/api/mcp-server'
    },
    {
      icon: <MdArchitecture />,
      title: 'Hierarchies & Collaboration',
      description: 'Create agent teams with complex topologies, hierarchies, and collaborative workflows.',
      highlights: ['Multi-agent systems', 'Agent hierarchies', 'Collaborative patterns'],
      link: '/docs/advanced/multi-agent'
    },
    {
      icon: <MdMemory />,
      title: 'Context & Memory',
      description: 'Smart memory management with volatile (request-scoped) and non-volatile (session-persistent) caching. Supports multiple backends: in-memory, Redis, and DynamoDB.',
      highlights: ['Volatile cache for RAG context', 'Non-volatile cache for user preferences', 'Multiple backend support', 'Clean prompts, lower costs'],
      link: '/docs/advanced/memory-management'
    },
    {
      icon: <MdSettings />,
      title: 'Execution Hooks',
      description: 'Powerful pre and post-execution hooks for surgical control over agent behavior. Implement guard rails, RAG context injection, response moderation, and custom logic.',
      highlights: ['Pre-hooks: guard rails, RAG, auth', 'Post-hooks: disclaimers, moderation', 'Hook chaining & composition', 'Framework-agnostic'],
      link: '/docs/integrations/hooks'
    },
    {
      icon: <MdHealthAndSafety />,
      title: 'Fault Tolerance',
      description: 'Production-grade resilience with multi-AZ deployments, automatic failure recovery, and health monitoring for high availability.',
      highlights: ['Multi-AZ deployment', 'Auto-recovery', 'Health monitoring', 'Zero downtime'],
      link: '/docs/core-concepts/fault-tolerance'
    },
    {
      icon: <MdVisibility />,
      title: 'Traceability & Observability',
      description: 'Comprehensive tracking of agent actions, LLM calls, and collaborative operations.',
      highlights: ['LangFuse integration', 'OpenLLMetry support', 'Multi-level verbosity'],
      link: '/docs/advanced/traceability'
    },
    {
      icon: <MdNetworkCheck />,
      title: 'MCP & A2A Support',
      description: 'Built-in Multi-Context Processing and Agent-to-Agent communication capabilities.',
      highlights: ['MCP integration', 'A2A messaging', 'Cross-agent coordination'],
      link: '/docs/api/mcp-server'
    },
  ];

  return (
    <section className={styles.section}>
      <div className="container">
        <div className={styles.sectionHeader}>
          <span className={styles.sectionNumber}>02</span>
          <h2 className={styles.sectionTitle}>Core Features</h2>
          <p className={styles.sectionSubtitle}>
            Everything you need to build sophisticated AI agents
          </p>
        </div>
        <div className={styles.featuresGrid}>
          {features.map((feature, idx) => (
            <div key={idx} className={styles.featureCard} style={{ animationDelay: `${idx * 0.1}s` }}>
              <div className={styles.featureIcon}>{feature.icon}</div>
              <h3>{feature.title}</h3>
              <p>{feature.description}</p>
              <ul className={styles.featureHighlights}>
                {feature.highlights.map((highlight, i) => (
                  <li key={i}>{highlight}</li>
                ))}
              </ul>
              {feature.link && (
                <Link to={feature.link} className={styles.featureLink}>
                  Learn more →
                </Link>
              )}
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}

function FrameworksSection() {
  const frameworks = [
    {
      icon: <SiOpenai />,
      name: 'OpenAI Agents SDK',
      description: 'Full support for OpenAI\'s agentic framework with seamless integration.',
      link: '/docs/frameworks/openai'
    },
    {
      icon: <MdLayers />,
      name: 'LangGraph',
      description: 'Build stateful, multi-actor applications with LangChain\'s graph framework.',
      link: '/docs/frameworks/langgraph'
    },
    {
      icon: <MdPower />,
      name: 'Google ADK',
      description: 'Leverage Google\'s Agent Development Kit for advanced agent capabilities.',
      link: '/docs/frameworks/google-adk'
    },
    {
      icon: <MdIntegrationInstructions />,
      name: 'CrewAI',
      description: 'Orchestrate role-playing autonomous AI agents for complex tasks.',
      link: '/docs/frameworks/crewai'
    },
  ];

  return (
    <section className={styles.section}>
      <div className="container">
        <div className={styles.sectionHeader}>
          <span className={styles.sectionNumber}>03</span>
          <h2 className={styles.sectionTitle}>Framework Support</h2>
          <p className={styles.sectionSubtitle}>
            Work with your favorite agentic frameworks
          </p>
        </div>
        <div className={styles.frameworksGrid}>
          {frameworks.map((framework, idx) => (
            <Link
              key={idx}
              to={framework.link}
              className={styles.frameworkCard}
              style={{ animationDelay: `${idx * 0.15}s` }}>
              <div className={styles.frameworkIcon}>{framework.icon}</div>
              <h3>{framework.name}</h3>
              <p>{framework.description}</p>
              <span className={styles.frameworkLink}>Learn more →</span>
            </Link>
          ))}
        </div>
      </div>
    </section>
  );
}

function MemorySection() {
  const memoryOptions = [
    {
      icon: <MdMemory />,
      name: 'Volatile Cache',
      description: 'Request-scoped temporary storage that auto-clears after execution. Perfect for RAG context, file content, and intermediate data without cluttering prompts.',
      useCases: ['RAG search results', 'Document content from uploads', 'Temporary calculations', 'Request-scoped feature flags']
    },
    {
      icon: <MdStorage />,
      name: 'Non-Volatile Cache',
      description: 'Session-persistent storage that survives across multiple requests. Ideal for user preferences, metadata, and configurations.',
      useCases: ['User preferences', 'Session metadata', 'Extracted information', 'Persistent configurations']
    },
    {
      icon: <SiRedis />,
      name: 'Redis Backend',
      description: 'High-performance distributed memory backend for production workloads with persistent state across instances.',
      useCases: ['Production deployments', 'Multi-process apps', 'Distributed systems', 'Session persistence']
    },
    {
      icon: <SiAmazondynamodb />,
      name: 'DynamoDB Backend',
      description: 'Serverless, auto-scaling NoSQL backend for AWS deployments with configurable TTL and pay-per-use pricing.',
      useCases: ['AWS Lambda deployments', 'Auto-scaling apps', 'Serverless architectures', 'AWS-native infrastructure']
    },
  ];

  return (
    <section className={styles.section}>
      <div className="container">
        <div className={styles.sectionHeader}>
          <span className={styles.sectionNumber}>04</span>
          <h2 className={styles.sectionTitle}>Smart Memory Management</h2>
          <p className={styles.sectionSubtitle}>
            Two types of intelligent caching with identical APIs but different lifecycles. Volatile cache for request-scoped data, 
            non-volatile for session persistence. Multiple backends (in-memory, Redis, DynamoDB) swap with just environment variables.
          </p>
        </div>
        <div className={styles.memoryGrid}>
          {memoryOptions.map((option, idx) => (
            <Link 
              key={idx} 
              to="/docs/advanced/memory-management" 
              className={styles.memoryCard} 
              style={{ animationDelay: `${idx * 0.1}s` }}>
              <div className={styles.memoryIcon}>{option.icon}</div>
              <h3>{option.name}</h3>
              <p>{option.description}</p>
              <div className={styles.useCases}>
                <strong>Use Cases:</strong>
                <ul>
                  {option.useCases.map((useCase, i) => (
                    <li key={i}>{useCase}</li>
                  ))}
                </ul>
              </div>
            </Link>
          ))}
        </div>
        <div className={styles.sectionFooter}>
          <Link to="/docs/advanced/memory-management" className={styles.sectionLink}>
            View Memory Management Documentation →
          </Link>
        </div>
      </div>
    </section>
  );
}

function TestingSection() {
  return (
    <section className={styles.section}>
      <div className="container">
        <div className={styles.sectionHeader}>
          <span className={styles.sectionNumber}>05</span>
          <h2 className={styles.sectionTitle}>Testing & Development</h2>
          <p className={styles.sectionSubtitle}>
            Built-in agent test framework for local development. Focus on domain-specific agent development 
            while Agent Kernel takes care of testing, deployment, and execution.
          </p>
        </div>
        <div className={styles.testingContent}>
          <Link to="/docs/testing/overview" className={styles.testingFeature}>
            <div className={styles.testingIcon}>
              <MdTerminal />
            </div>
            <h3>CLI-Based Testing</h3>
            <p>
              Interactive command-line interface for real-time agent testing and debugging. 
              Test your agents in a controlled environment before deployment.
            </p>
            <ul className={styles.testingList}>
              <li>Interactive chat sessions</li>
              <li>Real-time feedback</li>
              <li>Easy debugging</li>
              <li>Local execution</li>
            </ul>
          </Link>
          <Link to="/docs/testing/overview" className={styles.testingFeature}>
            <div className={styles.testingIcon}>
              <MdBugReport />
            </div>
            <h3>Automated Test Framework</h3>
            <p>
              Execute predefined test scenarios to validate agent behavior consistently. 
              Build comprehensive test suites for your agentic systems.
            </p>
            <ul className={styles.testingList}>
              <li>Scenario-based testing</li>
              <li>Automated validation</li>
              <li>Regression testing</li>
              <li>CI/CD integration</li>
            </ul>
          </Link>
        </div>
        <div className={styles.sectionFooter}>
          <Link to="/docs/testing/overview" className={styles.sectionLink}>
            View Testing Documentation →
          </Link>
        </div>
      </div>
    </section>
  );
}

function DeploymentSection() {
  return (
    <section className={styles.section}>
      <div className="container">
        <div className={styles.sectionHeader}>
          <span className={styles.sectionNumber}>06</span>
          <h2 className={styles.sectionTitle}>Deployment Options</h2>
          <p className={styles.sectionSubtitle}>
            Ready-to-use execution capabilities for every environment. Deploy anywhere, from local development 
            to global scale production, without changing your agent code.
          </p>
        </div>
        
        <div className={styles.deploymentOptions}>
          <Link to="/docs/deployment/overview" className={styles.deploymentCard}>
            <div className={styles.deploymentHeader}>
              <MdTerminal className={styles.deploymentIcon} />
              <h3>Local Development</h3>
            </div>
            <p>Test and develop agents locally with the built-in Agent Tester utility.</p>
            <ul className={styles.deploymentFeatures}>
              <li>CLI-based interaction</li>
              <li>Automated test scenarios</li>
              <li>Rapid iteration</li>
              <li>No cloud dependencies</li>
            </ul>
          </Link>

          <Link to="/docs/deployment/aws-serverless" className={styles.deploymentCard}>
            <div className={styles.deploymentHeader}>
              <FaAws className={styles.deploymentIcon} />
              <h3>AWS Serverless</h3>
            </div>
            <p>Scale dynamically with serverless architecture for variable workloads.</p>
            <ul className={styles.deploymentFeatures}>
              <li>Lambda-based execution</li>
              <li>Auto-scaling</li>
              <li>Pay-per-use pricing</li>
              <li>Zero infrastructure management</li>
            </ul>
            <span className={styles.deploymentLink}>
              View Guide →
            </span>
          </Link>

          <Link to="/docs/deployment/aws-containerized" className={styles.deploymentCard}>
            <div className={styles.deploymentHeader}>
              <MdCloud className={styles.deploymentIcon} />
              <h3>AWS Containerized</h3>
            </div>
            <p>Consistent performance with container-based deployment on AWS.</p>
            <ul className={styles.deploymentFeatures}>
              <li>ECS/EKS support</li>
              <li>Lower latency</li>
              <li>Predictable performance</li>
              <li>Resource optimization</li>
            </ul>
            <span className={styles.deploymentLink}>
              View Guide →
            </span>
          </Link>

          <Link to="/docs/deployment/overview" className={styles.deploymentCard}>
            <div className={styles.deploymentHeader}>
              <FaDocker className={styles.deploymentIcon} />
              <h3>On-Premise / Docker</h3>
            </div>
            <p>Deploy in your own infrastructure with REST API and Docker support.</p>
            <ul className={styles.deploymentFeatures}>
              <li>Full control</li>
              <li>Docker containerization</li>
              <li>REST API included</li>
              <li>Custom infrastructure</li>
            </ul>
          </Link>
        </div>

        <div className={styles.terraformSection}>
          <SiTerraform className={styles.terraformIcon} />
          <h3>Infrastructure as Code</h3>
          <p>
            Deploy with confidence using our official Terraform modules. One-command deployment 
            to AWS with best practices baked in.
          </p>
          <Link 
            to="https://registry.terraform.io/modules/yaalalabs" 
            className="button button--primary"
            target="_blank"
            rel="noopener noreferrer">
            View Terraform Modules
          </Link>
        </div>
        <div className={styles.sectionFooter}>
          <Link to="/docs/deployment/overview" className={styles.sectionLink}>
            View Deployment Documentation →
          </Link>
        </div>
      </div>
    </section>
  );
}

function ObservabilitySection() {
  return (
    <section className={styles.section}>
      <div className="container">
        <div className={styles.sectionHeader}>
          <span className={styles.sectionNumber}>07</span>
          <h2 className={styles.sectionTitle}>Observability & Traceability</h2>
          <p className={styles.sectionSubtitle}>
            Complete visibility into agent operations
          </p>
        </div>
        
        <div className={styles.observabilityContent}>
          <div className={styles.observabilityFeature}>
            <MdVisibility className={styles.observabilityIcon} />
            <h3>Multi-Level Traceability</h3>
            <p>Track every action, decision, and LLM call with configurable verbosity levels.</p>
            <ul>
              <li>Agent action tracking</li>
              <li>LLM call monitoring</li>
              <li>Collaborative operation logs</li>
              <li>Performance metrics</li>
            </ul>
          </div>

          <div className={styles.observabilityIntegrations}>
            <h3>Integrated Observability Tools</h3>
            <div className={styles.integrationCards}>
              <div className={styles.integrationCard}>
                <h4>LangFuse</h4>
                <p>Comprehensive LLM observability and analytics platform</p>
              </div>
              <div className={styles.integrationCard}>
                <h4>TraceLoop OpenLLMetry</h4>
                <p>OpenTelemetry-based observability for LLM applications</p>
              </div>
            </div>
            <Link to="/docs/advanced/traceability" className={styles.learnMoreLink}>
              Learn more about traceability →
            </Link>
          </div>
        </div>
      </div>
    </section>
  );
}

function MessagingSection() {
  const platforms = [
    { name: 'Slack', icon: <FaSlack />, status: 'Available' },
    { name: 'WhatsApp', icon: <FaWhatsapp />, status: 'Available' },
    { name: 'Messenger', icon: <FaFacebookMessenger />, status: 'Available' },
    { name: 'Telegram', icon: <FaTelegram />, status: 'Available' },
    { name: 'Instagram', icon: <FaInstagram />, status: 'Available' },
    { name: 'Gmail', icon: <SiGmail />, status: 'Coming Soon' },
  ];

  return (
    <section className={styles.section}>
      <div className="container">
        <div className={styles.sectionHeader}>
          <span className={styles.sectionNumber}>08</span>
          <h2 className={styles.sectionTitle}>Messaging Integrations</h2>
          <p className={styles.sectionSubtitle}>
            Connect your AI agents to popular messaging platforms and reach your users where they are. 
            Built-in integrations for Slack, WhatsApp, Messenger, Instagram, and Telegram.
          </p>
        </div>
        
        <div className={styles.messagingGrid}>
          {platforms.map((platform, idx) => {
            const card = (
              <>
                <div className={styles.messagingIcon}>{platform.icon}</div>
                <h3>{platform.name}</h3>
                <span className={styles.messagingStatus}>{platform.status}</span>
              </>
            );
            
            if (platform.status === 'Coming Soon') {
              return (
                <div 
                  key={idx} 
                  className={`${styles.messagingCard} ${styles.comingSoon}`}
                  style={{ animationDelay: `${idx * 0.1}s` }}>
                  {card}
                </div>
              );
            }
            
            const docLink = `/docs/integrations/${platform.name.toLowerCase()}`;
            return (
              <Link
                key={idx}
                to={docLink}
                className={styles.messagingCard}
                style={{ animationDelay: `${idx * 0.1}s` }}>
                {card}
              </Link>
            );
          })}
        </div>
        <div className={styles.sectionFooter}>
          <Link to="/docs/integrations/overview" className={styles.sectionLink}>
            View Integrations Documentation →
          </Link>
        </div>
      </div>
    </section>
  );
}

function CTASection() {
  return (
    <section className={styles.ctaSection}>
      <div className="container">
        <div className={styles.ctaContent}>
          <h2>Ready to Build Your AI Agents?</h2>
          <p>
            Agent Kernel is ideal for AI engineers who want framework flexibility, teams building production 
            AI agent systems, developers migrating between frameworks, organizations requiring enterprise-grade 
            deployment, and researchers exploring different agent frameworks.
          </p>
          <p style={{ marginTop: '1rem' }}>
            Get started with Agent Kernel today and bring your agentic applications to production.
          </p>
          <div className={styles.ctaButtons}>
            <Link
              className="button button--primary button--lg"
              to="/docs">
              Get Started
            </Link>
            <Link
              className="button button--secondary button--lg"
              to="https://github.com/yaalalabs/agent-kernel"
              target="_blank"
              rel="noopener noreferrer">
              View on GitHub
            </Link>
          </div>
        </div>
      </div>
    </section>
  );
}

export default function Features() {
  const { siteConfig } = useDocusaurusContext();
  
  return (
    <Layout
      title="Features"
      description="Comprehensive overview of Agent Kernel features - framework-agnostic AI agent runtime">
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
      <FeaturesHero />
      <main className={styles.mainContent}>
        <OverviewSection />
        <CoreFeaturesSection />
        <FrameworksSection />
        <MemorySection />
        <TestingSection />
        <DeploymentSection />
        <ObservabilitySection />
        <MessagingSection />
        <CTASection />
      </main>
    </Layout>
  );
}
