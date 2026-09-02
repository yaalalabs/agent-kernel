# Sourcing the clinical data

The three files in `data/` hold every clinical value in this system. All three still ship as
`status: placeholder`. This document records what has been verified so far, so the sourcing
session does not start from a blank page.

**Nothing here has been entered into the data files.** `provenance_test.py` enforces that a
file cannot claim `status: sourced` until its provenance block names a document, its date, a
`.gov.lk` or `who.int` URL, and a second cross-check.

## Rules

1. **Never cite a re-upload.** Copies of the Maternal Care Package and the EPI schedule are on
   Scribd and are convenient. They are unverifiable copies of unknown vintage. Get the
   `.gov.lk` original or do not use the value. `provenance_test.py` fails on a banned host.
2. **Two sources per value.** If they agree, take it. If they disagree, the newer official one
   wins and the discrepancy is noted in the file.
3. **Check the date printed on the face of the document.** Not the file metadata, not the URL,
   not the search ranking. An old-but-official document is more dangerous than an obviously
   unofficial one.

## Immunisation schedule — Epidemiology Unit

### Verified: the top result is a 2017 document

`https://www.epid.gov.lk/storage/post/pdfs/en_6403b42a75fa4_Doc2.pdf`

This is the current site's "National Immunization Schedule – Sri Lanka". It is a scanned
poster with **no text layer**; the image has to be extracted and read to see anything.

Having read it, three things are true at once, and they conflict:

| Signal | Says | Reliability |
| --- | --- | --- |
| Footer printed on the poster | **© 2017** | The document's own claim |
| Publisher line on the poster | "Ministry of Health, **Nutrition and Indigenous Medicine**" | Corroborates ~2015-2019; the ministry has since been renamed |
| PDF file metadata | Created 2023-03-05, MS Word, author "VVH Gunarathna" | A re-save date, not a revision |
| Where it is served from | The **current** epid.gov.lk, top search result | Implies currency it does not have |

So the trap is worse than a stale link on an old domain. This is a nine-year-old document on
the live site, with 2023 file metadata that masks its age. Under rule 3 it cannot be used
without a second, current source.

`old.epid.gov.lk` is also still live and still ranks —
`old.epid.gov.lk/web/attachments/article/138/Immunization_Schedule.pdf` — and note it is a
`.gov.lk` host, so the URL check alone will not catch it. `document_date` is the only guard.

### What that 2017 poster shows — NOT CLEARED FOR USE

Recorded only as one half of a cross-check. If the CHDR disagrees with any line here, the
CHDR wins and this document is stale.

```
0-4 weeks   BCG (preferably within 24h of birth)
2 months    OPV + Pentavalent (DTP-HepB-Hib) 1st, fIPV 1st
4 months    OPV + Pentavalent 2nd, fIPV 2nd
6 months    OPV + Pentavalent 3rd
9 months    MMR 1st
12 months   Live JE
18 months   OPV + DTP 4th
3 years     MMR 2nd
5 years     OPV + DT 5th
10 years    HPV 1st and 2nd (Grade 6)
11 years    aTd 6th (Grade 7)
```

The 9-month MMR is the line to check first: the timing of the first measles-containing dose
has moved before, and it is the value most likely to be out of date.

### Still open

- The **2025 National Immunization Summit report** exists
  (`en_68a7e565a6832_FINAL NIS 2025 Report - 18.08.2025_compressed.pdf`) but is over 10 MB and
  could not be retrieved here. Worth opening directly: the summit reviewed the existing
  schedule and considered new vaccines, so a revision may be in flight.
- The **CHDR** (Child Health Development Record) is the per-child immunisation record, held in
  two portions, one with the mother and one with the PHM. A physical copy is the natural second
  source and is the one this project cannot obtain remotely.

## Antenatal schedule — Family Health Bureau

### Not found by any filter tried

The library at `fhb.health.gov.lk/resources` holds 401 documents across ~34 pages. The
**Maternal Care Package** did not appear in:

| Filter tried | Result |
| --- | --- |
| `?units[0]=maternal-care` | 6 documents, all forms plus one adolescent health strategy. Not present. |
| `?type=guideline` | 33 guidelines over 3 pages; page 1 is 2024-2025 nutrition, reproductive health, implants. Not present on page 1. |
| `?search=maternal+care+package` | Returns the unfiltered 401; no exact-title match on page 1. |
| `/index.php/en/technical-units/maternal-care-unit` | **HTTP 404** |

Remaining leads: pages 2-3 of `?type=guideline`, and `?type=form` for the pregnancy record
form. The FHB lists `dmch@fhb.health.gov.lk` and +94 112 681 309, which may be faster than the
library search.

`term_gestational_weeks` in `data/antenatal_schedule.yaml` should come from this same document.

## Danger signs — FHB, supplemented by WHO

Not yet attempted. The leads are the pregnancy record form under `?type=form`, which lists
danger signs for mothers, and the patient-facing flash cards under Publications.

Each sign needs a source **and** a defensible severity. The table holds only `red` and `amber`
now; where a source does not clearly imply "go now", mark it `amber`. The amber floor in
`danger_signs.py` is doing the safety work regardless — an unmatched symptom is already amber,
and a placeholder table already escalates everything as red.

## When values land

1. Fill the `provenance:` block at the top of the file.
2. Flip `status:` to `sourced`.
3. Update `test_all_clinical_files_currently_ship_as_placeholders` in `provenance_test.py` in
   the **same commit**, so the flip is never silent.
4. Add the citation to the sources table in `README.md`.

No code changes are needed. The placeholder guards lift on their own.
