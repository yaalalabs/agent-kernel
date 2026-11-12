import hmac
import logging
import os

from agentkernel.integration.adapter import EdgeLifecycleRESTRequestHandler
from agentkernel.integration.livekit import LiveKitLifecycleAdapter
from agentkernel.pipeline import IOHandler
from agentkernel.secret import SecretManager

logging.basicConfig(level=logging.INFO)

from fastapi import APIRouter, HTTPException, Request
from agentkernel.api.handler import RESTRequestHandler
from agentkernel.core.config import AKConfig
from livekit import api


class LiveKitTokenHandler(RESTRequestHandler):
    """Development helper that mints a join token for an allowed room.

    The endpoint stays disabled until ``LIVEKIT_TOKEN_SECRET`` is set in the environment or the configured secret
    provider, and then requires that secret in the ``X-LiveKit-Token-Secret`` header. ``LIVEKIT_ALLOWED_ROOMS`` is a
    comma-separated allowlist (default ``call_01``). Protect or remove this route before exposing the service publicly.
    """

    def get_router(self) -> APIRouter:
        router = APIRouter()
        router.add_api_route("/livekit/token", self.get_token, methods=["GET"])
        return router

    def get_token(self, request: Request, participant_name: str = "user", room: str = "call_01"):
        secret = SecretManager.current().get("LIVEKIT_TOKEN_SECRET", None)
        if not secret:
            raise HTTPException(
                status_code=503,
                detail="Set LIVEKIT_TOKEN_SECRET to enable the token endpoint",
            )
        if not hmac.compare_digest(request.headers.get("x-livekit-token-secret", ""), secret):
            raise HTTPException(status_code=401, detail="Unauthorized")
        allowed = {
            name.strip() for name in os.environ.get("LIVEKIT_ALLOWED_ROOMS", "call_01").split(",") if name.strip()
        }
        if room not in allowed:
            raise HTTPException(status_code=403, detail=f"Room '{room}' is not in LIVEKIT_ALLOWED_ROOMS")
        config = AKConfig.get()
        token = (
            api.AccessToken(config.livekit.api_key, config.livekit.api_secret)
            .with_identity(f"user-{participant_name}")
            .with_name(participant_name)
            .with_grants(api.VideoGrants(room_join=True, room=room))
            .to_jwt()
        )
        return {"token": token}


if __name__ == "__main__":
    IOHandler.run(
        handlers=[
            EdgeLifecycleRESTRequestHandler(LiveKitLifecycleAdapter()),
            LiveKitTokenHandler(),
        ]
    )
