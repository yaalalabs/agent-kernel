# 02 · Welcome

| | |
|---|---|
| Artboards | `Start-Welcome` (main), `Start-Welcome-FirstLaunch`, `Start-Welcome-ToolchainMissing`, `Start-Welcome-NotAProject` |
| Design | Built on the [design canvas](https://claude.ai/artifact/VSewdGFtfYAQe4zGFVt3po), page **Start**: 4 of 4 artboards. |
| Canvas page | Start |
| Kind | Page, no desktop shell |
| Fidelity | Static. Buttons and rows are prototype links. |
| Read first | [00-project-brief.md](00-project-brief.md) |

## Job

The first window. There is no sign-in: the app starts from a folder. The user opens an existing project,
starts a new one, and sees at a glance whether this computer has what the app needs.

## Layout

- Two columns: actions and recent projects on the left, the toolchain check on the right.
- The Agent Kernel logo lockup at the top. No marketing copy.

## Content

**Left column**
- Heading "Open a project".
- Primary "Open folder", secondary "New project", and the AI button "Describe a project".
- "Recent" list. Each row: the folder name, its path as a `PathChip`, the marks of the frameworks it uses and
  when it was last opened.

| Folder | Path | Frameworks | Last opened |
|--------|------|------------|-------------|
| support-triage | `~/code/support-triage` | OpenAI Agents SDK, LangGraph, Google ADK | today |
| research-crew | `~/code/research-crew` | CrewAI | 3 days ago |

**Right column: "This computer"**
- `ToolchainRow`s. Versions are placeholders.

| Tool | Needed for | State |
|------|-----------|-------|
| Python 3.12 or 3.13 | Everything | found |
| uv | Everything | found |
| Claude Code | Build with AI | found |
| Terraform | Deploy | found |
| Docker | Containerized deploy targets | found |
| AWS CLI, profile `default` | Deploy to AWS | signed in |
| git | Optional | found |

- A "Recheck" control and a link to app settings.

## Behaviour

- "Open folder" and a recent row go to `Builder-Canvas`.
- "New project" goes to `Start-NewProject-Folder`. "Describe a project" goes to
  `Builder-AIDrawer-FirstExchange`.
- The settings link goes to `Settings-Toolchain`.

## States and variants

| Artboard | Pass | Shows |
|----------|------|-------|
| `Start-Welcome-FirstLaunch` | first | No recent projects. The left column leads with "New project" and one line: "A project is a folder on this computer. Everything the app creates stays in it." |
| `Start-Welcome-ToolchainMissing` | first | uv and Terraform missing. Their rows are in the failed state with install links. A banner: "Install uv to create or run a project". "New project" is disabled; "Open folder" still works. The Terraform row notes that only deploying is affected. |
| `Start-Welcome-NotAProject` | first | After choosing a folder with no Agent Kernel project in it. A modal: "No Agent Kernel project in `~/code/notes`", with "Create a project here", "Choose another folder" and "Cancel". |

## Tweaks

- `toolchain`: column or a compact strip under the actions.

## Handoff notes

- The app recognises a project by the presence of `config.yaml` and a Python file that registers an Agent
  Kernel module. An existing project made without the app opens the same way.
- Tool detection reads the user's own shell environment. The app installs nothing by itself.
