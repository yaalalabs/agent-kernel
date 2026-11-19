# Rebrand to Open Agent Kernel (OAK): implementation spec

This document details how the rebrand in [design.md](design.md) is built: the brand asset set, the theme
tokens, the hero and call-to-action component, and the rename rules. `design.md` is the requirements
source. Counts and line numbers were taken on branch `feat/rebranding_oak` at commit `c514f928c`.

## Design

### 1. Brand asset set

Layout of the committed folder:

```
branding/
  README.md
  logo-mark/        oak-mark-{orange,blue,white,black}.svg
  primary/          open-agent-kernel-{color,white-orange,blue,orange,white,black}.svg
  oak-horizontal/   oak-horizontal-{color,white-orange,blue,orange,white,black}.svg
  oak-vertical/     oak-vertical-{color,white-orange,blue,orange,white,black}.svg
  source/           ignored by git (.ai, .pdf, guide pages, PNG exports)
```

Rules:

1. Files are copied byte for byte from `branding/source/<Family>/SVG/`. Only the names change.
2. Variant names map as: `COLOUR` to `color`, `WHITE & ORANGE` to `white-orange`, `BLUE` to `blue`,
   `ORANGE` to `orange`, `WHITE` to `white`, `BLACK` to `black`. The mark has four variants, each lockup six.
3. Within a family the variants have different `viewBox` scales but the same aspect ratio (for example
   `421.54 x 118.76` and `144.79 x 40.79` for OAK Horizontal, both 3.55:1), so they are interchangeable at
   a set width.
4. `.gitignore` ignores `branding/source` (the entry is already in the working tree).
5. `branding/README.md` lists the five colours with hex and RGB, the four gradients as CSS, the lockup
   usage table from `design.md`, and the contrast rule for labels on orange.

Site files:

| Served path | Content | Replaces |
|---|---|---|
| `img/branding/open-agent-kernel-white-orange.svg` | Primary lockup, white and orange | `agent-kernel-icon-horizontal-color-dark-bg.svg` in the navbar |
| `img/branding/oak-horizontal-white-orange.svg` | OAK Horizontal, white and orange | `agent-kernel-icon-horizontal-color-dark-bg.svg` in the footer and chatbot |
| `img/branding/oak-mark-orange.svg` | mark, orange | `agent-kernel-icon-color.svg` |
| `img/branding/oak-mark-white.svg` | mark, white | `agent-kernel-icon-mono-white.svg` |
| `img/logo.svg` | mark, orange | old logo, same path |
| `img/favicon.ico` | mark, orange, 16, 32 and 48 px | old icon, same path |
| `img/favicon-16.png`, `img/favicon-32.png` | mark, orange | same paths |
| `img/apple-touch-icon.png` | mark, orange, on Prussian Blue, 180 px | same path |
| `img/card.png` | social card, 1200 x 630 | same path |

Of the nine old `agent-kernel-*` SVGs in `docs/static/img/branding/`, five are referenced (the three above
by the site, the two lockups by the root README) and four are not. All nine are deleted. The raster files are rendered from the SVGs with headless Chrome over the DevTools
protocol, the same method the blog banners use. The social card shows the Primary lockup (white and
orange), the tagline and `pip install agentkernel` on the blue gradient. Its HTML source is not committed.

### 2. Theme tokens

All tokens live in `docs/src/css/custom.css`. Derived steps are computed from the five brand colours.
The table gives the dark-mode values; the light-mode values follow it.

| Token | Old | New | Derivation |
|---|---|---|---|
| `--ak-orange` | (new) | `#FF5E32` | Tiger Flame Orange |
| `--ak-prussian` | (new) | `#02284F` | Prussian Blue |
| `--ak-dusk` | (new) | `#3F598A` | Dusk Blue |
| `--ak-sky` | (new) | `#ABCEE1` | Pale Sky |
| `--ak-ice` | (new) | `#B1CDFF` | Baby Blue Ice |
| `--ak-bg`, `--ak-surface` | `#010002` | `#011428` | Prussian Blue, 50% toward black |
| `--ak-bg-alt` | (new) | `#011C37` | Prussian Blue, 30% toward black |
| `--ak-surface-raised` | `#081226` | `#02284F` | Prussian Blue |
| `--ak-surface-overlay` | `#081226` | `#0D315A` | Prussian Blue, 18% toward Dusk Blue |
| `--ak-border` | `#081226` | `#173964` | Prussian Blue, 35% toward Dusk Blue |
| `--ak-border-accent` | `rgba(0, 221, 255, 0.35)` | `rgba(255, 94, 50, 0.35)` | accent |
| `--ak-primary` | (new) | `#FF5E32` | accent |
| `--ak-primary-light` | (new) | `#FF8260` | lightness +9% |
| `--ak-primary-dark` | (new) | `#FF4613` | lightness -6% |
| `--ak-primary-glow` | (new) | `rgba(255, 94, 50, 0.2)` | accent |
| `--ak-primary-soft` | (new) | `#F58A5E` | end stop of the orange gradient |
| `--ak-on-primary` | (new) | `#011428` | text on orange fills |
| `--ak-primary-rgb` | (new) | `255, 94, 50` | for `rgba(var(...), a)` |
| `--ak-blue` | `#00DDFF` | `#B1CDFF` | ambient, Baby Blue Ice |
| `--ak-blue-light` | `#40E8FF` | `#ABCEE1` | ambient, Pale Sky |
| `--ak-blue-dark` | `#00AADE` | `#3F598A` | ambient, Dusk Blue |
| `--ak-blue-glow` | `rgba(0, 221, 255, 0.2)` | `rgba(177, 205, 255, 0.2)` | ambient |
| `--ak-blue-rgb` | (new) | `177, 205, 255` | for `rgba(var(...), a)` |
| `--ak-sky-rgb`, `--ak-dusk-rgb`, `--ak-prussian-rgb`, `--ak-bg-rgb`, `--ak-primary-soft-rgb` | (new) | channel triplets | for `rgba(var(...), a)` |
| `--ak-purple`, `-light`, `-glow` | `#F200FF` family | removed | 4 uses move to `--ak-sky` or, inside the brand gradient, `--ak-primary-soft` |
| `--ak-gradient` | cyan to magenta | `linear-gradient(135deg, #FF5E32 0%, #F58A5E 100%)` | guide, orange block |
| `--ak-gradient-subtle` | cyan to magenta, 12% | `linear-gradient(135deg, rgba(255, 94, 50, 0.12) 0%, rgba(177, 205, 255, 0.12) 100%)` | |
| `--ak-gradient-blue` | (new) | `linear-gradient(225deg, #011C37 0%, #02284F 45%, #3F598A 100%)` | guide, blue block |
| `--ak-gradient-ice` | (new) | `linear-gradient(135deg, #B1CDFF 0%, #3F598A 100%)` | guide, ice block |
| `--ak-gradient-sky` | (new) | `radial-gradient(ellipse at 50% 0%, #ABCEE1 0%, #3F598A 75%)` | guide, sky block |
| `--ak-text` | `#E8E4F0` | `#EAF3F8` | Pale Sky, 75% toward white |
| `--ak-text-secondary` | `#9A91B8` | `#ABCEE1` | Pale Sky |
| `--ak-text-muted` | `#6B5F85` | `#798BAD` | Dusk Blue, 30% toward white |

Infima variables follow the same values: `--ifm-color-primary` `#FF5E32` with `dark #FF4613`,
`darker #FF3A04`, `darkest #D52E00`, `light #FF7651`, `lighter #FF8260`, `lightest #FFA68E`;
`--ifm-background-color`, navbar and footer backgrounds `#011428`; `--ifm-background-surface-color`
`#02284F`; `--ifm-font-color-base` `#EAF3F8`; `--ifm-font-color-secondary` `#ABCEE1`; navbar shadow and
table-of-contents border `#173964`; `--docusaurus-highlighted-code-line-bg` `rgba(177, 205, 255, 0.15)`.
The unused light-mode fallback block takes `#D52E00` as its primary so it stays readable on white.

Light mode redefines the themeable tokens under `[data-theme='light']`:

| Token | Light value |
|---|---|
| `--ak-bg`, `--ak-surface` | `#FFFFFF` |
| `--ak-bg-alt` | `#F5F8FC` |
| `--ak-surface-raised` | `#F1F5FA` |
| `--ak-surface-overlay` | `#E7EEF7` |
| `--ak-border` | `#D3DEEC` |
| `--ak-fg`, `--ak-fg-rgb` | `#02284F`, `2, 40, 79` (white and `255, 255, 255` in dark) |
| `--ak-text`, `--ak-text-secondary`, `--ak-text-muted` | `#02284F`, `#3F598A`, `#5D7199` |
| `--ak-primary-text` | `#D23F17` (`#FF5E32` in dark) |
| `--ak-blue`, `--ak-blue-light`, `--ak-blue-dark`, `--ak-sky` | `#3F598A`, `#5E7AAE`, `#02284F`, `#5E7AAE` |
| `--ak-bg-rgb`, `--ak-prussian-rgb` | `255, 255, 255`, `241, 245, 250` |
| `--ak-shadow-rgb` | `2, 40, 79` (`0, 0, 0` in dark) |
| `--ak-mono-filter` | `brightness(0) invert(0.14)` (`brightness(0) invert(1)` in dark) |

Rules for the two modes:

1. Accent fills (`--ak-primary*`, `--ak-gradient`) and the five brand colours are the same in both modes.
2. Stylesheets hold no literal white, grey text or black shadow. White became `--ak-fg` or
   `rgba(var(--ak-fg-rgb), a)`, grey text became a text token, and shadows use `--ak-shadow-rgb`. White
   is kept only as a solid background plate and as text on a coloured fill.
3. Orange text uses `--ak-primary-text`; orange fills, strokes and the mark use `--ak-primary`.
4. `.footer`, `.ak-dark` and `.ak-dark-surface` redeclare the dark values, which pins a subtree to the
   dark mode. `.ak-dark-surface` also paints the background and resets the Infima text colours. The
   footer, the chat launcher and the three persona pages are pinned.
5. Single-colour logos carry `mono: true` and take `--ak-mono-filter`, so they are white on dark and
   near-black on light. This includes logos whose file is drawn in white.
6. Canvas and WebGL code reads the tokens at run time through `themeRgba`, `themeInt` and
   `onThemeChange` in `docs/src/lib/brand.ts`.
7. `docs/docusaurus.config.js` enables the switch (`disableSwitch: false`, `defaultMode: 'dark'`,
   `respectPrefersColorScheme: false`) and gives the navbar logo a light source and a `srcDark`.

The values in the Derivation column are starting points. The five brand colours are fixed; the derived
steps may be tuned at the visual checkpoint (plan, iteration 2).

Measured contrast ratios for the pairs the theme relies on:

| Foreground on background | Ratio |
|---|---|
| `--ak-text` on `--ak-bg` | 16.47 |
| Pale Sky on `--ak-bg` / on Prussian Blue | 11.18 / 8.91 |
| Baby Blue Ice on `--ak-bg` / on Prussian Blue | 11.53 / 9.19 |
| orange on `--ak-bg` / on Prussian Blue | 6.10 / 4.86 |
| `--ak-bg` on orange (button labels) | 6.10 |
| white on orange (not used for text) | 3.04 |
| `--ak-text-muted` on `--ak-bg` / on Prussian Blue | 5.39 / 4.29 |

`--ak-text-muted` on Prussian Blue is below 4.5:1, so muted text on raised surfaces is limited to large
or non-essential text; otherwise `--ak-text-secondary` is used there.

### 3. Hard-coded colour replacement

Old colours are grouped into families. Every occurrence in `docs/src` and `docs/docusaurus.config.js` is
replaced by a token; none is replaced by a new literal. The stylesheets hold 2,022 colour occurrences and
222 distinct colours, so membership is decided by hue, saturation and lightness, not by a fixed list; the
table shows the main members.

| Family | Members | Becomes |
|---|---|---|
| Cyan | `#00DDFF`, `#00E5FF`, `#00D4FF`, `#00ECFF`, `#40E8FF`, `#00AADE`, `#0099BB`, and the triplets `0, 221, 255`, `0, 229, 255`, `0, 212, 255` | accent or ambient, by role |
| Magenta and violet | `#F200FF`, `#FF66FF`, `#D946EF`, `#C084FC`, `#9D6CFF`, `#8E5DFF`, triplet `242, 0, 255` | `--ak-sky` |
| Near-black backgrounds | `#010002`, `#020203`, `#05090F`, `#0D001A`, `#15012A`, `#131017` | `--ak-bg` |
| Dark surfaces | `#081226`, `#071026`, `#0C1A2E`, `#0F172A`, `#2A272E` | `--ak-surface-raised` or `--ak-surface-overlay` |
| Violet-grey text | `#E8E4F0`, `#DFE1F0`, `#9A91B8`, `#6B5F85` | `--ak-text`, `--ak-text-secondary`, `--ak-text-muted` |
| Saturated blues | `#4F7DF7`, `#2979FF`, `#818CF8` | `--ak-blue` or `--ak-blue-dark` |

Rules:

1. **Role decides the cyan mapping.** Accent roles (design.md, Colour theme) take `--ak-primary*`; ambient
   roles take `--ak-blue*`.
2. **First pass by rule block.** A one-off script decides per CSS rule block, so a button and its glow
   stay the same colour. A block is accent when it sets `color`, `fill` or `background` to a cyan with
   alpha of 0.6 or more, or when its selector is a hover, focus or active state, a button or a link.
   Every other block is ambient. Pale cyans are always ambient. Custom properties that carry a colour
   into a component (`--node-color`, `--timeline-color`) default to ambient.
3. **Second pass by eye.** Each page is screenshotted and individual cases are moved between accent and
   ambient. The first pass is not the final answer.
4. **Translucent colours** use `rgba(var(--ak-primary-rgb), a)` or `rgba(var(--ak-blue-rgb), a)`, keeping
   the original alpha.
5. **Canvas and WebGL code** cannot read CSS variables cheaply. A new module `docs/src/lib/brand.ts`
   exports the brand colours as hex strings, with helpers for `rgba()` strings, `0xRRGGBB` numbers and
   0 to 1 channel triplets. It is the only place outside `custom.css` where the literals appear.
   (`docs/src/theme` is reserved for Docusaurus component overrides, so the module does not live there.)
6. **Unchanged:** white, black shadows, status colours (`#26A64D`, `#DB4444`, `#F7A544`, `#22C55E`,
   `#EF4444`, `#FACC15`), vendor colours (`#FF9900`, `#0078D4` and per-integration colours), the slate
   greys, the categorical colours that tell diagram node kinds apart, and the per-persona accents (see
   design.md, Open questions).

Diagram colours:

| Mermaid theme variable (`docs/docusaurus.config.js:533`) | Becomes |
|---|---|
| `background` | `#011428` |
| `primaryColor`, `actorBkg` | `#02284F` |
| `primaryBorderColor`, `actorBorder`, `labelBoxBorderColor`, `activationBorderColor` | `#3F598A` |
| `primaryTextColor`, `actorTextColor`, `labelTextColor` | `#EAF3F8` |
| `lineColor`, `signalColor` | `#ABCEE1` |
| `titleColor`, `loopTextColor` | `#B1CDFF` |
| `clusterBkg`, `tertiaryColor`, `edgeLabelBackground` | `#011C37` |
| `clusterBorder`, `noteBorderColor` | `#173964` |
| `secondaryColor`, `labelBoxBkgColor`, `activationBkgColor`, `noteBkgColor` | `#0D315A` |
| `sequenceNumberColor` | `#011428` |

In-page `style` lines in `docs/docs` (29 files) change fill and label colour together:

| Old fill | Uses | New fill | New label colour |
|---|---|---|---|
| `#2e8555` | 73 | `#FF5E32` | `#02284F` |
| `#25c2a0` | 23 | `#3F598A` | `#fff` |
| `#1ebbd7` | 13 | `#B1CDFF` | `#02284F` |
| `#7d5ba6` | 8 | `#ABCEE1` | `#02284F` |

Vendor fills in those diagrams (`#ff9900`, `#0078d4`, `#4285f4`, `#326ce5`) do not change.

### 4. Hero and call-to-action component

New component `docs/src/components/OakMark/` (`index.tsx`, `styles.module.css`).

```tsx
type OakMarkProps = {
  variant?: 'hero' | 'hub' | 'cta';  // sizing and glow strength, default 'hero'
  animated?: boolean;                // default true
  className?: string;                // sizing class from the call site
};
export default function OakMark(props: OakMarkProps): JSX.Element;
```

- Renders the two paths of `oak-mark-orange.svg` (viewBox `0 0 86.86 86.85`) inline.
- The `hero` variant is a 3D scene:
  - each half of the mark is a stack of 15 SVG slices 2.2 px apart, which reads as an extruded body
  - on load the halves swing in from edge-on, pivoting on the centre gap
  - the body sways slowly and leans up to 13 degrees toward the pointer anywhere over the hero section
  - three tilted orbit rings carry five agent nodes; each ring is drawn twice, clipped to its far half
    behind the mark and its near half in front, so nodes pass behind and in front of it
  - a light sweep crosses the face every 7.5 s, and a ground shadow breathes with the float
  - animations use transforms only: animating opacity on a `preserve-3d` element flattens its children
- The `hub` and `cta` variants are the flat mark described below.
- Layers, back to front: a radial orange glow, the mark filled with the orange gradient, a thin Baby Blue
  Ice outline.
- Sizes: `hero` is centred in the hero's right column at up to 400 px; `hub` takes its size from the call
  site (96 px on the features map, 132 px on the use-cases orbit); `cta` is 150 px, less on small screens.
- Motion: the outline draws in once, then the glow breathes on a slow loop. CSS only, no canvas.
- `prefers-reduced-motion: reduce`, or `animated={false}`, renders the static mark.
- No new dependency.

Illustrations (`docs/src/components/BrandArt/`): `PersonaArt` draws the three path-card pictures (a rising
chart, an editor window, a node graph around the mark) and `CertSeal` draws the ISO 27001 seal and the
SOC 2 shield. Both use theme tokens only. They replace `business_leader.png`, `developer.png`, `ai.png`,
`iso.png` and `soc.png`, which are deleted. The path cards share one accent, `--ak-primary`.

Particle background (`docs/src/components/PlantParticlesBackground/index.tsx`): `models/index.glb` is three
icosphere meshes, not the old mark, so the geometry stays. `PALETTE` (`:29-33`) becomes Baby Blue Ice,
Pale Sky and orange, and the clear colour (`:286`) becomes the page background. Both read from `brand.ts`.

### 5. Rename rules

A one-off Python script applies the naming rules to markdown. It is not committed. It is deterministic,
and a second run produces no diff.

Protected spans (never rewritten):

1. fenced code blocks, except those tagged `mermaid`
2. inline code spans
3. link destinations and bare URLs
4. HTML attributes other than `alt` and `title`
5. MDX `import` and `export` lines
6. YAML frontmatter, except the keys `title`, `sidebar_label`, `description` and `keywords`

Rewrite rules, applied to everything else:

1. Frontmatter `title` and `sidebar_label`, and the H1: "Agent Kernel" becomes "Open Agent Kernel".
2. The first mention outside headings and frontmatter becomes "Open Agent Kernel (OAK)".
   - The parenthetical is dropped where it would read badly: a possessive ("Open Agent Kernel's"), a
     modifier ("the Open Agent Kernel REST API"), or a mention already followed by a parenthesis.
     Later mentions are still "OAK".
   - An existing "Agent Kernel (AK)" becomes "Open Agent Kernel (OAK)".
3. Every later mention, and every mention in an H2 or lower heading, becomes "OAK".
4. Inside `mermaid` blocks every mention becomes "OAK".
5. Frontmatter `description`: the first mention becomes "Open Agent Kernel (OAK)", later ones "OAK".
   - Skill `SKILL.md` descriptions follow the same rule. "Open Agent Kernel" contains "Agent Kernel", so
     prompts that use the old name still match the description text.
6. The prose abbreviation `AK`, matched as a whole word that is not part of an identifier (not followed
   or preceded by a letter, digit, `_`, `-`, `.` or `/`), becomes "OAK".
7. Punctuation and wording around a replacement are not otherwise changed.

The script prints every replacement with its line for review, and a separate list of lines where the name
precedes "REST API", "CLI", "Test", or a framework name. Decisions for those:

- In prose they are ordinary mentions: "the Agent Kernel REST API" becomes "the OAK REST API", "the Agent
  Kernel Test framework" becomes "the OAK Test framework".
- In code spans and blocks they are product output and stay, for example the span name at
  `examples/cli/cloudwatch/README.md:63` and the description string at
  `ak-py/src/agentkernel/skills/ak-cloud-deploy/SKILL.md:1263`.
- `AgentKernel` (one word) appears in scope only as product output (`docs/docs/advanced/traceability.md:545`,
  `docs/docs/quick-start.md:455`) and stays.

A file whose code fences do not balance is skipped and reported, then edited by hand.

Markdown file sets (files and occurrences of "Agent Kernel"):

| Area | Files | Occurrences |
|---|---|---|
| root (`README.md`, `CONTRIBUTING.md`, `DEVELOPER_GUIDE.md`, `SECURITY.md`, `AGENTS.md`) | 5 | 32 |
| `docs/docs` | 74 | 396 |
| `docs/src/pages/*.md` (legal pages) | 3 | 6 |
| `docs/README.md`, `docs/SETUP.md` | 2 | 6 |
| `ak-py/README.md` | 1 | 10 |
| `ak-py/src/agentkernel/skills/**/*.md` | 6 | 48 |
| `.agents/skills/**/*.md` | 19 | 48 |
| `.github/**/*.md` | 5 | 6 |
| `examples/**/*.md` | 128 | 413 |
| `use-cases/**/*.md` | 6 | 27 |
| `ak-deployment/**/*.md` | 19 | 43 |
| `e2e`, `agent`, `scripts` (`*.md`) | 3 | 7 |
| **Total** | **271** | **1,042** |

`docs/docs` also holds 82 whole-word uses of "AK".

Site source is edited by hand, because JSX text cannot be segmented safely:

- 24 `.tsx` files under `docs/src`, 151 occurrences, 135 of them display copy and the rest code comments,
  which are left alone. In `docs/src/pages` the first mention in a file is the full name and later ones
  are "OAK". Shared components always say "OAK". `alt`, `title` and `aria-label` text always uses the
  full name.
- Component names, file names, imports and class names do not change (`AgentKernelArchDiagram`,
  `WhyAgentKernel`).
- `docs/blog/authors.json`: the four "Agent Kernel Team" titles become "Open Agent Kernel Team".
- `docs/static/robots.txt:1`: the comment takes the full name.

Snapshot mirror:

1. Precondition: `diff -rq docs/docs docs/versioned_docs/version-0.10.1` prints nothing.
2. After `docs/docs` is finished and reviewed, `rsync -a --delete docs/docs/ docs/versioned_docs/version-0.10.1/`.
3. Postcondition: the same `diff -rq` prints nothing.
4. If the precondition fails because `docs/docs` has moved on, the script runs on the snapshot separately
   and hand edits are ported.

### Consumer changes

Asset references:

| Reference | Location | Becomes |
|---|---|---|
| README lockup | `README.md:3-5` | `branding/primary/open-agent-kernel-white-orange.svg` (dark), `branding/primary/open-agent-kernel-color.svg` (light), alt "Open Agent Kernel" |
| Navbar logo | `docs/docusaurus.config.js:440` | `img/branding/open-agent-kernel-white-orange.svg`, 2.75rem tall (44 px in the 60 px bar) so the three lines of type stay legible; the docs sidebar copy of the logo gets the same height |
| Footer logo | `docs/src/theme/Footer/Layout/index.tsx:74` | `img/branding/oak-horizontal-white-orange.svg` |
| Chatbot header | `docs/src/components/FloatingChatbot/index.tsx:204` | same |
| Chatbot launcher | `docs/src/components/FloatingChatbot/index.tsx:187` | `img/branding/oak-mark-white.svg` |
| In-page icon | `AgentKernelSitsInFlowDiagram/index.tsx:20`, `ArchitectureOverview/index.tsx:233`, `FloatingChatbot/index.tsx:265`, `SandboxFlowDiagram/index.tsx:254`, `pages/features.tsx:1317`, `pages/use-cases.tsx:206` | `img/branding/oak-mark-orange.svg` |
| Hero video | `pages/index.tsx:307`, `pages/use-cases.tsx:530` | `<OakMark variant="hero" />` |
| Hub video | `pages/features.tsx:403`, with the inline `#010002` at `:400` | `<OakMark variant="hub" />`, background from a token |
| CTA image | `components/CTASection/index.tsx:42`, `pages/index.tsx:737`, `features.tsx:2070`, `use-cases.tsx:583`, `ai-engineer.tsx:1263`, `developer.tsx:729`, `business-leader.tsx:584` | `<OakMark variant="cta" />` |

Deleted files: `docs/static/video/hero.mp4`, `docs/static/img/cta-bg.png`, the nine old SVGs in
`docs/static/img/branding/`. The CSS classes that sized them (`.heroVideo`, `.ctaImage`,
`.pageMapHubIcon`) are replaced by the component's own styles.

### Config changes

No `AKConfig`, YAML or environment variable changes.

`docs/docusaurus.config.js`:

| Line | Field | Becomes |
|---|---|---|
| `11` | `title` | `'Open Agent Kernel'` |
| `70` | `keywords` | `open agent kernel, OAK` added in front; `agent kernel` kept |
| `111` | `og:site_name` | `'Open Agent Kernel by Yaala Labs'` |
| `187`, `228` | JSON-LD `name` | `'Open Agent Kernel'` |
| `229` | JSON-LD `alternateName` | `['OAK', 'Agent Kernel', 'Open Agent Kernel by Yaala Labs']` |
| `328` | `blogTitle` | `'Open Agent Kernel Blog'` |
| `439` | navbar logo `alt` | `'Open Agent Kernel logo'` |

The `og:title`, `twitter:title` and description strings follow rewrite rules 1 to 3. The colour mode block
(`:514`) does not change.

### Behavioural changes

1. Every page of the site shows the new name, logo and palette. Intentional.
2. Browser titles change from "... | Agent Kernel" to "... | Open Agent Kernel". Intentional; the old name
   stays in structured data and keywords.
3. Eleven static URLs stop resolving after deploy: `/video/hero.mp4`, `/img/cta-bg.png` and the nine old
   SVGs under `/img/branding/`. Intentional; nothing in the repository links to them from outside the site
   source, and the three paths most likely to be linked externally keep their names.
4. The root README loads its logo from `branding/` instead of `docs/static/img/branding/`. Intentional.
5. `ak-py/README.md` changes, so the PyPI long description changes at the next release. Intentional.
6. Bundled skill prose and `description` text change in the next wheel. Skill names and frontmatter `name`
   do not change. Intentional.

**Non-changes:** the Python package and its behaviour, API titles, span names, log text, config keys,
environment variables, documentation URLs and slugs, sidebar structure, the 20 older doc versions, blog
posts, the test suite.

## Error handling

- The rename script writes only to files matched by the area globs above and exits non-zero if asked to
  touch a file with an extension other than `.md` or `.mdx`.
- Unbalanced code fences: the file is skipped and reported, never guessed at.
- A broken link fails the docs build (`onBrokenLinks: 'throw'`).
- A reference to a deleted asset is caught by the grep in Testing, step 4, before the build.

## Testing

No Python file changes, so the `ak-py` test suite is not part of this change. Step 1 enforces that.

1. **Scope guard.** `git status --porcelain` lists no `.py`, `.toml`, `.tf`, `.yaml` or `.yml` file, nothing
   under `docs/blog/*.md`, nothing under `docs/versioned_docs/` outside `version-0.10.1`, and nothing under
   `docs/specs/` outside this folder.
2. **Leftover name.** `git grep -n "Agent Kernel"` over the in-scope globs, ignoring "Open Agent Kernel",
   returns only lines inside code spans or blocks, code comments in `.tsx` files, the keyword and
   `alternateName` entries in `docs/docusaurus.config.js`, and the sentence in the naming section of
   `AGENTS.md` that records the former name.
3. **Old colours.**
   `grep -rniE '#00ddff|#00e5ff|#00d4ff|#f200ff|#010002|rgba\(0, ?2(21|29|12), ?255|rgba\(242, ?0, ?255' docs/src docs/docusaurus.config.js`
   prints nothing.
4. **Old assets.** `git grep -n -E 'agent-kernel-(icon|lockup)|hero\.mp4|cta-bg\.png' -- . ':!docs/versioned_docs' ':!docs/blog' ':!docs/specs'`
   prints nothing.
5. **Snapshot parity.** `diff -rq docs/docs docs/versioned_docs/version-0.10.1` prints nothing.
6. **Build.** `cd docs && NODE_ENV=production NODE_OPTIONS=--max-old-space-size=6144 npm run build` passes.
7. **Visual review.** Screenshots at 1440 x 900 of `/`, `/features`, `/use-cases`, `/docs`,
   `/docs/quick-start` and `/blog`, and of `/` at 390 px wide, in both colour modes, are compared with the
   brand guide. Checks:
   the logo is the right lockup, orange appears only in accent roles, no cyan or magenta remains, text
   contrast holds on both surface levels, and the reduced-motion hero is static.
8. **Punctuation.** No added line contains a dash character that its removed counterpart did not.
