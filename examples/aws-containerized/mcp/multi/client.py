import json
import logging
import traceback
import uuid
from typing import Any, List

from fastmcp.client import Client

logging.basicConfig(level=logging.WARN, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", force=True)


class MCPHttpClient:

    def __init__(self, server_url: str) -> None:
        self.log = logging.getLogger("ak.mcp.client")
        self.server_url = server_url
        self.session_id = str(uuid.uuid4())

    async def _list_tools(self) -> List[Any]:
        try:
            async with Client(self.server_url, auth="oauth") as client:
                assert await client.ping()
                return await client.list_tools()

        except Exception as e:
            self.log.exception(f"Exception occurred while listing tools: {e}")
            raise

    async def init(self):
        tools = await self._list_tools()
        for tool in tools:
            self.log.info(f"Found tool: {tool.name}")
        pass

    async def send(self, message: str, tool: str = "history"):
        async with Client(self.server_url, auth="oauth") as client:
            response = await client.call_tool(tool, {"prompt": message, "session_id": self.session_id})
            try:
                result = json.loads(response.content[0].text)
                return str(result.get("raw", result))
            except (json.JSONDecodeError, TypeError):
                return response.content[0].text
