"""The public surface of ``agentkernel.knowledgebase`` (#553 iteration 7).

Two promises are pinned here. The documented import at ``docs/docs/core-concepts/overview.md``
must work — it did not before this iteration, because the package exported nothing the OKF
tier added. And touching that surface must stay free of every optional SDK: an application
reading a local bundle should not need ``boto3`` installed, and one using Chroma should not
pay for ``trino``.

The isolation assertions unload both ``agentkernel`` and the SDKs before importing, because by
the time this module runs some earlier test has almost certainly imported them and a bare
``in sys.modules`` check would prove nothing. ``ModuleIsolation`` restores the session exactly
as it found it. The purge shape follows ``test_aws_lazy_exports.py``, widened to the SDKs
because here it is a third-party import, not a sibling submodule, that must stay unloaded.
"""

import sys

import pytest

import agentkernel.knowledgebase as knowledgebase

# Every optional SDK the knowledge-base tier can reach. None may be imported as a side effect
# of importing the package or of touching a name that does not need it.
OPTIONAL_SDKS = ["boto3", "chromadb", "neo4j", "trino"]

# Names reachable without any optional SDK — the whole surface except S3DocumentStore, which
# is exported precisely so that boto3 stays lazy rather than absent.
SDK_FREE_EXPORTS = [name for name in knowledgebase.__all__ if name != "S3DocumentStore"]


class ModuleIsolation:
    """Unload a set of top-level packages, then put ``sys.modules`` back as it was.

    Import laziness can only be observed from a state where the module is genuinely absent,
    and pytest sessions share one interpreter, so the unload has to be undone or every later
    test inherits half-torn-down packages.
    """

    def __init__(self, *roots: str) -> None:
        """Isolate the named top-level packages and their submodules."""
        self._roots = roots
        self._saved: dict = {}

    def _matches(self, name: str) -> bool:
        return any(name == root or name.startswith(f"{root}.") for root in self._roots)

    def __enter__(self) -> "ModuleIsolation":
        self._saved = {name: module for name, module in sys.modules.items() if self._matches(name)}
        for name in self._saved:
            del sys.modules[name]
        return self

    def __exit__(self, *exc_info) -> None:
        for name in [name for name in sys.modules if self._matches(name)]:
            del sys.modules[name]
        sys.modules.update(self._saved)

    @staticmethod
    def loaded_sdks() -> list[str]:
        """Return the optional SDKs currently imported, for assertion messages worth reading."""
        return [sdk for sdk in OPTIONAL_SDKS if sdk in sys.modules]


@pytest.fixture
def clean_import():
    """Yield ``agentkernel.knowledgebase`` imported with agentkernel and the SDKs unloaded."""
    with ModuleIsolation("agentkernel", *OPTIONAL_SDKS):
        import agentkernel.knowledgebase as fresh

        yield fresh


def test_every_exported_name_resolves():
    for name in knowledgebase.__all__:
        assert getattr(knowledgebase, name) is not None


def test_dir_reports_the_exported_names():
    assert dir(knowledgebase) == sorted(knowledgebase.__all__)


def test_an_unexported_name_raises_attribute_error():
    with pytest.raises(AttributeError, match="ChromaManager"):
        knowledgebase.ChromaManager


@pytest.mark.parametrize("name", ["ChromaManager", "Neo4jManager", "StarburstManager"])
def test_sdk_backed_managers_are_not_exported(name: str):
    # Lazy or not, exporting these would make an SDK a hard requirement the moment an
    # application touched the name. They stay behind their concrete modules.
    assert name not in knowledgebase.__all__


def test_the_documented_import_works(clean_import):
    # docs/docs/core-concepts/overview.md tells readers to write exactly this.
    from agentkernel.knowledgebase import KnowledgeBase

    assert KnowledgeBase is clean_import.KnowledgeBase


def test_importing_the_package_loads_no_optional_sdk(clean_import):
    assert ModuleIsolation.loaded_sdks() == []


def test_the_sdk_free_surface_loads_no_optional_sdk(clean_import):
    for name in SDK_FREE_EXPORTS:
        getattr(clean_import, name)

    assert ModuleIsolation.loaded_sdks() == []


def test_the_okf_backend_does_not_reach_the_s3_store(clean_import):
    # OKFManager composes a DocumentStore it is handed, so reading a local bundle must not
    # drag in the S3 implementation — the point of splitting the storage axis out.
    clean_import.OKFManager

    assert "agentkernel.knowledgebase.store.s3" not in sys.modules


def test_the_s3_store_resolves_and_is_what_loads_boto3(clean_import):
    # boto3 is a dependency of the `aws` extra, which the test environment installs; the
    # promise is that it is imported on demand, not that it is unreachable.
    assert ModuleIsolation.loaded_sdks() == []

    assert clean_import.S3DocumentStore.__name__ == "S3DocumentStore"
    assert "boto3" in sys.modules
