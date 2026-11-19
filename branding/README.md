# Open Agent Kernel brand assets

The logo set and colour palette for Open Agent Kernel (OAK). Use these files as they are: do not redraw,
recolour, stretch or add effects to the mark or the lockups.

<p>
  <img src="primary/open-agent-kernel-color.svg" alt="Open Agent Kernel primary lockup" height="72" />
  &nbsp;&nbsp;&nbsp;&nbsp;
  <img src="oak-horizontal/oak-horizontal-color.svg" alt="OAK horizontal lockup" height="56" />
  &nbsp;&nbsp;&nbsp;&nbsp;
  <img src="oak-vertical/oak-vertical-color.svg" alt="OAK vertical lockup" height="72" />
</p>

## Name

- Full name: **Open Agent Kernel**. Short name: **OAK**, always in capitals.
- Use the full name in titles and on first mention, written as "Open Agent Kernel (OAK)". Use "OAK" after that.
- Identifiers keep their current form: the `agentkernel` package, the `ak` CLI, `AKConfig`, `AK_*` environment variables.

## Logos

| Folder | Lockup | Use it for |
|---|---|---|
| `primary/` | Mark with "OPEN AGENT KERNEL" | The website navigation bar, the README header, social cards, covers, anywhere the full name should be read |
| `oak-horizontal/` | Mark with "OAK", side by side | Footers, compact headers and other spaces with limited height |
| `oak-vertical/` | Mark above "OAK" | Square spaces such as avatars and stickers |
| `logo-mark/` | The mark alone | Favicons, app icons, inline icons, diagram nodes |

Each lockup comes in six colourways. The mark comes in four (no `color` or `white-orange`, since it has one colour).

| File suffix | Colours | Background to use it on |
|---|---|---|
| `color` | Orange mark, Prussian Blue type | White and light backgrounds |
| `white-orange` | Orange mark, white type | Black, Prussian Blue and other dark backgrounds |
| `orange` | All Tiger Flame Orange | Prussian Blue |
| `blue` | All Prussian Blue | Pale Sky and other light blues |
| `white` | All white | The orange gradient and the blue gradient |
| `black` | All black | Grey and single-colour print |

Variants of one lockup share an aspect ratio, so they can be swapped at a fixed width or height.

## Colours

| Name | Hex | RGB | Role |
|---|---|---|---|
| Tiger Flame Orange | `#FF5E32` | 255, 94, 50 | Accent: the mark, calls to action, links, highlights |
| Prussian Blue | `#02284F` | 2, 40, 79 | Base: dark surfaces, type on light backgrounds |
| Dusk Blue | `#3F598A` | 63, 89, 138 | Support: borders, secondary surfaces |
| Pale Sky | `#ABCEE1` | 171, 206, 225 | Support: secondary text on dark, light surfaces |
| Baby Blue Ice | `#B1CDFF` | 177, 205, 255 | Support: ambient glows, diagram lines |

Orange is an accent. Keep it to the few things a reader should notice first, and let the blues carry the rest.

Text on an orange fill uses Prussian Blue or darker (4.86:1 or better). White text on orange is 3.04:1 and
is reserved for the logo and large display type.

## Gradients

```css
/* Orange */
background: linear-gradient(135deg, #FF5E32 0%, #F58A5E 100%);

/* Blue */
background: linear-gradient(225deg, #011C37 0%, #02284F 45%, #3F598A 100%);

/* Ice */
background: linear-gradient(135deg, #B1CDFF 0%, #3F598A 100%);

/* Sky */
background: radial-gradient(ellipse at 50% 0%, #ABCEE1 0%, #3F598A 75%);
```

The website does not use the gradients: its surfaces are flat (see below). They are for covers, social
cards and print.

## Website design system

The website (`docs/`) is built from one small system. Its tokens and classes are in
`docs/src/css/custom.css`, under "Design system: foundations" and "Design system: components".

**Type.** One scale, fluid between a 390 px and a 1440 px viewport.

| Token | Class | Size | Use it for |
|---|---|---|---|
| `--ak-type-display` | `ak-display` | 44 to 88 px | The hero headline only |
| `--ak-type-h1` | `ak-h1` | 38 to 64 px | The page title |
| `--ak-type-h2` | `ak-h2` | 32 to 52 px | Section titles |
| `--ak-type-h3` | `ak-h3` | 24 to 30 px | Titles inside a section |
| `--ak-type-h4` | `ak-h4` | 20 to 22 px | Card titles |
| `--ak-type-lead` | `ak-lead` | 18 to 21 px | The sentence under a title |
| `--ak-type-body` | `ak-body` | 17 to 18 px | Running text |
| `--ak-type-small` | `ak-small` | 15 px | Captions and secondary text: the smallest size for running text |
| `--ak-type-label` | `ak-label` | 13 px | Monospace section labels, in capitals |

Running text is 15 px or larger; the only smaller sizes are the 13 px monospace label and 14 px for labels
inside diagrams.

**Space.** Use the `--ak-space-*` steps (4, 8, 12, 16, 24, 32, 48, 64, 96, 128, 160 px). Page content sits in
`ak-container` (1280 px with a fluid gutter), sections use `ak-section` for their vertical padding, and prose
is held to `--ak-measure` (720 px).

**Shape.** Two corner radii: `--ak-radius-control` (8 px) for buttons, inputs and tags, and
`--ak-radius-card` (16 px) for cards and panels. Borders are one-pixel hairlines in `--ak-border`.

**Components.**

| Piece | Class or component | Notes |
|---|---|---|
| Section header | `SectionHeader` (`docs/src/components/ui/`) | A numbered monospace label, a title and one lead sentence, left-aligned |
| Buttons | `ak-btn` with `ak-btn--primary` or `ak-btn--secondary`, and `ak-btn--small` | Rectangular. One primary action per view |
| Text link | `ak-link` | Orange text with an arrow, for "Learn more" style links |
| Card | `ak-card` | A hairline border in the dark mode, a soft shadow in the light mode |
| Tag | `ak-tag` in an `ak-tag-row` | Short labels only |
| Dark panel | `ak-dark` | Pins a subtree to the dark values in either mode, as the closing panel does |
| Page header | `PageHero` (`docs/src/components/ui/`) | The header of every page below the home page: label, title, lead, actions and an optional drawing |
| Entrance | `Reveal` (`docs/src/components/ui/`) | The one entrance effect: content below the fold fades up once as it enters the view |

**Rules.**

- Surfaces are flat (no gradient fills, glass blur, glows or drop shadows), with two exceptions: cards lift
  with one soft shadow in the light mode, and floating layers (the chat launcher and its panel) carry a shadow.
- Content is never hidden without script, with reduced motion, in print, or when it is already on screen at
  load. `Reveal` is the only entrance effect.
- Section headers are left-aligned and headings are in sentence case.
- Orange is for the one thing to notice in a view: the primary action, the active item, the accent in a drawing.
- Every colour comes from a token, so that both colour modes work. Check new work in both.
- Interface icons are Tabler outline icons (`react-icons/tb`). Brand marks are Simple Icons (`react-icons/si`), and another set only where Simple Icons has no mark (AWS, Microsoft, Azure).
- A section that links to an `id` on another page registers it with `useBrokenLinks().collectAnchor(id)`, so the build checks the link.

**Moving illustrations.** The site's own illustration style is line art in motion, called particles on
rails: fine blue rails, dots that travel along them, and one orange element per drawing. The drawings are in
`docs/src/components/VectorMotion/` (`StageMotion`, one per stage) and `docs/src/components/LevelStack/`
(the three reading levels as one stack). A new drawing uses the same two colours and stroke width, pauses
when it is off screen, and shows a still frame when the visitor asks for reduced motion.

**Dot fields.** Three places draw fields of fine dots on the GPU: the mark in the home hero
(`docs/src/components/ParticleLogo/`), the wave behind the closing panel and the floor under the
integrations section (`docs/src/components/DotField/`, `Wave` and `Floor`, on the shared runner in
`engine.ts`). They use no library, read their colours from the theme tokens and pause off screen. They are
decoration, so nothing depends on them: without WebGL or with reduced motion the hero shows the plain mark,
the wave is one still frame with reduced motion, and the floor is not drawn.

## Blog banners

Every blog post has a banner: it is the post's `image:` in the front matter and the first image under its
title. Banners are 3200 by 1680 px (1600 by 840 CSS px at twice the density), on the pale background with
the Primary lockup, a short headline whose last words are in Tiger Flame Orange, one line of subtitle, and
one still from the stage drawings.

To make a banner for a new post:

1. Add an entry to `blog-banner/banners.json`: a `slug`, a `label` for the pill, the `title` and its
   `accent` (the last words of the headline), a `subtitle`, and a `drawing` (`build`, `connect`,
   `remember`, `guard`, `scale` or `observe`). Take the words from the post; do not add claims of your own.
2. Run `node branding/blog-banner/render.mjs <slug>`. It needs Node 22 or later and Google Chrome, and
   writes `docs/static/img/blog/<slug>-banner.png`.
3. In the post, set `image: /img/blog/<slug>-banner.png` and put the same image under the title.

The page that is rendered is `blog-banner/template.html`. Open it in a browser with the entry's fields as
the query string to preview a banner. The eight banners that predate the template were recoloured from
their pixels and keep their own layouts; their headlines still carry the earlier name.

## Source files

The designer's originals (the Illustrator file, the guideline PDF and PNG exports) live in `branding/source/`,
which is ignored by git because of its size. The SVGs here are byte-for-byte copies of the ones in that
folder, renamed.

The website serves its own copies of the files it needs from `docs/static/img/branding/`. When a logo
changes here, update that copy too.
