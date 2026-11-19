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
