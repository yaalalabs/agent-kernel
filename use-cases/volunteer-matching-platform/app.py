from agentkernel.api import RESTAPI, AgentRESTRequestHandler
from agentkernel.pydanticai import PydanticAIModule

from agent import AGENTS
from telegram_handler import FormattedTelegramRequestHandler

PydanticAIModule(AGENTS)


if __name__ == "__main__":
    # Explicit handler list serves both interfaces together: the web frontend's
    # POST /api/v1/chat (AgentRESTRequestHandler) and Telegram's POST /telegram/webhook
    # (FormattedTelegramRequestHandler — renders markdown as real Telegram formatting,
    # see telegram_handler.py). Slack was attempted and thoroughly investigated but
    # dropped — see README.md's Known Limitations and AGENTS.md for what was tried.
    # RESTAPI.run() with no handlers routes through the queue pipeline instead
    # (api/http.py's activation rule) — passing handlers here takes the direct-serve
    # path these integrations need.
    RESTAPI.run([AgentRESTRequestHandler(), FormattedTelegramRequestHandler()])
