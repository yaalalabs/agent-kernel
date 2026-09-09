import logging

from ...auth.handler import AuthValidator


class GCPAuthorizer:
    """HTTP-based authorizer for GCP Cloud Run.

    GCP equivalent of APIGatewayAuthorizer for AWS. Registers token validation
    with RESTAPI so that all routes require a valid Bearer token.

    Usage:
        handler = GCPAuthorizer(validator=CustomAuthTokenValidator()).register()
    """

    def __init__(self, validator: AuthValidator):
        self._validator = validator
        self._log = logging.getLogger("ak.deployment.gcp.akauthorizer")

    def register(self) -> None:
        """Register this authorizer with RESTAPI.

        Equivalent of APIGatewayAuthorizer(validator=...).handle in AWS.
        Call this before RESTAPI.run() to enforce authentication on all routes.
        """
        from ...api.http import RESTAPI

        self._log.info("Registering GCP authorizer")
        RESTAPI.add_auth_handlers([self._validator])
