import logging

from agentkernel.integration.adapter import GatewayRunner
from agentkernel.integration.livekit import LiveKitEdgeGateway
from agentkernel.pipeline import IOHandler

logging.basicConfig(level=logging.INFO)

gateway = LiveKitEdgeGateway(session_id="room_01")

from fastapi import APIRouter
from agentkernel.api.handler import RESTRequestHandler
from agentkernel.core.config import AKConfig
from livekit import api

class LiveKitTokenHandler(RESTRequestHandler):
    def get_router(self) -> APIRouter:
        router = APIRouter()
        router.add_api_route("/livekit/token", self.get_token, methods=["GET"])
        return router

    def get_token(self, participant_name: str = "user"):
        config = AKConfig.get()
        token = (
            api.AccessToken(config.livekit.api_key, config.livekit.api_secret)
            .with_identity(f"user-{participant_name}")
            .with_name(participant_name)
            .with_grants(api.VideoGrants(room_join=True, room="room_01"))
            .to_jwt()
        )
        return {"token": token}

if __name__ == "__main__":
    IOHandler.run(
        gateways=[GatewayRunner(gateway)],
        handlers=[LiveKitTokenHandler()]
    )

