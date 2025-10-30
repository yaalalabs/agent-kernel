import logging
import traceback
from http import HTTPStatus
from typing import Optional

from slack_sdk.errors import SlackApiError
from slack_bolt.adapter.fastapi import SlackRequestHandler
from slack_bolt import App

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ...core import AgentService, Runtime, Config
from ...api import RESTRequestHandler


class AgentSlackRequestHandler(RESTRequestHandler):
    """
    API routers that expose endpoints to interact Slack with Agent Kernel.
    Endpoints:
    - GET /health: Health check
    - GET /agents: List available agents. Not used by Slack but useful for testing.
    - POST /slack/events: Handle Slack events
    - POST /slack/interactions: Handle Slack interactions
    """
    def __init__(self):
        self._log = logging.getLogger("ak.api.slack")
        self._SLACK_BOT_TOKEN = Config.get().slack.bot_token
        self._SLACK_SIGNING_SECRET = Config.get().slack.signing_secret
        self._SLACK_BOT_USER_ID = Config.get().slack.bot_user_id
        self._SLACK_AGENT = Config.get().slack.agent if Config.get().slack.agent != "" else None

        # Initialize the Slack app
        self._slack_app = App(token=self._SLACK_BOT_TOKEN,
                        signing_secret=self._SLACK_SIGNING_SECRET)
        self._handler = SlackRequestHandler(self._slack_app)
        slack_app = self._slack_app
        
        @slack_app.event("message") #trigger this for any message event
        async def handle_messages(body, event, ack, client):
            ack() #sending the immediate acknowledgement
            if(event["channel_type"] ==  "im"): #if this is a direct message
                await self.handle(body,ack,client)

        @slack_app.event("app_mention")
        async def handle_mentions(body, ack, client):
            await self.handle(body, ack, client)

    def get_router(self) -> APIRouter:
        """
        Returns the APIRouter instance.
        """

        router = APIRouter()

        @router.get("/health")
        def health():
            return {"status": "ok"}

        @router.get("/agents")
        def list_agents():
            return {"agents": list(Runtime.instance().agents().keys())}

        @router.post("/slack/events")
        async def events(req):
            return await self._handler.handle(req)

        @router.post("/slack/interactions")
        async def interactions(req):
            return await self._handler.handle(req)

        
        return router

    async def handle(self, body, ack, client):
        """
        Async method to run the agent.
        :param req: Request an object containing the prompt and optional agent name.
        """
        user = body['event']["user"]
        text = body["event"]["text"]
        channel = body['event']['channel']
        ts = body['event']['ts']
        session = f'{channel}-{user}'  # Unique session per user per channel
        
        # Avoid the bot responding to its own messages
        if user == self._SLACK_BOT_USER_ID:
            return

        mention = f"<@{self._SLACK_BOT_USER_ID}>"
        question = text.replace(mention, "").strip()
        
        service = AgentService()
        try:
            response_for_first_bot_message = client.chat_postMessage(
                channel=channel,
                thread_ts=ts,
                text=f"Hi <@{user}>, Hold on tight, I'm processing your request :rolling-loader:"
            )
            service.select(session_id=session)
            if not service.agent:
                client.chat_postMessage(channel=channel, text="No agent available to handle your request.")
                return

            result = await service.run(question)

            if hasattr(result, 'raw'):
                response_text = str(result.raw)
            else:
                response_text = str(result)

            # This will update the initial message to remove the loading text emoji 
            client.chat_update(
                channel=response_for_first_bot_message['channel'],
                ts=response_for_first_bot_message['ts'],
                text=f"Hi <@{user}>,"
            )
            # post final reply
            client.chat_postMessage(text="Agent response", blocks=self._split_reply(response_text), channel=channel, thread=ts,
                                     metadata={"event_type": "first_pass",
                                               "event_payload": {"id": ts}
                                               })

        except SlackApiError as e:
            self._log.error(f"Slack API Error: {e.response['error']}")
        except Exception as e:
            self._log.error(f"Error handling message: {e}\n{traceback.format_exc()}")
            client.chat_postMessage(channel=channel, text="Error handling your request.")
            return
        
    def _split_reply(self, reply:str)-> list:
        """
        Prepares the reply text.
        :param reply: The reply text.
        :return: The prepared reply text.
        """
        response_chunks = [reply[i:i + 3000] for i in range(0, len(reply), 3000)]  # Current max chunk size in slack is 3000 characters
        self._log.debug(f"chunk {response_chunks}")
        blocks = []
        for i in range(len(response_chunks)):
            if i < 5:  # Limit to first 5 chunks:
                blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": response_chunks[i]}})
            else:
                blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": "Response is truncated due to size restrictions in Slack"}})
       
        
        return blocks
        
    