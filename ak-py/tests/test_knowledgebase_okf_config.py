"""The `okf` configuration block and OKFCapabilityManager (#553 iteration 11).

Two things here are worth more than the rest. First, the compatibility assertion: a config file
written before this change must still parse, with `okf` absent meaning the capability is off —
that is what lets the block ship without touching a single existing deployment. Second, the
type/uri agreement check, which exists only because `type` is deliberately redundant with the
uri's scheme; the redundancy is only safe while the check is.

No test constructs an S3DocumentStore. The s3 branch is asserted through the agreement checks
and a monkeypatched from_uri, so the suite stays offline.
"""

import logging

import pytest

from agentkernel.core.config import AKConfig, _OKFConfig, _OKFDatabaseConfig
from agentkernel.core.util.factory import AKConfigError
from agentkernel.knowledgebase.okf.capability import OKFCapabilityManager
from agentkernel.knowledgebase.store.base import DocumentStore
from agentkernel.knowledgebase.store.local import LocalDocumentStore


@pytest.fixture(autouse=True)
def reset_singletons():
    # A process-wide singleton left populated by one test silently changes the next, the
    # ScheduleManager.reset() precedent.
    AKConfig._reset()
    OKFCapabilityManager.reset()
    yield
    AKConfig._reset()
    OKFCapabilityManager.reset()


def _manager(databases: dict) -> OKFCapabilityManager:
    """Build a manager directly from parsed config, bypassing the AKConfig singleton."""
    return OKFCapabilityManager(_OKFConfig(databases=databases))


def _bundle(tmp_path, name: str = "bundle"):
    """An empty directory that LocalDocumentStore will accept as a root."""
    root = tmp_path / name
    root.mkdir()
    return root


class TestConfigModel:
    def test_the_capability_is_absent_by_default(self, monkeypatch):
        monkeypatch.setenv("AK_CONFIG_PATH_OVERRIDE", "/nonexistent/config.yaml")

        assert AKConfig.get().okf is None

    def test_a_config_file_written_before_this_change_still_parses(self, tmp_path, monkeypatch):
        # The compatibility promise the whole block rests on: no existing deployment changes.
        cfg = tmp_path / "config.yaml"
        cfg.write_text("session:\n  type: in_memory\napi:\n  port: 8080\n")
        monkeypatch.setenv("AK_CONFIG_PATH_OVERRIDE", str(cfg))

        config = AKConfig.get()

        assert config.okf is None
        assert config.session.type == "in_memory"

    def test_the_block_parses_from_yaml(self, tmp_path, monkeypatch):
        cfg = tmp_path / "config.yaml"
        cfg.write_text(
            "okf:\n"
            "  databases:\n"
            "    warehouse:\n"
            "      type: local\n"
            "      uri: ./bundle\n"
            "      description: Sales knowledge\n"
            "      refresh_seconds: 60\n"
            "      semantic_map:\n"
            '        "<TABLES>": tables\n'
            "      consumer: [reader]\n"
            "      producer: [writer]\n"
            "      curator: [keeper]\n"
        )
        monkeypatch.setenv("AK_CONFIG_PATH_OVERRIDE", str(cfg))

        database = AKConfig.get().okf.databases["warehouse"]

        assert (database.type, database.uri) == ("local", "./bundle")
        assert database.description == "Sales knowledge"
        assert database.refresh_seconds == 60
        assert database.semantic_map == {"<TABLES>": "tables"}
        assert (database.consumer, database.producer, database.curator) == (["reader"], ["writer"], ["keeper"])

    def test_the_block_materialises_from_env_vars(self, monkeypatch):
        # As with AK_THREAD__* and AK_SCHEDULE__*, any such variable enables the capability.
        monkeypatch.setenv("AK_CONFIG_PATH_OVERRIDE", "/nonexistent/config.yaml")
        monkeypatch.setenv("AK_OKF__DATABASES", '{"warehouse": {"type": "local", "uri": "./bundle", "consumer": ["reader"]}}')

        config = AKConfig.get()

        assert config.okf is not None
        assert config.okf.databases["warehouse"].consumer == ["reader"]

    def test_an_env_materialised_block_with_no_databases_is_inert_not_wrong(self, monkeypatch):
        monkeypatch.setenv("AK_CONFIG_PATH_OVERRIDE", "/nonexistent/config.yaml")
        monkeypatch.setenv("AK_OKF__DATABASES", "{}")

        config = AKConfig.get()

        assert config.okf is not None
        # No agent holds a role, so every agent gets no tools and no prompt.
        assert OKFCapabilityManager(config.okf).roles.has_any_role("anyone") is False

    def test_every_optional_field_has_its_documented_default(self):
        database = _OKFDatabaseConfig(type="local", uri="./bundle")

        assert database.description is None
        assert database.refresh_seconds == 300.0
        assert database.semantic_map is None
        assert (database.consumer, database.producer, database.curator) == (None, None, None)

    def test_an_omitted_role_list_is_distinguishable_from_an_empty_one(self):
        # None means "not declared" and [] means "declared empty". Both end up rejected by
        # from_config when no role names anyone, but only the first is what an ordinary config
        # file produces, and conflating them would hide a deliberately emptied list.
        declared_empty = _OKFDatabaseConfig(type="local", uri="./bundle", consumer=[])

        assert declared_empty.consumer == []
        assert declared_empty.producer is None

    def test_refresh_seconds_null_survives_as_none(self, tmp_path, monkeypatch):
        # null disables automatic refresh entirely; it must not fall back to the 300s default.
        cfg = tmp_path / "config.yaml"
        cfg.write_text("okf:\n  databases:\n    warehouse:\n      type: local\n      uri: ./b\n      refresh_seconds: null\n      consumer: [r]\n")
        monkeypatch.setenv("AK_CONFIG_PATH_OVERRIDE", str(cfg))

        assert AKConfig.get().okf.databases["warehouse"].refresh_seconds is None

    def test_type_and_uri_are_required(self):
        with pytest.raises(ValueError):
            _OKFDatabaseConfig(uri="./bundle")
        with pytest.raises(ValueError):
            _OKFDatabaseConfig(type="local")

    def test_every_field_carries_a_description(self):
        # They become user documentation; a field without one is invisible to a reader.
        for name, field in _OKFDatabaseConfig.model_fields.items():
            assert field.description, f"{name} has no description"
        assert _OKFConfig.model_fields["databases"].description


class TestSingleton:
    def test_get_returns_none_when_no_block_is_configured(self, monkeypatch):
        monkeypatch.setenv("AK_CONFIG_PATH_OVERRIDE", "/nonexistent/config.yaml")

        assert OKFCapabilityManager.get() is None

    def test_get_builds_once_and_caches(self, monkeypatch):
        base = AKConfig.get()
        block = _OKFConfig(databases={"warehouse": _OKFDatabaseConfig(type="local", uri="./b", consumer=["reader"])})
        monkeypatch.setattr(AKConfig, "get", classmethod(lambda cls: base.model_copy(update={"okf": block})))

        first = OKFCapabilityManager.get()

        assert first is not None
        assert OKFCapabilityManager.get() is first

    def test_reset_makes_the_next_get_rebuild(self, monkeypatch):
        base = AKConfig.get()
        block = _OKFConfig(databases={"warehouse": _OKFDatabaseConfig(type="local", uri="./b", consumer=["reader"])})
        monkeypatch.setattr(AKConfig, "get", classmethod(lambda cls: base.model_copy(update={"okf": block})))

        first = OKFCapabilityManager.get()
        OKFCapabilityManager.reset()

        assert OKFCapabilityManager.get() is not first

    def test_a_role_conflict_surfaces_from_get(self, monkeypatch):
        # Validation runs at construction, so an unusable block fails as soon as anything
        # reaches the capability rather than inside the first tool call.
        base = AKConfig.get()
        block = _OKFConfig(databases={"warehouse": _OKFDatabaseConfig(type="local", uri="./b", producer=["a"], curator=["a"])})
        monkeypatch.setattr(AKConfig, "get", classmethod(lambda cls: base.model_copy(update={"okf": block})))

        with pytest.raises(AKConfigError, match="both 'producer' and 'curator'"):
            OKFCapabilityManager.get()


class TestStoreResolution:
    def test_local_resolves_through_from_uri(self, tmp_path):
        root = _bundle(tmp_path)
        manager = _manager({"warehouse": _OKFDatabaseConfig(type="local", uri=str(root), consumer=["reader"])})

        store = manager.store("warehouse")

        assert isinstance(store, LocalDocumentStore)

    def test_the_resolved_store_is_cached(self, tmp_path):
        root = _bundle(tmp_path)
        manager = _manager({"warehouse": _OKFDatabaseConfig(type="local", uri=str(root), consumer=["reader"])})

        assert manager.store("warehouse") is manager.store("warehouse")

    def test_s3_resolves_through_from_uri(self, monkeypatch, tmp_path):
        # from_uri is monkeypatched so no boto3 client is constructed and the suite stays offline.
        seen = []
        sentinel = LocalDocumentStore(_bundle(tmp_path))

        def fake_from_uri(uri, **kwargs):
            seen.append(uri)
            return sentinel

        monkeypatch.setattr(DocumentStore, "from_uri", staticmethod(fake_from_uri))

        manager = _manager({"warehouse": _OKFDatabaseConfig(type="s3", uri="s3://bucket/prefix", consumer=["reader"])})

        assert manager.store("warehouse") is sentinel
        assert seen == ["s3://bucket/prefix"]

    def test_a_dotted_type_resolves_through_resolve_dotted(self, tmp_path):
        manager = _manager(
            {
                "warehouse": _OKFDatabaseConfig(
                    type="agentkernel.knowledgebase.store.local.LocalDocumentStore",
                    uri=str(_bundle(tmp_path)),
                    consumer=["reader"],
                )
            }
        )

        assert isinstance(manager.store("warehouse"), LocalDocumentStore)

    def test_a_dotted_type_that_is_not_a_document_store_is_refused(self, tmp_path):
        manager = _manager({"warehouse": _OKFDatabaseConfig(type="json.JSONDecoder", uri=str(_bundle(tmp_path)), consumer=["reader"])})

        with pytest.raises(AKConfigError, match="not a DocumentStore subclass"):
            manager.store("warehouse")

    def test_an_unknown_short_name_is_refused(self, tmp_path):
        # Neither built-in nor a dotted path, so resolve_dotted rejects it by shape.
        manager = _manager({"warehouse": _OKFDatabaseConfig(type="postgres", uri=str(_bundle(tmp_path)), consumer=["reader"])})

        with pytest.raises(AKConfigError, match="not a dotted path"):
            manager.store("warehouse")


class TestTypeUriAgreement:
    def test_local_with_an_s3_uri_is_refused(self):
        manager = _manager({"warehouse": _OKFDatabaseConfig(type="local", uri="s3://bucket/prefix", consumer=["reader"])})

        with pytest.raises(AKConfigError) as excinfo:
            manager.store("warehouse")

        message = str(excinfo.value)
        assert "'warehouse'" in message
        assert "'local'" in message
        assert "'s3://bucket/prefix'" in message
        assert "needs type 's3'" in message

    def test_s3_without_an_s3_uri_is_refused(self):
        manager = _manager({"warehouse": _OKFDatabaseConfig(type="s3", uri="./bundle", consumer=["reader"])})

        with pytest.raises(AKConfigError) as excinfo:
            manager.store("warehouse")

        message = str(excinfo.value)
        assert "'warehouse'" in message
        assert "'s3'" in message
        assert "'./bundle'" in message
        assert "needs an s3://bucket/prefix uri" in message

    def test_the_agreement_check_does_not_apply_to_a_custom_store(self, tmp_path):
        # A bring-your-own store defines what its own uri means, so neither check runs.
        manager = _manager(
            {
                "warehouse": _OKFDatabaseConfig(
                    type="agentkernel.knowledgebase.store.local.LocalDocumentStore",
                    uri=str(_bundle(tmp_path)),
                    consumer=["reader"],
                )
            }
        )

        assert isinstance(manager.store("warehouse"), LocalDocumentStore)


class TestValidateConfiguration:
    def test_a_writable_store_under_a_writable_role_is_silent(self, tmp_path, caplog):
        manager = _manager({"warehouse": _OKFDatabaseConfig(type="local", uri=str(_bundle(tmp_path)), producer=["writer"])})

        with caplog.at_level(logging.WARNING, logger="ak.knowledgebase.okf"):
            manager.validate_configuration()

        assert caplog.text == ""

    def test_a_read_only_store_under_a_producer_warns_rather_than_raising(self, tmp_path, monkeypatch, caplog):
        root = _bundle(tmp_path)
        monkeypatch.setattr(DocumentStore, "from_uri", staticmethod(lambda uri, **kw: LocalDocumentStore(root, writable=False)))
        manager = _manager({"warehouse": _OKFDatabaseConfig(type="local", uri=str(root), producer=["writer"], curator=["keeper"])})

        with caplog.at_level(logging.WARNING, logger="ak.knowledgebase.okf"):
            manager.validate_configuration()

        assert "'warehouse'" in caplog.text
        assert "['keeper', 'writer']" in caplog.text
        assert "will be refused" in caplog.text

    def test_a_read_only_store_with_only_consumers_is_silent(self, tmp_path, monkeypatch, caplog):
        # Read-only is the correct configuration here, not a mistake worth a warning.
        root = _bundle(tmp_path)
        monkeypatch.setattr(DocumentStore, "from_uri", staticmethod(lambda uri, **kw: LocalDocumentStore(root, writable=False)))
        manager = _manager({"warehouse": _OKFDatabaseConfig(type="local", uri=str(root), consumer=["reader"])})

        with caplog.at_level(logging.WARNING, logger="ak.knowledgebase.okf"):
            manager.validate_configuration()

        assert caplog.text == ""

    def test_a_bad_type_fails_validation_rather_than_the_first_tool_call(self, tmp_path):
        manager = _manager({"warehouse": _OKFDatabaseConfig(type="s3", uri=str(_bundle(tmp_path)), consumer=["reader"])})

        with pytest.raises(AKConfigError, match="'warehouse'"):
            manager.validate_configuration()

    def test_validation_walks_no_store(self, tmp_path, monkeypatch):
        # Resolution reads the store's declared writability and nothing else; walking stays
        # lazy, so a fleet with ten bundles pays nothing at startup.
        root = _bundle(tmp_path)
        monkeypatch.setattr(LocalDocumentStore, "list", lambda self, prefix="": pytest.fail("validate_configuration walked the store"))
        manager = _manager({"warehouse": _OKFDatabaseConfig(type="local", uri=str(root), consumer=["reader"])})

        manager.validate_configuration()


class TestBackendsAndBuilders:
    def test_an_unknown_database_names_the_configured_ones(self, tmp_path):
        manager = _manager({"warehouse": _OKFDatabaseConfig(type="local", uri=str(_bundle(tmp_path)), consumer=["reader"])})

        with pytest.raises(AKConfigError, match=r"\['warehouse'\]"):
            manager.backend("nope")

    def test_an_agent_with_no_role_gets_no_builder(self, tmp_path):
        manager = _manager({"warehouse": _OKFDatabaseConfig(type="local", uri=str(_bundle(tmp_path)), consumer=["reader"])})

        assert manager.builder_for("stranger") is None

    def test_a_builder_holds_only_that_agents_databases(self, tmp_path):
        manager = _manager(
            {
                "warehouse": _OKFDatabaseConfig(type="local", uri=str(_bundle(tmp_path, "warehouse")), consumer=["reader", "writer"]),
                "policies": _OKFDatabaseConfig(type="local", uri=str(_bundle(tmp_path, "policies")), consumer=["writer"]),
            }
        )

        # Read-side scoping is structural: a database the agent holds no role in is simply not
        # registered, so routing a tool at it needs no extra enforcement.
        assert list(manager.builder_for("reader").backends) == ["warehouse"]
        assert list(manager.builder_for("writer").backends) == ["warehouse", "policies"]

    def test_one_manager_per_database_is_shared_between_agents(self, tmp_path):
        manager = _manager({"warehouse": _OKFDatabaseConfig(type="local", uri=str(_bundle(tmp_path)), consumer=["a"], producer=["b"])})

        # Two agents reading one bundle pay one walk and one refresh cycle, not two.
        assert manager.builder_for("a").backends["warehouse"] is manager.builder_for("b").backends["warehouse"]
        assert manager.backend("warehouse") is manager.builder_for("a").backends["warehouse"]

    def test_a_builder_is_cached_per_agent(self, tmp_path):
        manager = _manager({"warehouse": _OKFDatabaseConfig(type="local", uri=str(_bundle(tmp_path)), consumer=["reader"])})

        assert manager.builder_for("reader") is manager.builder_for("reader")

    def test_the_backend_carries_the_configured_name_description_and_refresh(self, tmp_path):
        manager = _manager(
            {
                "warehouse": _OKFDatabaseConfig(
                    type="local",
                    uri=str(_bundle(tmp_path)),
                    description="Sales knowledge",
                    refresh_seconds=None,
                    consumer=["reader"],
                )
            }
        )

        backend = manager.backend("warehouse")

        assert backend.backend_name == "warehouse"
        assert backend.description == "Sales knowledge"
        assert backend._refresh_seconds is None

    def test_semantic_maps_reach_the_builder_per_database(self, tmp_path):
        manager = _manager(
            {
                "warehouse": _OKFDatabaseConfig(
                    type="local",
                    uri=str(_bundle(tmp_path, "warehouse")),
                    semantic_map={"<TABLES>": "tables"},
                    consumer=["reader"],
                ),
                "policies": _OKFDatabaseConfig(type="local", uri=str(_bundle(tmp_path, "policies")), consumer=["reader"]),
            }
        )

        builder = manager.builder_for("reader")

        # Only the database that declared one appears, so KnowledgeBuilder never warns about a
        # map naming a backend it does not hold.
        assert builder.backend_semantic_maps == {"warehouse": {"<TABLES>": "tables"}}
        assert builder.semantic_map == {}

    def test_no_store_is_walked_until_a_backend_is_asked_for(self, tmp_path, monkeypatch):
        walks = []
        monkeypatch.setattr(LocalDocumentStore, "list", lambda self, prefix="": walks.append(prefix) or [])
        manager = _manager({"warehouse": _OKFDatabaseConfig(type="local", uri=str(_bundle(tmp_path)), consumer=["reader"])})

        manager.store("warehouse")
        assert walks == []

        manager.backend("warehouse")
        assert walks
