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
- `/docs` serves the frozen `0.10.1` snapshot, not `docs/docs`.
  - Renaming only `docs/docs` would leave the default docs pages on the old name until the next release.
  - The snapshot is not a copy of `docs/docs`: ten of the 76 pages already differ at the merge base, so it is edited in place and never overwritten from `docs/docs`.
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
- "Agent Kernel by Yaala Labs" becomes "Open Agent Kernel". The company is named only in legal text: the
  policy pages, `NOTICE` and copyright lines, the website footer among them (decided 2026-11-20).
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
  - website source for the redesign: `docs/src/**`, `docs/static/**`, `docs/sidebars.js`, `docs/package.json`
  - `docs/plugins/**`: the build-time plugin that writes the llms.txt files (see llms.txt)
  - blog posts: front matter (`authors`, `image`) and the banner image under the title only; the text of a post is not edited (see Blog)
  - `branding/` (new)
  - `ak-py/README.md`
  - markdown under `examples/`, `use-cases/`, `ak-deployment/`, `e2e/`, `agent/`, `scripts/`
  - prose of the dev skills (`.agents/skills/`) and the bundled skills (`ak-py/src/agentkernel/skills/**/*.md`)
  - `.github/ISSUE_TEMPLATE/*.md`, `.github/SPRINT_ROLLOVER.md`
- The `0.10.1` snapshot is a one-time exception to the frozen-snapshot rule (`AGENTS.md`, Conventions).
  - The rule itself stays; the 20 older versions are not touched.
  - What the snapshot receives is listed under Verification; nothing else in it changes.

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
  - footer: Primary lockup, white and orange
  - chatbot header: OAK Horizontal, white and orange
  - root README: Primary lockup, colour on light schemes, white and orange on dark schemes
  - favicon set and in-page icons: the mark in Tiger Flame Orange
  - social card: Primary lockup, white and orange, on the blue gradient

### Colour theme

- The site has two colour modes. Light is the default; a navbar switch selects the dark mode and the choice is remembered.
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
- Diagrams follow the colour mode:
  - Mermaid diagrams have a dark palette and a light palette, so a diagram on the light page is drawn for a white background, not shown on a dark plate
  - the hard-coded `style` fills in the 29 pages that used the Docusaurus default greens take brand colours, with a label colour that reads on the fill, in `docs/docs` and in the `0.10.1` snapshot

### Hero and call-to-action visuals

- `hero.mp4` and `cta-bg.png` are removed from the site and the repository.
- Home hero: the mark as a field of fine dots (`ParticleLogo`).
  - on load it comes into focus from a loose haze over two seconds; nothing flies across the hero
  - under the pointer it ripples, and the ripple trails the cursor by a moment
  - as the page scrolls the dots scatter, and gather again on the way back
  - without WebGL, or with reduced motion, the plain mark is shown
- Closing panel: a slow sheet of dots behind the copy, wherever the closing panel appears. It replaces the call-to-action image.
- Integrations section: a floor of dots along its bottom edge, calm at rest, with one ripple each time the stage changes.
- The two dot fields are told apart on purpose and share one small WebGL runner. They start when they near the screen and pause off screen; with reduced motion nothing moves. They are decoration: no content depends on them.
- Raster images in the old colour scheme are replaced by drawings in the palette:
  - the three path cards on the home page become the level stack (see Design system, Home page)
  - the ISO 27001 and SOC 2 tiles become drawn seals
- No animation library: the earlier particle background, its 3D models, and the `gsap` and `three` dependencies are removed.
- The hero directions tried before this one, and why each was turned down, are in [research/review-log.md](research/review-log.md).

### Design system

Findings, measurements and starting values are in [research/design-audit.md](research/design-audit.md).
The site is consistent in colour after the rebrand; this section makes it consistent in type, layout and
surface, in a flat and clean style.

- Type:
  - one scale of nine roles (display, H1, H2, H3, H4, lead, body, small, label) and two weights (400, 600)
  - much larger than today: hero headline 88 px, section headings 52 px, body copy 18 px on a 1440 px screen
  - running text is 15 px or larger; the only smaller sizes are the 13 px monospace label and 14 px for labels inside diagrams
  - docs prose stays at 16 to 17 px
  - sentence case for every heading; headings are a solid colour
  - every page has exactly one `h1`, and each heading level has one size
- Layout:
  - one container width of 1280 px; prose capped at 720 px; section content left aligned
  - one spacing scale; section padding of 128, 96 and 64 px on desktop, tablet and mobile
  - one section-header pattern: numbered monospace label, heading, lead
- Surfaces are flat, with two exceptions:
  - no gradient fills, glass blur, glows or drop shadows on cards, panels and headings
  - exception 1: cards lift with one soft shadow in the light mode (in the dark mode they keep a 1 px border)
  - exception 2: floating layers (the chat launcher and its panel) carry a shadow
  - two surface levels; a card is a solid fill, or a hairline rule
  - two corner radii: 8 px for buttons, controls and tags, 16 px for cards and panels
- Components:
  - three button kinds: primary (solid orange), secondary (outline), tertiary (text link with an arrow); buttons are rectangular with an 8 px radius, not pills
  - one primary button per view
  - tags are outlined monospace labels and do not look like buttons
  - the navbar is 72 px tall, keeps the three-line lockup, and has one primary button; the version menu shows on docs pages only
  - one icon family; integration logos are SVG and single colour by default
  - one label per kind of action ("Quick start", "Learn more")
- Motion:
  - content is never hidden without script, with reduced motion, in print, or when it is already on screen at load
  - content below the fold may fade up once as it enters the view
  - that fade (`Reveal`) is the only entrance effect; the earlier scroll-reveal script is removed
  - decorative motion is removed: pulsing glows, shimmering gradients
- Vector animation is the site's imagery:
  - one vocabulary, particles on rails: fine straight and angled lines with dots that travel, queue, split and are filtered
  - two colours from the theme tokens; the drawings follow the colour mode
  - one drawing for each of the six stages (Build, Connect, Remember, Guard, Scale, Observe); the architecture diagram has dots travelling its rails
  - each drawing shows what that part of the runtime does; none is decoration
  - a drawing pauses off screen and shows a static frame for reduced-motion users; no new dependency
- Home page:
  - an announcement strip, then nine sections: hero, trust marks, what OAK does, architecture, works with, deploy anywhere, choose your path, questions, closing panel
  - the hero headline is short enough to set at display size
  - the feature section becomes a rail of six stages (Build, Connect, Remember, Guard, Scale, Observe); each stage shows one sentence, three points, its vector animation and the code or config that enables it, replacing the six tabs of cards
  - integrations stay on the home page as a scroll-stepped section, replacing the three marquee rows
    - grouped by the six stages, and every integration listed by name: none is hidden behind a count or a link
    - on a large screen the section stays in view while the scroll steps through the groups; elsewhere the groups are stacked
    - one data file holds the list
  - the three reading levels are one drawing, a stack of three layers, beside three rows that link to the persona pages
  - every FAQ question stays, in two columns of flat rows
  - a row of trust marks (licence, foundations, compliance) replaces the separate trust section; it carries no figures until real ones exist
  - the footer keeps the two foundation membership badges, unmodified (see Open questions)
- Pages below the home page:
  - features, use cases and the three persona pages start with the shared page header and end with the shared closing panel
  - features is a reference: capabilities listed under the six stages, each linked to its guide
  - use cases and the three persona pages share one skeleton; a persona page links back to the path selection on the home page
- The reference site named by the maintainer (choreolabs.com) informs principles only: type that carries the
  page, flat surfaces, hairlines and whitespace. Its palette is close to ours, so composition is what must
  differ: no wording, section order, imagery or signature component is taken from it. The audit lists, item
  by item, what stays ours.

### Blog

Findings and proposals are in [research/blog-audit.md](research/blog-audit.md).

- The blog uses the site's design system: the same type faces and scale, container, tags and page header.
- Index:
  - a topic filter that stays in view; the chosen topic is in the URL, so a filtered view can be shared
  - the newest post leads as a wide card; the rest are a grid of cards with banners
  - a tag page uses the same grid
- Post page:
  - a reading column at the prose measure (720 px), with a larger text size for long reading
  - a link back to all posts and the post's topic above the title
  - a table of contents beside the post on a wide screen
- Authors:
  - a post names the person who wrote it, taken from the commit history
  - the shared team author is "OAK", pictured by the mark on a disc so a round crop does not cut it
- Banners:
  - every post has a banner, set as its `image` and shown under its title
  - existing banners are recoloured in place and carry the new mark; their layouts and baked-in headlines are kept
  - posts without a banner get one from a template kept in `branding/blog-banner/`
- The text of a post is not edited, so post bodies still say "Agent Kernel" (see Open questions).

### What's new page

- The "What's new" list moves out of the docs introduction to its own page, `whats-new.md`, newest first, each entry linked to its guide.
- The introduction keeps a two-line tip that names the latest additions and links to the page.
- Both exist in `docs/docs` and in the `0.10.1` snapshot.
  - an entry for a capability that is not in the `0.10.1` release appears in `docs/docs` only
- The home page announcement strip names the newest headline capability and links to its guide.

### llms.txt

- The site publishes two files for AI assistants, in the format of llmstxt.org, written on every build with no new dependency:
  - `/llms.txt`: a summary of the project, then an index of the docs, the main site pages, the source and package links, and the blog posts
  - `/llms-full.txt`: the text of the docs pages in one file
- Both describe the docs of the latest release, the ones served at `/docs`, not the unreleased docs.
- The index and the full text are generated from the docs themselves: adding, renaming or removing a docs page needs no edit to a list.
  - order: the docs sidebar
  - description of a page or a blog post: its front matter `description`, else the first sentence of its opening paragraph
- Only the summary, the list of site pages and the list of source links are hand-written, in one template file.
- The summary states the former name, "Agent Kernel", and the identifiers that kept it.
  - This is the one public exception to the former-name rule (Open questions, Former-name note).
  - Reason: an assistant trained on older content knows the project by that name, and the blog titles listed in the same file still carry it.
- In the full text every link is absolute, and fenced code is unchanged.
- The files are not linked from a page and are not listed in the sitemap.

### Contributor guidance

- `AGENTS.md` gains a short naming section stating the rules above, so that contributors and the docs-sync automation write the new name.
- The three sync skills (`ak-dev-sync-docs-from-branch`, `ak-dev-sync-skills-from-branch`, `ak-dev-sync-skills-and-docs-from-commit`) point at that section.
- `AGENTS.md` and `branding/README.md` (*Website design system*) state the design-system rules; the two documents use the same wording for the type floor and the surface rule.
- `AGENTS.md` and the docs sync skill say which part of llms.txt is hand-written and when to update it.
- Every dev skill that tells a contributor where a new integration is listed on the site names the files that exist after the redesign.

### Verification

- No file outside the in-scope set changes; in particular no `.py`, `.toml`, `.tf`, `.yaml` or `.yml` file.
  - one exception, made later: the author name in `ak-py/pyproject.toml` (Naming, the company is named only in legal text)
- "Agent Kernel" remains in in-scope files only inside code spans, code blocks, the search-continuity entries, the sentence in `AGENTS.md` that records the former name, and the summary of `/llms.txt`.
- llms.txt: both files are in the build; every address in them under the site's own domain is a page of the build; the full text has one entry for each published docs page and no relative link outside fenced code.
- The `0.10.1` snapshot's diff against the merge base holds only:
  - the rename
  - the recoloured diagram `style` lines (the same 29 pages as `docs/docs`)
  - `whats-new.md` with its sidebar entry, and the introduction tip that links to it
  - the repaired sequence diagram in `advanced/threads.md`
- No doc version older than `0.10.1` changes.
- The production docs build passes with broken links failing the build.
- Screenshots of the home, features, use-cases, persona, docs and blog pages, in both colour modes and at desktop and phone width, are reviewed against the brand guide.
- With script off, with reduced motion and in print, no content is hidden.

## Non-goals

- Renaming the Python package, CLI, classes, environment variables, config keys, repository, domain, PyPI project, Helm chart or Terraform modules.
- Runtime strings, docstrings and code comments.
- `pyproject.toml` descriptions, `Chart.yaml` and Terraform descriptions, example code and example config files.
- The 20 doc versions older than `0.10.1`, the text of blog posts, the headlines baked into the older blog banners, existing folders under `docs/specs`.
- `NOTICE` and `LICENSE`.
- New typography.
- Surfaces outside the repository: the GitHub repository description and social preview, the PyPI page (it updates at the next release), the GHCR chart page.
- New Python components. This change adds no `AKConfig` field, ABC, factory or class, so the house patterns for new features do not apply.

## Open questions

- **Issue number.** Should an issue be opened so this folder can be renamed to `docs/specs/<number>-oak-rebrand/`?
- **Release announcement.** `.github/workflows/publish.yaml:207` posts "Agent Kernel v${VERSION}". It is a workflow file, so it is left unchanged. Change it with this work, or with the code rename?
- **Blog.** Post bodies, and the headlines baked into the older banners, keep the old name inside the new theme. Rewrite them, or leave them as a record of their date?
- **Membership badges.** The Linux Foundation and Agentic AI Foundation badges in the footer are the
  foundations' own artwork and are shown unmodified. Is a monochrome treatment acceptable to them?
- **Former-name note.** Resolved on 2026-11-19: no public page carries a note about the former name. The
  root README had one and it was removed; the docs introduction never had one. `AGENTS.md` keeps one
  sentence, because the naming rules for contributors refer to the old name. One public exception was
  made on 2026-11-20: the summary of `/llms.txt` says what the project was called (see llms.txt).
- **New copy.** The hero headline ("The Operating System For Enterprise AI Agents", capitalised word by word at the maintainer's request), the blog heading and
  the persona page titles and leads are new wording. They need the maintainer's read.
- **Trust figures.** No real figures exist yet. The row ships with marks only.
- **Skill evals.** `ak-init/evals/evals.json` (12 occurrences) and `ak-add-integration/evals/evals.json` (1) keep the old name as test prompts. Leave as is?
