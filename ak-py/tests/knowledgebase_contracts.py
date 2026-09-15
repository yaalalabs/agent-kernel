"""Reusable contract suites for knowledge-base backends and document stores.

``DocumentStoreContract`` asserts the semantics every
:class:`agentkernel.knowledgebase.store.base.DocumentStore` must honor, and
``KnowledgeBaseContract`` does the same for every
:class:`agentkernel.knowledgebase.base.KnowledgeBase`. Subclass one in a test module and
override its fixture; both are deliberately NOT named ``Test*`` so pytest does not collect
them on their own, and this module is not named ``test_*`` so pytest does not collect the
module either.

``FakeKnowledgeBase`` is the dependency-free reference backend the knowledge-base contract is
proven against before it is pointed at anything real: when it passes for the fake and fails
for a backend, the backend is what is wrong.

It all lives under ``tests/`` rather than in the package, so it is a suite this repo holds its
own backends to — not a published helper for out-of-tree backend authors.
"""

import re
import uuid
from typing import Any, Iterable, List, Mapping, Optional

import pytest

from agentkernel.knowledgebase.base import KnowledgeBase, Record
from agentkernel.knowledgebase.errors import KnowledgeCapabilityError, KnowledgePathError
from agentkernel.knowledgebase.model import KnowledgeCapabilities
from agentkernel.knowledgebase.store.base import DocumentStore

# Paths every store must refuse: parent traversal in both separator styles, an absolute
# path, and a normalising escape that only shows itself after the path is reduced.
ESCAPING_PATHS = ["..", "../secret.md", "a/../../secret.md", "/etc/passwd", "..\\secret.md", "./.."]

# A fixed tree the ordering and prefix assertions are made against. "a/z.md" before
# "ab/b.md" is the case that separates a global sort from os.walk's per-directory order.
CONTRACT_TREE = {
    "root.md": b"root document",
    "a/z.md": b"a/z",
    "ab/b.md": b"ab/b",
    "tables/orders.md": b"orders",
    "tables/customers.md": b"customers",
    "tables_extra/x.md": b"not under tables",
}


class DocumentStoreContract:
    """Reusable contract suite asserting ``DocumentStore`` semantics.

    Subclass in a test module and override both fixtures::

        class TestMyStoreContract(DocumentStoreContract):
            @pytest.fixture
            def store(self):
                return MyStore(..., writable=True)

            @pytest.fixture
            def read_only_store(self):
                return MyStore(..., writable=False)
    """

    @pytest.fixture
    def store(self) -> DocumentStore:
        """A writable, initially empty store; every subclass must override this."""
        raise NotImplementedError("subclasses must override the `store` fixture")

    @pytest.fixture
    def read_only_store(self) -> DocumentStore:
        """A store declaring ``writable=False``; every subclass must override this."""
        raise NotImplementedError("subclasses must override the `read_only_store` fixture")

    @pytest.fixture
    def populated_store(self, store: DocumentStore) -> DocumentStore:
        """The writable store with ``CONTRACT_TREE`` written into it."""
        for path, data in CONTRACT_TREE.items():
            store.write_bytes(path, data)
        return store

    def test_contract_write_read_round_trip(self, store: DocumentStore):
        store.write_bytes("notes/one.md", b"hello bytes")
        assert store.read_bytes("notes/one.md") == b"hello bytes"

    def test_contract_write_replaces_existing_contents(self, store: DocumentStore):
        store.write_bytes("notes/one.md", b"first")
        store.write_bytes("notes/one.md", b"second")
        assert store.read_bytes("notes/one.md") == b"second"

    def test_contract_exists_reports_presence(self, store: DocumentStore):
        assert store.exists("notes/one.md") is False
        store.write_bytes("notes/one.md", b"hello")
        assert store.exists("notes/one.md") is True

    def test_contract_missing_document_raises_file_not_found(self, store: DocumentStore):
        with pytest.raises(FileNotFoundError):
            store.read_bytes("nothing/here.md")

    def test_contract_list_is_globally_lexicographic(self, populated_store: DocumentStore):
        listed = populated_store.list()
        assert listed == sorted(CONTRACT_TREE)
        # The specific pair a per-directory walk order gets wrong.
        assert listed.index("a/z.md") < listed.index("ab/b.md")

    def test_contract_list_filters_by_namespace_not_string_prefix(self, populated_store: DocumentStore):
        assert populated_store.list("tables") == ["tables/customers.md", "tables/orders.md"]
        # "tables_extra/" shares a string prefix with "tables" but is a different namespace.
        assert "tables_extra/x.md" not in populated_store.list("tables")

    def test_contract_list_accepts_a_trailing_separator(self, populated_store: DocumentStore):
        assert populated_store.list("tables/") == populated_store.list("tables")

    def test_contract_list_of_an_unknown_namespace_is_empty(self, populated_store: DocumentStore):
        assert populated_store.list("nowhere") == []

    def test_contract_read_prefix_bytes_returns_a_prefix_of_read_bytes(self, store: DocumentStore):
        store.write_bytes("doc.md", b"0123456789")
        assert store.read_prefix_bytes("doc.md", 4) == b"0123"
        assert store.read_bytes("doc.md").startswith(store.read_prefix_bytes("doc.md", 4))

    def test_contract_read_prefix_bytes_past_the_end_returns_the_whole_document(self, store: DocumentStore):
        store.write_bytes("doc.md", b"short")
        assert store.read_prefix_bytes("doc.md", 4096) == b"short"

    @pytest.mark.parametrize("max_bytes", [0, -1])
    def test_contract_read_prefix_bytes_of_a_non_positive_size_returns_nothing(self, store: DocumentStore, max_bytes: int):
        # Left to the transport the three implementations disagreed: read() takes a negative
        # size as the whole file, a slice counts it from the end, and a ranged GET returns
        # nothing. The method promises at most max_bytes, so nothing is the only answer.
        store.write_bytes("doc.md", b"0123456789")
        assert store.read_prefix_bytes("doc.md", max_bytes) == b""

    def test_contract_read_prefix_bytes_on_a_missing_document_raises_file_not_found(self, store: DocumentStore):
        with pytest.raises(FileNotFoundError):
            store.read_prefix_bytes("nothing/here.md", 16)

    @pytest.mark.parametrize("path", ESCAPING_PATHS)
    def test_contract_read_bytes_refuses_an_escaping_path(self, store: DocumentStore, path: str):
        with pytest.raises(KnowledgePathError):
            store.read_bytes(path)

    @pytest.mark.parametrize("path", ESCAPING_PATHS)
    def test_contract_read_prefix_bytes_refuses_an_escaping_path(self, store: DocumentStore, path: str):
        with pytest.raises(KnowledgePathError):
            store.read_prefix_bytes(path, 16)

    @pytest.mark.parametrize("path", ESCAPING_PATHS)
    def test_contract_exists_refuses_an_escaping_path(self, store: DocumentStore, path: str):
        with pytest.raises(KnowledgePathError):
            store.exists(path)

    @pytest.mark.parametrize("path", ESCAPING_PATHS)
    def test_contract_write_bytes_refuses_an_escaping_path(self, store: DocumentStore, path: str):
        with pytest.raises(KnowledgePathError):
            store.write_bytes(path, b"payload")

    @pytest.mark.parametrize("path", ESCAPING_PATHS)
    def test_contract_list_refuses_an_escaping_prefix(self, store: DocumentStore, path: str):
        with pytest.raises(KnowledgePathError):
            store.list(path)

    @pytest.mark.parametrize("path", ["", ".", "./notes/one.md", "notes//one.md", "notes/./one.md"])
    def test_contract_benign_paths_are_accepted(self, store: DocumentStore, path: str):
        # Normalisation must not be so eager that ordinary paths are refused.
        assert store.exists(path) in (True, False)

    def test_contract_equivalent_paths_address_one_document(self, store: DocumentStore):
        store.write_bytes("notes/one.md", b"payload")
        assert store.read_bytes("./notes/one.md") == b"payload"
        assert store.read_bytes("notes//one.md") == b"payload"
        assert store.read_bytes("notes/../notes/one.md") == b"payload"

    def test_contract_a_read_only_store_declares_it(self, read_only_store: DocumentStore):
        assert read_only_store.writable is False

    def test_contract_a_read_only_store_refuses_writes(self, read_only_store: DocumentStore):
        with pytest.raises(KnowledgeCapabilityError):
            read_only_store.write_bytes("notes/one.md", b"payload")

    def test_contract_a_writable_store_declares_it(self, store: DocumentStore):
        assert store.writable is True

    def test_contract_close_is_callable_and_idempotent(self, store: DocumentStore):
        store.close()
        store.close()


# Keys the contract injects into a written record to prove a backend does not validate the
# shape it is handed. Record = Mapping[str, Any], so an unknown key must never raise.
UNKNOWN_RECORD_KEY = "contract_unknown"
UNKNOWN_METADATA_KEY = "contract_unknown_meta"

# What FakeKnowledgeBase holds unless a test hands it something else. Three records across two
# namespaces, which is the least that makes browse's directory-vs-concept split observable.
FAKE_SEED_RECORDS = {
    "notes/contract.md": {
        "text": "contract probe about orders and refunds",
        "metadata": {"id": "notes/contract.md", "source": "seed", "title": "Contract probe"},
    },
    "notes/second.md": {
        "text": "a second seeded record about customers",
        "metadata": {"id": "notes/second.md", "source": "seed", "title": "Second"},
    },
    "tables/orders.md": {
        "text": "orders table, one row per purchase",
        "metadata": {"id": "tables/orders.md", "source": "seed", "title": "Orders"},
    },
}

_TOKENS = re.compile(r"[^a-z0-9]+")
_MIN_TOKEN = 2


class FakeKnowledgeBase(KnowledgeBase):
    """Dependency-free reference backend, constructible in any capability shape.

    Records are stored verbatim, which is what lets the contract assert that unknown keys
    survive a write. Every operation delegates to the base when its capability is undeclared
    rather than being absent from the class, because the shape passed in — not the class —
    has to decide which operations raise.
    """

    def __init__(self, capabilities: KnowledgeCapabilities, name: str = "fake-kb", records: Optional[Mapping[str, Record]] = None) -> None:
        """
        Build a fake backend in the given capability shape.

        :param capabilities: What this instance claims to support.
        :param name: Backend name, also used in validation errors.
        :param records: Seed records keyed by id; defaults to ``FAKE_SEED_RECORDS``.
        :return: None.
        """
        super().__init__(capabilities=capabilities, name=name)
        # Assigned after super().__init__() on purpose, mirroring the shipped backends: it is
        # what proves the base never reads backend_name while constructing.
        self._name = name
        self._records: dict[str, dict] = {key: dict(value) for key, value in (records or FAKE_SEED_RECORDS).items()}
        self.connected = False
        self.closed = False

    @property
    def backend_name(self) -> str:
        """Return the name this instance was built with."""
        return self._name

    def connect(self, **kwargs) -> None:
        """Record that a connection was requested; there is nothing to connect to."""
        self.connected = True

    def get_description(self) -> str:
        """Describe the backend in the ``<name>: <description>`` shape the tools expect."""
        return f"{self.backend_name}: an in-memory reference knowledge base ({len(self._records)} record(s))"

    def search(self, query: str, limit: int = 3, **kwargs) -> List[Record]:
        """Rank records by how many of the query's tokens they contain."""
        if not self.capabilities.search:
            return super().search(query, limit=limit, **kwargs)
        tokens = self._tokenise(query)
        scored = [(len(tokens & self._record_tokens(record)), key) for key, record in self._records.items()]
        ranked = sorted(((score, key) for score, key in scored if score > 0), key=lambda pair: (-pair[0], pair[1]))
        return [dict(self._records[key]) for _, key in ranked[: max(limit, 0)]]

    def query(self, statement: str, limit: int = 3, **kwargs) -> List[Record]:
        """Run the toy ``fake-ql`` language: ``MATCH <substring>``, or everything."""
        if not self.capabilities.query:
            return super().query(statement, limit=limit, **kwargs)
        needle = statement.split(maxsplit=1)[1].lower() if statement.lower().startswith("match ") else ""
        matched = [dict(record) for key, record in sorted(self._records.items()) if needle in f"{record.get('text', '')}{key}".lower()]
        return matched[: max(limit, 0)]

    def fetch(self, ids: List[str], **kwargs) -> List[Record]:
        """Return records by id, in the order asked for, dropping unknown and duplicate ids."""
        if not self.capabilities.fetch:
            return super().fetch(ids, **kwargs)
        found: List[Record] = []
        seen: set[str] = set()
        for identity in ids or []:
            record = self._records.get(identity)
            # Unknown ids are omitted rather than raised: an agent guessing an id must not
            # lose the rest of the batch.
            if record is None or identity in seen:
                continue
            seen.add(identity)
            found.append(dict(record))
        return found

    def browse(self, path: str = "", limit: int = 50, **kwargs) -> List[Record]:
        """List the immediate children of a namespace, directories first."""
        if not self.capabilities.browse:
            return super().browse(path, limit=limit, **kwargs)
        prefix = f"{path.strip('/')}/" if path.strip("/") else ""
        directories: set[str] = set()
        concepts: List[Record] = []
        for key, record in self._records.items():
            if not key.startswith(prefix):
                continue
            head, separator, _ = key[len(prefix) :].partition("/")
            if separator:
                directories.add(head)
            else:
                concepts.append(dict(record))
        entries = [self._directory_record(prefix, name) for name in sorted(directories)]
        entries.extend(sorted(concepts, key=lambda record: record["metadata"]["id"]))
        return entries[: max(limit, 0)]

    def write(self, records: Iterable[Record], **kwargs) -> None:
        """Store records verbatim, synthesising an id for any record that carries none."""
        if not self.capabilities.writable:
            return super().write(records, **kwargs)
        for record in records or []:
            stored = dict(record)
            metadata = dict(stored.get("metadata", {}) or {})
            identity = metadata.get("id") or f"generated/{uuid.uuid4().hex[:8]}.md"
            metadata["id"] = identity
            stored["metadata"] = metadata
            self._records[identity] = stored

    def _derived_schema(self) -> Mapping[str, Any]:
        """Describe the held records, but only when the declaration promises it."""
        if not self.capabilities.derives_schema:
            return {}
        return {"record_count": len(self._records), "ids": sorted(self._records)}

    def close(self) -> None:
        """Record that the backend was closed; idempotent, like every real backend's."""
        self.closed = True

    @staticmethod
    def _directory_record(prefix: str, name: str) -> Record:
        """Build the record standing for a subdirectory of the browsed namespace."""
        identity = f"{prefix}{name}/"
        return {"text": identity, "metadata": {"id": identity, "source": identity, "title": name, "kind": "directory"}}

    @staticmethod
    def _tokenise(text: str) -> set[str]:
        """Reduce text to the tokens the toy ranker matches on."""
        return {token for token in _TOKENS.split(text.lower()) if len(token) >= _MIN_TOKEN}

    @classmethod
    def _record_tokens(cls, record: Mapping[str, Any]) -> set[str]:
        """Index a record's text, title and id together — the fake ranks over all three."""
        metadata = record.get("metadata", {}) or {}
        return cls._tokenise(f"{record.get('text', '')} {metadata.get('title', '')} {metadata.get('id', '')}")


def fake_vector_kb() -> FakeKnowledgeBase:
    """A ChromaManager-shaped fake: semantic search, writable, no fetch or browse."""
    return FakeKnowledgeBase(KnowledgeCapabilities(kinds=["vector"], search=True, search_mode="semantic", writable=True), name="fake-vector")


def fake_sql_kb() -> FakeKnowledgeBase:
    """A StarburstManager-shaped fake: read-only, reached through query()."""
    return FakeKnowledgeBase(KnowledgeCapabilities(kinds=["structured"], query=True, query_language="fake-ql", writable=False), name="fake-sql")


def fake_graph_kb() -> FakeKnowledgeBase:
    """A Neo4jManager-shaped fake: query plus writes, still no fetch."""
    return FakeKnowledgeBase(
        KnowledgeCapabilities(kinds=["graph", "structured"], query=True, query_language="fake-ql", writable=True), name="fake-graph"
    )


def fake_document_kb() -> FakeKnowledgeBase:
    """An OKFManager-shaped fake: the full document surface, schema derived."""
    return FakeKnowledgeBase(
        KnowledgeCapabilities(kinds=["document"], search=True, search_mode="lexical", fetch=True, browse=True, writable=True, derives_schema=True),
        name="fake-document",
    )


class _NamelessProbe(KnowledgeBase):
    """A backend whose ``backend_name`` is unusable until after ``super().__init__()``.

    Exists to pin the ordering ``KnowledgeBase.__init__`` documents in a comment: validation
    must report the subject it was handed, never reach for ``backend_name``. Every real
    backend is written this way, so getting it wrong turns a clear ``ValueError`` into an
    ``AttributeError`` from inside the base class.
    """

    def __init__(self, capabilities: KnowledgeCapabilities, name: str) -> None:
        """Validate before ``_name`` exists, which is exactly the risky order."""
        super().__init__(capabilities=capabilities, name=name)
        self._name = name

    @property
    def backend_name(self) -> str:
        """Read an attribute that only exists once construction completed."""
        return self._name

    def connect(self, **kwargs) -> None:
        """No connection to make."""

    def get_description(self) -> str:
        """Never reached: this probe is only ever constructed to fail."""
        return self._name


class KnowledgeBaseContract:
    """Reusable contract suite asserting ``KnowledgeBase`` semantics for any backend.

    Subclass in a test module and override the ``knowledge_base`` fixture::

        class TestMyBackendContract(KnowledgeBaseContract):
            @pytest.fixture
            def knowledge_base(self):
                return MyBackend(...)

    Every assertion is gated on the backend's *own* declaration, so a read-only backend, a
    backend with no ``fetch`` and a backend with the full surface all run the same suite and
    each is held only to what it claims. That is the whole point: the capability model is only
    load-bearing if declaring something obliges the backend to it.

    Override the input hooks below when the defaults do not address your backend's data.
    Not collected on its own — the class name is intentionally not prefixed ``Test``.
    """

    @pytest.fixture
    def knowledge_base(self) -> KnowledgeBase:
        """The backend under contract; every subclass must override this."""
        raise NotImplementedError("subclasses must override the `knowledge_base` fixture")

    def search_query(self) -> str:
        """Text that matches at least one record when ``search`` is declared."""
        return "contract"

    def query_statement(self) -> str:
        """A statement valid in the backend's declared ``query_language``."""
        return "SELECT 1"

    def browse_path(self) -> str:
        """A namespace that exists when ``browse`` is declared; ``""`` is the top level."""
        return ""

    def write_probe(self) -> tuple[Optional[str], Record]:
        """Return ``(id the record is retrievable under, the record to write)``.

        The id is ``None`` for a backend that synthesises one or stores something other than a
        document — the read-back assertion then skips rather than lying about what happened.
        """
        return ("contract-probe", {"text": "contract probe record", "metadata": {"id": "contract-probe", "source": "contract"}})

    def declared_ids(self, knowledge_base: KnowledgeBase) -> List[str]:
        """Ids the backend actually hands out, from ``search`` first and ``browse`` second.

        search before browse deliberately: a derived browse listing legitimately includes
        directory records whose ids name a namespace rather than a document, and those are
        not expected to fetch.
        """
        records: List[Record] = []
        if knowledge_base.capabilities.search:
            records = knowledge_base.search(self.search_query(), limit=5)
        if not records and knowledge_base.capabilities.browse:
            records = knowledge_base.browse(self.browse_path(), limit=5)
        return [record["metadata"]["id"] for record in records if isinstance(record.get("metadata"), Mapping) and record["metadata"].get("id")]

    def _assert_records(self, knowledge_base: KnowledgeBase, rows) -> None:
        """Assert the shape every operation's return value must have."""
        assert isinstance(rows, list)
        for record in rows:
            assert isinstance(record, Mapping)
            metadata = record.get("metadata")
            if metadata is None:
                continue
            assert isinstance(metadata, Mapping)
            if not knowledge_base.capabilities.fetch:
                continue
            # Ids only have to be usable on a backend that declares fetch — and there they
            # must survive fetch_kb's comma split, which is how the agent passes several.
            identity = metadata.get("id")
            assert isinstance(identity, str) and identity
            assert "," not in identity

    def test_contract_the_backend_ran_the_base_initialiser(self, knowledge_base: KnowledgeBase):
        # A backend that overrides __init__ without calling super() has no declaration at all,
        # and KnowledgeBuilder degrades it to "declares nothing" rather than raising. Caught
        # here instead, where it is still the backend author's problem.
        assert isinstance(knowledge_base.capabilities, KnowledgeCapabilities)
        assert hasattr(knowledge_base, "_dynamic_schema")

    def test_contract_the_live_declaration_is_coherent(self, knowledge_base: KnowledgeBase):
        # The declaration the backend is carrying now, which is not always the one it passed:
        # DocumentKnowledgeBase folds the store's writability into it after construction.
        assert KnowledgeBase.validate_capabilities(knowledge_base.capabilities, knowledge_base.backend_name) is None

    def test_contract_a_declaration_of_nothing_is_refused_naming_the_subject(self):
        with pytest.raises(ValueError, match="declares no capability") as excinfo:
            KnowledgeBase.validate_capabilities(KnowledgeCapabilities(), "probe-backend")

        assert "probe-backend" in str(excinfo.value)

    def test_contract_query_without_a_language_is_refused_naming_the_subject(self):
        with pytest.raises(ValueError, match="without a query_language") as excinfo:
            KnowledgeBase.validate_capabilities(KnowledgeCapabilities(query=True), "probe-backend")

        assert "probe-backend" in str(excinfo.value)

    def test_contract_a_language_without_query_is_refused_naming_the_subject(self):
        with pytest.raises(ValueError, match="without query=True") as excinfo:
            KnowledgeBase.validate_capabilities(KnowledgeCapabilities(search=True, query_language="sql"), "probe-backend")

        assert "probe-backend" in str(excinfo.value)

    def test_contract_reachability_is_reported_before_query_coherence(self):
        # A query_language with nothing declared is both unreachable and incoherent. Reporting
        # the missing capability first points the author at the cause; the dangling language
        # is a symptom of it, and mentioning that instead would send them to the wrong line.
        with pytest.raises(ValueError, match="declares no capability"):
            KnowledgeBase.validate_capabilities(KnowledgeCapabilities(query_language="sql"), "probe-backend")

    def test_contract_validation_never_reads_backend_name(self):
        # Backends assign the attributes backend_name depends on *after* super().__init__(),
        # so reaching for it during validation turns this ValueError into an AttributeError.
        with pytest.raises(ValueError, match="probe-backend"):
            _NamelessProbe(KnowledgeCapabilities(), "probe-backend")

    def test_contract_declared_operations_return_records(self, knowledge_base: KnowledgeBase):
        capabilities = knowledge_base.capabilities
        if capabilities.search:
            self._assert_records(knowledge_base, knowledge_base.search(self.search_query()))
        if capabilities.query:
            self._assert_records(knowledge_base, knowledge_base.query(self.query_statement()))
        if capabilities.browse:
            self._assert_records(knowledge_base, knowledge_base.browse(self.browse_path()))
        if capabilities.fetch:
            self._assert_records(knowledge_base, knowledge_base.fetch(self.declared_ids(knowledge_base)))
        if capabilities.writable:
            assert knowledge_base.write([self.write_probe()[1]]) is None

    @pytest.mark.parametrize(
        "operation, call",
        [
            ("search", lambda backend: backend.search("probe")),
            ("query", lambda backend: backend.query("probe")),
            ("fetch", lambda backend: backend.fetch(["probe"])),
            ("browse", lambda backend: backend.browse("")),
            ("write", lambda backend: backend.write([{"text": "probe"}])),
        ],
    )
    def test_contract_undeclared_operations_raise_naming_backend_and_operation(self, knowledge_base: KnowledgeBase, operation, call):
        capabilities = knowledge_base.capabilities
        # The flag is `writable`; the operation named in the error is `write`.
        declared = {
            "search": capabilities.search,
            "query": capabilities.query,
            "fetch": capabilities.fetch,
            "browse": capabilities.browse,
            "write": capabilities.writable,
        }
        if declared[operation]:
            pytest.skip(f"{knowledge_base.backend_name} declares {operation}")

        with pytest.raises(KnowledgeCapabilityError) as excinfo:
            call(knowledge_base)

        assert excinfo.value.subject == knowledge_base.backend_name
        assert excinfo.value.capability == operation

    def test_contract_every_operation_accepts_unknown_keyword_arguments(self, knowledge_base: KnowledgeBase):
        # Every signature carries **kwargs so a caller can pass a backend-specific option
        # without the base or a sibling backend having to know about it. A TypeError here
        # means one operation dropped it.
        calls = [
            lambda: knowledge_base.search(self.search_query(), contract_probe="ignored"),
            lambda: knowledge_base.query(self.query_statement(), contract_probe="ignored"),
            lambda: knowledge_base.fetch(self.declared_ids(knowledge_base), contract_probe="ignored"),
            lambda: knowledge_base.browse(self.browse_path(), contract_probe="ignored"),
            lambda: knowledge_base.write([self.write_probe()[1]], contract_probe="ignored"),
        ]
        for call in calls:
            try:
                call()
            except KnowledgeCapabilityError:
                # Undeclared: the base refused it, which is the other correct answer.
                continue

    def test_contract_a_fetch_backend_hands_out_usable_ids(self, knowledge_base: KnowledgeBase):
        if not knowledge_base.capabilities.fetch:
            pytest.skip(f"{knowledge_base.backend_name} does not declare fetch")
        identifiers = self.declared_ids(knowledge_base)

        assert identifiers
        for identity in identifiers:
            assert isinstance(identity, str) and identity
            assert "," not in identity

    def test_contract_a_declared_id_fetches_the_record_it_names(self, knowledge_base: KnowledgeBase):
        if not knowledge_base.capabilities.fetch:
            pytest.skip(f"{knowledge_base.backend_name} does not declare fetch")
        identity = self.declared_ids(knowledge_base)[0]

        records = knowledge_base.fetch([identity])

        assert len(records) == 1
        assert records[0]["metadata"]["id"] == identity

    def test_contract_fetch_omits_an_unknown_id_rather_than_raising(self, knowledge_base: KnowledgeBase):
        if not knowledge_base.capabilities.fetch:
            pytest.skip(f"{knowledge_base.backend_name} does not declare fetch")

        # Never an exception and never a placeholder record: an agent guessing an id must get
        # a shorter list, not a failed tool call.
        assert knowledge_base.fetch(["contract-no-such-id"]) == []

    def test_contract_write_tolerates_unknown_record_and_metadata_keys(self, knowledge_base: KnowledgeBase):
        if not knowledge_base.capabilities.writable:
            pytest.skip(f"{knowledge_base.backend_name} is not writable")
        _, record = self.write_probe()
        augmented = dict(record)
        augmented[UNKNOWN_RECORD_KEY] = "tolerated"
        augmented["metadata"] = {**dict(record.get("metadata", {}) or {}), UNKNOWN_METADATA_KEY: "tolerated"}

        # Record is a Mapping[str, Any]: a backend must ignore what it does not recognise
        # rather than validate the shape it was handed.
        assert knowledge_base.write([augmented]) is None

    def test_contract_unknown_metadata_survives_a_write_then_fetch(self, knowledge_base: KnowledgeBase):
        capabilities = knowledge_base.capabilities
        identity, record = self.write_probe()
        if not (capabilities.writable and capabilities.fetch and identity):
            pytest.skip(f"{knowledge_base.backend_name} cannot read back what it writes")
        augmented = dict(record)
        augmented["metadata"] = {**dict(record.get("metadata", {}) or {}), UNKNOWN_METADATA_KEY: "round-tripped"}

        knowledge_base.write([augmented])
        fetched = knowledge_base.fetch([identity])

        assert len(fetched) == 1
        assert fetched[0]["metadata"].get(UNKNOWN_METADATA_KEY) == "round-tripped"

    def test_contract_schema_is_callable_and_returns_a_mapping(self, knowledge_base: KnowledgeBase):
        # The regression guard for StarburstManager, where a `schema` string attribute
        # shadowed the method and made get_schemas raise TypeError for every deployment.
        assert callable(knowledge_base.schema)

        knowledge_base.add_schema({"contract": "probe"})

        assert isinstance(knowledge_base.schema(), Mapping)

    def test_contract_schema_carries_the_backend_and_the_declaration(self, knowledge_base: KnowledgeBase):
        knowledge_base.add_schema({"contract": "probe"})
        schema = knowledge_base.schema()

        assert schema["backend"] == knowledge_base.backend_name
        assert schema["capabilities"] == knowledge_base.capabilities.model_dump()

    def test_contract_capabilities_cannot_be_overridden_through_add_schema(self, knowledge_base: KnowledgeBase):
        # The declaration is prompt-visible, so a backend must not be able to advertise a
        # capability it does not have by writing one into its schema.
        knowledge_base.add_schema({"capabilities": "forged"})

        assert knowledge_base.schema()["capabilities"] == knowledge_base.capabilities.model_dump()

    def test_contract_deriving_a_schema_means_deriving_something(self, knowledge_base: KnowledgeBase):
        if not knowledge_base.capabilities.derives_schema:
            pytest.skip(f"{knowledge_base.backend_name} does not derive a schema")

        # _derived_schema is the ABC's documented extension point, so reaching for it here is
        # reading the contract, not the implementation.
        assert dict(knowledge_base._derived_schema())
        # And the payoff: schema() answers with no add_schema() call at all.
        assert isinstance(knowledge_base.schema(), Mapping)

    def test_contract_read_routes_on_the_declaration(self, knowledge_base: KnowledgeBase, monkeypatch):
        # Spied rather than compared by result: a backend whose two operations happened to
        # return the same rows would otherwise pass with a broken router.
        routed = []
        target = "query" if knowledge_base.capabilities.query else "search"
        other = "search" if knowledge_base.capabilities.query else "query"

        def record_call(text, limit=3, **kwargs):
            routed.append((target, text, limit, kwargs))
            return []

        def refuse(text, limit=3, **kwargs):
            pytest.fail(f"read() routed to {other} on a backend declaring query={knowledge_base.capabilities.query}")

        monkeypatch.setattr(knowledge_base, target, record_call)
        monkeypatch.setattr(knowledge_base, other, refuse)

        knowledge_base.read("probe", limit=7, extra="forwarded")

        assert routed == [(target, "probe", 7, {"extra": "forwarded"})]

    def test_contract_read_returns_records_through_the_real_operation(self, knowledge_base: KnowledgeBase):
        text = self.query_statement() if knowledge_base.capabilities.query else self.search_query()

        self._assert_records(knowledge_base, knowledge_base.read(text))

    def test_contract_get_description_names_the_backend(self, knowledge_base: KnowledgeBase):
        description = knowledge_base.get_description()

        assert isinstance(description, str) and description
        assert knowledge_base.backend_name in description

    def test_contract_format_results_of_nothing_is_the_shared_sentinel(self, knowledge_base: KnowledgeBase):
        # An override must keep the sentinel: it is the string every agent prompt is written
        # against, so a backend answering differently changes behaviour it does not own.
        assert knowledge_base.format_results([]) == "No relevant knowledge found."

    def test_contract_format_results_renders_the_rows_the_backend_produced(self, knowledge_base: KnowledgeBase):
        # Catches an override that raises on a record shape its own operation emits.
        text = self.query_statement() if knowledge_base.capabilities.query else self.search_query()
        rendered = knowledge_base.format_results(knowledge_base.read(text))

        assert isinstance(rendered, str) and rendered

    def test_contract_close_is_idempotent(self, knowledge_base: KnowledgeBase):
        knowledge_base.close()
        knowledge_base.close()
