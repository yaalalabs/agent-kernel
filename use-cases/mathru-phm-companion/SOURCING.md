# Sourcing the clinical data

Six files in `data/` hold every clinical value in this system, and all six still ship as
`status: placeholder`. This document records what has been verified so far, so the sourcing
session does not start from a blank page.

The four child-health schedules are captured with their provenance recorded. The **antenatal**
and **danger-sign** files are still empty: no source to hand covers either. **No file has been
flipped to `sourced`,** so nothing here reaches a mother yet. `provenance_test.py` enforces
that a file cannot claim `sourced` until its provenance block names a document, its printed
date, a `.gov.lk` or `who.int` URL, and a second cross-check.

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

### Corroborated by a second source, still not authoritative

A second compilation, citing the **Sri Lanka Essential Health Services Package 2019**
(`previousmoh.health.gov.lk`), agrees with the 2017 poster on **every immunisation line**:
BCG at birth; OPV + Pentavalent + fIPV at 2 and 4 months; OPV + Pentavalent at 6; MMR-1 at 9;
Live JE at 12; OPV + DPT booster at 18; MMR-2 at 36; OPV booster + DT at 60.

Those values are now in `data/immunization_schedule.yaml` with that provenance recorded. The
file **remains `placeholder`**, for three reasons:

1. **The 2022 CHDR circular does not carry the schedule.** It mandates the CHDR as the
   national child health record covering birth to 19 years; it does not reproduce the visit
   table. So the newest document in play cannot be the citation for these values.
2. **Both sources that do carry the schedule predate it.** A 2017 poster and a 2019 services
   package. Two old sources agreeing is weaker than it looks — they may share an origin rather
   than independently confirming each other.
3. **`previousmoh.health.gov.lk` is a legacy domain**, the same class of hazard as
   `old.epid.gov.lk`. It passes the `.gov.lk` URL check, which is exactly why `document_date`
   is a required provenance field.

The line to check first is **MMR-1 at 9 months**. The timing of the first measles-containing
dose has moved before, and it is the single value most likely to be stale.

### The four CHDR child schedules

The CHDR carries several overlapping schedules that do not share their ages. Each now has its
own data file, its own provenance block, and its own placeholder guard. All four are captured
and all four are gated:

| Schedule | File | Entries | Blocker |
| --- | --- | --- | --- |
| Immunisation | `immunization_schedule.yaml` | 9 | Both sources predate the 2022 CHDR circular |
| Developmental screening | `developmental_screening.yaml` | 10 | Relayed from a secondary description, not the schedule document |
| Vitamin A | `vitamin_a.yaml` | 10 | **Unresolved discrepancy**, see below |
| MMN supplementation | `mmn_supplementation.yaml` | 3 periods | Term / normal-birth-weight pathway only |

**Developmental screening** is the one with independent value: 24, 48 and 60 months carry no
immunisation, so a mother told only about immunisation visits would miss all three, and the
60-month point is the school-entry assessment. There is a test asserting exactly that gap.

**Vitamin A carries an unresolved conflict** between the two readings available:

| Reading | Ages | Doses |
| --- | --- | --- |
| A — national strategy, "every 6 months from 6 months through 5 years" | 6, 12, 18, 24, 30, 36, 42, 48, 54, 60 | 10 |
| B — reported service data | 6, 18, 36 | 3 |

That is 6-month spacing against 12-month spacing, not a rounding difference. The file encodes
reading A, because a stated national recommendation is the stronger claim and expanding its
own interval is mechanical rather than a judgement about dosing; the three ages that also
appear in reading B are marked in the file. The discrepancy is recorded in the file itself and
a test asserts it stays recorded. It must be resolved before that file is flipped.

**MMN is the only schedule whose items have duration** — 60-day periods, not appointments. The
`visits` schema now carries an optional `duration_days` for this. Anything presenting them
must say "starting on" rather than naming an appointment date. The regime is also the term /
normal-birth-weight pathway only; preterm and low-birth-weight infants follow a different one
that this project neither models nor stores the data to identify.

None of the four is wired into a tool. `schedules.py` exposes a loader for each, but
`next_appointment` still reads immunisation and antenatal only — surfacing the others is a
product decision, not a data one.

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

The antenatal and danger-sign files remain fully unpopulated.

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
