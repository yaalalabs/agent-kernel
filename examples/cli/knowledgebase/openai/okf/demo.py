"""
Open Knowledge Format knowledge base demo using Agent Kernel + OpenAI Agents SDK.

An OKF bundle is a directory of markdown concepts with YAML frontmatter. Because the knowledge
lives in files rather than a service, this demo needs no database and no credentials beyond an
OpenAI key -- ./bundle is the whole knowledge base.

Look at what is *not* in this file. There is no import from agentkernel.knowledgebase: no
document store, no OKFManager, no KnowledgeBuilder, no tool binding, and no instructions
explaining how to navigate a bundle. All of it comes from the `okf` block in config.yaml, which
names these three agents. Agent Kernel gives each one the tools its role allows and appends the
navigation protocol to its prompt.

The three agents differ only in what they are for. Consumer reads. Producer adds new knowledge.
Curator maintains what is already there. Producer and curator have identical permissions -- the
difference is responsibility, and it arrives as a different sentence in the prompt.
"""

from agents import Agent
from agentkernel.cli import CLI
from agentkernel.openai import OpenAIModule

# Every name below must match config.yaml exactly. An agent the block does not name simply gets
# no knowledge-base tools -- there is no error to notice, so the names are the contract.

consumer = Agent(
    name="kb_consumer_agent",
    model="gpt-4o-mini",
    instructions=(
        "You are an analytics knowledge assistant. You answer questions about the data warehouse "
        "from the knowledge base, and you cite the concept path you took each answer from. "
        "If the bundle does not cover a question, say so before answering from general knowledge."
    ),
)

producer = Agent(
    name="kb_producer_agent",
    model="gpt-4o-mini",
    instructions=(
        "You are an analytics knowledge author. When you learn something about the warehouse that "
        "the knowledge base does not already record, write it down as a new concept. Check first "
        "that it is genuinely new, and write one fact per concept."
    ),
)

curator = Agent(
    name="kb_curator_agent",
    model="gpt-4o-mini",
    instructions=(
        "You are an analytics knowledge curator. You review what the knowledge base already holds, "
        "correct what is wrong, and bring what is out of date up to date. Read the existing concept "
        "before you change it, and say what you changed and why."
    ),
)

OpenAIModule([consumer, producer, curator])


if __name__ == "__main__":
    CLI.main()
