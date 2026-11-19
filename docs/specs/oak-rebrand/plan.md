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

