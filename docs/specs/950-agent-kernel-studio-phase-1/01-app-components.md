# 01 · Desktop shell and app components

| | |
|---|---|
| Artboards | `System-Foundations`, `System-Shell`, `System-Controls`, `System-Data`, `System-Canvas`, `System-Chat`, `System-Local`, `System-Overlays` |
| Design | Partly built on the [design canvas](https://claude.ai/artifact/VSewdGFtfYAQe4zGFVt3po), page **System**: the shell components `TopBar`, `StatusBar` and `BottomPanel`, imported by every screen. The specimen artboards listed above are not drawn; the other app components are drawn inline in the screens that use them. |
| Canvas page | System |
| Kind | Specimen artboards, fixed size, one per group |
| Fidelity | Static, every state shown side by side |
| Build order | **First**, before any screen. Screens import these components. |
| Read first | [00-project-brief.md](00-project-brief.md) |

## Job

The Agent Kernel Design System covers brand, tokens and seven primitives. A desktop builder needs more. This
brief inventories the components to build once on the System page and import into every screen. It comes
first, because Claude Design reuses components across artboards.

## From the design system (mount, do not redraw)

Button (primary, secondary, outline, ghost), Badge, Tag, Card, Input, CodeBlock, GradientHeading.

## To build (names are the intended code names)

**Foundations** (`System-Foundations`)
- The app density scale from brief 00: type sizes, row heights, spacing steps.
- The colour roles table from brief 00 as swatches with their token names.

**Shell** (`System-Shell`)
- `DesktopShell`, `TopBar`, `ProjectSwitcher` (closed, open), `AppTabs` (each tab active once),
  `RunControl` (stopped, starting, running, failed), `DeployStatus` (not deployed, deployed, applying, failed).
- `BottomPanel` (collapsed, open on each of Problems, Run log, Commands), `StatusBar`.
- `BuildWithAIDrawer` (docked right, docked bottom; views Chat, Code, Rules).
- `Tabs` (underline, for use inside a screen).

**Controls** (`System-Controls`)
- Button variants the system lacks: `AIButton` (magenta outline, sparkle icon), `IconButton`, a danger
  button. Each in default, hover, focus, disabled.
- `Select`, `Textarea`, `Toggle`, `Checkbox`, `Radio`, `Slider`, `SegmentedControl`, `KeyValueEditor`,
  `FolderField` (a path with a "Choose" control), `CodeEditor` (line numbers, gutter markers, inline
  annotation).
- Chips: `StatusChip` (passed, running, waiting, failed, not set up), `FrameworkChip` (logo plus name, one per
  framework), `ModelChip`, `PathChip` (a file or folder path, with reveal and copy), `SecretChip` (key name
  plus where it is stored, never a value), `AIBadge` ("Added by Claude Code").

**Data** (`System-Data`)
- `DataTable` (header; row default, hover, selected), `ProgressBar`, `SpanTree`, `Waterfall`,
  `ResultSquares`, `DiffView`, `JSONTree`, `FileTree` (with markers for changed, new and AI-written files).

**Canvas** (`System-Canvas`)
- `CanvasNode` variants: agent, tool, knowledge, channel, store, guardrail. States: default, selected,
  AI-generated, error.
- `Port` (default, connected), `Edge` (routing, handoff with label, binding, generated), `DeployFrame`
  (not deployed, deployed), `PaletteTile` (default, dragging), `DropTarget`, `MiniMap`, `ZoomControl`.

**Chat and runs** (`System-Chat`)
- `UserBubble`, `AgentMessage` (with agent avatar), `ReasoningBlock`, `ToolCallCard`, `HandoffDivider`,
  `PlanCard`, `ApprovalCard` (pending, approved, denied), `CanvasChangesCard`, `StreamEventRow`, `Composer`,
  `RuleCard` (enforced, drafted, out of sync, AI-added), `AnnotationPill`.

**Local machine** (`System-Local`)
- `CommandRow`: one command the app ran, with its working directory, duration and exit status (running,
  succeeded, failed), expandable to its output.
- `LogStream`: streaming process output with follow and clear.
- `ToolchainRow`: a tool, its detected path, its state (found, missing, wrong version) and an install link.
- `CheckRow`: one prerequisite check with a status, a detail and an action.
- `PlanSummary`: a Terraform plan as three counts (to add, to change, to destroy) and a grouped resource list.
- `VariableForm`: Terraform variables as labelled fields, with required markers and secret fields shown as
  `SecretChip`s.
- `OutputList`: Terraform outputs as name and value rows with copy.
- `ChangeOnDiskBanner`: a file changed outside the app.

**Overlays and feedback** (`System-Overlays`)
- `Modal`, `ConfirmModal` (a destructive variant that names what will be affected), `Drawer`, `ContextMenu`,
  `Popover`, `Tooltip`, `Toast` (success, warning, error), `InlineBanner`, `EmptyState`, `Skeleton`, `Spinner`.

## Rules

- Every interactive component shows default, hover, focus and disabled.
- Edge types differ by more than colour: solid for routing and handoffs, dashed for bindings.
- `ApprovalCard` is one component. It serves agent approvals in a test run and coding-agent permission
  requests in the Build with AI drawer.
- `CommandRow` always shows the literal command. The app never hides what it runs.
- The empty, loading and error patterns (`EmptyState`, `Skeleton`, `InlineBanner`) are defined here once.
  Screen briefs name only the states that need a specific design.

## Tweaks

- `density`: comfortable or compact, applied across all specimen artboards.

## Handoff notes

- Once approved, these are candidates to add to the Agent Kernel Design System so later designs reuse them.
- A component that appears on no Phase 1 screen should be removed before handoff.
