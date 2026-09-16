from pydantic import BaseModel, ConfigDict

from app.agent.discovery.models import ActionType


class CapabilityActionContext(BaseModel):
    model_config = ConfigDict(extra="forbid")

    step: int
    action: ActionType

    target_role: str | None = None
    target_name: str | None = None

    value: str | None = None
    url: str | None = None

    reason: str


class CapabilityCompletionContext(BaseModel):
    model_config = ConfigDict(extra="forbid")

    result: str
    reason: str

    final_url: str
    final_observation: str


class CapabilityContext(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user_request: str

    interactions: list[CapabilityActionContext]

    completion: CapabilityCompletionContext