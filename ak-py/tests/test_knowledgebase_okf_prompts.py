"""The OKF system-prompt section (#553 iteration 12).

Everything here is prompt text, so it is composed from configuration alone -- no OKFManager is
constructed and no bundle is walked to render it. That is the property that makes the prompt
independent of construction order, and it is asserted directly: these tests pass no store.
"""

import pytest

from agentkernel.core.config import _OKFDatabaseConfig
from agentkernel.knowledgebase.okf.prompts import OKFPromptComposer
from agentkernel.knowledgebase.okf.roles import OKFRole, OKFRoleRegistry


def _compose(databases: dict, agent_name: str) -> str:
    registry = OKFRoleRegistry.from_config(databases)
    return OKFPromptComposer(registry, {name: config.description for name, config in databases.items()}).compose(agent_name)


def _database(description=None, **roles) -> _OKFDatabaseConfig:
    return _OKFDatabaseConfig(type="local", uri="./bundle", description=description, **roles)


class TestCompose:
    def test_an_agent_with_no_role_gets_nothing(self):
        assert _compose({"warehouse": _database(consumer=["reader"])}, "stranger") == ""

    def test_an_unnamed_agent_gets_nothing(self):
        registry = OKFRoleRegistry.from_config({"warehouse": _database(consumer=["reader"])})
        composer = OKFPromptComposer(registry, {"warehouse": None})

        assert composer.compose(None) == ""
        assert composer.compose("") == ""

    def test_the_section_carries_the_header_and_the_database(self):
        section = _compose({"warehouse": _database(description="Analytics concepts.", consumer=["reader"])}, "reader")

        assert "[Organizational knowledge (OKF)]" in section
        assert "- warehouse (read only): Analytics concepts." in section

    def test_a_writable_role_is_announced_as_read_and_write(self):
        section = _compose({"warehouse": _database(producer=["writer"])}, "writer")

        assert "- warehouse (read and write)" in section

    def test_a_database_with_no_description_still_renders(self):
        section = _compose({"warehouse": _database(consumer=["reader"])}, "reader")

        assert "- warehouse (read only)" in section
        # No dangling colon where the description would have been.
        assert "(read only):" not in section

    @pytest.mark.parametrize("role, marker", [("consumer", "CONSUMER"), ("producer", "PRODUCER"), ("curator", "CURATOR")])
    def test_each_role_carries_its_own_mandate(self, role, marker):
        section = _compose({"warehouse": _database(**{role: ["agent"]})}, "agent")

        assert f"Your role is {marker}" in section

    def test_producer_and_curator_are_told_different_things(self):
        # They are identical in permission and differ only here, so if these two sentences ever
        # converge the distinction has silently stopped existing.
        assert OKFPromptComposer.MANDATES[OKFRole.PRODUCER] != OKFPromptComposer.MANDATES[OKFRole.CURATOR]

    def test_an_agent_holding_different_roles_in_two_databases_gets_both_mandates(self):
        section = _compose(
            {
                "warehouse": _database(description="Warehouse.", producer=["agent"]),
                "policies": _database(description="Policies.", consumer=["agent"]),
            },
            "agent",
        )

        assert "- warehouse (read and write): Warehouse." in section
        assert "- policies (read only): Policies." in section
        assert "Your role is PRODUCER" in section
        assert "Your role is CONSUMER" in section

    def test_a_mandate_is_scoped_under_the_database_it_applies_to(self):
        section = _compose(
            {
                "warehouse": _database(producer=["agent"]),
                "policies": _database(consumer=["agent"]),
            },
            "agent",
        )
        lines = section.splitlines()

        # The producer mandate must sit under warehouse, not under policies: an agent that reads
        # them in the wrong order would write into the bundle it may only read.
        warehouse_at = lines.index("- warehouse (read and write)")
        policies_at = lines.index("- policies (read only)")
        assert "PRODUCER" in lines[warehouse_at + 1]
        assert "CONSUMER" in lines[policies_at + 1]

    def test_a_database_an_agent_holds_no_role_in_is_absent(self):
        section = _compose(
            {
                "warehouse": _database(consumer=["reader"]),
                "policies": _database(consumer=["other"]),
            },
            "reader",
        )

        assert "warehouse" in section
        assert "policies" not in section

    def test_the_navigation_protocol_appears_exactly_once_regardless_of_database_count(self):
        one = _compose({"warehouse": _database(consumer=["reader"])}, "reader")
        several = _compose(
            {
                "warehouse": _database(consumer=["reader"]),
                "policies": _database(consumer=["reader"]),
                "runbooks": _database(consumer=["reader"]),
            },
            "reader",
        )

        assert one.count("How to use them:") == 1
        assert several.count("How to use them:") == 1

    def test_the_protocol_keeps_its_five_steps(self):
        # Lifted from the protocol every OKF application used to hand-write; it ships with the
        # capability now, so losing a step here removes it from every application at once.
        section = _compose({"warehouse": _database(consumer=["reader"])}, "reader")

        for step in ("1.", "2.", "3.", "4.", "5."):
            assert f"\n{step} " in section
        assert "get_schemas()" in section
        assert "browse_kb()" in section
        assert "fetch_kb()" in section
        assert "search_kb()" in section
        assert "human-reviewed" in section

    def test_composition_needs_no_store_and_no_backend(self):
        # The whole point: a composer built from config alone renders a complete section.
        registry = OKFRoleRegistry.from_config({"warehouse": _database(description="Only config.", curator=["keeper"])})
        section = OKFPromptComposer(registry, {"warehouse": "Only config."}).compose("keeper")

        assert "Only config." in section
        assert "Your role is CURATOR" in section
