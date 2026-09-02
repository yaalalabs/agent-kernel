import time

import pytest
from fastapi.testclient import TestClient
from test_api import account

from scopewise.app import Settings, create_app
from scopewise.store import Store
from scopewise.telegram import LinkService


def test_link_codes_expire_and_are_single_use(tmp_path):
    store = Store(tmp_path / "telegram.db")
    links = LinkService(store)
    code = links.issue("alice")
    with store.connect() as db:
        assert db.execute("SELECT code FROM link_codes").fetchone()["code"] != code
    links.redeem(123, code)
    assert links.owner(123) == "alice"
    with pytest.raises(ValueError):
        links.redeem(456, code)
    assert links.owner(456) is None
    expired = links.issue("bob")
    with store.connect() as db:
        db.execute("UPDATE link_codes SET expires=?", (time.time() - 1,))
    with pytest.raises(ValueError):
        links.redeem(456, expired)


def test_telegram_requires_secret_private_chat_and_link(tmp_path, monkeypatch):
    monkeypatch.setenv("AK_TELEGRAM__BOT_TOKEN", "12345:test-token-only")
    monkeypatch.setenv("AK_TELEGRAM__WEBHOOK_SECRET", "synthetic-secret-with-at-least-24-characters")
    app = create_app(Settings(data_dir=tmp_path, invitation="test-classroom-invitation"))
    sent = []

    async def send(chat, text, **kwargs):
        sent.append((chat, text))

    monkeypatch.setattr(app.state.telegram, "_send_message", send)
    with TestClient(app) as client:
        account(client)
        code = client.post("/api/telegram/link").json()["code"]
        body = {"update_id": 1, "message": {"message_id": 1, "chat": {"id": 123, "type": "private"}, "from": {"id": 123}, "text": "/link " + code}}
        assert client.post("/telegram/webhook", json=body).status_code == 403
        headers = {"X-Telegram-Bot-Api-Secret-Token": "synthetic-secret-with-at-least-24-characters"}
        group = {**body, "update_id": 2, "message": {**body["message"], "chat": {"id": 123, "type": "group"}}}
        assert client.post("/telegram/webhook", json=group, headers=headers).status_code == 200
        assert not sent
        assert client.post("/telegram/webhook", json=body, headers=headers).status_code == 200
        assert "linked" in sent[-1][1].lower()
        count = len(sent)
        client.post("/telegram/webhook", json=body, headers=headers)
        assert len(sent) == count
        client.delete("/api/telegram/link")
        assert app.state.telegram.links.owner(123) is None
