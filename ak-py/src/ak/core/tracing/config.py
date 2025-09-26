from typing import Optional, Dict
from pydantic import BaseModel, Field, field_validator

from .enums_and_mappings import TracingProviderEnum, AgentFrameworkEnum


class _TracingFrameworkVariables(BaseModel):
    url: Optional[str] = None


class _TracingConfigPerAgentFramework(BaseModel):
    name: Optional[str] = None
    provider: TracingProviderEnum
    variables: Optional[_TracingFrameworkVariables] = None


class _TracingConfig(BaseModel):
    enabled: bool = True
    name: str = Field(..., description="Global tracer/app name")
    frameworks: Dict[str, _TracingConfigPerAgentFramework] = Field(default_factory=dict)

    @field_validator("frameworks")
    def validate_framework_keys(cls, v: Dict[str, _TracingConfigPerAgentFramework]) -> Dict[str, _TracingConfigPerAgentFramework]:
        invalid = set(v.keys()) - {f.value for f in AgentFrameworkEnum}
        if invalid:
            raise ValueError(
                f"Invalid framework(s): {invalid}. Allowed: {[f.value for f in AgentFrameworkEnum]}"
            )
        return v

