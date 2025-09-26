from enum import Enum

class AgentFrameworkEnum(str, Enum):
    openai = "openai"
    langgraph = "langgraph"
    crewai = "crewai"
