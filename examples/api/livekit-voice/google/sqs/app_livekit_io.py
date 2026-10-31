import logging

from agentkernel.integration.adapter import GatewayRunner
from agentkernel.integration.livekit import LiveKitEdgeGateway
from agentkernel.pipeline import IOHandler

logging.basicConfig(level=logging.INFO)

gateway = LiveKitEdgeGateway(session_id="room_01")

from agentkernel.api.handler import RESTRequestHandler
from agentkernel.core.config import AKConfig
from agentkernel.secret import SecretManager
from fastapi import APIRouter
from livekit import api


class LiveKitTokenHandler(RESTRequestHandler):
    def get_router(self) -> APIRouter:
        router = APIRouter()
        router.add_api_route("/livekit/token", self.get_token, methods=["GET"])
        return router

    def get_token(self, participant_name: str = "user"):
        config = AKConfig.get()
        # An empty livekit field falls back to the secret provider (SSM), as the gateway's own do.
        api_key = config.livekit.api_key or SecretManager.current().get("AK_LIVEKIT__API_KEY")
        api_secret = config.livekit.api_secret or SecretManager.current().get("AK_LIVEKIT__API_SECRET")
        token = (
            api.AccessToken(api_key, api_secret)
            .with_identity(f"user-{participant_name}")
            .with_name(participant_name)
            .with_grants(api.VideoGrants(room_join=True, room="room_01"))
            .to_jwt()
        )
        return {"token": token}


if __name__ == "__main__":
    IOHandler.run(gateways=[GatewayRunner(gateway)], handlers=[LiveKitTokenHandler()])
