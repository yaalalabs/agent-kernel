"""
Neo4j knowledge base demo using Agent Kernel + OpenAI Agents SDK.


"""

from agents import Agent
from agentkernel.cli import CLI
from agentkernel.knowledgebase.knowledgebuilder import KnowledgeBuilder
from agentkernel.knowledgebase.neo4j import Neo4jManager
from agentkernel.openai import OpenAIModule, OpenAIToolBuilder


# Step 1: Configure Neo4j and describe exactly how reads/writes should be built.
neo4j_backend = Neo4jManager(
    name="Neo4jDB",
    description=(
        "Neo4j graph database. Use for entities, relationships, and structured facts. "
        "Supports raw Cypher queries for precise lookups."
    ),
).add_schema(
    {
        "description": (
            "Neo4j graph database. Use for entities, relationships, and structured facts. "
            "Supports raw Cypher queries for precise lookups."
        ),
        "store_payload": {
            "text": "string - human-readable description of the fact",
            "source": "string - origin label (default: 'agent')",
            "cypher_query": "(optional) Cypher string to execute for creating nodes/relationships",
            "cypher_params_json": "(optional) JSON-stringified params for the Cypher query",
        },
        "read_payload": {
            "query": "string - a valid Cypher query only",
            "limit": "int - max results",
        },
        "query_generation_guide": {
            "rules": [
                "Use Cypher only for read_kb and write_kb.",
                "Prefer parameterized queries.",
                "For list queries, return all matches unless user asks to limit.",
                "For person-name matching, use case-insensitive comparisons with toLower().",
                "For friendship checks, use undirected pattern: (a)-[:FRIENDS_WITH]-(b).",
                "Use the exact relationship type FRIENDS_WITH only. Never use FRIEND, FRIENDSHIP, or FRIEND_OF.",
                "For add/create friendship writes, use MERGE for both Person nodes and MERGE for the relationship.",
                "Never use MATCH for both nodes in create flows, because missing nodes cause zero-row writes.",
            ],
            "labels": ["Person", "MemoryNote", "CypherFact"],
            "relationship": "FRIENDS_WITH (exact label only)",
            "read_examples": {
                "list_friends": "MATCH (p:Person)-[:FRIENDS_WITH]-(f:Person) WHERE toLower(p.name) = toLower($person) RETURN DISTINCT f.name AS friend ORDER BY friend",
                "check_friendship": "MATCH (a:Person)-[:FRIENDS_WITH]-(b:Person) WHERE toLower(a.name) = toLower($a) AND toLower(b.name) = toLower($b) RETURN COUNT(*) > 0 AS are_friends",
            },
            "write_examples": {
                "add_friendship": "MERGE (a:Person {name: $person}) MERGE (b:Person {name: $friend}) MERGE (a)-[:FRIENDS_WITH]->(b)",
                "verify_friendship": "MATCH (a:Person)-[:FRIENDS_WITH]-(b:Person) WHERE toLower(a.name)=toLower($person) AND toLower(b.name)=toLower($friend) RETURN COUNT(*) > 0 AS added",
            },
        },
    }
)

# Step 2: Turn Neo4j capabilities into reusable KB tools.
knowledge_builder = KnowledgeBuilder([neo4j_backend])


def build_agent(description: str) -> Agent:
    """Create the router agent and attach Neo4j knowledge tools."""

    instructions = f"""{description}

EXECUTION PROTOCOL:

1. SCHEMA FIRST - ONCE ONLY:
   Call get_schemas() exactly once at the very start of every session. Never call it again.
   The schema is your complete source of truth - backends, purposes, query formats, and constraints.

2. ROUTE:
   Read the backend description to match the user's intent to the correct backend.

3. BUILD THE QUERY:
   Find the query_guide or examples section for Neo4j in the schema.
   Construct the full Cypher query string by following those templates exactly.
   Never pass a key name like 'list_all' - always pass the real constructed query string.

4. EXECUTE:
   Call read_kb() or write_kb() with the fully constructed query string.
   Wait for the result before responding.

5. RESPOND:
   Answer strictly from the returned data. If empty, say no records were found.
"""
    # Step 3: build() creates callables and bind(...) adapts them to OpenAI tools.
    knowledge_tools = knowledge_builder.build()
    return Agent(
        name="KB_Router_Agent",
        model="gpt-4o-mini",
        instructions=instructions,
        tools=OpenAIToolBuilder.bind(knowledge_tools),
    )


AGENT_DESCRIPTION = """
You are a personal knowledge assistant.
You help users store and retrieve information in Neo4jDB.

Always route to the Neo4jDB backend first, execute the tool call, and return direct results.
"""

# Step 4: Register the configured agent in the OpenAI runtime module.
agent = build_agent(AGENT_DESCRIPTION)
OpenAIModule([agent])

if __name__ == "__main__":
    try:
        # Step 5: Start CLI for interactive prompts.
        CLI.main()
    finally:
        # Always close Neo4j driver resources before exit.
        neo4j_backend.close()
