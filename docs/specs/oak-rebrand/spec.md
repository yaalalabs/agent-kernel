# Rebrand to Open Agent Kernel (OAK): implementation spec

This document details how the rebrand in [design.md](design.md) is built: the brand asset set, the theme
tokens, the website's own components, the blog pages and the rename rules. `design.md` is the requirements
source.

- The design system (type scale, spacing, radii, component classes, surface and motion rules, icon
  families) is specified in [branding/README.md](../../../branding/README.md#website-design-system). It is
  not repeated here; sections 4 and 6 to 8 cover what that document does not.
- Counts and line numbers in sections 1 to 3 and 5, and in the Consumer and Config tables, were taken on
  branch `feat/rebranding_oak` at commit `c514f928c`, before the site was rebuilt. They locate each change
  in the files as they were then.

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
| `img/branding/open-agent-kernel-white-orange.svg` | Primary lockup, white and orange | `agent-kernel-icon-horizontal-color-dark-bg.svg` in the navbar (dark mode) and the footer |
| `img/branding/open-agent-kernel-color.svg` | Primary lockup, colour | new: the navbar in the light mode |
| `img/branding/oak-horizontal-white-orange.svg` | OAK Horizontal, white and orange | `agent-kernel-icon-horizontal-color-dark-bg.svg` in the chatbot header; the docs sidebar in the dark mode |
| `img/branding/oak-horizontal-color.svg` | OAK Horizontal, colour | new: the docs sidebar in the light mode |
| `img/branding/oak-avatar.svg` | mark on a disc | new: the shared blog author (section 8) |
| `img/branding/oak-mark-orange.svg` | mark, orange | `agent-kernel-icon-color.svg` |
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
In the light mode `--ifm-color-primary` is `#D23F17`, the darkened orange, so links stay readable on white.

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
   footer and the chat launcher are pinned.
5. Single-colour logos carry `mono: true` and take `--ak-mono-filter`, so they are white on dark and
   near-black on light. This includes logos whose file is drawn in white.
6. Translucent black fills use `--ak-scrim-rgb` (`0, 0, 0` in dark, `214, 225, 240` in light), so a panel that
   darkens a navy surface tints a white one instead.
7. Canvas and WebGL code reads the tokens at run time through `themeRgba`, `themeInt` and
   `onThemeChange` in `docs/src/lib/brand.ts`.
8. `docs/docusaurus.config.js` enables the switch and makes light the default (`disableSwitch: false`,
   `defaultMode: 'light'`, `respectPrefersColorScheme: false`), and gives the navbar logo a light source
   (`open-agent-kernel-color.svg`) and a `srcDark` (`open-agent-kernel-white-orange.svg`).

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
   greys, and the categorical colours that tell diagram node kinds apart.
7. **Removed, not mapped:** the per-persona accents (amber, green, magenta). The persona pages take the
   brand palette (section 7).

Diagram colours. Mermaid diagrams have two palettes, one per colour mode.

The dark palette is `themeConfig.mermaid.options.themeVariables` in `docs/docusaurus.config.js`. Both
colour modes use the customised `base` theme (`theme: { light: 'base', dark: 'base' }`).

| Mermaid theme variable | Becomes |
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

The light palette is `LIGHT_VARIABLES` in `docs/src/theme/Mermaid/index.tsx`:

| Mermaid theme variable | Light value |
|---|---|
| `background`, `edgeLabelBackground`, `sequenceNumberColor` | `#FFFFFF` |
| `primaryColor`, `mainBkg`, `actorBkg` | `#EEF3FB` |
| `primaryBorderColor`, `nodeBorder`, `lineColor`, `signalColor`, `loopTextColor`, `actorBorder`, `labelBoxBorderColor`, `activationBorderColor`, `secondaryBorderColor` | `#3F598A` |
| `textColor`, `primaryTextColor`, `secondaryTextColor`, `tertiaryTextColor`, `titleColor`, `actorTextColor`, `signalTextColor`, `labelTextColor`, `noteTextColor` | `#02284F` |
| `clusterBkg`, `tertiaryColor` | `#F6F8FC` |
| `clusterBorder`, `tertiaryBorderColor` | `#B9C8E0` |
| `secondaryColor`, `labelBoxBkgColor`, `activationBkgColor` | `#E1EAF7` |
| `actorLineColor` | `#8FA1C2` |
| `noteBkgColor`, `noteBorderColor` | `#FFF0EA`, `#F2A98F` |

How the light palette reaches a diagram:

1. The Docusaurus Mermaid theme passes one set of `themeVariables` to Mermaid, so the config cannot hold
   two palettes.
2. The swizzled wrapper reads the colour mode (`useColorMode`). On the dark page the diagram source is
   passed through unchanged.
3. On the light page `forColorMode` prepends an init directive
   (`%%{init: {"theme":"base","themeVariables":{...}}}%%`) carrying `LIGHT_VARIABLES`. If the source starts
   with a front matter block, the directive goes after it, because front matter has to stay first.
4. The same function serves the inline diagram and the expanded (lightbox) view.
5. Switching the colour mode re-renders the diagram with the other palette. No diagram source in the docs
   is edited for this.

Limits: a diagram that carries its own `%%{init}%%` directive is not handled specially (none in the docs
does). Flowcharts, sequence diagrams and a diagram with front matter were checked in both modes; class and
state diagrams were not.

In-page `style` lines (29 files in `docs/docs`, and the same 29 in the `0.10.1` snapshot) change fill and
label colour together, so a node a diagram colours itself reads on either background:

| Old fill | Uses | New fill | New label colour |
|---|---|---|---|
| `#2e8555` | 73 | `#FF5E32` | `#02284F` |
| `#25c2a0` | 23 | `#3F598A` | `#fff` |
| `#1ebbd7` | 13 | `#B1CDFF` | `#02284F` |
| `#7d5ba6` | 8 | `#ABCEE1` | `#02284F` |

Vendor fills in those diagrams (`#ff9900`, `#0078d4`, `#4285f4`, `#326ce5`) do not change.

### 4. Hero and closing visuals

Superseded: the first version of this section specified one component, `OakMark` (a particle mark on a 2D
canvas for the hero, and a flat mark with a glow for diagram hubs and calls to action), and a recoloured
`PlantParticlesBackground`. Both were built, reviewed and replaced, and neither is in the tree. The
diagram hubs and the image calls to action went with the pages that held them (sections 6 and 7). What
shipped is below.

**Home hero: `docs/src/components/ParticleLogo/`** (`index.tsx`, `styles.module.css`)

```tsx
export default function ParticleLogo(props: { className?: string }): JSX.Element;
```

- The mark as a field of fine dots, drawn with raw WebGL. No library.
- Dots are placed once, from a seeded generator, so every visit sees the same field:
  - a hexagonal lattice inside the two halves of the mark (step `UNITS / 64`), lightly jittered
  - every third dot repeated on a layer behind, which gives the mark thickness as it turns
  - a denser line along the outline, and a little dust around the mark
- Every dot is moved in the vertex shader from a few uniforms (time, build, scatter, hover, pointer,
  tilt), so the page thread does no per-dot work.
- Behaviour:
  - on load the mark comes into focus over two seconds (`BUILD_SECONDS`): the dots start as a loose haze
    close to their places, then fade in and tighten
  - at rest a slow wave lifts rows of dots and the mark turns a little
  - under the pointer rings travel out, the dots swirl and the mark leans towards the pointer; the ripple
    trails the cursor by a moment and lingers after it
  - as the page scrolls the dots let go and drift up and out; scrolling back gathers them
- Colours come from the theme through `docs/src/lib/brand.ts` and are repainted on a colour mode change:
  additive blending on the dark page, ink on the light page with a slightly larger dot.
- The canvas fills the hero. An `anchor` box, sized in the stylesheet, says where the mark sits.
- The loop stops while the hero is off screen or the tab is hidden.
- Fallback: with `prefers-reduced-motion: reduce`, without WebGL, without script, or when the browser
  takes the WebGL context away, the plain SVG mark is shown in the anchor box.
- The component is decorative (`aria-hidden`).

**Dot fields: `docs/src/components/DotField/`** (`engine.ts`, `Wave.tsx`, `Floor.tsx`, `styles.module.css`)

```ts
export function runDots(canvas: HTMLCanvasElement, scene: DotScene, still?: boolean): () => void;
export function tokenColour(element: Element, token: string): [number, number, number];
```

- `engine.ts` is a small WebGL runner. A scene supplies its vertex shader, its attributes and a function
  that sets its uniforms each frame. The runner starts a scene when its canvas first nears the screen,
  sizes the canvas to its box, stops drawing while it is off screen or the tab is hidden, and cleans up.
  All scenes share one fragment shader (a round dot).
- `Wave` is a sheet of dots that rolls like slow water, seen from a low angle, behind the copy of the
  closing panel. It thins out towards the copy and carries the accent on its crests. With reduced motion
  it draws one still frame.
- `Floor` (`{ stage: number }`) is a floor of dots along the bottom edge of the integrations section
  (section 6). It is told apart from the wave on purpose: centred and calm, one colour at rest, with the
  accent only as a ripple that crosses it when `stage` changes, in the direction the visitor moved. With
  reduced motion it is not drawn.
- Both are decoration: without WebGL nothing is drawn and no content is affected.

**Closing panel: `ClosingPanel` in `docs/src/components/HomeSections/index.tsx`**

- A panel pinned to the dark tokens (`ak-dark`), so it is navy in both colour modes: the wave, a heading,
  one lead sentence, a primary and a secondary action.
- It ends the home, features, use-cases and persona pages. `CTASection` renders the same panel above the
  footer on docs and blog pages. It replaces every use of `cta-bg.png`.

**Seals: `docs/src/components/BrandArt/`**

- `CertSeal` (`shape: 'seal' | 'shield'`) draws the ISO 27001 seal and the SOC 2 shield from theme tokens,
  for the trust marks row. It replaces `iso.png` and `soc.png`.
- `business_leader.png`, `developer.png` and `ai.png` are replaced by the level stack (section 6).

Docs sidebar (`docs/src/theme/DocSidebar/Desktop/`): the stock component, ejected so that it renders the OAK
Horizontal lockup at 1.4rem through `ThemedImage`, not a copy of the navbar logo.

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
   - The hyphen exclusion protects identifiers such as `ak-py`, and it also skips prose compounds. Those
     are fixed by hand, outside code spans and blocks: "AK-internal", "AK-owned", "AK-first" and
     "AK-level" become "OAK-internal" and so on (22 occurrences in 11 files: three dev skills, two docs
     pages and their `0.10.1` copies, four example READMEs).
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
- Component names, file names, imports and class names do not change (for example
  `AgentKernelSitsInFlowDiagram`).
- `docs/blog/authors.json`: every "Agent Kernel Team" title becomes "Open Agent Kernel Team" (section 8
  covers the author entries).
- `docs/static/robots.txt:1`: the comment takes the full name.

The `0.10.1` snapshot:

The snapshot is edited in place. It is never overwritten from `docs/docs`: the two trees already differ
in ten of their 76 pages at the merge base (`advanced/queue-mode-guide.md`, `api/a2a-server.md`,
`api/agui-server.md`, `api/mcp-server.md`, `api/rest-api.md`, `core-concepts/configuration.md`,
`core-concepts/module.md`, `frameworks/pydantic-ai.md`, `integrations/agui.md`, `intro.md`), because
`docs/docs` has moved on since the release. A mirror would publish unreleased behaviour under `0.10.1`.

1. The rename script runs on `docs/versioned_docs/version-0.10.1` as its own area, with the same rules.
2. The diagram `style` replacement (section 3) runs on the same 29 pages there.
3. Hand edits made in `docs/docs` are ported one by one: the rename fixes the script could not make (the
   flagged lines, and the "AK-" compounds of rule 6) and the semicolon in the sequence diagram of
   `advanced/threads.md`.
4. `whats-new.md` is added and listed in `docs/versioned_sidebars/version-0.10.1-sidebars.json`, and the
   "What's New" list in `intro.md` becomes the two-line tip (section 8).
5. Nothing else in the snapshot changes. Testing step 5 checks this against the merge base.

### 6. Home page sections

`docs/src/pages/index.tsx` renders, in order: `Announcement`, `Hero`, `TrustMarks`, `CapabilityRail`,
`ArchitectureOverview`, `Integrations`, `Deployment`, `Levels`, `FAQ`, `ClosingPanel`. The sections live
in `docs/src/components/HomeSections/`. Their type, spacing, buttons, cards and tags are the design
system's (`branding/README.md`, *Website design system*); only what that document does not cover is
specified here.

**Pinned integrations section: `HomeSections/Integrations.tsx`**

- Data: `INTEGRATION_ROWS` in `HomeSections/integrations.data.tsx`, 82 integrations, each with a `name`,
  a `role`, and a logo (an icon component, or an image with an optional `mono` flag). Every provider
  `type` the runtime ships has an item, except the `in_memory` defaults. Names are unique, because the
  architecture diagram picks chips by name.
- Grouping: `GROUPS` has six groups named after the six stages. A group has titled sets, and a set lists
  the roles it shows. An integration whose role no set names is not dropped: it appears in a "More" set
  at the end of the last group.
- Every group, with every integration name, is in the server-rendered page.
- The section pins where the window is roomy enough, `(min-width: 997px) and (min-height: 700px) and
  (prefers-reduced-motion: no-preference)`, and the tallest group is measured to fit the pinned frame.
  The pinned layout is applied on trial and measured before the browser paints; the pinned behaviour
  starts only once the measurement has passed. Where it fails (about 1000 by 700), the six groups are
  stacked one after another, and the trial is repeated when a resize comes to rest. Short or narrow
  windows set the groups a little closer, so that 1280 by 720 and 1024 by 768 still pin.
- Under 997 px the six groups fold: a group's heading opens and closes its integrations, groups open
  independently, and the first starts open. The stylesheet folds them before script runs. Closed groups
  are hidden with `hidden="until-found"`, so find-in-page still reaches them. Nothing is folded without
  script (a `noscript` rule) or in print.
- With reduced motion on a wide screen, and without script, the six groups are stacked one after another.
- While pinned:
  - the section is one screen plus 45vh for each group tall (`--steps` is the number of groups) and its
    frame is sticky; the scroll position inside the section picks the group in view
  - the group list on the left is a control: choosing a group scrolls the page to the middle of that
    group's step
  - the frame keeps the height of the tallest group, so it does not jump between groups
  - groups that are not showing stay findable: they are hidden with `hidden="until-found"`, and a
    find-in-page match brings its group forward; a browser without that value hides them plainly
  - a link to an anchor further down the page (the persona pages link to `#levels`) is scrolled to once
    more after pinning has changed the section's height
- `DotField/Floor` runs along the bottom edge and ripples when the group changes (section 4).

**Level stack: `docs/src/components/LevelStack/`** and `HomeSections/Levels.tsx`

```tsx
export type LevelStackProps = {
  active?: number | null;                 // the layer to light: 0 is the top, null lights none
  onActivate?: (level: number) => void;   // called when the pointer enters a layer
  className?: string;
};
```

- One SVG drawing of three layers, each drawn flat in a 220 unit square and projected by one matrix: the
  outcome (tiles and a rising line), the code (a file with one line lit), the runtime (a lattice of
  workers, one in the accent). Dots drop along the ties between layers. Colours and stroke match the
  stage drawings.
- The drawing is decorative (`aria-hidden`); the rows beside it carry the text and the links.
- On the home page (`Levels`) the drawing and three rows are one control: a row lights its layer, and a
  layer lights its row. Until the visitor points at something, the light walks down the stack every
  2.8 seconds while the section is on screen. With reduced motion it does not walk. Under 997 px, where
  the drawing sits above the rows and the two are never in view together, it does not walk either: the
  drawing is still, no row is singled out, and all three rows are at full strength.
- Each row links to its persona page. The section registers its `levels` anchor with
  `useBrokenLinks().collectAnchor`, because the persona pages link back to it.
- Each persona page header shows the same drawing with its own layer lit.

**Other sections**

- `CapabilityRail` (`HomeSections/index.tsx`): `STAGES`, six entries of
  `{ id, name, summary, points, file, language, code, docs }`, each shown with its `StageMotion` drawing
  from `docs/src/components/VectorMotion/` and the code or config that switches the stage on.
- `ArchitectureOverview`: three columns, sources (channels and clients), the runtime, and destinations
  (agents, data and clouds). The runtime is one `ak-dark` panel as tall as the columns beside it, so each
  card joins it with one straight rail. The rails are CSS, with a dot
  travelling each one; the diagram needs no script. Its cards come from `ArchitectureOverview/data.tsx`,
  which picks integrations by name from `INTEGRATION_ROWS`.
- `Deployment`: `TARGETS`, entries of `{ icon, name, description, modes, modules }`.
- `Announcement`: one line above the hero for the newest headline capability, with a link to its guide.
- `TrustMarks`: licence, the two foundation memberships and the two compliance seals. No figures.

### 7. Features, use-cases and persona pages

- All five pages start with `PageHero` (`docs/src/components/ui/`) and end with `ClosingPanel`.
- `docs/src/pages/features.tsx`: `STAGES`, six stage groups holding 36 capabilities of
  `{ title, summary, points?, guide, more? }`, beside a sticky index of the stages. Every capability links
  to its guide.
- `docs/src/pages/use-cases.tsx`: real projects, scenarios with a guide and an example each, kinds of
  team, and a neutral before and after list. The review behind both pages is
  [research/features-use-cases-review.md](research/features-use-cases-review.md).
- The three persona pages (`developer.tsx`, `ai-engineer.tsx`, `business-leader.tsx`, styled by
  `persona.module.css`) are built from `docs/src/components/PersonaKit/`, so they read as one set:

| Export | What it is |
|---|---|
| `Journey({ steps, children })` | The step rail (`StepTimeline`) and the sections it lists; the rail stays in view while they are on screen |
| `PersonaSection({ id, index, label, title, lead?, children })` | One numbered section of the journey |
| `Tabs({ name, label, items })` | A tab set, used for the views of an agent system on the AI engineer page |
| `CodeSample({ title, language, children })` | A framed code sample with its file name |
| `DocLinks({ links })` | A row of documentation links |
| `OtherLevels({ current })` | Links to the other two reading levels |

- A persona page header has a way back to the path selection (`PageHero`'s `back` prop, to `/#levels`)
  and shows the level stack with its own layer lit.
- No page passes its own accent colour. The step rail and every drawing use `--ak-primary` and the
  ambient blues, and the pages follow the colour mode like every other page.

### 8. Blog and what's new page

**Blog pages.** Styles are in `docs/src/css/blog.css`, which replaces `blog-medium.css`.

- Index (`docs/src/theme/BlogListPage/`):
  - `PageHero`, then a topic bar that stays in view (`position: sticky`)
  - topics come from `BLOG_TOPICS` in `docs/src/components/Blog/topics.ts`, which groups posts by matching
    their front matter tags; only topics with at least one post are shown, and a post whose tags match no
    topic still appears under "All"
  - the chosen topic lives in the URL (`?topic=<slug>`), so a filtered view can be shared; it is applied
    after mount, so the server-rendered page is the unfiltered list
  - with no filter the newest post is a lead card (`BlogPostCard` with `lead`), and the rest are a grid of
    cards: three columns, then two, then one
- Tag page (`docs/src/theme/BlogTagsPostsPage/`): the same header and grid.
- Card (`docs/src/components/Blog/BlogPostCard/`): the banner, a line of facts (topic, date, reading
  time), the title, the description and the author.
- Post page (`docs/src/theme/BlogPostPage/`):
  - a reading column at `--ak-measure` (720 px) on the page container, with article text at 19 px
  - above the title: an "All posts" link, and the post's first topic, which links to the filtered index
  - beside the post on a wide screen: the table of contents, unless the post sets
    `hide_table_of_contents`
  - the previous and next links are two flat cards; docs pages use the same pair
- A new post needs no code change unless its tags fit no topic; then extend `BLOG_TOPICS`.

**Authors** (`docs/blog/authors.json`).

- The shared entry `yaala` is named "OAK" and pictured by `/img/branding/oak-avatar.svg`: the mark on a
  disc, because the bare mark touches the edge of its box and a round crop cuts its corners.
- Posts name their writers. The 14 posts that were credited to the shared entry now carry
  `authors: [amitha]` (12 posts) or `authors: [john]` (2 posts), taken from the commit history. Three
  posts already named their writer and are unchanged.
- An author with no picture of their own uses the OAK avatar.

**Banners.** The template, its data and the renderer are in `branding/blog-banner/`; the steps for a new
banner are in `branding/README.md` (*Blog banners*).

- Every one of the 17 posts sets `image:` to its banner. Ten posts had `image: /img/card.png`; they now
  point at their own banner and show it under the title.
- Ten banners are rendered from the template. Eight existing images (seven banners and one figure inside
  a post) are recoloured in place and carry the new mark; their layouts are kept, and so are their
  baked-in headlines, which still say "Agent Kernel".
- These are the only edits to files under `docs/blog/`: `authors.json`, and in posts the `authors` and
  `image` front matter and one banner image line. No sentence of a post is changed.

**What's new page.**

- `docs/docs/whats-new.md` (`sidebar_position: 2`): the list that used to open the introduction, newest
  first, each entry linked to its guide, with a pointer to the GitHub releases for the full history.
- `docs/docs/intro.md` keeps a two-line tip that names the latest additions and links to the page.
- The `0.10.1` snapshot has the same page and tip, without the entries for capabilities that are not in
  that release (today: the agent registry).
- `ak-dev-sync-docs-from-branch` tells a contributor to add an entry at the top when a branch ships a
  headline capability.

### 9. llms.txt

Two files for AI assistants, in the format of [llmstxt.org](https://llmstxt.org), written by a local
plugin on every build. No dependency is added.

**Plugin: `docs/plugins/llms-txt/`** (`index.js`, the text helpers in `text.js`, the summary in `template.md`)

- It runs in `postBuild` and reads what Docusaurus has loaded: the docs plugin's versions, each page's
  title, permalink and source file, the resolved sidebar, and the blog plugin's posts.
- It describes the version served at `/docs` (`isLast`): the released docs, because that is what an
  installed package matches. Pages marked `draft` or `unlisted` are left out.
- `/llms.txt`:
  1. the summary from `template.md`, hand-written: what OAK is, the identifiers that kept the old name,
     the install command, the supported Python versions, where other versions of the docs are, and the
     licence. `{{site}}` and `{{version}}` are filled in.
  2. one section per top-level sidebar category, with the loose pages first under "Getting started".
     Nested categories are flattened into their parent. A page no sidebar lists goes under "More".
  3. each page as `- [title](absolute address): description`. The description is the front matter
     `description` where there is one, else the first sentence of the page's opening paragraph, at most
     220 characters. A nested page titled "Overview" is named after its category.
  4. the hand-written "Website" and "Source and packages" sections, then the blog posts under
     "Optional", which the format lets a reader skip.
- `/llms-full.txt`: the markdown of the same pages in the same order, each under a `Source:` line with
  its address. Front matter and MDX import lines are removed. Every relative link is made absolute: a
  link to a markdown file becomes the address of that page, and any other path is resolved from the
  page's own address. Fenced code is left exactly as written.
- The files exist only in a build. `npm start` does not serve them.

### Consumer changes

Asset references, as they are in the tree:

| Reference | Location | Becomes |
|---|---|---|
| README lockup | root `README.md`, the `<picture>` at the top | `branding/primary/open-agent-kernel-white-orange.svg` (dark), `branding/primary/open-agent-kernel-color.svg` (light), alt "Open Agent Kernel" |
| Navbar logo | `themeConfig.navbar.logo` in `docs/docusaurus.config.js` | `src: img/branding/open-agent-kernel-color.svg`, `srcDark: img/branding/open-agent-kernel-white-orange.svg`; 3.25rem tall (52 px in the 72 px bar) so the three lines of type stay legible |
| Docs sidebar logo | `docs/src/theme/DocSidebar/Desktop/index.tsx` | `oak-horizontal-color.svg` (light), `oak-horizontal-white-orange.svg` (dark) |
| Footer logo | `docs/src/theme/Footer/Layout/index.tsx` | `img/branding/open-agent-kernel-white-orange.svg` (the footer is navy in both modes) |
| Chatbot header | `docs/src/components/FloatingChatbot/index.tsx` | `img/branding/oak-horizontal-white-orange.svg` |
| Chatbot launcher | same file | the mark drawn inline beside the label "Ask OAK"; no image file |
| In-page icon | `AgentKernelSitsInFlowDiagram/index.tsx`, `ArchitectureOverview/index.tsx`, `FloatingChatbot/index.tsx` (welcome screen), `SandboxFlowDiagram/index.tsx` | `img/branding/oak-mark-orange.svg` |
| Hero video | `docs/src/pages/index.tsx` | `ParticleLogo`, inside `HomeSections/Hero.tsx` (section 4) |
| Hub video, hero video on use cases | `features.tsx`, `use-cases.tsx` | removed with the rebuild of those pages; they start with `PageHero` (section 7) |
| CTA image | `CTASection` and the six page files | `ClosingPanel` with the `Wave` dot field (section 4) |

The white mark, `img/branding/oak-mark-white.svg`, is deleted: no source file referred to it once the
launcher drew the mark inline. The canonical copy stays in `branding/logo-mark/`.

Deleted static files (28):

- `video/hero.mp4`, `img/cta-bg.png`, and the nine old `agent-kernel-*` SVGs in `img/branding/`
- `img/business_leader.png`, `img/developer.png`, `img/ai.png`, `img/iso.png`, `img/soc.png`
- `models/brain.glb`, `models/index.glb`, `models/leaf.glb`
- nine integration logos in `img/integrations/` whose integrations now use a vector mark (`chatgpt.png`,
  `crewai.png`, `crewai.svg`, `googleADK.png`, `langgraph.png`, `livekit.png`, `logfire.svg`,
  `pydantic-ai.png`, `smolagents.png`)

Deleted site source: `docs/src/pages/index.module.css`, `docs/src/css/blog-medium.css`,
`docs/src/clientModules/scrollReveal.ts`, and the components `AgentKernelArchDiagram`,
`AgentKernelRuntimeFlowDiagram`, `FeatureExplorer`, `HeroAnimation`, `IntegrationsMarquee`,
`ParticleSphere`, `PlantParticlesBackground`, `RequestLifecycleAnimation`, `UseCaseJourneyMap` and
`Blog/BlogPostRow`.

### Config changes

No `AKConfig`, YAML or environment variable changes.

`docs/docusaurus.config.js` (line numbers as of `c514f928c`):

| Line | Field | Becomes |
|---|---|---|
| `11` | `title` | `'Open Agent Kernel'` |
| `70` | `keywords` | `open agent kernel, OAK` added in front; `agent kernel` kept |
| `111` | `og:site_name` | `'Open Agent Kernel'` (first `'Open Agent Kernel by Yaala Labs'`; the company name left the metadata in iteration 22) |
| `187`, `228` | JSON-LD `name` | `'Open Agent Kernel'` |
| `229` | JSON-LD `alternateName` | `['OAK', 'Agent Kernel']` |
| `328` | `blogTitle` | `'Open Agent Kernel Blog'` |
| `439` | navbar logo `alt` | `'Open Agent Kernel logo'` |

The `og:title`, `twitter:title` and description strings follow rewrite rules 1 to 3.

Also in `docs/docusaurus.config.js`:

- `themeConfig.colorMode`: `defaultMode: 'light'`, `disableSwitch: false`, `respectPrefersColorScheme: false`
  (it was dark only, with the switch disabled).
- `themeConfig.mermaid`: `theme: { light: 'base', dark: 'base' }` and the dark `themeVariables` of section 3.
- `clientModules`: the scroll-reveal module is removed; `ensureGtagGlobal.ts` stays.
- Navbar items: one primary action ("Quick start", `ak-btn ak-btn--primary ak-btn--small`) is added on the
  right. The version menu stays in the config and is shown on docs pages only, by a rule in `custom.css`.

`docs/package.json`: `gsap`, `three` and `@types/three` are removed. Nothing is added.

### Behavioural changes

1. Every page of the site shows the new name, logo and palette. Intentional.
2. Browser titles change from "... | Agent Kernel" to "... | Open Agent Kernel". Intentional; the old name
   stays in structured data and keywords.
3. The 28 static files listed under Consumer changes stop resolving after deploy. Intentional; nothing in
   the repository links to them from outside the site source, and the three paths most likely to be linked
   externally (`img/favicon.ico`, `img/logo.svg`, `img/card.png`) keep their names.
4. The root README loads its logo from `branding/` instead of `docs/static/img/branding/`. Intentional.
5. `ak-py/README.md` changes, so the PyPI long description changes at the next release. Intentional.
6. Bundled skill prose and `description` text change in the next wheel. Skill names and frontmatter `name`
   do not change. Intentional.

7. Light is the default colour mode. A visitor who had never chosen a mode sees the light site;
   the switch in the navbar selects the dark one and the choice is remembered. Intentional.
8. Docs diagrams are drawn in the palette of the colour mode in use. Intentional.
9. The "What's New" list leaves the docs introduction for its own page, which adds one entry to the docs
   sidebar. Intentional; the introduction links to it.
10. Blog posts show a named writer in place of the shared team author, and every post has a banner.
    Blog URLs, slugs, dates and tags do not change. Intentional.

**Non-changes:** the Python package and its behaviour, API titles, span names, log text, config keys,
environment variables, documentation URLs and slugs, the rest of the sidebar structure, the 20 older doc
versions, the text of blog posts, the test suite.

## Error handling

- The rename script writes only to files matched by the area globs above and exits non-zero if asked to
  touch a file with an extension other than `.md` or `.mdx`.
- Unbalanced code fences: the file is skipped and reported, never guessed at.
- A broken link fails the docs build (`onBrokenLinks: 'throw'`).
- A reference to a deleted asset is caught by the grep in Testing, step 4, before the build.
- An integration name that the architecture diagram picks but the integration data does not hold throws
  during static rendering, so the build fails instead of dropping a logo silently.
- An anchor that another page links to is registered with `useBrokenLinks().collectAnchor`, so a renamed
  section id fails the build.
- WebGL missing, refused or lost: the hero shows the plain mark and the dot fields draw nothing. No
  content depends on a canvas.

## Testing

No Python file changes, so the `ak-py` test suite is not part of this change. Step 1 enforces that.
`<base>` is `git merge-base HEAD origin/develop`.

1. **Scope guard.** `git diff --name-only <base>` lists:
   - no `.py`, `.toml`, `.tf`, `.yaml` or `.yml` file
   - nothing under `docs/versioned_docs/` or `docs/versioned_sidebars/` outside `version-0.10.1`
   - nothing under `docs/specs/` outside this folder
   - under `docs/blog/`, one non-post file, `authors.json`; and in posts only front matter and banner
     lines, which this prints nothing for:
     `git diff -U0 <base> -- 'docs/blog/*.md' | grep '^[+-]' | grep -vE '^(\+\+\+|---) ' | grep -vE '^[+-](authors: |image: |!\[[^]]*\]\(/img/blog/[a-z0-9-]+\.png\)$|$)'`
2. **Leftover name.** `git grep -n "Agent Kernel"` over the in-scope globs, ignoring "Open Agent Kernel",
   returns only lines inside code spans or blocks, code comments in `.tsx` files, the keyword and
   `alternateName` entries in `docs/docusaurus.config.js`, and the sentence in `AGENTS.md` that records
   the former name. The same search for the prose compounds
   (`AK-internal`, `AK-owned`, `AK-first`, `AK-level`) returns only code spans and blocks.
3. **Old colours.**
   `grep -rniE '#00ddff|#00e5ff|#00d4ff|#f200ff|#010002|rgba\(0, ?2(21|29|12), ?255|rgba\(242, ?0, ?255' docs/src docs/docusaurus.config.js`
   prints nothing.
4. **Old assets and removed components.**
   `git grep -n -E 'agent-kernel-(icon|lockup)|hero\.mp4|cta-bg\.png' -- . ':!docs/versioned_docs' ':!docs/blog' ':!docs/specs'`
   prints nothing, and so does a search of `.agents/` and `AGENTS.md` for the removed site inventory names
   (`IntegrationsMarquee`, `FeatureExplorer`, `FEATURE_TABS`, `WhatsNewBanner`).
5. **Snapshot scope.** `docs/docs` and the `0.10.1` snapshot are not expected to be identical (they differ
   at the merge base). What is checked is the snapshot's own diff against `<base>`:
   - `git diff --name-status <base> -- docs/versioned_docs/version-0.10.1 | grep -v '^M'` prints one line,
     the added `whats-new.md`
   - with every form of the old and the new name replaced by one token, and the `fill:` and `color:`
     values on diagram `style` lines masked, the only hunks that still differ are the "What's New" block
     of `intro.md`, the new `whats-new.md`, and one message line of the sequence diagram in
     `advanced/threads.md`
   - `docs/versioned_sidebars/version-0.10.1-sidebars.json` gains one line, `"whats-new"`
6. **Build.** `cd docs && NODE_ENV=production NODE_OPTIONS=--max-old-space-size=6144 npm run build` passes,
   with every doc version, and with no broken link or anchor.
7. **Visual review.** Captures at 1440 x 900 and at 390 px wide, in both colour modes, of `/`, `/features`,
   `/use-cases`, one persona page, `/docs`, `/docs/quick-start`, `/blog` and one blog post. Checks:
   - the logo is the right lockup, orange appears only in accent roles, no cyan or magenta remains, and
     text contrast holds on both surface levels
   - a docs page with a flowchart, a sequence diagram and a diagram with front matter reads in both modes
   - at 390 px the integrations section is folded with the first group open, each heading opens and closes
     its group, and all 82 integration names are in the page source
8. **Motion and fallbacks.**
   - with `prefers-reduced-motion: reduce`: the hero shows the plain mark, the integrations section is
     stacked, the stage drawings and the level stack are still, and no content is hidden
   - with JavaScript off: every section of the home page is visible, and at 390 px no integration group
     is folded
   - in print preview, from a phone-width window and from a pinned desktop window: no content is hidden,
     and all six integration groups show their integrations (a printed page is narrower than the fold
     breakpoint, so this is where a folded group would go missing)
9. **Keyboard.** On the home, features, use-cases and one persona page every control is reachable and
   shows a focus ring, including the group list of the integrations section and the blog topic filter.
10. **Punctuation.** No added line contains a dash character that its removed counterpart did not.

Not covered by these steps, and stated as such in the pull request: Safari and Firefox, class and state
diagrams in the light palette, and the WebGL hero on a low-power device.
