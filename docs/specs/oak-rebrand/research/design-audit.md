# Design audit: making the site look professionally designed

Supporting research for the design-system requirements in [../design.md](../design.md) and iterations 10 to
17 of [../plan.md](../plan.md). Measurements were taken on 2026-11-19 from the local dev server at 1440 x 900
in the dark mode, by reading computed styles from the rendered pages.

## Summary

After the rebrand the site is consistent in colour. It still does not read as professionally designed, for
three reasons:

1. **The type is too small and there are too many sizes.** Over a third of the home page's text is below
   14 px, and a quarter is below 12 px.
2. **Every section has its own layout rules.** Container widths, section padding, corner radii and button
   styles change from section to section.
3. **The surface treatment is busy.** Gradients, glows, glass blur and 37 running animations compete with
   the content.

The direction is a flat, clean system: much larger type, fewer sizes, one grid, solid surfaces, hairline
borders, and orange used sparingly.

## What was measured

| Measure | Home | Features | Developer | Docs page |
|---|---|---|---|---|
| Distinct font sizes | 19 | 14 | 13 | 11 |
| Text below 14 px | 37.9% | 26.1% | 52.1% | 12.6% |
| Text below 12 px | 24.5% | 8.0% | 2.3% | 0.3% |
| Most common sizes | 15, 14, 11 px | 14, 15, 16 px | 13, 16, 15 px | 15, 16, 14 px |
| H1 | 56 px | none on the page | 56 px | 35 px |
| H2 | 36, 38.4 and 41.6 px | 40 px | 56 px (same as H1) | 25.6 px |
| Card corner radii in use | 12, 14, 16, 20, 24, 32 px | 8, 10, 12, 16, 20, 24 px | 8, 12, 14, 20, 24 px | 8 px |
| Container widths in use | 700, 720, 760, 1200, 1280, 1320 px | 720, 800, 900, 960, 1152, 1320 px | 980, 1080, 1100, 1152, 1200, 1320 px | 1200, 1320 px |
| Section padding (top/bottom) | 0, 80/88, 128/128 px | 96/64, 80/72, 96/96 px | 32, 96, 112 px | n/a |
| Running animations at rest | 37 | 77 | 25 | 16 |
| Boxes with a gradient background | 11 | 2 | 2 | 0 |

Other measured facts:

- Buttons and pills carry 13.6 px text at 38 to 40 px tall. Navigation links are 14 px.
- Five font weights are in use on the home page (400, 500, 600, 700, 800).
- The features page has no `h1`.
- On the developer page the `h1` and every `h2` are the same size, so the page has no heading hierarchy.

## Findings

Numbered so the plan can refer to them. F1 to F16 are from the first audit; F17 to F23 are new.

**Type**

- **F1. Scale.** Too many sizes, and too small (table above). Headings mix Title Case and sentence case.
- **F17. Weights.** Five weights where two would do.
- **F18. Heading hierarchy.** Three different `h2` sizes on the home page; `h1` equal to `h2` on persona
  pages; no `h1` on the features page.

**Layout**

- **F3. Spacing and grid.** Six container widths and at least four section paddings per page. Empty bands
  sit next to cramped diagrams.
- **F4. Section headers.** Three patterns are in use: a pill with a star, orange square capitals, and
  numbered step labels.
- **F9. Cards.** Six corner radii and three border treatments.

**Components**

- **F2. Buttons.** "Quick Start" is orange in the hero and a dark pill in the closing section. Other pages
  say "Get Started". Every button and tag is a pill, so tags and actions look alike.
- **F8. Icons and logos.** Three icon families plus emoji in the docs introduction. Integration logos mix
  colour with single colour, and PNG with SVG.
- **F12. Floating buttons.** The chat launcher and scroll-to-top stack in one corner and cover text on
  mobile.
- **F13. Navbar.** No primary action. The three-line lockup renders its letters about 9 px tall.

**Surface and motion**

- **F19. Effects.** Gradient text on headings, gradient and glass card backgrounds, glows on buttons and
  hubs, backdrop blur.
- **F14. Motion.** Most sections are hidden until scrolled into view, and dozens of animations run at rest.
- **F23. Imagery.** The site has no illustration language of its own. Raster images were replaced by
  static drawings, diagrams are dense and still, and what moves is decoration, not explanation.
- **F7. Before and after colours.** "Without OAK" is red and OAK is orange; on navy the two are too close.

**Pages**

- **F5. Hero.** The install box competes with the primary button, and the rotated side label is clutter.
  There is no proof near the top.
- **F20. Home feature section.** Six tabs, each holding up to nine small cards of 11 to 14 px text, chips
  and two links. It is the densest part of the page and the hardest to scan.
- **F11. Trust.** Compliance tiles sit alone in one section while the foundation badges are in the footer.
- **F21. Home length.** Ten sections and 9,168 px. Architecture, features and integrations repeat one
  another.
- **F10. Docs chrome.** The sidebar and table of contents are both boxed panels. The long "What's New"
  list pushes the introduction down.
- **F6. Blog.** Banners are white with the old cyan mark, and titles still say "Agent Kernel".
- **F15. Persona pages.** Very long, with a tiny step timeline.
- **F16. Light mode.** A faithful inversion of dark. It needs elevation by soft shadow, not border.
- **F22. Page titles.** "Quick Start", "Get Started", "Learn More", "Read More" and "Choose this path" are
  all used for the same kind of action.

## Reference: choreolabs.com

The maintainer named this site as inspiration for font sizing and for flat, clean design, with the
instruction not to copy it, and supplied twelve screenshots taken at a 1914 px wide viewport. Sizes below are
read off those screenshots, so they are approximate.

**Why copying is a real risk.** The reference uses dark navy and a vivid orange on white. Those are close
to OAK's own brand colours. Colour therefore cannot be what sets us apart; composition has to.

**Type, as observed**

| Element | Reference (at 1914 px) | Ours today (at 1440 px) |
|---|---|---|
| Hero headline | about 125 px, three words, two lines | 56 px, eleven words |
| Section heading | about 72 px | 36 to 42 px |
| Feature title | about 64 px | 15 to 17 px |
| Card or story title | about 48 px; list titles 22 to 28 px | 14 to 16 px |
| Lead and body copy | 20 to 22 px, regular weight, grey | 14 to 16 px |
| Navigation links | about 17 px | 14 px |
| Button label | about 17 px, bold | 13.6 px |
| Uppercase section label | about 14 px, wide tracking | 11 px |
| Smallest text on the page | about 14 px | 11 px |

Headings are a tight, bold geometric sans with negative tracking and a line height under 1.0. Body copy is
a lighter, wider face. Two faces, used consistently.

**Surface, as observed**

- No shadows, gradients, glows or blur anywhere.
- Hairline rules do the structural work. Sections and even the hero's lower row are divided into cells by
  1 px lines.
- Emphasis comes from a solid block of colour: an orange cell behind a button, one navy card among white
  ones, a full orange band for the closing section.
- Cards have a 16 to 20 px radius, a hairline border and a flat fill.
- Section backgrounds alternate between white and a very pale blue-grey.

**Vector animation, as observed**

- Moving line art is the site's main imagery. Apart from photographs in the industry cards, there is
  nothing else.
- Each drawing is crisp vector work in two colours: fine blue lines and dots with one orange element.
- The hero has dotted discs drifting at different tilts. The product section has a wireframe sphere, and
  woven wave lines that converge into an orange stream.
- In the product section the drawing stays in view and changes with the active item.
- The motion is slow and continuous. Nothing flashes, bounces or waits to be scrolled into view.
- The vocabulary is organic: spheres, waves and discs.

**Components, as observed**

- Buttons are pills: solid orange with a dark label, or solid navy with a white label. Everything else is
  an orange text link with an arrow.
- Tags are small filled navy rectangles with white uppercase text.
- Section labels are plain uppercase text, sometimes set opposite the heading on the right.
- Small orange marks recur: a short dash in the corner of a card, thin corner brackets around a figure.
- The navbar is about 72 px tall, with centred links and one orange button on the right.

**Layout, as observed**

- Everything is left aligned on a wide container (about 1690 px of content at 1914 px).
- Section padding is generous: roughly 120 to 160 px.
- The capability section is two columns divided by a vertical rule: an illustration that stays in view on
  the left, and on the right a stack of items, each a short label, a large title, one line and a button.
  Progress segments along the bottom show which item is active.
- Proof is a bento of statistic cards with very large numerals, and a customer-story block with one large
  card beside a ruled list.

**Principles taken**

1. Type carries the page. Headings two to three times larger than ours today, body copy at 18 px or more.
2. Say less per section: one heading, one line, one action.
3. Flat surfaces. Structure from hairlines and whitespace, emphasis from one solid colour.
4. One label pattern, one heading pattern, one link pattern, repeated everywhere.
5. Left aligned on one wide container, with generous section padding.
6. Vector animation as the imagery: line art in two colours that moves slowly and explains something.

**What stays ours, so the result is not a copy**

| Reference | OAK |
|---|---|
| White page by default | Dark navy by default, light as an option |
| Pill buttons | Rectangular buttons with an 8 px radius |
| Filled navy tags | Outlined tags in the monospace face |
| Plain uppercase section labels | Numbered monospace labels ("01 / Build") |
| Orange dash and corner-bracket marks | No borrowed marks; the hero particles and the mark's own geometry are our motifs |
| Hero cells with an orange button block | Headline, lead and two buttons on open space, beside the particle mark |
| Sticky illustration beside a stack of capability titles | A capability rail with a live code panel (below) |
| Statistic bento with one navy card | No statistics until we have real figures; a quiet row of trust marks instead |
| Customer logo strip with a boxed label | A compatibility matrix of what OAK works with |
| Full-width solid orange closing band | A Prussian Blue panel with one orange button |
| Organic line art: spheres, woven waves, dotted discs | Our own vocabulary, particles on rails: straight and angled lines with dots that travel, queue, split and are filtered |
| Drawings that set a mood | Drawings that show what a stage of the runtime does, beside the code that enables it |

Nothing is taken from the reference's wording, section order or imagery.

## Proposed system

Starting values. They are tuned on the home page in iteration 10 before they spread.

**Type** (Archivo at weights 400 and 600; JetBrains Mono for labels, tags and code)

| Role | Desktop (1440 px and up) | Mobile | Line height | Tracking | Use |
|---|---|---|---|---|---|
| Display | 88 px | 44 px | 1.0 | -0.035em | Hero `h1` only |
| H1 | 64 px | 38 px | 1.05 | -0.03em | Page titles |
| H2 | 52 px | 32 px | 1.08 | -0.025em | Section headings |
| H3 | 30 px | 24 px | 1.2 | -0.015em | Row and card titles |
| H4 | 22 px | 20 px | 1.3 | 0 | Small card titles, list titles |
| Lead | 21 px | 18 px | 1.5 | 0 | One line under a heading |
| Body | 18 px | 17 px | 1.6 | 0 | Paragraphs and card copy |
| Small | 15 px | 15 px | 1.5 | 0 | Captions and metadata |
| Label | 13 px mono | 13 px mono | 1.4 | 0.08em, uppercase | Section labels and tags |

Sizes between mobile and desktop scale fluidly with the viewport. Nothing below 14 px except the monospace
label. Docs prose stays at 16 to 17 px. Sentence case everywhere. Headings are a solid colour.

**Space and grid**

- One container: 1280 px, with 24 px side padding on mobile. Prose is capped at 720 px.
- Spacing steps: 4, 8, 12, 16, 24, 32, 48, 64, 96, 128, 160 px.
- Section padding: 128 px desktop, 96 px tablet, 64 px mobile. No exceptions.
- Section content is left aligned. The closing section is the only centred one.

**Surfaces (flat)**

- Two surface levels: page and raised. Sections are separated by a hairline or by a change of level, not
  by a glow.
- Cards are a solid raised fill with a 1 px border, or no fill at all with hairline rules between rows.
- No gradient fills, glass blur or glows on cards and headings. In the light mode, cards use one soft
  shadow in place of the border.
- Corner radii: 8 px for buttons, controls and tags, 16 px for cards and panels.

**Components**

- **Buttons.** Primary: solid orange, navy label, 8 px radius, 52 px tall, 17 px text at weight 600.
  Secondary: 1 px outline, same size. Tertiary: a text link with an arrow. One primary button per view.
- **Section header.** Numbered monospace label, `h2`, lead; left aligned.
- **Tags.** Monospace, 13 px, outlined, 8 px radius. Not clickable, so they cannot be mistaken for buttons.
- **Icons.** One family at 20 and 24 px. Integration logos are SVG and single colour by default.
- **Labels for actions.** "Quick start" for the primary action, "Read the docs" and "View on GitHub" for
  the secondary ones, "Learn more" for card links.
- **Navbar.** 72 px tall, so the three-line lockup has room. Links at 16 px. "Quick start" as the one
  primary button. The version menu appears on docs pages only.

**Motion**

Two kinds of motion, with opposite rules.

- **Decorative motion goes.** No scroll-triggered reveals that hide content, no pulsing glows, no
  shimmering gradients. At most one 200 ms fade on entry.
- **Illustrative vector animation stays, and becomes the site's imagery.**

**Vector animation: particles on rails**

- One vocabulary for every drawing: fine straight and angled lines (rails), small dots (requests), and a
  few plain outlines. Dots travel, queue, split, settle and are filtered. It continues the hero, where
  particles form the mark, and it describes what a runtime does.
- Two colours from the theme tokens: the ambient blue for lines and dots, the accent for the one element
  that matters in each drawing. They follow the colour mode.
- Stroke weight 1.25 px, dot radius 2 to 3 px, corner joins rounded. Loops of 6 to 10 seconds with eased,
  constant-speed travel.
- Six stage drawings:
  - **Build**: differently shaped outlines slot into one common frame.
  - **Connect**: dots arrive from many entry points, pass through one node, and fan out.
  - **Remember**: dots settle into a ring and stay while new ones pass.
  - **Guard**: dots meet a boundary drawn from the mark's outline; some pass, some are turned back.
  - **Scale**: one lane becomes many, and a queue drains into them.
  - **Observe**: a trace draws across as a row of spans, with a marker scanning it.
- One architecture drawing: the existing diagram simplified, with requests flowing through it.
- Limits: one animation in view at a time; paused when off screen or when the tab is hidden; a static frame
  for reduced-motion users; SVG with CSS where possible and a single small canvas where not; no new
  dependency.
- Built from three shared primitives (rail, dot, pulse) so the set stays consistent and new drawings are
  cheap.

## Home page, restructured

Nine lighter sections in place of ten dense ones. Integrations and the full FAQ stay on the page, as the
maintainer asked; how integrations are shown changes.

1. **Hero.** A headline short enough to set at display size (about seven words), one lead line,
   "Quick start" and "View on GitHub", and the install command as one copyable line. The particle mark
   stays.
2. **Trust marks.** One quiet row: Apache 2.0, the two foundations, ISO 27001 and SOC 2. No figures until
   real ones exist; the row is built so they can be added. It replaces the separate trust section and the
   footer badges.
3. **What OAK does.** The feature section, shown differently (below).
4. **Architecture.** One diagram, larger, with fewer and bigger labels, animated as requests flow through it.
5. **Works with.** Integrations as a compatibility matrix (below), replacing the three marquee rows.
6. **Deploy anywhere.** Four flat cards.
7. **Choose your path.** The three path cards.
8. **Questions.** Every question kept, in two columns of flat rows.
9. **Closing section.** A Prussian Blue panel with one heading and one primary button.

**The feature section: a capability rail with code.** Today it is six tabs of up to nine small cards each.

- A rail of six numbered stages across the full width: **Build, Connect, Remember, Guard, Scale, Observe**.
  It reads as the path a request takes through the runtime.
- Selecting a stage shows one panel in three parts: the stage name at H3 size with one sentence and three
  short points; that stage's vector animation; and the few lines of Python or `config.yaml` that turn the
  capability on.
- The drawing shows what the stage does and the code shows how little it takes. The pairing is the
  product's central claim, that capabilities are configured and not built, and the reference does not do it.
- One "Learn more" link per stage leads to the docs page. The detail in today's cards moves there.
- On mobile the rail scrolls sideways, and the drawing and the code sit under the copy.

**Integrations: a compatibility matrix.** Today it is three rows of moving logo chips.

> Superseded during implementation: the four-column matrix below showed about 30 of the 76 integrations and dropped whole categories, such as identity and secrets. The home page now has a ledger, with one row per category and every integration listed by name. See iteration 13 in `plan.md`.

- Four columns under one heading: Frameworks, Clouds, Channels, Data and observability.
- Each column lists its most used entries by name with a small single-colour logo, then a count and a link
  to the full list.
- Static, scannable and text-first. If motion is wanted, a single slow row of logos can sit above it.
