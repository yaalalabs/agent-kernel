"""Authenticated private-chat extension of Agent Kernel's Telegram integration."""

import hmac
import secrets
import sqlite3
import time

from agentkernel.telegram import AgentTelegramRequestHandler
from fastapi import APIRouter, BackgroundTasks, HTTPException, Request

from .security import digest


class LinkService:
    def __init__(self, store):
        self.store = store

    def issue(self, owner):
        code = secrets.token_urlsafe(24)
        with self.store.connect() as db:
            db.execute("DELETE FROM link_codes WHERE owner=? OR expires<?", (owner, time.time()))
            db.execute("INSERT INTO link_codes VALUES (?,?,?)", (digest(code), owner, time.time() + 600))
        return code

    def redeem(self, chat_id, code):
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT owner FROM link_codes WHERE code=? AND expires>?", (digest(code), time.time())).fetchone()
            if not row:
                raise ValueError("Link code is invalid or expired. Generate a new one in your web workspace.")
            db.execute("DELETE FROM link_codes WHERE code=?", (digest(code),))
            db.execute("DELETE FROM telegram_links WHERE chat_id=? OR owner=?", (str(chat_id), row["owner"]))
            db.execute("INSERT INTO telegram_links VALUES (?,?)", (str(chat_id), row["owner"]))

    def owner(self, chat_id):
        with self.store.connect() as db:
            row = db.execute("SELECT owner FROM telegram_links WHERE chat_id=?", (str(chat_id),)).fetchone()
            return row["owner"] if row else None

    def unlink(self, owner):
        with self.store.connect() as db:
            db.execute("DELETE FROM telegram_links WHERE owner=?", (owner,))
            db.execute("DELETE FROM link_codes WHERE owner=?", (owner,))


class ScopeWiseTelegram(AgentTelegramRequestHandler):
    def __init__(self, store, jobs, secret):
        if len(secret) < 24:
            raise ValueError("Telegram requires a random webhook secret of at least 24 characters.")
        super().__init__()
        self.store, self.jobs, self.links = store, jobs, LinkService(store)
        self.secret = secret
        self.inflight = 0

    def get_router(self):
        router = APIRouter()

        @router.post("/telegram/webhook")
        async def webhook(request: Request, background: BackgroundTasks):
            if not hmac.compare_digest(request.headers.get("X-Telegram-Bot-Api-Secret-Token", ""), self.secret):
                raise HTTPException(403, "Invalid webhook secret.")
            try:
                body = await request.json()
            except ValueError:
                raise HTTPException(400, "Invalid JSON.") from None
            if not isinstance(body, dict) or type(body.get("update_id")) is not int:
                raise HTTPException(400, "Invalid update.")
            message = body.get("message", {})
            if not isinstance(message, dict):
                raise HTTPException(400, "Invalid message.")
            chat, sender = message.get("chat", {}), message.get("from", {})
            if not isinstance(chat, dict) or not isinstance(sender, dict):
                raise HTTPException(400, "Invalid message.")
            # Do not forward groups, media, edited messages, or callback data to the model.
            if chat.get("type") != "private" or type(chat.get("id")) is not int or chat.get("id") != sender.get("id"):
                return {"ok": True}
            if not isinstance(message.get("text"), str) or not message.get("message_id"):
                return {"ok": True}
            if self.inflight >= 3:
                raise HTTPException(503, "Telegram queue is full. Retry later.")
            with self.store.connect() as db:
                db.execute("DELETE FROM telegram_updates WHERE created<?", (time.time() - 604800,))
                try:
                    db.execute("INSERT INTO telegram_updates VALUES (?,?)", (body["update_id"], time.time()))
                except sqlite3.IntegrityError:
                    return {"ok": True}
            if not self.store.allow(f"telegram:{chat['id']}", 20, 60):
                return {"ok": True}
            self.inflight += 1
            background.add_task(self.process, message)
            return {"ok": True}

        return router

    async def process(self, message):
        try:
            # Native Agent Kernel dispatches commands vs agent messages and sends replies.
            await self._handle_message(message)
        except Exception:
            # Never log webhook bodies, linking codes or bot-token-bearing exception URLs.
            self._log.warning("Telegram processing failed; ask the user to resend the message.")
        finally:
            self.inflight -= 1

    async def _handle_command(self, chat_id, command):
        parts = command.split(maxsplit=1)
        if parts[0] == "/link":
            if len(parts) != 2:
                return await self._send_message(chat_id, "Send /link followed by the single-use code from your web workspace.")
            try:
                self.links.redeem(chat_id, parts[1])
                return await self._send_message(
                    chat_id, "Workspace linked. Send /courses, then /use 1 to select a module. Telegram can see messages you send here."
                )
            except ValueError as exc:
                return await self._send_message(chat_id, str(exc))
        owner = self.links.owner(chat_id)
        if parts[0] == "/unlink" and owner:
            self.links.unlink(owner)
            return await self._send_message(chat_id, "Workspace disconnected.")
        if not owner:
            return await self._send_message(
                chat_id, "Connect your account using a code from the ScopeWise web workspace. Send /link CODE in this private chat."
            )
        courses = self.store.list(owner, "course")
        if parts[0] == "/courses":
            return await self._send_message(
                chat_id, "\n".join(f"{i}. {c['title']}" for i, c in enumerate(courses, 1)) or "Create a module in your web workspace first."
            )
        if parts[0] == "/use":
            try:
                index = int(parts[1]) - 1
                if index < 0 or index >= len(courses):
                    raise ValueError()
                course = courses[index]
                existing = self.store.list(owner, "telegram_context")
                self.store.put(owner, "telegram_context", None, {"selected_course": course["id"]}, existing[0]["id"] if existing else None)
                return await self._send_message(
                    chat_id, f"Selected {course['title']}. Ask what needs practice or request a pack from reviewed questions."
                )
            except (ValueError, IndexError):
                return await self._send_message(chat_id, "Send /courses, then /use followed by a valid module number.")
        return await self._send_message(
            chat_id,
            (
                "Commands: /courses, /use NUMBER, /unlink. Ask about coverage or request a reviewed practice "
                "pack. Upload and approve sources in the web workspace."
            ),
        )

    async def _process_agent_message(self, chat_id, message_text, message=None):
        owner = self.links.owner(chat_id)
        if not owner:
            return await self._handle_command(chat_id, "/start")
        if not message_text or len(message_text) > 2000:
            return await self._send_message(chat_id, "Use a text message of at most 2,000 characters. Upload documents in the web workspace.")
        selected = self.store.list(owner, "telegram_context")
        if not selected:
            return await self._send_message(chat_id, "Select a module first: /courses, then /use NUMBER.")
        course_id = selected[0]["selected_course"]
        try:
            self.store.get(owner, "course", course_id)
        except KeyError:
            return await self._send_message(chat_id, "That module was deleted. Send /courses to select another.")
        if self.jobs.lock.locked() or self.jobs.tasks:
            return await self._send_message(chat_id, "The local model is busy. Please send your question again after the current analysis finishes.")
        if not self.store.allow(f"chat:{owner}", 30, 3600):
            return await self._send_message(chat_id, "Hourly assistant limit reached. Please try again later.")
        async with self.jobs.lock:
            try:
                reply = await self.jobs.model().chat(owner, course_id, message_text)
            except Exception:
                reply = "The local assistant could not complete this request. Please check the web workspace and try again."
        if self.links.owner(chat_id) == owner:
            await self._send_message(chat_id, str(reply))
