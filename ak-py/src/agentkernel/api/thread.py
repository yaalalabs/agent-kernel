"""
REST request handler exposing Conversation Thread Support read endpoints.
"""

import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Request

from ..core.thread import Authoriser, ConversationThreadManager
from .handler import RESTRequestHandler


class ThreadRESTRequestHandler(RESTRequestHandler):
    """
    API router that exposes endpoints to read conversation threads.
    Endpoints:
    - GET /threads: List threads filtered by user_id and/or group_id
    - GET /threads/{session_id}: Get a thread with full message history

    When an Authoriser is supplied, every request must carry a Bearer token that
    the Authoriser resolves to a user_id; listings are scoped to that user and
    thread reads enforce ownership. Without an Authoriser, routes are open.
    """

    def __init__(self, authoriser: Optional[Authoriser] = None):
        """
        Initializes a ThreadRESTRequestHandler instance.
        :param authoriser: Optional user-supplied Authoriser protecting the thread routes.
        """
        self._log = logging.getLogger("ak.api.thread")
        self._authoriser = authoriser

    def _resolve_user(self, request: Request) -> Optional[str]:
        """
        Resolve the caller's user_id via the configured Authoriser.
        :param request: The incoming FastAPI request.
        :return: The resolved user_id, or None when no Authoriser is configured.
        :raises HTTPException: 401 when a token is missing or rejected.
        """
        if self._authoriser is None:
            return None
        auth_header = request.headers.get("authorization")
        if auth_header is None:
            raise HTTPException(status_code=401, detail="Missing authorization header")
        token = auth_header.replace("Bearer ", "").strip()
        user_id = self._authoriser.authorise(token)
        if user_id is None:
            raise HTTPException(status_code=401, detail="Unauthorized")
        return user_id

    def get_router(self) -> APIRouter:
        """
        Returns the APIRouter instance.
        """
        router = APIRouter()

        @router.get("/threads")
        def list_threads(
            request: Request,
            user_id: Optional[str] = None,
            group_id: Optional[str] = None,
            limit: Optional[int] = None,
            cursor: Optional[str] = None,
        ):
            manager = ConversationThreadManager.get()
            if manager is None:
                raise HTTPException(status_code=404, detail="Thread support is not enabled")
            resolved_user_id = self._resolve_user(request)
            if resolved_user_id is not None:
                user_id = resolved_user_id  # listings are forced to the authorised user
            try:
                page = manager.list_threads(user_id=user_id, group_id=group_id, limit=limit, cursor=cursor)
            except ValueError as e:
                raise HTTPException(status_code=400, detail=str(e))
            return {
                "threads": [thread.model_dump(mode="json", exclude={"messages"}) for thread in page.threads],
                "next_cursor": page.next_cursor,
            }

        @router.get("/threads/{session_id}")
        def get_thread(session_id: str, request: Request, limit: Optional[int] = None, cursor: Optional[str] = None):
            manager = ConversationThreadManager.get()
            if manager is None:
                raise HTTPException(status_code=404, detail="Thread support is not enabled")
            resolved_user_id = self._resolve_user(request)
            try:
                thread = manager.get_thread(session_id, user_id=resolved_user_id)
            except PermissionError:
                raise HTTPException(status_code=403, detail="Thread is not owned by the authorised user")
            if thread is None:
                raise HTTPException(status_code=404, detail=f"Thread {session_id} not found")
            try:
                page = manager.get_messages(session_id, limit=limit, cursor=cursor)
            except ValueError as e:
                raise HTTPException(status_code=400, detail=str(e))
            body = thread.model_dump(mode="json", exclude={"messages"})
            body["messages"] = [message.model_dump(mode="json") for message in page.messages]
            body["next_cursor"] = page.next_cursor
            return body

        return router
