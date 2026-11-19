# Rebrand to Open Agent Kernel (OAK): documentation and website

Agent Kernel becomes **Open Agent Kernel**, shortened to **OAK**. This change applies the new name and the
new visual identity (mark, lockups, colour palette) to the documentation, the top-level README and the
website. Code and repository structure keep their current names and are renamed in a later change.

No GitHub issue exists for this work yet, so the folder is un-numbered (see Open questions).

## Motivation

- The brand guide in `branding/source/` ("Agent Kernel Logo Refinement & Extension", version 3, November 2026) defines:
  - a new mark and three lockups: Primary ("OPEN AGENT KERNEL"), OAK Horizontal, OAK Vertical
  - five colours: Tiger Flame Orange `#FF5E32`, Prussian Blue `#02284F`, Dusk Blue `#3F598A`, Pale Sky `#ABCEE1`, Baby Blue Ice `#B1CDFF`
  - four gradient blocks
  - no typography
- The old name is in most user-facing prose:
  - 271 in-scope markdown files, 1,042 occurrences (per-area table in `spec.md`)
  - site source: 151 occurrences in 24 `.tsx` files, 15 in `docs/docusaurus.config.js` (site title at `:11`)
- The site theme is the old identity:
  - cyan `#00DDFF` and magenta `#F200FF` on near-black `#010002` (`docs/src/css/custom.css:11-27`)
  - dark only (`docs/docusaurus.config.js:514-516`)
  - colours are mostly hard-coded: 195 distinct hex values in 39 files, 1,306 lines with `rgb()`/`rgba()` in 41 files
- Media that bake in the old mark:
  - `docs/static/video/hero.mp4` (8.7 MB), used at `docs/src/pages/index.tsx:307`, `features.tsx:403`, `use-cases.tsx:530`
  - `docs/static/img/cta-bg.png`, used in 7 places
  - `docs/static/img/card.png`, the favicon set, `docs/static/img/logo.svg`, nine SVGs in `docs/static/img/branding/`
- `/docs` serves the frozen `0.10.1` snapshot, which is byte-identical to `docs/docs` today.
  - Renaming only `docs/docs` would leave the default docs pages on the old name until the next release.
- `branding/source/` is 23 MB (13 MB `.ai`, 4 MB PDF, 5 MB of guide pages); its 22 SVGs total 50 KB.

## Requirements

### Naming

- Full name: "Open Agent Kernel". Short name: "OAK", always capitals.
- Where each form is used:
  - page titles, H1s, sidebar labels, SEO metadata, image alt text: "Open Agent Kernel"
  - first mention in the body of a page: "Open Agent Kernel (OAK)"
  - every later mention on that page, and H2 or lower headings: "OAK"
  - diagram node labels: "OAK"
- The prose abbreviation "AK" becomes "OAK" ("AK session" becomes "OAK session").
- "Agent Kernel by Yaala Labs" becomes "Open Agent Kernel by Yaala Labs".
- Identifiers do not change:
  - `agentkernel`, the `ak` CLI, `AKConfig` and every other class, `AK_*` environment variables, config keys
  - `ak-py`, `ak-deployment`, skill names (`ak-init`, `ak-dev-*`)
  - `yaalalabs/agent-kernel` URLs, `kernel.yaala.ai`, the PyPI project name
- Product output stays verbatim:
  - text inside code spans and code blocks is never rewritten
  - strings the product emits keep their emitted form when quoted (the OpenAPI title "Agent Kernel REST API", trace span names such as "Agent Kernel Claude", the `AgentKernel` service name, the CLI banner)
- Search continuity: "Agent Kernel" stays in the site's structured data as an alternate name and in the keyword list.

### Scope

- In scope:
  - root `README.md`, `CONTRIBUTING.md`, `DEVELOPER_GUIDE.md`, `SECURITY.md`, `AGENTS.md`
  - `docs/docs` and the `docs/versioned_docs/version-0.10.1` snapshot
  - website copy: `docs/docusaurus.config.js`, `docs/src/**/*.tsx`, the three legal pages, `docs/static/robots.txt`, `docs/blog/authors.json`, `docs/README.md`, `docs/SETUP.md`
  - `ak-py/README.md`
  - markdown under `examples/`, `use-cases/`, `ak-deployment/`, `e2e/`, `agent/`, `scripts/`
  - prose of the dev skills (`.agents/skills/`) and the bundled skills (`ak-py/src/agentkernel/skills/**/*.md`)
  - `.github/ISSUE_TEMPLATE/*.md`, `.github/SPRINT_ROLLOVER.md`
- The `0.10.1` snapshot is a one-time exception to the frozen-snapshot rule (`AGENTS.md:178`).
  - The rule itself stays; the 20 older versions are not touched.

### Brand assets

- A top-level `branding/` folder is the canonical home of the logo set.
  - holds the 22 SVGs under kebab-case names, grouped by lockup
  - holds a `README.md` with the palette, the gradients and which lockup goes where
  - `branding/source/` is ignored by git
- The site keeps only the files it serves, under `docs/static/img/branding/`.
  - the nine old `agent-kernel-*` SVGs are deleted
- Paths that outside pages may link to keep their names and get new content: `img/favicon.ico`, `img/logo.svg`, `img/card.png`.
- Lockup usage:
  - navbar: Primary lockup (colour on the light mode, white and orange on the dark mode)
  - docs sidebar: OAK Horizontal, at a smaller size than the navbar logo
  - footer, chatbot header: OAK Horizontal, white and orange
  - root README: Primary lockup, colour on light schemes, white and orange on dark schemes
  - favicon set and in-page icons: the mark in Tiger Flame Orange
  - social card: Primary lockup, white and orange, on the blue gradient

### Colour theme

- The site has two colour modes. Dark is the default; a navbar switch selects the light mode and the choice is remembered.
  - both modes use the same token names, so a component never branches on the mode
  - the footer stays navy in both modes
- Role mapping:
  - dark mode: page background a darker step of Prussian Blue, cards and raised surfaces Prussian Blue
  - light mode: page background white, raised surfaces cool tints toward Pale Sky, text Prussian Blue
  - accent: Tiger Flame Orange
  - ambient: Baby Blue Ice and Pale Sky in the dark mode, Dusk Blue in the light mode
  - borders and muted text: Dusk Blue tints
- Orange is the accent, not the wallpaper.
  - accent uses: calls to action, links, active and selected states, focus rings, gradient headline words, the mark, the OAK node in diagrams
  - ambient uses: card borders, glows, shadows, grid backgrounds, diagram strokes and connectors, particles, code highlights
- Token names:
  - the `--ak-` prefix stays
  - `--ak-blue*` stays and becomes the ambient blue
  - a new `--ak-primary*` family carries the accent
  - `--ak-purple*` is removed
- No file under `docs/src` keeps a hard-coded cyan, magenta or near-black from the old palette.
- Contrast:
  - body text and links meet WCAG AA (4.5:1) on the page background and raised surfaces of both modes
  - orange used as text on white is darkened to `#D23F17` (4.6:1); orange fills keep `#FF5E32`
  - labels on orange fills use the dark navy (6.10:1), never white (3.04:1)
- The three persona pages (developer, AI engineer, business leader) use the brand palette. Their former
  per-persona accents (amber, green, magenta) are removed, and they follow the colour mode like every other page.
- Status colours (success, error, warning) and vendor colours (AWS, Azure, Google, integration logos) do not change.
- Typography does not change (Archivo, JetBrains Mono).
- Diagrams follow the theme:
  - the Mermaid theme variables in `docs/docusaurus.config.js:533`
  - the hard-coded `style` fills in the 29 `docs/docs` pages that use the Docusaurus default greens

### Hero and call-to-action visuals

- `hero.mp4` and `cta-bg.png` are removed from the site and the repository.
- One code-drawn component, built from the mark's SVG paths, replaces them at all 10 call sites.
  - the home hero forms the mark from fine particles, in the spirit of the original video: they drift in and settle into the mark's shape, shimmer, and part around the pointer
  - diagram hubs and calls to action use the flat mark with a glow
  - honours `prefers-reduced-motion` by rendering a static scene
  - adds no dependency
- Raster images in the old colour scheme are replaced by illustrations drawn in the palette:
  - the three path cards on the home page (business leader, developer, AI engineer)
  - the ISO 27001 and SOC 2 tiles
- The particle background keeps its geometry (a sphere) and takes the new palette.

### Design system

Findings, measurements and starting values are in [research/design-audit.md](research/design-audit.md).
The site is consistent in colour after the rebrand; this section makes it consistent in type, layout and
surface, in a flat and clean style.

- Type:
  - one scale of nine roles (display, H1, H2, H3, H4, lead, body, small, label) and two weights (400, 600)
  - much larger than today: hero headline 88 px, section headings 52 px, body copy 18 px on a 1440 px screen
  - nothing below 14 px on marketing pages except the 13 px monospace label; docs prose stays at 16 to 17 px
  - sentence case for every heading; headings are a solid colour
  - every page has exactly one `h1`, and each heading level has one size
- Layout:
  - one container width of 1280 px; prose capped at 720 px; section content left aligned
  - one spacing scale; section padding of 128, 96 and 64 px on desktop, tablet and mobile
  - one section-header pattern: numbered monospace label, heading, lead
- Surfaces are flat:
  - two surface levels; cards are a solid fill with a 1 px border, or a hairline rule
  - no gradient fills, glass blur or glows on cards and headings
  - two corner radii: 8 px for buttons, controls and tags, 16 px for cards and panels
- Components:
  - three button kinds: primary (solid orange), secondary (outline), tertiary (text link with an arrow); buttons are rectangular with an 8 px radius, not pills
  - one primary button per view
  - tags are outlined monospace labels and do not look like buttons
  - the navbar is 72 px tall, keeps the three-line lockup, and has one primary button; the version menu shows on docs pages only
  - one icon family; integration logos are SVG and single colour by default
  - one label per kind of action ("Quick start", "Learn more")
- Motion:
  - content is visible without being scrolled into view
  - decorative motion is removed: scroll reveals that hide content, pulsing glows, shimmering gradients
- Vector animation is the site's imagery:
  - one vocabulary, particles on rails: fine straight and angled lines with dots that travel, queue, split and are filtered
  - two colours from the theme tokens; the drawings follow the colour mode
  - one drawing for each of the six stages (Build, Connect, Remember, Guard, Scale, Observe) and one for the architecture
  - each drawing shows what that part of the runtime does; none is decoration
  - one animation in view at a time, paused off screen, a static frame for reduced-motion users, no new dependency
- Home page:
  - nine sections: hero, trust marks, what OAK does, architecture, works with, deploy anywhere, choose your path, questions, closing section
  - the hero headline is short enough to set at display size
  - the feature section becomes a rail of six stages (Build, Connect, Remember, Guard, Scale, Observe); each stage shows one sentence, three points, its vector animation and the code or config that enables it, replacing the six tabs of cards
  - integrations stay on the home page as a four-column compatibility matrix, replacing the three marquee rows
  - every FAQ question stays, in two columns of flat rows
  - a row of trust marks (licence, foundations, compliance) replaces the separate trust section and the footer badges; it carries no figures until real ones exist
- The reference site named by the maintainer (choreolabs.com) informs principles only: type that carries the
  page, flat surfaces, hairlines and whitespace. Its palette is close to ours, so composition is what must
  differ: no wording, section order, imagery or signature component is taken from it. The audit lists, item
  by item, what stays ours.

### Contributor guidance

- `AGENTS.md` gains a short naming section stating the rules above, so that contributors and the docs-sync automation write the new name.
- The three sync skills (`ak-dev-sync-docs-from-branch`, `ak-dev-sync-skills-from-branch`, `ak-dev-sync-skills-and-docs-from-commit`) point at that section.

### Verification

- No file outside the in-scope set changes; in particular no `.py`, `.toml`, `.tf`, `.yaml` or `.yml` file.
- "Agent Kernel" remains in in-scope files only inside code spans, code blocks, and the search-continuity entries.
- `docs/docs` and the `0.10.1` snapshot are still identical.
- The production docs build passes with broken links failing the build.
- Screenshots of the home, features, use-cases, docs and blog pages are reviewed against the brand guide.

## Non-goals

- Renaming the Python package, CLI, classes, environment variables, config keys, repository, domain, PyPI project, Helm chart or Terraform modules.
- Runtime strings, docstrings and code comments.
- `pyproject.toml` descriptions, `Chart.yaml` and Terraform descriptions, example code and example config files.
- The 20 doc versions older than `0.10.1`, blog post bodies, blog banner images, existing folders under `docs/specs`.
- `NOTICE` and `LICENSE`.
- New typography.
- Surfaces outside the repository: the GitHub repository description and social preview, the PyPI page (it updates at the next release), the GHCR chart page.
- New Python components. This change adds no `AKConfig` field, ABC, factory or class, so the house patterns for new features do not apply.

## Open questions

- **Issue number.** Should an issue be opened so this folder can be renamed to `docs/specs/<number>-oak-rebrand/`?
- **Release announcement.** `.github/workflows/publish.yaml:207` posts "Agent Kernel v${VERSION}". It is a workflow file, so it is left unchanged. Change it with this work, or with the code rename?
- **Blog.** Post bodies and banners keep the old name and mark inside the new theme. Is regenerating the banners a follow-up?
- **Dead media.** `docs/static/models/leaf.glb` and `brain.glb` (3.1 MB together) are referenced nowhere. Delete them here?
- **Membership badges.** The Linux Foundation and Agentic AI Foundation badges in the footer are the
  foundations' own artwork and are shown unmodified. Is a monochrome treatment acceptable to them?
- **Former-name note.** Should the README and the docs intro carry one line saying that Open Agent Kernel
  was previously called Agent Kernel and that the `agentkernel` package and `ak` CLI are unchanged?
- **Hero headline.** The current headline is eleven words, too long for display size. Candidate: "The operating
  system for enterprise AI agents", with scale and compliance moved to the lead line. Whose call is the copy?
- **Trust figures.** No real figures exist yet. The row ships with marks only.
- **Skill evals.** `ak-init/evals/evals.json` (12 occurrences) and `ak-add-integration/evals/evals.json` (1) keep the old name as test prompts. Leave as is?
