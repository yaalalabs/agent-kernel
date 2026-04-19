from agentkernel.cli import CLI
from agentkernel.knowledgebase.knowledgebuilder import KnowledgeBuilder
from agentkernel.knowledgebase.starburst import StarburstManager
from agentkernel.openai import OpenAIModule, OpenAIToolBuilder
from agents import Agent

s_db = StarburstManager(
    name="StarburstDB-mongo",
    host="name-mongocluster.trino.galaxy.starburst.io",
    catalog="catalog name",
    schema="schema name",
    table_name="clients",
    description=(
        "Starburst Galaxy read-only backend - MongoDB via Trino. "
        "Contains client records. "
        "Query syntax is defined strictly in the query_guide - follow it exactly."
        "use the place holder <MONGO_SOURCE> in your queries as defined in the schema. NEVER use any other name, table name or path."
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

s2_db = StarburstManager(
    name="StarburstDB_Sheets",
    host="name-free-cluster.trino.galaxy.starburst.io",
    catalog="catalog name",
    description=(
        "Starburst Galaxy read-only backend - Google Sheets via Trino. "
        "Contains company knowledge: topics, policies, tech info, department notes. "
        "Query syntax is defined strictly in the query_guide - follow it exactly."
        "use the place holder <SHEETS_SOURCE> in your queries as defined in the schema. NEVER use any other name, table name or path."
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

knowledgeBuilder = KnowledgeBuilder(
    [s_db, s2_db],
    semantic_map={
        "<SHEETS_SOURCE>": "TABLE(kb_sheets.system.sheet(id => 'put your sheet id here'))",
        "<MONGO_SOURCE>": "put your MongoDB source path here (eg: mongodb.default.clients)",
    },
)


def build_agent(description: str) -> Agent:
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
   Use only the placeholder tokens, column names, and syntax patterns defined in the schema.

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
        tools=OpenAIToolBuilder.bind(knowledgeBuilder.build()),
    )


AGENT_DESCRIPTION = """
You are a personal knowledge assistant.
You help users store and retrieve information across the StarburstDB-mongo and StarburstDB_Sheets backends.

Always route to one backend first, execute the tool call, and return direct results.
"""

agent = build_agent(AGENT_DESCRIPTION)

OpenAIModule([agent])

if __name__ == "__main__":
    try:
        CLI.main()
    finally:
        s_db.close()
        s2_db.close()
