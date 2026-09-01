import hashlib
import hmac
import re
import secrets
import sqlite3
import time
import uuid

from .store import Store


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def password_hash(password, salt=None):
    salt = salt or secrets.token_hex(16)
    result = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=16384, r=8, p=1).hex()
    return f"{salt}:{result}"


class Auth:
    def __init__(self, store: Store, invitation: str):
        self.store = store
        self.invitation = invitation
        self.dummy = password_hash("dummy-password-for-timing")

    def register(self, username, password, invitation):
        username = username.strip().lower()
        if not self.invitation or not hmac.compare_digest(invitation, self.invitation):
            raise ValueError("A valid classroom invitation is required.")
        if not re.fullmatch(r"[a-z0-9_.-]{3,40}", username) or not 12 <= len(password) <= 128:
            raise ValueError("Use a 3–40 character username and a 12–128 character password.")
        user_id = uuid.uuid4().hex
        try:
            with self.store.connect() as db:
                db.execute("INSERT INTO users VALUES (?,?,?)", (user_id, username, password_hash(password)))
        except sqlite3.IntegrityError as exc:
            raise ValueError("That username is unavailable.") from exc
        return {"id": user_id, "username": username}

    def login(self, username, password):
        if len(password) > 128:
            raise ValueError("Invalid username or password.")
        with self.store.connect() as db:
            row = db.execute("SELECT * FROM users WHERE username=?", (username.strip().lower(),)).fetchone()
            expected = row["password"] if row else self.dummy
            actual = password_hash(password, expected.split(":")[0])
            if not hmac.compare_digest(actual, expected) or row is None:
                raise ValueError("Invalid username or password.")
            token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
            db.execute("DELETE FROM sessions WHERE expires < ?", (time.time(),))
            db.execute("INSERT INTO sessions VALUES (?,?,?,?)", (digest(token), row["id"], csrf, time.time() + 86400))
            return token, csrf, {"id": row["id"], "username": row["username"]}

    def resolve(self, token):
        if not token:
            return None
        with self.store.connect() as db:
            row = db.execute(
                "SELECT u.id,u.username,s.csrf FROM sessions s JOIN users u ON u.id=s.user_id WHERE s.token=? AND s.expires>?",
                (digest(token), time.time()),
            ).fetchone()
            return dict(row) if row else None

    def check_csrf(self, token, csrf):
        user = self.resolve(token)
        return bool(user and csrf and hmac.compare_digest(user["csrf"], csrf))

    def logout(self, token):
        with self.store.connect() as db:
            db.execute("DELETE FROM sessions WHERE token=?", (digest(token or ""),))
