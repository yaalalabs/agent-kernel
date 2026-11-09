"""Typed errors of the identity capability."""


class AuthenticationError(Exception):
    """A credential was presented and could not be accepted.

    The reason is for the operator's log: surfaces answer the client with a generic 401 (or the
    WebSocket policy-violation close) and never echo it, so a caller learns nothing about why.
    """
