import React from 'react';
import Link from '@docusaurus/Link';
import Layout from '@theme/Layout';
import styles from './features.module.css';
import RequestLifecycleAnimation from '../components/RequestLifecycleAnimation';
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
  MdExtension,
  MdArchitecture,
  MdIntegrationInstructions,
  MdRocketLaunch,
  MdPower,
  MdGroup,
  MdMessage,
  MdSettings,
  MdHealthAndSafety,
  MdCheck,
} from 'react-icons/md';
import { FaPython, FaAws, FaDocker, FaSlack, FaWhatsapp, FaInstagram, FaTelegram } from 'react-icons/fa';
import { SiTerraform, SiRedis, SiAmazondynamodb, SiOpenai, SiGmail } from 'react-icons/si';
import { FaMicrosoft } from 'react-icons/fa';
import { FaFacebookMessenger } from 'react-icons/fa6';

/* ─── Hero ──────────────────────────────────────────────────────────────── */

function Hero() {
  return (
    <header className={styles.hero}>
      <div className={styles.heroOrb} />
      <div className={styles.heroGrid} />
      <div className="container">
        <div className={styles.heroContent}>
          <span className={styles.heroBadge}>Everything in one runtime</span>
          <h1 className={styles.heroTitle}>Why Agent Kernel<br />Changes the Game</h1>
          <p className={styles.heroSubtitle}>
            Like Express.js for web servers or Spring Boot for Java — Agent Kernel is the scaffolding,
            execution environment, session management, and deployment infrastructure for AI agents.
            You bring the logic. We handle the rest.
          </p>
          <div className={styles.heroButtons}>
            <Link className={`button button--primary button--lg ${styles.btnPrimary}`} to="/docs">
              Get Started →
            </Link>
            <Link className={`button button--secondary button--lg ${styles.btnSecondary}`} to="/use-cases">
              Find Your Use Case →
            </Link>
          </div>
        </div>
      </div>
    </header>
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
    <section className={styles.section}>
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
      icon: <MdStorage />,
      title: 'Knowledge Bases',
      description: 'Backend-agnostic durable knowledge storage for cross-session, multi-agent knowledge. Semantic search, graph queries, and SQL analytics with a single unified API.',
      highlights: ['ChromaDB — vector/semantic search', 'Neo4j — entity and relationship graphs', 'Starburst Galaxy — SQL over MongoDB, Sheets, PostgreSQL', 'semantic_map keeps agent prompts portable'],
      link: '/docs/next/architecture/knowledge-bases',
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
    <section className={styles.section}>
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
    {
      name: 'Smol Agents',
      description: "Hugging Face's lightweight agentic framework for open-source models. Coming soon.",
      link: '/docs/frameworks/overview',
      comingSoon: true,
    },
    {
      name: 'LiveKit Agents',
      description: 'Real-time audio and video agent framework for voice-enabled AI applications. Coming soon.',
      link: '/docs/frameworks/overview',
      comingSoon: true,
    },
  ];

  return (
    <section className={styles.section}>
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
              className={`${styles.frameworkCard} ${f.featured ? styles.frameworkFeatured : ''} ${'comingSoon' in f && f.comingSoon ? styles.frameworkComingSoon ?? '' : ''}`}
              style={'comingSoon' in f && f.comingSoon ? { opacity: 0.6 } : {}}>
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

/* ─── Memory Section ────────────────────────────────────────────────────── */

function MemorySection() {
  const types = [
    {
      icon: <MdMemory />,
      name: 'Volatile Cache',
      description: 'Request-scoped temporary storage. Auto-clears after each request. Keeps prompts clean and reduces token usage.',
      useCases: ['RAG search results', 'Uploaded file content', 'Temporary calculations', 'Request-scoped flags'],
    },
    {
      icon: <MdStorage />,
      name: 'Non-Volatile Cache',
      description: 'Session-persistent storage that survives across multiple requests. Share data between hooks and tools.',
      useCases: ['User preferences', 'Session metadata', 'Extracted entities', 'Persistent configurations'],
    },
    {
      icon: <SiRedis />,
      name: 'Redis Backend',
      description: 'High-performance distributed memory for production AWS and Azure workloads.',
      useCases: ['Production deployments', 'Multi-process apps', 'Distributed systems', 'Session persistence'],
    },
    {
      icon: <SiAmazondynamodb />,
      name: 'DynamoDB / Cosmos DB',
      description: 'Serverless, auto-scaling NoSQL for AWS Lambda and Azure Functions with configurable TTL.',
      useCases: ['Serverless deployments', 'Auto-scaling apps', 'Pay-per-use pricing', 'Cloud-native infrastructure'],
    },
  ];

  return (
    <section className={styles.section}>
      <div className="container">
        <div className={styles.sectionHeader}>
          <span className={styles.sectionNumber}>04</span>
          <h2 className={styles.sectionTitle}>Smart Memory Management</h2>
          <p className={styles.sectionSubtitle}>
            Two cache types with identical APIs, different lifecycles. Swap backends with environment variables — no code changes.
          </p>
        </div>
        <div className={styles.memoryGrid}>
          {types.map((t, i) => (
            <Link key={i} to="/docs/architecture/memory-management" className={styles.memoryCard}>
              <div className={styles.memoryIcon}>{t.icon}</div>
              <h3 className={styles.memoryName}>{t.name}</h3>
              <p className={styles.memoryDescription}>{t.description}</p>
              <ul className={styles.memoryUseCases}>
                {t.useCases.map((u, j) => <li key={j}>{u}</li>)}
              </ul>
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
    <section className={styles.section}>
      <div className="container">
        <div className={styles.sectionHeader}>
          <span className={styles.sectionNumber}>05</span>
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

/* ─── Deployment Section ────────────────────────────────────────────────── */

function DeploymentSection() {
  const options = [
    {
      icon: <MdTerminal />,
      title: 'Local Development',
      description: 'CLI testing and REST API server for local iteration.',
      features: ['CLI interactive sessions', 'Automated test scenarios', 'No cloud dependencies', 'Fast iteration'],
      link: '/docs/deployment/local',
    },
    {
      icon: <FaAws />,
      title: 'AWS Serverless',
      description: 'Lambda-based execution for variable, cost-efficient workloads.',
      features: ['Lambda execution', 'Auto-scaling', 'Pay-per-use', 'DynamoDB session storage'],
      link: '/docs/deployment/aws-serverless',
    },
    {
      icon: <FaAws />,
      title: 'AWS Containerized',
      description: 'ECS/Fargate for consistent, predictable production performance.',
      features: ['ECS/Fargate', 'Multi-AZ', 'Predictable performance', 'Redis session storage'],
      link: '/docs/deployment/aws-containerized',
    },
    {
      icon: <FaMicrosoft />,
      title: 'Azure Serverless',
      description: 'Azure Functions with KEDA-based scaling and Cosmos DB.',
      features: ['Azure Functions', 'KEDA auto-scaling', 'Cosmos DB storage', 'Pay-per-use'],
      link: '/docs/deployment/azure-serverless',
    },
    {
      icon: <FaMicrosoft />,
      title: 'Azure Containerized',
      description: 'Container Apps for multi-zone, high-availability deployments.',
      features: ['Container Apps', 'Multi-zone HA', 'Built-in scaling', 'Redis session storage'],
      link: '/docs/deployment/azure-containerized',
    },
    {
      icon: <FaDocker />,
      title: 'On-Premise / Docker',
      description: 'Full control with Docker and REST API for on-premise deployments.',
      features: ['Docker support', 'REST API server', 'Custom infrastructure', 'Full control'],
      link: '/docs/deployment/local',
    },
  ];

  return (
    <section className={styles.section}>
      <div className="container">
        <div className={styles.sectionHeader}>
          <span className={styles.sectionNumber}>06</span>
          <h2 className={styles.sectionTitle}>Deploy Anywhere</h2>
          <p className={styles.sectionSubtitle}>
            From local CLI to global multi-cloud production — the same agent code runs everywhere.
          </p>
        </div>
        <div className={styles.deploymentGrid}>
          {options.map((o, i) => (
            <Link key={i} to={o.link} className={styles.deploymentCard}>
              <div className={styles.deploymentHeader}>
                <span className={styles.deploymentIcon}>{o.icon}</span>
                <h3 className={styles.deploymentTitle}>{o.title}</h3>
              </div>
              <p className={styles.deploymentDescription}>{o.description}</p>
              <ul className={styles.deploymentFeatures}>
                {o.features.map((f, j) => <li key={j}>{f}</li>)}
              </ul>
            </Link>
          ))}
        </div>
        <div className={styles.terraformBanner}>
          <SiTerraform className={styles.terraformBannerIcon} />
          <div>
            <h3>Infrastructure as Code — Multi-Cloud</h3>
            <p>Official Terraform modules for AWS and Azure. Production-ready with best practices baked in.</p>
          </div>
          <div className={styles.terraformBannerButtons}>
            <Link
              to="https://registry.terraform.io/modules/yaalalabs?provider=aws"
              className="button button--primary"
              target="_blank"
              rel="noopener noreferrer">
              <FaAws style={{ marginRight: '6px' }} /> AWS Modules
            </Link>
            <Link
              to="https://registry.terraform.io/modules/yaalalabs?provider=azurerm"
              className="button button--secondary"
              target="_blank"
              rel="noopener noreferrer">
              <FaMicrosoft style={{ marginRight: '6px' }} /> Azure Modules
            </Link>
          </div>
        </div>
      </div>
    </section>
  );
}

/* ─── Observability Section ─────────────────────────────────────────────── */

function ObservabilitySection() {
  return (
    <section className={styles.section}>
      <div className="container">
        <div className={styles.sectionHeader}>
          <span className={styles.sectionNumber}>07</span>
          <h2 className={styles.sectionTitle}>Observability & Traceability</h2>
          <p className={styles.sectionSubtitle}>
            Full visibility into every agent action, LLM call, and tool invocation — with one config line.
          </p>
        </div>
        <div className={styles.observabilityLayout}>
          <div className={styles.observabilityText}>
            <MdVisibility className={styles.observabilityBigIcon} />
            <h3>Multi-Level Tracing</h3>
            <p>Track every decision your agents make at the granularity you choose.</p>
            <ul>
              <li>Agent action tracking</li>
              <li>LLM call monitoring with cost estimation</li>
              <li>Tool invocation logs</li>
              <li>Multi-agent collaboration traces</li>
              <li>Performance metrics and latency</li>
            </ul>
            <Link to="/docs/advanced/traceability" className={styles.featureLink}>
              View traceability docs →
            </Link>
          </div>
          <div className={styles.observabilityTools}>
            <div className={styles.observabilityTool}>
              <h4>LangFuse</h4>
              <p>Comprehensive LLM observability, analytics, and prompt management platform.</p>
            </div>
            <div className={styles.observabilityTool}>
              <h4>OpenLLMetry (Traceloop)</h4>
              <p>OpenTelemetry-based observability for LLM applications. Works with any OTel backend.</p>
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}

/* ─── Guardrails Section ────────────────────────────────────────────────── */

function GuardrailsSection() {
  return (
    <section className={styles.section}>
      <div className="container">
        <div className={styles.sectionHeader}>
          <span className={styles.sectionNumber}>08</span>
          <h2 className={styles.sectionTitle}>Content Safety & Guardrails</h2>
          <p className={styles.sectionSubtitle}>
            Validate inputs before agents see them and outputs before users do.
            Works with any Agent Kernel framework via execution hooks.
          </p>
        </div>
        <div className={styles.observabilityLayout}>
          <div className={styles.observabilityText}>
            <MdSecurity className={styles.observabilityBigIcon} />
            <h3>Multi-Layer Protection</h3>
            <p>Validate content at both input and output stages with pluggable providers.</p>
            <ul>
              <li>Input validation before agent processing</li>
              <li>Output validation before delivery</li>
              <li>PII detection and redaction (30+ entity types)</li>
              <li>Jailbreak and prompt attack detection</li>
              <li>Topic blocking and keyword filtering</li>
              <li>Contextual grounding checks</li>
            </ul>
            <Link to="/docs/advanced/guardrails" className={styles.featureLink}>
              View guardrails docs →
            </Link>
          </div>
          <div className={styles.observabilityTools}>
            <div className={styles.observabilityTool}>
              <h4>OpenAI Guardrails</h4>
              <p>Flexible LLM-based content validation with custom rules and policies.</p>
            </div>
            <div className={styles.observabilityTool}>
              <h4>AWS Bedrock Guardrails</h4>
              <p>Enterprise-grade content filtering with 30+ PII types and contextual grounding checks.</p>
            </div>
          </div>
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
    { name: 'Teams', icon: <FaMicrosoft />, color: '#6264A7', link: '/docs/integrations/teams' },
  ];

  return (
    <section className={styles.section}>
      <div className="container">
        <div className={styles.sectionHeader}>
          <span className={styles.sectionNumber}>09</span>
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
    <section className={styles.ctaSection}>
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
              Get Started →
            </Link>
            <Link className={`button button--secondary button--lg ${styles.btnSecondary}`} to="/use-cases">
              Find Your Use Case →
            </Link>
            <Link
              className={`button button--secondary button--lg ${styles.btnSecondary}`}
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

/* ─── Page Export ───────────────────────────────────────────────────────── */

export default function Features() {
  return (
    <Layout
      title="Features"
      description="Comprehensive overview of Agent Kernel features — framework-agnostic, multi-cloud AI agent runtime with built-in testing, observability, guardrails, and messaging integrations.">
      <Hero />
      <main>
        <ProblemTable />
        <RequestLifecycleAnimation />
        <CoreFeatures />
        <FrameworkSupport />
        <MemorySection />
        <TestingSection />
        <DeploymentSection />
        <ObservabilitySection />
        <GuardrailsSection />
        <MessagingSection />
        <CTASection />
      </main>
    </Layout>
  );
}
