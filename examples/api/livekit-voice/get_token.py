import os

from livekit import api

api_key = os.environ.get("AK_LIVE_VOICE_API_KEY")
api_secret = os.environ.get("AK_LIVE_VOICE_API_SECRET")

if not api_key or not api_secret:
    print("Error: AK_LIVE_VOICE_API_KEY or AK_LIVE_VOICE_API_SECRET is missing.")
    exit(1)

token = (
    api.AccessToken(api_key, api_secret)
    .with_identity("human-user")
    .with_name("Human")
    .with_grants(api.VideoGrants(room_join=True, room="room_01"))
    .to_jwt()
)

print(token)
