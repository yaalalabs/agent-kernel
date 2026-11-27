import hashlib
import hmac


class TokenSigner:
    """Signs `<user>.<hmac-sha256-hex(secret, user)>`; the same line as the app's BenchIdentityProvider."""

    def __init__(self, secret: str):
        self._secret = secret.encode("utf-8")

    def token(self, user: str) -> str:
        return f"{user}.{hmac.new(self._secret, user.encode('utf-8'), hashlib.sha256).hexdigest()}"

    @staticmethod
    def user(client: int) -> str:
        return f"bench-{client}"
