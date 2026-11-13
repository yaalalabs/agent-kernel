# 01 · Sign in

> **Parked for a later phase.** Written for the hosted product, before Phase 1 was scoped as a local desktop
> app. Revise it against the current project brief before designing from it. Brief numbers inside refer to
> the original numbering; see [README.md](README.md) in this folder.

| | |
|---|---|
| Artboards | `Entry-SignIn` (main), `Entry-SignIn-Error`, `Entry-SignUp`, `Entry-SignIn-SSO` |
| Canvas page | Entry |
| Kind | Page, fluid, drawn at 1440 wide. No app shell. |
| Fidelity | Static. Buttons and links are prototype links. |
| Read first | [00-project-brief.md](../00-project-brief.md) |

## Job

The entry point of the SaaS. Single sign-on first, email second. The other half of the page shows what the
product is by rendering a small real piece of it.

## Layout

- Two columns: a brand panel (a little over half) and a form panel.
- At narrow widths the form comes first and the brand panel drops below it.

## Content

**Brand panel**
- The Agent Kernel logo lockup (real asset) and the name "Agent Kernel Studio".
- A read-only mini canvas built from the real `CanvasNode`, `Edge` and `DeploymentFrame` components: a Slack
  channel node routes to **triage** (OpenAI Agents SDK, gpt-4o), which hands off to **billing** (LangGraph,
  claude-sonnet-4-5) and **kb-researcher** (Google ADK, gemini-2.5-pro), inside a frame labelled
  "AWS ECS Fargate · queue mode".
- Heading "Build, run and ship production agents".
- Three proof lines with check icons: "8 agent frameworks, one runtime", "Slack, Teams, WhatsApp, Gmail and
  more built in", "Deploy to AWS, Azure, GCP or Kubernetes".

**Form panel**
- "Sign in to your workspace", helper "Use your company identity or email".
- Three buttons: "Continue with Google", "Continue with GitHub", "Continue with Microsoft".
- Divider "or". Fields "Work email" and "Password". A "Keep me signed in" checkbox and a "Forgot password?"
  link.
- Primary button "Continue". Below it "Use single sign-on (SSO)" and "New to Agent Kernel Studio? Create an
  account".
- Footer line: "Apache 2.0 open-source runtime · Terms · Privacy".

Do not add version strings, cluster or uptime lines, testimonials or statistics.

## Behaviour

- "Continue" and the three identity buttons go to `Home-Dashboard`.
- "Create an account" goes to `Entry-SignUp`. Its "Create account" goes to `Entry-Onboarding-Workspace`.
- "Use single sign-on (SSO)" goes to `Entry-SignIn-SSO`.

## States and variants

| Artboard | Pass | Shows |
|----------|------|-------|
| `Entry-SignIn-Error` | first | Password field in its error state with the message "Incorrect email or password" |
| `Entry-SignUp` | first | Full name, work email, password, an "I agree to the Terms" checkbox, primary "Create account", link "Already have an account? Sign in" |
| `Entry-SignIn-SSO` | second | A single "Workspace URL" field with the suffix `.[YOUR DOMAIN]`, primary "Continue with SSO", link "Sign in with email instead" |

## Tweaks

- `brandPanel`: canvas preview or logo only.

## Open details

- Which identity providers the product really supports. The three shown are examples.
- The product domain for workspace URLs.
