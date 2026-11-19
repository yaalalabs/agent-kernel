"""Response-handler Lambda: consumes the Output Queue and stores each reply for the caller waiting on it."""

from agentkernel.aws import ResponseHandler

handler = ResponseHandler.handle
