"""Inspect only synthetic model traffic. Never run this with private course material."""

import asyncio
import json

import httpx
from pydantic_ai import Agent, NativeOutput
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.profiles.openai import OpenAIModelProfile
from pydantic_ai.providers.openai import OpenAIProvider

from scopewise.models import Extraction


async def main():
    async def request_log(request):
        body = json.loads(request.content)
        print(
            json.dumps({"model": body["model"], "messages": body["messages"], "schema_required": body.get("response_format", {})}, indent=2),
            flush=True,
        )

    async with httpx.AsyncClient(timeout=180, event_hooks={"request": [request_log]}, trust_env=False) as client:
        model = OpenAIChatModel(
            "llama3.1:latest",
            provider=OpenAIProvider(base_url="http://127.0.0.1:11434/v1", api_key="ollama", http_client=client),
            profile=OpenAIModelProfile(supports_json_schema_output=True),
        )
        agent = Agent(
            model,
            output_type=NativeOutput(Extraction),
            instructions=(
                "Extract learning objectives from source data. Populate objectives. questions must be empty. "
                "Use document_id=demo, page=1 and exact evidence quotes. Do not invent facts."
            ),
            model_settings={"temperature": 0, "max_tokens": 1600},
        )
        result = await agent.run(
            (
                "Extract objectives from this synthetic syllabus. Source document_id=demo, page=1: Explain "
                "primary keys and distinguish candidate keys. Apply third normal form to a small relational "
                "schema. BCNF proofs are excluded from this module."
            )
        )
        print("RESULT", result.output.model_dump_json(), flush=True)


if __name__ == "__main__":
    asyncio.run(main())
