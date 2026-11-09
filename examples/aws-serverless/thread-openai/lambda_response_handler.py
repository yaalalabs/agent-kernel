"""Response-handler Lambda: consumes the Output Queue and writes each reply to the response store
for the chat route's wait. Nothing here mentions threads: the agent runner records the reply.
"""

from agentkernel.aws import ResponseHandler

handler = ResponseHandler.handle
