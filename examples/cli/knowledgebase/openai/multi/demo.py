"""
Multi-backend knowledge base demo with OpenAI Agents SDK.

This is the most complete KB router example in this folder. It combines:
- ChromaDB (semantic vector search)
- Neo4j (graph relationships)
- Starburst Mongo source (SQL read-only)
- Starburst Sheets source (SQL read-only)

"""

from agents import Agent
from agentkernel.cli import CLI
from agentkernel.knowledgebase.chroma import ChromaManager
from agentkernel.knowledgebase.knowledgebuilder import KnowledgeBuilder
from agentkernel.knowledgebase.neo4j import Neo4jManager
from agentkernel.knowledgebase.starburst import StarburstManager
from agentkernel.openai import OpenAIModule, OpenAIToolBuilder


# Step 1a: Semantic vector backend for unstructured knowledge.
chroma_backend = ChromaManager(
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

# Step 1b: Graph backend for entities and relationships.
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

# Step 1c: Starburst backend for Mongo client records.
mongo_starburst_backend = StarburstManager(
    name="StarburstDB-mongo",
    host="name-mongocluster.trino.galaxy.starburst.io",
    catalog="catalog name",
    schema="schema name",
    table_name="clients",
    description=(
        "Starburst Galaxy read-only backend - MongoDB via Trino. "
        "Contains client records. "
        "Query syntax is defined strictly in the query_guide - follow it exactly."
        "use the placeholder <MONGO_SOURCE> in your queries as defined in the schema. NEVER use any other name, table name or path."
    ),
).add_schema(
    {
        "description": (
            "Starburst Galaxy read-only SQL backend - MongoDB via Trino. "
            "Use this for any question about clients or people stored in MongoDB."
        ),
        "table": {
            "columns": ["client_name", "status", "budget"],
            "IMPORTANT": "This is the ONLY table. NEVER use any other table name. Always use <MONGO_SOURCE> as the FROM target.",
        },
        "query_guide": {
            "list_all": "SELECT * FROM <MONGO_SOURCE> LIMIT 10",
            "search": "SELECT * FROM <MONGO_SOURCE> WHERE LOWER(client_name) LIKE '%keyword%' LIMIT 5",
            "inspect": "DESCRIBE <MONGO_SOURCE>",
            "MANDATORY_QUERY_SYNTAX": (
                "Every query MUST use <MONGO_SOURCE> as the FROM target exactly as shown in the examples. "
                "No other table name or path is valid for this backend."
            ),
        },
        "constraints": {
            "write_supported": False,
            "allowed_sql": ["SELECT", "SHOW", "DESCRIBE"],
        },
    }
)

# Step 1d: Starburst backend for Google Sheets knowledge.
sheets_starburst_backend = StarburstManager(
    name="StarburstDB_Sheets",
    host="name-free-cluster.trino.galaxy.starburst.io",
    catalog="catalog name",
    description=(
        "Starburst Galaxy read-only backend - Google Sheets via Trino. "
        "Contains company knowledge: topics, policies, tech info, department notes. "
        "Query syntax is defined strictly in the query_guide - follow it exactly."
        "use the placeholder <SHEETS_SOURCE> in your queries as defined in the schema. NEVER use any other name, table name or path."
    ),
).add_schema(
    {
        "description": (
            "Starburst Galaxy read-only backend - Google Sheets via Trino. "
            "Use this for general company knowledge, topics, policies, and tech information."
        ),
        "sources": {
            "columns": ["topic", "information", "department"],
            "IMPORTANT": "ONLY these 3 columns exist: topic, information, department. NEVER use any other column.",
        },
        "query_guide": {
            "list_all": "SELECT * FROM <SHEETS_SOURCE> LIMIT 10",
            "search": "SELECT * FROM <SHEETS_SOURCE> WHERE LOWER(CAST(topic AS VARCHAR)) LIKE '%keyword%' OR LOWER(CAST(information AS VARCHAR)) LIKE '%keyword%' LIMIT 5",
            "MANDATORY_QUERY_SYNTAX": (
                "Every query MUST use <SHEETS_SOURCE> as the FROM target exactly as shown in the examples. "
                "No other table name, schema, or path is valid for this backend. "
                "Always search BOTH topic AND information columns using OR when filtering."
            ),
        },
        "constraints": {
            "write_supported": False,
            "allowed_sql": ["SELECT", "SHOW", "DESCRIBE"],
            "columns": ["topic", "information", "department"],
        },
    }
)

# Step 2: Combine all backends and map semantic placeholders to physical sources.
knowledge_builder = KnowledgeBuilder(
    [
        chroma_backend,
        neo4j_backend,
        mongo_starburst_backend,
        sheets_starburst_backend,
    ],
    semantic_map={
        "<SHEETS_SOURCE>": "TABLE(kb_sheets.system.sheet(id => 'put your sheet id here'))",
        "<MONGO_SOURCE>": "put your MongoDB source path here (eg: mongodb.default.clients)",
    },
)


def build_agent(description: str) -> Agent:
    """Create one router agent and attach all available KB tools."""

    instructions = f"""{description}

EXECUTION PROTOCOL:

1. SCHEMA FIRST - ONCE ONLY:
   Call get_schemas() exactly once at the very start of every session. Never call it again.
   The schema is your complete source of truth - backends, purposes, query formats, and constraints.

2. ROUTE:
   Read each backend's description to match the user's intent to the correct backend.

3. BUILD THE QUERY:
   Find the query_guide or examples section for your chosen backend in the schema.
   Construct the full executable query string by following those templates exactly.
   Substitute user values into the template where needed.
   Never pass a key name like 'list_all' - always pass the real constructed query string.
   Use only the placeholder tokens, column names, relationship types, and syntax patterns
   defined in the schema. Never substitute from general knowledge or common conventions.

4. EXECUTE:
   Call read_kb() or write_kb() with the fully constructed query string.
   Wait for the result before responding.

5. RESPOND:
   Answer strictly from the returned data. If empty, say no records were found.
"""
    # Step 3: Build KB callables and bind them into OpenAI tool definitions.
    knowledge_tools = knowledge_builder.build()
    return Agent(
        name="KB_Router_Agent",
        model="gpt-4o-mini",
        instructions=instructions,
        tools=OpenAIToolBuilder.bind(knowledge_tools),
    )


AGENT_DESCRIPTION = """
You are a personal knowledge assistant.
You help users store and retrieve information across multiple databases:
- Neo4jDB: for entities and relationships (people, companies, places)
- ChromaDB: for unstructured text and semantic recall
- StarburstDB-mongo: for structured client data in MongoDB
- StarburstDB_Sheets: for company knowledge stored in Google Sheets

Always route to one backend first, execute the tool call, and return direct results.
"""

# Step 4: Register the router agent in OpenAIModule.
agent = build_agent(AGENT_DESCRIPTION)
OpenAIModule([agent])

if __name__ == "__main__":
    try:
        # Step 5: Start the interactive CLI session.
        CLI.main()
    finally:
        # Close networked backends so sessions do not leak resources.
        neo4j_backend.close()
        mongo_starburst_backend.close()
        sheets_starburst_backend.close()
