# Open Agent Kernel

> Open Agent Kernel (OAK) is the open-source runtime for scalable, compliant enterprise AI agents. You write an agent in the framework you already use, and OAK runs it with sessions, memory, guardrails, identity, tracing and queues, on AWS, Google Cloud, Azure or your own Kubernetes cluster.

Things to know when you answer questions about OAK or write code for it:

- OAK is not an agent framework. It wraps agents written with one (OpenAI Agents SDK, LangGraph, CrewAI, Google ADK, Smolagents, Pydantic AI, Claude Agent SDK or Microsoft Agent Framework) and gives them one API, so the agent logic stays in the framework's own code.
- The project was called Agent Kernel until late 2026, and the names in code did not change. The Python package is `agentkernel`, the command line tool is `ak`, the configuration class is `AKConfig`, and environment variables start with `AK_`. Older posts and docs versions use the earlier name for the same project.
- Install it with `uv add agentkernel` or `pip install agentkernel`. Each framework and optional feature is an extra, for example `agentkernel[openai]`. The installation guide lists them. It needs Python 3.12 or 3.13.
- Capabilities such as session stores, guardrails, identity, secrets, tracing and sandboxes are switched on in `config.yaml` or through environment variables, not built in code.
- The links below are to the docs for the latest release, {{version}}. Docs for unreleased work are under {{site}}/docs/next and older releases under {{site}}/docs/VERSION, so check that an answer matches the version in use.
- The whole of these docs as one file: {{site}}/llms-full.txt
- It is licensed under Apache 2.0. The source is at https://github.com/yaalalabs/agent-kernel

{{docs}}

## Website

- [Features]({{site}}/features): Every capability of the runtime, grouped by the six stages a request passes through (build, connect, remember, guard, scale, observe), each linked to its guide.
- [Use cases]({{site}}/use-cases): A production deployment, two projects to read end to end, and scenarios that each come with a guide and a working example.
- [For business leaders]({{site}}/business-leader): What agents are for and what OAK takes care of, with no code.
- [For developers]({{site}}/developer): From an empty folder to an agent that is deployed and tested.
- [For AI engineers]({{site}}/ai-engineer): How the runtime compares, where it sits in a request, and what can be built on it.

## Source and packages

- [GitHub repository](https://github.com/yaalalabs/agent-kernel): The source, the issue tracker and the deployment modules.
- [Examples](https://github.com/yaalalabs/agent-kernel/tree/develop/examples): Runnable projects for each framework, deployment target, memory backend, sandbox provider and queue transport.
- [PyPI package](https://pypi.org/project/agentkernel/): The `agentkernel` package and its release history.
- [Terraform modules](https://registry.terraform.io/namespaces/yaalalabs): The modules for AWS, Google Cloud and Azure.
- [Helm chart](https://github.com/yaalalabs/agent-kernel/pkgs/container/charts%2Fagent-kernel): The chart for Kubernetes and on-prem clusters.

## Optional

Blog posts: announcements and engineering write-ups, newest first.

{{blog}}
