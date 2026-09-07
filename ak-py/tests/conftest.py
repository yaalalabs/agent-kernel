"""Fixtures shared across test modules, chiefly the faked backend SDKs.

The knowledge-base SDK doubles live here rather than in one of the test modules that use
them: ``test_knowledgebase_backends`` and ``test_knowledgebase_contract`` both need a
``ChromaManager``, ``Neo4jManager`` and ``StarburstManager`` whose client is faked, and a
fixture reached by importing another test module's namespace couples the two files and hides
the fixture behind a ``noqa``. One fake per SDK, one place to fix it when a client's shape
changes, and pytest resolves it for either module without an import.

Nothing here touches a live Chroma, Neo4j or Starburst. The manager classes are imported
inside the fixtures, not at module scope, so a run that exercises neither module — and an
environment without those optional extras installed — does not import their SDKs at
collection time.
"""

from typing import Any, Mapping

import pytest


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
def chroma(monkeypatch):
    from agentkernel.knowledgebase.chroma import ChromaManager

    monkeypatch.setattr("agentkernel.knowledgebase.chroma.chromadb.PersistentClient", FakeChromaClient)
    # Passing an embedding function keeps DefaultEmbeddingFunction (and its model download) out.
    return ChromaManager(persist_path="/tmp/unused-chroma", embedding_function=object())


@pytest.fixture
def neo4j_driver() -> FakeNeo4jDriver:
    return FakeNeo4jDriver()


@pytest.fixture
def neo4j(monkeypatch, neo4j_driver):
    from agentkernel.knowledgebase.neo4j import Neo4jManager

    class FakeGraphDatabase:
        @staticmethod
        def driver(uri, auth=None):
            return neo4j_driver

    monkeypatch.setattr("agentkernel.knowledgebase.neo4j.GraphDatabase", FakeGraphDatabase)
    return Neo4jManager(uri="bolt://fake:7687", user="neo4j", password="secret")


@pytest.fixture
def starburst(monkeypatch):
    from agentkernel.knowledgebase.starburst import StarburstManager

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
