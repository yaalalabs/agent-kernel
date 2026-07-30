from ....core.config import AKConfig, ExecutionMode
from .akagentrunner import ECSAgentRunner as _SyncECSAgentRunner
from .akagentrunner import ECSStreamAgentRunner as _StreamECSAgentRunner
from .akoutputconsumer import ECSOutputConsumer
from .core.api import AWSRestAPI, AWSWebsocketAPI, ECSWebSocketRequestHandler, ECSWebSocketSystemRequestHandler
from .ecs_io_handler import ECSIOHandler

_config = AKConfig.get()
if _config.execution.mode == ExecutionMode.STREAM:
    ECSAgentRunner = _StreamECSAgentRunner
else:
    ECSAgentRunner = _SyncECSAgentRunner
