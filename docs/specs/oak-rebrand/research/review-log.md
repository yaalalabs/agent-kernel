# Review log

A record of the maintainer's review rounds on the redesigned site, all on 2026-11-19, and of what each
round decided. It is supporting material, not requirements: [design.md](../design.md) states the outcome,
and [plan.md](../plan.md) names a rejected direction only where it explains a decision.

Figures marked "as recorded" were measured when the work was done and were not measured again for this
log.

## Round 1: the phase 2 site

The first build of the design system (tokens, shared components, stage drawings, a rebuilt home page) was
reviewed in the browser.

| Item | Outcome |
|---|---|
| Stage drawings (`VectorMotion`) | Accepted as the site's motion language |
| Hero: a particle mark on a 2D canvas | Not accepted: not lively enough |
| Integrations: a ledger, one hairline row per category | Not accepted: the maintainer asked for a section that brings each group forward as the page scrolls |
| Level tiles | To be redone, with more care for how the section and its items are presented |
| Features and use-cases pages | To be reviewed, restructured and stripped of duplicates |
| Items left "not done", and dead code | To be finished and removed |

Earlier in the same phase the integrations had been a four-column compatibility matrix. It showed about
30 of the 76 integrations and dropped whole categories (identity, secrets, queues, sandboxes), which is
where the requirement that every integration is listed by name comes from.

## Round 2: hero options and seven points

A hero built as a system drawing (channels, the mark, frameworks, with simulated traffic) was found worse
than the particle mark and removed. With four directions turned down (a fade-in mark, an extruded mark,
the 2D particle mark, the system drawing), the maintainer asked to see options before the next build, and
then set the brief directly.

| Point | Decision |
|---|---|
| Colour mode | Light is the default; dark stays on the navbar switch |
| Install line | Show the `uv` command beside `pip` |
| Persona pages | The way back to the path selection had gone missing; restore it |
| Architecture section | Rebuild: lines were disconnected, and some ran under boxes |
| Chat button | Keep the colours; make the text readable |
| Hero | A particle animation: the logo builds from particles as the page loads, animates under the pointer, and scatters on scroll. The reference named was mazehq.com |
| Blog banners | Low effort: recolour the existing ones and change their logo; add banners where they are missing |

Follow-ups in the same round:

- Particle fields elsewhere on the home page: of the places offered, the maintainer chose the closing
  panel and the integrations section.
- Docs diagrams were hard to read on the light page. A dark plate under each diagram was offered and
  turned down: the maintainer asked for a real light version, with a white background and colours chosen
  for it.
- The home page announcement was changed to identity provider support, then shortened because the line
  ran too long.

## Round 3: refinements

| Item | Decision |
|---|---|
| Dot cloud behind the integrations list | Removed as oddly placed: a shape floating under the list, cut by the bottom of the window. Replaced by the recommended option of three, a floor of dots along the bottom edge, changed so that it does not read as a copy of the closing panel's wave |
| Hero entrance | The spiral fly-in was too intense. Of four options the maintainer chose the calmest (the mark comes into focus from a haze), over two seconds |
| Hero density | Settled over three trials: about a quarter of the dots the first version had (lattice step `UNITS / 64`), each about 40 per cent larger. The original small dot was tried at this density and undone as too faint |
| Hero ripple | The ripple trails the cursor by a moment, and fades slowly once the pointer leaves the mark |
| Shared blog author | "Yaala Labs" becomes "OAK"; the footer names Open Agent Kernel |
| Blog audit | All four proposals in [blog-audit.md](blog-audit.md) accepted |
| OAK avatar | The bare mark was cut by the round crop; it now sits on a disc |
| Post authors | Posts credited to the shared author name their writers, taken from the commit history, with the writer's GitHub picture where the account has one. One post (knowledge bases) was assigned on the maintainer's word. An account with only the generated placeholder picture keeps the OAK avatar |
| Root README | Restructured to follow the site |

## Merging develop

Develop gained the agent registry (#983) and the first part of the Azure Functions retirement (#984)
while the branch was open. Eight files conflicted.

- Skills and docs pages: develop's content, in the new name. Six places where develop's new prose said
  "Agent Kernel" were renamed.
- `docs/src/pages/features.tsx` (and the since-removed `FeatureExplorer/data.tsx`): the branch's
  restructure was kept and develop's edits were carried into it.
- `docs/docs/intro.md` kept the short tip; the registry entry heads `docs/docs/whats-new.md`. The `0.10.1`
  copy was left alone, because the registry is not in that release.
- Azure Functions: the two examples develop deleted stay deleted, and the site and the root README no
  longer offer it. The pages under `docs/docs` are left to `docs/specs/957-retire-azure-functions/`.

## Measurements kept from the rounds

As recorded:

- Features page: 2,142 lines of page code became about 550. It listed 35 capabilities before the merge of
  develop and lists 36 after it.
- Persona pages: 2,471 lines of page code became about 1,000, on one skeleton.
- Dead code: ten unused components and the 6,100 line `index.module.css` were removed.
- Diagrams: a node that a diagram colours itself sets both its fill and its text colour in all 1,866 cases
  across every doc version, which is why no older version needed an edit for the light palette.
- Keyboard pass on the home, features, use-cases and developer pages: every control reachable, with a
  visible focus ring.

Checked again for this log, against the tree:

- 76 integrations in `HomeSections/integrations.data.tsx`.
- The integrations section pins at 997 px and wider, in a window at least 700 px tall, when motion is
  allowed (`PIN_QUERY` in `HomeSections/Integrations.tsx`).
- 17 blog posts, each with a banner; 14 of them changed author (12 and 2).
- The `0.10.1` snapshot differs from `docs/docs` in ten pages at the merge base.

## Pull request review (#988)

Decisions from the review of the pull request that touch these documents:

- `Reveal` stays as the one entrance effect, and the earlier scroll-reveal client module is removed. The
  motion requirement is restated as what is true: content is never hidden without script, with reduced
  motion, in print, or when it is already on screen at load.
- The type floor is 15 px for running text, with the 13 px monospace label and 14 px labels inside
  diagrams as the only smaller sizes. Surfaces are flat with two exceptions: the light-mode card shadow
  and the shadow under floating layers. `design.md`, `AGENTS.md` and `branding/README.md` now say this in
  the same words.
- The snapshot check is restated against the merge base, and the mirror step is removed from the spec.
- The dev skills and `AGENTS.md` named site files this change deleted; they now name the files that exist.
