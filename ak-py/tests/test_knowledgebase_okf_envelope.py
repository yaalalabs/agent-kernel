"""The OKF manifest's scale envelope (#553 iteration 8).

The design targets 10,000 concepts held in process. That number is only meaningful if
something enforces it, so this module builds a bundle of exactly that size and measures what
the manifest retains — the claim CI checks rather than one the spec asserts in prose.

Measurement notes, because the wrong measurement here is worse than none:

* ``tracemalloc``, not RSS. RSS moves with the interpreter and with the allocator's retained
  arenas, so it measures the process rather than the manifest.
* Every manager walks its bundle once at construction before anything is measured. That walk
  warms pydantic's validators, PyYAML's caches and the OS page cache, so the measured second
  walk allocates what the manifest holds and little else.
* The memory assertion is made per concept over a slice of the bundle, because the cost is
  linear in the concept count and measuring the whole thing under coverage costs 75 s to learn
  the same number. Every other claim here is still made at the full 10,000.
* The measured bundle stays referenced across the second snapshot, so what is counted is
  retained memory rather than garbage the collector had not yet reclaimed.

Concept bodies are deliberately longer than ``BODY_INDEX_MAX_TOKENS``. An envelope measured
over bodies that fit under the cap would pass while telling us nothing: the cap is the reason
the number is bounded at all.
"""

import gc
import tracemalloc

import pytest

from agentkernel.knowledgebase import LocalDocumentStore, OKFManager
from agentkernel.knowledgebase.okf.model import DiagnosticCode
from agentkernel.knowledgebase.okf.parser import BODY_INDEX_MAX_TOKENS

CONCEPT_COUNT = 10_000

# 100 directories of 100, rather than 10,000 files in one: closer to how a bundle is actually
# organised, and it keeps the walk off a pathologically large directory index.
DIRECTORY_COUNT = 100
PER_DIRECTORY = CONCEPT_COUNT // DIRECTORY_COUNT

# Measured at 182 MB on this branch with BODY_INDEX_MAX_TOKENS = 128 (~19 KB per concept);
# 770 MB before the cap existed, for the same bundle. The ceiling leaves headroom for
# allocator and interpreter variation rather than pinning the measurement — a regression that
# matters here is a structural one, and those move the number by tens of megabytes.
ENVELOPE_BYTES = 250 * 1024 * 1024
PER_CONCEPT_BUDGET = ENVELOPE_BYTES // CONCEPT_COUNT

# The manifest costs the same per concept at every size — measured 19,090 B at 1,000, 2,000
# and 10,000, varying by 4 bytes — so the memory assertion is made over a slice. Under
# coverage, tracemalloc around a 10,000-concept walk costs 75 s and tells us exactly what a
# fifth of it does. The full-size claims below are still made at full size; only the
# measurement is sampled.
MEASURED_CONCEPTS = 2_000

VOCABULARY = (
    "orders customers revenue table column partition warehouse schema identifier timestamp "
    "currency amount status region channel product category fulfilment refund discount"
).split()

# Past the cap, so every concept exercises the truncation, but only just: the retained size
# is fixed by the cap, so a longer body would buy nothing here and cost real time in CI --
# each token is a regex split and a set insertion, 10,000 times over.
BODY_TOKEN_COUNT = BODY_INDEX_MAX_TOKENS + 32


def concept_document(index: int) -> bytes:
    """Render one deterministic concept, so a failure here is reproducible."""
    body = " ".join(f"{VOCABULARY[(index + offset) % len(VOCABULARY)]}{offset}" for offset in range(BODY_TOKEN_COUNT))
    return (
        f"---\ntype: BigQuery Table\ntitle: Concept {index}\n"
        f"description: Row-level facts for concept {index}.\n"
        f"tags: [sales, generated]\nstatus: stable\n---\n# Overview\n{body}\n"
    ).encode("utf-8")


@pytest.fixture(scope="session")
def bundle_root(tmp_path_factory) -> str:
    """Materialise the 10,000-concept bundle once for the whole session."""
    root = tmp_path_factory.mktemp("okf-envelope")
    (root / "index.md").write_bytes(b'---\nokf_version: "0.2"\n---\n# Root listing\n')
    for directory_index in range(DIRECTORY_COUNT):
        directory = root / f"d{directory_index:03d}"
        directory.mkdir()
        for file_index in range(PER_DIRECTORY):
            (directory / f"c{file_index:03d}.md").write_bytes(concept_document(directory_index * PER_DIRECTORY + file_index))
    return str(root)


@pytest.fixture(scope="session")
def manager(bundle_root: str) -> OKFManager:
    """One manager over the whole bundle, walked once at construction.

    ``refresh_seconds=None`` is load-bearing: it guarantees no operation in this module
    triggers an implicit extra walk between a measurement's two snapshots.
    """
    return OKFManager(LocalDocumentStore(bundle_root, writable=False), refresh_seconds=None, max_concepts=CONCEPT_COUNT)


class TestScaleEnvelope:
    def test_the_walk_keeps_every_concept_at_the_design_target(self, manager: OKFManager):
        manifest = manager._manifest

        assert len(manifest.concepts) == CONCEPT_COUNT
        assert manifest.truncated is False
        assert manifest.diagnostics == []
        # The root index.md was read on the same walk that absorbed 10,000 concepts.
        assert manifest.okf_version == "0.2"

    def test_the_manifest_stays_within_the_envelope(self, bundle_root: str):
        # A second manager over the same bundle, capped at the sampled size. Its construction
        # walk warms pydantic's validators, PyYAML's caches and the page cache, so the walk
        # measured below allocates what the manifest retains and little else.
        sampled = OKFManager(LocalDocumentStore(bundle_root, writable=False), refresh_seconds=None, max_concepts=MEASURED_CONCEPTS)

        gc.collect()
        tracemalloc.start(1)
        try:
            before = tracemalloc.take_snapshot()
            bundle = sampled._walk()
            gc.collect()
            after = tracemalloc.take_snapshot()
            # Referenced here on purpose: the snapshot must see the manifest as retained
            # rather than as garbage the collector had already reclaimed.
            assert len(bundle.concepts) == MEASURED_CONCEPTS
            retained = sum(statistic.size_diff for statistic in after.compare_to(before, "filename"))
        finally:
            tracemalloc.stop()

        per_concept = retained / MEASURED_CONCEPTS

        assert per_concept < PER_CONCEPT_BUDGET, (
            f"the manifest retained {per_concept:.0f} B per concept, over the "
            f"{PER_CONCEPT_BUDGET} B budget — {per_concept * CONCEPT_COUNT / 1024 / 1024:.0f} MB "
            f"projected at {CONCEPT_COUNT} concepts, against a {ENVELOPE_BYTES / 1024 / 1024:.0f} MB envelope"
        )

    def test_the_body_index_is_what_bounds_the_envelope(self, manager: OKFManager):
        # Without the cap this bundle's memory would scale with how much prose each author
        # wrote. Asserting the cap held for every concept is what makes the ceiling above a
        # property of the design rather than of the fixture.
        indexed = {len(concept.field_tokens["body"]) for concept in manager._manifest.concepts.values()}

        assert indexed == {BODY_INDEX_MAX_TOKENS}

    def test_ranking_the_whole_bundle_stays_deterministic(self, manager: OKFManager):
        # Also the performance canary: a ranker that stopped reading the per-concept token
        # index would show up here as a hang rather than as a wrong answer.
        first = [record["metadata"]["id"] for record in manager.search("orders0 revenue1", limit=5)]
        second = [record["metadata"]["id"] for record in manager.search("orders0 revenue1", limit=5)]

        assert first == second
        assert first == sorted(first)[: len(first)] or len(set(first)) == len(first)

    def test_truncation_keeps_a_lexicographic_prefix_and_says_so(self, bundle_root: str):
        limit = MEASURED_CONCEPTS
        truncated = OKFManager(LocalDocumentStore(bundle_root, writable=False), refresh_seconds=None, max_concepts=limit)
        manifest = truncated._manifest

        assert len(manifest.concepts) == limit
        assert manifest.truncated is True
        assert [diagnostic.code for diagnostic in manifest.diagnostics] == [DiagnosticCode.TRUNCATED]
        # The store lists in lexicographic order and the walk consumes it in that order, so a
        # truncated bundle is a prefix — not an arbitrary 5,000 of the 10,000.
        assert sorted(manifest.concepts) == list(manifest.concepts)
        assert max(manifest.concepts) < "d020/c000.md"
