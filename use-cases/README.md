# Building Agents With Agent Kernel Skills

This guide shows how to use the Agent Kernel skills pack with a coding agent to create a new agent project. The sample agent directory is `waste-sorting-assistant`, but the same workflow can be reused with any folder name.

Python version must be `3.12` - `3.13.x`.

Before starting, install the `agentkernel` package first; this installs the `ak` CLI used to download the skills pack. Follow the Agent Kernel quick-start installation path for your preferred framework.

Install Agent Kernel with:

```bash
pip install agentkernel
```

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

## 2. Define The Agent Spec

Create a `SPEC.md` file in the agent folder. This file should describe the agent's purpose, tools, memory needs, local run mode, deployment target, and any folder or file structure requirements.

## 3. Download The Skills Pack

List the available Agent Kernel skills and supported coding assistants:

```bash
ak skill list
ak skill assistants
```

Install the skills for the coding agent you will use. For example:

```bash
ak skill install --assistant cursor
```

Other supported assistants use the same command with a different assistant name:

```bash
ak skill install --assistant copilot
ak skill install --assistant claude
ak skill install --assistant windsurf
ak skill install --assistant codex
ak skill install --assistant aider
```

The coding agent discovers the installed skills from its configured skill directory inside the current agent folder. To have those skills auto-applied, open the agent folder itself as the workspace root, for example `use-cases/waste-sorting-assistant`. If you keep the larger repository open as the workspace root, nested skill files can still be read manually, but the coding agent may not automatically apply them.

## 4. Ask The Coding Agent To Build The Agent

Use the installed Agent Kernel skills and the local `SPEC.md` to scaffold and implement the agent. For the sample `waste-sorting-assistant`, give the coding agent this prompt:

```text
Using the Agent Kernel skills pack, read SPEC.md and build the Agent Kernel project in this folder.

Follow the requirements in SPEC.md. Create the project structure, dependencies, configuration, agent implementation, tools, memory/session persistence, local run path, tests, and deployment files described there.
```


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
