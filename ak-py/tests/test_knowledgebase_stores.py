"""DocumentStore — the storage axis (#553 iteration 4).

Nothing consumes DocumentStore yet, which is exactly why the guarantees are pinned here:
OKFManager will lean on all three of them. Containment is the security-relevant one — a
store path is an agent-supplied string that becomes a filesystem path or an object key, and
the paths are not only agent-supplied (a manifest walk emits them, a link inside a document
becomes one). Global lexicographic ordering is the one that makes max_concepts truncation
identical across pods. Interchangeability is what lets a bundle move from a directory to S3.

No test touches a live bucket; the S3 store runs against an in-memory fake client that
raises real botocore ClientErrors and pages its listings.
"""

import os
import sys

import pytest
from botocore.exceptions import ClientError
from knowledgebase_contracts import CONTRACT_TREE, DocumentStoreContract

from agentkernel.core.util.factory import AKConfigError
from agentkernel.knowledgebase.errors import KnowledgeCapabilityError, KnowledgePathError
from agentkernel.knowledgebase.store import DocumentStore, LocalDocumentStore
from agentkernel.knowledgebase.store.s3 import S3DocumentStore


def _client_error(code: str, operation: str = "GetObject") -> ClientError:
    return ClientError({"Error": {"Code": code, "Message": code}}, operation)


class FakeS3Body:
    def __init__(self, data: bytes) -> None:
        self._data = data

    def read(self) -> bytes:
        return self._data


class FakeS3Client:
    """In-memory S3 stand-in: real ClientErrors, ranged GETs, and paged listings."""

    def __init__(self, page_size: int = 2) -> None:
        self.objects: dict[str, bytes] = {}
        self.page_size = page_size
        self.get_ranges: list[str] = []
        self.list_calls: list[dict] = []

    def put_object(self, Bucket: str, Key: str, Body: bytes):  # noqa: N803 - boto3 casing
        self.objects[Key] = Body
        return {}

    def get_object(self, Bucket: str, Key: str, Range: str = ""):  # noqa: N803 - boto3 casing
        if Key not in self.objects:
            raise _client_error("NoSuchKey")

        data = self.objects[Key]
        if not Range:
            return {"Body": FakeS3Body(data)}

        self.get_ranges.append(Range)
        if not data:
            # S3 rejects any range against a zero-length object.
            raise _client_error("InvalidRange")
        start, _, end = Range.removeprefix("bytes=").partition("-")
        return {"Body": FakeS3Body(data[int(start) : int(end) + 1])}

    def head_object(self, Bucket: str, Key: str):  # noqa: N803 - boto3 casing
        if Key not in self.objects:
            raise _client_error("404", "HeadObject")
        return {"ContentLength": len(self.objects[Key])}

    def list_objects_v2(self, Bucket: str, Prefix: str = "", ContinuationToken: str = ""):  # noqa: N803 - boto3 casing
        self.list_calls.append({"Prefix": Prefix, "ContinuationToken": ContinuationToken})
        # Deliberately NOT sorted: the store must not inherit the client's ordering.
        keys = [key for key in reversed(list(self.objects)) if key.startswith(Prefix)]
        start = int(ContinuationToken) if ContinuationToken else 0
        page = keys[start : start + self.page_size]
        next_start = start + self.page_size
        truncated = next_start < len(keys)
        return {
            "Contents": [{"Key": key} for key in page],
            "IsTruncated": truncated,
            **({"NextContinuationToken": str(next_start)} if truncated else {}),
        }


class TestLocalDocumentStoreContract(DocumentStoreContract):
    """Run the store contract against a real directory tree."""

    @pytest.fixture
    def store(self, tmp_path) -> LocalDocumentStore:
        return LocalDocumentStore(str(tmp_path), writable=True)

    @pytest.fixture
    def read_only_store(self, tmp_path) -> LocalDocumentStore:
        return LocalDocumentStore(str(tmp_path), writable=False)


class TestS3DocumentStoreContract(DocumentStoreContract):
    """Run the same contract against the S3 store, under a non-empty key prefix."""

    @pytest.fixture
    def store(self) -> S3DocumentStore:
        return S3DocumentStore("bucket", "bundles/kb", client=FakeS3Client(), writable=True)

    @pytest.fixture
    def read_only_store(self) -> S3DocumentStore:
        return S3DocumentStore("bucket", "bundles/kb", client=FakeS3Client(), writable=False)


class TestNormaliseRelative:
    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("", ""),
            ("   ", ""),
            (".", ""),
            ("./", ""),
            ("a.md", "a.md"),
            ("  a.md  ", "a.md"),
            ("a//b.md", "a/b.md"),
            ("a/./b.md", "a/b.md"),
            ("a/x/../b.md", "a/b.md"),
            ("a\\b.md", "a/b.md"),
        ],
    )
    def test_benign_paths_reduce_to_a_posix_relative_path(self, raw: str, expected: str):
        assert DocumentStore.normalise_relative(raw) == expected

    @pytest.mark.parametrize("raw", ["/etc/passwd", "/", "  /abs.md"])
    def test_an_absolute_path_is_refused_by_name(self, raw: str):
        with pytest.raises(KnowledgePathError, match="absolute path"):
            DocumentStore.normalise_relative(raw)

    @pytest.mark.parametrize("raw", ["..", "../x.md", "a/../../x.md", "..\\x.md"])
    def test_an_escaping_path_is_refused_by_name(self, raw: str):
        with pytest.raises(KnowledgePathError, match="escapes the store namespace"):
            DocumentStore.normalise_relative(raw)


class TestLocalDocumentStore:
    def test_a_missing_root_is_a_construction_error(self, tmp_path):
        with pytest.raises(ValueError, match="not an existing directory"):
            LocalDocumentStore(str(tmp_path / "nope"))

    def test_a_file_as_root_is_a_construction_error(self, tmp_path):
        target = tmp_path / "a-file"
        target.write_text("x")
        with pytest.raises(ValueError, match="not an existing directory"):
            LocalDocumentStore(str(target))

    def test_writable_is_probed_when_not_declared(self, tmp_path):
        assert LocalDocumentStore(str(tmp_path)).writable is True

    def test_a_declared_writable_flag_wins_over_the_probe(self, tmp_path):
        # The probe would say True; the declaration is what an application controls.
        assert LocalDocumentStore(str(tmp_path), writable=False).writable is False

    @pytest.mark.skipif(getattr(os, "geteuid", lambda: 1)() == 0, reason="root ignores the write bit")
    def test_an_unwritable_directory_probes_as_read_only(self, tmp_path):
        root = tmp_path / "ro"
        root.mkdir()
        root.chmod(0o500)
        try:
            assert LocalDocumentStore(str(root)).writable is False
        finally:
            root.chmod(0o700)

    def test_a_refused_write_never_touches_disk(self, tmp_path):
        store = LocalDocumentStore(str(tmp_path), writable=False)
        with pytest.raises(KnowledgeCapabilityError):
            store.write_bytes("notes/one.md", b"payload")
        assert list(tmp_path.iterdir()) == []

    def test_list_sorts_globally_not_per_directory(self, tmp_path):
        store = LocalDocumentStore(str(tmp_path))
        for path in ("a/z.md", "ab/b.md", "a/a.md"):
            store.write_bytes(path, b"x")

        # os.walk yields directory "a" fully before "ab", so a naive walk order would put
        # a/z.md before ab/b.md by accident; here it must hold by sort, for every pair.
        assert store.list() == ["a/a.md", "a/z.md", "ab/b.md"]

    def test_write_bytes_creates_parent_directories(self, tmp_path):
        store = LocalDocumentStore(str(tmp_path))
        store.write_bytes("deep/nested/one.md", b"payload")
        assert (tmp_path / "deep" / "nested" / "one.md").read_bytes() == b"payload"

    def test_read_prefix_bytes_reads_only_the_prefix(self, tmp_path):
        store = LocalDocumentStore(str(tmp_path))
        store.write_bytes("doc.md", b"0123456789")
        assert store.read_prefix_bytes("doc.md", 3) == b"012"


class TestBaseReadPrefixBytes:
    """The default a store inherits when its transport cannot serve a partial read."""

    class WholeReadStore(LocalDocumentStore):
        """Drops the local override, so the base default does the slicing."""

        read_prefix_bytes = DocumentStore.read_prefix_bytes

    def test_the_default_slices_the_leading_bytes(self, tmp_path):
        store = self.WholeReadStore(str(tmp_path), writable=True)
        store.write_bytes("doc.md", b"0123456789")
        assert store.read_prefix_bytes("doc.md", 4) == b"0123"

    @pytest.mark.parametrize("max_bytes", [0, -1])
    def test_the_default_returns_nothing_for_a_non_positive_size(self, tmp_path, max_bytes: int):
        # A negative size would otherwise slice from the end, which is not a prefix at all.
        store = self.WholeReadStore(str(tmp_path), writable=True)
        store.write_bytes("doc.md", b"0123456789")
        assert store.read_prefix_bytes("doc.md", max_bytes) == b""


@pytest.mark.skipif(sys.platform == "win32", reason="symlink creation needs privileges on Windows")
class TestLocalDocumentStoreSymlinks:
    @pytest.fixture
    def escaping_symlink(self, tmp_path):
        """A bundle root containing a symlink that points at a file outside it."""
        outside = tmp_path / "outside"
        outside.mkdir()
        secret = outside / "secret.md"
        secret.write_text("credentials")

        root = tmp_path / "bundle"
        root.mkdir()
        (root / "ok.md").write_text("fine")
        (root / "escape.md").symlink_to(secret)
        return LocalDocumentStore(str(root))

    def test_the_walk_skips_a_symlink_resolving_outside_the_root(self, escaping_symlink):
        assert escaping_symlink.list() == ["ok.md"]

    def test_a_direct_read_through_the_symlink_is_refused(self, escaping_symlink):
        with pytest.raises(KnowledgePathError, match="resolves outside"):
            escaping_symlink.read_bytes("escape.md")

    def test_a_symlink_staying_inside_the_root_is_served(self, tmp_path):
        root = tmp_path / "bundle"
        (root / "real").mkdir(parents=True)
        (root / "real" / "one.md").write_text("inside")
        (root / "link.md").symlink_to(root / "real" / "one.md")

        store = LocalDocumentStore(str(root))
        assert store.read_bytes("link.md") == b"inside"
        assert store.list() == ["link.md", "real/one.md"]


class TestS3DocumentStore:
    @pytest.fixture
    def client(self) -> FakeS3Client:
        return FakeS3Client()

    @pytest.fixture
    def store(self, client) -> S3DocumentStore:
        return S3DocumentStore("bucket", "bundles/kb", client=client)

    def test_a_bucket_is_required(self):
        with pytest.raises(ValueError, match="requires a bucket"):
            S3DocumentStore("", client=FakeS3Client())

    def test_paths_are_written_under_the_configured_prefix(self, store, client):
        store.write_bytes("tables/orders.md", b"payload")
        assert list(client.objects) == ["bundles/kb/tables/orders.md"]

    def test_listed_keys_come_back_as_store_relative_paths(self, store):
        store.write_bytes("tables/orders.md", b"a")
        store.write_bytes("root.md", b"b")
        assert store.list() == ["root.md", "tables/orders.md"]

    def test_a_store_without_a_prefix_uses_bare_keys(self, client):
        store = S3DocumentStore("bucket", client=client)
        store.write_bytes("root.md", b"payload")
        assert list(client.objects) == ["root.md"]
        assert store.list() == ["root.md"]

    def test_listing_pages_until_the_response_is_not_truncated(self, store, client):
        for index in range(5):
            store.write_bytes(f"doc{index}.md", b"x")

        # page_size is 2, so five objects need three pages.
        assert store.list() == [f"doc{index}.md" for index in range(5)]
        assert len(client.list_calls) == 3
        assert [call["ContinuationToken"] for call in client.list_calls] == ["", "2", "4"]

    def test_listing_scopes_the_request_to_the_namespace(self, store, client):
        store.list("tables")
        assert client.list_calls[0]["Prefix"] == "bundles/kb/tables/"

    def test_keys_outside_the_store_prefix_are_dropped(self, store, client):
        client.objects["other-bundle/leak.md"] = b"not ours"
        client.objects["bundles/kb/ours.md"] = b"ours"
        # Reached by asking for everything under the store root.
        assert store.list() == ["ours.md"]

    def test_a_folder_marker_key_is_not_a_document(self, store, client):
        client.objects["bundles/kb/tables/"] = b""
        client.objects["bundles/kb/tables/orders.md"] = b"payload"
        assert store.list() == ["tables/orders.md"]

    def test_a_missing_key_becomes_file_not_found(self, store):
        with pytest.raises(FileNotFoundError, match="no such object"):
            store.read_bytes("nothing.md")

    def test_an_unrelated_client_error_propagates(self, store, client):
        def denied(**kwargs):
            raise _client_error("AccessDenied")

        client.get_object = denied
        with pytest.raises(ClientError):
            store.read_bytes("anything.md")

    def test_exists_is_false_for_a_missing_key_and_raises_for_anything_else(self, store, client):
        assert store.exists("nothing.md") is False

        def denied(**kwargs):
            raise _client_error("AccessDenied", "HeadObject")

        client.head_object = denied
        with pytest.raises(ClientError):
            store.exists("anything.md")

    def test_read_prefix_bytes_issues_a_ranged_get(self, store, client):
        store.write_bytes("doc.md", b"0123456789")
        assert store.read_prefix_bytes("doc.md", 4) == b"0123"
        # The whole point of the override: 4 bytes requested, 4 bytes transferred.
        assert client.get_ranges == ["bytes=0-3"]

    def test_a_zero_length_object_falls_back_to_a_full_read(self, store):
        store.write_bytes("empty.md", b"")
        assert store.read_prefix_bytes("empty.md", 16) == b""

    def test_a_non_positive_prefix_length_never_calls_s3(self, store, client):
        assert store.read_prefix_bytes("doc.md", 0) == b""
        assert client.get_ranges == []

    def test_writable_is_declared_and_never_probed(self, client):
        assert S3DocumentStore("bucket", client=client).writable is True
        assert S3DocumentStore("bucket", client=client, writable=False).writable is False


class LocalSubclassStore(LocalDocumentStore):
    """A bring-your-own store, used to exercise the python: discriminator."""


class NotAStore:
    """Deliberately not a DocumentStore subclass."""


class TestFromUri:
    def test_a_bare_path_resolves_to_a_local_store(self, tmp_path):
        store = DocumentStore.from_uri(str(tmp_path))
        assert isinstance(store, LocalDocumentStore)

    def test_a_file_uri_resolves_to_a_local_store_rooted_at_the_path(self, tmp_path):
        (tmp_path / "one.md").write_bytes(b"payload")
        store = DocumentStore.from_uri(f"file://{tmp_path}")
        assert isinstance(store, LocalDocumentStore)
        assert store.read_bytes("one.md") == b"payload"

    def test_kwargs_reach_the_local_constructor(self, tmp_path):
        assert DocumentStore.from_uri(str(tmp_path), writable=False).writable is False

    def test_an_s3_uri_splits_bucket_from_prefix(self):
        client = FakeS3Client()
        store = DocumentStore.from_uri("s3://my-bucket/bundles/kb", client=client)
        assert isinstance(store, S3DocumentStore)
        store.write_bytes("one.md", b"payload")
        assert list(client.objects) == ["bundles/kb/one.md"]

    def test_an_s3_uri_without_a_prefix_is_the_bucket_root(self):
        client = FakeS3Client()
        store = DocumentStore.from_uri("s3://my-bucket", client=client)
        store.write_bytes("one.md", b"payload")
        assert list(client.objects) == ["one.md"]

    def test_an_s3_uri_without_a_bucket_is_a_config_error(self):
        with pytest.raises(AKConfigError, match="needs a bucket"):
            DocumentStore.from_uri("s3:///just-a-prefix")

    def test_the_python_discriminator_resolves_a_custom_store(self, tmp_path):
        store = DocumentStore.from_uri(f"python:{__name__}.LocalSubclassStore", root=str(tmp_path))
        assert isinstance(store, LocalSubclassStore)

    def test_the_python_discriminator_rejects_a_non_store(self):
        with pytest.raises(AKConfigError, match="not a DocumentStore subclass"):
            DocumentStore.from_uri(f"python:{__name__}.NotAStore")

    def test_the_python_discriminator_rejects_an_unimportable_path(self):
        with pytest.raises(AKConfigError, match="could not import"):
            DocumentStore.from_uri("python:no.such.module.Store")

    def test_a_dotted_path_without_the_discriminator_is_treated_as_a_filesystem_path(self):
        # This is exactly why the discriminator is mandatory: a dotted path IS a valid
        # bare path, so an inferred rule would silently root a local store at a directory
        # that does not exist instead of loading the class.
        with pytest.raises(ValueError, match="not an existing directory"):
            DocumentStore.from_uri("mypkg.stores.GitStore")

    @pytest.mark.parametrize("uri", ["git://host/repo", "https://example.com/kb", "gs://bucket/prefix"])
    def test_an_unknown_scheme_is_a_config_error(self, uri: str):
        with pytest.raises(AKConfigError, match="unsupported document store scheme"):
            DocumentStore.from_uri(uri)


def test_the_contract_tree_is_what_the_ordering_assertions_need():
    """Guards the fixture data itself: drop 'a/z.md' or 'ab/b.md' and the contract goes quiet."""
    assert {"a/z.md", "ab/b.md", "tables/orders.md", "tables_extra/x.md"} <= set(CONTRACT_TREE)
