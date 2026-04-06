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
).add_schema({
    "description": (
        "Semantic vector store. Use for unstructured text, natural-language facts, "
        "and any data best retrieved by meaning rather than exact structure."
    ),
    "store_payload": {
        "text":   "string — the content to store",
        "source": "string — origin label (default: 'agent')",
    },
    "read_payload": {
        "query": "string — natural language search query",
        "limit": "int — max results to return",
    },
})

g_db = Neo4jManager(
    name="Neo4jDB",
    description=(
        "Neo4j graph database. Use for entities, relationships, and structured facts. "
        "Supports raw Cypher queries for precise lookups."
    ),
).add_schema({
    "description": (
        "Neo4j graph database. Use for entities, relationships, and structured facts. "
        "Supports raw Cypher queries for precise lookups."
    ),
    "store_payload": {
        "text":               "string — human-readable description of the fact",
        "source":             "string — origin label (default: 'agent')",
        "cypher_query":       "(optional) Cypher string to execute for creating nodes/relationships",
        "cypher_params_json": "(optional) JSON-stringified params for the Cypher query",
    },
    "read_payload": {
        "query": "string — natural language question OR a valid Cypher query",
        "limit": "int — max results",
    },
    "query_generation_guide": {
        "goal": "Help LLM generate valid Cypher for this KB.",
        "known_internal_labels":  ["MemoryNote", "CypherFact"],
        "domain_labels_examples": ["Person", "Car", "Company", "Place", "Thing"],
        "common_properties":      ["name", "model", "title", "text", "source"],
        "relationship_pattern":   "(a)-[r]->(b)",
        "cypher_best_practices": [
            "Prefer parameterized queries (use $name, $value, etc.).",
            "Use OPTIONAL MATCH when relationships may not exist.",
        ],
        "write_query_template": (
            "MERGE (a:Person {name: $person}) "
            "MERGE (b:Person {name: $friend}) "
            "MERGE (a)-[:FRIENDS_WITH]->(b)"
        ),
    },
})

s_db = StarburstManager(
    name="StarburstDB",
    host="johnpraveenyl-mongocluster.trino.galaxy.starburst.io",
    catalog="kb_mongo",
    schema="my_company_kb",
    table_name="clients",
    description=(
        "Starburst Galaxy read-only backend — MongoDB via Trino. "
        "Contains client records. The ONLY valid table is kb_mongo.my_company_kb.clients."
    ),
).add_schema({
    "description": (
        "Starburst Galaxy read-only SQL backend — MongoDB via Trino. "
        "Use this for any question about clients or people stored in MongoDB."
    ),
    "table": {
        "full_path":  "kb_mongo.my_company_kb.clients",
        "columns":    ["client_name","status","budget"],
        "IMPORTANT":  "This is the ONLY table. NEVER use any other table name.",
    },
    "query_guide": {
        "list_all":  "SELECT * FROM kb_mongo.my_company_kb.clients LIMIT 10",
        "search":    "SELECT * FROM kb_mongo.my_company_kb.clients WHERE LOWER(name) LIKE '%john%' LIMIT 5",
        "inspect":   "DESCRIBE kb_mongo.my_company_kb.clients",
        "RULE":      "NEVER create a table name from the user's words. ALWAYS use kb_mongo.my_company_kb.clients.",
    },
    "constraints": {
        "write_supported": False,
        "allowed_sql":     ["SELECT", "SHOW", "DESCRIBE"],
        "table_names":     ["kb_mongo.my_company_kb.clients"],
    },
})


s2_db = StarburstManager(
    name="StarburstDB_Sheets",
    host="johnpraveenyl-free-cluster.trino.galaxy.starburst.io",
    catalog="kb_sheets",
    description=(
        "Starburst Galaxy read-only backend — Google Sheets via Trino. "
        "Contains company knowledge: topics, policies, tech info, department notes."
    ),
).add_schema({
    "description": (
        "Starburst Galaxy read-only backend — Google Sheets via Trino. "
        "Use this for general company knowledge, topics, policies, and tech information."
    ),
    "sources": {
        "google_sheet": {
            "sheet_id": "1ND7S86ni14J-0hVYIrBs3zIUPMkKoT0YGmvyLLHhDDY",
            "use_for":  "company knowledge — topics, policies, tech info, department notes",
            "columns":  ["topic", "information", "department"],
            "IMPORTANT": "ONLY these 3 columns exist: topic, information, department. NEVER use any other column.",
        },
    },
    "query_guide": {
        "list_all": "SELECT * FROM TABLE(kb_sheets.system.sheet(id => '1ND7S86ni14J-0hVYIrBs3zIUPMkKoT0YGmvyLLHhDDY')) LIMIT 10",
        "search":   "SELECT * FROM TABLE(kb_sheets.system.sheet(id => '1ND7S86ni14J-0hVYIrBs3zIUPMkKoT0YGmvyLLHhDDY')) WHERE LOWER(CAST(topic AS VARCHAR)) LIKE '%rtx%' OR LOWER(CAST(information AS VARCHAR)) LIKE '%rtx%' LIMIT 5",
        "RULE":     "Always search BOTH topic AND information using OR. Always CAST columns to VARCHAR before LOWER().",
    },
    "constraints": {
        "write_supported": False,
        "allowed_sql":     ["SELECT", "SHOW", "DESCRIBE"],
        "columns":         ["topic", "information", "department"],
    },
})

knowledgeBuilder = KnowledgeBuilder([v_db, g_db, s_db, s2_db])


def build_agent(description: str) -> Agent:
    instructions = f"""{description}

CRITICAL ROUTING RULES — FOLLOW EXACTLY:

1. START: Call get_schemas() ONCE at the beginning. Do not call it again.

2. ROUTE based on the question:
   - Client/people data in MongoDB  → StarburstDB
   - Topics/policies/tech knowledge → StarburstDB_Sheets
   - Unstructured text/semantic     → ChromaDB
   - Entities/relationships         → Neo4jDB

3. STARBURST STRICT SQL RULES — NON-NEGOTIABLE:
   - ALWAYS generate valid SQL before calling read_kb() on any Starburst backend.
   - NEVER pass plain text or natural language to StarburstDB or StarburstDB_Sheets.
   - StarburstDB has EXACTLY ONE table: kb_mongo.my_company_kb.clients
   - StarburstDB_Sheets uses ONLY: TABLE(kb_sheets.system.sheet(id => '1ND7S86ni14J-0hVYIrBs3zIUPMkKoT0YGmvyLLHhDDY'))
   - NEVER invent or guess table names. Use ONLY the exact paths above.
   - NEVER create table names from the user's words.
     Example: user says "yaala labs" → do NOT use table "yaala_labs". Use kb_mongo.my_company_kb.clients with a WHERE LIKE filter.
   - StarburstDB_Sheets has ONLY 3 columns: topic, information, department. Never use any other column name.

4. NO RETRIES:
   - Each backend gets exactly ONE attempt per user message.
   - If a query fails, STOP immediately and answer from your own knowledge. Do not retry.

5. WRITES:
   - ChromaDB and Neo4jDB support write_kb().
   - StarburstDB and StarburstDB_Sheets are strictly read-only. Never call write_kb() on them.

6. RESPOND:
   - Always give a clear, direct answer.
   - If no data found in the database, say "No data found for [query]" and answer from your own knowledge.
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
- StarburstDB: for structured client data in MongoDB
- StarburstDB_Sheets: for company knowledge stored in Google Sheets

Always query the right database first. If no data is found, answer from your own knowledge and say so clearly.
"""

agent = build_agent(AGENT_DESCRIPTION)

OpenAIModule([agent])

if __name__ == "__main__":
    try:
        CLI.main()
    finally:
        g_db.close()