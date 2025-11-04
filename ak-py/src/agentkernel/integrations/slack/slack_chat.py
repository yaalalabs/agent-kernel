import logging
import traceback

from fastapi import APIRouter, Request
from slack_bolt.adapter.fastapi.async_handler import AsyncSlackRequestHandler
from slack_bolt.async_app import AsyncApp
from slack_sdk.errors import SlackApiError

from ...api import RESTRequestHandler
from ...core import AgentService, Config


class AgentSlackRequestHandler(RESTRequestHandler):
    """
    API routers that expose endpoints to interact with Slack using Agent Kernel.
    Endpoints:
    - GET /health: Health check
    - GET /agents: List available agents. Not used by Slack but useful for testing.
    - POST /slack/events: Handle Slack events
    """

    def __init__(self):
        self._log = logging.getLogger("ak.api.slack")
        self._slack_agent = Config.get().slack.agent if Config.get().slack.agent != "" else None
        self._slack_agent_acknowledgement = (
            Config.get().slack.agent_acknowledgement if Config.get().slack.agent_acknowledgement != "" else None
        )
        self._bot_id = None

        # Initialize the Slack app
        self._slack_app = AsyncApp()
        self._handler = AsyncSlackRequestHandler(self._slack_app)
        slack_app = self._slack_app

        @slack_app.event("message")  # trigger this for any message event
        async def handle_messages(message, say):
            await self.handle(message, say)

    def get_router(self) -> APIRouter:
        """
        Returns the APIRouter instance.
        """
        router = APIRouter()

        @router.get("/health")
        def health():
            return {"status": "ok"}

        @router.post("/slack/events")
        async def slack_events(req: Request):
            body = await req.json()
            self._log.debug(f"Received Slack event: {body}")
            return await self._handler.handle(req)

        return router

    async def handle(self, body: dict, say):
        """
        Async method to run the agent.
        :param body: dict containing Slack message data.
        :param say: function for sending messages back to Slack.
        """
        user = body["user"]
        text = body["text"]
        channel = body["channel"]

        # in Slack, thread_ts is populated if its a thread message if not, use ts
        thread_ts = body.get("thread_ts", None) or body["ts"]
        if self._bot_id is None:
            self._bot_id = (await self._slack_app.client.auth_test())["user_id"]

        # Avoid the bot responding to its own messages
        if user == self._bot_id:
            return

        mention = f"<@{self._bot_id}>"
        question = text.replace(mention, "").strip()

        self._log.debug(f"Received request from user {user} in channel {channel}: {question}")

        service = AgentService()
        try:
            response_for_first_bot_message = None
            if self._slack_agent_acknowledgement is not None:
                response_for_first_bot_message = await say(
                    channel=channel,
                    thread_ts=thread_ts,
                    text=f"Hi <@{user}>, {self._slack_agent_acknowledgement} :rolling-loader:",
                )
            service.select(session_id=thread_ts, name=self._slack_agent)
            if not service.agent:
                await say(channel=channel, text="No agent available to handle your request.")
                return

            result = await service.run(question)

            if hasattr(result, "raw"):
                response_text = str(result.raw)
            else:
                response_text = str(result)

            # This will update the initial message to remove the loading text emoji
            if response_for_first_bot_message is not None:
                new_ts = response_for_first_bot_message["ts"]
                ch = response_for_first_bot_message["channel"]
                await say.client.chat_update(channel=ch, ts=new_ts, text=f"Hi <@{user}>,")
            else:
                new_ts = thread_ts
                ch = channel

            self._log.debug(f"Agent response: {response_text}")

            # post final reply
            await say(
                text="Agent response",
                blocks=self._split_reply(response_text),
                channel=ch,
                thread_ts=new_ts,
                metadata={"event_type": "first_pass", "event_payload": {"id": new_ts}},
            )

        except SlackApiError as e:
            self._log.error(f"Slack API Error: {e.response['error']}")
        except Exception as e:
            self._log.error(f"Error handling message: {e}\n{traceback.format_exc()}")
            await say(channel=channel, text="Error handling your request.")
            return

    def _split_reply(self, reply: str) -> list:
        """
        Prepares the reply text.
        :param reply: The reply text.
        :return: The prepared reply text.
        """
        response_chunks = [
            reply[i : i + 3000] for i in range(0, len(reply), 3000)
        ]  # Current max chunk size in slack is 3000 characters

        blocks = []
        for i in range(len(response_chunks)):
            if i < 5:  # Limit to first 5 chunks:
                blocks.append(
                    {
                        "type": "section",
                        "text": {"type": "mrkdwn", "text": response_chunks[i]},
                    }
                )
            else:
                blocks.append(
                    {
                        "type": "section",
                        "text": {
                            "type": "mrkdwn",
                            "text": "Response is truncated due to size restrictions in Slack",
                        },
                    }
                )
                break

        return blocks
