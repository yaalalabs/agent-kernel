# /// script
# requires-python = ">=3.12"
# dependencies = ["livekit-api>=0.4.0"]
# ///
"""Print a LiveKit access token for a human participant joining ``room_01``.

Run with ``uv run get_token.py``: uv reads the dependency block above and installs it.
"""

import os

from livekit import api

api_key = os.environ.get("AK_LIVEKIT__API_KEY")
api_secret = os.environ.get("AK_LIVEKIT__API_SECRET")

if not api_key or not api_secret:
    print("Error: AK_LIVEKIT__API_KEY or AK_LIVEKIT__API_SECRET is missing.")
    exit(1)

token = (
    api.AccessToken(api_key, api_secret)
    .with_identity("human-user")
    .with_name("Human")
    .with_grants(api.VideoGrants(room_join=True, room="room_01"))
    .to_jwt()
)

print(token)
