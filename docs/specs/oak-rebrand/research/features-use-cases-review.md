# Features and use-cases pages: review and restructure

Review for iteration 22 of `plan.md`, done on 2026-11-19 against the pages as they stood after phase 2.
Section lists come from `docs/src/pages/features.tsx` and `use-cases.tsx` at that point; heights are from
captures at 1440 px wide.

## The split between the three pages

- **Home** says what OAK is: the six stages, the architecture, integrations, deployment, levels, questions.
- **Features** is the reference: every capability once, under its stage, with the guide to read next.
- **Use cases** is the scenarios page: who uses OAK for what, each entry ending at something to read or run.
- A statement lives on one page. The other two link to it.

## Features

**Before** (2142 lines of page code, 3367 of CSS, 14 381 px tall):

| Section | What it said | Verdict |
|---|---|---|
| Hero with the runtime flow diagram | Frameworks in, OAK, clouds and channels out | Repeats the home architecture and integrations sections. Dropped |
| "Everything OAK does" page map | Seven boxes around a hub, linking to the sections below | A second table of contents drawn as a diagram. Replaced by a plain index |
| 01 The problem | Eleven tabs of "without OAK" against "with OAK" | Every "with" line restates a capability card below it. Dropped; the one comparison lives on Use cases |
| 02 Core capabilities | Twelve cards | Kept as the core of the page. Three cards repeated sections 03, 04 and 07, and one repeated the home deployment section |
| 03 Sandboxed execution | The detailed sandbox diagram | Kept: the only capability whose moving parts need a picture |
| 04 Framework support | Eight logo cards and a multi-framework card | Repeats the home integrations list and the "Framework-neutral runtime" card. Folded into two entries |
| 05 Testing | Three approaches, three comparison modes | Kept, as five entries under Observe |
| 06 Messaging | Eight channel cards | Repeats the home integrations list. Folded into one entry with a link per channel |
| 07 Protocol support | MCP, A2A, A2UI as long paragraphs | Repeats the "MCP and A2A" card. Now one short entry each, plus AG-UI, which was missing |

- Other findings:
  - 42 lines of gsap, ScrollTrigger and observer code; most content started hidden and needed script to appear.
  - A three.js particle background ran behind the whole page.
  - Seven hand-numbered section labels, six container widths (see the audit), red on the "without" side.
  - Capabilities with a guide but no place on the page: threads, secrets, human in the loop, scheduling,
    multimodal input, agent skills, queue mode, REST API, AG-UI, configuration.

**After** (548 lines of page code, 278 of CSS, about 11 500 px tall):

1. Page hero: what the page is, and how it relates to the home page.
2. The reference, with a sticky index of the six stages that follows the reader:
   - 01 Build (9 capabilities), 02 Connect (7), 03 Remember (4), 04 Guard (5), 05 Scale (5), 06 Observe (5).
   - Each capability: a title, one or two sentences, up to four points, the guide to read next, and links to
     further pages where there are several (the eight frameworks, the seven channels, the deployment targets).
   - Each stage header carries its drawing from the home page, small, as a wayfinding mark.
3. A closer look: the sandbox diagram at the full container width.
4. Closing panel.

- Why by stage: the home page teaches the six stages, so the reference uses the same six. A reader who met
  "Guard" on the home page finds guardrails, identity, secrets, approvals and sandboxes under "Guard" here.
- All 74 links on the page were checked against `docs/docs` and `version-0.10.1`, fragments included.
- Five links lost their `/docs/next/` prefix: those pages are now in `0.10.1`.

## Use cases

**Before** (624 lines of page code, 1463 of CSS, 4701 px tall):

| Section | What it said | Verdict |
|---|---|---|
| Hero over a three.js sphere, pinned for one screen | "Who is OAK built for?", then a paragraph listing frameworks and clouds | The question was never answered below. Replaced by the page hero |
| Traditional vs. OAK | Seven steps against two, "3 to 6 months" against "days", "about 90% time saved" | The comparison is kept, in neutral colours. The three figures have no source and are dropped |
| Real-world use cases | Three cards | One linked to a blog post. Two linked to `#`, and one of those claimed a 20x improvement. The linked one is kept; the two others are dropped until there is something to link |
| Why teams choose OAK | Eight cards around a hub | All eight restate the Features page or the home page. Dropped |
| Four audience segments | Services companies, product companies, startups, domain experts, with pain points and value | Written but never shown: the modal that held them had no trigger. Now a section |

**After** (483 lines of page code, 411 of CSS, about 8500 px tall):

1. Page hero.
2. 01 Built with OAK: three projects a reader can open.
   - Trade surveillance at Climate Impact X, in production, from the blog post.
   - Mathru and the waste sorting assistant, from `use-cases/` in the repository.
3. 02 Scenarios: ten needs, each with the path a request takes, a guide and an example folder.
   - The path is a rail with a box per part, in the vocabulary of the stage drawings; the part the reader
     writes is the one orange box.
   - Every guide and every example folder was checked to exist.
4. 03 Who it is for: the four team kinds, each with what OAK removes for it and a place to start.
5. 04 What you skip: the seven workstreams against the two, with a link to Features for the rest.
6. Closing panel.

## Both pages

- Built on `PageHero`, `SectionHeader`, `Reveal`, `ak-container` and the `ak-*` classes; one container width.
- No gsap, no ScrollTrigger, no canvas. All content is in the server-rendered page and visible without script.
- No interface icons are left on either page. The sandbox diagram uses Tabler outline icons, and brand marks
  from Simple Icons (AWS from Font Awesome, since Simple Icons has no AWS mark).
- Every control is a link: there are no tabs or accordions left to operate. Focus states are visible on all.
- Neither page imports `index.module.css` any more.

## Left for the maintainer

- The two unlinked "real-world" cards (AI-first SDLC, troubleshooter agent) can return when a write-up exists.
- The hero of each page has an empty slot for a drawing.
- Components no page imports after this change: `HeroAnimation` and `PlantParticlesBackground` (from these two
  pages), `AgentKernelRuntimeFlowDiagram`, `UseCaseJourneyMap`.
- Six framework logo images under `docs/static/img/integrations/` are no longer referenced: `chatgpt.png`,
  `crewai.png`, `googleADK.png`, `langgraph.png`, `pydantic-ai.png`, `smolagents.png`.
