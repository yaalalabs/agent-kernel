"""
Demo WebSocket client for the openai-websocket-scalable example.

Connects to the deployed WebSocket API, authenticates via an (unsigned, demo-only) JWT passed
as a `?token=` query string, sends a chat message on the `chat` route, and prints the
CHAT_RESPONSE eventually pushed back over the connection once the Agent Runner (polling the
Input Queue) finishes processing and the REST/IO service's output-queue consumer broadcasts
the reply. It then sends a frame on the custom `status` route (registered via
`@AWSWebsocketAPI.register("status")` in app_rest_service.py, answered directly — no queue
involved) and prints its SYSTEM_RESPONSE.

Usage:
    python client.py "wss://<ws-id>.execute-api.<region>.amazonaws.com/agents" "What is 2+2?"
"""

import asyncio
import json
import sys
import uuid

import jwt
import websockets


def _demo_token() -> str:
    # WARNING: unsigned — matches the demo CustomAuthValidator in app_rest_service.py. Never do this in production.
    return jwt.encode({"userId": "user-1", "email": "test@test.com"}, None, algorithm="none")


async def chat(ws_url: str, prompt: str) -> None:
    session_id = str(uuid.uuid4())

    async with websockets.connect(f"{ws_url}?token={_demo_token()}") as ws:
        await ws.send(
            json.dumps(
                {
                    "route": "chat",
                    "body": {
                        "session_id": session_id,
                        "agent": "triage",
                        "prompt": prompt,
                    },
                }
            )
        )
        # The chat frame's own HTTP response (from the WS API Gateway integration) is just
        # "Request queued successfully" — the actual agent reply arrives asynchronously as a
        # separate WebSocket push once the Agent Runner finishes, so we wait for that here.
        print(json.loads(await ws.recv()))

        # Custom route demo (Terraform: ws_routes = [{ route = "status" }]) — answered directly
        # by the REST/IO service, no Input/Output Queue round trip.
        await ws.send(json.dumps({"route": "status", "body": {}}))
        print(json.loads(await ws.recv()))


if __name__ == "__main__":
    url = sys.argv[1] if len(sys.argv) > 1 else "ws://localhost:8000"
    message = sys.argv[2] if len(sys.argv) > 2 else "Who won the 1996 cricket world cup?"
    asyncio.run(chat(url, message))
