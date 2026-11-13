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

from collections.abc import Mapping
from typing import Any

import pytest


@pytest.fixture(autouse=True)
def _env_only_secret_manager(monkeypatch):
    """Serve every test an environment-only ``SecretManager``.

    Framework consumers resolve their credentials through ``SecretManager.current()``, which
    otherwise builds from ``AKConfig.get()`` — a mock in many tests — and keeps whatever provider
    the first test configured for the rest of the run. Tests of the manager itself reset it in
    their own fixture.
    """
    from agentkernel.secret import EnvSecretProvider, SecretManager

    monkeypatch.setattr(SecretManager, "_instance", SecretManager(EnvSecretProvider(), cache_ttl=0))


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


@pytest.fixture
def static_identity(monkeypatch):
    """The ``static`` identity provider over one seeded credential, installed as the process-wide provider (#603).

    ``alice-secret`` authenticates ``alice`` (groups ``ops``); every other credential is refused with
    ``AuthenticationError``. The provider is the real one, built over a secret manager that knows the
    one key, and it records every ``authenticate`` call in ``calls`` so a test can assert whether a
    credential was consulted. It is installed on ``IdentityProviderFactory.get`` rather than through
    configuration, so a module's own ``AKConfig.get`` stub needs neither an ``identity`` nor a
    ``secret`` block; the construction-from-config path is pinned in ``test_identity_providers``.
    """
    from agentkernel.identity import IdentityProviderFactory, StaticIdentityProvider
    from agentkernel.secret import SecretManager, SecretProvider

    # SecretManager reads the environment before its provider, and the example suites export this
    # very variable, so a value left in the shell would shadow the seeded credential.
    monkeypatch.delenv("ALICE_TOKEN", raising=False)

    class _OneSecret(SecretProvider):
        def get_secret(self, key):
            return {"ALICE_TOKEN": "alice-secret"}.get(key)

    class _RecordingStaticProvider(StaticIdentityProvider):
        def __init__(self):
            principals = {"ALICE_TOKEN": {"subject": "alice", "groups": ["ops"]}}
            super().__init__(principals, secrets=SecretManager(provider=_OneSecret(), cache_ttl=0))
            self.calls = []

        async def authenticate(self, credential, context=None):
            self.calls.append((credential, context))
            return await super().authenticate(credential, context)

    provider = _RecordingStaticProvider()
    IdentityProviderFactory.reset()
    monkeypatch.setattr(IdentityProviderFactory, "get", classmethod(lambda cls: provider))
    yield provider
    IdentityProviderFactory.reset()
