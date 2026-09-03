"""Capability declarations and renamed operations on the three shipped backends (#553 iteration 2).

Every backend SDK is faked — no test touches a live Chroma, Neo4j, or Starburst. What is
pinned here is the part of the refactor that is invisible until something calls it: the
declarations, the read -> search/query renames, the new limit defaults, Neo4j's generic
write metadata, and the StarburstManager.schema attribute/method collision, which made
get_schemas raise TypeError for every Starburst deployment.
"""

from typing import Any, Mapping

import pytest

from agentkernel.knowledgebase.chroma import ChromaManager
from agentkernel.knowledgebase.errors import KnowledgeCapabilityError, KnowledgeError
from agentkernel.knowledgebase.neo4j import Neo4jManager
from agentkernel.knowledgebase.starburst import StarburstManager


class FakeChromaCollection:
    def __init__(self) -> None:
        self.queries: list[tuple[list[str], int]] = []
        self.upserts: list[dict] = []

    def query(self, query_texts, n_results):
        self.queries.append((query_texts, n_results))
        return {"documents": [["doc one"]], "metadatas": [[{"source": "kb"}]]}

    def upsert(self, documents, metadatas, ids):
        self.upserts.append({"documents": documents, "metadatas": metadatas, "ids": ids})


class FakeChromaClient:
    def __init__(self, path: str) -> None:
        self.path = path
        self.collection = FakeChromaCollection()

    def get_or_create_collection(self, name, embedding_function):
        return self.collection


class FakeNeo4jRecord:
    def __init__(self, payload: Mapping[str, Any]) -> None:
        self.payload = payload

    def data(self):
        return dict(self.payload)


class FakeNeo4jDriver:
    def __init__(self) -> None:
        self.executed: list[tuple[str, dict]] = []
        self.closed = False

    def verify_connectivity(self) -> None:
        pass

    def execute_query(self, query, parameters_=None, database_=None):
        self.executed.append((query, dict(parameters_ or {})))
        return [FakeNeo4jRecord({"n": 1})], None, None

    def close(self) -> None:
        self.closed = True


class FakeTrinoCursor:
    description = [("col",)]

    def __init__(self) -> None:
        self.executed: list[str] = []

    def execute(self, sql: str) -> None:
        self.executed.append(sql)

    def fetchall(self):
        return [("value",)]

    def close(self) -> None:
        pass


class FakeTrinoConnection:
    def __init__(self, **kwargs) -> None:
        self.kwargs = kwargs
        self.cursors: list[FakeTrinoCursor] = []

    def cursor(self) -> FakeTrinoCursor:
        created = FakeTrinoCursor()
        self.cursors.append(created)
        return created

    def close(self) -> None:
        pass


@pytest.fixture
def chroma(monkeypatch) -> ChromaManager:
    monkeypatch.setattr("agentkernel.knowledgebase.chroma.chromadb.PersistentClient", FakeChromaClient)
    # Passing an embedding function keeps DefaultEmbeddingFunction (and its model download) out.
    return ChromaManager(persist_path="/tmp/unused-chroma", embedding_function=object())


@pytest.fixture
def neo4j_driver() -> FakeNeo4jDriver:
    return FakeNeo4jDriver()


@pytest.fixture
def neo4j(monkeypatch, neo4j_driver) -> Neo4jManager:
    class FakeGraphDatabase:
        @staticmethod
        def driver(uri, auth=None):
            return neo4j_driver

    monkeypatch.setattr("agentkernel.knowledgebase.neo4j.GraphDatabase", FakeGraphDatabase)
    return Neo4jManager(uri="bolt://fake:7687", user="neo4j", password="secret")


@pytest.fixture
def starburst(monkeypatch) -> StarburstManager:
    monkeypatch.setattr("trino.dbapi.connect", lambda **kwargs: FakeTrinoConnection(**kwargs))
    monkeypatch.setattr("trino.auth.BasicAuthentication", lambda user, password: ("auth", user))
    return StarburstManager(
        host="fake.galaxy",
        user="u",
        password="p",
        catalog="mongo",
        schema="sales",
        table_name="orders",
    )


class TestChromaManager:
    def test_it_declares_semantic_search_and_writes(self, chroma):
        caps = chroma.capabilities
        assert caps.kinds == ["vector"]
        assert (caps.search, caps.search_mode, caps.writable) == (True, "semantic", True)
        assert (caps.query, caps.fetch, caps.browse, caps.derives_schema) == (False, False, False, False)

    def test_relevance_retrieval_is_now_named_search(self, chroma):
        assert "search" in ChromaManager.__dict__
        assert "read" not in ChromaManager.__dict__  # inherited and routing, no longer overridden
        assert chroma.search("refund policy") == [{"text": "doc one", "metadata": {"source": "kb"}}]

    def test_read_routes_to_search(self, chroma):
        chroma.read("refund policy", limit=7)
        assert chroma.collection.queries == [(["refund policy"], 7)]

    def test_writes_still_reach_the_collection(self, chroma):
        chroma.write([{"text": "a fact", "metadata": {"source": "kb"}}])
        assert chroma.collection.upserts[0]["documents"] == ["a fact"]

    def test_schema_carries_the_declaration(self, chroma):
        schema = chroma.add_schema({"description": "vectors"}).schema()
        assert schema["capabilities"]["search_mode"] == "semantic"


class TestNeo4jManager:
    def test_it_declares_cypher_query_and_writes(self, neo4j):
        caps = neo4j.capabilities
        assert caps.kinds == ["graph", "structured"]
        assert (caps.query, caps.query_language, caps.writable) == (True, "cypher", True)
        assert (caps.search, caps.fetch, caps.browse) == (False, False, False)

    def test_query_language_retrieval_is_now_named_query(self, neo4j):
        assert "query" in Neo4jManager.__dict__
        assert "read" not in Neo4jManager.__dict__
        rows = neo4j.query("MATCH (n) RETURN n")
        assert rows == [{"text": '{"n": 1}', "metadata": {"source": "graph"}}]

    def test_read_routes_to_query(self, neo4j, neo4j_driver):
        neo4j.read("MATCH (n) RETURN n")
        assert "MATCH (n) RETURN n" in neo4j_driver.executed[0][0]

    def test_query_defaults_to_a_limit_of_three(self, neo4j, neo4j_driver):
        neo4j.query("MATCH (n) RETURN n")
        assert neo4j_driver.executed[0][1] == {"ak_read_limit": 3}

    def test_write_prefers_the_generic_query_key(self, neo4j, neo4j_driver):
        neo4j.write([{"text": "", "metadata": {"query": "CREATE (:N)", "params": {"a": 1}}}])
        assert neo4j_driver.executed == [("CREATE (:N)", {"a": 1})]

    def test_write_falls_back_to_the_legacy_cypher_keys(self, neo4j, neo4j_driver):
        neo4j.write([{"text": "", "metadata": {"cypher_query": "CREATE (:Old)", "cypher_params": {"b": 2}}}])
        assert neo4j_driver.executed == [("CREATE (:Old)", {"b": 2})]

    def test_the_generic_key_wins_when_both_are_present(self, neo4j, neo4j_driver):
        metadata = {"query": "CREATE (:New)", "cypher_query": "CREATE (:Old)"}
        neo4j.write([{"text": "", "metadata": metadata}])
        assert neo4j_driver.executed == [("CREATE (:New)", {})]

    def test_a_record_carrying_no_query_is_skipped_rather_than_executed(self, neo4j, neo4j_driver):
        # It used to reach the driver as _run(None, {}).
        with pytest.raises(KnowledgeError):
            neo4j.write([{"text": "just prose", "metadata": {"source": "agent"}}])
        assert neo4j_driver.executed == []

    def test_a_skipped_record_does_not_stop_the_rest_of_the_batch(self, neo4j, neo4j_driver):
        with pytest.raises(KnowledgeError):
            neo4j.write(
                [
                    {"text": "just prose", "metadata": {"source": "agent"}},
                    {"text": "", "metadata": {"query": "CREATE (:N)"}},
                ]
            )
        # Raised only once the batch was through, so the healthy record still landed.
        assert neo4j_driver.executed == [("CREATE (:N)", {})]

    def test_the_skip_report_names_what_was_stored_and_what_was_not(self, neo4j, neo4j_driver):
        # write_kb turns this into "Failed to write...", which is the whole point: a
        # text-only write to Neo4j used to be reported to the agent as a success.
        with pytest.raises(KnowledgeError) as excinfo:
            neo4j.write(
                [
                    {"text": "just prose", "metadata": {"source": "agent"}},
                    {"text": "", "metadata": {"query": "CREATE (:N)"}},
                ]
            )
        assert "1 of 2" in str(excinfo.value)
        assert "1 stored" in str(excinfo.value)

    def test_a_batch_that_is_entirely_writable_does_not_report(self, neo4j, neo4j_driver):
        neo4j.write([{"text": "", "metadata": {"query": "CREATE (:N)"}}])
        assert neo4j_driver.executed == [("CREATE (:N)", {})]

    def test_schema_carries_the_declaration(self, neo4j):
        schema = neo4j.add_schema({"nodes": ["Customer"]}).schema()
        assert schema["capabilities"]["query_language"] == "cypher"


class TestStarburstManager:
    def test_it_declares_read_only_sql(self, starburst):
        caps = starburst.capabilities
        assert caps.kinds == ["structured"]
        assert (caps.query, caps.query_language, caps.writable) == (True, "sql", False)
        assert (caps.search, caps.fetch, caps.browse) == (False, False, False)

    def test_the_trino_schema_now_lives_on_db_schema(self, starburst):
        assert starburst.db_schema == "sales"

    def test_schema_resolves_to_the_inherited_method(self, starburst):
        # The regression guard: self.schema used to shadow schema(), so get_schemas raised
        # TypeError: 'str' object is not callable for every Starburst deployment.
        assert callable(starburst.schema)
        result = starburst.add_schema({"table": "mongo.sales.orders"}).schema()
        assert isinstance(result, Mapping)
        assert result["table"] == "mongo.sales.orders"
        assert result["capabilities"]["query_language"] == "sql"

    def test_the_schema_constructor_keyword_is_unchanged(self, starburst):
        # Both shipped examples pass schema=..., so the keyword must keep working.
        assert starburst.connection.kwargs["schema"] == "sales"
        assert starburst.connection.kwargs["catalog"] == "mongo"

    def test_the_row_source_uses_the_renamed_attribute(self, starburst):
        rows = starburst.query("SELECT * FROM orders")
        assert rows == [{"text": "col: value", "metadata": {"source": "mongo.sales.orders"}}]

    def test_query_language_retrieval_is_now_named_query(self, starburst):
        assert "query" in StarburstManager.__dict__
        assert "read" not in StarburstManager.__dict__
        assert starburst.query("SELECT 1") == [{"text": "col: value", "metadata": {"source": "mongo.sales.orders"}}]

    def test_read_routes_to_query(self, starburst):
        starburst.read("SELECT * FROM orders")
        assert starburst.connection.cursors[0].executed == ["SELECT * FROM orders LIMIT 3"]

    def test_query_defaults_to_a_limit_of_three(self, starburst):
        starburst.query("SELECT * FROM orders")
        assert starburst.connection.cursors[0].executed == ["SELECT * FROM orders LIMIT 3"]

    @pytest.mark.parametrize(
        "sql",
        [
            # The bug: "LIMIT" in sql.upper() matched inside the identifier, so the whole
            # table was read into the agent's context unbounded.
            "SELECT * FROM credit_limits",
            "SELECT rate_limit FROM policies",
            # A word boundary alone still matches these two, which is why the clause has
            # to carry its count to count.
            "SELECT * FROM t WHERE note = 'limit'",
            "SELECT limit FROM policies",
            # A subquery LIMIT bounds the subquery, not the result: without the fallback this
            # returns every row of the outer table.
            "SELECT * FROM huge WHERE id IN (SELECT id FROM t LIMIT 10)",
            "SELECT * FROM (SELECT * FROM orders LIMIT 10) t",
        ],
    )
    def test_a_limit_that_does_not_bound_the_result_does_not_disable_the_fallback(self, starburst, sql: str):
        starburst.query(sql)
        assert starburst.connection.cursors[0].executed == [f"{sql} LIMIT 3"]

    @pytest.mark.parametrize(
        "sql",
        [
            "SELECT * FROM orders LIMIT 10",
            "select * from orders limit 10",
            "SELECT * FROM t LIMIT ALL",
            "SELECT * FROM orders OFFSET 5 LIMIT 10",
            # Trino's other spelling of the same clause; appending a LIMIT after one is invalid SQL.
            "SELECT * FROM orders FETCH FIRST 10 ROWS ONLY",
            "SELECT * FROM orders FETCH NEXT 1 ROW ONLY",
        ],
    )
    def test_a_statement_that_already_bounds_itself_is_left_alone(self, starburst, sql: str):
        starburst.query(sql)
        assert starburst.connection.cursors[0].executed == [sql]

    def test_a_trailing_semicolon_does_not_defeat_the_anchored_clause(self, starburst):
        # The statement is stripped of its terminator before the guard runs, so the clause is
        # still the last thing in it.
        starburst.query("SELECT * FROM orders LIMIT 10 ;")
        assert starburst.connection.cursors[0].executed == ["SELECT * FROM orders LIMIT 10 "]

    def test_non_read_sql_is_still_rejected(self, starburst):
        assert starburst.query("DELETE FROM orders") == []
        assert starburst.connection.cursors == []

    def test_write_raises_a_capability_error(self, starburst):
        with pytest.raises(KnowledgeCapabilityError) as excinfo:
            starburst.write([{"text": "x"}])
        assert excinfo.value.subject == "starburst"
        assert excinfo.value.capability == "write"

    def test_write_is_refused_by_the_base_declaration_not_by_an_override(self, starburst):
        # StarburstManager no longer overrides write(); writable=False is what refuses it.
        assert "write" not in vars(type(starburst))
