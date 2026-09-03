"""OKF parsing — the representation axis (#553 iteration 5).

The guarantee under test is tolerance. OKF's conformance rules are almost entirely
obligations on the *consumer*: carry unknown keys, keep an unknown ``type``, treat a bare
``verified`` mapping as a list, tolerate broken links. Read together they mean a strict OKF
reader is a non-conformant one, so these tests pin the shape of every degradation — what is
skipped (three conditions, no more), what is carried, and which diagnostic says so.

Two further guarantees have consequences beyond this module. Tokenisation is asserted here
because the same function indexes concepts and splits queries, which is what makes search
ranking reproducible across pods. And the isolation test fails if this package ever gains a
store or a network import, because that separation is what lets one reader serve a local
directory and an S3 prefix unchanged.
"""

import json
import subprocess
import sys
from datetime import datetime, timezone

import pytest

from agentkernel.knowledgebase.okf.model import DiagnosticCode, OKFConcept, TrustTier
from agentkernel.knowledgebase.okf.parser import (
    OKF_VERSION,
    derive_trust,
    extract_links,
    is_reserved,
    is_stale,
    parse_concept,
    parse_index,
    split_frontmatter,
    tokenise,
)

NOW = datetime(2026, 6, 1, tzinfo=timezone.utc)


def document(frontmatter: str, body: str = "body text") -> str:
    """Build a document from a frontmatter block and a body."""
    return f"---\n{frontmatter}\n---\n{body}"


def codes(diagnostics) -> list[str]:
    """Reduce diagnostics to their codes, which is what most assertions are about."""
    return [diagnostic.code for diagnostic in diagnostics]


class TestSplitFrontmatter:
    def test_a_well_formed_document_splits_into_block_and_body(self):
        frontmatter, body = split_frontmatter("---\ntype: Table\n---\n# Schema\nrows\n")
        assert frontmatter == "type: Table\n"
        assert body == "# Schema\nrows\n"

    def test_carriage_returns_do_not_hide_the_delimiters(self):
        frontmatter, body = split_frontmatter("---\r\ntype: Table\r\n---\r\nbody\r\n")
        assert frontmatter == "type: Table\r\n"
        assert body == "body\r\n"

    @pytest.mark.parametrize(
        "data",
        [
            "type: Table\n---\nbody\n",  # no opening delimiter
            "---\ntype: Table\nbody with no close\n",  # no closing delimiter
            "  ---\ntype: Table\n---\nbody\n",  # the delimiter is not on its own first line
            "",
        ],
    )
    def test_an_incomplete_block_yields_no_frontmatter_and_the_input_body(self, data):
        frontmatter, body = split_frontmatter(data)
        assert frontmatter is None
        assert body == data

    def test_a_delimiter_inside_the_body_does_not_reopen_the_block(self):
        frontmatter, body = split_frontmatter("---\ntype: Table\n---\nbefore\n---\nafter\n")
        assert frontmatter == "type: Table\n"
        assert body == "before\n---\nafter\n"


class TestParseConceptSkips:
    """The three — and only three — conditions that skip a concept."""

    def test_a_comma_in_the_path_is_refused_because_fetch_ids_split_on_it(self):
        concept, diagnostics = parse_concept("tables/a,b.md", document("type: Table"), body_complete=True)
        assert concept is None
        assert codes(diagnostics) == [DiagnosticCode.COMMA_IN_PATH.value]

    def test_a_document_with_no_frontmatter_block_is_skipped(self):
        concept, diagnostics = parse_concept("a.md", "# Just a heading\n", body_complete=True)
        assert concept is None
        assert codes(diagnostics) == [DiagnosticCode.UNPARSEABLE_FRONTMATTER.value]

    def test_frontmatter_that_is_not_valid_yaml_is_skipped(self):
        concept, diagnostics = parse_concept("a.md", document("type: [unclosed"), body_complete=True)
        assert concept is None
        assert codes(diagnostics) == [DiagnosticCode.UNPARSEABLE_FRONTMATTER.value]

    @pytest.mark.parametrize("frontmatter", ["- a\n- b", "just a string", ""])
    def test_frontmatter_that_is_not_a_mapping_is_skipped(self, frontmatter):
        concept, diagnostics = parse_concept("a.md", document(frontmatter), body_complete=True)
        assert concept is None
        assert codes(diagnostics) == [DiagnosticCode.UNPARSEABLE_FRONTMATTER.value]

    @pytest.mark.parametrize("frontmatter", ["title: No type here", "type:", "type: '   '", "type: 42"])
    def test_type_is_the_one_required_key(self, frontmatter):
        concept, diagnostics = parse_concept("a.md", document(frontmatter), body_complete=True)
        assert concept is None
        assert codes(diagnostics) == [DiagnosticCode.MISSING_TYPE.value]


class TestParseConceptTolerance:
    def test_an_unknown_type_value_is_kept_verbatim(self):
        concept, diagnostics = parse_concept("a.md", document("type: Some Future Kind"), body_complete=True)
        assert concept.type == "Some Future Kind"
        assert diagnostics == []

    def test_unknown_keys_land_in_extra_untouched(self):
        concept, diagnostics = parse_concept("a.md", document("type: Table\nowner: analytics\nreview: {every: 30d}"), body_complete=True)
        assert concept.extra == {"owner": "analytics", "review": {"every": "30d"}}
        assert diagnostics == []

    def test_the_computation_family_collapses_into_computation_and_not_into_extra(self):
        frontmatter = "type: Attested Computation\nruntime: python3.12\nparameters: {n: 1}\ncomputation: ./calc.py\nexecutor: e\nattester: a"
        concept, _ = parse_concept("a.md", document(frontmatter), body_complete=True)
        assert concept.computation == {"runtime": "python3.12", "parameters": {"n": 1}, "computation": "./calc.py", "executor": "e", "attester": "a"}
        assert concept.extra == {}

    def test_missing_optional_fields_take_defaults_with_no_diagnostic(self):
        concept, diagnostics = parse_concept("a.md", document("type: Table"), body_complete=True)
        assert (concept.title, concept.description, concept.resource, concept.status) == (None, None, None, None)
        assert (concept.tags, concept.verified, concept.sources, concept.generated) == ([], [], [], {})
        assert diagnostics == []

    def test_a_bare_verified_mapping_becomes_a_one_element_list(self):
        concept, diagnostics = parse_concept("a.md", document('type: Table\nverified: {by: "human:jsmith", at: 2026-01-01}'), body_complete=True)
        assert len(concept.verified) == 1
        assert concept.verified[0]["by"] == "human:jsmith"
        assert codes(diagnostics) == [DiagnosticCode.COERCED_SCALAR.value]

    def test_a_scalar_tags_value_becomes_a_one_element_list(self):
        concept, diagnostics = parse_concept("a.md", document("type: Table\ntags: sales"), body_complete=True)
        assert concept.tags == ["sales"]
        assert codes(diagnostics) == [DiagnosticCode.COERCED_SCALAR.value]

    def test_a_non_string_tag_is_stringified(self):
        concept, diagnostics = parse_concept("a.md", document("type: Table\ntags: [sales, 2026]"), body_complete=True)
        assert concept.tags == ["sales", "2026"]
        assert codes(diagnostics) == [DiagnosticCode.COERCED_SCALAR.value]

    def test_a_yaml_resolved_scalar_in_a_text_field_is_carried_as_text(self):
        # An unquoted timestamp or number arrives from safe_load as a datetime or an int;
        # stringifying carries the value where rejecting it would lose the concept.
        concept, _ = parse_concept("a.md", document("type: Table\ntitle: 2026\nstale_after: 2026-12-01T00:00:00Z"), body_complete=True)
        assert concept.title == "2026"
        assert concept.stale_after.startswith("2026-12-01")

    def test_the_path_is_the_identity(self):
        concept, _ = parse_concept("tables/orders.md", document("type: Table"), body_complete=True)
        assert concept.path == "tables/orders.md"


class TestVersionZeroTwoOnly:
    """The two v0.1 fallbacks are MAY, so declining them is conformant — and asserted."""

    def test_a_legacy_timestamp_lands_in_extra_and_never_on_generated(self):
        concept, _ = parse_concept("a.md", document("type: Table\ntimestamp: 2025-01-01T00:00:00Z"), body_complete=True)
        assert "timestamp" in concept.extra
        assert concept.generated == {}

    def test_a_body_citations_list_stays_ordinary_body_text(self):
        body = "# Schema\n\n# Citations\n- [bq_meta] BigQuery INFORMATION_SCHEMA\n"
        concept, _ = parse_concept("a.md", document("type: Table", body), body_complete=True)
        assert concept.sources == []
        assert "# Citations" in concept.body


class TestBodyHandling:
    def test_a_complete_body_is_retained_with_its_links(self):
        concept, _ = parse_concept("tables/orders.md", document("type: Table", "see [c](./customers.md)"), body_complete=True)
        assert concept.body == "see [c](./customers.md)"
        assert concept.links == ["tables/customers.md"]

    def test_a_bounded_prefix_keeps_tokens_but_neither_body_nor_links(self):
        # The walk reads a prefix, so a link set built from it would be truncated and a
        # retained body would blow the manifest envelope. fetch re-reads for both.
        concept, _ = parse_concept("tables/orders.md", document("type: Table", "see [c](./customers.md)"), body_complete=False)
        assert concept.body is None
        assert concept.links == []
        assert "customers" in concept.body_tokens


class TestTokenise:
    def test_tokens_are_lowercased_split_on_non_alphanumerics_and_at_least_two_characters(self):
        assert tokenise("Orders_2026: a per-customer TABLE!") == {"orders", "2026", "per", "customer", "table"}

    def test_empty_text_yields_no_tokens(self):
        assert tokenise("") == set()


class TestTrust:
    def test_no_verified_entries_is_unverified(self):
        assert derive_trust([]) is TrustTier.UNVERIFIED

    def test_an_agent_actor_is_machine_confirmed(self):
        assert derive_trust([{"by": "reference_agent/gemini-2.5-pro"}]) is TrustTier.MACHINE_CONFIRMED

    def test_one_human_actor_among_agents_is_human_reviewed(self):
        assert derive_trust([{"by": "process:nightly"}, {"by": "human:jsmith"}]) is TrustTier.HUMAN_REVIEWED

    def test_a_malformed_entry_does_not_upgrade_the_tier(self):
        assert derive_trust([{"at": "2026-01-01"}]) is TrustTier.MACHINE_CONFIRMED

    def test_nothing_but_verified_feeds_the_tier(self):
        concept, _ = parse_concept("a.md", document("type: Table\ngenerated: {by: agent/1}\nstatus: stable"), body_complete=True)
        assert concept.trust is TrustTier.UNVERIFIED


class TestStaleness:
    def test_no_deadline_is_never_stale(self):
        assert is_stale(None, NOW) == (False, [])

    def test_a_deadline_in_the_future_is_not_stale(self):
        assert is_stale("2026-12-01T00:00:00Z", NOW) == (False, [])

    def test_a_deadline_in_the_past_is_stale(self):
        stale, diagnostics = is_stale("2026-01-01T00:00:00Z", NOW)
        assert (stale, diagnostics) == (True, [])

    def test_a_naive_deadline_is_read_as_utc(self):
        assert is_stale("2026-01-01T00:00:00", NOW)[0] is True

    def test_an_unparseable_deadline_is_reported_and_never_assumed_stale(self):
        stale, diagnostics = is_stale("next tuesday", NOW)
        assert stale is False
        assert codes(diagnostics) == [DiagnosticCode.UNPARSEABLE_STALE_AFTER.value]

    def test_the_concept_path_is_stamped_onto_a_staleness_diagnostic(self):
        # is_stale has no path in its signature, so parse_concept re-stamps what it emits.
        _, diagnostics = parse_concept("tables/orders.md", document("type: Table\nstale_after: soon"), body_complete=True)
        assert [(d.code, d.path) for d in diagnostics] == [(DiagnosticCode.UNPARSEABLE_STALE_AFTER.value, "tables/orders.md")]

    def test_staleness_rides_on_the_concept_and_filters_nothing(self):
        concept, _ = parse_concept("a.md", document("type: Table\nstale_after: 2026-01-01T00:00:00Z"), body_complete=True, now=NOW)
        assert isinstance(concept, OKFConcept)
        assert concept.stale is True


class TestExtractLinks:
    @pytest.mark.parametrize(
        "target,expected",
        [
            ("/tables/customers.md", "tables/customers.md"),  # bundle-absolute
            ("./customers.md", "tables/customers.md"),  # relative to the concept's directory
            ("customers.md", "tables/customers.md"),  # bare relative
            ("../datasets/orders_db.md", "datasets/orders_db.md"),  # up one level, still inside
        ],
    )
    def test_both_specified_link_forms_resolve_bundle_relative(self, target, expected):
        links, diagnostics = extract_links("tables/orders.md", f"see [x]({target})")
        assert links == [expected]
        assert diagnostics == []

    def test_a_link_escaping_the_bundle_is_dropped_with_a_diagnostic(self):
        links, diagnostics = extract_links("tables/orders.md", "see [x](../../secrets.md)")
        assert links == []
        assert codes(diagnostics) == [DiagnosticCode.PATH_ESCAPE.value]

    @pytest.mark.parametrize("target", ["https://example.com/x.md", "mailto:a@b.md", "./notes.txt", "#section"])
    def test_targets_that_are_not_bundle_documents_are_ignored(self, target):
        assert extract_links("tables/orders.md", f"see [x]({target})") == ([], [])

    def test_a_broken_but_contained_link_is_kept_because_nothing_is_resolved_at_parse_time(self):
        links, diagnostics = extract_links("tables/orders.md", "see [gone](./missing.md)")
        assert links == ["tables/missing.md"]
        assert diagnostics == []

    def test_repeated_links_yield_one_entry_in_first_occurrence_order(self):
        body = "[b](./b.md) [a](./a.md) [b again](./b.md)"
        assert extract_links("tables/orders.md", body)[0] == ["tables/b.md", "tables/a.md"]

    def test_a_root_level_concept_resolves_relative_links_against_the_bundle_root(self):
        assert extract_links("orders.md", "[x](./customers.md)")[0] == ["customers.md"]


class TestReservedFiles:
    @pytest.mark.parametrize("path", ["index.md", "log.md", "tables/index.md", "a/b/log.md", "tables/Index.md"])
    def test_both_names_are_reserved_at_every_level(self, path):
        assert is_reserved(path) is True

    @pytest.mark.parametrize("path", ["orders.md", "tables/orders.md", "indexes.md", "tables/index.markdown"])
    def test_an_ordinary_concept_is_not_reserved(self, path):
        assert is_reserved(path) is False

    def test_an_index_with_no_frontmatter_is_all_body(self):
        body, version, diagnostics = parse_index("index.md", "# Sales\n- [orders](/tables/orders.md)\n", is_root=True)
        assert body == "# Sales\n- [orders](/tables/orders.md)\n"
        assert (version, diagnostics) == (None, [])

    def test_the_root_index_may_declare_the_version(self):
        body, version, diagnostics = parse_index("index.md", document(f'okf_version: "{OKF_VERSION}"', "# Sales\n"), is_root=True)
        assert (body, version, diagnostics) == ("# Sales\n", OKF_VERSION, [])

    def test_other_keys_in_the_root_index_are_unrecognised_content_not_an_error(self):
        _, version, diagnostics = parse_index("index.md", document("curator: analytics"), is_root=True)
        assert (version, diagnostics) == (None, [])

    def test_a_version_this_reader_does_not_target_is_reported_and_the_bundle_still_loads(self):
        body, version, diagnostics = parse_index("index.md", document('okf_version: "0.1"', "# Sales\n"), is_root=True)
        assert (body, version) == ("# Sales\n", "0.1")
        assert codes(diagnostics) == [DiagnosticCode.VERSION_MISMATCH.value]

    def test_a_non_root_index_carrying_frontmatter_is_reported_and_its_body_still_used(self):
        body, version, diagnostics = parse_index("tables/index.md", document("okf_version: '0.2'", "# Tables\n"), is_root=False)
        assert (body, version) == ("# Tables\n", None)
        assert codes(diagnostics) == [DiagnosticCode.INDEX_FRONTMATTER.value]

    def test_unparseable_index_frontmatter_still_serves_the_listing(self):
        body, version, diagnostics = parse_index("index.md", document("okf_version: [unclosed", "# Sales\n"), is_root=True)
        assert (body, version) == ("# Sales\n", None)
        assert codes(diagnostics) == [DiagnosticCode.UNPARSEABLE_FRONTMATTER.value]


class TestDiagnosticCoverage:
    # truncated and unreadable belong to the manifest walk (OKFManager), not the parser.
    PARSER_REACHABLE = {
        DiagnosticCode.UNPARSEABLE_FRONTMATTER,
        DiagnosticCode.MISSING_TYPE,
        DiagnosticCode.COMMA_IN_PATH,
        DiagnosticCode.PATH_ESCAPE,
        DiagnosticCode.VERSION_MISMATCH,
        DiagnosticCode.INDEX_FRONTMATTER,
        DiagnosticCode.UNPARSEABLE_STALE_AFTER,
        DiagnosticCode.COERCED_SCALAR,
    }

    def test_every_parser_reachable_code_is_actually_emitted(self):
        emitted = set()
        for path, data in [("a,b.md", document("type: Table")), ("a.md", "no block"), ("a.md", document("title: x"))]:
            emitted.update(codes(parse_concept(path, data, body_complete=True)[1]))
        emitted.update(codes(parse_concept("a.md", document("type: T\ntags: x\nstale_after: soon", "[e](../../x.md)"), body_complete=True)[1]))
        emitted.update(codes(parse_index("index.md", document("okf_version: '0.1'"), is_root=True)[2]))
        emitted.update(codes(parse_index("t/index.md", document("a: b"), is_root=False)[2]))

        assert emitted == {code.value for code in self.PARSER_REACHABLE}

    def test_the_manager_only_codes_are_defined_but_unreached_here(self):
        assert {DiagnosticCode.TRUNCATED, DiagnosticCode.UNREADABLE} & self.PARSER_REACHABLE == set()


class TestIsolation:
    def test_the_package_pulls_in_neither_the_network_nor_the_storage_axis(self):
        # A subprocess, not sys.modules in-process: under pytest these are already imported
        # by unrelated machinery, so an in-process assertion would pass vacuously. The
        # network check is a delta because ``agentkernel`` itself imports urllib.request at
        # its root — what must hold is that okf/ adds nothing; the storage axis is checked
        # absolutely, since nothing else in the import chain reaches it.
        script = (
            "import json, sys;"
            " import agentkernel;"
            " before = set(sys.modules);"
            " import agentkernel.knowledgebase.okf;"
            " added = set(sys.modules) - before;"
            " print(json.dumps({"
            "  'network': sorted(n for n in added if n.split('.')[0] in ('urllib', 'httpx', 'http', 'socket')),"
            "  'store': 'agentkernel.knowledgebase.store' in sys.modules,"
            " }))"
        )
        result = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True, check=True)
        reached = json.loads(result.stdout.strip().splitlines()[-1])
        assert reached == {"network": [], "store": False}
