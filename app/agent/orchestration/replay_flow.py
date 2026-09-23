"""Replay orchestration, including synchronous human handoff."""

import logging
import os
from urllib.parse import urlparse
from uuid import uuid4

from app.agent.console import field, section, success
from app.agent.discovery.browser import BrowserSession
from app.agent.handoff.decision import (
    ConditionKind,
    ConditionSource,
    RecoveryDecisionContext,
    decide_recovery,
)
from app.agent.handoff.manager import HumanHandoffManager
from app.agent.handoff.models import (
    ExecutionPhase,
    InterventionRequest,
)
from app.agent.handoff.operator import TerminalOperator
from app.agent.policy.engine import PolicyEngine
from app.agent.replay.models import (
    ReplayRecoveryAction,
    ReplayStatus,
)
from app.agent.replay.replay_engine import ReplayEngine


logger = logging.getLogger(__name__)


class ReplayFlow:
    def __init__(
        self,
        *,
        target_url: str,
        handoff_manager=None,
        handoff_enabled: bool = True,
        checkpoint_resume_capability_ids: frozenset[str] = frozenset(),
        max_interventions: int = 2,
        policy_engine: PolicyEngine | None = None,
    ):
        self.target_url = target_url
        self.handoff_enabled = handoff_enabled
        self.policy_engine = policy_engine
        self.checkpoint_resume_capability_ids = frozenset(
            checkpoint_resume_capability_ids
        )

        self.max_interventions = max_interventions

        self.handoff_manager = (
            handoff_manager
            if handoff_manager is not None
            else HumanHandoffManager(
                operator=TerminalOperator(
                    operator_id="local-operator"
                )
            )
        )

    @staticmethod
    def _origin(url):
        parsed = urlparse(url)
        port = parsed.port

        if port is None:
            port = {
                "http": 80,
                "https": 443,
            }.get(parsed.scheme)

        return parsed.scheme, parsed.hostname, port

    def _session_usable(self, page):
        try:
            return (
                not page.is_closed()
                and self._origin(page.url)
                == self._origin(self.target_url)
            )

        except Exception:
            return False

    def _install_handoff_demo(self, engine):
        """
        Add one temporary checkpoint condition to the runtime artifact.

        Enabled only through HANDOFF_DEMO=1, against the local test app.
        The saved capability artifact is not modified.
        """
        hostname = urlparse(self.target_url).hostname

        if hostname not in {"localhost", "127.0.0.1", "::1"}:
            raise ValueError(
                "The handoff demo is restricted to the local test application."
            )

        if not self.handoff_enabled or self.max_interventions < 1:
            raise ValueError(
                "The handoff demo requires human intervention to be enabled "
                "with at least one intervention allowed."
            )

        if not engine.checkpoint_resume_allowed:
            raise ValueError(
                "Enable checkpoint resume for this reviewed read-only "
                "capability before running the demo."
            )

        original_wait = (
            engine.checkpoint_validator.wait_and_validate
        )

        panel_id = f"handoff-demo-{uuid4().hex}"
        marker = f"Demo intervention resolved {uuid4().hex}"
        injected = False

        def wait_with_demo(
            checkpoint,
            page,
            inputs,
            timeout_ms=5000,
        ):
            nonlocal injected

            # Verify the real application checkpoint before introducing
            # the artificial demonstration condition.
            result = original_wait(
                checkpoint=checkpoint,
                page=page,
                inputs=inputs,
                timeout_ms=timeout_ms,
            )

            if (
                injected
                or not result[0]
                or not checkpoint.url_pattern
            ):
                return result

            if not self._session_usable(page):
                raise RuntimeError(
                    "The demo requires the original local application session."
                )

            page.evaluate(
                """
                ({panelId, marker}) => {
                    const panel = document.createElement("section");
                    panel.id = panelId;

                    Object.assign(panel.style, {
                        position: "fixed",
                        bottom: "20px",
                        right: "20px",
                        zIndex: "2147483647",
                        background: "white",
                        color: "#111",
                        border: "3px solid #2563eb",
                        borderRadius: "10px",
                        padding: "20px",
                        width: "320px",
                        fontFamily: "sans-serif",
                        boxShadow: "0 4px 20px #0004"
                    });

                    const title = document.createElement("h3");
                    title.textContent = "Human handoff demonstration";

                    const explanation = document.createElement("p");
                    explanation.textContent =
                        "Wait for the terminal handoff prompt, then " +
                        "resolve this demonstration checkpoint.";

                    const button = document.createElement("button");
                    button.type = "button";
                    button.textContent = "Resolve demo checkpoint";
                    button.disabled = true;
                    button.style.padding = "10px";

                    const status = document.createElement("p");

                    button.addEventListener("click", () => {
                        status.textContent = marker;
                        button.disabled = true;
                    });

                    panel.append(title, explanation, button, status);
                    document.body.append(panel);
                }
                """,
                {
                    "panelId": panel_id,
                    "marker": marker,
                },
            )

            # ReplayEngine uses a deep copy of the artifact.
            # Only that runtime copy receives this additional condition.
            checkpoint.required_text = [
                *checkpoint.required_text,
                marker,
            ]

            injected = True

            logger.info(
                "Demo checkpoint condition added; waiting for human intervention."
            )

            # The marker is absent until the human clicks the demo button.
            return original_wait(
                checkpoint=checkpoint,
                page=page,
                inputs=inputs,
                timeout_ms=timeout_ms,
            )

        engine.checkpoint_validator.wait_and_validate = wait_with_demo

        def activate_demo():
            if injected:
                engine.page.evaluate(
                    """
                    panelId => {
                        const panel = document.getElementById(panelId);
                        const button = panel?.querySelector("button");

                        if (button) {
                            button.disabled = false;
                        }
                    }
                    """,
                    panel_id,
                )

        return activate_demo

    def __call__(
        self,
        *,
        artifact,
        business_outcome_rules,
        inputs,
    ):
        section("REPLAY")
        field("Capability", artifact.capability_id)
        field(
            "Inputs",
            ", ".join(sorted(inputs)) if inputs else "None",
        )
        logger.debug("Starting deterministic replay.")

        browser = BrowserSession(headless=False)
        run_id = str(uuid4())
        session_id = str(uuid4())

        try:
            browser.start()
            browser.open(self.target_url)

            # Replaced with the demo activation callback only when enabled.
            activate_demo = lambda: None

            def handle_intervention(result, verify_resume):
                # Engine calls this only for recognized application-level
                # execution conditions, not artifact or programming errors.
                decision = decide_recovery(
                    RecoveryDecisionContext(
                        condition_kind=ConditionKind.FAILURE,
                        source=ConditionSource.TARGET_APPLICATION,
                        live_session_usable=self._session_usable(
                            browser.page
                        ),
                        human_intervention_allowed=self.handoff_enabled,
                    )
                )

                if not decision.requires_handoff:
                    return False

                if verify_resume is None:
                    logger.info(
                        "Inspection-only handoff: this run will stop after "
                        "intervention; automatic continuation is unavailable."
                    )
                # Show the handoff demo condition, when the demo is active.
                activate_demo()

                intervention_id = uuid4()

                try:
                    screenshot_ref = browser.capture_handoff_screenshot(
                        evidence_dir=self.handoff_manager.evidence_dir,
                        intervention_id=intervention_id,
                    )

                except Exception:
                    logger.error(
                        "Handoff screenshot capture failed; "
                        "the intervention cannot proceed."
                    )
                    return False
                
                request = InterventionRequest(
                    intervention_id=intervention_id,
                    run_id=run_id,
                    phase=ExecutionPhase.REPLAY,
                    reason=result.reason,
                    browser_session_id=session_id,
                    current_step=result.failed_step,
                    capability_id=artifact.capability_id,
                    evidence_refs=list(result.evidence_refs),
                    screenshot_ref=screenshot_ref,
                )

                # Enable the demo button only when automation is handing
                # control to the operator.
                activate_demo()

                outcome = self.handoff_manager.request_intervention(
                    request=request,
                    decision=decision,
                )

                journal = (
                    self.handoff_manager.evidence_dir
                    / f"{request.intervention_id}.jsonl"
                )

                result.evidence_refs.append(str(journal))
                result.evidence_refs.append(screenshot_ref)

                if not outcome.may_attempt_resume:
                    return False

                # "Finished" is only an operator declaration.
                verified = False

                try:
                    if (
                        verify_resume is not None
                        and self._session_usable(browser.page)
                    ):
                        verified = bool(verify_resume())

                        verified = (
                            verified
                            and self._session_usable(browser.page)
                        )

                except Exception:
                    verified = False

                return self.handoff_manager.complete_resume(
                    intervention_id=request.intervention_id,
                    state_verified=verified,
                )

            engine = ReplayEngine(
                page=browser.page,
                business_outcome_rules=business_outcome_rules,
                on_intervention=handle_intervention,
                checkpoint_resume_allowed=(
                    artifact.capability_id
                    in self.checkpoint_resume_capability_ids
                ),
                max_interventions=self.max_interventions,
                policy_engine=self.policy_engine,
                policy_profile_id=artifact.capability_id,
            )

            if os.getenv("HANDOFF_DEMO") == "1":
                activate_demo = self._install_handoff_demo(engine)

            replay_inputs = dict(inputs)

            result = engine.replay(
                artifact,
                replay_inputs,
            )

            # Restart only this preflight case: no actions have run.
            if (
                result.status == ReplayStatus.RECOVERABLE_FAILURE
                and result.recovery_action
                == ReplayRecoveryAction.REQUEST_INPUT
                and result.completed_steps == 0
            ):
                for parameter in artifact.inputs:
                    if (
                        parameter.required
                        and not replay_inputs.get(
                            parameter.name, ""
                        ).strip()
                    ):
                        value = input(
                            f"Enter {parameter.name}: "
                        ).strip()

                        if value:
                            replay_inputs[parameter.name] = value

                if all(
                    replay_inputs.get(parameter.name, "").strip()
                    for parameter in artifact.inputs
                    if parameter.required
                ):
                    result = engine.replay(
                        artifact,
                        replay_inputs,
                    )

                else:
                    logger.warning("Required replay inputs are still missing.")

            if result.status == ReplayStatus.SUCCESS:
                success("Deterministic replay completed")

            field("Status", result.status.value)
            field("Completed", f"{result.completed_steps} steps")
            field(
                "Human assisted",
                "Yes" if result.human_assisted else "No",
            )

            if result.outputs:
                print()
                for name, value in result.outputs.items():
                    field("Result", f"{name} = {value}")
            elif result.status != ReplayStatus.SUCCESS:
                field("Reason", result.reason)
            if result.error_code:
                logger.warning(
                    "Replay error: %s | %s",
                    result.error_code,
                    result.reason,
                )
            if result.outputs:
                logger.debug(
                    "Replay outputs returned: %s",
                    sorted(result.outputs),
                )
            logger.debug(
                "Full replay result: %s",
                result.model_dump_json(),
            )

            return result

        finally:
            # Handoff happens inside engine.replay(), before reaching here.
            browser.close()