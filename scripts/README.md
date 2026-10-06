# Scripts

This directory contains utility scripts for the agent-kernel project.

## sync_blogs/

Syncs the website's blog posts to Hashnode (`hashnode.py`) and DEV Community (`devto.py`).
Helpers both scripts share live in `sync_blogs/utils/`: `common.py` (post/frontmatter
parsing, authors, sync state, dates, URLs) and `images.py` (the SVG image check below).
The only dependency is `pyyaml`.

**No SVG images in blog posts.** DEV Community and Hashnode can't display SVG images and
neither has an upload API, so a post with one would publish with a broken image. Use
PNG/JPEG/GIF/WebP instead (body images and the frontmatter `image`). The docs deploy runs
`python scripts/sync_blogs/check_images.py` before building the website, and both sync scripts
run the same check across every post before publishing, so an SVG image fails the run before
anything is published. Plain links to an `.svg` file are fine, and so are shields.io badges:
both syncs point them at shields' PNG endpoint (`raster.shields.io`).

**Sync state through a PR.** `develop` only accepts changes through pull requests, so CI
records the updated sync-state files in one PR from the `chore/blog-sync-state` branch instead
of pushing them. Until that PR is merged, each run starts from the state files on that branch
and adds its changes to the same PR. Each sync job loads and commits both platforms' state
files (the PR is rebuilt from the job's files, so leaving one out would drop the other sync's
unmerged changes), and the Hashnode job runs after the DEV one. Merging the PR doesn't redeploy
the website.

**Duplicate protection.** A post with no record in the state file (a new post, or a lost or
stale state file) is first looked up on the platform by its canonical URL: DEV's organization
articles (`DEVTO_ORGANIZATION_ID`) or Hashnode's publication posts. This takes one list request
per run, and only when such a post exists. If the post is already there it is updated instead,
so a lost state file causes at most a one-off redundant update, never a duplicate article.

**Rate limits.** Both scripts retry a rate-limited request up to 5 times, waiting for the
server's `Retry-After` (else 30s).

### sync_blogs/hashnode.py

Publishes `docs/blog/*.md` posts to a Hashnode publication so blog content gets
Hashnode's reach on top of the Agent Kernel website. Runnable locally; its job in
`.github/workflows/deploy-docs.yml` (`sync-hashnode`) is commented out for now, as only DEV
Community is published to at the moment.

**How it works:**
- A blog file that has never been synced is published to Hashnode right away
  (no draft step).
- A blog file that was synced and then edited has its Hashnode post updated in
  place, so the website stays the single source of truth.
- A JSON state file (`docs/blog/.hashnode-sync-state.json`, recorded by CI through the
  sync-state PR) tracks which posts are synced, their Hashnode post id, and a content hash.
- A post with no state record is matched against the publication's posts by canonical URL
  first (see *Duplicate protection* above). Hashnode returns at most 100 posts per page, so
  the lookup follows the cursor through every page.

**Authors:** every post is published by the single Agent Kernel account that owns the
publication (one Pro seat). The real authors from the post's `authors` frontmatter
(resolved through `docs/blog/authors.json`) are credited in the Hashnode subtitle
(*"By A & B"*) and in a linked byline at the top of the post body.

**Original source and date:** each post's `originalArticleURL` (canonical) points at its
kernel.yaala.ai page, and `publishedAt` is backdated to the date it went live on the
website - the frontmatter `date` when set, otherwise the `YYYY-MM-DD-` filename prefix
(the same rule Docusaurus uses). A footer line also links back to the website.

**Requirements:** Hashnode's GraphQL API (`https://gql-beta.hashnode.com`; the old
`gql.hashnode.com` was retired on 2026-05-13) needs the publication to be on the **Pro**
plan, for reads and writes alike. Its Cloudflare front rejects Python's default
User-Agent, so the script sends its own. Rate limits are 20,000 queries and 500 mutations per
minute; a rate-limited request (HTTP 429, or a GraphQL rate-limit error) is retried.

**Usage:**
```bash
pip install pyyaml

export HASHNODE_PAT=...                  # Personal Access Token (Account settings -> Developer)
export HASHNODE_PUBLICATION_ID=...       # the publication to publish to

# Find the id to put in HASHNODE_PUBLICATION_ID
python scripts/sync_blogs/hashnode.py --find-publication agentkernel.hashnode.dev

# Write the Markdown that would be sent next to each post (<post>.hashnode-preview.md, gitignored); no token needed
python scripts/sync_blogs/hashnode.py --preview

# Print what would be published/updated, without calling the Hashnode API
python scripts/sync_blogs/hashnode.py --dry-run

# Publish new posts and update changed ones
python scripts/sync_blogs/hashnode.py

# Sync just one post (repeat --post for several)
python scripts/sync_blogs/hashnode.py --post 2026-09-14-scheduled-tasks.md
```

**Options:**
- `--blog-dir`: directory of blog markdown files (default: `docs/blog`)
- `--state-file`: path to the sync-state JSON file (default: `<blog-dir>/.hashnode-sync-state.json`)
- `--site-url`: canonical site origin used for `originalArticleURL` and for absolutizing image/link paths (default: `https://kernel.yaala.ai`)
- `--preview`: write the rendered Markdown and post metadata to `<post>.hashnode-preview.md`; no API calls
- `--dry-run`: print what would be published or updated without writing to Hashnode or the state file
- `--find-publication HOST`: print the id of the publication at `HOST`, then exit
- `--post FILE`: only sync this post (file name under `--blog-dir`); repeatable. Default: every post

**Content conversion:** Docusaurus-only syntax is rewritten into plain Markdown - `<Tabs>`
become headed sections, `:::` admonitions become blockquotes, JSX `<div>` image/badge/caption
blocks become Markdown images and italic captions, the leading `# Title` is dropped (Hashnode
renders the title itself), and root-relative links/images are made absolute. Docusaurus code
fence metadata (```` ```yaml title="config.yaml" ````) is stripped to the language, with the
`title` shown as a bold label above the block.

**Tags:** Hashnode allows at most 5 tags per post, so the first 5 frontmatter tags are used
(as slugs, e.g. `AI Agents` -> `ai-agents`).

**Opting a post out:** add `hashnode: false` to that post's frontmatter.

**CI secrets:** `HASHNODE_PAT` and `HASHNODE_PUBLICATION_ID` (GitHub repo -> Settings ->
Secrets and variables -> Actions). If either is missing, the workflow job skips the sync.

**Syncing a single post from CI:** once the `sync-hashnode` job is re-enabled, run the *Deploy
GitHub Pages* workflow manually (Actions -> Run workflow) and fill in `hashnode_post` with the
blog file name. Pushes to `develop` still sync every new/changed post.

### sync_blogs/devto.py

Publishes `docs/blog/*.md` posts to DEV Community (dev.to), the same way
`sync_blogs/hashnode.py` does for Hashnode. Run automatically by
`.github/workflows/deploy-docs.yml` (the `sync-devto` job) after every docs deploy; also
runnable locally.

**How it works:**
- A blog file that has never been synced is published to DEV right away (no draft step).
- A blog file that was synced and then edited has its DEV article updated in place.
- A JSON state file (`docs/blog/.devto-sync-state.json`, recorded by CI through the sync-state PR) tracks
  which posts are synced, their DEV article id, and a content hash.
- A post with no state record (a new post, or a lost or stale state file) is first looked up
  among the organization's articles on DEV by its canonical URL (one list call per run, only
  when needed; needs `DEVTO_ORGANIZATION_ID`). If it is already there, that article is updated
  instead, so a lost state file can't cause duplicate articles, only a one-off redundant update.

**Authors:** every article is published by the account that owns the API key, optionally
under a DEV organization (`DEVTO_ORGANIZATION_ID`). DEV has no subtitle field, so the real
authors from `docs/blog/authors.json` are credited in a linked byline at the top of the body.

**Original source and date:** each article's `canonical_url` points at its kernel.yaala.ai
page. DEV's API cannot backdate an article, so the date the post went live on the website
(frontmatter `date`, else the `YYYY-MM-DD-` filename prefix) is stated in the
*"Originally published at kernel.yaala.ai on ..."* footer instead.

**Tags:** DEV allows at most 4 tags per article, lowercase alphanumeric only, so the first 4
frontmatter tags are used with non-alphanumerics removed (`ai-agents` -> `aiagents`).

**Usage:**
```bash
pip install pyyaml

export DEVTO_API_KEY=...                 # Settings -> Extensions -> DEV Community API Keys
export DEVTO_ORGANIZATION_ID=...         # optional: publish under this organization

# Find the id to put in DEVTO_ORGANIZATION_ID (no API key needed)
python scripts/sync_blogs/devto.py --find-organization agentkernel

# Write the Markdown that would be sent next to each post (<post>.devto-preview.md, gitignored); no API key needed
python scripts/sync_blogs/devto.py --preview

# Print what would be published/updated, without calling the DEV API
python scripts/sync_blogs/devto.py --dry-run

# Publish new posts and update changed ones
python scripts/sync_blogs/devto.py

# Sync just one post (repeat --post for several)
python scripts/sync_blogs/devto.py --post 2026-09-14-scheduled-tasks.md
```

**Options:**
- `--blog-dir`: directory of blog markdown files (default: `docs/blog`)
- `--state-file`: path to the sync-state JSON file (default: `<blog-dir>/.devto-sync-state.json`)
- `--site-url`: canonical site origin used for `canonical_url` and for absolutizing image/link paths (default: `https://kernel.yaala.ai`)
- `--preview`: write the rendered Markdown and article metadata to `<post>.devto-preview.md`; no API calls
- `--dry-run`: print what would be published or updated without writing to DEV or the state file
- `--find-organization USERNAME`: print the id of the DEV organization at `dev.to/USERNAME`, then exit
- `--post FILE`: only sync this post (file name under `--blog-dir`); repeatable. Default: every post

**Content conversion:** identical to the Hashnode sync - `<Tabs>` become headed sections,
`:::` admonitions become blockquotes, JSX `<div>` blocks become Markdown images and captions
(which also removes the `style={{...}}` props DEV would otherwise parse as Liquid tags), the
leading `# Title` is dropped, root-relative links/images are made absolute, and code fence
metadata is stripped (DEV only recognizes a bare language after a code fence; without this the
block breaks and swallows the text after it).

**Rate limits:** DEV throttles article writes; on HTTP 429 the script waits (`Retry-After`,
else 30s) and retries, so a first full sync of every post just takes a few minutes.

**Opting a post out:** add `devto: false` to that post's frontmatter.

**CI secrets:** `DEVTO_API_KEY` (required) and `DEVTO_ORGANIZATION_ID` (optional). If the
API key is missing, the workflow job skips the sync.

**Syncing a single post from CI:** run the *Deploy GitHub Pages* workflow manually and fill in
`devto_post` with the blog file name.

## bump_version.py

Handles semantic versioning for the project with support for:
- Major, minor, and patch version bumps
- Pre-release versions (alpha, beta)
- Automatic pre-release number determination

**Usage:**
```bash
cd ak-py
python ../scripts/bump_version.py --bump patch
python ../scripts/bump_version.py --bump minor --prerelease alpha --auto-prerelease-number
python ../scripts/bump_version.py --bump major --prerelease beta --prerelease-number 2
```

## update_examples_version.py

Updates agentkernel version references in example `pyproject.toml` files and optionally regenerates `uv.lock` files.

**Usage:**
```bash
# Update pyproject.toml files only (skip lock regeneration)
python scripts/update_examples_version.py --version 0.2.0 --skip-lock

# Update pyproject.toml and regenerate lock files with retry logic
python scripts/update_examples_version.py --version 0.2.0 --lock-retries 5 --lock-retry-delay 30

# Force regenerate lock files even if pyproject.toml hasn't changed
python scripts/update_examples_version.py --version 0.2.0 --force-lock --lock-retries 5

# Dry run to see what would change
python scripts/update_examples_version.py --version 0.2.0 --dry-run
```

**Options:**
- `--version`: New version to set (required unless --force-lock is used)
- `--skip-lock`: Skip regenerating uv.lock files
- `--force-lock`: Force regenerate uv.lock files even if pyproject.toml hasn't changed
- `--lock-retries`: Number of retry attempts for lock regeneration (default: 3)
- `--lock-retry-delay`: Delay in seconds between retries (default: 10)
- `--dry-run`: Show what would be changed without making modifications

**Note on PyPI Propagation:**
When running immediately after publishing to PyPI, the new package version may not be available yet. The script includes retry logic with a delay between retries, but in CI/CD pipelines, it's recommended to:
1. First update `pyproject.toml` files with `--skip-lock`
2. Wait 60-120 seconds for PyPI propagation
3. Then regenerate lock files with increased retry attempts

## update_terraform_versions.py

Updates Terraform module versions for all `yaalalabs/ak-*` modules in `.tf` files.

**Usage:**
```bash
# Update all Terraform module versions
python scripts/update_terraform_versions.py --version 0.2.0-b5

# Dry run to see what would change
python scripts/update_terraform_versions.py --version 0.2.0-b5 --dry-run

# Specify custom directories to search
python scripts/update_terraform_versions.py --version 0.2.0-b5 --directories ak-deployment examples

# Add custom exclusion patterns
python scripts/update_terraform_versions.py --version 0.2.0-b5 --exclude .terraform .backup
```

**Options:**
- `--version`: New version to set for all yaalalabs/ak-* modules (required)
- `--directories`: Directories to search for .tf files (default: ak-deployment examples)
- `--exclude`: Patterns to exclude from search (default: .terraform)
- `--dry-run`: Show what would be changed without making modifications

**What it does:**
- Scans all `.tf` files in specified directories
- Finds module declarations with `source = "yaalalabs/ak-*"` or `source = "app.terraform.io/yaalalabs/ak-*"`
- Updates the corresponding `version` attribute to the specified version
- Skips non-yaalalabs modules (like terraform-aws-modules)
- Excludes `.terraform` directories by default

## update_chart_versions.py

Pins the published Helm chart version wherever it is installed from: every
`oci://ghcr.io/yaalalabs/charts/agent-kernel --version X.Y.Z` reference in `.md`, `.yaml`, and `.yml` files under the examples, the chart README and `Chart.yaml` description, the docs site source, and the bundled `ak-cloud-deploy` skill, in the root `README.md` (what GitHub renders on the chart's GHCR package page), plus the `CHART_VERSION="X.Y.Z"` variable in the k8s examples' `deploy/deploy.sh` scripts (only `.sh` files that name the chart qualify). The publish workflow runs it for each release (before the wheel is built, so the skill inside it carries the new pin), so every surface installs the chart version that release publishes.

**Usage:**
```bash
# Pin every chart reference to a version (SemVer 2, as on the release tag)
python scripts/update_chart_versions.py --version 0.9.1

# Prereleases use the hyphenated tag form, which Helm accepts (PEP 440's 1.0.0a1 is rejected)
python scripts/update_chart_versions.py --version 1.0.0-a1

# Dry run to see what would change
python scripts/update_chart_versions.py --version 0.9.1 --dry-run

# Specify custom directories to search
python scripts/update_chart_versions.py --version 0.9.1 --directories examples
```

**Options:**
- `--version`: New chart version to set (required; must be SemVer 2)
- `--directories`: Directories or files to search (default: examples ak-deployment docs/docs ak-py/src/agentkernel/skills README.md)
- `--exclude`: Path segments to exclude from search (default: .venv node_modules .terraform __pycache__ versioned_docs)
- `--dry-run`: Show what would be changed without making modifications

**What it does:**
- Scans `.md`, `.yaml`, `.yml`, and `.sh` files in the specified directories (an entry that names a file is scanned as given)
- Rewrites only the version token after `oci://ghcr.io/yaalalabs/charts/agent-kernel --version` (and inside `CHART_VERSION="..."` in deploy scripts that reference the chart), leaving prose, shell continuations, and comment markers as they are
- Leaves references already at the target version, and installs from a local chart path, untouched

## Provisioning

The `provision.sh` script is used to give you an idea of what should be the done before deploying the project to a cloud provider. It will check for the necessary tools and permissions, and will also check for the existence of the required resources.

>**Note:** The script is not needed to be used as-is. It's meant to be a starting point for your own provisioning scripts. also use this to identify what is the minimum permissions required for the project to work.

### Azure

To provision an Azure environment, run the following command:

```bash
./provision.sh --provider azure
```

This will check for the necessary tools and permissions, and will also check for the existence of the required resources. Also, enable the necessary Azure resource providers. including some roles that are required for the project to work.

### AWS

To provision an AWS environment, run the following command:

```bash
./provision.sh --provider aws
```

This will check for the necessary tools and permissions. Will check for basic AWS configurations and permissions.