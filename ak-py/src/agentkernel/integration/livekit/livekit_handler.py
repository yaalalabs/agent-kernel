import asyncio
import logging
from typing import Callable

from fastapi import APIRouter, HTTPException
from livekit import agents, api
from livekit.agents import AgentServer, JobContext, WorkerOptions, WorkerType, llm
from livekit.agents.types import DEFAULT_API_CONNECT_OPTIONS, NOT_GIVEN, APIConnectOptions, NotGivenOr
from livekit.agents.voice import Agent as VoicePipelineAgent
from livekit.agents.voice import AgentSession
from livekit.plugins import deepgram, openai, silero

from ...api import RESTRequestHandler
from ...core import AgentService, Config
from ...core.model import AgentReplyText

logger = logging.getLogger("ak.integration.livekit")


class AgentKernelLLMStream(llm.LLMStream):
    """
    A simple LLMStream implementation that yields a single response string.
    LiveKit's TTS engine consumes this stream and synthesizes it into speech.
    """

    def __init__(self, parent_llm: llm.LLM, text: str, chat_ctx: llm.ChatContext):
        super().__init__(parent_llm, chat_ctx=chat_ctx, tools=[], conn_options=DEFAULT_API_CONNECT_OPTIONS)
        self._text = text

    async def _run(self) -> None:
        pass

    async def __anext__(self):
        if self._text is None:
            raise StopAsyncIteration

        text = self._text
        self._text = None

        return llm.ChatChunk(id="agent_kernel_chunk", delta=llm.ChoiceDelta(content=text, role="assistant"))


class AgentKernelLLMStreamWrapper(llm.LLMStream):
    """
    An asynchronous generator wrapper that bridges LiveKit's streaming interface
    with Agent Kernel's request-response architecture. It awaits the Agent Kernel
    response and yields it to the LiveKit voice pipeline.
    """

    def __init__(self, parent_llm: llm.LLM, chat_ctx: llm.ChatContext, agent_name: str, session_id: str, user_message: str):
        super().__init__(parent_llm, chat_ctx=chat_ctx, tools=[], conn_options=DEFAULT_API_CONNECT_OPTIONS)
        self.agent_name = agent_name
        self.session_id = session_id
        self.user_message = user_message
        self._service = AgentService()
        self._fetched = False

    async def _run(self) -> None:
        pass

    async def __anext__(self):
        if self._fetched:
            raise StopAsyncIteration

        self._fetched = True

        # Select the agent and session
        self._service.select(name=self.agent_name, session_id=self.session_id)

        if not self._service.agent:
            return llm.ChatChunk(
                id="agent_kernel_chunk", delta=llm.ChoiceDelta(content="Error: No agent available to handle this request.", role="assistant")
            )

        try:
            # Run the agent
            reply = await self._service.run(self.user_message)
            response_text = str(reply)
        except Exception as e:
            logger.error(f"Agent Kernel error: {e}", exc_info=True)
            response_text = "I'm sorry, I encountered an internal error while processing your request."

        return llm.ChatChunk(id="agent_kernel_chunk", delta=llm.ChoiceDelta(content=response_text, role="assistant"))


class AgentKernelLLM(llm.LLM):
    """
    A custom LiveKit LLM implementation that intercepts user speech (transcribed to text)
    and routes it to the Agent Kernel runtime, bypassing direct LLM API calls.
    """

    def __init__(self, agent_name: str, session_id: str):
        super().__init__()
        self.agent_name = agent_name
        self.session_id = session_id
        self._service = AgentService()

    def chat(
        self,
        *,
        chat_ctx: llm.ChatContext,
        tools: list[llm.Tool] | None = None,
        conn_options: APIConnectOptions = DEFAULT_API_CONNECT_OPTIONS,
        parallel_tool_calls: NotGivenOr[bool] = NOT_GIVEN,
        tool_choice: NotGivenOr[llm.ToolChoice] = NOT_GIVEN,
        extra_kwargs: NotGivenOr[dict] = NOT_GIVEN,
    ) -> "AgentKernelLLMStreamWrapper | AgentKernelLLMStream":
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
            return AgentKernelLLMStream(self, "I did not hear anything.", chat_ctx)

        logger.debug(f"Received transcribed user speech: {user_message}")

        return AgentKernelLLMStreamWrapper(
            parent_llm=self,
            chat_ctx=chat_ctx,
            agent_name=self.agent_name,
            session_id=self.session_id,
            user_message=user_message,
        )


async def _default_entrypoint(ctx: JobContext):
    """
    Default entrypoint for the LiveKit worker.
    Initializes an AgentSession using Deepgram (STT), OpenAI (TTS), and AgentKernel (LLM).
    """
    logger.info(f"Connecting to room {ctx.room.name}")
    vad = silero.VAD.load()

    agent_name = Config.get().livekit.agent
    if not agent_name:
        logger.warning("No agent configured for LiveKit interactions. Set 'agent' under 'livekit' in config.yaml.")

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

    agent = VoicePipelineAgent(
        vad=vad,
        stt=stt_plugin,
        llm=AgentKernelLLM(agent_name=agent_name, session_id=ctx.room.name),
        tts=tts_plugin,
        instructions="You are a helpful voice assistant.",
    )

    await ctx.connect(auto_subscribe=agents.AutoSubscribe.AUDIO_ONLY)

    session = AgentSession()
    await session.start(agent, room=ctx.room)


class AgentLiveKitRequestHandler(RESTRequestHandler):
    """
    RESTRequestHandler for LiveKit Integration.

    This handler achieves two things:
    1. Exposes a REST API endpoint (`/livekit/token`) to generate secure access tokens for frontend clients.
    2. Runs a LiveKit Worker as a background asyncio task seamlessly tied to the FastAPI lifecycle.
    """

    def __init__(self, entrypoint_fnc: Callable[[JobContext], None] = None):
        self._log = logging.getLogger("ak.api.livekit")
        self._entrypoint = entrypoint_fnc or _default_entrypoint
        self._worker_task = None

        # Pull config
        self.url = Config.get().livekit.url
        self.api_key = Config.get().livekit.api_key
        self.api_secret = Config.get().livekit.api_secret

    def get_router(self) -> APIRouter:
        router = APIRouter(prefix="/livekit", tags=["LiveKit Integration"])

        @router.on_event("startup")
        async def startup_event():
            if getattr(self, "_worker_started", False):
                return
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

            # Set port to 0 to assign a random port, avoiding conflicts on 8081
            kwargs["port"] = 0

            # We initialize the AgentServer and start it as an asyncio task
            worker_opts = WorkerOptions(agent_name="agent-kernel-worker", entrypoint_fnc=self._entrypoint, worker_type=WorkerType.ROOM, **kwargs)

            server = AgentServer.from_server_options(worker_opts)
            self._worker_task = asyncio.create_task(server.run())

        @router.get("/token")
        def get_token(room: str, identity: str):
            """
            Generates a secure LiveKit Access Token for a frontend client to join the voice room.
            """
            if not self.api_key or not self.api_secret:
                raise HTTPException(status_code=500, detail="LiveKit API Key or Secret not configured in config.yaml under 'livekit'")

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
