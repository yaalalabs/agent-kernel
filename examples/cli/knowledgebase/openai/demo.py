from agentkernel.cli import CLI
from agentkernel.knowledgebase.chroma_kb import ChromaManager
from agentkernel.knowledgebase.knowledgebuilder import KnowledgeBuilder
from agentkernel.knowledgebase.neo4j_kb import Neo4jManager
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

knowledgeBuilder = KnowledgeBuilder([v_db, g_db])


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
2.understand the database descrtiption using get_all_kb_descriptions() and use that to decide which backend to use for each query. For example, if the query is about finding a relationship between two entities, use Neo4j. If it's about recalling a fact or piece of text, use ChromaDB.
3. ANALYZE: For reads → use `read_kb()`. For writes → use `write_kb()`. For structured/graph data → prefer graphdb. For text/semantic → prefer chromadb.
4. ACTION: Pick ONE backend explicitly based on the data type. NEVER ask which backend to use — decide and execute.
5. EXECUTE: Call the tool with complete parameters. For Neo4j, include Cypher queries when storing entities/relationships.
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
      
