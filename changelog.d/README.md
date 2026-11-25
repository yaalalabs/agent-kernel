# Changelog fragments

Each pull request with a change users would notice adds one file here. At release time the
Publish workflow compiles the files into a new section of [CHANGELOG.md](../CHANGELOG.md) with
[towncrier](https://towncrier.readthedocs.io/) and deletes them. Never edit `CHANGELOG.md` to add
an entry.

## File name

`<issue>.<type>.md`, where `<issue>` is the GitHub issue the PR fixes.

- A second entry for the same issue and type adds a counter: `664.added.1.md`.
- A PR with no issue uses `+<short-slug>.<type>.md` (rendered without a link).

| Type | Use it for |
| --- | --- |
| `breaking` | Anything that makes existing code, config or deployments stop working. Say what to change: "To migrate, ..." |
| `added` | New capability, framework, provider, deployment target, config key, API field or CLI flag |
| `changed` | Changed behaviour or default that keeps working without changes |
| `deprecated` | Something still works but will be removed |
| `removed` | Something removed that nobody should still depend on (otherwise use `breaking`) |
| `fixed` | A bug a user could have hit |
| `security` | A security fix |

## Content

One to three sentences of Markdown for someone using OAK, not for its developers: what changed in
their terms (config key, API field, CLI flag, deployment target), with a link to the docs page when
there is one. Name the surface when it is not the Python package ("Helm chart: ...",
"Terraform: ..."). The issue link is added for you.

Example, `changelog.d/629.added.md`:

```markdown
Defer a chat to a later time or a cron cadence with a `schedule` block on the chat request, and
list, pause or cancel schedules through `/api/v1/schedules`. See
[Scheduling](https://kernel.yaala.ai/docs/advanced/scheduling).
```

Example, `changelog.d/984.breaking.md`:

```markdown
Remove the Azure Functions deployment target. To migrate, deploy to Azure Container Apps
([Azure containerized](https://kernel.yaala.ai/docs/deployment/azure-containerized)).
```

Preview what the next release will say: `uvx towncrier@26.9.0 build --draft --version next`.

Full rules: [CONTRIBUTING.md, "Changelog entries"](../CONTRIBUTING.md#changelog-entries).
