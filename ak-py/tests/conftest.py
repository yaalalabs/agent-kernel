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


@pytest.fixture
def descriptor_only_registry():
    """The class of a registry that knows descriptors and hosts no agent (#603).

    It stands in for a process over a shared registry store, which lists agents that run in another
    process: ``descriptors()`` and ``descriptor(id)`` answer, ``get`` and ``agents`` find nothing, and
    nothing registers into it. Build one with the descriptors it should know and hand it to ``Runtime``.
    """
    from agentkernel.core.registry import AgentRegistry

    class DescriptorOnlyRegistry(AgentRegistry):
        def __init__(self, descriptors):
            self._descriptors = {descriptor.id: descriptor for descriptor in descriptors}

        def register(self, descriptor, agent):  # pragma: no cover - nothing registers here
            raise AssertionError("not registered into")

        def deregister(self, id):  # pragma: no cover
            raise AssertionError("not deregistered from")

        def get(self, id):
            return None

        def descriptor(self, id):
            return self._descriptors.get(id)

        def agents(self):
            return {}

        def descriptors(self):
            return list(self._descriptors.values())

    return DescriptorOnlyRegistry


@pytest.fixture
def surface_agent():
    """The class of an agent served on the surfaces it is built with, whose reply is its own name (#603).

    ``surface_agent("internal", ["a2a"])`` is on ``a2a`` only, ``surface_agent("public")`` on every surface. A run
    replies with the agent's name, streamed or not, so a test reads from the reply which agent a request reached.
    """
    from agentkernel.core.base import Agent, Runner
    from agentkernel.core.event import MessageEnd, MessageStart, TextDelta
    from agentkernel.core.model import AgentReplyText

    class WhoRanRunner(Runner):
        def __init__(self):
            super().__init__("WhoRanRunner")

        async def run(self, agent, session, requests):
            return AgentReplyText(response=agent.name)

        async def stream(self, agent, session, requests):
            yield MessageStart(message_id="who-1")
            yield TextDelta(message_id="who-1", content=agent.name)
            yield MessageEnd(message_id="who-1")

    class SurfaceAgent(Agent):
        def __init__(self, name, surfaces=None):
            super().__init__(name, WhoRanRunner())
            self._set_descriptor(self.descriptor.model_copy(update={"surfaces": surfaces}))

        def get_description(self):
            return "Surface test agent"

        def override_system_prompt(self, prompt):
            pass

        def attach_tool(self, tool):
            pass

    return SurfaceAgent


@pytest.fixture
def kept_off_rest(surface_agent):
    """A runtime of the test's own hosting an agent kept off ``rest`` beside one on every surface (#603).

    ``internal`` is on ``a2a`` only and registered first, so it is the agent a request naming none would reach
    were surfaces ignored; ``public`` is on every surface. Not entered: a test runs under it with ``with``.
    """
    from agentkernel.core.runtime import Runtime
    from agentkernel.core.session.in_memory import InMemorySessionStore

    runtime = Runtime(InMemorySessionStore())
    runtime.register(surface_agent("internal", ["a2a"]))
    runtime.register(surface_agent("public"))
    return runtime


@pytest.fixture
def credentials(monkeypatch):
    """Returns a function that installs an ``identity.credentials`` block on the live configuration (#603, iteration 25).

    ``credentials(**fields)`` puts the block (with a static identity provider beside it, which nothing here builds)
    where ``CredentialManager.get`` reads it, resets the process-wide manager and returns it, so retention, the
    broker and release run as in a configured process: the real store, the real exchangers. The manager and the
    in-memory store are emptied before and after. Code that authenticates builds ``RequestAuthenticator(provider,
    manager)`` itself, since the static provider's secret is not seeded.
    """
    from agentkernel.core.config import AKConfig, _IdentityConfig
    from agentkernel.identity.credential.in_memory import InMemoryCredentialStore
    from agentkernel.identity.credential.manager import CredentialManager

    def _forget() -> None:
        CredentialManager.reset()
        InMemoryCredentialStore._entries.clear()

    def _install(**fields):
        provider = {"type": "static", "static": {"principals": {"ALICE_TOKEN": {"subject": "alice"}}}}
        monkeypatch.setattr(AKConfig.get(), "identity", _IdentityConfig.model_validate({"provider": provider, "credentials": fields}))
        _forget()
        return CredentialManager.get()

    _forget()
    yield _install
    _forget()


@pytest.fixture
def credential_manager(monkeypatch):
    """The process's ``CredentialManager`` over an empty in-memory store, as ``CredentialManager.get`` returns it (#603).

    For a surface test that needs credentials kept and released without an ``identity`` block on the configuration:
    hand it to ``RequestAuthenticator(provider, credential_manager)`` where a route retains, and read
    ``credential_manager.store`` (or ``InMemoryCredentialStore._entries``) for what is left.
    """
    from agentkernel.identity.credential.in_memory import InMemoryCredentialStore
    from agentkernel.identity.credential.manager import CredentialManager

    store = InMemoryCredentialStore(None)
    store.clear()
    manager = CredentialManager(store, {}, 300)
    monkeypatch.setattr(CredentialManager, "get", classmethod(lambda cls: manager))
    yield manager
    store.clear()


@pytest.fixture
def authorization(monkeypatch):
    """Returns a function that installs an ``authorization`` block of type ``static`` on the live configuration (#603).

    ``authorization(grants=[...], tools=[...])`` puts the block where ``AuthorizerFactory`` and the access gate
    read it, so everything from the gate down runs as it does in a configured process: the real factory, the real
    static backend with the lookups it supplies itself, the real gate. The shared authorizer and gate are dropped
    before and after, and the block is removed when the test ends. A test that replaces or resets ``AKConfig``
    calls it afterwards.
    """
    from agentkernel.core.config import AKConfig, _AuthorizationConfig
    from agentkernel.identity.authz.factory import AuthorizerFactory
    from agentkernel.identity.authz.gate import AccessGate

    def _forget() -> None:
        AuthorizerFactory.reset()
        AccessGate.reset()

    def _install(grants=(), tools=()):
        block = _AuthorizationConfig.model_validate({"type": "static", "static": {"grants": list(grants), "tools": list(tools)}})
        monkeypatch.setattr(AKConfig.get(), "authorization", block)
        _forget()
        return block

    _forget()
    yield _install
    _forget()


@pytest.fixture
def mcp_asgi_transport():
    """Returns a function that builds a FastMCP HTTP transport to an ASGI app, served in-process.

    ``mcp_asgi_transport(app, auth=...)`` gives a ``StreamableHttpTransport`` whose client talks to ``app``
    with no socket. FastMCP 4's transport takes an ``httpx2`` client only, so the factory builds one.
    """
    import httpx2
    from fastmcp.client.transports import StreamableHttpTransport

    def _transport(app, auth=None):
        def factory(headers=None, timeout=None, auth=None, **kwargs):
            return httpx2.AsyncClient(
                transport=httpx2.ASGITransport(app=app),
                base_url="http://mcp.test",
                headers=headers,
                timeout=timeout or httpx2.Timeout(30),
                auth=auth,
                **kwargs,
            )

        return StreamableHttpTransport("http://mcp.test/", auth=auth, httpx_client_factory=factory)

    return _transport
