"""Response-handler Lambda: consumes the Output Queue.

A Slack reply (a message with an `integration` attribute) goes back to Slack through the Slack
outbound adapter, whatever the execution mode; a chat reply goes to the response store for the
client's poll.
"""

from agentkernel.aws import ResponseHandler

handler = ResponseHandler.handle
