from agentkernel.cli import CLI
from agentkernel.knowledgebase.chroma import ChromaManager
from agentkernel.knowledgebase.knowledgebuilder import KnowledgeBuilder
from agentkernel.openai import OpenAIModule, OpenAIToolBuilder
from agents import Agent

v_db = ChromaManager(
    persist_path="./Scratches/my_chroma_db",
    name="ChromaDB",
    description=(
        "Semantic vector store. Use for unstructured text, natural-language facts, "
        "and any data best retrieved by meaning rather than exact structure."
    ),
).add_schema(
    {
        "description": (
            "Semantic vector store. Use for unstructured text, natural-language facts, "
            "and any data best retrieved by meaning rather than exact structure."
        ),
        "store_payload": {
            "text": "string - the content to store",
            "source": "string - origin label (default: 'agent')",
        },
        "read_payload": {
            "query": "string - natural language search query",
            "limit": "int - max results to return",
        },
    }
)

knowledge_builder = KnowledgeBuilder([v_db])


def build_agent(description: str) -> Agent:
    instructions = f"""{description}

EXECUTION PROTOCOL:

1. SCHEMA FIRST - ONCE ONLY:
   Call get_schemas() exactly once at the very start of every session. Never call it again.
   The schema is your complete source of truth - backends, purposes, query formats, and constraints.

2. ROUTE:
   Read the backend description to match the user's intent to the correct backend.

3. BUILD THE QUERY:
   Construct the full search query string for ChromaDB.
   Never pass a key name like 'list_all' - always pass the real constructed query string.

4. EXECUTE:
   Call read_kb() or write_kb() with the fully constructed query string.
   Wait for the result before responding.

5. RESPOND:
   Answer strictly from the returned data. If empty, say no records were found.
"""
    return Agent(
        name="KB_Router_Agent",
        model="gpt-4o-mini",
        instructions=instructions,
        tools=OpenAIToolBuilder.bind(knowledge_builder.build()),
    )


AGENT_DESCRIPTION = """
You are a personal knowledge assistant.
You help users store and retrieve information in ChromaDB.

Always route to the ChromaDB backend first, execute the tool call, and return direct results.
"""

agent = build_agent(AGENT_DESCRIPTION)

OpenAIModule([agent])

if __name__ == "__main__":
    CLI.main()
