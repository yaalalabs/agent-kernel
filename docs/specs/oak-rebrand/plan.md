# Rebrand to Open Agent Kernel (OAK): implementation plan

Order of work for [spec.md](spec.md). Each iteration leaves the site building. Nothing is committed until
the maintainer asks.

## Iteration 1: Brand assets

- **Goal:** the new logo set is in the repository and the site serves it.
- **Files:** `branding/**`, `.gitignore`, `docs/static/img/branding/*`, `docs/static/img/{logo.svg,favicon.ico,favicon-16.png,favicon-32.png,apple-touch-icon.png,card.png}`
- **Steps:**
  1. Copy and rename the 22 SVGs into `branding/`; write `branding/README.md`; confirm `branding/source` is ignored (spec 1).
  2. Add the three site SVGs; render the favicon set, `logo.svg` and the social card (spec 1).
  3. Repoint the asset references and delete the nine old SVGs (spec, Consumer changes).
- **Verify:** Testing step 4 for the SVG names; the README lockup renders in a markdown preview.

## Iteration 2: Theme tokens and checkpoint

- **Goal:** the token layer carries the new palette, and the direction is confirmed before it spreads.
- **Files:** `docs/src/css/custom.css`, `docs/src/css/blog-medium.css`, `docs/src/theme/brand.ts`, `docs/src/pages/index.module.css`
- **Steps:**
  1. Rewrite the tokens and Infima variables (spec 2).
  2. Add `brand.ts` (spec 3, rule 5).
  3. Apply the colour replacement to the home page styles (spec 3).
  4. Screenshot the home page and one docs page; send them for review. Tune derived steps if asked.
- **Verify:** Testing step 6; the two screenshots.

## Iteration 3: Theme propagation

- **Goal:** no old-palette colour remains in the site source.
- **Files:** the remaining `docs/src/**/*.css` and `.tsx` files with colours, `docs/docusaurus.config.js` (Mermaid block), the 29 `docs/docs` pages with diagram fills
- **Steps:**
  1. First pass by property, then second pass by eye, page by page (spec 3, rules 1 to 4).
  2. Particle background palette and clear colour (spec 4).
  3. Mermaid theme variables and in-page diagram fills (spec 3, Diagram colours).
- **Verify:** Testing steps 3 and 6; screenshots of `/features`, `/use-cases`, `/docs/quick-start`.

## Iteration 4: Hero and call-to-action visuals

- **Goal:** the old mark is gone from every page.
- **Files:** `docs/src/components/OakMark/*`, `docs/src/components/CTASection/index.tsx`, the six page files, `docs/src/pages/index.module.css`, `docs/src/pages/features.module.css`
- **Steps:**
  1. Build `OakMark` with its three variants and the reduced-motion path (spec 4).
  2. Replace the 3 video and 7 image call sites; delete `hero.mp4` and `cta-bg.png` (spec, Consumer changes).
- **Verify:** Testing steps 4 and 6; a screenshot of the hero with reduced motion on and off.

## Iteration 5: Site copy

- **Goal:** the website reads "Open Agent Kernel" and "OAK" throughout.
- **Files:** `docs/docusaurus.config.js`, 24 `.tsx` files under `docs/src`, `docs/src/pages/*.md`, `docs/blog/authors.json`, `docs/static/robots.txt`, `docs/README.md`, `docs/SETUP.md`
- **Steps:**
  1. Apply the config table (spec, Config changes).
  2. Edit the `.tsx` copy by hand, page by page (spec 5, site source).
  3. Run the script on the markdown files in this set (spec 5).
- **Verify:** Testing step 2 for these files; Testing step 6.

## Iteration 6: Docs

- **Goal:** current docs and the `0.10.1` snapshot carry the new name.
- **Files:** `docs/docs/**`, `docs/versioned_docs/version-0.10.1/**`
- **Steps:**
  1. Check the snapshot precondition (spec 5, Snapshot mirror).
  2. Run the script on `docs/docs`; review the replacement list and the flagged lines.
  3. Mirror to the snapshot.
- **Verify:** Testing steps 2, 5 and 6.

## Iteration 7: READMEs and skills

- **Goal:** every other in-scope markdown file carries the new name.
- **Files:** root markdown files, `ak-py/README.md`, markdown under `examples/`, `use-cases/`, `ak-deployment/`, `e2e/`, `agent/`, `scripts/`, `.github/`, `.agents/skills/`, `ak-py/src/agentkernel/skills/`
- **Steps:**
  1. Run the script per area; review each area's replacement list (spec 5).
  2. Hand-check the README header, the skill `description` lines and the flagged lines.
- **Verify:** Testing step 2 for these areas.

## Iteration 7b: Home page review, hero scene and light mode

- **Goal:** the home page has no off-palette artwork, the hero is the 3D scene, and the site has a light mode.
- **Files:** `docs/src/components/OakMark/*`, `docs/src/components/BrandArt/*`, `docs/src/lib/brand.ts`, `docs/src/css/custom.css`, the site stylesheets, `docs/src/pages/index.tsx`, `docs/src/theme/Footer/Layout/index.tsx`, `docs/docusaurus.config.js`
- **Steps:**
  1. Replace the path-card images and the compliance badges with `BrandArt`; restyle the footer brand column and the chat launcher.
  2. Rebuild the hero as the 3D scene (spec 4).
  3. Add the light token set, convert white, grey and shadow literals to tokens, enable the switch, pin the footer, launcher and persona pages (spec 2, rules for the two modes).
- **Verify:** Testing steps 3, 6 and 7 in both modes.

## Iteration 8: Tests

- **Goal:** the whole change passes the spec's checks.
- **Steps:** run Testing steps 1 to 8 in order on the full working tree; fix and re-run until all pass.
- **Verify:** all eight steps pass; the screenshot set is attached for review.

## Iteration 9: Sync docs and skills

- **Goal:** contributors and the docs-sync automation keep using the new name.
- **Files:** `AGENTS.md`, `.agents/skills/ak-dev-sync-docs-from-branch/SKILL.md`, `.agents/skills/ak-dev-sync-skills-from-branch/SKILL.md`, `.agents/skills/ak-dev-sync-skills-and-docs-from-commit/SKILL.md`
- **Steps:**
  1. Add the naming section to `AGENTS.md` (design, Contributor guidance) and link `branding/README.md`.
  2. Point the three sync skills at that section.
  3. No other dev skill describes behaviour that this change alters; the prose rename in iteration 7 is their only edit. Confirm by re-reading the diff of `.agents/skills/`.
- **Verify:** Testing step 2 still passes; the `ak-dev-sync-docs-from-branch` checklist finds nothing left to sync.

# Phase 2: design system

Not started. It implements the Design system section of [design.md](design.md). Finding numbers (F1 to F23)
refer to [research/design-audit.md](research/design-audit.md). The detailed spec for this phase is written
after the design is approved.

## Iteration 10: Foundations

- **Status:** done on 2026-11-19. Tokens and utility classes are in `docs/src/css/custom.css`; the navbar and the home hero use them. The maintainer reviewed the checkpoint and asked for the remaining iterations.
- **Goal:** the type scale, spacing scale, container, radii and flat surface rules exist as tokens, proven on the home hero and navbar.
- **Findings:** F1, F17, F18, F3, F9, F19.
- **Files:** `docs/src/css/custom.css`, `docs/src/pages/index.module.css`
- **Steps:**
  1. Add type, space, radius and container tokens; add heading and text utility classes.
  2. Apply them to the hero and one more section; tune the scale against screenshots.
  3. Checkpoint with the maintainer before the scale spreads.
- **Verify:** the measurement script reports no text below 13 px in those sections; screenshots in both modes.

## Iteration 11: Components

- **Status:** done for buttons, section headers, cards, tags and text links (`docs/src/css/custom.css`, `docs/src/components/ui/SectionHeader.tsx`). Legacy stylesheets were brought onto the two radii and the flat-surface rules by a one-off normalisation script. Not done: one icon family, and SVG versions of the PNG integration logos.
- **Goal:** one implementation each of button, section header, card, tag and text link.
- **Findings:** F2, F4, F9, F8, F22.
- **Files:** `docs/src/css/custom.css`, a new `docs/src/components/ui/` folder, the stylesheets that define today's variants
- **Steps:**
  1. Build the five components from the tokens.
  2. Replace the existing button, pill and eyebrow variants across pages; unify action labels.
  3. Move icons to one family; convert the remaining PNG integration logos to SVG where a vector exists.
- **Verify:** the measurement script reports two card radii and three button styles site-wide.

## Iteration 12: Vector animation set

- **Status:** done for the six stage drawings (`StageMotion` in `docs/src/components/VectorMotion/`), which sit in the capability rail beside the configuration that switches each stage on. They are SMIL only, use two theme tokens, pause off screen and render a static frame on the server and for reduced motion. Not done: the architecture flow drawing, the in-browser review of the motion language with the maintainer (step 2 was skipped, so all six were drawn before review), and a check in Safari and Firefox.
- **Goal:** the site has its own moving line art, in one vocabulary.
- **Findings:** F23, F14.
- **Files:** a new `docs/src/components/VectorMotion/` folder
- **Steps:**
  1. Build the three primitives (rail, dot, pulse) with the limits from the audit: tokens for colour, pause off screen, static frame for reduced motion.
  2. Prototype one stage drawing (Guard) and checkpoint with the maintainer on the motion language before drawing the rest. Stills cannot show motion, so this review happens in the browser.
  3. Draw the other five stages and the architecture flow.
- **Verify:** each drawing in both colour modes and with reduced motion on; the measurement script reports one running illustration per view.

## Iteration 13: Home page

- **Status:** done. Nine sections: hero, trust marks, capability rail, architecture, integration ledger, deploy, paths, questions, closing panel. The four-column compatibility matrix was replaced by a ledger after review, because the matrix showed about 30 of the 76 integrations and dropped whole categories (identity, secrets, queues, sandboxes). The ledger has one hairline row per category and lists every integration by name; it reads the same data file as the marquee, and an integration whose role is not mapped to a category still appears, under "More". The footer membership badges were kept, because they are the foundations' own artwork and their display terms were not checked. The architecture diagram keeps its old internals; only its header and spacing changed.
- **Goal:** the home page has the nine lighter sections, the capability rail and the compatibility matrix.
- **Findings:** F5, F20, F11, F21, F7.
- **Files:** `docs/src/pages/index.tsx`, `docs/src/pages/index.module.css`, `docs/src/components/FeatureExplorer/*`, `docs/src/components/IntegrationsMarquee/*`, `docs/src/components/FAQ/*`
- **Steps:**
  1. Hero: short headline at display size, lead, two actions, one-line install command.
  2. Trust marks row; remove the trust section and the footer badges.
  3. Rebuild the feature section as the six-stage rail, each stage with its drawing and a code panel.
  4. Rebuild integrations as the four-column compatibility matrix.
  5. Enlarge and simplify the architecture diagram and give it the flow animation; set the FAQ in two columns with every question kept; flat closing panel.
- **Verify:** section count; the measurement script on the page; screenshots at 1440 and 390 px in both modes.

## Iteration 14: Features, use-cases and persona pages

- **Status:** partly done. Type floor, radii, flat surfaces, sentence-case headings, left-aligned section headers and the shared closing panel are applied; the features page has an `h1`. Not done: shortening the persona journeys, the neutral colour for "before" comparisons, and one container width on the features page.
- **Goal:** the other marketing pages use the system.
- **Findings:** F18, F15, F7, F1.
- **Files:** `docs/src/pages/features.tsx`, `use-cases.tsx`, `developer.tsx`, `ai-engineer.tsx`, `business-leader.tsx` and their stylesheets
- **Steps:**
  1. Give every page one `h1` and the shared heading sizes.
  2. Apply the container, spacing and components; replace red with neutral on "before" comparisons.
  3. Shorten the persona journeys and enlarge the step timeline.
- **Verify:** the measurement script per page; screenshots in both modes.

## Iteration 15: Docs, blog and site chrome

- **Status:** partly done. The docs sidebar and table of contents are unboxed, the navbar is 72 px with its primary action, and the scroll-to-top button is hidden on small screens. Not done: moving the "What's New" list to a changelog, and the blog banners (the posts still carry the old name, which is the maintainer's call).
- **Goal:** the docs, blog, navbar and footer match.
- **Findings:** F10, F6, F12, F13.
- **Files:** `docs/src/css/custom.css`, `docs/src/css/blog-medium.css`, `docs/src/theme/*`, `docs/docusaurus.config.js`, `docs/static/img/blog/*`, `docs/docs/intro.md`
- **Steps:**
  1. Remove the boxed panels around the docs sidebar and table of contents; widen the content column.
  2. Move the "What's New" list out of the introduction to a changelog page.
  3. Raise the navbar to 72 px, add the primary action, show the version menu on docs pages only; keep one floating button.
  4. Regenerate the blog banners from one template in the brand palette.
- **Verify:** screenshots of a docs page, the blog list and a post in both modes.

## Iteration 16: Motion, accessibility and light mode

- **Status:** partly done. Glows, blur and gradient fills are removed, and light-mode cards lift with a shadow. Not done: replacing the scroll-triggered reveals on the features and persona pages, and a keyboard pass.
- **Goal:** content never waits on an animation, and the light mode is designed, not inverted.
- **Findings:** F14, F16.
- **Steps:**
  1. Replace scroll-triggered reveals with one short fade that never hides content; remove decorative loops, keeping only the vector drawings.
  2. Check contrast and focus states for every component in both modes.
  3. In the light mode, replace card borders with one soft shadow.
- **Verify:** the measurement script reports at most a handful of running animations per page; a keyboard pass.

## Iteration 17: Tests, then docs and skills

- **Status:** partly done. The production build passes on an isolated copy with the current docs and version 0.10.1 (the full build with every frozen version was not re-run). `AGENTS.md` and `branding/README.md` carry the design-system rules. Not done: the screenshot set for review.
- **Goal:** the whole phase passes the checks, and the guidance matches.
- **Steps:**
  1. Run the Testing steps of the spec on the full tree, and the production build.
  2. Update the *Naming and brand* section of `AGENTS.md` and `branding/README.md` with the type scale, spacing and component rules.
- **Verify:** the build passes; the screenshot set is attached for review.


# Phase 3: review round of 2026-11-19

The maintainer reviewed the phase 2 site. The stage drawings are accepted as the motion language. The
particle hero and the integration ledger are not, the level tiles are to be redone, and the items left
"not done" in phase 2 are to be finished. Shared pieces for this phase: `PageHero` and `Reveal` in
`docs/src/components/ui/`.

## Iteration 18: Home hero as a system drawing

- **Status:** rejected. The system drawing (channels, the mark, frameworks, with simulated traffic under a full-width headline) was built and the maintainer found it worse than the particle mark. It was removed, and the particle hero is back as a placeholder. Four hero directions have now been turned down (a fade-in mark, an extruded mark, the particle mark, the system drawing), so the next one is chosen by the maintainer from options before anything is built: a cinematic mark in WebGL like the original video, ambient line art, a product-in-action terminal, or type only.
- **Goal:** the hero shows the runtime at work, in the accepted motion language, and reads as alive.
- **Files:** `docs/src/components/VectorMotion/`, `docs/src/pages/index.tsx`, `docs/src/components/OakMark/`
- **Steps:**
  1. Draw one scene: channels on the left, the mark as the kernel, agent frameworks on the right, with requests and replies travelling the rails without a fixed loop.
  2. Replace the particle mark; remove its code.
- **Verify:** frame sequences in both colour modes, at desktop and phone width, and with reduced motion.

## Iteration 19: Integrations as a scroll-stepped section

- **Status:** done (`docs/src/components/HomeSections/Integrations.tsx`). Six groups named after the stages, 76 integrations, all in the server-rendered page. The section pins at 997 px and wider when the window is at least 700 px tall and motion is allowed; otherwise the groups are stacked. The data file moved to `HomeSections/integrations.data.tsx`, and the marquee component was removed.
- **Goal:** every integration is still shown, one group at a time, as the visitor scrolls.
- **Files:** `docs/src/components/HomeSections/`
- **Steps:**
  1. Group the integrations by the six stages, so the section continues the story of section 01.
  2. Pin the section while the scroll steps through the groups; the group list on the left is also a control.
  3. Fall back to a plain stacked list on small screens, short viewports, reduced motion and without script.
- **Verify:** captures at each step in both modes; the fallback at phone width; all 76 integrations present in the server-rendered page.

## Iteration 20: Level section

- **Status:** done. The levels are three layers of one isometric stack (`docs/src/components/LevelStack/`): the outcome, the code, the runtime. On the home page the stack sits beside three rows, a row lights its layer and a layer lights its row, and the light walks down the stack until the visitor points at something. Each persona page header shows the stack with its own layer lit.
- **Goal:** the three reading levels are presented as one idea, with drawings in the motion language.
- **Files:** `docs/src/components/HomeSections/`, `docs/src/components/VectorMotion/`, `docs/src/pages/index.tsx`
- **Steps:**
  1. Draw the same request path at three depths: the overview, the build view, the internals.
  2. Present the levels as depth rows that link to the persona pages; reuse each drawing in its persona page header.
- **Verify:** both modes, phone width, keyboard focus on each row.

## Iteration 21: Architecture flow drawing

- **Status:** done in place. The existing diagram keeps its layout; its glow and gradients are gone, its connectors are solid rails, and a dot travels each one (paused off screen, absent for reduced motion). Its links now show a focus ring.
- **Goal:** the architecture section moves in the same language as the rest of the page.
- **Files:** `docs/src/components/ArchitectureOverview/`, `docs/src/components/VectorMotion/`
- **Verify:** both modes; one running illustration per view.

## Iteration 22: Features and use-cases pages

- **Status:** done. Features is a reference with a sticky index of the six stages and 35 capabilities, each linked to its guide (2,142 lines of page code to about 550). Use cases has three real projects, ten scenarios with a guide and an example each, four kinds of team, and a neutral before and after list. The review is in `research/features-use-cases-review.md`. Unsourced figures and two cards that linked nowhere were removed.
- **Goal:** each page says each thing once, in the shared layout, and helps a reader decide.
- **Files:** `docs/src/pages/features.tsx`, `docs/src/pages/use-cases.tsx`, their stylesheets, and the components only they use
- **Steps:**
  1. Review both pages and record the findings in `research/features-use-cases-review.md`: what each section says, what repeats the home page or the other page, what is kept.
  2. Restructure on `PageHero`, `SectionHeader`, `ak-container` and the component classes; remove the duplicates and the dead code.
  3. Replace scroll-triggered reveals with `Reveal`; use the neutral colour for "before" comparisons.
- **Verify:** both modes at desktop and phone width; the measurement script.

## Iteration 23: Persona pages

- **Status:** done. One skeleton for the three pages: `PageHero`, a sticky step rail, five sections, links to the other levels, the closing panel (`docs/src/components/PersonaKit/`, `docs/src/pages/persona.module.css`). 2,471 lines of page code to about 1,000. The titles, leads and the business page's commitment answers are new copy and need the maintainer's read.
- **Goal:** the three persona pages are shorter and share the page header and the step pattern.
- **Files:** `docs/src/pages/developer.tsx`, `ai-engineer.tsx`, `business-leader.tsx`, and the components only they use
- **Steps:**
  1. Shorten each journey to the steps a reader needs; enlarge the step timeline.
  2. Replace scroll-triggered reveals with `Reveal`; use the neutral colour for "before" comparisons.
- **Verify:** both modes at desktop and phone width; a keyboard pass.

## Iteration 24: One icon family and vector logos

- **Status:** done for icons: only the three brand exceptions (AWS, Microsoft, Azure) come from outside Tabler and Simple Icons. Seven channel logos moved from PNG to vector marks. Eight integration logos stay as PNG because neither set has a mark for them (Google ADK, Bedrock, Daytona, E2B, Langfuse, LiteLLM, OpenLLMetry, TypeSafe).
- **Goal:** interface icons come from one family, and integration logos are vectors where one exists.
- **Rule:** interface icons are Tabler outline icons (`react-icons/tb`). Brand marks come from Simple Icons (`react-icons/si`), and from another set only where Simple Icons has no mark (AWS, Microsoft, Azure).
- **Verify:** no `react-icons/md` or interface icon from `react-icons/fa` is left under `docs/src`.

## Iteration 25: Changelog and blog banners

- **Status:** partly done. The "What's new" list is its own page (`docs/docs/whats-new.md`, mirrored to 0.10.1) and the introduction links to it. The blog banners are not started: seven are bespoke illustrations that carry each post's diagram, so replacing them from one template would lose content, and redrawing them is a design decision for the maintainer.
- **Steps:**
  1. Move the "What's New" list from the docs introduction to a changelog page, in the current docs and in `0.10.1`.
  2. Regenerate the blog banners from one template in the brand palette, and keep the template in the repository.
- **Verify:** the docs build; the blog index in both modes.

## Iteration 26: Dead code, keyboard pass and checks

- **Status:** done except the browser check. Removed: ten unused components, the 6,100-line `index.module.css`, unused images and the three.js models, and gsap from the last component that used it. A keyboard pass on the home, features, use-cases and developer pages found every control reachable with a visible focus ring. The production build passes on an isolated copy with no broken links or anchors. Not done: Safari and Firefox, the full build with every frozen version, and removing `gsap` and `three` from `package.json` (left until the hero direction is chosen, since a WebGL hero would need `three`).
- **Steps:**
  1. Remove unused components, unused local functions and stylesheet rules that no page refers to.
  2. Keyboard pass on every marketing page.
  3. Production build; the screenshot set; a check of the drawings in Safari and Firefox.
- **Verify:** the build passes; a scan reports no unused class in the page stylesheets.

## Iteration 27: second review round of 2026-11-19

- **Status:** done.
- **Goal:** the seven points from the maintainer's second review.
- **Steps:**
  1. Light is the default colour mode (`docs/docusaurus.config.js`); the dark mode stays on the navbar switch.
  2. The hero install line switches between `pip install agentkernel` and `uv add agentkernel`.
  3. The persona pages have a "Back to path selection" link at the top of the page header (`PageHero` takes a `back` prop) and a button at the foot.
  4. The architecture diagram is rebuilt: the runtime is one panel as tall as the columns beside it, so each card joins it with one straight rail. No connector bends, crosses a box or stops short, and the diagram needs no script.
  5. The chat launcher is a flat labelled button ("Ask OAK"), and the panel is rebuilt on solid surfaces: in the light mode it had been translucent, with a white heading on white.
  6. The hero is a particle mark on the GPU (`docs/src/components/ParticleLogo/`), following the maintainer's brief and the reference they named: it builds from particles on load, ripples, swirls and leans under the pointer, and scatters as the page scrolls. This supersedes iteration 18. `gsap` and `three` are removed from `package.json`.
  7. Blog banners: the eight existing ones are recoloured and carry the new mark (text baked into them keeps the old name), and the ten posts without one have a banner from a template kept in `branding/blog-banner/`. The blog index thumbnail takes the banners' shape.
- **Verify:** the production build passes on an isolated copy; captures of each change in both colour modes. Not checked: Safari and Firefox, and the particle hero on a low-power device.
- **Open:** resolved in iteration 28: the maintainer chose the closing panel and the integrations section.

## Iteration 28: particle fields and light diagrams

- **Status:** done.
- **Steps:**
  1. Closing panel: a slow sheet of dots behind the copy, with the accent on its crests (`docs/src/components/DotField/Wave.tsx`). It appears wherever the closing panel does.
  2. Integrations section: a dot cloud behind the stage list was built and then removed. The maintainer found it oddly placed: a shape floating under the list, cut by the bottom of the window. Its replacement, chosen by the maintainer from three options, is a floor of dots along the bottom edge of the pinned section (`DotField/Floor.tsx`). It differs from the closing panel's wave on purpose: centred and calm, one colour at rest, with the accent only as a ripple that crosses it when the stage changes, in the direction of travel.
  3. The wave uses a small WebGL runner (`DotField/engine.ts`), which starts a scene when it first nears the screen, pauses it off screen, and draws a single still frame for reduced motion.
  4. Docs diagrams follow the colour mode. The maintainer asked for a real light version, not a dark plate: on the light page each Mermaid diagram is sent a light palette as an init directive (`docs/src/theme/Mermaid/index.tsx`), and the plate is white. Nodes a diagram colours itself set both fill and text colour in all 1,866 cases across every doc version, so they read on either background.
  5. A sequence diagram in `docs/docs/advanced/threads.md` had a semicolon in a message, which ends a statement and broke the diagram. Fixed in the current docs and the 0.10.1 copy.
  6. The home page announcement now leads with identity provider support.
- **Verify:** the production build passes on an isolated copy; flowcharts, a front-matter diagram and sequence diagrams captured in both modes; Not checked: Safari and Firefox, and class or state diagrams in the light palette.
- **Hero entrance, revised:** the maintainer found the spiral fly-in too intense and chose a calmer one from four options. The mark now comes into focus over two seconds: the dots start as a haze close to their places and tighten. Hover and scroll behaviour are unchanged.
