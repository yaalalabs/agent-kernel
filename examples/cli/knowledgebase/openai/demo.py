from agentkernel.cli import CLI
from agentkernel.knowledgebase.chroma_kb import ChromaManager
from agentkernel.knowledgebase.knowledgebuilder import KnowledgeBuilder
from agentkernel.knowledgebase.neo4j_kb import Neo4jManager
from agentkernel.knowledgebase.starburst_kb import StarburstManager
from agentkernel.openai import OpenAIModule, OpenAIToolBuilder
from agents import Agent

# vector database for semantic recall
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
            "text": "string — the content to store",
            "source": "string — origin label (default: 'agent')",
        },
        "read_payload": {
            "query": "string — natural language search query",
            "limit": "int — max results to return",
        },
    }
)

# graph database for entities and relationships
g_db = Neo4jManager(
    name="Neo4jDB",
    description="Neo4j graph database. Use for entities, relationships, and structured facts. Supports raw Cypher queries for precise lookups.",
).add_schema(
    {
        "description": (
            "Neo4j graph database. Use for entities, relationships, and structured facts. "
            "Supports raw Cypher queries for precise lookups."
        ),
        "store_payload": {
            "text": "string — human-readable description of the fact",
            "source": "string — origin label (default: 'agent')",
            "cypher_query": "(optional) Cypher string to execute for creating nodes/relationships",
            "cypher_params_json": "(optional) JSON-stringified params for the Cypher query",
        },
        "read_payload": {
            "query": "string — natural language question OR a valid Cypher query",
            "limit": "int — max results",
        },
        "query_generation_guide": {
            "goal": "Help LLM generate valid Cypher for this KB.",
            "known_internal_labels": ["MemoryNote", "CypherFact"],
            "domain_labels_examples": ["Person", "Car", "Company", "Place", "Thing"],
            "common_properties": ["name", "model", "title", "text", "source"],
            "relationship_pattern": "(a)-[r]->(b)",
            "cypher_best_practices": [
                "Prefer parameterized queries (use $name, $value, etc.).",
                "Use OPTIONAL MATCH when relationships may not exist.",
            ],
            "write_query_template": "MERGE (a:Person {name: $person}) "
            "MERGE (b:Person {name: $friend}) "
            "MERGE (a)-[:FRIENDS_WITH]->(b)"
            "use above templeate to write friend relationship between two people.",
        },
    }
)

# Starburst settings (edit these directly; no shell export required)
STARBURST_CATALOG = "kb_mongo"
STARBURST_SHEET_ID = "1ND7S86ni14J-0hVYIrBs3zIUPMkKoT0YGmvyLLHhDDY"
STARBURST_TABLE_LOCATION = "kb_mongo.my_company_kb.clients"

# ---------------------------------------------------------------------------
# Starburst Galaxy — read-only federated SQL backend
# Give the agent catalog + schema + table so it can write correct SQL itself.
# ---------------------------------------------------------------------------
s_db = StarburstManager(
    name="StarburstDB",
    catalog="kb_mongo",          # your Galaxy catalog name
    schema="my_company_kb",      # the schema (MongoDB database name) inside that catalog
    table_name="clients",        # the table / collection the agent will query
    description=(
        "Starburst Galaxy read-only backend connected to MongoDB via Trino. "
        "Use this to query structured data about clients. "
        "Fully-qualified table: kb_mongo.my_company_kb.clients. "
        "Always write SQL as: SELECT <columns> FROM kb_mongo.my_company_kb.clients WHERE ... LIMIT <n>"
    ),
).add_schema({
    "description": (
        "Starburst Galaxy read-only SQL backend (MongoDB via Trino). "
        "The agent must generate a valid SQL query using the table info below."
    ),
    "table": {
        "catalog":    "kb_mongo",
        "schema":     "my_company_kb",
        "table_name": "clients",
        "full_path":  "kb_mongo.my_company_kb.clients",
    },
    "read_payload": {
        "query": "A valid SQL statement — SELECT / SHOW / DESCRIBE only.",
        "limit": "int — max rows (default: 5). Appended automatically if omitted from SQL.",
    },
    "query_guide": {
        "basic":     "SELECT * FROM kb_mongo.my_company_kb.clients LIMIT 5",
        "filtered":  "SELECT * FROM kb_mongo.my_company_kb.clients WHERE name = 'Alice' LIMIT 5",
        "inspect":   "DESCRIBE kb_mongo.my_company_kb.clients",
        "list":      "SHOW TABLES FROM kb_mongo.my_company_kb",
    },
    "constraints": {
        "write_supported": False,
        "allowed_sql":     ["SELECT", "SHOW", "DESCRIBE"],
        "note":            "Always use the full path kb_mongo.my_company_kb.clients in every query.",
    },
})
knowledgeBuilder = KnowledgeBuilder([v_db, g_db, s_db])


def build_agent(description: str) -> Agent:
    """
    Build a KB Router Agent.

    Args:
        description: What this agent is for — defines its personality and domain.
                     Example: "You are a personal knowledge assistant for a software engineer."
    """
    instructions = f"""{description}

CRITICAL ROUTING RULES — FOLLOW EXACTLY:
1. START: Call `get_schemas()` immediately to understand all available backends.
2. UNDERSTAND: Use `get_all_kb_descriptions()` to decide which backend to use. Example: entities/relationships → Neo4j; text/semantic recall → ChromaDB; structured SQL tables + sheets → StarburstDB.
3. ANALYZE: For reads → use `read_kb()`. For writes → use `write_kb()` except StarburstDB (strictly read-only). StarburstDB auto-detects: natural language → sheet search; explicit SQL (qualified table) → direct query; unqualified SQL → tries to qualify then falls back.
4. ACTION: Pick ONE backend explicitly based on the data type. NEVER ask which backend to use — decide and execute.
5. EXECUTE: Call the tool with complete parameters. For Neo4j, include Cypher queries when storing. For StarburstDB, let it auto-detect.
6. RESPOND: Report results clearly. If no results found, say "No data found for [query]" and offer alternatives.
7. NEVER: Loop, retry the same failed query, or issue repeated write attempts after a read failure.

"""
    return Agent(
        name="KB_Router_Agent",
        model="gpt-4o-mini",
        instructions=instructions,
        tools=OpenAIToolBuilder.bind(knowledgeBuilder.build()),
    )


AGENT_DESCRIPTION = """
You are a personal knowledge assistant. 
You help users store and retrieve information across a graph database (for entities and 
relationships) and a vector store (for general text and semantic recall). 
and also answer question by deciding which database to query based on the question and the database descriptions, then querying that database and returning the results in a clear format. if you dont have them in the database use your own knowledge to answer the question. 
Always use the databases when possible, but if you dont have the information in the database, use your own knowledge to answer the question. Always return a clear and concise answer to the user. 
"""

agent = build_agent(AGENT_DESCRIPTION)


OpenAIModule([agent])

if __name__ == "__main__":
    try:
        CLI.main()
    finally:
        g_db.close()
