"""Coordinate synchronous handoff without owning the browser lifecycle."""

import json
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

from app.agent.handoff.decision import RecoveryDecision
from app.agent.handoff.models import (
    ControlOwner,
    HandoffState,
    InterventionOutcome,
    InterventionRequest,
    InterventionResolution,
    InterventionStatus,
)
from app.agent.handoff.operator import ACTION_SUMMARIES, HumanOperator


class HumanHandoffManager:
    def __init__(
        self,
        *,
        operator: HumanOperator,
        evidence_dir: str | Path = "evidence/handoff",
    ):
        self.operator = operator
        self.evidence_dir = Path(evidence_dir)
        self._state: HandoffState | None = None

    @property
    def state(self) -> HandoffState | None:
        # Prevent callers from changing ownership behind the manager.
        if self._state is None:
            return None

        return self._state.model_copy(deep=True)

    def request_intervention(
        self,
        *,
        request: InterventionRequest,
        decision: RecoveryDecision,
    ) -> InterventionOutcome:
        """
        Called synchronously by the paused discovery/replay flow.

        The caller must keep the browser alive, stop browser automation,
        and ensure the decision was based on current session/policy facts.
        This manager cannot stop independently running background workers.
        """
        if not decision.requires_handoff:
            raise ValueError("The recovery decision does not permit handoff.")

        active_statuses = {
            InterventionStatus.REQUESTED,
            InterventionStatus.HUMAN_ACTIVE,
            InterventionStatus.RESUMING,
        }

        if (
            self._state is not None
            and self._state.status in active_statuses
        ):
            raise RuntimeError("An intervention is already active.")

        self._state = HandoffState(
            request=request.model_copy(deep=True),
        )

        try:
            self._record("intervention_requested")

            self._state.status = InterventionStatus.HUMAN_ACTIVE
            self._state.control_owner = ControlOwner.HUMAN
            self._record("human_control_started")

            # The calling automation remains blocked until this returns.
            outcome = self.operator.handle(
                self._state.request.model_copy(deep=True)
            )

            if outcome.intervention_id != request.intervention_id:
                raise ValueError(
                    "Operator response belongs to another intervention."
                )

            self._state.operator_id = outcome.operator_id
            self._state.control_owner = ControlOwner.AUTOMATION

            if outcome.resolution == InterventionResolution.RESOLVED:
                # Control returns for verification, not arbitrary execution.
                self._state.status = InterventionStatus.RESUMING

            elif outcome.resolution == InterventionResolution.TIMED_OUT:
                self._state.status = InterventionStatus.TIMED_OUT

            else:
                # Includes both explicit cancellation and unresolved cases.
                # The evidence retains their distinct resolution values.
                self._state.status = InterventionStatus.CANCELLED

            self._record(
                "human_control_returned",
                outcome=outcome,
            )

            return outcome

        except BaseException:
            # A failed operator interface or evidence write must not leave
            # the manager claiming that an intervention can resume.
            self._state.status = InterventionStatus.CANCELLED
            self._state.control_owner = ControlOwner.AUTOMATION

            try:
                self._record("intervention_aborted")
            except Exception:
                # Preserve the original exception.
                pass

            raise

    def complete_resume(
        self,
        *,
        intervention_id: UUID,
        state_verified: bool,
    ) -> bool:
        """
        Record the caller's verification result.

        This method does not inspect the page or execute browser actions.
        Return True only when the caller has verified safe continuation.
        """
        if self._state is None:
            raise RuntimeError("No intervention exists.")

        if self._state.request.intervention_id != intervention_id:
            raise ValueError("Intervention ID does not match.")

        if self._state.status != InterventionStatus.RESUMING:
            raise RuntimeError(
                "The intervention is not awaiting resume verification."
            )

        self._state.status = (
            InterventionStatus.RESOLVED
            if state_verified
            else InterventionStatus.CANCELLED
        )

        try:
            self._record(
                "resume_verified"
                if state_verified
                else "resume_rejected"
            )
        except BaseException:
            self._state.status = InterventionStatus.CANCELLED
            raise

        return state_verified

    def _record(
        self,
        event: str,
        *,
        outcome: InterventionOutcome | None = None,
    ) -> None:
        if self._state is None:
            raise RuntimeError("Cannot record without an intervention.")

        request = self._state.request

        # Explicit allowlist: no raw reason, goal, page content, inputs,
        # URLs, exception messages, or unrestricted operator comments.
        record = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "event": event,
            "intervention_id": str(request.intervention_id),
            "phase": request.phase.value,
            "current_step": request.current_step,
            "status": self._state.status.value,
            "control_owner": self._state.control_owner.value,
        }

        if outcome is not None:
            record["resolution"] = outcome.resolution.value

            # Persist only a recognized, controlled description.
            if outcome.action_summary in ACTION_SUMMARIES.values():
                record["operator_reported_action"] = outcome.action_summary

        self.evidence_dir.mkdir(
            parents=True,
            exist_ok=True,
            mode=0o700,
        )

        path = self.evidence_dir / f"{request.intervention_id}.jsonl"

        with path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(record) + "\n")