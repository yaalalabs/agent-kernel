"""Smoke test for the LiveKit voice example.

Connects to the room as a human participant (the running server holds the agent identity),
publishes a microphone track to trigger the agent's greeting, and prints the transcript the
agent sends back over the ``lk-chat`` data channel.

Run the server first, then:

    AK_LIVE_VOICE_URL=... AK_LIVE_VOICE_API_KEY=... AK_LIVE_VOICE_API_SECRET=... python test_gw.py

Do NOT construct a LiveKitEdgeGateway here: the server already joined the room as the agent,
and a second connection with the same identity gets kicked with ``DuplicateIdentity``.
"""

import asyncio
import logging
import os

from livekit import api, rtc

logging.basicConfig(level=logging.INFO)

URL = os.environ["AK_LIVE_VOICE_URL"]
KEY = os.environ["AK_LIVE_VOICE_API_KEY"]
SECRET = os.environ["AK_LIVE_VOICE_API_SECRET"]
ROOM = os.environ.get("AK_LIVE_VOICE_ROOM", "room_01")


async def main() -> None:
    token = (
        api.AccessToken(KEY, SECRET)
        .with_identity("human-user")
        .with_name("Human")
        .with_grants(api.VideoGrants(room_join=True, room=ROOM))
        .to_jwt()
    )

    room = rtc.Room()

    @room.on("data_received")
    def on_data_received(data_packet: rtc.DataPacket) -> None:
        try:
            logging.info(f"Agent transcript: {data_packet.data.decode('utf-8')}")
        except Exception:
            pass

    @room.on("track_subscribed")
    def on_track_subscribed(
        track: rtc.Track,
        publication: rtc.RemoteTrackPublication,
        participant: rtc.RemoteParticipant,
    ) -> None:
        if track.kind == rtc.TrackKind.KIND_AUDIO:
            logging.info(f"Subscribed to agent audio from {participant.identity}")

    await room.connect(URL, token)
    logging.info(
        f"Connected as {room.local_participant.identity}; publishing mic track to trigger the greeting"
    )

    source = rtc.AudioSource(sample_rate=24000, num_channels=1)
    track = rtc.LocalAudioTrack.create_audio_track("test-voice", source)
    await room.local_participant.publish_track(
        track, rtc.TrackPublishOptions(source=rtc.TrackSource.SOURCE_MICROPHONE)
    )

    await asyncio.sleep(20)
    await room.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
