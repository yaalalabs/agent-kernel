# Agent Kernel Documentation Assistant - Containerized Deployment

This package contains an Agent Kernel documentation assistant built with OpenAI Agents SDK, deployed in a containerized configuration using AWS ECS. 
The agent uses RAG (Retrieval-Augmented Generation) to answer questions about Agent Kernel by searching through the official documentation.

## Features

- **OpenAI Agents SDK Integration**: Leverages OpenAI's Agents SDK for building intelligent agents
- **RAG-Powered Documentation Search**: Searches through `docs/docs` markdown files to answer questions
- **Keyword-Based Search Tool**: Custom tool that finds relevant documentation snippets
- **REST API**: Exposes the agent via REST API with custom endpoint support
- **Containerized Deployment**: Full AWS ECS deployment with API Gateway
- **Session Management**: Redis-backed session persistence

## Deployed Resources

This demo deploys the following AWS resources:

- AWS ECS cluster running the Agent Kernel implementation
- API Gateway endpoint for the ECS service
- ElastiCache Redis for session management

## Prerequisites

- AWS CLI configured with appropriate credentials
- Terraform (`1.9.5` or higher) installed
- Python 3.12+
- uv package manager

## Local Development

1. Install dependencies:
    ```bash
    ./build.sh
    ```

2. For local development with custom agentkernel builds:
    ```bash
    ./build.sh local
    ```

3. Run the application locally:
    ```bash
    uv run app.py
    ```

## Deployment Steps

1. Build the deployment package:
    ```bash
    cd deploy && ./deploy.sh
    ```

2. For deployment with local agentkernel builds:
    ```bash
    cd deploy && ./deploy.sh local
    ```

