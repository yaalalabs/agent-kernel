"""Minimal WebSocket client for the README's stream-mode walkthrough.

Connects to the gateway, authenticates with a demo JWT accepted by app_ws_gateway.py's
validator (signature verification is off there, so any signing key works), sends one chat
frame, and prints every frame until the reply completes: CHAT_QUEUED acknowledges the enqueue,
then STREAM_CHUNK frames arrive (the one carrying ``done: true`` is the last) in stream mode,
or a single CHAT_RESPONSE frame in async mode.

    uv run python ws_client.py [ws://localhost:18001/ws] [prompt]
"""

import asyncio
import json
import sys

import jwt
import websockets


def demo_token() -> str:
    return jwt.encode({"userId": "user-1", "email": "test1@test.com"}, "demo-secret", algorithm="HS256")


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
