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


def test_maf_tool_builder_forwards_approval_mode():
    from agentkernel.framework.maf.maf import MAFToolBuilder

    def refund(order_id: str) -> str:
        """Refund an order."""
        return order_id

    (gated,) = MAFToolBuilder.bind([refund], approval_mode="always_require")
    (open_tool,) = MAFToolBuilder.bind([refund])

    assert gated.approval_mode == "always_require"
    assert open_tool.approval_mode == "never_require"
