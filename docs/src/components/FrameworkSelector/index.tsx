import React, { useState } from "react";
import Link from "@docusaurus/Link";
import styles from "./styles.module.css";

interface FrameworkSelectorProps {
  showTitle?: boolean;
  showDescription?: boolean;
  accentColor?: string;
}

const FRAMEWORKS = [
  { id: "openai",    label: "OpenAI Agents" },
  { id: "crewai",   label: "CrewAI"         },
  { id: "langgraph", label: "LangGraph"     },
  { id: "adk",      label: "Google ADK"     },
];

const FRAMEWORK_DATA = {
  openai: {
    installation: `# 1. Install the CLI\npip install agentkernel[openai]`,
    usage: `from agents import Agent as OpenAIAgent\nfrom agentkernel.cli import CLI\nfrom agentkernel.openai import OpenAIModule\n\nagent = OpenAIAgent(\n    name="assistant",\n    instructions="You are a helpful assistant.",\n)\n\nOpenAIModule([agent])\n\nif __name__ == "__main__":\n    CLI.main()`,
    docLink: "/docs/frameworks/openai",
  },
  crewai: {
    installation: `# 1. Install the CLI\npip install agentkernel[crewai]`,
    usage: `from crewai import Agent as CrewAgent\nfrom agentkernel.cli import CLI\nfrom agentkernel.crewai import CrewAIModule\n\nagent = CrewAgent(\n    role="assistant",\n    goal="Help users with their questions",\n    backstory="You are a helpful AI assistant",\n    verbose=False,\n)\n\nCrewAIModule([agent])\n\nif __name__ == "__main__":\n    CLI.main()`,
    docLink: "/docs/frameworks/crewai",
  },
  langgraph: {
    installation: `# 1. Install the CLI\npip install agentkernel[langgraph]`,
    usage: `from typing import TypedDict\nfrom langgraph.graph import StateGraph, END\nfrom agentkernel.cli import CLI\nfrom agentkernel.langgraph import LangGraphModule\n\nclass State(TypedDict):\n    messages: list\n\ndef agent_node(state: State):\n    return {"messages": state["messages"] + ["response"]}\n\nworkflow = StateGraph(State)\nworkflow.add_node("agent", agent_node)\nworkflow.set_entry_point("agent")\nworkflow.add_edge("agent", END)\n\ngraph = workflow.compile()\ngraph.name = "assistant"\n\nLangGraphModule([graph])\n\nif __name__ == "__main__":\n    CLI.main()`,
    docLink: "/docs/frameworks/langgraph",
  },
  adk: {
    installation: `# 1. Install the CLI\npip install agentkernel[adk]`,
    usage: `from adk import Agent as ADKAgent\nfrom agentkernel.cli import CLI\nfrom agentkernel.adk import ADKModule\n\nagent = ADKAgent(\n    name="assistant",\n    model="gemini-2.0-flash-exp",\n    instructions="You are a helpful AI assistant",\n)\n\nADKModule([agent])\n\nif __name__ == "__main__":\n    CLI.main()`,
    docLink: "/docs/frameworks/google-adk",
  },
};

/* ─── Minimal Python syntax tokeniser ──────────────────────────────────────── */
type TokenType = "keyword" | "builtin" | "string" | "comment" | "number" | "operator" | "plain";
interface Token { type: TokenType; value: string }

const PY_KEYWORDS = new Set([
  "from","import","as","def","class","return","if","else","elif","for",
  "while","in","not","and","or","True","False","None","with","pass",
  "raise","try","except","finally","lambda","yield","del","global",
  "nonlocal","assert","break","continue","__name__","__main__",
]);

function tokeniseLine(line: string): Token[] {
  const tokens: Token[] = [];
  let i = 0;
  while (i < line.length) {
    if (line[i] === "#") { tokens.push({ type: "comment", value: line.slice(i) }); break; }
    if (line[i] === '"' || line[i] === "'") {
      const q = line[i]; let j = i + 1;
      while (j < line.length && line[j] !== q) { if (line[j] === "\\") j++; j++; }
      tokens.push({ type: "string", value: line.slice(i, j + 1) });
      i = j + 1; continue;
    }
    if (/[0-9]/.test(line[i])) {
      let j = i;
      while (j < line.length && /[0-9._]/.test(line[j])) j++;
      tokens.push({ type: "number", value: line.slice(i, j) });
      i = j; continue;
    }
    if (/[a-zA-Z_]/.test(line[i])) {
      let j = i;
      while (j < line.length && /[a-zA-Z0-9_]/.test(line[j])) j++;
      const word = line.slice(i, j);
      tokens.push({ type: PY_KEYWORDS.has(word) ? "keyword" : "plain", value: word });
      i = j; continue;
    }
    if (/[=\+\-\*\/\(\)\[\]\{\}:,\.<>!]/.test(line[i])) {
      tokens.push({ type: "operator", value: line[i] }); i++; continue;
    }
    tokens.push({ type: "plain", value: line[i] }); i++;
  }
  return tokens;
}

function CodeWithLines({ code }: { code: string }) {
  const lines = code.split("\n");
  return (
    <table className={styles.codeTable}>
      <tbody>
        {lines.map((line, idx) => (
          <tr key={idx} className={styles.codeLine}>
            <td className={styles.lineNumber}>{idx + 1}</td>
            <td className={styles.lineContent}>
              {tokeniseLine(line).map((tok, ti) => (
                <span key={ti} className={styles[`tok_${tok.type}`]}>{tok.value}</span>
              ))}
              {line === "" && "\u00A0"}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function TrafficLights() {
  return (
    <div className={styles.trafficLights}>
      <span className={`${styles.dot} ${styles.dotRed}`} />
      <span className={`${styles.dot} ${styles.dotYellow}`} />
      <span className={`${styles.dot} ${styles.dotGreen}`} />
    </div>
  );
}

function ToolbarIcons() {
  return (
    <div className={styles.toolbarIcons}>
      <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
        <rect x="1" y="1" width="5" height="12" rx="1" stroke="currentColor" strokeWidth="1.2"/>
        <rect x="8" y="1" width="5" height="5"  rx="1" stroke="currentColor" strokeWidth="1.2"/>
        <rect x="8" y="8" width="5" height="5"  rx="1" stroke="currentColor" strokeWidth="1.2"/>
      </svg>
      <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
        <rect x="1" y="1" width="5" height="12" rx="1" stroke="currentColor" strokeWidth="1.2"/>
        <rect x="8" y="1" width="5" height="12" rx="1" stroke="currentColor" strokeWidth="1.2"/>
      </svg>
      <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
        <path d="M11.5 9A5 5 0 1 1 5 2.5a4 4 0 0 0 6.5 6.5z" stroke="currentColor" strokeWidth="1.2" strokeLinejoin="round"/>
      </svg>
      <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
        <path d="M7 1v2M7 11v2M1 7h2M11 7h2M2.93 2.93l1.41 1.41M9.66 9.66l1.41 1.41M2.93 11.07l1.41-1.41M9.66 4.34l1.41-1.41"
          stroke="currentColor" strokeWidth="1.2" strokeLinecap="round"/>
      </svg>
    </div>
  );
}

export default function FrameworkSelector({
  showTitle       = true,
  showDescription = true,
  accentColor     = "#CC7D21",
}: FrameworkSelectorProps) {
  const [selectedFramework, setSelectedFramework] = useState<string>("openai");
  const [copiedCode, setCopiedCode]               = useState<string | null>(null);

  const copyToClipboard = (code: string, id: string) => {
    navigator.clipboard.writeText(code);
    setCopiedCode(id);
    setTimeout(() => setCopiedCode(null), 2000);
  };

  const fw = FRAMEWORK_DATA[selectedFramework as keyof typeof FRAMEWORK_DATA];
  const accentRgb = hexToRgb(accentColor);
  const cssVars = {
    "--accent":    accentColor,
    "--accent-10": `rgba(${accentRgb}, 0.10)`,
    "--accent-15": `rgba(${accentRgb}, 0.15)`,
    "--accent-40": `rgba(${accentRgb}, 0.40)`,
    "--accent-60": `rgba(${accentRgb}, 0.60)`,
  } as React.CSSProperties;

  return (
    <div className={styles.frameworkContainer} style={cssVars}>
      {showTitle && (
        <h2 className={styles.frameworkTitle}>Choose Your Framework</h2>
      )}
      {showDescription && (
        <p className={styles.frameworkBody}>
          Choose a supported framework that fits your team, while Agent Kernel
          gives you a consistent production-ready layer for deployment, APIs,
          sessions, and integrations.
        </p>
      )}

      {/* ── Centered pill buttons ── */}
      <div className={styles.frameworkButtons}>
        {FRAMEWORKS.map((f) => (
          <button
            key={f.id}
            onClick={() => setSelectedFramework(f.id)}
            className={`${styles.frameworkButton} ${
              selectedFramework === f.id ? styles.frameworkButtonActive : ""
            }`}
          >
            {f.label}
          </button>
        ))}
      </div>

      {/* ── Two-column cards ── */}
      <div className={styles.frameworkContent}>

        {/* Left — Installation */}
        <div className={styles.codeCard}>
          <div className={styles.codeCardHeader}>
            <span className={styles.codeCardLabel}>Installation:</span>
            <button
              onClick={() => copyToClipboard(fw.installation, `${selectedFramework}-install`)}
              className={styles.copyBtn}
            >
              {copiedCode === `${selectedFramework}-install` ? "✓ Copied" : "Copy"}
            </button>
          </div>
          <div className={styles.macWindow}>
            <div className={styles.macTitleBar}>
              <TrafficLights />
              <ToolbarIcons />
            </div>
            <div className={styles.editorBody}>
              <CodeWithLines code={fw.installation} />
            </div>
          </div>
          <Link to={fw.docLink} className={styles.docLink}>
            View Full Documentation →
          </Link>
        </div>

        {/* Right — Basic Usage */}
        <div className={styles.codeCard}>
          <div className={styles.codeCardHeader}>
            <span className={styles.codeCardLabel}>Basic Usage:</span>
            <button
              onClick={() => copyToClipboard(fw.usage, `${selectedFramework}-usage`)}
              className={styles.copyBtn}
            >
              {copiedCode === `${selectedFramework}-usage` ? "✓ Copied" : "Copy"}
            </button>
          </div>
          <div className={styles.macWindow}>
            <div className={styles.macTitleBar}>
              <TrafficLights />
              <ToolbarIcons />
            </div>
            <div className={styles.editorBody}>
              <CodeWithLines code={fw.usage} />
            </div>
          </div>
        </div>

      </div>
    </div>
  );
}

function hexToRgb(hex: string): string {
  const c = hex.replace("#", "");
  return [0, 2, 4].map((i) => parseInt(c.slice(i, i + 2), 16)).join(", ");
}