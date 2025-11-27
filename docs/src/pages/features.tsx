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
  MdSettings
} from 'react-icons/md';
import { FaPython, FaAws, FaDocker, FaSlack, FaWhatsapp, FaInstagram, FaTelegram } from 'react-icons/fa';
import { SiTerraform, SiRedis, SiAmazondynamodb, SiOpenai, SiGmail } from 'react-icons/si';
import { FaFacebookMessenger } from 'react-icons/fa6';

function FeaturesHero() {
  return (
    <header className={styles.featuresHero}>
      <div className="container">
        <div className={styles.heroContent}>
          <h1 className={styles.heroTitle}>Agent Kernel Features</h1>
          <p className={styles.heroSubtitle}>
            A versatile, framework-agnostic runtime for building and deploying AI agents. 
            Migrate your existing agents and instantly utilize pre-built execution and testing capabilities.
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
          <div className={styles.overviewCard}>
            <div className={styles.overviewIcon}>
              <MdSwapHoriz />
            </div>
            <h3>Framework Agnostic</h3>
            <p>
              Build agents using any AI agentic framework and migrate them to Agent Kernel to benefit from 
              its execution framework capabilities. No vendor lock-in - seamlessly migrate between LangGraph, 
              OpenAI Agents SDK, Google ADK, CrewAI, and custom frameworks without rewriting your agent logic.
            </p>
          </div>
          <div className={styles.overviewCard}>
            <div className={styles.overviewIcon}>
              <MdRocket />
            </div>
            <h3>Production Ready</h3>
            <p>
              Enterprise-grade features including built-in session management, conversational state tracking, 
              pluggable memory backends, comprehensive traceability with LangFuse and OpenLLMetry, and 
              multi-agent collaboration support. Deploy with confidence from day one.
            </p>
          </div>
          <div className={styles.overviewCard}>
            <div className={styles.overviewIcon}>
              <MdSpeed />
            </div>
            <h3>Deploy Anywhere</h3>
            <p>
              From CLI testing for local development to REST API servers, AWS serverless, containerized environments, 
              or on-premise deployments. One codebase, multiple deployment options. Switch deployment modes 
              without changing your agent code.
            </p>
          </div>
          <div className={styles.overviewCard}>
            <div className={styles.overviewIcon}>
              <MdIntegrationInstructions />
            </div>
            <h3>Versatile Integrations</h3>
            <p>
              Built-in integrations for popular messaging platforms including Slack, WhatsApp, and Messenger. 
              Support for MCP Server and A2A Server protocols. Easy-to-build custom integrations with pluggable architecture.
            </p>
          </div>
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
      description: 'Efficient memory management with support for in-memory, Redis, and DynamoDB backends.',
      highlights: ['Multiple memory stores', 'Context preservation', 'Custom adapters'],
      link: '/docs/advanced/memory-management'
    },
    {
      icon: <MdSettings />,
      title: 'Execution Hooks',
      description: 'Customize agent behavior with pre and post-execution hooks for guardrails, RAG, and response moderation.',
      highlights: ['Pre-execution hooks', 'Post-execution hooks', 'Context injection'],
      link: '/docs/integrations/hooks'
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
      name: 'In-Memory',
      description: 'Fast, ephemeral storage for development and testing',
      useCases: ['Local development', 'Testing', 'Prototyping']
    },
    {
      icon: <SiRedis />,
      name: 'Redis',
      description: 'High-performance distributed memory for production workloads',
      useCases: ['Production systems', 'Shared state', 'High throughput']
    },
    {
      icon: <SiAmazondynamodb />,
      name: 'DynamoDB',
      description: 'Serverless, scalable NoSQL database for AWS deployments',
      useCases: ['Serverless apps', 'AWS environments', 'Global scale']
    },
    {
      icon: <MdStorage />,
      name: 'Custom Adapters',
      description: 'Build your own memory backend for specific requirements',
      useCases: ['Enterprise systems', 'Custom databases', 'Special needs']
    },
  ];

  return (
    <section className={styles.section}>
      <div className="container">
        <div className={styles.sectionHeader}>
          <span className={styles.sectionNumber}>04</span>
          <h2 className={styles.sectionTitle}>Memory Management</h2>
          <p className={styles.sectionSubtitle}>
            Pluggable memory architecture with flexible backends for every use case. 
            Choose the right storage solution for your development, testing, and production needs.
          </p>
        </div>
        <div className={styles.memoryGrid}>
          {memoryOptions.map((option, idx) => (
            <div key={idx} className={styles.memoryCard} style={{ animationDelay: `${idx * 0.1}s` }}>
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
            </div>
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
          <div className={styles.testingFeature}>
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
          </div>
          <div className={styles.testingFeature}>
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
          </div>
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
          <div className={styles.deploymentCard}>
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
          </div>

          <div className={styles.deploymentCard}>
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
            <Link to="/docs/deployment/aws-serverless" className={styles.deploymentLink}>
              View Guide →
            </Link>
          </div>

          <div className={styles.deploymentCard}>
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
            <Link to="/docs/deployment/aws-containerized" className={styles.deploymentLink}>
              View Guide →
            </Link>
          </div>

          <div className={styles.deploymentCard}>
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
            <Link to="/docs/deployment/overview" className={styles.deploymentLink}>
              View Guide →
            </Link>
          </div>
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
    { name: 'Facebook Messenger', icon: <FaFacebookMessenger />, status: 'Available' },
    { name: 'Instagram', icon: <FaInstagram />, status: 'Coming Soon' },
    { name: 'Gmail', icon: <SiGmail />, status: 'Coming Soon' },
    { name: 'Telegram', icon: <FaTelegram />, status: 'Coming Soon' },
  ];

  return (
    <section className={styles.section}>
      <div className="container">
        <div className={styles.sectionHeader}>
          <span className={styles.sectionNumber}>08</span>
          <h2 className={styles.sectionTitle}>Messaging Integrations</h2>
          <p className={styles.sectionSubtitle}>
            Connect your AI agents to popular messaging platforms and reach your users where they are. 
            Built-in integrations for Slack, WhatsApp, and Messenger, with more coming soon.
          </p>
        </div>
        
        <div className={styles.messagingGrid}>
          {platforms.map((platform, idx) => (
            <div 
              key={idx} 
              className={`${styles.messagingCard} ${platform.status === 'Coming Soon' ? styles.comingSoon : ''}`}
              style={{ animationDelay: `${idx * 0.1}s` }}>
              <div className={styles.messagingIcon}>{platform.icon}</div>
              <h3>{platform.name}</h3>
              <span className={styles.messagingStatus}>{platform.status}</span>
            </div>
          ))}
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
