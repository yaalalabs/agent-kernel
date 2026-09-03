"""The OKF backend over a document store (#553 iteration 6).

This is where the two axes meet, so the guarantees pinned here are mostly about the seam. The
manifest is the reason a browse over an S3 bundle is not one GET per object per tool call, so
its refresh policy — one walk under concurrent callers, a stale answer in preference to a
failed one, a clock that resets on failure — is asserted rather than described. Write-through
is asserted with refresh_seconds=None, which is what proves a written concept is visible
because the write inserted it and not because a refresh happened to fire.

Ranking is pinned because a lexical ranker that reorders between processes would make an
agent's behaviour irreproducible: scoring is field-weighted presence and ties break on path.

Nothing is ever filtered on trust or staleness — the OKF conformance rules make those advisory
signals, and a bundle of entirely stale, unverified concepts must still answer every operation.

No test touches a live bucket or a network: every store here is a LocalDocumentStore over
tmp_path, sometimes subclassed to count or to fail.
"""

import threading
import time

import pytest
import yaml

from agentkernel.knowledgebase.errors import KnowledgeCapabilityError, KnowledgePathError
from agentkernel.knowledgebase.okf import manager as manager_module
from agentkernel.knowledgebase.okf.manager import OKFManager
from agentkernel.knowledgebase.okf.model import DiagnosticCode, TrustTier
from agentkernel.knowledgebase.store import LocalDocumentStore

ORDERS = """---
type: BigQuery Table
title: Orders
description: One row per completed purchase.
tags: [sales, revenue]
verified: [{by: "human:jsmith"}]
---
# Schema
FK to [customers](/tables/customers.md).
"""

CUSTOMERS = """---
type: BigQuery Table
title: Customers
description: One row per customer.
tags: [sales]
---
# Schema
customer rows
"""

ORDERS_DB = """---
type: Dataset
title: Orders DB
---
# Overview
the warehouse
"""

BUNDLE = {
    "index.md": '---\nokf_version: "0.2"\n---\n# Root listing\n- orders\n',
    "log.md": "# Log\n- created\n",
    "tables/index.md": "# Curated tables\n- orders\n",
    "tables/orders.md": ORDERS,
    "tables/customers.md": CUSTOMERS,
    "datasets/orders_db.md": ORDERS_DB,
    "broken.md": "no frontmatter at all\n",
}


def write_bundle(root, files) -> str:
    """Materialise a bundle on disk and return its root as a string."""
    for path, text in files.items():
        target = root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
    return str(root)


def make_manager(root, files=None, **kwargs) -> OKFManager:
    """Build a manager over a freshly written bundle."""
    return OKFManager(LocalDocumentStore(write_bundle(root, files if files is not None else BUNDLE), writable=True), **kwargs)


def ids(records) -> list[str]:
    """Reduce records to their ids, which is what most assertions are about."""
    return [record["metadata"]["id"] for record in records]


class CountingStore(LocalDocumentStore):
    """A store that counts walks, and can be told to fail every walk after the first."""

    def __init__(self, root: str, fail_after_first: bool = False, walk_delay: float = 0.0) -> None:
        super().__init__(root, writable=True)
        self.list_calls = 0
        self.fail_after_first = fail_after_first
        self.walk_delay = walk_delay

    def list(self, prefix: str = "") -> list[str]:
        self.list_calls += 1
        if self.fail_after_first and self.list_calls > 1:
            raise OSError("store is unavailable")
        if self.walk_delay:
            time.sleep(self.walk_delay)
        return super().list(prefix)


class FakeClock:
    """Stands in for the manager module's ``time``, so refresh timing is not wall-clock bound."""

    def __init__(self, now: float = 1000.0) -> None:
        self.now = now

    def monotonic(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class TestCapabilities:
    def test_capabilities_are_built_from_the_store_it_was_handed(self, tmp_path):
        capabilities = make_manager(tmp_path).capabilities
        assert capabilities.kinds == ["document"]
        assert (capabilities.search, capabilities.search_mode) == (True, "lexical")
        assert (capabilities.fetch, capabilities.browse, capabilities.derives_schema) == (True, True, True)
        assert capabilities.writable is True

    def test_a_read_only_store_makes_the_backend_read_only(self, tmp_path):
        store = LocalDocumentStore(write_bundle(tmp_path, BUNDLE), writable=False)
        assert OKFManager(store).capabilities.writable is False

    def test_declaring_no_query_language_routes_read_to_search(self, tmp_path):
        manager = make_manager(tmp_path)
        assert manager.capabilities.query is False
        assert manager.capabilities.query_language is None
        assert ids(manager.read("customers")) == ids(manager.search("customers"))

    def test_the_backend_name_falls_back_to_okf(self, tmp_path):
        assert make_manager(tmp_path).backend_name == "okf"
        assert make_manager(tmp_path, name="sales-kb").backend_name == "sales-kb"


class TestSchema:
    def test_schema_works_without_any_add_schema_call(self, tmp_path):
        # The whole point of derives_schema: a bundle already states its own shape.
        schema = make_manager(tmp_path).schema()
        assert schema["backend"] == "okf"
        assert schema["capabilities"]["search_mode"] == "lexical"

    def test_the_derived_schema_describes_the_bundle(self, tmp_path):
        derived = make_manager(tmp_path)._derived_schema()
        assert derived["okf_version"] == "0.2"
        assert derived["concept_count"] == 3
        assert derived["types"] == ["BigQuery Table", "Dataset"]
        assert derived["top_level_directories"] == ["datasets", "tables"]
        assert derived["reserved_files"] == {"index": ["index.md", "tables/index.md"], "log": ["log.md"]}
        assert derived["truncated"] is False
        assert derived["diagnostics"] >= 1

    def test_capabilities_cannot_be_overridden_by_add_schema(self, tmp_path):
        manager = make_manager(tmp_path)
        manager.add_schema({"capabilities": {"writable": "yes"}, "note": "kept"})
        schema = manager.schema()
        assert schema["capabilities"] == manager.capabilities.model_dump()
        assert schema["note"] == "kept"


class TestSearch:
    def test_frontmatter_outranks_body_text_by_presence_not_frequency(self, tmp_path):
        files = {
            "titled.md": "---\ntype: Note\ntitle: Widget\n---\nunrelated prose\n",
            "bodied.md": "---\ntype: Note\ntitle: Something Else\n---\n" + ("widget " * 40),
        }
        # The body mentions it forty times and still loses: title weight 4 beats body weight 1.
        assert ids(make_manager(tmp_path, files).search("widget")) == ["titled.md", "bodied.md"]

    def test_ties_break_lexicographically_on_path(self, tmp_path):
        # Both score 4 on a title hit alone, so only the path ordering can decide.
        assert ids(make_manager(tmp_path).search("orders")) == ["datasets/orders_db.md", "tables/orders.md"]

    def test_ranking_is_identical_across_two_independently_built_managers(self, tmp_path):
        first, second = make_manager(tmp_path), make_manager(tmp_path)
        assert ids(first.search("sales orders customer", limit=10)) == ids(second.search("sales orders customer", limit=10))

    def test_a_concept_matching_nothing_is_excluded_rather_than_ranked_last(self, tmp_path):
        assert ids(make_manager(tmp_path).search("revenue", limit=10)) == ["tables/orders.md"]

    def test_an_unmatched_query_returns_nothing(self, tmp_path):
        assert make_manager(tmp_path).search("zebra") == []

    def test_limit_truncates_the_ranking(self, tmp_path):
        assert len(make_manager(tmp_path).search("sales", limit=1)) == 1

    def test_search_records_carry_the_advisory_signals_but_no_links(self, tmp_path):
        metadata = make_manager(tmp_path).search("revenue")[0]["metadata"]
        assert metadata["id"] == "tables/orders.md"
        assert metadata["kind"] == "BigQuery Table"
        assert metadata["trust"] == TrustTier.HUMAN_REVIEWED.value
        assert metadata["stale"] is False
        assert "links" not in metadata


class TestFetch:
    def test_records_come_back_in_the_order_requested(self, tmp_path):
        requested = ["tables/orders.md", "datasets/orders_db.md", "tables/customers.md"]
        assert ids(make_manager(tmp_path).fetch(requested)) == requested

    def test_a_duplicate_id_yields_one_record(self, tmp_path):
        assert ids(make_manager(tmp_path).fetch(["tables/orders.md", "tables/orders.md"])) == ["tables/orders.md"]

    def test_an_unknown_id_is_omitted_rather_than_raised_or_stubbed(self, tmp_path):
        assert ids(make_manager(tmp_path).fetch(["nope.md", "tables/orders.md"])) == ["tables/orders.md"]

    def test_an_escaping_id_is_dropped_not_raised(self, tmp_path):
        assert make_manager(tmp_path).fetch(["../../etc/passwd"]) == []

    def test_a_directory_id_from_browse_is_dropped_rather_than_aborting_the_batch(self, tmp_path):
        # browse hands the agent directory records and the fetch tool invites it to browse
        # first, so a directory id is a routine mistake. Reading one is an OSError that is not
        # a FileNotFoundError, which is what used to take every other id in the call with it.
        manager = make_manager(tmp_path, {"tables/orders.md": ORDERS, "top.md": ORDERS_DB})

        assert ids(manager.browse("")) == ["tables/", "top.md"]
        assert ids(manager.fetch(["tables/", "top.md"])) == ["top.md"]

    def test_fetch_is_the_only_operation_carrying_the_full_body_and_links(self, tmp_path):
        manager = make_manager(tmp_path)
        record = manager.fetch(["tables/orders.md"])[0]
        assert record["metadata"]["links"] == ["tables/customers.md"]
        assert "# Schema" in record["text"]
        assert "links" not in manager.browse("datasets")[0]["metadata"]


class TestBrowse:
    def test_the_root_index_supplies_the_listing(self, tmp_path):
        records = make_manager(tmp_path).browse("")
        assert ids(records) == ["index.md"]
        assert records[0]["metadata"]["kind"] == "index"
        assert "# Root listing" in records[0]["text"]

    def test_a_nested_index_is_honoured_exactly_as_the_root_one_is(self, tmp_path):
        records = make_manager(tmp_path).browse("tables")
        assert ids(records) == ["tables/index.md"]
        assert "# Curated tables" in records[0]["text"]

    def test_a_directory_with_no_index_gets_a_derived_listing(self, tmp_path):
        assert ids(make_manager(tmp_path).browse("datasets")) == ["datasets/orders_db.md"]

    def test_a_derived_listing_carries_subdirectories_before_concepts(self, tmp_path):
        files = {"top.md": ORDERS_DB, "tables/orders.md": ORDERS, "datasets/orders_db.md": ORDERS_DB}
        records = make_manager(tmp_path, files).browse("")
        assert ids(records) == ["datasets/", "tables/", "top.md"]
        assert records[0]["metadata"]["kind"] == "directory"

    def test_limit_truncates_a_derived_listing(self, tmp_path):
        files = {"tables/orders.md": ORDERS, "tables/customers.md": CUSTOMERS}
        assert ids(make_manager(tmp_path, files).browse("tables", limit=1)) == ["tables/customers.md"]

    def test_a_curated_listing_is_never_truncated_by_limit(self, tmp_path):
        assert len(make_manager(tmp_path).browse("tables", limit=0)) == 1

    def test_an_unknown_directory_is_empty_rather_than_an_error(self, tmp_path):
        assert make_manager(tmp_path).browse("nowhere") == []

    def test_an_escaping_path_is_empty_rather_than_raised(self, tmp_path):
        assert make_manager(tmp_path).browse("../..") == []


class TestWrite:
    def test_a_supplied_id_is_honoured(self, tmp_path):
        manager = make_manager(tmp_path)
        manager.write([{"text": "body", "metadata": {"id": "tables/new.md", "type": "Note", "title": "New"}}])
        assert ids(manager.fetch(["tables/new.md"])) == ["tables/new.md"]

    def test_an_id_is_synthesised_when_the_tool_surface_cannot_supply_one(self, tmp_path):
        # write_kb's signature carries no id, so without synthesis this path is unreachable.
        manager = make_manager(tmp_path, write_prefix="drafts")
        manager.write([{"text": "body", "metadata": {"title": "Auto Named!"}}])
        written = ids(manager.browse("drafts"))
        assert len(written) == 1
        assert written[0].startswith("drafts/auto-named-")
        assert written[0].endswith(".md")

    def test_synthesis_falls_back_through_title_then_type_then_a_constant(self, tmp_path):
        manager = make_manager(tmp_path)
        manager.write([{"text": "a", "metadata": {"type": "Attested Computation"}}, {"text": "b", "metadata": {}}])
        written = ids(manager.browse("generated"))
        assert any(path.startswith("generated/attested-computation-") for path in written)
        assert any(path.startswith("generated/concept-") for path in written)

    def test_a_supplied_id_without_the_markdown_suffix_still_survives_the_next_walk(self, tmp_path):
        # The write-through makes any path visible immediately, so only a rewalk proves the
        # document is really in the bundle rather than an orphan the walk declines to read.
        manager = make_manager(tmp_path)
        manager.write([{"text": "body", "metadata": {"id": "notes/decision", "type": "Note"}}])

        assert ids(manager.fetch(["notes/decision.md"])) == ["notes/decision.md"]
        assert "notes/decision.md" in manager.reload().concepts

    def test_a_supplied_id_naming_a_reserved_file_is_refused(self, tmp_path):
        # index.md is a directory's curated listing, not a concept slot.
        manager = make_manager(tmp_path)
        with pytest.raises(KnowledgePathError, match="reserved OKF file"):
            manager.write([{"text": "x", "metadata": {"id": "tables/index.md"}}])

    def test_a_comma_in_a_supplied_id_is_refused(self, tmp_path):
        manager = make_manager(tmp_path)
        with pytest.raises(KnowledgePathError, match="may not contain"):
            manager.write([{"text": "x", "metadata": {"id": "tables/a,b.md"}}])

    def test_a_comma_bearing_path_already_in_the_bundle_is_skipped_by_the_walk(self, tmp_path):
        # The other end of the same rule: every id this backend hands out must round-trip
        # through the fetch tool's comma-separated list.
        manager = make_manager(tmp_path, {"a,b.md": ORDERS_DB, "fine.md": ORDERS_DB})
        assert ids(manager.browse("")) == ["fine.md"]
        assert any(d.code == DiagnosticCode.COMMA_IN_PATH.value for d in manager._ensure_manifest().diagnostics)

    def test_an_escaping_id_is_refused(self, tmp_path):
        with pytest.raises(KnowledgePathError, match="escapes the store namespace"):
            make_manager(tmp_path).write([{"text": "x", "metadata": {"id": "../escape.md"}}])

    def test_a_read_only_backend_refuses_before_any_io(self, tmp_path):
        store = LocalDocumentStore(write_bundle(tmp_path, BUNDLE), writable=False)
        with pytest.raises(KnowledgeCapabilityError, match="does not support capability: write"):
            OKFManager(store).write([{"text": "x", "metadata": {"id": "a.md"}}])

    def test_the_emitted_document_is_conformant_with_a_fixed_key_order(self, tmp_path):
        root = write_bundle(tmp_path, BUNDLE)
        manager = OKFManager(LocalDocumentStore(root, writable=True), producer="process:demo")
        metadata = {"id": "n.md", "type": "Note", "title": "T", "description": "D", "tags": ["x"], "status": "stable", "owner": "me"}
        manager.write([{"text": "Body.", "metadata": metadata}])

        document = (tmp_path / "n.md").read_text(encoding="utf-8")
        frontmatter = yaml.safe_load(document.split("---\n")[1])
        assert list(frontmatter) == ["type", "title", "description", "tags", "status", "generated", "owner"]
        assert document.endswith("---\n\nBody.")

    def test_a_missing_type_falls_back_to_note_because_type_is_the_conformance_bar(self, tmp_path):
        manager = make_manager(tmp_path)
        manager.write([{"text": "b", "metadata": {"id": "n.md", "title": "T"}}])
        assert manager.fetch(["n.md"])[0]["metadata"]["kind"] == "Note"

    def test_the_producer_is_stamped_and_defaults_to_the_installed_package(self, tmp_path):
        default = make_manager(tmp_path)
        default.write([{"text": "b", "metadata": {"id": "a.md"}}])
        stamped = yaml.safe_load((tmp_path / "a.md").read_text(encoding="utf-8").split("---\n")[1])
        assert stamped["generated"]["by"].startswith("agentkernel/")
        assert stamped["generated"]["at"].endswith("+00:00")

    def test_the_provenance_stamp_is_the_backends_to_make_not_the_callers(self, tmp_path):
        root = write_bundle(tmp_path, BUNDLE)
        manager = OKFManager(LocalDocumentStore(root, writable=True), producer="process:demo")
        manager.write([{"text": "x", "metadata": {"id": "g.md", "generated": {"by": "someone-else", "at": "1999-01-01"}}}])

        stamped = yaml.safe_load((tmp_path / "g.md").read_text(encoding="utf-8").split("---\n")[1])
        assert stamped["generated"]["by"] == "process:demo"
        assert stamped["generated"]["at"] != "1999-01-01"

    def test_a_caller_cannot_mint_its_own_trust_tier(self, tmp_path):
        # derive_trust reads `verified` and nothing else, so a writer able to supply it could
        # promote its own output to the tier a human reviewer is supposed to confer.
        manager = make_manager(tmp_path)
        manager.write([{"text": "x", "metadata": {"id": "v.md", "verified": [{"by": "human:nobody"}]}}])

        assert manager.fetch(["v.md"])[0]["metadata"]["trust"] == TrustTier.UNVERIFIED.value
        assert "verified" not in (tmp_path / "v.md").read_text(encoding="utf-8")

    def test_two_writes_of_the_same_content_differ_only_in_the_generated_stamp(self, tmp_path):
        manager = make_manager(tmp_path, producer="process:demo")
        record = {"text": "Body.", "metadata": {"id": "n.md", "type": "Note", "title": "T"}}
        manager.write([record])
        first = (tmp_path / "n.md").read_text(encoding="utf-8")
        manager.write([record])
        second = (tmp_path / "n.md").read_text(encoding="utf-8")

        def without_stamp(text: str) -> str:
            return "\n".join(line for line in text.splitlines() if "at:" not in line)

        assert without_stamp(first) == without_stamp(second)


class TestWriteThrough:
    def test_a_written_concept_is_visible_immediately_with_refresh_disabled(self, tmp_path):
        # refresh_seconds=None is the point: visibility can only come from the write itself.
        manager = make_manager(tmp_path, refresh_seconds=None)
        manager.write([{"text": "Body.", "metadata": {"id": "tables/new.md", "type": "Note", "title": "New"}}])

        assert ids(manager.fetch(["tables/new.md"])) == ["tables/new.md"]
        assert "tables/new.md" in ids(manager.browse("datasets") + manager.search("New", limit=10))
        assert manager._derived_schema()["concept_count"] == 4

    def test_a_write_replaces_the_manifest_entry_at_that_path(self, tmp_path):
        manager = make_manager(tmp_path, refresh_seconds=None)
        manager.write([{"text": "b", "metadata": {"id": "tables/orders.md", "type": "Note", "title": "Replaced"}}])
        assert manager.fetch(["tables/orders.md"])[0]["metadata"]["title"] == "Replaced"


class TestRefreshAndConcurrency:
    def test_the_manifest_is_not_rewalked_inside_the_interval(self, tmp_path, monkeypatch):
        clock = FakeClock()
        monkeypatch.setattr(manager_module, "time", clock)
        store = CountingStore(write_bundle(tmp_path, BUNDLE))
        manager = OKFManager(store, refresh_seconds=300)

        clock.advance(299)
        manager.search("orders")
        assert store.list_calls == 1

    def test_the_first_call_past_the_interval_pays_the_walk(self, tmp_path, monkeypatch):
        clock = FakeClock()
        monkeypatch.setattr(manager_module, "time", clock)
        store = CountingStore(write_bundle(tmp_path, BUNDLE))
        manager = OKFManager(store, refresh_seconds=300)

        clock.advance(301)
        manager.search("orders")
        assert store.list_calls == 2

    def test_refresh_none_never_rewalks(self, tmp_path, monkeypatch):
        clock = FakeClock()
        monkeypatch.setattr(manager_module, "time", clock)
        store = CountingStore(write_bundle(tmp_path, BUNDLE))
        manager = OKFManager(store, refresh_seconds=None)

        clock.advance(100_000)
        manager.search("orders")
        assert store.list_calls == 1

    def test_a_failed_refresh_serves_the_previous_manifest_and_resets_the_clock(self, tmp_path, monkeypatch):
        clock = FakeClock()
        monkeypatch.setattr(manager_module, "time", clock)
        store = CountingStore(write_bundle(tmp_path, BUNDLE), fail_after_first=True)
        manager = OKFManager(store, refresh_seconds=300)

        clock.advance(301)
        assert ids(manager.search("revenue")) == ["tables/orders.md"]
        assert store.list_calls == 2

        # The clock reset means an outage costs one attempt per interval, not one per call.
        manager.search("revenue")
        assert store.list_calls == 2

    def test_an_initial_load_failure_propagates_rather_than_serving_an_empty_bundle(self, tmp_path):
        store = CountingStore(write_bundle(tmp_path, BUNDLE), fail_after_first=True)
        store.list_calls = 1  # the next call is the "second" and therefore fails
        with pytest.raises(OSError, match="store is unavailable"):
            OKFManager(store)

    def test_reload_forces_a_walk_regardless_of_the_interval(self, tmp_path):
        store = CountingStore(write_bundle(tmp_path, BUNDLE))
        manager = OKFManager(store, refresh_seconds=None)
        manager.reload()
        assert store.list_calls == 2

    def test_two_concurrent_callers_crossing_the_boundary_produce_one_walk(self, tmp_path, monkeypatch):
        clock = FakeClock()
        monkeypatch.setattr(manager_module, "time", clock)
        store = CountingStore(write_bundle(tmp_path, BUNDLE), walk_delay=0.3)
        manager = OKFManager(store, refresh_seconds=300)
        clock.advance(301)

        barrier = threading.Barrier(2)

        def call() -> None:
            barrier.wait(timeout=5)
            manager.search("orders")

        threads = [threading.Thread(target=call) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=10)

        # The loser is served the current manifest rather than blocking on the winner's walk.
        assert store.list_calls == 2


class TestTruncation:
    def test_max_concepts_keeps_a_lexicographic_prefix_and_says_so(self, tmp_path):
        files = {f"c{index:02d}.md": ORDERS_DB for index in range(6)}
        manager = make_manager(tmp_path, files, max_concepts=3)
        manifest = manager._ensure_manifest()

        assert sorted(manifest.concepts) == ["c00.md", "c01.md", "c02.md"]
        assert manifest.truncated is True
        assert any(d.code == DiagnosticCode.TRUNCATED.value for d in manifest.diagnostics)
        assert manager._derived_schema()["truncated"] is True

    def test_truncation_drops_concepts_without_abandoning_later_reserved_files(self, tmp_path):
        # store.list() is globally lexicographic, so a bundle whose concepts live under `aaa/`
        # hits the cap before the root index.md, which a `break` would never read.
        files = {"aaa/c00.md": ORDERS_DB, "aaa/c01.md": CUSTOMERS, "index.md": BUNDLE["index.md"]}
        manager = make_manager(tmp_path, files, max_concepts=1)
        manifest = manager._ensure_manifest()

        assert manifest.truncated is True
        assert manifest.okf_version == "0.2"
        assert manifest.index_files == {"": "index.md"}
        assert ids(manager.browse("")) == ["index.md"]
        # One diagnostic for the bundle, not one per concept past the cap.
        assert len([d for d in manifest.diagnostics if d.code == DiagnosticCode.TRUNCATED.value]) == 1

    def test_a_skipped_file_does_not_consume_the_budget(self, tmp_path):
        files = {"a.md": "no frontmatter\n", "b.md": ORDERS_DB, "c.md": CUSTOMERS}
        manifest = make_manager(tmp_path, files, max_concepts=2)._ensure_manifest()
        assert sorted(manifest.concepts) == ["b.md", "c.md"]
        assert manifest.truncated is False


class TestTrustAndStaleness:
    STALE_BUNDLE = {
        "one.md": "---\ntype: Note\ntitle: Alpha\nstale_after: 2000-01-01T00:00:00Z\n---\nalpha body\n",
        "two.md": "---\ntype: Note\ntitle: Alpha Two\nstale_after: 2000-01-01T00:00:00Z\n---\nalpha body\n",
    }

    def test_a_wholly_stale_unverified_bundle_still_answers_every_operation(self, tmp_path):
        manager = make_manager(tmp_path, self.STALE_BUNDLE)
        assert ids(manager.search("alpha", limit=10)) == ["one.md", "two.md"]
        assert ids(manager.browse("")) == ["one.md", "two.md"]
        assert ids(manager.fetch(["one.md", "two.md"])) == ["one.md", "two.md"]

    def test_the_signals_ride_on_the_records_instead(self, tmp_path):
        metadata = make_manager(tmp_path, self.STALE_BUNDLE).search("alpha")[0]["metadata"]
        assert metadata["stale"] is True
        assert metadata["trust"] == TrustTier.UNVERIFIED.value


class TestDescriptionAndFormatting:
    def test_diagnostics_are_surfaced_in_the_description_not_swallowed(self, tmp_path):
        description = make_manager(tmp_path).get_description()
        assert description.startswith("okf: Open Knowledge Format bundle")
        assert "bundle diagnostic(s); first:" in description

    def test_a_clean_bundle_describes_itself_plainly(self, tmp_path):
        assert make_manager(tmp_path, {"a.md": ORDERS_DB}).get_description() == "okf: Open Knowledge Format bundle"

    def test_format_results_carries_the_text_and_the_routing_signals(self, tmp_path):
        manager = make_manager(tmp_path)
        rendered = manager.format_results(manager.search("revenue"))
        assert rendered == "- [tables/orders.md] Orders — BigQuery Table · trust=human-reviewed: One row per completed purchase."

    def test_a_fetched_body_reaches_the_prompt_verbatim(self, tmp_path):
        manager = make_manager(tmp_path)
        rendered = manager.format_results(manager.fetch(["tables/orders.md"]))
        header, _, body = rendered.partition("\n")
        assert header == "- [tables/orders.md] Orders — BigQuery Table · trust=human-reviewed"
        assert body == "# Schema\nFK to [customers](/tables/customers.md)."

    def test_a_record_with_no_type_or_tier_renders_no_empty_signals(self, tmp_path):
        manager = make_manager(tmp_path)
        rendered = manager.format_results(manager.browse("datasets"))
        assert rendered == "- [datasets/orders_db.md] Orders DB — Dataset · trust=unverified"

    def test_a_stale_record_is_marked(self, tmp_path):
        manager = make_manager(tmp_path, TestTrustAndStaleness.STALE_BUNDLE)
        assert manager.format_results(manager.search("alpha", limit=1)).endswith("· STALE")

    def test_an_empty_result_says_so(self, tmp_path):
        assert make_manager(tmp_path).format_results([]) == "No relevant knowledge found."


class TestStoreComposition:
    def test_close_delegates_to_the_store_and_tolerates_repeat_calls(self, tmp_path):
        closed = []
        store = LocalDocumentStore(write_bundle(tmp_path, BUNDLE), writable=True)
        store.close = lambda: closed.append(1)

        manager = OKFManager(store)
        manager.close()
        manager.close()
        assert closed == [1, 1]

    def test_the_store_is_reachable_for_a_caller_that_needs_it(self, tmp_path):
        manager = make_manager(tmp_path)
        assert manager.store.exists("tables/orders.md") is True
