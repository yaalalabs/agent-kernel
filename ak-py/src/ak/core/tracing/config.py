from typing import Optional, Dict
from pydantic import BaseModel, Field, field_validator, model_validator

from .enums_and_mappings import TracingProviderEnum
from ..enums import AgentFrameworkEnum


class TracingFrameworkVariables(BaseModel):
    url: Optional[str] = None


class TracingConfigPerAgentFramework(BaseModel):
    name: Optional[str] = None
    provider: TracingProviderEnum
    variables: Optional[TracingFrameworkVariables] = None

    @model_validator(mode="before")
    @classmethod
    def ensure_variables(cls, values): # This is done because for example when doing <TracingConfigPerAgentFramework instance>.variables.url we can get "NoneType has no attribute url" error instead of giving None
        if values.get("variables") is None:
            values["variables"] = TracingFrameworkVariables()
        return values


class TracingConfig(BaseModel):
    enabled: bool = False
    name: str = Field(default="ak-tracer", description="Global tracer/app name")
    frameworks: Dict[str, TracingConfigPerAgentFramework] = Field(default_factory=dict)

    @field_validator("frameworks")
    def validate_framework_keys(cls, v: Dict[str, TracingConfigPerAgentFramework]) -> Dict[str, TracingConfigPerAgentFramework]:
        invalid = set(v.keys()) - {f.value for f in AgentFrameworkEnum}
        if invalid:
            raise ValueError(
                f"Invalid framework(s): {invalid}. Allowed: {[f.value for f in AgentFrameworkEnum]}"
            )
        return v

