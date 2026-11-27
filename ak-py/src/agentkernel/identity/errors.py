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


class CredentialError(Exception):
    """A credential a run needs cannot be had: it cannot be decrypted, or (later) found or exchanged.

    The message never carries a credential or a key. A tool turns it into an error result for the model.
    """
