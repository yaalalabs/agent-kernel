# 09 · App settings

| | |
|---|---|
| Artboards | `Settings-Toolchain` (main), `Settings-CodingAgents`, `Settings-Cloud`, `Settings-Secrets`, `Settings-General` |
| Design | Built on the [design canvas](https://claude.ai/artifact/VSewdGFtfYAQe4zGFVt3po), page **Settings**: 5 of 5 artboards. |
| Canvas page | Settings |
| Kind | Page with the top bar of `DesktopShell`, a settings sub-navigation and a "Back to project" link |
| Fidelity | Static. The sub-navigation links the artboards. |
| Story moment | B, ready to ship |
| Read first | [00-project-brief.md](00-project-brief.md) |

## Job

Settings for this computer and this project. There are no accounts, members or billing. The page answers: what
is installed, which coding agent may do what, which cloud profile deploys use, and which secrets the project
expects.

## Layout

- A sub-navigation on the left: Toolchain, Coding agents, Cloud, Secrets, General.
- Content on the right in a readable column.

## Content

**`Settings-Toolchain`**
- Header "Toolchain", description "The app uses the tools already installed on this computer. It installs
  nothing by itself."
- `ToolchainRow`s: Python 3.12 or 3.13, uv, git, Claude Code, Terraform, Docker, AWS CLI. Each shows its
  detected path (`[PATH]`), its version (`[VERSION]`), its state and what it is needed for.
- "Recheck", and a field to point at a tool that was not found automatically.

**`Settings-CodingAgents`**
- Card "Claude Code": state "Connected"; path `[PATH]`; a line "Signed in to Claude Code with your own account.
  The app never reads or stores your Claude credentials."; "Skills installed in this project": ak-init,
  ak-build, ak-add-capabilities, ak-add-integration, ak-test, ak-cloud-deploy, with "Update skills".
- Permissions for this project: a toggle "Edit project files", on; a choice "Running commands": "Ask every
  time" (selected) or "Allow listed commands", with the list (`uv run pytest`); a locked row "Never apply or
  destroy Terraform".
- A toggle "Take a checkpoint before each turn", on.
- Rows for Codex, Cursor, Windsurf and GitHub Copilot, each "Not set up", under the note "More coding agents
  connect in a later release".

**`Settings-Cloud`**
- A note: "Deploys use the profiles configured on this computer. The app stores no cloud credentials."
- AWS: profile select `default`, account `[ACCOUNT]`, default region eu-west-1, state "Signed in".
- Azure: "Not signed in", with the command `az login`.
- Google Cloud: "Not signed in", with the command `gcloud auth application-default login`.

**`Settings-Secrets`**
- Header "Secrets", description "Keys this project expects. Values stay in `.env` on this computer, which git
  ignores. The app shows names only."
- A `DataTable`. Values are never shown.

| Key | Kept in | Used by | State |
|-----|---------|---------|-------|
| OPENAI_API_KEY | `.env` | triage, OpenAI Guardrails | set |
| ANTHROPIC_API_KEY | `.env` | billing | set |
| GOOGLE_API_KEY | `.env` | kb-researcher | set |
| SLACK_BOT_TOKEN | `.env` | Slack | set |
| SLACK_SIGNING_SECRET | `.env` | Slack | set |
| WALLED_API_KEY | `.env` | Walled AI | set |
| LANGFUSE_SECRET_KEY | `.env` | Langfuse | missing |

- "Add key". A note: "When deploying, keys are passed to Terraform at run time and are not written to
  `terraform.tfvars`."

**`Settings-General`**
- "Default location for new projects" as a `FolderField`: `~/code`.
- "Open files with": the system default editor.
- "Theme": a choice of "System" (selected), "Light" and "Dark".
- "Usage data": a toggle "Send anonymous usage data to help improve the app", off, with the line "Off by
  default. With it off, the app sends nothing of its own."

## Behaviour

- The sub-navigation links the five artboards. "Back to project" goes to `Builder-Canvas`.

## Tweaks

- `subNav`: left column or top tabs.

## Handoff notes

- Toolchain and cloud settings belong to the computer. Coding-agent permissions and secrets belong to the
  project and live in the working directory.
- Local keys use OAK's `env` secret provider. A cloud secret store is chosen per deploy target, in
  `config.yaml`.
- A secret is a key name plus the provider that resolves it (`secret.provider.type` in `config.yaml`: `env`,
  `aws_ssm`, `kubernetes`, or a dotted path). The Secrets table reads the provider from `config.yaml` and shows
  `.env` for the `env` provider. The app never assumes `.env` is the only store, so a later hosted Studio can
  resolve the same names from its own store without changing the project.
- A missing key is the same condition that stops a local run in brief 07.
- Usage data is off by default and opt-in. With it off, the app makes no network calls of its own; the tools it
  runs and the project's model providers make their own.
