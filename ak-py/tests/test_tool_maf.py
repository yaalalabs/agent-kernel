def test_maf_tool_builder():
    from agentkernel.framework.maf.maf import MAFToolBuilder

    def my_tool(a: int, b: int) -> int:
        """Adds two numbers."""
        return a + b

    def another_tool() -> str:
        return "hello"

    tools = MAFToolBuilder.bind([my_tool, another_tool])
    assert len(tools) == 2

    assert [tool.name for tool in tools] == ["my_tool", "another_tool"]
