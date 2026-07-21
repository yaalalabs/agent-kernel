# Sandbox — Basic

The starting-point sandbox example. See [../README.md](../README.md) for the full set
(`basic`, `profiles`, `policy`, `identity`).

This package demonstrates the Agent Kernel sandbox capability: an OpenAI Agents SDK agent
that writes code and executes it in a sandbox. When `sandbox.enabled` is true, Agent
Kernel attaches the sandbox system tools (`run_code`, `run_command`, `write_sandbox_file`,
`read_sandbox_file`, `check_sandbox_task`, `list_sandbox_sessions`, `new_sandbox_session`,
`destroy_sandbox_session`) to every agent **and injects the usage context into each agent's
system prompt** — note that `demo.py`'s agent instructions say nothing about the sandbox;
the capability is self-describing.

The default profile uses the `local_subprocess` provider with the `thread` broker flavor:
executions run as local subprocesses in a per-sandbox temporary working directory.

> **Warning:** `local_subprocess` provides **no isolation**. The agent's code runs directly
> on your machine. Use it for development and testing only. For an isolated sandbox, switch
> `type` to `docker` in `config.yaml` (requires the `sandbox-docker` extra and a running
> Docker daemon).

Install dependencies using:

    ./build.sh

Install local dependencies in development mode using:

    ./build.sh local

Set your OpenAI API key, then run the demo:

    export OPENAI_API_KEY=sk-...
    uv run demo.py

Things to try in the CLI:

    Compute the 30th Fibonacci number by running Python code.
    Write a file called notes.txt containing "hello", then read it back.
    How many days are there between 2024-02-01 and 2026-07-20? Run code to find out.
    Start a fresh sandbox session named "uv-project" and initialize a uv project in it.
    Start another session named "npm-project" and create a blank npm project.
    Go back to the uv project and list its files.

The sandbox keeps its working directory per session: files written in one turn are still
there in the next, and the agent can reuse the `sandbox_session_id` it gets back from each
tool result to continue in the same environment.

To run tests:

    uv run pytest -s

The tests use fuzzy comparison mode (`test-config.yaml`): because the sandbox executes
real code, every expected answer is an exact value (42, "hello sandbox", 328), so results
are evaluated deterministically without an LLM judge. Running the agent itself still
requires `OPENAI_API_KEY`.
