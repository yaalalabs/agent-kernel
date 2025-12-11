# Agent Kernel Documentation Assistant - Containerized Deployment

This package contains an Agent Kernel documentation assistant built with OpenAI Agents SDK, deployed in a containerized configuration using AWS ECS. 
The agent uses **LlamaIndex-powered RAG (Retrieval-Augmented Generation)** to answer questions about Agent Kernel by searching through the official documentation and example projects.

## Features

- **OpenAI Agents SDK Integration**: Leverages OpenAI's Agents SDK for building intelligent agents
- **LlamaIndex RAG System**: Advanced semantic search using LlamaIndex with vector embeddings
- **Comprehensive Knowledge Base**: Searches through:
  - All markdown documentation files from `docs/docs`
  - All example project files (Python, TOML, YAML, shell scripts, JSON)
- **Vector-Based Search**: Uses OpenAI embeddings (text-embedding-3-small) for semantic similarity
- **Persistent Index**: Vector index is persisted to disk for fast startup
- **REST API**: Exposes the agent via REST API with custom endpoint support
- **Containerized Deployment**: Full AWS ECS deployment with API Gateway
- **Session Management**: Redis-backed session persistence

## Architecture

The RAG system consists of three main components:

1. **rag_loader.py**: Loads documentation and example files from the cloned agent-kernel repository
2. **rag_system.py**: LlamaIndex-based vector store and query engine
3. **tool.py**: Agent tools for searching and managing the knowledge index

## Prerequisites

- AWS CLI configured with appropriate credentials
- Terraform (`1.9.5` or higher) installed
- Python 3.12+
- uv package manager
- OpenAI API key (for embeddings and LLM)

## Environment Variables

Set the following environment variables:

```bash
export OPENAI_API_KEY="your-api-key"
```

## Local Development

1. Install dependencies:
    ```bash
    ./build.sh
    ```

2. For local development with custom agentkernel builds:
    ```bash
    ./build.sh local
    ```

3. Clone the agent-kernel repository for RAG data (first time only):
    ```bash
    cd /tmp
    git clone --depth 1 git@github.com:yaalalabs/agent-kernel.git agent-kernel-rag
    ```

4. Run the application locally:
    ```bash
    uv run app.py
    ```

   The first run will:
   - Load all documentation and example files
   - Create vector embeddings
   - Build and persist the index to `./rag_storage/`

   Subsequent runs will load the existing index from storage (much faster).

## RAG System Details

### Data Sources

The RAG system indexes:
- **Documentation**: All `.md` files from `docs/docs/`
- **Examples**: All relevant files from `examples/` including:
  - Python files (`.py`)
  - Configuration files (`.toml`, `.yaml`, `.yml`, `.json`)
  - Shell scripts (`.sh`)
  - Text files (`.txt`, `.rst`)

### Index Configuration

- **Chunk Size**: 1024 tokens
- **Chunk Overlap**: 200 tokens
- **Top K Results**: 5 most relevant chunks
- **Embedding Model**: text-embedding-3-small
- **LLM**: gpt-4o-mini

### Tools Available

1. **search_agent_kernel_docs(query)**: Search the knowledge base
2. **rebuild_knowledge_index()**: Rebuild the vector index (use when docs are updated)

## Deployment Steps

1. Build the deployment package:
    ```bash
    cd deploy && ./deploy.sh
    ```

2. For deployment with local agentkernel builds:
    ```bash
    cd deploy && ./deploy.sh local
    ```

