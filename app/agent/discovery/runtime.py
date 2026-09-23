from dataclasses import dataclass, field
from uuid import uuid4

from app.agent.discovery.browser import BrowserSession
from app.agent.handoff.decision import (
    ConditionKind,
    ConditionSource,
    RecoveryDecisionContext,
    decide_recovery,
)
from app.agent.handoff.manager import HumanHandoffManager
from app.agent.handoff.models import ExecutionPhase, InterventionRequest
from app.agent.observability.discovery_logger import DiscoveryLogger
from app.agent.schemas.recording import RecordedTransition


@dataclass
class DiscoveryRunState:
    """Mutable state that belongs to one discovery run, not the agent object."""

    run_id: str = field(default_factory=lambda: str(uuid4()))
    session_id: str = field(default_factory=lambda: str(uuid4()))
    failure_count: int = 0
    human_assisted: bool = False
    intervention_count: int = 0
    recorder_initialized: bool = False
    current_step: int = 0
    action_history: list = field(default_factory=list)
    intervention_evidence: list[str] = field(default_factory=list)
    assisted_execution_trace: list[RecordedTransition] = field(default_factory=list)


class HandoffCoordinator:
    """Own the discovery-specific pause/handoff/resume protocol."""

    def __init__(
        self,
        *,
        browser: BrowserSession,
        logger: DiscoveryLogger,
        manager: HumanHandoffManager | None,
        target_url: str,
        handoff_enabled: bool,
        max_interventions: int,
        max_steps: int,
        session_usable,
        policy_scope_check,
        state: DiscoveryRunState,
    ):
        self.browser = browser
        self.logger = logger
        self.manager = manager
        self.target_url = target_url
        self.handoff_enabled = handoff_enabled
        self.max_interventions = max_interventions
        self.max_steps = max_steps
        self.session_usable = session_usable
        self.policy_scope_check = policy_scope_check
        self.state = state

    def request(self, *, step: int, reason: str) -> bool:
        if (
            self.manager is None
            or self.state.intervention_count >= self.max_interventions
            or step >= self.max_steps
        ):
            self.logger.log(
                "human_handoff_unavailable",
                step=step,
                reason="manager_unavailable_or_execution_budget_exhausted",
            )
            return False

        decision = decide_recovery(
            RecoveryDecisionContext(
                condition_kind=ConditionKind.FAILURE,
                source=ConditionSource.TARGET_APPLICATION,
                live_session_usable=self.session_usable(
                    self.browser,
                    self.target_url,
                ),
                human_intervention_allowed=self.handoff_enabled,
            )
        )

        if not decision.requires_handoff:
            self.logger.log(
                "human_handoff_denied",
                step=step,
                reason="session_or_policy_does_not_permit_handoff",
            )
            return False

        intervention_id = uuid4()
        try:
            screenshot_ref = self.browser.capture_handoff_screenshot(
                evidence_dir=self.manager.evidence_dir,
                intervention_id=intervention_id,
            )
        except Exception:
            self.logger.log(
                "human_handoff_screenshot_failed",
                step=step,
                reason="screenshot_capture_failed",
            )
            return False

        request = InterventionRequest(
            intervention_id=intervention_id,
            run_id=self.state.run_id,
            phase=ExecutionPhase.DISCOVERY,
            reason=reason,
            browser_session_id=self.state.session_id,
            current_step=step,
            screenshot_ref=screenshot_ref,
        )

        # An intervention makes the run assisted even if the operator only
        # inspects the live session. Assisted traces are never promoted into
        # an autonomous reusable candidate path.
        self.state.human_assisted = True
        self.state.intervention_count += 1

        try:
            outcome = self.manager.request_intervention(
                request=request,
                decision=decision,
            )

            journal = (
                self.manager.evidence_dir
                / f"{request.intervention_id}.jsonl"
            )
            self.state.intervention_evidence.append(str(journal))

            if not outcome.may_attempt_resume:
                return False

            resumed = self._verify_and_complete_resume(request)
        except Exception:
            self.logger.log(
                "human_handoff_failed",
                step=step,
                reason="intervention_or_resume_verification_failed",
            )
            return False

        self.logger.log(
            "human_handoff_completed",
            step=step,
            resumed=resumed,
            intervention_id=str(request.intervention_id),
        )
        return resumed

    def _verify_and_complete_resume(self, request: InterventionRequest) -> bool:
        verified = False

        try:
            if (
                self.session_usable(self.browser, self.target_url)
                and self.policy_scope_check(
                    self.state.current_step,
                    self.browser.page.url,
                )
            ):
                fresh_observation = self.browser.observe()
                verified = (
                    isinstance(fresh_observation, str)
                    and bool(fresh_observation.strip())
                    and self.session_usable(self.browser, self.target_url)
                )
        except Exception:
            verified = False

        return self.manager.complete_resume(
            intervention_id=request.intervention_id,
            state_verified=verified,
        )
