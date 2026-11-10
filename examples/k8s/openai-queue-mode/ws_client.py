"""Minimal WebSocket client for the README's async + delta walkthrough.

Connects to the gateway, authenticates with the demo credential the static identity provider in
config.yaml accepts (the DEMO_AUTH_TOKEN value the demo-credentials Secret holds; export the same
value here), sends one chat frame, and prints every frame until the reply completes: CHAT_QUEUED
acknowledges the enqueue, then STREAM_CHUNK frames arrive (the one carrying ``done: true`` is the
last) with message_type delta, or a single CHAT_RESPONSE frame with the default (complete).

    DEMO_AUTH_TOKEN=... uv run python ws_client.py [ws://localhost:18001/ws] [prompt]
"""

import asyncio
import json
import os
import sys

import websockets


def demo_token() -> str:
    token = os.environ.get("DEMO_AUTH_TOKEN")
    if not token:
        sys.exit("Set DEMO_AUTH_TOKEN to the value the demo-credentials Secret holds (see the README)")
    return token


async def main() -> None:
    url = sys.argv[1] if len(sys.argv) > 1 else "ws://localhost:18001/ws"
    prompt = sys.argv[2] if len(sys.argv) > 2 else "Who is Napoleon? One sentence."

    async with websockets.connect(f"{url}?token={demo_token()}") as websocket:
        await websocket.send(
            json.dumps({"route": "chat", "prompt": prompt, "session_id": "ws-demo-1", "agent": "triage"})
        )
        while True:
            frame = json.loads(await websocket.recv())
            print(json.dumps(frame))
            if frame.get("type") == "CHAT_RESPONSE" or frame.get("done"):
                break


if __name__ == "__main__":
    asyncio.run(main())
