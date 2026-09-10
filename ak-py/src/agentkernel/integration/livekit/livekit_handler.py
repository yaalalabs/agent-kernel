import asyncio
import base64
import io
import json
import logging
from typing import Awaitable, Callable, Optional

from fastapi import APIRouter, Depends, HTTPException
from livekit import agents, api, rtc
from livekit.agents import AgentServer, JobContext, WorkerOptions, WorkerType, llm
from livekit.agents.types import DEFAULT_API_CONNECT_OPTIONS, NOT_GIVEN, APIConnectOptions, NotGivenOr
from livekit.agents.voice import Agent as VoicePipelineAgent
from livekit.agents.voice import AgentSession
from livekit.plugins import deepgram, openai, silero
from PIL import Image

from ...api import RESTRequestHandler
from ...core import AgentService, Config
from ...core.model import AgentRequestImage, AgentRequestText, StreamEvent

logger = logging.getLogger("ak.integration.livekit")


class AgentKernelLLMStream(llm.LLMStream):
    """
    Streams Agent Kernel tokens to LiveKit TTS in real-time.
    Bridges Agent Kernel's StreamChunk async generator to LiveKit's ChatChunk async iterable.
    """

    def __init__(
        self,
        parent_llm: llm.LLM,
        chat_ctx: llm.ChatContext,
        agent_name: str,
        session_id: str,
        user_message: str,
        service: AgentService,
        frame_data: Optional[str] = None,
    ):
        super().__init__(parent_llm, chat_ctx=chat_ctx, tools=[], conn_options=DEFAULT_API_CONNECT_OPTIONS)
        self.agent_name = agent_name
        self.session_id = session_id
        self.user_message = user_message
        self._frame_data = frame_data
        self._service = service
        self._stream_iter: Optional[asyncio.AsyncGenerator] = None

    async def _run(self) -> None:
        pass

    async def __anext__(self):
        if self._stream_iter is None:
            self._service.select(name=self.agent_name, session_id=self.session_id)

            if not self._service.agent:
                raise StopAsyncIteration

            if self._frame_data:
                requests = [
                    AgentRequestText(text=self.user_message),
                    AgentRequestImage(image_data=self._frame_data, mime_type="image/jpeg", name="webcam_frame"),
                ]
            else:
                requests = [AgentRequestText(text=self.user_message)]

            self._stream_iter = self._service.run_stream_async(requests)

        try:
            chunk = await self._stream_iter.__anext__()
        except StopAsyncIteration:
            raise StopAsyncIteration

        if chunk.error:
            logger.error(f"Agent Kernel stream error: {chunk.error}")
            raise RuntimeError(chunk.error)

        if chunk.done:
            raise StopAsyncIteration

        tool_calls = []
        if chunk.event and chunk.event.type == "tool_call":
            tool_calls = [
                llm.FunctionToolCall(
                    name=chunk.event.tool_name,
                    arguments=json.dumps(chunk.event.arguments),
                    call_id=chunk.event.call_id,
                )
            ]

        return llm.ChatChunk(
            id=f"ak_{id(chunk)}",
            delta=llm.ChoiceDelta(content=chunk.delta or "", tool_calls=tool_calls, role="assistant"),
        )


class AgentKernelLLM(llm.LLM):
    """
    A custom LiveKit LLM implementation that streams user speech (transcribed to text)
    to the Agent Kernel runtime and yields tokens incrementally to the TTS engine.
    """

    def __init__(self, agent_name: str, session_id: str, frame_holder: Optional[dict] = None):
        super().__init__()
        self.agent_name = agent_name
        self.session_id = session_id
        self._frame_holder = frame_holder

    def chat(
        self,
        *,
        chat_ctx: llm.ChatContext,
        tools: list[llm.Tool] | None = None,
        conn_options: APIConnectOptions = DEFAULT_API_CONNECT_OPTIONS,
        parallel_tool_calls: NotGivenOr[bool] = NOT_GIVEN,
        tool_choice: NotGivenOr[llm.ToolChoice] = NOT_GIVEN,
        extra_kwargs: NotGivenOr[dict] = NOT_GIVEN,
    ) -> AgentKernelLLMStream:
        """
        Called by LiveKit's AgentSession when the user has finished speaking and
        the STT has finalized the transcript.
        """
        # Find the last user message
        user_message = ""
        for msg in reversed(chat_ctx.messages()):
            if msg.role == "user" and msg.text_content:
                user_message = msg.text_content
                break

        if not user_message:
            # Return empty stream that immediately ends
            return AgentKernelLLMStream(
                parent_llm=self,
                chat_ctx=chat_ctx,
                agent_name=self.agent_name,
                session_id=self.session_id,
                user_message="",
                service=AgentService(),
            )

        logger.debug(f"Received transcribed user speech: {user_message}")

        # Grab and consume the latest video frame
        frame_data = None
        if self._frame_holder and self._frame_holder.get("frame"):
            try:
                frame = self._frame_holder.pop("frame")
                rgba_frame = frame.convert(rtc.VideoBufferType.RGBA)
                image = Image.frombytes("RGBA", (rgba_frame.width, rgba_frame.height), rgba_frame.data)
                rgb_image = image.convert("RGB")
                buffer = io.BytesIO()
                rgb_image.save(buffer, format="JPEG")
                frame_data = base64.b64encode(buffer.getvalue()).decode("utf-8")
                logger.debug("Attaching webcam frame to this voice turn")
            except Exception as e:
                logger.error(f"Failed to encode video frame for LLM: {e}")

        return AgentKernelLLMStream(
            parent_llm=self,
            chat_ctx=chat_ctx,
            agent_name=self.agent_name,
            session_id=self.session_id,
            user_message=user_message,
            service=AgentService(),
            frame_data=frame_data,
        )


async def _default_entrypoint(ctx: JobContext):
    """
    Default entrypoint for the LiveKit worker.
    Initializes an AgentSession using Deepgram (STT), OpenAI (TTS), and AgentKernel (LLM).

    When vision_enabled is true in config, the entrypoint also subscribes to video tracks
    and captures the latest webcam frame on each voice turn, passing it through the
    multimodal pipeline as an AgentRequestImage.
    """
    logger.info(f"Connecting to room {ctx.room.name}")
    vad = silero.VAD.load()

    agent_name = Config.get().livekit.agent
    if not agent_name:
        logger.warning("No agent configured for LiveKit interactions. Set 'agent' under 'livekit' in config.yaml.")

    vision_enabled = Config.get().livekit.vision_enabled

    stt_provider = Config.get().livekit.stt_provider
    if stt_provider == "openai":
        from livekit.plugins import openai as lk_openai

        stt_plugin = lk_openai.STT()
    else:
        stt_plugin = deepgram.STT()

    tts_provider = Config.get().livekit.tts_provider
    if tts_provider == "elevenlabs":
        from livekit.plugins import elevenlabs

        tts_plugin = elevenlabs.TTS()
    elif tts_provider == "google":
        from livekit.plugins import google

        tts_plugin = google.TTS()
    else:
        tts_plugin = openai.TTS()

    # Shared mutable dict to pass the latest frame from the video capture task to the LLM
    frame_holder = {} if vision_enabled else None

    agent = VoicePipelineAgent(
        vad=vad,
        stt=stt_plugin,
        llm=AgentKernelLLM(agent_name=agent_name, session_id=ctx.room.name, frame_holder=frame_holder),
        tts=tts_plugin,
        instructions="You are a helpful voice assistant.",
    )

    if vision_enabled:
        await ctx.connect(auto_subscribe=agents.AutoSubscribe.SUBSCRIBE_ALL)
        logger.info("Vision enabled: subscribing to audio and video tracks")
    else:
        await ctx.connect(auto_subscribe=agents.AutoSubscribe.AUDIO_ONLY)

    session = AgentSession()
    await session.start(agent, room=ctx.room)

    # If vision is enabled, start a background task to capture the latest video frame
    if vision_enabled:
        _start_video_capture(ctx.room, frame_holder)


def _start_video_capture(room, frame_holder: dict):
    """
    Starts a background task that continuously reads video frames from the first
    available video track in the room. Only the latest frame is kept in memory;
    older frames are overwritten.
    """
    video_stream = None
    tasks = []

    def _create_stream(track: rtc.Track):
        nonlocal video_stream
        if video_stream is not None:
            video_stream.close()

        video_stream = rtc.VideoStream(track)

        async def _read_stream():
            async for event in video_stream:
                try:
                    # Only store the raw frame to avoid CPU overhead on every tick
                    frame_holder["frame"] = event.frame
                except Exception as e:
                    logger.debug(f"Failed to capture video frame: {e}")

        task = asyncio.create_task(_read_stream())
        task.add_done_callback(lambda t: tasks.remove(t) if t in tasks else None)
        tasks.append(task)

    # Check for existing video tracks from remote participants
    for participant in room.remote_participants.values():
        for publication in participant.track_publications.values():
            if publication.track and publication.track.kind == rtc.TrackKind.KIND_VIDEO:
                _create_stream(publication.track)
                logger.info("Started video frame capture from existing track")
                return

    # Watch for new video tracks that are published later
    @room.on("track_subscribed")
    def _on_track_subscribed(track: rtc.Track, publication, participant):
        if track.kind == rtc.TrackKind.KIND_VIDEO:
            _create_stream(track)
            logger.info("Started video frame capture from newly subscribed track")


class AgentLiveKitRequestHandler(RESTRequestHandler):
    """
    API routers that expose endpoints to interact with LiveKit using Agent Kernel.
    Endpoints:
    - GET /livekit/token: Generates a secure LiveKit Access Token for a frontend client to join the voice room.

    This handler also runs a LiveKit Worker as a background asyncio task seamlessly tied to the FastAPI lifecycle.
    """

    def __init__(
        self,
        entrypoint_fnc: Optional[Callable[[JobContext], Awaitable[None]]] = None,
        auth_dependency: Optional[Callable] = None,
    ):
        self._log = logging.getLogger("ak.api.livekit")
        self._entrypoint = entrypoint_fnc or _default_entrypoint
        self._auth_dependency = auth_dependency
        self._worker_task = None
        self._server = None

        # Pull config
        self.url = Config.get().livekit.url
        self.api_key = Config.get().livekit.api_key
        self.api_secret = Config.get().livekit.api_secret

    def get_router(self) -> APIRouter:
        from contextlib import asynccontextmanager

        @asynccontextmanager
        async def lifespan(r: APIRouter):
            if not getattr(self, "_worker_started", False):
                self._worker_started = True
                self._log.info("Starting up LiveKit Background Worker")

                # Setup worker options
                kwargs = {}
                if self.url:
                    kwargs["ws_url"] = self.url
                if self.api_key:
                    kwargs["api_key"] = self.api_key
                if self.api_secret:
                    kwargs["api_secret"] = self.api_secret

                # Set port to 0 to assign a random port
                kwargs["port"] = 0

                # We initialize the AgentServer and start it as an asyncio task
                worker_opts = WorkerOptions(agent_name="agent-kernel-worker", entrypoint_fnc=self._entrypoint, worker_type=WorkerType.ROOM, **kwargs)

                self._server = AgentServer.from_server_options(worker_opts)
                self._worker_task = asyncio.create_task(self._server.run())

            yield

            if self._worker_task and not self._worker_task.done():
                self._log.info("Shutting down LiveKit Background Worker")
                self._worker_task.cancel()
                try:
                    await self._worker_task
                except asyncio.CancelledError:
                    pass

        router = APIRouter(prefix="/livekit", tags=["LiveKit Integration"], lifespan=lifespan)

        dependencies = [Depends(self._auth_dependency)] if self._auth_dependency else []

        @router.get("/token", dependencies=dependencies)
        def get_token(room: str, identity: str):
            """
            Generates a secure LiveKit Access Token for a frontend client to join the voice room.
            :param room: The name of the room the client is joining.
            :param identity: The identity of the client.
            :return: A dictionary containing the generated JWT token.

            """
            if not self.api_key or not self.api_secret:
                raise HTTPException(
                    status_code=500,
                    detail=(
                        "LiveKit API key or secret not configured. Set them in config.yaml under "
                        "'livekit' or via environment variables such as "
                        "AK_LIVEKIT__API_KEY and AK_LIVEKIT__API_SECRET."
                    ),
                )

            token = api.AccessToken(self.api_key, self.api_secret)
            token.with_identity(identity)
            token.with_name(identity)
            token.with_grants(
                api.VideoGrants(
                    room_join=True,
                    room=room,
                )
            )
            return {"token": token.to_jwt()}

        return router
