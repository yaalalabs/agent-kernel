# Blog design audit

Audit of the blog index (`/blog`) and a post page, on 2026-11-19, after the banners were recoloured.
Measured in Chrome at 1440 px and 390 px, in both colour modes. Nothing here is implemented: these are
findings and proposals for the maintainer to choose from.

## What works

- The banners now read as one set, and the index thumbnail keeps their shape.
- Both colour modes are legible; nothing depends on the old cyan theme.
- The topic filter works and stays in view while the list scrolls.
- The closing panel and footer match the rest of the site.

## Findings

| # | Finding | Measured | Elsewhere on the site |
|---|---|---|---|
| B1 | A third typeface. Leads, excerpts and article text are set in Charter, a serif used nowhere else. | Charter, 18 px on the index, 22 px in posts | Archivo for text, JetBrains Mono for labels and code |
| B2 | Headings are heavier. | Weight 800 (`h1` 52 px, post `h2` 30 px at 700) | Weight 600, tighter tracking |
| B3 | Article text and code are oversized. | Text 22 px on a 38.5 px line; code 20.7 px, so code blocks overrun the column and scroll | Text 18 px; code 15 px |
| B4 | A narrow centred column on both pages. | 696 px, centred in a 1320 px page | 1280 px container, left aligned, with `PageHero` |
| B5 | The index has no page header in the site's pattern: no label, a smaller title, no room for a lead post. | `h1` 52 px, no label | Label, 64 px title, lead |
| B6 | Banners are shown small. | 190 by 100 px thumbnails | The banners were made to be seen: 3200 px wide |
| B7 | Long posts have no table of contents. | The sample post is 11,400 px tall | Docs pages have one |
| B8 | The way back is a round floating chevron beside the title. | One-off control | "Back to" text link at the top of `PageHero` |
| B9 | Tags at the foot of a post use the old tinted pill, and there are many. | 13 tags on the sample post | `ak-tag`, outlined, monospace |
| B10 | Phone: the author and date wrap into four short lines beside the thumbnail, and titles are cut at two lines with an ellipsis. | 390 px | n/a |
| B11 | Tables inside a post switch to a small sans face in the middle of serif text. | About 13 px | n/a |
| B12 | Post titles and bodies still say "Agent Kernel". | 14 of 17 titles | Known: post text was left as history by decision |

## Proposed changes

1. **Type (B1, B2, B3, B11).** One text face for the blog, the site's: text at 19 px on a 1.65 line, headings at
   weight 600 on the site scale, code at 15 px. This is the largest single improvement and the smallest change.
2. **Index (B4, B5, B6, B10).** A page header in the site's pattern, the latest post as a lead card with its
   banner at full width, then the rest as a grid of cards with banners. On a phone the banner sits above the
   title and titles are not cut.
3. **Post page (B4, B7, B8).** Keep a reading column at the site's 720 px measure, add a table of contents
   beside it on wide screens, and replace the floating chevron with an "All posts" link above the title.
4. **Tags (B9).** The site's tag style, with the topic shown at the top of the post and the full list at the foot.
5. **Not proposed:** renaming post text (B12). Raise it separately if wanted.
