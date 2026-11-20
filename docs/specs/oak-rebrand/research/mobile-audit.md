# Mobile design audit

Audit of the site on a phone, on 2026-11-20, against `develop` at `92e6792e1` (the merged rebrand).
Eleven pages were loaded in Chrome with phone emulation (touch, 390 by 844 px), measured by script and
read screen by screen: the home page, features, use cases, the three persona pages, the blog index, one
post, and three docs pages. Overflow was also measured at 360 px and 320 px, and the home page was
checked in dark mode. The findings and proposals below are as they were written before any change. All
of them were then taken: what shipped is under [Outcome](#outcome).

## What works

- No page scrolls sideways at 390, 360 or 320 px. Wide content (code, tables, tab rows) scrolls inside
  its own box.
- Text holds the type floor: body text is 16 to 17 px, and the only text under 13 px is the docs version
  badge (12 px) and the author's team line on a post (12.8 px).
- Sections stack cleanly into one column in both colour modes, and `Reveal` and lazy images behave under
  real scrolling.
- The docs menu, the "On this page" drawer, tables in posts and the search field (16 px, so no zoom on
  focus) are all fine.
- The persona step bar already follows the navbar when it slides away.

## Broken on a phone

| # | Finding | Measured | Cause |
|---|---|---|---|
| M1 | The chat launcher covers the cookie banner's **Accept** button on a first visit. | Launcher 138 by 52 px at the bottom right; the banner's buttons are 154 by 30 px in the same corner | The launcher's `z-index` (10060) is above the banner, and both anchor to the bottom |
| M2 | The phone menu has no **Quick start**, and on pages outside the docs it shows a lone chevron with no label. GitHub is an unlabelled icon. | Menu rows are 31 px tall | `.navbar .navbar-cta { display: none }` under 996 px also hides the copy inside the menu; `html:not(.plugin-docs) .navbar-version-dropdown` hides the "Versions" label but not its expand button |
| M3 | FAQ questions are set in the browser's button font, not the site's. | Arial in Chrome; Archivo everywhere else | `.faqQuestion` is a `button` with no `font: inherit`. This shows at every width |
| M4 | On the blog index a 72 px gap opens above the sticky topic bar when the navbar slides away, and cards scroll through it. | Bar at `top: 72px`, navbar at `-74px` | The bar lacks the `html:has(.navbar[class*='navbarHidden'])` rule that `StepTimeline` has. This shows at every width |
| M5 | The agent loop diagram on the business leader page shows two of its steps. The rest scroll sideways with no cue. | 340 px visible of 1,208 px; the card is 330 px tall around 110 px of content; step captions are at 55% opacity | A horizontal flow that only gains `overflow-x: auto` under 900 px |
| M6 | The chat field will zoom the page on an iPhone when it takes focus. | Field text is 15 px | Safari zooms any field under 16 px |

## Design findings

| # | Finding | Measured |
|---|---|---|
| M7 | The "Ask OAK" launcher sits over content on every screen: card titles, links, the last row of chips. | 138 by 52 px, a third of the width |
| M8 | The hero mark sits behind the headline and lead at 30% opacity. On a phone it reads as a stain under the copy, and its hover and ripple do not exist on touch. | `.stage { opacity: 0.3 }` and centred under 1,100 px |
| M9 | In "OAK, explained for your level of expertise" the drawing is above the rows, so it is off screen while the rows are read, but it keeps stepping, and two of the three rows are always dimmed. They look disabled. | Inactive titles in a pale blue; the drawing is 400 px tall |
| M10 | The architecture chips are logos only. Names appear on hover, which a phone does not have, and the generic icons (REST, WebSocket, CLI, schedules) cannot be told apart. | 36 px chips, no text |
| M11 | The integrations section is not pinned on a phone (by design), so all six groups are listed: 75 chips. | 5.5 screens |
| M12 | Pages are long, and the features page loses its stage navigation after the first screen. | Home 18.6 screens, features 19.4, use cases 17.1; the "On this page" row on features is `position: static` |
| M13 | A blog post's title is the same size as the headings inside it, and smaller than every other page title. | `h1` 24 px, `h2` 24 px; other page titles are 38 px |
| M14 | In the closing panel the wave runs behind the lead and lowers its contrast, in both colour modes. | `.closingWave { inset: 0 }` |
| M15 | Many tap targets are small. | Menu button 30 by 30 px; cookie buttons 30 px tall; arrow links 26 px; footer links 30 px; post tags 28 px; the topic links on blog cards 18 px (18 of them are under the 24 px minimum of WCAG 2.2) |
| M16 | The announcement takes three lines. | 125 px, above a 72 px navbar: the headline starts 300 px down |
| M17 | The cookie banner covers a quarter of the screen. | 208 px tall, text at 14 px |
| M18 | Mermaid diagrams shrink to fit, so labels are unreadable in the page, and the expanded view opens small with the page showing through. | Labels about 5.5 px in the page; expanded at 114%; backdrop at 94% opacity; expand button 37 by 28 px |
| M19 | The footer lists the three legal links twice, and is long. | 1.3 screens |
| M20 | The navbar keeps its desktop height. | 72 px, 8.5% of the screen |
| M21 | The side gutter differs between the site and the docs. | 24 px on the site. Docs text starts 40 px in: a 16 px container, then 16 px and 8 px of inner padding (first measured as 16 px, from the container alone) |
| M22 | In the chat panel, the header offers "Expand" though the panel is already full screen, and the page behind still scrolls. | Panel 390 by 844 px |

## Proposals

**Fix as one batch (M1 to M6).** Each is a few lines of CSS, with no design decision in it:

- M1: lift the launcher above the cookie banner while the banner is shown, or hide it until consent is answered.
- M2: scope the two `display: none` rules to the bar (`.navbar__inner`), so the menu keeps "Quick start" and "Versions"; give the GitHub entry a text label in the menu.
- M3: `font: inherit` on `.faqQuestion`.
- M4: copy the `StepTimeline` rule to `.topicBar`.
- M5: under 900 px, lay the loop out as a two-column grid of steps (or a numbered column), and set the captions in the secondary text colour.
- M6: 16 px on the chat field.

**Decisions for the maintainer.**

- M7, launcher: on phones show the mark only, in a 48 px square, with the same accessible name.
- M8, hero mark, three directions:
  - A. Its own block above the label, about 160 px tall, at full strength. Paid for by M16 (one-line announcement) and M20 (shorter navbar).
  - B. Anchored to the top right corner of the hero and cropped by the edge, so it stays clear of the lead.
  - C. No mark on phones: the plain page, and no WebGL on low-power devices.
- M9, levels: on phones show all three rows at full strength and stop the stepping; the drawing stays as a still image.
- M10, architecture: under each group title, one line naming the members, shown only on touch devices.
- M11, integrations: an accordion of the six stages with the first open, about 1.5 screens.
- M12, features: make the stage row sticky under the navbar, as the persona step bar is.
- M13: post title at 32 px on phones.
- M14: on phones keep the wave to the lower part of the panel, under the buttons.
- M15: 44 px menu and cookie buttons; arrow links and footer links padded to 44 px on coarse pointers.
- M16: on phones, the label and the linked headline only, on one line.
- M17: one sentence and the two links on phones.
- M18: open the expanded diagram at twice the fitted size, on an opaque backdrop.
- M19: drop the bottom row of legal links; two columns of links on phones.
- M20: 56 px navbar on phones.

## Not checked

- A real phone. Everything above is Chrome's phone emulation on a Mac.
- Safari on iOS: toolbar behaviour, the WebGL hero and wave on a low-power device, the on-screen keyboard over the chat panel.
- Android Chrome, landscape, and tablet widths between 768 and 996 px.
- Touch gestures inside the expanded diagram.

## Outcome

All 22 findings were fixed on 2026-11-20, with direction A for the hero. Checked the same way as the
audit: Chrome phone emulation at 390 px in both colour modes, overflow at 360 and 320 px, reduced
motion, and the home page at 1440 and 1024 px for regressions.

| # | What shipped |
|---|---|
| M1 | While the cookie banner waits for an answer the launcher is not shown, under 1,200 px (where the two can meet). The banner sets `data-ak-consent="pending"` on the root element. |
| M2 | The hide rules are scoped to the bar (`.navbar__inner`). The menu ends with a full-width "Quick start", GitHub has its name, the version entry is hidden whole outside the docs, and rows are 44 px at the body size. |
| M3 | `font: inherit` on the FAQ question button. |
| M4 | The topic bar moves to the top when the navbar slides away. |
| M5 | Under 900 px the loop is a column of steps on a rail, with the two parallel steps in a named band. Captions use the secondary text colour at every width. |
| M6 | The chat field is 16 px on phones. |
| M7 | The launcher is the mark alone, 48 px, on phones. It is hidden while the phone menu is open. |
| M8 | Direction A: under 600 px the mark is a 9 rem block above the label, at full strength. Between 600 and 1,100 px it is unchanged. |
| M9 | Under 996 px the drawing is still, no row is singled out, and all three rows are at full strength. |
| M10 | Each card lists its members by name where there is no hover (`@media (hover: none)`). |
| M11 | Under 996 px the six groups fold, with the first open: 2.2 screens, from 5.5. Groups open independently, closed ones stay reachable by find-in-page, and without script nothing is folded. |
| M12 | The stage row on the features page stays under the navbar on small screens and keeps the current stage in view. |
| M13 | Post titles are 32 px on phones. |
| M14 | Under 720 px the wave keeps to the foot of the panel, under the buttons. |
| M15 | Menu, close, cookie, diagram and viewer buttons are 44 px. One-line links (`ak-link`, the back link, module and example links, card topics) get a 44 px target from an unseen box on coarse pointers, with no change to the layout. Footer links are 44 px rows on touch. |
| M16 | Under 720 px the announcement is the label and the headline on one line, and the whole bar is the link. |
| M17 | On phones the banner shows the first sentence and the two policy links: 160 px, from 208. |
| M18 | On a narrow screen a diagram opens at twice the fitted size, from its top left corner. The viewer's backdrop is solid at every width. |
| M19 | The bottom row of legal links is gone. On phones the footer is left aligned with the link columns two abreast: 1.1 screens, from 1.3. |
| M20 | The navbar is 56 px under 996 px. |
| M21 | Docs and plain pages start on the site gutter under 996 px. |
| M22 | On phones the panel has no "Expand", and the page behind it does not scroll. |

The home page is 15.9 screens on a phone, from 18.6. The items under [Not checked](#not-checked) still stand.
