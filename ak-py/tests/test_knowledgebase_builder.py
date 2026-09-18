"""Capability-gated agent tools on KnowledgeBuilder (#553 iteration 3).

This is the riskiest consumer of the capability model: everything here is prompt-visible,
so a wrong gate silently changes what every agent in a deployment can see. What is pinned
is the gating matrix over the registered set, the tool order (stable across runs so prompt
caches stay warm), the mis-routing strings that must never become exceptions inside a
framework, and write_kb's move off the Neo4j-specific cypher_* metadata keys.

read_kb's routing between query() and search() is pinned here too. It was a concrete read()
on the ABC until #553's amendment moved it into the tool body, and it is the rule that lets
one tool serve every backend, so it is worth its own test class.

Backends are declared inline; the reusable FakeKnowledgeBase lands with KnowledgeBaseContract.
"""

import json
import logging
from typing import Iterable, List

import pytest

from agentkernel.knowledgebase.base import KnowledgeBase, Record
from agentkernel.knowledgebase.knowledgebuilder import KnowledgeBuilder
from agentkernel.knowledgebase.model import KnowledgeCapabilities

BASE_TOOLS = ["get_schemas", "read_kb", "write_kb", "get_all_kb_descriptions"]


class MinimalStub(KnowledgeBase):
    """Implements only the three members that stayed abstract, so any operation raises."""

    def __init__(self, capabilities: KnowledgeCapabilities, name: str = "stub") -> None:
        super().__init__(capabilities=capabilities, name=name)
        self.name = name
        self.calls: list[tuple[str, tuple, dict]] = []
        self.written: list[Record] = []

    @property
    def backend_name(self) -> str:
        return self.name

    def connect(self, **kwargs) -> None:
        pass

    def get_description(self) -> str:
        return f"{self.name}: a stub backend"


class StubBackend(MinimalStub):
    """Records which operation was reached and with what, so routing is observable."""

    def search(self, query: str, limit: int = 3, **kwargs) -> List[Record]:
        self.calls.append(("search", (query, limit), kwargs))
        return [{"text": f"search:{query}", "metadata": {"source": self.name}}]

    def query(self, statement: str, limit: int = 3, **kwargs) -> List[Record]:
        self.calls.append(("query", (statement, limit), kwargs))
        return [{"text": f"query:{statement}", "metadata": {"source": self.name}}]

    def fetch(self, ids: List[str], **kwargs) -> List[Record]:
        self.calls.append(("fetch", (list(ids),), kwargs))
        return [{"text": f"fetch:{identity}", "metadata": {"source": self.name}} for identity in ids]

    def browse(self, path: str = "", limit: int = 50, **kwargs) -> List[Record]:
        self.calls.append(("browse", (path, limit), kwargs))
        return [{"text": f"browse:{path}", "metadata": {"source": self.name}}]

    def write(self, records: Iterable[Record], **kwargs) -> None:
        self.written.extend(records)


class NoCapabilitiesBackend(KnowledgeBase):
    """A backend whose __init__ never calls super().__init__(), so it has no declaration."""

    def __init__(self, name: str = "undeclared") -> None:
        self.name = name

    @property
    def backend_name(self) -> str:
        return self.name

    def connect(self, **kwargs) -> None:
        pass

    def get_description(self) -> str:
        return f"{self.name}: never declared anything"


def _vector(name: str = "vector") -> StubBackend:
    """The ChromaManager shape."""
    return StubBackend(KnowledgeCapabilities(kinds=["vector"], search=True, search_mode="semantic", writable=True), name=name)


def _sql(name: str = "sql") -> StubBackend:
    """The StarburstManager shape."""
    return StubBackend(KnowledgeCapabilities(kinds=["structured"], query=True, query_language="sql"), name=name)


def _documents(name: str = "okf") -> StubBackend:
    """The OKFManager shape: relevance, identity, and enumeration over documents."""
    return StubBackend(KnowledgeCapabilities(kinds=["document"], search=True, fetch=True, browse=True, writable=True), name=name)


def _tool_names(builder: KnowledgeBuilder) -> List[str]:
    return [tool.__name__ for tool in builder.build()]


def _tool(builder: KnowledgeBuilder, name: str):
    for tool in builder.build():
        if tool.__name__ == name:
            return tool
    raise AssertionError(f"{name} was not emitted; got {_tool_names(builder)}")


class TestToolGating:
    def test_a_query_only_application_gets_exactly_the_four_existing_tools(self):
        # write_kb is among the four, so a read-only application still sees it. Its gate is
        # the per-call check, asserted in TestRouting, not its absence from the list.
        assert _tool_names(KnowledgeBuilder([_sql()])) == BASE_TOOLS

    def test_fetch_adds_only_fetch_kb(self):
        backend = StubBackend(KnowledgeCapabilities(kinds=["document"], fetch=True), name="ids")
        assert _tool_names(KnowledgeBuilder([backend])) == BASE_TOOLS + ["fetch_kb"]

    def test_browse_adds_only_browse_kb(self):
        backend = StubBackend(KnowledgeCapabilities(kinds=["document"], browse=True), name="tree")
        assert _tool_names(KnowledgeBuilder([backend])) == BASE_TOOLS + ["browse_kb"]

    def test_search_and_query_on_one_backend_emits_search_kb(self):
        # read_kb routes to query() whenever query is declared, which would leave search()
        # unreachable. search_kb is what makes the declaration honest.
        backend = StubBackend(KnowledgeCapabilities(kinds=["hybrid"], search=True, query=True, query_language="sql"), name="hybrid")
        assert _tool_names(KnowledgeBuilder([backend])) == BASE_TOOLS + ["search_kb"]

    def test_a_search_only_backend_emits_search_kb(self):
        # The gate is the registered set declaring search, nothing more. It used to also
        # require query, which left an OKF-only or Chroma-only application with no search_kb
        # -- the case the amendment exists to fix. read_kb reaching the same search() is
        # accepted redundancy, and is what the two docstrings now describe.
        assert _tool_names(KnowledgeBuilder([_vector()])) == BASE_TOOLS + ["search_kb"]

    def test_search_and_query_on_different_backends_emits_search_kb(self):
        # Where query lives is irrelevant to the gate; the vector backend declaring search
        # is the whole condition.
        assert _tool_names(KnowledgeBuilder([_vector(), _sql()])) == BASE_TOOLS + ["search_kb"]

    def test_the_full_capability_set_emits_seven_tools_in_a_fixed_order(self):
        backend = StubBackend(
            KnowledgeCapabilities(kinds=["document"], search=True, query=True, query_language="sql", fetch=True, browse=True, writable=True),
            name="everything",
        )
        assert _tool_names(KnowledgeBuilder([backend])) == BASE_TOOLS + ["search_kb", "fetch_kb", "browse_kb"]

    def test_gating_is_a_property_of_the_registered_set_not_of_one_backend(self):
        # A vector backend registered alongside an OKF-shaped one gains browse_kb in the
        # prompt, and routing it at the vector backend is what reports the mismatch.
        assert _tool_names(KnowledgeBuilder([_vector(), _documents()])) == BASE_TOOLS + ["search_kb", "fetch_kb", "browse_kb"]

    def test_a_backend_without_a_declaration_warns_and_is_treated_as_declaring_nothing(self, caplog):
        builder = KnowledgeBuilder([NoCapabilitiesBackend(), _documents()])

        with caplog.at_level(logging.WARNING, logger="ak.KnowledgeBuilder"):
            names = [tool.__name__ for tool in builder.build()]

        assert names == BASE_TOOLS + ["search_kb", "fetch_kb", "browse_kb"]
        assert "undeclared" in caplog.text
        assert "super().__init__" in caplog.text


class TestReadRouting:
    """read_kb branches on the declaration. This moved off KnowledgeBase.read() in #553's amendment."""

    def test_read_kb_routes_to_query_for_a_query_backend(self):
        sql = _sql()
        result = _tool(KnowledgeBuilder([sql]), "read_kb")("sql", "SELECT 1")

        assert sql.calls == [("query", ("SELECT 1", 3), {})]
        assert result == "- query:SELECT 1 (source: sql)"

    def test_read_kb_routes_to_search_for_a_non_query_backend(self):
        vector = _vector()
        result = _tool(KnowledgeBuilder([vector]), "read_kb")("vector", "refund policy")

        assert vector.calls == [("search", ("refund policy", 3), {})]
        assert result == "- search:refund policy (source: vector)"

    def test_a_backend_declaring_both_routes_to_query(self):
        # The rule is "a declared query language wins", not "whichever was declared first".
        hybrid = StubBackend(KnowledgeCapabilities(search=True, query=True, query_language="sql"), name="hybrid")
        _tool(KnowledgeBuilder([hybrid]), "read_kb")("hybrid", "SELECT 1")

        assert [call[0] for call in hybrid.calls] == ["query"]

    def test_read_kb_defaults_to_a_limit_of_three(self):
        vector = _vector()
        _tool(KnowledgeBuilder([vector]), "read_kb")("vector", "anything")

        assert vector.calls == [("search", ("anything", 3), {})]

    def test_read_kb_forwards_an_explicit_limit(self):
        sql = _sql()
        _tool(KnowledgeBuilder([sql]), "read_kb")("sql", "SELECT 1", limit=17)

        assert sql.calls == [("query", ("SELECT 1", 17), {})]


class TestRouting:
    def test_routing_at_a_backend_that_does_not_declare_the_capability_returns_a_string(self):
        vector, documents = _vector(), _documents()
        fetch_kb = _tool(KnowledgeBuilder([vector, documents]), "fetch_kb")

        result = fetch_kb("vector", "some-id")

        assert result == "Backend 'vector' does not support fetch. Backends that do: ['okf']."
        # The gate, not the backend, is what stopped the call.
        assert vector.calls == []

    def test_read_kb_at_a_backend_that_can_neither_search_nor_query_names_the_right_tools(self):
        # read() would have fallen through to search() and reported a capability the agent
        # never asked for; nothing here can serve a read, so the alternatives list is empty.
        identities = StubBackend(KnowledgeCapabilities(kinds=["document"], fetch=True), name="ids")
        read_kb = _tool(KnowledgeBuilder([identities]), "read_kb")

        assert read_kb("ids", "anything") == "Backend 'ids' does not support reads. Backends that do: []."
        assert identities.calls == []

    def test_read_kb_points_at_the_backends_that_can_serve_a_read(self):
        identities = StubBackend(KnowledgeCapabilities(kinds=["document"], fetch=True), name="ids")
        builder = KnowledgeBuilder([identities, _vector(), _sql()])

        result = _tool(builder, "read_kb")("ids", "anything")

        # Both a search backend and a query backend satisfy a read.
        assert result == "Backend 'ids' does not support reads. Backends that do: ['vector', 'sql']."

    def test_write_kb_at_a_read_only_backend_is_gated_rather_than_raised_through(self):
        sql = _sql()
        result = _tool(KnowledgeBuilder([sql, _vector()]), "write_kb")("sql", text="an order")

        # The field is spelled "writable"; the agent is told "writes".
        assert result == "Backend 'sql' does not support writes. Backends that do: ['vector']."
        assert sql.written == []

    def test_an_unknown_backend_keeps_the_existing_message(self):
        builder = KnowledgeBuilder([_documents()])
        assert _tool(builder, "browse_kb")("nope") == "Unknown backend 'nope'. Available: ['okf']"

    def test_search_kb_routes_at_any_backend_declaring_search(self):
        hybrid = StubBackend(KnowledgeCapabilities(search=True, query=True, query_language="sql"), name="hybrid")
        vector = _vector()
        search_kb = _tool(KnowledgeBuilder([hybrid, vector]), "search_kb")

        # The gate was opened by hybrid, but vector declares search too, so it serves.
        assert search_kb("vector", "invoices") == "- search:invoices (source: vector)"
        assert vector.calls == [("search", ("invoices", 3), {})]

    def test_browse_defaults_reach_the_backend_unchanged(self):
        documents = _documents()
        _tool(KnowledgeBuilder([documents]), "browse_kb")("okf", "tables/")

        assert documents.calls == [("browse", ("tables/", 50), {})]

    def test_a_declared_but_unimplemented_operation_surfaces_as_text_not_an_exception(self):
        # A dishonest declaration is a backend bug, but it must not escape into the framework.
        dishonest = MinimalStub(KnowledgeCapabilities(kinds=["document"], browse=True), name="dishonest")
        result = _tool(KnowledgeBuilder([dishonest]), "browse_kb")("dishonest", "")

        assert result.startswith("Execution Error:")
        assert "browse" in result


class TestFetchIds:
    def test_ids_are_split_stripped_and_emptied_segments_dropped(self):
        documents = _documents()
        _tool(KnowledgeBuilder([documents]), "fetch_kb")("okf", " a.md , ,b.md ")

        assert documents.calls == [("fetch", (["a.md", "b.md"],), {})]

    def test_an_all_empty_argument_never_reaches_the_backend(self):
        documents = _documents()
        result = _tool(KnowledgeBuilder([documents]), "fetch_kb")("okf", " , ")

        assert result == "Error: provide at least one id."
        assert documents.calls == []

    def test_a_single_id_needs_no_separator(self):
        documents = _documents()
        _tool(KnowledgeBuilder([documents]), "fetch_kb")("okf", "tables/orders.md")

        assert documents.calls == [("fetch", (["tables/orders.md"],), {})]


class TestSemanticMap:
    def test_search_kb_queries_are_resolved(self):
        hybrid = StubBackend(KnowledgeCapabilities(search=True, query=True, query_language="sql"), name="hybrid")
        builder = KnowledgeBuilder([hybrid], semantic_map={"<ORDERS>": "analytics.sales.orders"})

        _tool(builder, "search_kb")("hybrid", "rows in <ORDERS>")

        assert hybrid.calls == [("search", ("rows in analytics.sales.orders", 3), {})]

    def test_browse_kb_paths_are_resolved(self):
        documents = _documents()
        builder = KnowledgeBuilder([documents], semantic_map={"<BUNDLE>": "prod/kb"})

        _tool(builder, "browse_kb")("okf", "<BUNDLE>/tables")

        assert documents.calls == [("browse", ("prod/kb/tables", 50), {})]

    def test_fetch_kb_resolves_each_segment_after_the_split(self):
        documents = _documents()
        builder = KnowledgeBuilder([documents], semantic_map={"<BUNDLE>": "prod/kb"})

        _tool(builder, "fetch_kb")("okf", "<BUNDLE>/a.md, <BUNDLE>/b.md")

        assert documents.calls == [("fetch", (["prod/kb/a.md", "prod/kb/b.md"],), {})]


class TestPerBackendSemanticMaps:
    """okf.databases.<name>.semantic_map is declared per database, and one builder holds several."""

    def test_a_backend_map_applies_only_to_that_backend(self):
        vector, documents = _vector(), _documents()
        builder = KnowledgeBuilder(
            [vector, documents],
            backend_semantic_maps={"okf": {"<ROOT>": "prod/kb"}},
        )

        _tool(builder, "browse_kb")("okf", "<ROOT>/tables")
        _tool(builder, "search_kb")("vector", "rows in <ROOT>")

        assert documents.calls == [("browse", ("prod/kb/tables", 50), {})]
        # The vector backend holds no map, so the token is passed through untouched rather
        # than resolved with a neighbour's mapping.
        assert vector.calls == [("search", ("rows in <ROOT>", 3), {})]

    def test_a_backend_map_beats_the_flat_map_for_that_backend_only(self):
        # The case that cannot be expressed by flattening: one token, two meanings.
        vector, documents = _vector(), _documents()
        builder = KnowledgeBuilder(
            [vector, documents],
            semantic_map={"<ROOT>": "shared/default"},
            backend_semantic_maps={"okf": {"<ROOT>": "prod/kb"}},
        )

        _tool(builder, "browse_kb")("okf", "<ROOT>/tables")
        _tool(builder, "search_kb")("vector", "rows in <ROOT>")

        assert documents.calls == [("browse", ("prod/kb/tables", 50), {})]
        assert vector.calls == [("search", ("rows in shared/default", 3), {})]

    def test_tokens_the_backend_map_does_not_mention_still_resolve(self):
        # Merged over, not replacing: overriding one token must not drop the rest.
        documents = _documents()
        builder = KnowledgeBuilder(
            [documents],
            semantic_map={"<ROOT>": "shared/default", "<AREA>": "sales"},
            backend_semantic_maps={"okf": {"<ROOT>": "prod/kb"}},
        )

        _tool(builder, "browse_kb")("okf", "<ROOT>/<AREA>")

        assert documents.calls == [("browse", ("prod/kb/sales", 50), {})]

    def test_a_map_naming_an_unregistered_backend_warns_rather_than_raising(self, caplog):
        # The OKF layer passes each builder only its own subset, so a name that is not here
        # is a bug in that layer -- worth a warning, but not worth failing an app build.
        with caplog.at_level(logging.WARNING, logger="ak.KnowledgeBuilder"):
            builder = KnowledgeBuilder([_documents()], backend_semantic_maps={"gone": {"<ROOT>": "x"}})

        assert "'gone'" in caplog.text
        assert "no such backend is registered" in caplog.text
        assert _tool_names(builder) == BASE_TOOLS + ["search_kb", "fetch_kb", "browse_kb"]


class TestWritableToolSet:
    def test_build_defaults_to_the_historical_four_in_their_historical_order(self):
        # The compatibility promise: no existing caller passes the argument, and none of
        # them may see a different list because it exists.
        assert _tool_names(KnowledgeBuilder([_sql()])) == BASE_TOOLS
        assert [tool.__name__ for tool in KnowledgeBuilder([_sql()]).build(writable=True)] == BASE_TOOLS

    def test_writable_false_omits_write_kb_and_keeps_the_rest_in_order(self):
        names = [tool.__name__ for tool in KnowledgeBuilder([_sql()]).build(writable=False)]
        assert names == ["get_schemas", "read_kb", "get_all_kb_descriptions"]

    def test_writable_false_still_emits_the_capability_gated_tools(self):
        # The parameter withholds one tool; it does not make the builder read-only in any
        # other sense, and browsing a bundle is a read.
        names = [tool.__name__ for tool in KnowledgeBuilder([_documents()]).build(writable=False)]
        assert names == ["get_schemas", "read_kb", "get_all_kb_descriptions", "search_kb", "fetch_kb", "browse_kb"]

    def test_writable_false_withholds_the_tool_even_from_a_writable_backend(self):
        # Presence is the caller's question; the per-call writable check is the backend's.
        # A writable backend is exactly the case where the two answers differ.
        assert _documents().capabilities.writable is True
        assert "write_kb" not in [tool.__name__ for tool in KnowledgeBuilder([_documents()]).build(writable=False)]


class TestWriteMetadata:
    def test_a_write_with_a_query_emits_the_generic_keys_only(self):
        vector = _vector()
        write_kb = _tool(KnowledgeBuilder([vector]), "write_kb")

        write_kb("vector", text="an order", query="CREATE (n:Order)", params_json='{"id": 7}')

        metadata = vector.written[0]["metadata"]
        assert metadata == {"source": "agent", "query": "CREATE (n:Order)", "params": {"id": 7}}
        # Neo4j's spelling is gone: it was being written for every backend, vector stores included.
        assert "cypher_query" not in metadata
        assert "cypher_params" not in metadata

    def test_a_text_only_write_carries_only_the_source(self):
        vector = _vector()
        _tool(KnowledgeBuilder([vector]), "write_kb")("vector", text="an order")

        assert vector.written == [{"text": "an order", "metadata": {"source": "agent"}}]

    def test_write_queries_are_still_resolved_through_the_semantic_map(self):
        vector = _vector()
        builder = KnowledgeBuilder([vector], semantic_map={"<ORDERS>": "analytics.sales.orders"})

        _tool(builder, "write_kb")("vector", text="an order", query="INSERT INTO <ORDERS> VALUES (1)")

        assert vector.written[0]["metadata"]["query"] == "INSERT INTO analytics.sales.orders VALUES (1)"

    @pytest.mark.parametrize("params_json", ["not json", "[1, 2]", '"a string"'])
    def test_a_non_object_params_json_keeps_its_existing_message(self, params_json: str):
        vector = _vector()
        result = _tool(KnowledgeBuilder([vector]), "write_kb")("vector", query="MATCH (n)", params_json=params_json)

        assert result == "Error: params_json must be a valid JSON object string."
        assert vector.written == []


class TestGetSchemas:
    def test_one_failing_backend_no_longer_fails_the_whole_call(self):
        healthy = _vector("healthy").add_schema({"columns": ["id"]})
        # No add_schema() and no derived schema, so schema() raises the base ValueError.
        broken = _sql("broken")
        get_schemas = _tool(KnowledgeBuilder([healthy, broken]), "get_schemas")

        schemas = json.loads(get_schemas())

        assert schemas["healthy"]["columns"] == ["id"]
        assert "has not been set" in schemas["broken"]["error"]

    def test_capabilities_reach_the_agent_through_the_schema(self):
        get_schemas = _tool(KnowledgeBuilder([_documents().add_schema({"about": "docs"})]), "get_schemas")

        capabilities = json.loads(get_schemas())["okf"]["capabilities"]

        assert capabilities["fetch"] is True
        assert capabilities["browse"] is True
        assert capabilities["query"] is False


class TestUnchangedSurface:
    def test_the_constructor_signature_and_its_validation_are_unchanged(self):
        with pytest.raises(ValueError, match="Duplicate knowledge base backend_name"):
            KnowledgeBuilder([_vector("same"), _sql("same")])

    def test_read_kb_still_routes_on_the_declaration(self):
        vector, sql = _vector(), _sql()
        read_kb = _tool(KnowledgeBuilder([vector, sql]), "read_kb")

        assert read_kb("vector", "invoices") == "- search:invoices (source: vector)"
        assert read_kb("sql", "SELECT 1") == "- query:SELECT 1 (source: sql)"

    def test_get_all_kb_descriptions_is_untouched(self):
        builder = KnowledgeBuilder([_vector(), _documents()])
        assert _tool(builder, "get_all_kb_descriptions")() == "vector: a stub backend\nokf: a stub backend"

    def test_every_tool_is_a_plain_callable_with_a_docstring(self):
        # The docstrings are the agent-visible tool descriptions, not developer notes.
        for tool in KnowledgeBuilder([_documents()]).build():
            assert callable(tool)
            assert tool.__doc__ and tool.__doc__.strip()
