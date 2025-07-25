# Agent Kernel by Yaala Labs

## Introduction

Agent Kernel (AK) is a versatile, ready-to-use solution designed to streamline the development and execution of AI agent logic. Its framework-agnostic nature enables developers to effortlessly switch between different AI agent frameworks without modifying the underlying agent logic.

AK offers a variety of execution options, each supporting multiple deployment profiles. This flexibility allows developers to deploy their agents across a range of environments, including local environments, cloud platforms, and on-premise enterprise systems. Cloud deployments can be configured as standalone solutions or integrated seamlessly into existing application infrastructures. Deployment profiles range from lightweight configurations for development purposes to robust, enterprise-level setups designed to meet stringent compliance requirements.


## Agent Development

AK's Python libraries provide developers with comprehensive tools to:

1. **Design and Define Agents**
   - Create agents and specify their roles.

2. **Tool Integration**
   - Bind tools and functionalities to agents for enhanced capabilities.

3. **Collaboration and Teamwork**
   - Build collections of agents that can collaborate to achieve shared goals.

4. **Agent Hierarchies**
   - Define topologies and hierarchies, including prebuilt setups like supervisor agents managing subordinate agents.

5. **Context and Memory Management**
   - Handle agent memory efficiently, with in-built support for both short-term and long-term memory management.

6. **Traceability and Accountability**
   - Ensure transparency by tracking and auditing agent operations.

7. **Prebuilt Knowledge Sources**
   - Leverage predefined knowledge sources, including graph databases, and manage these resources through built-in tools.

AK currently supports the AI Agent Framework portability for [langraph](https://www.langchain.com/langgraph) and [OpenAI Agents](https://openai.github.io/openai-agents-python/).

### Agent Capabilities

Agent Kernel (AK) offers a range of capabilities to support productive agent development:

1. **Agent Memory Management**
   - AK supports both short-term and long-term memory management via pluggable storage types.
   - It currently offers in-memory and Redis-based options for in-built short-term memory management.
   - For long-term memory, AK supports AWS DynamoDB and MongoDB.
   - Developers can customize memory management based on their preferences.

2. **LLM Portability**
   - AK agents' language models are configurable.
   - In multi-agent collaborative setups, each agent can be configured with a preferred LLM and customized hyperparameters.

3. **Agent Collaboration**
   - AK natively supports different types of agents, including hierarchical and collaborative (team-based) setups.
   - Developers can define custom topologies to suit specific use cases.


### Agents' Support Capabilities

The Agent Kernel includes in-built capabilities to facilitate seamless integration into applications:

1. **Thread Management**
   - Support for in-built chat functionality with thread management.
   - Features include thread history persistence, context persistence, and double text prevention.

2. **Auditability**
   - Provides detailed traceability of all agent actions with multiple verbosity levels.
   - Includes tracking of collaborative actions and LLM calls.

3. **Role-Based Access Control (RBAC)**
   - Built-in capability for role-based access control for both agents and tool invocation.
   - Includes interfaces to attach custom RBAC tools as needed.

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

#### Deployment Profiles

AK's cloud deployments feature multiple profiles designed to accommodate varying hardware and environment requirements, ensuring high availability and enterprise-grade standards. The supported profiles include:

1. **Development Profile**
   - Optimized for minimal resource consumption.
   - Enables quick deployment for development and testing purposes.

2. **Production Profile**
   - Delivers a robust, secure, and enterprise-standard deployment.
   - Includes advanced features like signed code, encrypted persistent storage, and fault-tolerant configurations.

3. **Staging-lite Profile**
   - Mirrors the Production Profile but is tuned to reduce operational costs.
   - Balances the resource and configuration similarities to production while keeping expenses in check.

These versatile deployment and testing options make AK a powerful and flexible platform for building, testing, and deploying AI-based agents in diverse environments.