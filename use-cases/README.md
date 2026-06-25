# Building Agents With Agent Kernel Skills

This guide shows how to use the Agent Kernel skills pack with a coding agent to create a new agent project. The sample agent directory is `waste-sorting-assistant`, but the same workflow can be reused with any folder name.

## 1. Create Or Enter The Agent Directory

From the directory where you keep agent projects, create the agent folder if it does not already exist, then move into it:

```bash
mkdir -p waste-sorting-assistant
cd waste-sorting-assistant
```

For another agent, replace `waste-sorting-assistant` with your own folder name:

```bash
mkdir -p <your-agent-folder>
cd <your-agent-folder>
```

## 2. Initialize The Project With uv

Use `uv` from the start so the agent project has an isolated Python environment and lockfile:

```bash
uv init --app --python 3.12
```

Then add Agent Kernel to the project:

```bash
uv add agentkernel
```

## 3. Download The Skills Pack

List the available Agent Kernel skills and supported coding assistants:

```bash
uv run ak skill list
uv run ak skill assistants
```

Install the skills for the coding agent you will use. For Cursor, run:

```bash
uv run ak skill install --assistant cursor
```

Other supported assistants use the same command with a different assistant name:

```bash
uv run ak skill install --assistant copilot
uv run ak skill install --assistant claude
uv run ak skill install --assistant windsurf
uv run ak skill install --assistant codex
uv run ak skill install --assistant aider
```

The coding agent discovers the installed skills from its configured skill directory inside the current agent folder. To have those skills auto-applied, open the agent folder itself as the workspace root, for example `use-cases/waste-sorting-assistant`. If you keep the larger repository open as the workspace root, nested skill files can still be read manually, but the coding agent may not automatically apply them.

## 4. Ask The Coding Agent To Build The Agent

Use the installed Agent Kernel skills to scaffold and implement the agent. For the sample `waste-sorting-assistant`, give the coding agent this prompt:

```text
Using the Agent Kernel skills pack, build an Agent Kernel project in this folder.

Agent description:
A single-agent solution that advises users on the correct disposal method for a given item based on its material and the user's local recycling rules. The agent uses a tool to look up disposal categories and applies memory to retain region-specific rules across interactions, improving accuracy over repeated use.

Create the project structure, dependencies, configuration, agent implementation, lookup tool, memory/session persistence, and a basic way to run and test the agent locally.
```

For a different agent, keep the same instruction shape and replace the agent description with your own.

## 5. Continue Development

After the first scaffold is generated, use follow-up prompts such as:

```text
Add automated tests for the disposal lookup tool and memory behavior.
```

```text
Add a REST API entry point for this agent.
```

```text
Add deployment configuration for the target cloud provider.
```

The coding agent should use the relevant Agent Kernel skills, such as `ak-init`, `ak-build`, `ak-add-capabilities`, `ak-cloud-deploy`, and `ak-test`, to generate the project files and keep the implementation aligned with Agent Kernel conventions.
