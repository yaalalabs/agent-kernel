import logging

from agentkernel.integration.adapter import GatewayRunner
from agentkernel.livekit import LiveKitEdgeGateway
from agentkernel.pipeline import IOHandler

logging.basicConfig(level=logging.INFO)

gateway = LiveKitEdgeGateway(session_id="room_01")

from agentkernel.api.handler import RESTRequestHandler
from fastapi import APIRouter


class LiveKitTokenHandler(RESTRequestHandler):
    def get_router(self) -> APIRouter:
        router = APIRouter()
        router.add_api_route("/livekit/token", self.get_token, methods=["GET"])
        return router

    def get_token(self, participant_name: str = "user"):
        # The gateway signs it with the LiveKit settings it already reads, for the room it serves.
        token = gateway.participant_token(f"user-{participant_name}", participant_name)
        return {"token": token}


if __name__ == "__main__":
    IOHandler.run(gateways=[GatewayRunner(gateway)], handlers=[LiveKitTokenHandler()])
