"""The OKF role model (#553 iteration 11).

Permission is per (agent, database) pair, not per agent, and that is the property most likely
to be broken by a well-meaning simplification: an agent that produces into one bundle and only
consumes another must keep both answers. The two AKConfigErrors are pinned with their text,
because a config error nobody can act on is barely better than none.

The registry is built from literal dicts throughout. It never reads AKConfig, which is what
makes that possible.
"""

import pytest

from agentkernel.core.config import _OKFDatabaseConfig
from agentkernel.core.util.factory import AKConfigError
from agentkernel.knowledgebase.okf.roles import OKFAssignment, OKFRole, OKFRoleRegistry


def _database(**roles) -> _OKFDatabaseConfig:
    """A configured database with the given role lists; type and uri are required but unused here."""
    return _OKFDatabaseConfig(type="local", uri="./bundle", **roles)


class TestOKFRole:
    @pytest.mark.parametrize(
        "role, writable",
        [(OKFRole.CONSUMER, False), (OKFRole.PRODUCER, True), (OKFRole.CURATOR, True)],
    )
    def test_writable_is_the_one_place_the_distinction_lives(self, role, writable):
        assert role.writable is writable

    def test_the_roles_are_exactly_the_three_config_field_names(self):
        # The enum values are read back off _OKFDatabaseConfig with getattr, so a rename here
        # that is not mirrored there silently produces a database nobody can reach.
        assert [role.value for role in OKFRole] == ["consumer", "producer", "curator"]
        for role in OKFRole:
            assert hasattr(_OKFDatabaseConfig(type="local", uri="x"), role.value)


class TestFromConfig:
    def test_one_agent_in_one_role(self):
        registry = OKFRoleRegistry.from_config({"warehouse": _database(consumer=["reader"])})

        assert registry.assignments_for("reader") == (OKFAssignment(database="warehouse", role=OKFRole.CONSUMER),)
        assert registry.databases_for("reader") == ("warehouse",)

    def test_one_agent_across_several_databases(self):
        registry = OKFRoleRegistry.from_config(
            {
                "warehouse": _database(consumer=["reader"]),
                "policies": _database(consumer=["reader"]),
            }
        )

        assert registry.databases_for("reader") == ("warehouse", "policies")

    def test_one_agent_holding_a_different_role_in_each_database(self):
        # The pair-not-agent property. A producer of one bundle is not a producer of them all.
        registry = OKFRoleRegistry.from_config(
            {
                "warehouse": _database(producer=["writer"]),
                "policies": _database(consumer=["writer"]),
            }
        )

        assert registry.assignments_for("writer") == (
            OKFAssignment(database="warehouse", role=OKFRole.PRODUCER),
            OKFAssignment(database="policies", role=OKFRole.CONSUMER),
        )
        assert registry.may_write("writer", "warehouse") is True
        assert registry.may_write("writer", "policies") is False

    def test_producer_of_one_and_curator_of_another_is_accepted(self):
        # The negative of the conflict rule below: the check is per database on purpose.
        registry = OKFRoleRegistry.from_config(
            {
                "warehouse": _database(producer=["agent"]),
                "policies": _database(curator=["agent"]),
            }
        )

        assert registry.writable_databases_for("agent") == frozenset({"warehouse", "policies"})

    def test_several_agents_in_one_database(self):
        registry = OKFRoleRegistry.from_config({"warehouse": _database(consumer=["a", "b"], producer=["c"])})

        assert registry.databases_for("a") == ("warehouse",)
        assert registry.may_write("c", "warehouse") is True
        assert registry.may_write("b", "warehouse") is False

    def test_blank_and_whitespace_only_names_are_dropped(self):
        registry = OKFRoleRegistry.from_config({"warehouse": _database(consumer=[" reader ", "", "   "])})

        assert registry.databases_for("reader") == ("warehouse",)
        assert registry.has_any_role("") is False

    def test_a_name_repeated_in_one_role_produces_one_assignment(self):
        # Two identical assignments would later append the same mandate to a prompt twice.
        registry = OKFRoleRegistry.from_config({"warehouse": _database(consumer=["reader", "reader"])})

        assert registry.assignments_for("reader") == (OKFAssignment(database="warehouse", role=OKFRole.CONSUMER),)

    def test_an_undeclared_role_list_is_read_as_naming_nobody(self):
        # The three lists default to None, so an ordinary config file declaring only consumers
        # leaves producer and curator unset rather than empty.
        config = _OKFDatabaseConfig(type="local", uri="./bundle", consumer=["reader"])
        assert (config.producer, config.curator) == (None, None)

        registry = OKFRoleRegistry.from_config({"warehouse": config})

        assert registry.databases_for("reader") == ("warehouse",)
        assert registry.writable_databases_for("reader") == frozenset()

    def test_an_empty_block_is_a_registry_nobody_appears_in(self):
        # AK_OKF__* env vars can materialise the block with no databases. Inert, not an error.
        registry = OKFRoleRegistry.from_config({})

        assert registry.has_any_role("anyone") is False


class TestValidation:
    def test_a_database_naming_no_agent_is_refused(self):
        with pytest.raises(AKConfigError) as excinfo:
            OKFRoleRegistry.from_config({"warehouse": _database()})

        assert "'warehouse'" in str(excinfo.value)
        assert "names no agent" in str(excinfo.value)

    def test_the_no_agent_error_names_the_offending_database_among_valid_ones(self):
        with pytest.raises(AKConfigError, match="'policies'"):
            OKFRoleRegistry.from_config(
                {
                    "warehouse": _database(consumer=["reader"]),
                    "policies": _database(),
                }
            )

    def test_a_database_with_only_blank_names_counts_as_naming_no_agent(self):
        with pytest.raises(AKConfigError, match="names no agent"):
            OKFRoleRegistry.from_config({"warehouse": _database(consumer=["", "  "])})

    def test_one_agent_as_both_producer_and_curator_of_one_database_is_refused(self):
        with pytest.raises(AKConfigError) as excinfo:
            OKFRoleRegistry.from_config({"warehouse": _database(producer=["agent"], curator=["agent"])})

        message = str(excinfo.value)
        assert "'warehouse'" in message
        assert "'agent'" in message
        assert "both 'producer' and 'curator'" in message

    def test_the_conflict_error_lists_every_conflicting_agent(self):
        with pytest.raises(AKConfigError) as excinfo:
            OKFRoleRegistry.from_config({"warehouse": _database(producer=["b", "a"], curator=["a", "b"])})

        assert "['a', 'b']" in str(excinfo.value)


class TestLookups:
    @pytest.fixture
    def registry(self) -> OKFRoleRegistry:
        return OKFRoleRegistry.from_config(
            {
                "warehouse": _database(consumer=["reader"], producer=["writer"], curator=["keeper"]),
                "policies": _database(consumer=["writer"]),
            }
        )

    def test_writable_databases_for_returns_only_the_writable_subset(self, registry):
        assert registry.writable_databases_for("writer") == frozenset({"warehouse"})
        assert registry.writable_databases_for("keeper") == frozenset({"warehouse"})
        assert registry.writable_databases_for("reader") == frozenset()

    def test_may_write_is_false_for_a_database_the_agent_holds_no_role_in(self, registry):
        assert registry.may_write("keeper", "policies") is False

    def test_an_unnamed_agent_holds_nothing(self, registry):
        assert registry.has_any_role("stranger") is False
        assert registry.assignments_for("stranger") == ()
        assert registry.databases_for("stranger") == ()
        assert registry.writable_databases_for("stranger") == frozenset()
        assert registry.may_write("stranger", "warehouse") is False

    def test_has_any_role_is_true_for_a_read_only_agent(self, registry):
        # Holding a role and holding write permission are different questions.
        assert registry.has_any_role("reader") is True
        assert registry.writable_databases_for("reader") == frozenset()

    def test_assignments_are_immutable(self, registry):
        # Read from every agent construction and every tool call, including consumer threads.
        with pytest.raises((AttributeError, TypeError)):
            registry.assignments_for("reader")[0].database = "elsewhere"
