"""
Open Knowledge Format knowledge base demo using Agent Kernel + OpenAI Agents SDK.

An OKF bundle is a directory of markdown concepts with YAML frontmatter. Because the knowledge
lives in files rather than a service, this demo needs no database and no credentials beyond an
OpenAI key -- ./bundle is the whole knowledge base.
"""

from agents import Agent
from agentkernel.cli import CLI
from agentkernel.knowledgebase import KnowledgeBuilder, LocalDocumentStore, OKFManager
from agentkernel.openai import OpenAIModule, OpenAIToolBuilder


# Step 1: Point the backend at the bundle. There is no add_schema() call anywhere in this file:
# OKFManager declares derives_schema=True and describes itself from what the bundle contains.
#
# writable=False because a bundle checked into git is a knowledge source, not a scratchpad. The
# store's writability folds into the backend's declaration, so this one keyword is what makes
# write_kb report the backend as read-only instead of adding files under bundle/generated/.
okf_backend = OKFManager(
    LocalDocumentStore("./bundle", writable=False),
    name="OKF",
    description=(
        "Open Knowledge Format bundle describing the analytics warehouse: one markdown concept "
        "per table and per upstream source system, organised into browsable namespaces."
    ),
)

# Step 2: Turn backend capabilities into callable KB tools.
#
# The semantic_map lets a namespace be referred to by a logical token, so the same agent
# instructions work against a bundle whose physical layout differs per environment.
knowledge_builder = KnowledgeBuilder([okf_backend], semantic_map={"<TABLES>": "tables"})


def build_agent(description: str) -> Agent:
    """Create the router agent and bind knowledge-base tools.

    The protocol below is written around browse/fetch rather than search, because a bundle is
    a navigable tree: listing a namespace and then reading a named concept beats guessing
    search terms.
    """

    instructions = f"""{description}

EXECUTION PROTOCOL:

1. SCHEMA FIRST - ONCE ONLY:
   Call get_schemas() exactly once at the very start of every session. Never call it again.
   The schema tells you the bundle's version, how many concepts it holds, which concept types
   exist, and which top-level namespaces you can browse.

2. NAVIGATE BEFORE YOU SEARCH:
   Call browse_kb() with an empty path to read the bundle's own front page, then browse a
   namespace such as <TABLES> to see what it holds. Browsing a namespace that has a curated
   listing returns that listing verbatim - trust it, it was written by a human.

3. READ THE CONCEPT:
   Call fetch_kb() with the exact concept path you saw while browsing, for example
   'tables/orders.md'. Only fetch_kb returns a concept's full body and its links to other
   concepts, so this is the step that actually answers the question.

4. SEARCH ONLY WHEN YOU CANNOT NAVIGATE:
   If browsing does not reveal the right concept, call read_kb() with the words you would
   expect to appear in it. Ranking is lexical, so use terms from the domain, not a sentence.

5. RESPOND:
   Answer from the concept you read, and name the concept path you took it from.
   Every result carries a trust signal: 'human-reviewed' was checked by a person,
   'machine-confirmed' by an automated check, 'unverified' by nobody. Say so when it matters.
   If nothing in the bundle covers the question, say so before answering from general knowledge.
"""

    # Step 3: build() produces framework-agnostic callables; bind(...) makes them OpenAI tools.
    #
    # Six tools here, not seven. fetch_kb and browse_kb exist because this backend declares
    # fetch and browse; search_kb does not, because its gate needs a backend declaring both
    # search and query, and an OKF bundle has no query language. read_kb reaches search()
    # directly, so nothing is lost.
    return Agent(
        name="KB_Router_Agent",
        model="gpt-4o-mini",
        instructions=instructions,
        tools=OpenAIToolBuilder.bind(knowledge_builder.build()),
    )


AGENT_DESCRIPTION = """
You are an analytics knowledge assistant.
You answer questions about the data warehouse from an Open Knowledge Format bundle.

The bundle is the source of truth. Browse it, read the concept that answers the question, and
cite the concept path you used.
"""

# Step 4: Create and register the agent in the OpenAI module runtime.
agent = build_agent(AGENT_DESCRIPTION)
OpenAIModule([agent])


if __name__ == "__main__":
    # Step 5: Launch interactive CLI chat.
    CLI.main()
