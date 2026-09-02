# Score Metric Selection — `quasi_exact_match_score` vs alternatives

Supporting research for `../design.md`'s score-metric decision. Records the two design corrections
this metric went through and why the rejected alternatives (`quasi_contains_score`,
`PatternMatchMetric`, `rouge_score`/`sentence_bleu_score`, and DeepEval's model-backed scorers) were
ruled out in favour of `Scorer.quasi_exact_match_score`. `design.md` states only the final decision
and its consequence; this file is the record of how it got there.

## Two corrections

1. **First design: `Scorer.quasi_contains_score`**, assumed to perform substring containment.
   Verified against the source (`scorer/scorer.py:119-124`): it is list-membership *equality* —
   `normalize_text(prediction) in normalized_targets` — never a substring test in either argument
   direction. Same semantics as `quasi_exact_match_score`, extended over several gold answers; its
   only other in-package use is the DROP benchmark's multiple-gold-answer exact match.
2. **`spec.md`'s first-pass correction: `PatternMatchMetric`** (regex-based containment), reasoning
   that a verbose-but-correct `actual` should still match a short `expected` phrase. That containment
   property was re-evaluated and deliberately given up in favour of `quasi_exact_match_score` — a
   documented `Scorer` primitive rather than a hand-assembled regex `BaseMetric`.

## Rejected alternatives

- **`quasi_contains_score`** — ruled out above; not a containment test despite its name.
- **`PatternMatchMetric`** — does deliver containment (a full-string regex match against a
  normalised-and-wildcard-wrapped pattern), but was given up in favour of a documented `Scorer`
  primitive over a hand-assembled regex `BaseMetric`; see correction 2 above.
- **`rouge_score` / `sentence_bleu_score`** — both require an additional package DeepEval does not
  itself depend on: `rouge-score` pulls in `nltk`, `numpy`, and `absl-py` (verified via an isolated
  install). Both are F-measure-based, which penalises length mismatch between a short `expected` and
  a verbose `actual` at least as severely as exact match does, without the offsetting benefit of being
  a documented, dependency-free `Scorer` primitive.
- **Model-backed scorers** (`faithfulness` via SummaC, `hallucination` via Vectara HHEM,
  `answer_relevancy` via a sentence-transformers cross-encoder) — ruled out for the same reason as
  `quasi_contains`: everything model-backed pulls PyTorch and a first-run model download into every
  environment installing the `test` extra.

`quasi_exact_match_score` needs neither an extra dependency nor a model download, runs offline, and
ships in `deepeval` core with zero extra dependency (survey §9).

Sources: `deepeval/scorer/scorer.py` (`scorer/scorer.py:114-117`, `:119-124`) · isolated pip install
of `rouge-score` · `evaluator-framework-survey.md` §9.
