import React, { useState } from "react";
import Link from "@docusaurus/Link";
import styles from "./styles.module.css";

interface FrameworkSelectorProps {
  showTitle?: boolean;
  showDescription?: boolean;
}

const FRAMEWORKS = [
  { id: "openai", label: "OpenAI Agents" },
  { id: "crewai", label: "CrewAI" },
  { id: "langgraph", label: "LangGraph" },
  { id: "adk", label: "Google ADK" },
];

const FRAMEWORK_DATA = {
  openai: {
    installation: "pip install agentkernel[openai]",
    usage: `from agents import Agent as OpenAIAgent
from agentkernel.cli import CLI
from agentkernel.openai import OpenAIModule

agent = OpenAIAgent(
    name="assistant",
    instructions="You are a helpful assistant.",
)

OpenAIModule([agent])

if __name__ == "__main__":
    CLI.main()`,
    docLink: "/docs/frameworks/openai",
  },
  crewai: {
    installation: "pip install agentkernel[crewai]",
    usage: `from crewai import Agent as CrewAgent
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
    docLink: "/docs/frameworks/crewai",
  },
  langgraph: {
    installation: "pip install agentkernel[langgraph]",
    usage: `from typing import TypedDict
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
    docLink: "/docs/frameworks/langgraph",
  },
  adk: {
    installation: "pip install agentkernel[adk]",
    usage: `from adk import Agent as ADKAgent
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
    docLink: "/docs/frameworks/google-adk",
  },
};

export default function FrameworkSelector({
  showTitle = true,
  showDescription = true,
}: FrameworkSelectorProps) {
  const [selectedFramework, setSelectedFramework] = useState<string>("openai");
  const [copiedCode, setCopiedCode] = useState<string | null>(null);

  const copyToClipboard = (code: string, id: string) => {
    navigator.clipboard.writeText(code);
    setCopiedCode(id);
    setTimeout(() => setCopiedCode(null), 2000);
  };

  const currentFramework =
    FRAMEWORK_DATA[selectedFramework as keyof typeof FRAMEWORK_DATA];

  return (
    <div className={styles.frameworkContainer}>
      {showTitle && <h2 className={styles.frameworkTitle}>Choose Your Framework</h2>}
      {showDescription && (
        <p className={styles.frameworkBody}>
          Choose a supported framework that fits your team, while Agent Kernel
          gives you a consistent production-ready layer for deployment, APIs,
          sessions, and integrations.
        </p>
      )}

      <div className={styles.frameworkContent}>
        {/* Left Column - Buttons */}
        <div className={styles.frameworkButtonsCol}>
          <div className={styles.frameworkButtonsGroup}>
            {FRAMEWORKS.map((fw) => (
              <button
                key={fw.id}
                onClick={() => setSelectedFramework(fw.id)}
                className={`${styles.frameworkButton} ${
                  selectedFramework === fw.id
                    ? styles.frameworkButtonActive
                    : ""
                }`}
              >
                {fw.label}
              </button>
            ))}
          </div>
        </div>

        {/* Right Column - Code Display */}
        <div className={styles.frameworkCodeCol}>
          <div className={styles.frameworkCodeBlock}>
            <div className={styles.frameworkCodeHeader}>
              <p className={styles.frameworkCodeLabel}>Installation:</p>
              <button
                onClick={() =>
                  copyToClipboard(
                    currentFramework.installation,
                    `${selectedFramework}-install`
                  )
                }
                className={styles.frameworkCopyBtn}
                title="Copy code"
              >
                {copiedCode === `${selectedFramework}-install`
                  ? "✓ Copied"
                  : "Copy"}
              </button>
            </div>
            <pre className={styles.frameworkCodePre}>
              <code>{currentFramework.installation}</code>
            </pre>

            <div className={styles.frameworkCodeHeader}>
              <p className={styles.frameworkCodeLabel}>Basic Usage:</p>
              <button
                onClick={() =>
                  copyToClipboard(
                    currentFramework.usage,
                    `${selectedFramework}-usage`
                  )
                }
                className={styles.frameworkCopyBtn}
                title="Copy code"
              >
                {copiedCode === `${selectedFramework}-usage`
                  ? "✓ Copied"
                  : "Copy"}
              </button>
            </div>
            <pre className={styles.frameworkCodePre}>
              <code>{currentFramework.usage}</code>
            </pre>

            <Link
              to={currentFramework.docLink}
              className={styles.frameworkDocLink}
            >
              View Full Documentation →
            </Link>
          </div>
        </div>
      </div>
    </div>
  );
}
