"""Capability declaration and error types of the knowledge-base tier (#553 iteration 1).

KnowledgeCapabilities is what every backend declares and what KnowledgeBase routes on, so
the defaults and the exact field set are pinned here — a backend that forgets a field must
get the conservative answer (False), and a field added later must fail this file loudly.

The deliberate absence of cross-field validation is also pinned: the reachability and
query/query_language invariants belong to KnowledgeBase.validate_capabilities, called by
KnowledgeBase.__init__ because only it knows the backend name — so an incoherent declaration
must still *construct*, and be refused one layer up. Both halves are pinned here.
"""

import pytest
from pydantic import ValidationError

from agentkernel.knowledgebase.base import KnowledgeBase
from agentkernel.knowledgebase.errors import KnowledgeCapabilityError, KnowledgeError, KnowledgePathError
from agentkernel.knowledgebase.model import KnowledgeCapabilities, KnowledgeMetadata, KnowledgeRecord

CAPABILITY_FIELDS = {
    "kinds",
    "search",
    "search_mode",
    "query",
    "query_language",
    "fetch",
    "browse",
    "writable",
    "derives_schema",
}


class TestKnowledgeCapabilities:
    def test_every_operation_defaults_to_unsupported(self):
        caps = KnowledgeCapabilities()
        assert caps.search is False
        assert caps.query is False
        assert caps.fetch is False
        assert caps.browse is False
        assert caps.writable is False
        assert caps.derives_schema is False

    def test_advisory_fields_default_to_unstated(self):
        caps = KnowledgeCapabilities()
        assert caps.kinds == []
        assert caps.search_mode is None
        assert caps.query_language is None

    def test_model_dump_carries_exactly_the_declared_fields(self):
        # Asserting the key set, not a subset, so adding a capability fails here first.
        assert set(KnowledgeCapabilities().model_dump()) == CAPABILITY_FIELDS

    def test_kinds_is_not_shared_between_instances(self):
        first = KnowledgeCapabilities()
        second = KnowledgeCapabilities()
        first.kinds.append("vector")
        assert second.kinds == []

    def test_kinds_is_an_open_taxonomy(self):
        caps = KnowledgeCapabilities(kinds=["vector", "graph", "something-new"])
        assert caps.kinds == ["vector", "graph", "something-new"]

    def test_unknown_search_mode_is_rejected(self):
        with pytest.raises(ValidationError):
            KnowledgeCapabilities(search=True, search_mode="hybrid")


class TestCapabilitiesAreNotValidatedAtModelLevel:
    """Incoherent declarations must construct; KnowledgeBase.__init__ is what refuses them."""

    def test_query_without_a_query_language_constructs(self):
        assert KnowledgeCapabilities(query=True).query_language is None

    def test_query_language_without_query_constructs(self):
        assert KnowledgeCapabilities(query_language="sql").query is False

    def test_a_wholly_unreachable_declaration_constructs(self):
        caps = KnowledgeCapabilities()
        assert not any([caps.search, caps.query, caps.fetch, caps.browse])

    def test_search_without_a_search_mode_is_legal(self):
        # search_mode is advisory metadata, not bidirectional with search, unlike query_language.
        caps = KnowledgeCapabilities(search=True)
        assert caps.search is True
        assert caps.search_mode is None


class TestRecordTypedDicts:
    """The record types are documentation; nothing validates them at runtime."""

    def test_every_metadata_key_is_optional(self):
        assert KnowledgeMetadata.__total__ is False
        assert KnowledgeMetadata.__optional_keys__ == frozenset({"id", "source", "title", "kind", "trust", "stale", "links"})
        assert KnowledgeMetadata.__required_keys__ == frozenset()

    def test_every_record_key_is_optional(self):
        assert KnowledgeRecord.__total__ is False
        assert KnowledgeRecord.__optional_keys__ == frozenset({"text", "metadata"})
        assert KnowledgeRecord.__required_keys__ == frozenset()

    def test_backend_specific_keys_are_not_rejected(self):
        record = KnowledgeRecord(text="hello", distance=0.42)
        assert record == {"text": "hello", "distance": 0.42}


class TestKnowledgeErrors:
    def test_every_error_shares_one_base(self):
        assert issubclass(KnowledgeCapabilityError, KnowledgeError)
        assert issubclass(KnowledgePathError, KnowledgeError)
        assert issubclass(KnowledgeError, Exception)

    def test_capability_error_is_not_a_not_implemented_error(self):
        # A declaration mismatch must stay distinguishable from an unimplemented abstract method.
        assert not issubclass(KnowledgeCapabilityError, NotImplementedError)

    def test_capability_error_names_subject_and_operation(self):
        error = KnowledgeCapabilityError("starburst", "write")
        assert str(error) == "starburst does not support capability: write"
        assert error.subject == "starburst"
        assert error.capability == "write"

    def test_capability_error_without_a_subject(self):
        error = KnowledgeCapabilityError("browse")
        assert str(error) == "unsupported capability: browse"
        assert error.subject is None
        assert error.capability == "browse"

    def test_capability_error_without_arguments(self):
        error = KnowledgeCapabilityError()
        assert str(error) == ""
        assert error.subject is None
        assert error.capability == ""


class TestValidateCapabilities:
    """The invariants KnowledgeBase.__init__ enforces on a declaration.

    Static, so it is exercised straight off the class — no backend needed.
    """

    def test_a_reachable_declaration_passes(self):
        KnowledgeBase.validate_capabilities(KnowledgeCapabilities(search=True), "chromadb")

    def test_writable_alone_is_reachable(self):
        # A write-only sink is a legitimate backend, so writable counts toward reachability.
        KnowledgeBase.validate_capabilities(KnowledgeCapabilities(writable=True), "sink")

    def test_a_declaration_with_no_capability_is_rejected(self):
        with pytest.raises(ValueError, match="declares no capability"):
            KnowledgeBase.validate_capabilities(KnowledgeCapabilities(), "empty")

    def test_query_without_a_query_language_is_rejected(self):
        with pytest.raises(ValueError, match="declares query=True without a query_language"):
            KnowledgeBase.validate_capabilities(KnowledgeCapabilities(query=True), "neo4j")

    def test_query_language_without_query_is_rejected(self):
        with pytest.raises(ValueError, match="declares query_language 'sql' without query=True"):
            KnowledgeBase.validate_capabilities(KnowledgeCapabilities(search=True, query_language="sql"), "starburst")

    def test_a_blank_query_language_does_not_satisfy_query(self):
        with pytest.raises(ValueError, match="without a query_language"):
            KnowledgeBase.validate_capabilities(KnowledgeCapabilities(query=True, query_language="   "), "neo4j")

    def test_a_blank_query_language_does_not_trip_the_reverse_check(self):
        KnowledgeBase.validate_capabilities(KnowledgeCapabilities(search=True, query_language="   "), "chromadb")

    def test_unreachability_is_reported_before_query_incoherence(self):
        # Wrong in both ways at once: the caller should hear the more fundamental problem.
        with pytest.raises(ValueError, match="declares no capability"):
            KnowledgeBase.validate_capabilities(KnowledgeCapabilities(query_language="sql"), "broken")

    def test_every_message_names_the_given_subject(self):
        with pytest.raises(ValueError, match="'my-backend'"):
            KnowledgeBase.validate_capabilities(KnowledgeCapabilities(), "my-backend")
        with pytest.raises(ValueError, match="'my-backend'"):
            KnowledgeBase.validate_capabilities(KnowledgeCapabilities(query=True), "my-backend")
        with pytest.raises(ValueError, match="'my-backend'"):
            KnowledgeBase.validate_capabilities(KnowledgeCapabilities(search=True, query_language="sql"), "my-backend")
