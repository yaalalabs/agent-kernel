# Agent Kernel running Claude Agent SDK Agents

This package contains a demo of Agent Kernel running agents built with the
[Claude Agent SDK](https://code.claude.com/docs/en/agent-sdk/overview). Users may interact with agents via the
Agent Kernel CLI.

## Model provider

The Claude Agent SDK runs Claude models only. It needs an Anthropic API key or a cloud provider; Anthropic does
not allow third-party products to use a claude.ai login.

**Set exactly one** of these — setting more than one, or a cloud provider with no real credentials behind it,
makes the Claude Code CLI hang silently instead of failing with an error:

    export ANTHROPIC_API_KEY=...          # Claude API — simplest, no extra setup

    # or

    export CLAUDE_CODE_USE_BEDROCK=1      # Amazon Bedrock — needs a configured AWS account with Bedrock access to Claude models

    # or

    export CLAUDE_CODE_USE_VERTEX=1       # Google Vertex AI — needs a configured GCP project with Vertex access to Claude models

Each run starts a Claude Code CLI subprocess, bundled in the `claude-agent-sdk` wheel (no Node.js needed).

## Multi-agent routing

Claude's native multi-agent primitive is the **subagent**. The `triage` agent lists the specialist agents in
native `AgentDefinition` entries in `ClaudeAgentOptions.agents`, and delegates to them
through the SDK's `Agent` tool. The weather subagent calls `get_weather`, an Agent Kernel tool bound with
`ClaudeToolBuilder`.

## Built-in tools

By default the Claude Agent SDK gives the model Claude Code's built-in tools (Bash, Read, Write, WebFetch, ...)
acting on this host, and loads `~/.claude` settings. The shared `options()` helper in `demo.py` turns that off for
every agent with `tools=[]` and `setting_sources=[]`, and uses `permission_mode="dontAsk"` so any tool call that is
not explicitly approved is denied. `strict_mcp_config=True` and `verbatim_prompts=True` additionally keep local MCP
configuration and `@path` expansion out of user prompts, and `max_turns=8` bounds a runaway run. Agent Kernel
approves the tools bound with `ClaudeToolBuilder`, and the `Agent` tool an agent with native subagents delegates through.

## Running

Install dependencies using:

    ./build.sh

Install local dependencies in development mode using:

    ./build.sh local

Run this demo using the following.

    python demo.py

To run tests:

    uv run pytest -s

> Note: until a release of `agentkernel` that includes the `claude` extra is published to PyPI, build with
> `./build.sh local` against a locally built `ak-py/dist`.
