---
slug: /agent-kernel-execution-broker
title: "Introducing the Agent Kernel Execution Broker: A Safe Place for AI Agents to Run Code"
authors: [yaala]
tags: [agent-kernel, sandbox, execution-broker, security, docker, e2b, daytona, aws, enterprise-ai, code-execution]
image: /img/blog/execution-broker-banner.png
---

# Introducing the Agent Kernel Execution Broker: A Safe Place for AI Agents to Run Code

![Agent Kernel Execution Broker: agents connect through sandbox tools and a security policy to the broker, which routes execution to Docker, E2B, Daytona, EC2, or your own provider](/img/blog/execution-broker-banner.png)

AI agents have become remarkably good at writing code. Running that code is where most teams stop.

And they are right to hesitate. An agent that can execute code on your infrastructure can also read your filesystem, call your internal APIs, exhaust your CPU, or exfiltrate data over the network. So teams end up in one of two places: they switch code execution off entirely and cap what their agents can do, or they build a one-off sandbox stack in-house, wire it to one agent framework, marry it to one vendor, and maintain it forever.

**The Agent Kernel Execution Broker removes that trade-off.** It is a vendor-neutral brokering layer that sits between your agents and the environments their code runs in, with security policy and access control enforced on every single execution.

<!-- truncate -->

## One Broker Between Agents and Every Sandbox

The idea is simple. Agents never touch execution backends directly. They ask, and the Execution Broker routes the request to an isolated sandbox through a pluggable provider.

Enable it, and every agent gains code, shell, and file tools automatically, with usage guidance injected into its instructions. Your agent code never mentions the sandbox at all.

Before any code runs, two gates are checked, and both fail closed:

- **Security policy.** Each execution runs inside a permission and resource envelope: network egress rules (allow, deny, or an allowlist), filesystem read and write scopes, CPU and memory limits, and a hard wall-clock timeout. If a backend cannot enforce a policy you asked for, the execution is rejected rather than silently downgraded. Security is never quietly weakened to make something run.
- **Access control and identity.** Sandboxed code can run under the agent's identity or under the authenticated end user's identity, resolved per session. A user-scoped request can never silently fall back to broader agent credentials.

That fail-closed posture is the heart of the design: the broker checks what a backend has honestly declared it can enforce, and refuses anything it cannot guarantee.

## Your Containers, Your Rules

For teams that want full control, Docker mode lets you bring your own curated container images as the sandbox environment. Your golden image, your internal registry, your approved dependencies, your compliance checklist baked in. The broker adds enforced isolation on top: network switched off or restricted, CPU and memory capped, a read-only root filesystem with a writable workspace.

Security teams get a controlled, auditable execution surface. Agents get a fully equipped environment. Nobody has to choose.

An honest note on where responsibility sits today: command-level security comes from the environment you bring. Your curated container decides which interpreters, binaries, and tools exist for the agent to invoke, which is exactly where that control belongs. And this layer is about to get deeper: in the next version, sandbox providers gain native pseudo-terminal support, bringing full PTY sessions to Daytona, E2B, and other connections.

## Connect to Systems You Already Own

Not every workload belongs in a disposable sandbox. Sometimes the agent needs to operate on a real machine: an EC2 instance running your batch jobs, a long-lived container with your tooling installed.

The broker supports this through **attached environments**, and it treats them with the respect your infrastructure deserves. Attaching is an explicit, validated opt-in in configuration, never a side effect. The broker connects to the environment but never owns it: it will not provision it, will not destroy it, and will never silently recreate it if it becomes unreachable. Pointing agents at a live system is a deliberate decision, and the framework enforces that.

## Five Providers Out of the Box

The Execution Broker ships with pre-built providers, each honestly declaring its isolation tier:

- **Local Subprocess**, no isolation. Runs on the host for development and testing only.
- **Docker**, container isolation. A container per sandbox on your own Docker daemon, with network, filesystem, and resource policy actually enforced.
- **E2B**, micro-VM isolation. Managed Firecracker micro-VMs in the E2B cloud, with a stateful kernel where variables persist across calls.
- **Daytona**, container isolation. Managed cloud container sandboxes with enforced network and resource policy, plus warm starts from snapshots.
- **EC2 via SSM**, attach-only with no added isolation boundary, because it runs on an instance you already own. Supports running commands as a specific user through AWS role assumption.

![The five pre-built sandbox providers and their isolation tiers: Local Subprocess, Docker, E2B, Daytona, and EC2 via SSM](/img/blog/execution-broker-providers.png)

Those tiers are part of the contract. The framework never pretends two backends are interchangeable on security grounds; you always know exactly what boundary you are getting.

## Sessions and a Lifecycle You Never Manage

Real work is rarely one command. An agent writes a script, runs it, inspects the output, fixes a bug, and runs it again. The broker makes this natural through **sandbox sessions**: each session is a persistent workspace, so files written in one step are still there several conversation turns later. Sessions are isolated per conversation, and agents can create, list, and discard them as easily as calling a tool.

You choose the lifetime per workload: a persistent workspace for multi-step projects, a fresh throwaway sandbox per call for stateless computation, or a shared warm environment when startup cost matters.

The lifecycle runs itself. Idle sandboxes are reclaimed automatically and recreated on the next touch. If a backend sandbox vanishes, the broker heals the session under the same identity, and, crucially, tells the agent that the workspace was reset. Nothing is ever swept under the rug. Long-running executions do not block the conversation either: they are promoted to background tasks the agent polls, so a twenty-minute job and a two-second one flow through the same tools.

Nobody on your team writes provisioning, cleanup, or reconnection code. Ever.

## Framework-Neutral, Plug and Play

Here is the part that changes the dynamic.

Everything above works with whatever agent framework you already use: OpenAI Agents SDK, LangGraph, CrewAI, Google ADK, Smolagents, Pydantic AI. The sandbox capability is switched on with a few lines of configuration, and switching providers is a configuration change, not a rewrite. Develop against local subprocesses, test against Docker, ship on micro-VMs, and your agents never know the difference.

The industry keeps offering the same deal: adopt our sandbox, adopt our SDK, adopt our lock-in. Agent Kernel takes the opposite position. **The broker is the contract; providers are interchangeable plumbing.** Your security policy, your identity model, your session semantics, and your agent code all stay put while the execution backend underneath is swapped freely.

And when none of the built-in providers fit, you **bring your own**. Implement the provider interface for your internal platform, your Kubernetes setup, your private cloud, and point the configuration at it. A public contract test suite verifies your implementation honors the same semantics. Your custom backend instantly inherits everything the broker provides: policy enforcement, identity, sessions, self-healing lifecycle, background task promotion. You write the connection to your infrastructure; Agent Kernel supplies the guarantees.

This is what plug and play looks like in practice. The sandbox is switched on in configuration:

```yaml title="config.yaml"
sandbox:
  enabled: true
  type: docker              # or e2b | daytona
  docker:
    image: python:3.12-slim
  broker:
    flavor: thread
```

And the agent code never mentions the sandbox at all:

```python title="demo.py"
from agents import Agent
from agentkernel.cli import CLI
from agentkernel.openai import OpenAIModule

coder = Agent(
    name="coder",
    instructions="You are a coding assistant.",
)

OpenAIModule([coder])

if __name__ == "__main__":
    CLI.main()
```

Swap `docker` for `e2b`, `daytona`, `ec2_ssm`, or your own provider. The agent never knows the difference.

## The Bottom Line

Code execution is the capability that turns AI agents from advisors into operators, and it is exactly the capability most enterprises cannot responsibly turn on without guardrails. The Agent Kernel Execution Broker makes it safe to say yes: one broker, guarded by fail-closed security policy and access control, in front of any sandbox you choose, with none of your agent code held hostage by the choice.

Agent Kernel is open source under Apache 2.0.

- Sandbox documentation: https://kernel.yaala.ai/docs/advanced/sandbox
- Architecture deep dive: https://kernel.yaala.ai/docs/architecture/sandbox-internals
- GitHub: https://github.com/yaalalabs/agent-kernel

`pip install agentkernel` and give your agents a safe place to run.
