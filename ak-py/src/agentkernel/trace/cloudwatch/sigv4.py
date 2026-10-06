from __future__ import annotations

import logging

import requests
from botocore.auth import SigV4Auth
from botocore.awsrequest import AWSRequest
from botocore.session import Session as BotocoreSession
from google.protobuf.message import DecodeError
from google.rpc.status_pb2 import Status


class SigV4Session(requests.Session):
    """
    A requests session that signs every request with AWS Signature Version 4.

    The X-Ray OTLP endpoint (``https://xray.<region>.amazonaws.com/v1/traces``) accepts SigV4 auth only,
    so this session is handed to the stock OTLP/HTTP span exporter, which posts each batch through it.
    """

    def __init__(self, region: str, service: str = "xray", botocore_session: BotocoreSession | None = None):
        """
        Initializes a SigV4Session instance.
        :param region: The AWS region to sign for.
        :param service: The AWS service to sign for.
        :param botocore_session: The botocore session that resolves credentials; defaults to the standard chain.
        """
        super().__init__()
        self.region = region
        self.service = service
        self._botocore_session = botocore_session or BotocoreSession()
        self._log = logging.getLogger("ak.trace.cloudwatch")

    def request(self, method, url, *args, data=None, headers=None, **kwargs):
        """
        Signs the request body and sends it. Raises NoCredentialsError when no credentials resolve, which
        the span processor logs, rather than sending a request the endpoint would reject.
        """
        # botocore caches the resolved credentials on its session; refreshable ones rotate on access
        credentials = self._botocore_session.get_credentials()
        signed = AWSRequest(method=method, url=url, data=data, headers={"Content-Type": "application/x-protobuf"})
        SigV4Auth(credentials, self.service, self.region).add_auth(signed)
        response = super().request(method, url, *args, data=data, headers={**(headers or {}), **dict(signed.headers)}, **kwargs)
        if response.status_code >= 400:
            self._log.error("X-Ray in %s rejected the span export (HTTP %s): %s", self.region, response.status_code, self._rejection(response))
        return response

    @staticmethod
    def _rejection(response: requests.Response) -> str:
        """
        The message of the OTLP google.rpc.Status a rejected export returns, or the raw body if it is not one.
        """
        try:
            message = Status.FromString(response.content).message
        except DecodeError:
            message = ""
        return message or response.text
