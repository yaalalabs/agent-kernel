"""Reusable contract suites for knowledge-base backends and document stores.

``DocumentStoreContract`` asserts the semantics every
:class:`agentkernel.knowledgebase.store.base.DocumentStore` must honor. Subclass it in a
test module and override the ``store`` and ``read_only_store`` fixtures; it is deliberately
NOT named ``Test*`` so pytest does not collect it on its own, and this module is not named
``test_*`` so pytest does not collect the module either.

It lives under ``tests/`` rather than in the package, so it is a suite this repo holds its
own backends to — not a published helper for out-of-tree backend authors.
"""

import pytest

from agentkernel.knowledgebase.errors import KnowledgeCapabilityError, KnowledgePathError
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
