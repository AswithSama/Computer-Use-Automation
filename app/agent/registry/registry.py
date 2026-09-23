
import logging
import re
from pathlib import Path
from uuid import uuid4

from app.agent.schemas.capability import CapabilityArtifact
from app.agent.schemas.outcomes import BusinessOutcomeRule
from app.agent.schemas.registry import (
    SelectionContext,
    StoredCapability,
)

logger = logging.getLogger(__name__)


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

    def list_drafts(self) -> list[Path]:
        """
        Return pending capability draft paths across all tenants
        and applications.

        Invalid records and records whose metadata does not match
        their registry location are skipped.
        """
        if not self.directory.exists():
            return []

        pending = []

        for path in sorted(self.directory.glob("*/*/*.json")):
            try:
                stored = self.load(path)
            except Exception as exc:
                logger.warning(
                    "Could not load %s: %s",
                    path,
                    exc,
                )
                continue

            if stored.approval_status != "draft":
                continue

            # Verify that the stored metadata agrees with
            # the tenant/application directory.
            if (
                path.parent.name != stored.app_id
                or path.parent.parent.name != stored.tenant_id
            ):
                logger.warning(
                    "Registry location mismatch: %s",
                    path,
                )
                continue

            pending.append(path)

        return pending

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

    def is_approved(
        self,
        draft: StoredCapability,
    ) -> bool:
        """
        Check whether the same capability version has already
        been approved for this tenant and application.
        """
        eligible = self.list_eligible(
            tenant_id=draft.tenant_id,
            app_id=draft.app_id,
        )

        return any(
            existing.artifact.capability_id
            == draft.artifact.capability_id
            and existing.version == draft.version
            for _, existing in eligible
        )

    def approve_draft(self, draft_path: Path) -> Path:
        draft_path = Path(draft_path).resolve()
        draft = self.load(draft_path)

        expected_folder = (
            self.directory
            / self._safe_id(draft.tenant_id)
            / self._safe_id(draft.app_id)
        ).resolve()

        if draft_path.parent != expected_folder:
            raise ValueError(
                "Draft is outside its registered tenant/app folder."
            )

        if draft.approval_status != "draft":
            raise ValueError(
                "Only draft capabilities can be approved."
            )

        # Prevent duplicate approved capability versions.
        if self.is_approved(draft):
            raise ValueError(
                "An approved capability with this ID "
                "and version already exists."
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

        # Create a new approved snapshot.
        # Never overwrite the original draft.
        with approved_path.open("x", encoding="utf-8") as stream:
            stream.write(
                approved.model_dump_json(indent=2) + "\n"
            )

        return approved_path