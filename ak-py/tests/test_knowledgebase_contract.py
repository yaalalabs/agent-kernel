"""KnowledgeBaseContract run against every backend that exists (#553 iteration 8).

The contract is what makes the capability model load-bearing. A backend that declares fetch
and hands out an id with a comma in it, or declares derives_schema and derives nothing, is a
declaration the agent's prompt is built from — so it has to be caught here rather than in a
tool call.

Order matters: the dependency-free fake runs first, in four shapes covering every branch the
contract has. A contract green against the fake and red against a backend is a statement about
the backend. Then OKFManager over a real bundle on disk, then the three SDK-backed managers
with their clients faked. No test here touches a live Chroma, Neo4j, Starburst or bucket.

The SDK doubles are imported from test_knowledgebase_backends rather than duplicated: one fake
per SDK, one place to fix it when a client's shape changes. Importing named symbols binds only
those names, so that module's own tests are not collected twice.
"""

import pytest
from knowledgebase_contracts import (
    KnowledgeBaseContract,
    fake_document_kb,
    fake_graph_kb,
    fake_sql_kb,
    fake_vector_kb,
)
from test_knowledgebase_backends import chroma, neo4j, neo4j_driver, starburst  # noqa: F401  (pytest fixtures)
from test_knowledgebase_okf_manager import BUNDLE, write_bundle

from agentkernel.knowledgebase import LocalDocumentStore, OKFManager


class TestFakeVectorContract(KnowledgeBaseContract):
    """The ChromaManager shape: search only, writable, nothing addressable by id."""

    @pytest.fixture
    def knowledge_base(self):
        return fake_vector_kb()

    def search_query(self) -> str:
        return "orders"


class TestFakeSqlContract(KnowledgeBaseContract):
    """The StarburstManager shape: read-only, and read() routes to query()."""

    @pytest.fixture
    def knowledge_base(self):
        return fake_sql_kb()

    def query_statement(self) -> str:
        return "MATCH orders"


class TestFakeGraphContract(KnowledgeBaseContract):
    """The Neo4jManager shape: a query language plus writes, still no fetch."""

    @pytest.fixture
    def knowledge_base(self):
        return fake_graph_kb()

    def query_statement(self) -> str:
        return "MATCH orders"


class TestFakeDocumentContract(KnowledgeBaseContract):
    """The OKFManager shape: the full surface, including a derived schema."""

    @pytest.fixture
    def knowledge_base(self):
        return fake_document_kb()

    def search_query(self) -> str:
        return "orders"

    def browse_path(self) -> str:
        return "tables"

    def write_probe(self):
        return (
            "generated/contract-probe.md",
            {"text": "written by the contract", "metadata": {"id": "generated/contract-probe.md", "title": "Probe"}},
        )


class TestOKFManagerContract(KnowledgeBaseContract):
    """OKF over a real LocalDocumentStore on tmp_path: a real filesystem, no network."""

    @pytest.fixture
    def knowledge_base(self, tmp_path):
        # refresh_seconds=None so no background re-walk can land between a write and the
        # fetch that reads it back.
        return OKFManager(LocalDocumentStore(write_bundle(tmp_path, BUNDLE), writable=True), refresh_seconds=None)

    def search_query(self) -> str:
        return "orders"

    def browse_path(self) -> str:
        return "tables"

    def write_probe(self):
        # An OKF id is a bundle path: comma-free, .md-suffixed, and carrying the non-empty
        # `type` that is the whole conformance bar for a concept document.
        return (
            "generated/contract-probe.md",
            {"text": "written by the contract", "metadata": {"id": "generated/contract-probe.md", "type": "Note", "title": "Probe"}},
        )


class TestChromaManagerContract(KnowledgeBaseContract):
    """ChromaManager with chromadb.PersistentClient monkeypatched by the shared fixture."""

    @pytest.fixture
    def knowledge_base(self, chroma):
        return chroma

    def search_query(self) -> str:
        return "refund policy"


class TestNeo4jManagerContract(KnowledgeBaseContract):
    """Neo4jManager with GraphDatabase monkeypatched by the shared fixture."""

    @pytest.fixture
    def knowledge_base(self, neo4j):
        return neo4j

    def query_statement(self) -> str:
        return "MATCH (n) RETURN n"

    def write_probe(self):
        # A Neo4j write is a statement, not a document, and there is nothing to read it back
        # with — the None id is what tells the contract to skip the round-trip rather than
        # invent an expectation this backend never promised.
        return (None, {"text": "", "metadata": {"query": "CREATE (:ContractProbe)", "params": {}}})


class TestStarburstManagerContract(KnowledgeBaseContract):
    """StarburstManager with trino.dbapi.connect monkeypatched by the shared fixture."""

    @pytest.fixture
    def knowledge_base(self, starburst):
        return starburst

    def query_statement(self) -> str:
        return "SELECT 1"
