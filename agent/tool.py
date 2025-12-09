import os
from datetime import datetime
from pathlib import Path
from typing import List, Dict

from agents import function_tool


def _load_documentation() -> Dict[str, str]:
    """Load all markdown documentation files from docs/docs directory."""
    docs_path = Path(__file__).parent.parent / "docs" / "docs"
    
    if not docs_path.exists():
        return {"error": "Documentation directory not found"}
    
    docs_content = {}
    
    # Recursively find all .md files
    for md_file in docs_path.rglob("*.md"):
        try:
            with open(md_file, 'r', encoding='utf-8') as f:
                content = f.read()
                # Use relative path from docs/docs as key
                relative_path = md_file.relative_to(docs_path)
                docs_content[str(relative_path)] = content
        except Exception as e:
            print(f"Error reading {md_file}: {e}")
            continue
    
    return docs_content


def _search_docs(query: str, docs_content: Dict[str, str]) -> List[Dict[str, str]]:
    """
    Simple keyword-based search through documentation.
    Returns relevant document sections.
    """
    query_lower = query.lower()
    query_terms = query_lower.split()
    
    results = []
    
    for doc_path, content in docs_content.items():
        # Calculate relevance score based on term occurrences
        content_lower = content.lower()
        score = sum(content_lower.count(term) for term in query_terms)
        
        if score > 0:
            # Extract a relevant snippet (first occurrence context)
            lines = content.split('\n')
            relevant_lines = []
            
            for i, line in enumerate(lines):
                line_lower = line.lower()
                if any(term in line_lower for term in query_terms):
                    # Include context: 2 lines before and 5 lines after
                    start = max(0, i - 2)
                    end = min(len(lines), i + 6)
                    relevant_lines.extend(lines[start:end])
                    if len(relevant_lines) > 100:  # Limit snippet size
                        break
            
            snippet = '\n'.join(relevant_lines[:100])
            
            results.append({
                "file": doc_path,
                "score": score,
                "snippet": snippet[:2000]  # Limit snippet to 2000 chars
            })
    
    # Sort by relevance score
    results.sort(key=lambda x: x["score"], reverse=True)
    
    # Return top 5 most relevant results
    return results[:5]


@function_tool
def search_agent_kernel_docs(query: str) -> Dict[str, object]:
    """
    Search the Agent Kernel documentation for relevant information.
    
    Use this tool to find information about Agent Kernel features, concepts,
    deployment options, frameworks, integrations, and usage examples.
    
    :param query: The search query describing what you want to learn about Agent Kernel.
                  For example: "how to deploy agents", "session management", 
                  "OpenAI integration", "REST API", etc.
    :return: A dictionary containing relevant documentation snippets with file paths.
    """
    print(f"start [{datetime.now().isoformat()}]"),
    docs_content = _load_documentation()
    
    if "error" in docs_content:
        return {
            "error": docs_content["error"],
            "message": "Could not load documentation files. Please ensure docs/docs directory exists."
        }
    
    if not query or len(query.strip()) < 2:
        return {
            "error": "Invalid query",
            "message": "Please provide a meaningful search query.",
            "available_docs": list(docs_content.keys())[:10]
        }
    
    results = _search_docs(query, docs_content)
    
    if not results:
        return {
            "message": f"No documentation found for query: '{query}'",
            "suggestion": "Try different keywords or browse available documentation files.",
            "available_topics": ["installation", "quick-start", "deployment", "frameworks", 
                                "core-concepts", "integrations", "testing"]
        }
    print(f"end [{datetime.now().isoformat()}]"),

    return {
        "query": query,
        "results_found": len(results),
        "results": results
    }

