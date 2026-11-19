import React from 'react';
import Link from '@docusaurus/Link';
import { CodeSample, Tabs, type TabItem } from '@site/src/components/PersonaKit';
import styles from '@site/src/pages/persona.module.css';

/**
 * The first step of the developer page: pick a framework, and see the install command and the
 * whole agent file for it. The snippets are the ones in the quick start guide
 * (docs/docs/quick-start.md): keep the two in step.
 */

type Framework = {
  id: string;
  label: string;
  /** Packages to add, as passed to `uv add`. */
  packages: string;
  /** The model provider key the example needs. */
  key: string;
  agent: string;
  docs: string;
};

const FRAMEWORKS: Framework[] = [
  {
    id: 'openai',
    label: 'OpenAI Agents',
    packages: '"agentkernel[openai]"',
    key: 'OPENAI_API_KEY',
    agent: `from agents import Agent as OpenAIAgent
from agentkernel.cli import CLI
from agentkernel.openai import OpenAIModule

agent = OpenAIAgent(
    name="assistant",
    instructions="You are a helpful assistant.",
)

OpenAIModule([agent])

if __name__ == "__main__":
    CLI.main()`,
    docs: '/docs/frameworks/openai',
  },
  {
    id: 'langgraph',
    label: 'LangGraph',
    packages: '"agentkernel[langgraph]"',
    key: 'OPENAI_API_KEY',
    agent: `from typing import TypedDict
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
    docs: '/docs/frameworks/langgraph',
  },
  {
    id: 'crewai',
    label: 'CrewAI',
    packages: '"agentkernel[crewai]"',
    key: 'OPENAI_API_KEY',
    agent: `from crewai import Agent as CrewAgent
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
    docs: '/docs/frameworks/crewai',
  },
  {
    id: 'adk',
    label: 'Google ADK',
    packages: '"agentkernel[adk]"',
    key: 'GOOGLE_API_KEY',
    agent: `from adk import Agent as ADKAgent
from agentkernel.cli import CLI
from agentkernel.adk import GoogleADKModule

agent = ADKAgent(
    name="assistant",
    model="gemini-2.0-flash-exp",
    instructions="You are a helpful AI assistant",
)

GoogleADKModule([agent])

if __name__ == "__main__":
    CLI.main()`,
    docs: '/docs/frameworks/google-adk',
  },
  {
    id: 'claude',
    label: 'Claude Agent SDK',
    packages: '"agentkernel[claude]"',
    key: 'ANTHROPIC_API_KEY',
    agent: `from claude_agent_sdk import ClaudeAgentOptions
from agentkernel.claude import ClaudeAgentSpec, ClaudeModule
from agentkernel.cli import CLI

assistant = ClaudeAgentSpec(
    name="assistant",
    description="A helpful AI assistant.",
    options=ClaudeAgentOptions(
        model="sonnet",
        system_prompt="You are a helpful AI assistant.",
        tools=[],
        setting_sources=[],
        permission_mode="dontAsk",
    ),
)

ClaudeModule([assistant])

if __name__ == "__main__":
    CLI.main()`,
    docs: '/docs/frameworks/claude-agent-sdk',
  },
  {
    id: 'pydanticai',
    label: 'Pydantic AI',
    packages: '"agentkernel[pydanticai]" "pydantic-ai-slim[openai]"',
    key: 'OPENAI_API_KEY',
    agent: `from pydantic_ai import Agent
from agentkernel.cli import CLI
from agentkernel.pydanticai import PydanticAIModule

agent = Agent(
    model="openai:gpt-4o-mini",
    name="assistant",
    description="A helpful assistant.",
    instructions="You are a helpful assistant.",
)

PydanticAIModule([agent])

if __name__ == "__main__":
    CLI.main()`,
    docs: '/docs/frameworks/pydantic-ai',
  },
  {
    id: 'maf',
    label: 'Microsoft Agent Framework',
    packages: '"agentkernel[maf]" agent-framework-openai',
    key: 'OPENAI_API_KEY',
    agent: `from agent_framework import Agent
from agent_framework.openai import OpenAIChatClient
from agentkernel.cli import CLI
from agentkernel.maf import MAFModule

agent = Agent(
    OpenAIChatClient(model="gpt-4.1-mini"),
    name="assistant",
    description="A helpful assistant.",
    instructions="You are a helpful assistant.",
)

MAFModule([agent])

if __name__ == "__main__":
    CLI.main()`,
    docs: '/docs/frameworks/microsoft-agents',
  },
  {
    id: 'smolagents',
    label: 'Smolagents',
    packages: '"agentkernel[smolagents]"',
    key: 'OPENAI_API_KEY',
    agent: `from smolagents import LiteLLMModel, ToolCallingAgent
from agentkernel.cli import CLI
from agentkernel.smolagents import SmolagentsModule

model = LiteLLMModel(model_id="openai/gpt-4o")

assistant = ToolCallingAgent(
    tools=[],
    model=model,
    name="assistant",
    description="You are a helpful AI assistant",
)

SmolagentsModule([assistant])

if __name__ == "__main__":
    CLI.main()`,
    docs: '/docs/frameworks/smolagents',
  },
];

function FrameworkPanel({ framework }: { framework: Framework }): JSX.Element {
  const install = `uv init --python 3.12 my-agent
cd my-agent
uv add ${framework.packages}
export ${framework.key}=your-api-key-here`;
  return (
    <div className={styles.split}>
      <div className={styles.stack}>
        <CodeSample title="Terminal" language="bash">
          {install}
        </CodeSample>
        <p className="ak-body">
          Two lines of the file belong to OAK: the module line registers the agent with the runtime, and{' '}
          <code>CLI.main()</code> starts it. The rest is your framework's own code.
        </p>
        <Link to={framework.docs} className="ak-link">
          {framework.label} guide
        </Link>
      </div>
      <CodeSample title="my_agent.py" language="python">
        {framework.agent}
      </CodeSample>
    </div>
  );
}

const ITEMS: TabItem[] = FRAMEWORKS.map((framework) => ({
  id: framework.id,
  label: framework.label,
  content: <FrameworkPanel framework={framework} />,
}));

/** A tab per supported agent framework, each with its install command and a complete agent file. */
export default function FrameworkSelector(): JSX.Element {
  return <Tabs name="framework" label="Agent frameworks" items={ITEMS} />;
}
