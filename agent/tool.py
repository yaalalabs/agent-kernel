from typing import Dict

from agents import function_tool

from rag_system import get_rag_instance


@function_tool
def search_agent_kernel_docs(query: str) -> Dict[str, object]:
    """
    Search the Agent Kernel documentation and examples using advanced RAG (Retrieval-Augmented Generation).
    
    This tool uses LlamaIndex to search through:
    - All markdown documentation files from docs/docs
    - All example projects including Python files, TOML configs, YAML files, and shell scripts
    
    Use this tool to find information about Agent Kernel features, concepts,
    deployment options, frameworks, integrations, code examples, and usage patterns.
    
    :param query: The search query describing what you want to learn about Agent Kernel.
                  For example: "how to deploy agents", "session management", 
                  "OpenAI integration", "REST API", "LangGraph example", etc.
    :return: A dictionary containing the AI-generated response with relevant sources.
    """

    if not query or len(query.strip()) < 2:
        return {
            "error": "Invalid query",
            "message": "Please provide a meaningful search query (at least 2 characters).",
        }

    try:
        # Get RAG instance and query
        rag = get_rag_instance()
        result = rag.query(query)
        return result

    except Exception as e:
        print(f"Error in RAG query: {e}")
        return {
            "error": str(e),
            "message": "An error occurred while searching the documentation. Please try again.",
            "query": query,
        }