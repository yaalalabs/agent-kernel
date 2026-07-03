from ....core.config import AKConfig, ExecutionMode
from .akagentrunner import ServerlessAgentRunner as _SyncRunner
from .akagentrunner import ServerlessStreamAgentRunner as _StreamRunner
from .akauthorizer import APIGatewayAuthorizer
from .aklambda import Lambda
from .akresponsehandler import ResponseHandler
from .akwsconnectionhandler import WebsocketConnectionHandler

_config = AKConfig.get()
if _config.execution.mode == ExecutionMode.STREAM:
    ServerlessAgentRunner = _StreamRunner
else:
    ServerlessAgentRunner = _SyncRunner
