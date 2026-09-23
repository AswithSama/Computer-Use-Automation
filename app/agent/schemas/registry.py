from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.agent.schemas.capability import CapabilityArtifact
from app.agent.schemas.outcomes import BusinessOutcomeRule

ApprovalStatus = Literal["draft", "approved", "rejected"]

class SelectionContext(BaseModel):
    model_config = ConfigDict(extra="forbid")

    use_when: str
    workflow_summary: str
    example_goals: list[str] = Field(default_factory=list)

class StoredCapability(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # Registry metadata: supplied by trusted application context.
    tenant_id: str
    app_id: str

    # Every new capability starts as a draft.
    approval_status: ApprovalStatus = "draft"

    # Registry version; distinct from the artifact schema version.
    version: int = Field(default=1, ge=1)

    artifact: CapabilityArtifact
    selection_context: SelectionContext | None = None

    # Pydantic serializes the rule dataclasses through this model.
    business_outcome_rules: list[BusinessOutcomeRule] = Field(
        default_factory=list
    )
