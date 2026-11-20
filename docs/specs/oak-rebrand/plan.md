# Rebrand to Open Agent Kernel (OAK): implementation plan

Order of work for [spec.md](spec.md). Each iteration leaves the site building.

- The iterations are the ones that shipped, in the order the work was done. All are done on
  `feat/rebranding_oak`. What was not checked is listed under Known gaps.
- A direction that was tried and replaced is not an iteration. Where one explains a decision it is named
  in a **Decided** line. The review rounds behind those decisions are in
  [research/review-log.md](research/review-log.md).
- "spec N" is a numbered section of `spec.md`. "Testing step N" is a step of its Testing section. The
  design system's rules are in `branding/README.md` (*Website design system*), which is the spec for
  iterations 7 to 12 wherever it covers them.

## Iteration 1: Brand assets

- **Goal:** the new logo set is in the repository and the site serves it.
- **Files:** `branding/**`, `.gitignore`, `docs/static/img/branding/*`, `docs/static/img/{logo.svg,favicon.ico,favicon-16.png,favicon-32.png,apple-touch-icon.png,card.png}`
- **Steps:**
  1. Copy and rename the 22 SVGs into `branding/`; write `branding/README.md`; confirm `branding/source` is ignored (spec 1).
  2. Add the site SVGs; render the favicon set, `logo.svg` and the social card (spec 1).
  3. Repoint the asset references and delete the nine old SVGs (spec, Consumer changes).
- **Verify:** Testing step 4; the README lockup renders in a markdown preview.

## Iteration 2: Theme tokens and checkpoint

- **Goal:** the token layer carries the new palette, and the direction is confirmed before it spreads.
- **Files:** `docs/src/css/custom.css`, `docs/src/lib/brand.ts`
- **Steps:**
  1. Rewrite the tokens and Infima variables (spec 2).
  2. Add `brand.ts` for canvas and WebGL code (spec 3, rule 5).
  3. Apply the colour replacement to the home page styles (spec 3).
  4. Capture the home page and one docs page for review; tune the derived steps if asked.
- **Verify:** Testing step 6; the two captures.

## Iteration 3: Theme propagation and the two colour modes

- **Goal:** no old-palette colour remains in the site source, and one set of token names serves a light and a dark mode.
- **Files:** the `docs/src/**/*.css` and `.tsx` files with colours, `docs/docusaurus.config.js` (colour mode, Mermaid block), the 29 pages with diagram fills in `docs/docs` and in `docs/versioned_docs/version-0.10.1`
- **Steps:**
  1. Replace colours by rule block, then by eye, page by page (spec 3, rules 1 to 4).
  2. Add the light token set; convert white, grey and shadow literals to tokens; pin the footer and the dark panels (spec 2, rules for the two modes).
  3. Enable the navbar switch with light as the default (spec, Config changes).
  4. Set the dark Mermaid variables and recolour the in-page diagram fills (spec 3, Diagram colours).
- **Verify:** Testing steps 3 and 6; captures of `/`, `/features`, `/use-cases` and `/docs/quick-start` in both modes.

## Iteration 4: Site copy

- **Goal:** the website reads "Open Agent Kernel" and "OAK" throughout.
- **Files:** `docs/docusaurus.config.js`, the `.tsx` files under `docs/src`, `docs/src/pages/*.md`, `docs/blog/authors.json`, `docs/static/robots.txt`, `docs/README.md`, `docs/SETUP.md`
- **Steps:**
  1. Apply the config table (spec, Config changes).
  2. Edit the `.tsx` copy by hand, page by page (spec 5, site source).
  3. Run the rename script on the markdown files in this set (spec 5).
- **Verify:** Testing step 2 for these files; Testing step 6.

## Iteration 5: Docs

- **Goal:** the current docs and the `0.10.1` snapshot carry the new name.
- **Files:** `docs/docs/**`, `docs/versioned_docs/version-0.10.1/**`
- **Steps:**
  1. Run the script on `docs/docs`; review the replacement list and the flagged lines.
  2. Run the script on the snapshot as its own area, and port the hand edits one by one (spec 5, The `0.10.1` snapshot).
- **Decided:** the snapshot is not mirrored from `docs/docs`. Ten of its pages already differ from `docs/docs` at the merge base, so a mirror would publish unreleased behaviour under `0.10.1`.
- **Verify:** Testing steps 2, 5 and 6.

## Iteration 6: READMEs and skills

- **Goal:** every other in-scope markdown file carries the new name.
- **Files:** root markdown files, `ak-py/README.md`, markdown under `examples/`, `use-cases/`, `ak-deployment/`, `e2e/`, `agent/`, `scripts/`, `.github/`, `.agents/skills/`, `ak-py/src/agentkernel/skills/`
- **Steps:**
  1. Run the script per area; review each area's replacement list (spec 5).
  2. Hand-check the README header, the skill `description` lines and the flagged lines.
  3. Fix the hyphenated prose compounds the script skips, such as "AK-internal" (spec 5, rule 6).
- **Verify:** Testing step 2 for these areas.

## Iteration 7: Design system foundations and components

- **Goal:** one type scale, one spacing scale, one container, two radii, and one implementation each of the button, section header, page header, card, tag, text link and entrance effect.
- **Files:** `docs/src/css/custom.css`, `docs/src/components/ui/` (`SectionHeader`, `PageHero`, `Reveal`), `docs/docusaurus.config.js` (navbar items, client modules), the stylesheets that held page-local variants
- **Steps:**
  1. Add the type, space, radius and container tokens and the `ak-*` classes (`branding/README.md`, *Website design system*).
  2. Build the shared components; replace the page-local buttons, pills and eyebrows; use one label per kind of action.
  3. Raise the navbar to 72 px, keep the three-line lockup, add one primary action, and show the version menu on docs pages only.
  4. Move interface icons to Tabler outline and brand marks to Simple Icons, with AWS, Microsoft and Azure from another set; replace PNG integration logos with a vector mark where one exists.
  5. Make `Reveal` the only entrance effect, and remove the scroll-reveal client module (design, Motion).
- **Verify:** Testing steps 7 to 9; no `react-icons/md` import is left under `docs/src`, and `react-icons/fa` and `react-icons/vsc` supply only the three brand exceptions.

## Iteration 8: Stage drawings

- **Goal:** the site has its own moving line art, in one vocabulary.
- **Files:** `docs/src/components/VectorMotion/`
- **Steps:**
  1. Build the primitives (rail, port, dot, pulse) on theme tokens, with a static frame that is a real moment of the loop.
  2. Draw the six stages: Build, Connect, Remember, Guard, Scale, Observe.
- **Verify:** each drawing in both colour modes; with reduced motion each shows its static frame (Testing step 8).

## Iteration 9: Home page

- **Goal:** the home page is an announcement strip and nine sections built from the design system.
- **Files:** `docs/src/pages/index.tsx`, `docs/src/components/HomeSections/*`, `docs/src/components/ArchitectureOverview/*`, `docs/src/components/LevelStack/*`, `docs/src/components/BrandArt/*`, `docs/src/components/FAQ/*`
- **Steps:**
  1. Hero copy: a headline short enough for display size, a lead, two actions, and an install line (`uv add agentkernel`; it first switched between pip and uv, see iteration 21).
  2. Trust marks row with the drawn seals; the separate trust section goes, and the footer keeps its two membership badges.
  3. Capability rail: six stages, each with its drawing and the code or config that switches it on (spec 6).
  4. Architecture as three columns joined by straight rails (spec 6).
  5. Integrations as the pinned, scroll-stepped section over one data file, with the stacked fallback (spec 6).
  6. Deployment targets; the three reading levels as the level stack (spec 6); every FAQ question in two columns of flat rows; the closing panel; the announcement strip.
- **Decided:** integrations were first a four-column matrix and then a ledger. The matrix showed about 30 of the 76 integrations and dropped whole categories, which is why the requirement is that every integration is listed by name.
- **Verify:** Testing steps 7 to 9; all 76 integration names are in the server-rendered page.

## Iteration 10: Hero mark and dot fields

- **Goal:** the hero shows the mark built from particles, and the closing panel and integrations section carry their dot fields.
- **Files:** `docs/src/components/ParticleLogo/*`, `docs/src/components/DotField/*`, `docs/src/components/HomeSections/{Hero,Integrations}.tsx`, `docs/src/components/HomeSections/index.tsx`
- **Steps:**
  1. Build `ParticleLogo` with its plain-mark fallback (spec 4).
  2. Build the dot runner and the `Wave` behind the closing panel (spec 4).
  3. Build the `Floor` along the bottom edge of the integrations section (spec 4).
- **Decided:** four earlier hero directions were turned down (a fade-in mark, an extruded mark, a particle mark on a 2D canvas, and a system drawing of channels and frameworks). The maintainer then set the brief: the mark builds from particles on load, moves under the pointer and scatters on scroll.
- **Decided:** a dot cloud behind the integrations list was removed as oddly placed, cut by the bottom of the window. The floor replaced it.
- **Verify:** Testing step 8; captures of the hero, the closing panel and the integrations section in both modes.

## Iteration 11: Features, use-cases and persona pages

- **Goal:** each page says each thing once, in the shared layout, and helps a reader decide.
- **Files:** `docs/src/pages/{features,use-cases,developer,ai-engineer,business-leader}.tsx`, `docs/src/pages/{features,use-cases,persona}.module.css`, `docs/src/components/PersonaKit/*`, `docs/src/components/StepTimeline/*`
- **Steps:**
  1. Review features and use cases, and record what repeats and what is kept in `research/features-use-cases-review.md`.
  2. Rebuild features as a reference of capabilities under the six stages, each linked to its guide (spec 7).
  3. Rebuild use cases on the shared layout; remove unsourced figures and cards that link nowhere; use a neutral colour for "before" comparisons.
  4. Rebuild the three persona pages on one skeleton from `PersonaKit`, with the way back to the path selection and the level stack in the header (spec 7).
- **Verify:** Testing steps 7 and 9 for these pages.

## Iteration 12: Docs pages and site chrome

- **Goal:** the docs pages, the footer and the chat assistant match the design system in both colour modes.
- **Files:** `docs/src/css/custom.css`, `docs/src/theme/Mermaid/*`, `docs/src/theme/DocSidebar/Desktop/*`, `docs/src/theme/Footer/Layout/index.tsx`, `docs/src/components/FloatingChatbot/*`, `docs/src/components/ScrollToTopButton/*`, `advanced/threads.md` in `docs/docs` and in the `0.10.1` snapshot
- **Steps:**
  1. Remove the boxed panels around the docs sidebar and table of contents; give the sidebar its own lockup.
  2. Send the light Mermaid palette with each diagram on the light page (spec 3, Diagram colours).
  3. Repair the sequence diagram in `advanced/threads.md`: a semicolon in a message ended the statement.
  4. Rebuild the chat launcher as a flat labelled button and its panel on solid surfaces; these two floating layers keep a shadow.
  5. Make the previous and next links flat cards; hide the scroll-to-top button on small screens. The footer copyright is unchanged: Yaala Labs is the holder, as in `NOTICE`.
- **Verify:** Testing step 7; flowcharts, sequence diagrams and a diagram with front matter in both modes.

## Iteration 13: What's new page

- **Goal:** the "What's new" list is its own page, and the introduction is short again.
- **Files:** `docs/docs/whats-new.md`, `docs/docs/intro.md`, `docs/sidebars.js`, the same three in the `0.10.1` snapshot (`whats-new.md`, `intro.md`, `docs/versioned_sidebars/version-0.10.1-sidebars.json`), `docs/src/components/HomeSections/Announcement.tsx`
- **Steps:**
  1. Move the list to `whats-new.md`, newest first; leave a two-line tip in the introduction (spec 8).
  2. Do the same in the snapshot, without entries for capabilities that are not in that release.
  3. Point the home page announcement at the newest headline capability.
- **Verify:** Testing steps 5 and 6.

## Iteration 14: Blog

- **Goal:** the blog uses the design system, posts name their writers, and every post has a banner.
- **Files:** `docs/src/css/blog.css`, `docs/src/theme/{BlogListPage,BlogTagsPostsPage,BlogPostPage}/*`, `docs/src/components/Blog/*`, `docs/blog/authors.json`, front matter in `docs/blog/*.md`, `docs/static/img/blog/*`, `docs/static/img/branding/oak-avatar.svg`, `branding/blog-banner/*`
- **Steps:**
  1. Audit the blog and record the findings and proposals in `research/blog-audit.md`.
  2. Rebuild the index, the tag page and the post page (spec 8, Blog pages).
  3. Rename the shared author to "OAK" with the disc avatar; credit the 14 posts that used it to their writers (spec 8, Authors).
  4. Recolour the eight existing images in place; render a banner from the template for the ten posts without one (spec 8, Banners).
- **Decided:** the existing banners are recoloured, not regenerated from the template, because seven of them carry their post's own diagram.
- **Verify:** Testing step 1 (the blog guard), steps 6 and 7.

## Iteration 15: Root README

- **Goal:** the root README follows the site.
- **Files:** `README.md`
- **Steps:**
  1. Use the site's headline and lead; group the capabilities by the six stages; show `pip` beside `uv`; link the three guided tours.
  2. Carry no note about the former name (design, Open questions).
- **Verify:** the README renders in a markdown preview in a light and a dark scheme; Testing step 2.

## Iteration 16: Dead code and dependencies

- **Goal:** nothing unused is left in the site source.
- **Files:** the deleted components, stylesheets and static files listed in spec, Consumer changes; `docs/package.json`
- **Steps:**
  1. Remove the components, stylesheets, images and 3D models that no page refers to.
  2. Remove `gsap`, `three` and `@types/three`.
- **Verify:** Testing steps 4 and 6; no import of `gsap` or `three` is left under `docs/src`.

## Iteration 17: Merge develop

- **Goal:** the branch carries what develop gained while it was open: the agent registry (#983) and the first part of the Azure Functions retirement (#984).
- **Steps:**
  1. Text conflicts in skills and docs pages: take develop's content, in the new name.
  2. `docs/src/pages/features.tsx`: keep this branch's structure and carry develop's edits into it (the "Agent registry and catalog" capability under Connect, and the MCP and A2A summaries).
  3. `docs/docs/intro.md` keeps the short tip and names the registry; the registry entry heads `docs/docs/whats-new.md`. The `0.10.1` copy is not changed, since the registry is not in that release.
  4. Azure Functions: the home page, the features page, the FAQ and the root README no longer offer it. The pages under `docs/docs` are left to `docs/specs/957-retire-azure-functions/`.
- **Verify:** the rename script reports nothing left to change in the files develop touched; Testing step 6.

## Iteration 18: Tests

- **Goal:** the whole change passes the spec's checks.
- **Steps:** run Testing steps 1 to 10 in order on the full tree; fix and re-run until all pass.
- **Verify:** every step passes; the capture set is ready for review.

## Iteration 19: Sync docs and skills

- **Goal:** contributors and the docs-sync automation write the new name and find the site's new files.
- **Files:** `AGENTS.md`, `branding/README.md`, `.agents/skills/**`
- **Steps:**
  1. Add the *Naming and brand* section to `AGENTS.md` (design, Contributor guidance) and link `branding/README.md`.
  2. Point the three sync skills at that section.
  3. State the design-system rules in `AGENTS.md` and `branding/README.md`, with the same wording for the type floor and the surface rule.
  4. Rewrite the *Docs-Site Landing and Features Pages* section of `ak-dev-sync-docs-from-branch` for the rebuilt site: the data files, their shapes, and which entry each kind of change touches.
  5. Bring every other dev skill that names a site file into line. Thirteen do: `ak-dev-sync-skills-and-docs-from-commit`, `ak-dev-review-pr`, and the eleven `ak-dev-new-*` skills for an evaluator, framework, guardrail, identity provider, knowledge base, messaging platform, multimodal store, queue transport, sandbox, secret provider and tracing provider.
- **Verify:** Testing step 4; the `ak-dev-sync-docs-from-branch` checklist finds nothing left to sync.

## Iteration 20: Phone pass

- **Goal:** the site works on a phone as well as it does on a desktop.
- **Files:** `docs/src/css/custom.css`, `docs/src/css/blog.css`, `docs/src/components/HomeSections/**`, and the cookie banner, chat, FAQ, loop diagram, architecture, particle mark, footer, Mermaid and blog index components
- **Steps:**
  1. Audit eleven pages at 390 px with touch emulation (`research/mobile-audit.md`): 6 things broken, 16 design findings.
  2. Fix all 22. What shipped for each is in the audit's Outcome table.
  3. Add the small-screen rules to `AGENTS.md`.
- **Verify:** no page scrolls sideways at 390, 360 or 320 px; the home page is unchanged at 1440 px; Testing step 6.

## Iteration 21: Home page follow-ups

- **Goal:** four requests from the maintainer after the phone pass.
- **Files:** `docs/src/components/HomeSections/{integrations.data.tsx,Integrations.tsx,integrations.module.css,Hero.tsx,hero.module.css,Deployment.tsx}`, `README.md`
- **Steps:**
  1. The integrations section lists every built-in provider: three more sandboxes (Kubernetes pods, Amazon EC2 over SSM, local subprocess), two more secret providers (environment variables, Kubernetes Secrets), A2UI and Open Knowledge Format. 82 entries, from 75. In-memory defaults are not listed: they are not something to plug in.
  2. The Guard group is taller for it, so the section now measures whether its tallest group fits the pinned frame, and falls back to the stacked list where it does not. Short or narrow windows set the groups a little closer.
  3. The hero headline capitalises every word, on the site and in the root README.
  4. The hero install line is `uv add agentkernel` alone.
  5. Google Cloud comes before Azure in the deployment tiles.
  6. The Azure tile offers the serverless variant: Container Apps scaled to zero, through the same Terraform module as the containerized one.
  7. Review fixes: the pinned layout is measured on trial before any pinned behaviour starts; print shows every integration group; the "In parallel" label has its own row; an open chat keeps its close control while the cookie banner waits; the features index does not animate with reduced motion; a diagram opens larger on a phone only when it was shrunk to fit.
- **Verify:** the pinned section at 1440 by 900, 1280 by 720 and 1024 by 768, and the stacked list at 1000 by 700; Testing steps 6 and 8.

## Iteration 22: Company name

- **Goal:** "Yaala Labs" is named only in legal text.
- **Files:** `docs/docusaurus.config.js`, `docs/docs/intro.md` and its `0.10.1` copy, `docs/README.md`, `use-cases/mathru-phm-companion/README.md`, `ak-py/pyproject.toml`, `AGENTS.md`
- **Steps:**
  1. Site metadata: the author, publisher and site name are "Open Agent Kernel"; the `company` tag and the name in both keyword lists go; the structured data describes the project, not the company.
  2. The "Built with ... by Yaala Labs" sign-off leaves the docs introduction (current and `0.10.1`) and the docs README; one use-case README drops "by Yaala Labs".
  3. The package author in `ak-py/pyproject.toml` is "Open Agent Kernel", with the same contact address.
  4. Two unused company logo images are deleted from `docs/static/img`.
  5. The rule is added to *Naming and brand* in `AGENTS.md`.
- **Kept, by the maintainer's decision:** the footer copyright line, the 20 older doc versions and published blog posts; and, as legal text or identifiers, the policy pages, `NOTICE`, README copyright lines, the `yaalalabs` organisation and registry names, `kernel.yaala.ai` and the email addresses.
- **Verify:** no "Yaala Labs" in the built home page outside the footer copyright; Testing step 6.

## Iteration 23: llms.txt

- **Goal:** an AI assistant can find out what OAK is and where each docs page is, from one file.
- **Files:** `docs/plugins/llms-txt/{index.js,text.js,template.md}`, `docs/docusaurus.config.js`, `docs/README.md`, `AGENTS.md`, `.agents/skills/ak-dev-sync-docs-from-branch/SKILL.md`
- **Steps:**
  1. Write the plugin (spec, section 9) and register it under `plugins` in the site config.
  2. Write the summary in `template.md`.
  3. Tell contributors which part is hand-written: `AGENTS.md` and the docs sync skill.
- **Verify:** the build writes both files; every address in `llms.txt` under the site's own domain is a page of the build; `llms-full.txt` has one `Source:` line for each docs page and no relative link outside code.

## Known gaps

- Not checked: Safari and Firefox; a real phone or Android Chrome (phones were checked in Chrome's emulation only); the WebGL hero on a low-power device; class and state diagrams in the light palette.
- Eight integration logos stay as PNG because neither icon set has a mark for them (Google ADK, Bedrock, Daytona, E2B, Langfuse, LiteLLM, OpenLLMetry, TypeSafe).
- Post bodies, and the headlines baked into the older banners, still say "Agent Kernel" (design, Open questions).
- The hero headline, the blog heading and the persona page titles and leads are new copy and need the maintainer's read.
