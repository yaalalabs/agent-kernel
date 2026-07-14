import asyncio
import json
import sys
import uuid

import jwt
import websockets


def _demo_token() -> str:
    # WARNING: unsigned — matches the demo CustomAuthValidator in app.py. Never do this in production.
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
        print(json.loads(await ws.recv()))

        # Custom route demo (Terraform: ws_routes = [{ route = "status" }]).
        await ws.send(json.dumps({"route": "status", "body": {}}))
        print(json.loads(await ws.recv()))


if __name__ == "__main__":
    url = sys.argv[1] if len(sys.argv) > 1 else "ws://localhost:8000"
    message = sys.argv[2] if len(sys.argv) > 2 else "Who won the 1996 cricket world cup?"
    asyncio.run(chat(url, message))
