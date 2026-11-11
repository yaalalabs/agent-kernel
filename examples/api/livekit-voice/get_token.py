# /// script
# requires-python = ">=3.12"
# dependencies = ["livekit-api>=0.4.0"]
# ///
"""Print a LiveKit access token for a human participant joining a room (default ``call_01``).

Run with ``uv run get_token.py [room] [name]``: uv reads the dependency block above and installs it. Every room is its
own call. Give each device its own name: LiveKit allows one connection per identity in a room, so a second device
joining with the same name replaces the first.
"""

import os
import sys

from livekit import api

api_key = os.environ.get("AK_LIVEKIT__API_KEY")
api_secret = os.environ.get("AK_LIVEKIT__API_SECRET")

if not api_key or not api_secret:
    print("Error: AK_LIVEKIT__API_KEY or AK_LIVEKIT__API_SECRET is missing.")
    exit(1)

room = sys.argv[1] if len(sys.argv) > 1 else "call_01"
name = sys.argv[2] if len(sys.argv) > 2 else "user"

token = (
    api.AccessToken(api_key, api_secret)
    .with_identity(f"human-{name}")
    .with_name(name)
    .with_grants(api.VideoGrants(room_join=True, room=room))
    .to_jwt()
)

print(token)
