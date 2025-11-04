![Agent Kernel Banner](docs/static/img/banner.png)

# Agent Kernel by Yaala Labs

> **[Developer Guide](DEVELOPER_GUIDE.md)**

## Introduction

Agent Kernel (AK) is a versatile, ready-to-use solution designed to streamline the development and execution of AI agent logic. Its framework-agnostic nature enables developers to effortlessly migrate from different AI agent frameworks without modifying the underlying agent logic.

AK offers a variety of execution options. This flexibility allows developers to deploy their agents across a range of environments, including local environments, cloud platforms, and on-premise enterprise systems. Cloud deployments can be configured as standalone solutions or integrated seamlessly into existing application infrastructures.

## Why Choose Agent Kernel?

Agent Kernel (AK) provides a streamlined solution for developing and executing AI agents. It eliminates the need to rewrite existing agents by integrating seamlessly with your preferred agentic framework. Additionally, it offers unified development capabilities that allow engineers to focus on logic without being tied to a specific framework. Here's how Agent Kernel enhances the development experience:

**Seamless Migration**  
Run existing agents on Agent Kernel's variety of execution frameworks with little to no effort required for porting.


Currently, Agent Kernel supports portability across popular AI agent frameworks, including [Langraph](https://www.langchain.com/langgraph) and [OpenAI Agents](https://openai.github.io/openai-agents-python/), allowing developers to leverage these frameworks’ capabilities while benefiting from AK's versatility.

## Agent Kernel Features

AK's Python libraries provide developers with comprehensive tools to:

1. **Design and Define Agents**
   - Create agents and specify their roles.

2. **Tool Integration**
   - Bind tools and functionalities to agents for enhanced capabilities.

3. **Hierarchies, Collaboration and Teamwork**
   - Build collections of agents that can collaborate to achieve shared goals and define topologies & hierarchies by leveraging supported agentic frameworks

4. **Context and Memory Management**
   - Handle agent memory efficiently, with in-built support for memory management.
   - It currently offers in-memory and Redis-based options.
   - Developers can customize memory management based on their preferences.

5. **Traceability and Accountability**
   - Ensures transparency by tracking and auditing agent operations.
   - Provides detailed traceability of all agent actions with multiple verbosity levels.
   - Includes tracking of collaborative actions and LLM calls.

8. **Built-in MCP Support**
   - AK includes built-in Multi-Context Processing (MCP) capabilities, enabling agents to connect and interact with external tools, data sources, and services seamlessly.
   - This ensures optimal collaboration and task distribution across dynamic environments.
   - AK optionally allows to expose AI agents as MCP tools.

9. **Built-in A2A Support**
   - AK provides Agent-to-Agent (A2A) communication support.
   - This enables advanced collaborative workflows, message passing, and synchronization between agents within a shared ecosystem.

### Agent Testing

Agent Kernel (AK) offers a robust utility for testing agents locally. Developers can use the built-in CLI-based testing environment to interact with agents and assess their functionality. Additionally, an automated test framework allows predefined scenarios to be executed, simplifying the process of validating agent behavior.

## Agent Deployment

AK provides flexible deployment options for executing agent logic efficiently. The agent logic, packaged as a Python library, integrates seamlessly into various deployment environments to ensure adaptability and scalability.

### Local Deployment

AK supports local execution of agent logic using its in-built **Agent Tester** utility. This allows developers to:
- Interact with agents via the Command Line Interface (CLI).
- Develop and execute automated tests through predefined scenarios for comprehensive debugging and refinement.

### Cloud Deployment

Cloud deployment for AK is currently supported on AWS, offering two distinct execution frameworks based on the workload type:

1. **Serverless Agent Execution Framework**
   - Ideal for scenarios with inconsistent or variable loads.
   - Scales dynamically in response to the workload requirements.

2. **Server-based Agent Execution Framework**
   - Suitable for scenarios with relatively consistent loads.
   - Offers reduced latency compared to serverless setups, ensuring faster response times.

### On-Premise Deployment

Agent Kernel is equipped with a REST API which can be bundled as a docker image. Agent Kernel examples come with a container-based solution which can be extended to implement an on-premise solution.


These versatile deployment and testing options make AK a powerful and flexible platform for building, testing, and deploying AI-based agents in diverse environments.