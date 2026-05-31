import React, { useState, useEffect, useRef } from "react";
import gsap from "gsap";
import ScrollTrigger from "gsap/dist/ScrollTrigger";
import Link from "@docusaurus/Link";
import Layout from "@theme/Layout";
import {
  MdTerminal,
  MdBolt,
  MdCode,
  MdAutoAwesome,
  MdSmartToy,
  MdLink,
  MdPermMedia,
} from "react-icons/md";
import styles from "./index.module.css";
import AgentKernelArchDiagram from "../components/AgentKernelArchDiagram";
import { StepTimeline } from "../components/StepTimeline";
import HeroAnimation from "../components/HeroAnimation";

const DEV_FEATURE_GROUPS = [
  {
    title: "Build & Interface",
    cols: 4 as const,
    features: [
      {
        icon: MdTerminal,
        title: "CLI for Prototyping",
        body: "Easy interfacing your agents on your laptop via Agent Kernel's command line interface.",
      },
      {
        icon: MdBolt,
        title: "REST API Server",
        body: "FastAPI-based server out of the box. No boilerplate. Just run your agent.",
      },
      {
        icon: MdCode,
        title: "Native MCP and A2A support",
        body: "Expose agents as tools (MCP) and enable agent-to-agent collaboration (A2A). Makes integration with external AI systems straightforward.",
      },
      {
        icon: MdAutoAwesome,
        title: "Multi-Framework Support",
        body: "Run OpenAI Agents, LangGraph, CrewAI, Google ADK, Smolagents, LiveKit side-by-side. Keep one runtime across teams while using the best framework per use case.",
      },
    ],
  },
  {
    title: "Runtime & Extensibility",
    cols: 3 as const,
    features: [
      {
        icon: MdSmartToy,
        title: "Pluggable Session & Memory",
        body: "Start local in-memory, scale to Redis, DynamoDB, or Cosmos DB in production. Switch via config, not code rewrites.",
      },
      {
        icon: MdLink,
        title: "Execution Hooks",
        body: "Pre/post hooks for RAG injection, input validation, response moderation, analytics.",
      },
      {
        icon: MdPermMedia,
        title: "Multimodal Support",
        body: "In-built framework-neutral multimodal support across all integration channels. Handle files/images cleanly and keep sessions lightweight. Additional voice and video support via LiveKit.",
      },
    ],
  },
];

export default function DeveloperPage() {
  const [selectedFramework, setSelectedFramework] = useState<string>("openai");
  const [copiedCode, setCopiedCode] = useState<string | null>(null);
  const contentRef = useRef<HTMLDivElement>(null);
  const sectionRef = useRef<HTMLElement>(null);

  const copyToClipboard = (code: string, id: string) => {
    navigator.clipboard.writeText(code);
    setCopiedCode(id);
    setTimeout(() => setCopiedCode(null), 2000);
  };

  useEffect(() => {
    gsap.registerPlugin(ScrollTrigger);

    if (!sectionRef.current || !contentRef.current) {
      return;
    }

    const context = gsap.context(() => {
      // Animate developer analogy section
      const devAnalogy = contentRef.current?.querySelector(
        `.${styles.developerAnalogy}`,
      );
      if (devAnalogy) {
        gsap.fromTo(
          devAnalogy,
          { opacity: 0, y: 35 },
          {
            opacity: 1,
            y: 0,
            duration: 1.1,
            ease: "power2.out",
            scrollTrigger: {
              trigger: devAnalogy,
              start: "top 75%",
              toggleActions: "play none none reverse",
            },
          },
        );
      }

      // Animate Architecture Wrapper
      const archWrappers =
        contentRef.current?.querySelectorAll(
          `.${styles.devArchitectureWrapper}`,
        ) || [];
      archWrappers.forEach((wrapper) => {
        gsap.fromTo(
          wrapper,
          { opacity: 0, y: 40, scale: 0.95 },
          {
            opacity: 1,
            y: 0,
            scale: 1,
            duration: 1.1,
            ease: "power2.out",
            scrollTrigger: {
              trigger: wrapper,
              start: "top 80%",
              toggleActions: "play none none reverse",
            },
          },
        );
      });

      // Animate architecture layers - Slide from left
      const layers =
        contentRef.current?.querySelectorAll(
          `.${styles.architectureLayerGroup}`,
        ) || [];
      layers.forEach((layer, index) => {
        gsap.fromTo(
          layer,
          { opacity: 0, x: -50 },
          {
            opacity: 1,
            x: 0,
            duration: 0.9,
            delay: index * 0.12,
            ease: "power2.out",
            scrollTrigger: {
              trigger: layer,
              start: "top 85%",
              toggleActions: "play none none reverse",
            },
          },
        );
      });

      // Animate feature cards
      const devFeatureCard =
        contentRef.current?.querySelectorAll(`.${styles.devFeatureCard}`) || [];
      devFeatureCard.forEach((card, idx) => {
        gsap.fromTo(
          card,
          { opacity: 0, y: 25, scale: 0.96 },
          {
            opacity: 1,
            y: 0,
            scale: 1,
            duration: 0.95,
            ease: "power2.out",
            delay: (idx % 3) * 0.1,
            scrollTrigger: {
              trigger: card,
              start: "top 88%",
              toggleActions: "play none none reverse",
            },
          },
        );
      });

      // Animate framework section
      const devFrameworkSection = contentRef.current?.querySelector(
        `.${styles.devFrameworkSection}`,
      );
      if (devFrameworkSection) {
        gsap.fromTo(
          devFrameworkSection,
          { opacity: 0, y: 40 },
          {
            opacity: 1,
            y: 0,
            duration: 1.1,
            ease: "power2.out",
            scrollTrigger: {
              trigger: devFrameworkSection,
              start: "top 80%",
              toggleActions: "play none none reverse",
            },
          },
        );
      }

      // Animate framework buttons
      const frameworkButtons =
        contentRef.current?.querySelectorAll(`.${styles.devFrameworkButton}`) ||
        [];
      frameworkButtons.forEach((btn, idx) => {
        gsap.fromTo(
          btn,
          { opacity: 0, y: 15, scale: 0.95 },
          {
            opacity: 1,
            y: 0,
            scale: 1,
            duration: 0.7,
            ease: "power2.out",
            delay: idx * 0.08,
            scrollTrigger: {
              trigger: btn,
              start: "top 85%",
              toggleActions: "play none none reverse",
            },
          },
        );
      });

      // Animate code blocks
      const codeBlocks =
        contentRef.current?.querySelectorAll(
          `.${styles.devFrameworkCodeBlock}`,
        ) || [];
      codeBlocks.forEach((block, idx) => {
        gsap.fromTo(
          block,
          { opacity: 0, x: 30, scale: 0.98 },
          {
            opacity: 1,
            x: 0,
            scale: 1,
            duration: 0.95,
            ease: "power2.out",
            delay: idx * 0.12,
            scrollTrigger: {
              trigger: block,
              start: "top 83%",
              toggleActions: "play none none reverse",
            },
          },
        );
      });

      // Add professional hover animations to cards
      const allAnimatedCards =
        contentRef.current?.querySelectorAll(
          `.${styles.devFeatureCard}`,
        ) || [];
      allAnimatedCards.forEach((card: any) => {
        card.addEventListener("mouseenter", () => {
          gsap.to(card, {
            y: -6,
            scale: 1.02,
            boxShadow: "0 16px 32px rgba(0,0,0,0.12)",
            duration: 0.25,
            ease: "power2.out",
          });
        });
        card.addEventListener("mouseleave", () => {
          gsap.to(card, {
            y: 0,
            scale: 1,
            boxShadow: "0 4px 12px rgba(0,0,0,0.05)",
            duration: 0.25,
            ease: "power2.out",
          });
        });
      });

      // Add hover animations to framework buttons
      frameworkButtons.forEach((btn: any) => {
        btn.addEventListener("mouseenter", () => {
          gsap.to(btn, {
            scale: 1.05,
            duration: 0.15,
            ease: "power2.out",
          });
        });
        btn.addEventListener("mouseleave", () => {
          gsap.to(btn, {
            scale: 1,
            duration: 0.15,
            ease: "power2.out",
          });
        });
      });
    }, sectionRef);

    return () => {
      context.revert();
    };
  }, []);

  return (
    <Layout
      title="Agent Kernel for Developers"
      description="Learn how Agent Kernel helps developers build and deploy AI agents quickly without reinventing the wheel."
    >
      <HeroAnimation
        badge="Developers"
        title="Build AI Agents Without Rebuilding Infrastructure"
        subtitle="Agent Kernel gives developers a production-ready runtime so you can focus on agent logic. Use your preferred framework, expose agents through API or messaging channels, and deploy to cloud environments fast with enterprise-grade building blocks included."
      />
      <section ref={sectionRef} className={styles.devPageSection}>
        <StepTimeline levelId="02" contentRef={contentRef} />
        <div className="container">
          <div ref={contentRef} className={styles.developerContent}>
            {/* Step 01 — Developer Analogy */}
            <div
              className={`${styles.developerAnalogy} ${styles.developerBlock}`}
              data-step="dev-01"
            >
              <p className={styles.devStepLabel}>Developer Analogy</p>
              <h1 className={styles.devTitle}>
                Building blocks and deployment infrastructure for your AI
                Agent.
              </h1>
              <div className={styles.devDescription}>
                <p className={styles.devIntro}>
                  Agent Kernel is like the operating system for the AI
                  assistants, think Linux for your agents.
                </p>
                <div className={styles.devBulletList}>
                  <div className={styles.devBulletItem}>
                    <span className={styles.devBullet}>•</span>
                    <span className={styles.devBulletText}>
                      Install it on your laptop, server, or cloud and run AI
                      agents hassle-free.
                    </span>
                  </div>
                  <div className={styles.devBulletItem}>
                    <span className={styles.devBullet}>•</span>
                    <span className={styles.devBulletText}>
                      No need to build infrastructure, APIs, or messaging and
                      other integrations.
                    </span>
                  </div>
                  <div className={styles.devBulletItem}>
                    <span className={styles.devBullet}>•</span>
                    <span className={styles.devBulletText}>
                      Everything works out of the box.
                    </span>
                  </div>
                  <div className={styles.devBulletItem}>
                    <span className={styles.devBullet}>•</span>
                    <span className={styles.devBulletText}>
                      Scales from single execution to thousands of agent
                      invocations in parallel.
                    </span>
                  </div>
                  <div className={styles.devBulletItem}>
                    <span className={styles.devBullet}>•</span>
                    <span className={styles.devBulletText}>
                      Interacts with the real world automatically.
                    </span>
                  </div>
                  <div className={styles.devBulletItem}>
                    <span className={styles.devBullet}>•</span>
                    <span className={styles.devBulletText}>
                      Just define what your agent should do.
                    </span>
                  </div>
                </div>
              </div>
            </div>

            {/* Architecture flow — 8 stacked layers */}
            <div
              className={`${styles.architectureWrapper} ${styles.developerBlock}`}
              data-step="dev-02"
            >
              <div className={styles.architectureStack}>
                {[
                  {
                    num: "01",
                    label: "Your Agent Logic",
                    items: ["Instructions", "Tools", "Framework SDK"],
                  },
                  {
                    num: "02",
                    label: "Agent Kernel Runtime",
                    items: [
                      "Agents",
                      "Agent Runner",
                      "Session Management",
                      "Hooks",
                    ],
                  },
                  {
                    num: "03",
                    label: "Storage & Memory",
                    items: [
                      "In-Memory",
                      "Redis",
                      "DynamoDB",
                      "CosmosDB",
                      "Firestore",
                    ],
                  },
                  {
                    num: "04",
                    label: "Knowledge Bases",
                    items: ["ChromaDB", "Neo4j", "Starburst", "SQLDB"],
                  },
                  {
                    num: "05",
                    label: "Observability",
                    items: ["LangFuse", "OpenLLMetry"],
                  },
                  {
                    num: "06",
                    label: "Cloud Infrastructure",
                    items: [
                      "AWS Lambda",
                      "ECS",
                      "Azure Functions",
                      "Container Apps",
                      "GCP Cloud Run",
                      "GCP Cloud Run Functions",
                    ],
                  },
                  {
                    num: "07",
                    label: "Interfacing",
                    items: ["CLI", "MCP", "A2A", "REST API"],
                  },
                  {
                    num: "08",
                    label: "Channels",
                    items: [
                      "Slack",
                      "Teams",
                      "WhatsApp",
                      "Telegram",
                      "Messenger",
                      "Instagram",
                      "Gmail",
                    ],
                  },
                ].map((layer, i, arr) => (
                  <div
                    key={layer.label}
                    className={styles.architectureLayerGroup}
                  >
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
                                <span
                                  className={styles.layerSubSep}
                                  aria-hidden="true"
                                >
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
            <div className={styles.devFeatureSection} data-step="dev-03">
              <p className={styles.devFeatureLabel}>
                All Enterprise Features Available Free And Open-Source
              </p>
              <h2 className={styles.devFeatureTitle}>
                Focus on Agent Logic. We Handle the Rest.
              </h2>

              <div className={styles.devFeatureGroups}>
                {DEV_FEATURE_GROUPS.map((group) => (
                  <div key={group.title} className={styles.devFeatureGroup}>
                    <h3 className={styles.devFeatureGroupTitle}>
                      {group.title}
                    </h3>
                    <div
                      className={`${styles.devFeaturesGrid} ${
                        group.cols === 4
                          ? styles.devFeaturesGrid4
                          : styles.devFeaturesGrid3
                      }`}
                    >
                      {group.features.map((feature) => {
                        const IconComponent = feature.icon;
                        return (
                          <div
                            key={feature.title}
                            className={styles.devFeatureCard}
                          >
                            <div className={styles.devFeatureCardHeader}>
                              <div className={styles.devFeatureIconWrap}>
                                <IconComponent
                                  className={styles.devFeatureIcon}
                                  aria-hidden
                                />
                              </div>
                              <h4 className={styles.devFeatureCardTitle}>
                                {feature.title}
                              </h4>
                            </div>
                            <p className={styles.devFeatureCardBody}>
                              {feature.body}
                            </p>
                          </div>
                        );
                      })}
                    </div>
                  </div>
                ))}
              </div>
            </div>

            {/* Step 03 — Framework Selection */}
            <div
              className={`${styles.devFrameworkSection} ${styles.developerBlock}`}
              data-step="dev-04"
            >
              <p className={styles.devFrameworkLabel}>No lock-in. Your choice</p>
              <h2 className={styles.devFrameworkTitle}>
                Use The Framework You Prefer
              </h2>

              <div className={styles.devFrameworkContainer}>
                {/* Left Column - Body & Buttons */}
                <div className={styles.devFrameworkButtonsCol}>
                  <p className={styles.devFrameworkBody}>
                    Choose a supported framework that fits your team, while
                    Agent Kernel gives you a consistent production-ready layer
                    for deployment, APIs, sessions, and integrations.
                  </p>

                  <div className={styles.devFrameworkButtonsGroup}>
                    {[
                      { id: "openai", label: "OpenAI Agents" },
                      { id: "crewai", label: "CrewAI" },
                      { id: "langgraph", label: "LangGraph" },
                      { id: "adk", label: "Google ADK" },
                    ].map((fw) => (
                      <button
                        key={fw.id}
                        onClick={() => setSelectedFramework(fw.id)}
                        className={`${styles.devFrameworkButton} ${
                          selectedFramework === fw.id
                            ? styles.devFrameworkButtonActive
                            : ""
                        }`}
                      >
                        {fw.label}
                      </button>
                    ))}
                  </div>
                </div>

                {/* Right Column - Code Display */}
                <div className={styles.devFrameworkCodeCol}>
                  {selectedFramework === "openai" && (
                    <div className={styles.devFrameworkCodeBlock}>
                      <div className={styles.devFrameworkCodeHeader}>
                        <p className={styles.devFrameworkCodeLabel}>
                          Installation:
                        </p>
                        <button
                          onClick={() =>
                            copyToClipboard(
                              "pip install agentkernel[openai]",
                              "openai-install",
                            )
                          }
                          className={styles.devFrameworkCopyBtn}
                          title="Copy code"
                        >
                          {copiedCode === "openai-install"
                            ? "✓ Copied"
                            : "Copy"}
                        </button>
                      </div>
                      <pre className={styles.devFrameworkCodePre}>
                        <code>pip install agentkernel[openai]</code>
                      </pre>
                      <div className={styles.devFrameworkCodeHeader}>
                        <p className={styles.devFrameworkCodeLabel}>
                          Basic Usage:
                        </p>
                        <button
                          onClick={() =>
                            copyToClipboard(
                              `from agents import Agent as OpenAIAgent
from agentkernel.cli import CLI
from agentkernel.openai import OpenAIModule

agent = OpenAIAgent(
    name="assistant",
    instructions="You are a helpful assistant.",
)

OpenAIModule([agent])

if __name__ == "__main__":
    CLI.main()`,
                              "openai-usage",
                            )
                          }
                          className={styles.devFrameworkCopyBtn}
                          title="Copy code"
                        >
                          {copiedCode === "openai-usage"
                            ? "✓ Copied"
                            : "Copy"}
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
                      <Link
                        to="/docs/frameworks/openai"
                        className={styles.devFrameworkDocLink}
                      >
                        View Full Documentation →
                      </Link>
                    </div>
                  )}

                  {selectedFramework === "crewai" && (
                    <div className={styles.devFrameworkCodeBlock}>
                      <div className={styles.devFrameworkCodeHeader}>
                        <p className={styles.devFrameworkCodeLabel}>
                          Installation:
                        </p>
                        <button
                          onClick={() =>
                            copyToClipboard(
                              "pip install agentkernel[crewai]",
                              "crewai-install",
                            )
                          }
                          className={styles.devFrameworkCopyBtn}
                          title="Copy code"
                        >
                          {copiedCode === "crewai-install"
                            ? "✓ Copied"
                            : "Copy"}
                        </button>
                      </div>
                      <pre className={styles.devFrameworkCodePre}>
                        <code>pip install agentkernel[crewai]</code>
                      </pre>
                      <div className={styles.devFrameworkCodeHeader}>
                        <p className={styles.devFrameworkCodeLabel}>
                          Basic Usage:
                        </p>
                        <button
                          onClick={() =>
                            copyToClipboard(
                              `from crewai import Agent as CrewAgent
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
    CLI.main()`,
                              "crewai-usage",
                            )
                          }
                          className={styles.devFrameworkCopyBtn}
                          title="Copy code"
                        >
                          {copiedCode === "crewai-usage"
                            ? "✓ Copied"
                            : "Copy"}
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
                      <Link
                        to="/docs/frameworks/crewai"
                        className={styles.devFrameworkDocLink}
                      >
                        View Full Documentation →
                      </Link>
                    </div>
                  )}

                  {selectedFramework === "langgraph" && (
                    <div className={styles.devFrameworkCodeBlock}>
                      <div className={styles.devFrameworkCodeHeader}>
                        <p className={styles.devFrameworkCodeLabel}>
                          Installation:
                        </p>
                        <button
                          onClick={() =>
                            copyToClipboard(
                              "pip install agentkernel[langgraph]",
                              "langgraph-install",
                            )
                          }
                          className={styles.devFrameworkCopyBtn}
                          title="Copy code"
                        >
                          {copiedCode === "langgraph-install"
                            ? "✓ Copied"
                            : "Copy"}
                        </button>
                      </div>
                      <pre className={styles.devFrameworkCodePre}>
                        <code>pip install agentkernel[langgraph]</code>
                      </pre>
                      <div className={styles.devFrameworkCodeHeader}>
                        <p className={styles.devFrameworkCodeLabel}>
                          Basic Usage:
                        </p>
                        <button
                          onClick={() =>
                            copyToClipboard(
                              `from typing import TypedDict
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
    CLI.main()`,
                              "langgraph-usage",
                            )
                          }
                          className={styles.devFrameworkCopyBtn}
                          title="Copy code"
                        >
                          {copiedCode === "langgraph-usage"
                            ? "✓ Copied"
                            : "Copy"}
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
                      <Link
                        to="/docs/frameworks/langgraph"
                        className={styles.devFrameworkDocLink}
                      >
                        View Full Documentation →
                      </Link>
                    </div>
                  )}

                  {selectedFramework === "adk" && (
                    <div className={styles.devFrameworkCodeBlock}>
                      <div className={styles.devFrameworkCodeHeader}>
                        <p className={styles.devFrameworkCodeLabel}>
                          Installation:
                        </p>
                        <button
                          onClick={() =>
                            copyToClipboard(
                              "pip install agentkernel[adk]",
                              "adk-install",
                            )
                          }
                          className={styles.devFrameworkCopyBtn}
                          title="Copy code"
                        >
                          {copiedCode === "adk-install" ? "✓ Copied" : "Copy"}
                        </button>
                      </div>
                      <pre className={styles.devFrameworkCodePre}>
                        <code>pip install agentkernel[adk]</code>
                      </pre>
                      <div className={styles.devFrameworkCodeHeader}>
                        <p className={styles.devFrameworkCodeLabel}>
                          Basic Usage:
                        </p>
                        <button
                          onClick={() =>
                            copyToClipboard(
                              `from adk import Agent as ADKAgent
from agentkernel.cli import CLI
from agentkernel.adk import ADKModule

agent = ADKAgent(
    name="assistant",
    model="gemini-2.0-flash-exp",
    instructions="You are a helpful AI assistant",
)

ADKModule([agent])

if __name__ == "__main__":
    CLI.main()`,
                              "adk-usage",
                            )
                          }
                          className={styles.devFrameworkCopyBtn}
                          title="Copy code"
                        >
                          {copiedCode === "adk-usage" ? "✓ Copied" : "Copy"}
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
                      <Link
                        to="/docs/frameworks/google-adk"
                        className={styles.devFrameworkDocLink}
                      >
                        View Full Documentation →
                      </Link>
                    </div>
                  )}
                </div>
              </div>
            </div>

            {/* Step 04 — How Agent Kernel Fits In */}
            <div className={styles.devArchitectureSection} data-step="dev-05">
              <p className={styles.devStepLabel}>The complete picture</p>
              <h2 className={styles.devTitle}>How Agent Kernel Fits In</h2>

              <p className={styles.devFrameworkBody}>
                You write your AI agent's logic. Agent Kernel handles everything
                else: the infrastructure, the cloud deployment, memory, knowledge
                bases, hooks, observability & traceability, LLM cost tracking,
                the integrations so your agent is live and talking to real users
                in days.
              </p>

              <div className={styles.devArchitectureWrapper}>
                <AgentKernelArchDiagram />
              </div>
            </div>
          </div>
        </div>
      </section>
    </Layout>
  );
}
