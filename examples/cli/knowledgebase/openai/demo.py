from agentkernel.cli import CLI
from agentkernel.knowledgebase.chroma_kb import ChromaManager
from agentkernel.knowledgebase.knowledgebuilder import KnowledgeBuilder
from agentkernel.knowledgebase.neo4j_kb import Neo4jManager
from agentkernel.knowledgebase.starburst_kb import StarburstManager
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
            "text": "string — the content to store",
            "source": "string — origin label (default: 'agent')",
        },
        "read_payload": {
            "query": "string — natural language search query",
            "limit": "int — max results to return",
        },
    }
)

g_db = Neo4jManager(
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
            "text": "string — human-readable description of the fact",
            "source": "string — origin label (default: 'agent')",
            "cypher_query": "(optional) Cypher string to execute for creating nodes/relationships",
            "cypher_params_json": "(optional) JSON-stringified params for the Cypher query",
        },
        "read_payload": {
            "query": "string — a valid Cypher query only",
            "limit": "int — max results",
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
                "check_friendship": "MATCH (a:Person)-[:FRIENDS_WITH]-(b:Person) WHERE toLower(a.name) = toLower($a) AND toLower(b.name) = toLower($b) RETURN COUNT(*) > 0 AS are_friends"
            },
            "write_examples": {
                "add_friendship": "MERGE (a:Person {name: $person}) MERGE (b:Person {name: $friend}) MERGE (a)-[:FRIENDS_WITH]->(b)",
                "verify_friendship": "MATCH (a:Person)-[:FRIENDS_WITH]-(b:Person) WHERE toLower(a.name)=toLower($person) AND toLower(b.name)=toLower($friend) RETURN COUNT(*) > 0 AS added"
            }
        },
    }
)

s_db = StarburstManager(
    name="StarburstDB-mongo",
    host="johnpraveenyl-mongocluster.trino.galaxy.starburst.io",
    catalog="kb_mongo",
    schema="my_company_kb",
    table_name="clients",
    description=(
        "Starburst Galaxy read-only backend — MongoDB via Trino. "
        "Contains client records. The ONLY valid table is kb_mongo.my_company_kb.clients."
    ),
).add_schema(
    {
        "description": (
            "Starburst Galaxy read-only SQL backend — MongoDB via Trino. "
            "Use this for any question about clients or people stored in MongoDB."
        ),
        "table": {
            "full_path": "kb_mongo.my_company_kb.clients",
            "columns": ["client_name", "status", "budget"],
            "IMPORTANT": "This is the ONLY table. NEVER use any other table name.",
        },
        "query_guide": {
            "list_all": "SELECT * FROM kb_mongo.my_company_kb.clients LIMIT 10",
            "search": "SELECT * FROM kb_mongo.my_company_kb.clients WHERE LOWER(name) LIKE '%john%' LIMIT 5",
            "inspect": "DESCRIBE kb_mongo.my_company_kb.clients",
            "RULE": "NEVER create a table name from the user's words. ALWAYS use kb_mongo.my_company_kb.clients.",
        },
        "constraints": {
            "write_supported": False,
            "allowed_sql": ["SELECT", "SHOW", "DESCRIBE"],
            "table_names": ["kb_mongo.my_company_kb.clients"],
        },
    }
)


s2_db = StarburstManager(
    name="StarburstDB_Sheets google sheets via trino",
    host="johnpraveenyl-free-cluster.trino.galaxy.starburst.io",
    catalog="kb_sheets",
    description=(
        "Starburst Galaxy read-only backend — Google Sheets via Trino. "
        "Contains company knowledge: topics, policies, tech info, department notes."
        "sheet_id: 1ND7S86ni14J-0hVYIrBs3zIUPMkKoT0YGmvyLLHhDDY"
    ),
).add_schema(
    {
        "description": (
            "Starburst Galaxy read-only backend — Google Sheets via Trino. "
            "Use this for general company knowledge, topics, policies, and tech information."
        ),
        "sources": {
            "google_sheet": {
                "sheet_id": "1ND7S86ni14J-0hVYIrBs3zIUPMkKoT0YGmvyLLHhDDY",
                "use_for": "company knowledge — topics, policies, tech info, department notes",
                "columns": ["topic", "information", "department"],
                "IMPORTANT": "ONLY these 3 columns exist: topic, information, department. NEVER use any other column.",
            },
        },
        "query_guide": {
    "list_all": "SELECT * FROM TABLE(kb_sheets.system.sheet(id => '1ND7S86ni14J-0hVYIrBs3zIUPMkKoT0YGmvyLLHhDDY')) LIMIT 10",
    "search": "SELECT * FROM TABLE(kb_sheets.system.sheet(id => '1ND7S86ni14J-0hVYIrBs3zIUPMkKoT0YGmvyLLHhDDY')) WHERE LOWER(CAST(topic AS VARCHAR)) LIKE '%rtx%' OR LOWER(CAST(information AS VARCHAR)) LIKE '%rtx%' LIMIT 5",
    "MANDATORY_QUERY_SYNTAX": (
        "Every query to this backend MUST use the FROM clause exactly as shown in the examples above. "
        "No other FROM syntax is valid for this backend."
    ),
},
        "constraints": {
            "write_supported": False,
            "allowed_sql": ["SELECT", "SHOW", "DESCRIBE"],
            "columns": ["topic", "information", "department"],
        },
    }
)

knowledgeBuilder = KnowledgeBuilder([v_db, g_db, s_db, s2_db])


def build_agent(description: str) -> Agent:
    instructions = f"""{description}

EXECUTION PROTOCOL:

1. SCHEMA FIRST — ONCE ONLY:
   Call get_schemas() exactly once at the start. Never call it again.
   The schema is your complete source of truth — backends, purposes, query formats, constraints.

2. ROUTE:
   Read each backend's description to match the user's intent to the right backend.

3. BUILD THE QUERY:
   Find the query_guide or examples section for your chosen backend in the schema.
   Construct the full, executable query string by following those templates exactly.
   Substitute user values into the template. Never pass a key name like 'list_all' — always the real query.
   CRITICAL: Use ONLY the relationship types, table names, column names, and syntax patterns 
   found in the schema. Never substitute from general knowledge or common conventions.

4. EXECUTE:
   Call read_kb() or write_kb() with the constructed query string.
   Wait for the result before responding.

5. RESPOND:
   Answer strictly from the returned data. If empty, say no records were found.

6.STARBURST:
    starburst galaxy read only backend google sheets via trino. Contains company knowledge: topics, policies, tech info, department notes.
    query syntax is defined strictly in the schema in the query_guide section follow it exactly.
    only for google sheets(
    WARNING: Uses special TVF syntax — FROM TABLE(kb_sheets.system.sheet(id => '...')). 
    get the sheet id from the schema and never deviate from the example query formats.)
"""
    return Agent(
        name="KB_Router_Agent",
        model="gpt-4o-mini",
        instructions=instructions,
        tools=OpenAIToolBuilder.bind(knowledgeBuilder.build()),
    )

AGENT_DESCRIPTION = """
You are a personal knowledge assistant.
You help users store and retrieve information across multiple databases:
- Neo4jDB: for entities and relationships (people, companies, places)
- ChromaDB: for unstructured text and semantic recall
- StarburstDB-mongo: for structured client data in MongoDB
- StarburstDB_Sheets: for company knowledge stored in Google Sheets

Always route to one backend first, execute the tool call, and return direct results.
Use schema guidance when available, but never get stuck retrying schema calls.
"""

agent = build_agent(AGENT_DESCRIPTION)

OpenAIModule([agent])

if __name__ == "__main__":
    try:
        CLI.main()
    finally:
        g_db.close()
