import json
import re
from dataclasses import asdict
from pathlib import Path
from typing import Literal
from uuid import uuid4

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


class CapabilityRegistry:
    def __init__(
        self,
        directory: str = "capabilities",
    ):
        self.directory = Path(directory)

    @staticmethod
    def _safe_id(value: str) -> str:
        if not re.fullmatch(r"[A-Za-z0-9_-]+", value):
            raise ValueError("Invalid registry identifier.")
        return value

    def save_draft(
        self,
        *,
        tenant_id: str,
        app_id: str,
        artifact: CapabilityArtifact,
        selection_context: SelectionContext,
        business_outcome_rules: tuple[BusinessOutcomeRule, ...] = (),
    ) -> Path:
        tenant_id = self._safe_id(tenant_id)
        app_id = self._safe_id(app_id)

        existing_versions = [
            stored.version
            for _, stored in self.list_eligible(
                tenant_id=tenant_id,
                app_id=app_id,
            )
            if stored.artifact.capability_id == artifact.capability_id
        ]

        stored = StoredCapability(
            tenant_id=tenant_id,
            app_id=app_id,
            approval_status="draft",
            version=max(existing_versions, default=0) + 1,
            artifact=artifact,
            selection_context=selection_context,
            business_outcome_rules=list(business_outcome_rules),
        )

        folder = self.directory / tenant_id / app_id
        folder.mkdir(parents=True, exist_ok=True)

        filename = (
            f"{self._safe_id(artifact.capability_id)}_"
            f"{uuid4().hex}.json"
        )
        path = folder / filename

        with path.open("x", encoding="utf-8") as stream:
            stream.write(stored.model_dump_json(indent=2) + "\n")

        return path
    def load(self, path: Path) -> StoredCapability:
        return StoredCapability.model_validate_json(
            path.read_text(encoding="utf-8")
        )

    def list_eligible(
        self,
        *,
        tenant_id: str,
        app_id: str,
    ) -> list[tuple[Path, StoredCapability]]:
        tenant_id = self._safe_id(tenant_id)
        app_id = self._safe_id(app_id)

        folder = self.directory / tenant_id / app_id

        if not folder.exists():
            return []

        eligible = []

        for path in folder.glob("*.json"):
            stored = self.load(path)

            # Verify the file's contents, not just its directory.
            if (
                stored.tenant_id == tenant_id
                and stored.app_id == app_id
                and stored.approval_status == "approved"
            ):
                eligible.append((path, stored))

        return eligible


    def approve_draft(self, draft_path: Path) -> Path:
        draft_path = Path(draft_path).resolve()
        draft = self.load(draft_path)

        expected_folder = (
            self.directory
            / self._safe_id(draft.tenant_id)
            / self._safe_id(draft.app_id)
        ).resolve()

        if draft_path.parent != expected_folder:
            raise ValueError("Draft is outside its registered tenant/app folder.")

        if draft.approval_status != "draft":
            raise ValueError("Only draft capabilities can be approved.")

        # Do not approve two different artifacts under the same
        # tenant, app, capability ID, and version.
        for _, existing in self.list_eligible(
            tenant_id=draft.tenant_id,
            app_id=draft.app_id,
        ):
            if (
                existing.artifact.capability_id
                == draft.artifact.capability_id
                and existing.version == draft.version
            ):
                raise ValueError(
                    "An approved capability with this ID and version already exists."
                )

        approved = StoredCapability.model_validate(
            {
                **draft.model_dump(),
                "approval_status": "approved",
            }
        )

        approved_path = expected_folder / (
            f"{self._safe_id(draft.artifact.capability_id)}"
            f"_v{draft.version}_approved_{uuid4().hex}.json"
        )

        # Create a new approved snapshot. Never overwrite the draft.
        with approved_path.open("x", encoding="utf-8") as stream:
            stream.write(approved.model_dump_json(indent=2) + "\n")

        return approved_path