def test_maf_tool_builder():
    from agentkernel.framework.maf.maf import MAFToolBuilder

    def my_tool(a: int, b: int) -> int:
        """Adds two numbers."""
        return a + b

    def another_tool() -> str:
        return "hello"

    tools = MAFToolBuilder.bind([my_tool, another_tool])
    assert len(tools) == 2

    # In a real environment with agent-framework installed, these would be MAF tool wrappers.
    # Without it, it falls back to the original functions.
    assert any(getattr(t, "__name__", getattr(t, "name", "")) == "my_tool" for t in tools)
    assert any(getattr(t, "__name__", getattr(t, "name", "")) == "another_tool" for t in tools)
