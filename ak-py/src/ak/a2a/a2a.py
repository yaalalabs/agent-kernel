from .. import Agent
from ..core import Runtime
from ..core.config import AKConfig


class A2A:

    @staticmethod
    def get_cards():
        cards = []
        if not AKConfig.a2a.enabled:
            return cards
        agents: dict[str, Agent] = Runtime.instance().agents()
        for name, agent in agents.items():
            whitelisted = AKConfig.a2a.agents == ["*"] or name in AKConfig.a2a.agents
            if not whitelisted:
                continue
            cards.append(agent.get_a2a_card())
        return cards
