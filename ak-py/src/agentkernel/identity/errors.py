"""Typed errors of the identity capability."""


class AuthenticationError(Exception):
    """A credential was presented and could not be accepted.

    The reason (the exception message) is for the operator's log: a surface answers the client
    with ``public_detail`` only, a generic ``Unauthorized`` unless the failure is in the shape of
    the credential itself, so a caller learns nothing about why a token was refused.
    """

    def __init__(self, reason: str, *, public_detail: str = "Unauthorized"):
        super().__init__(reason)
        self.public_detail = public_detail
