import logging
from urllib.parse import urlparse

from app.agent.discovery.browser import BrowserSession
from app.agent.discovery.executor import ActionExecutor
from app.agent.discovery.output_binding.output_binding_llm import OutputBindingLLM
from app.agent.discovery.output_binding.output_binding_verifier import (
    OutputBindingVerifier,
)
from app.agent.discovery.output_binding.output_grounder import OutputGrounder
from app.agent.discovery.output_binding.output_locator import OutputLocatorBuilder
from app.agent.discovery.runtime import DiscoveryRunState, HandoffCoordinator
from app.agent.handoff.manager import HumanHandoffManager
from app.agent.llm.browser_llm import BrowserLLM
from app.agent.observability.discovery_logger import DiscoveryLogger
from app.agent.policy.engine import PolicyEngine
from app.agent.policy.models import PolicyDecision, PolicyViolation
from app.agent.recording.state_fingerprint import build_state_fingerprint
from app.agent.recording.trajectory_recorder import TrajectoryRecorder
from app.agent.schemas.discovery import ActionType
from app.agent.schemas.recording import (
    DiscoveredOutputLocation,
    DiscoveryResult,
    RecordedState,
    RecordedTransition,
    TableRowMatchBinding,
    VerifiedTableOutputBinding,
)
from app.agent.validation.outcome_validator import OutcomeValidator
from app.agent.validation.validator import ActionValidator, ValidationStatus
from app.agent.validation.value_validator_llm import (
    ValidatorDecision,
    ValueValidatorLLM,
)


logger = logging.getLogger(__name__)


class DiscoveryAgent:
    def __init__(
        self,
        max_steps: int = 20,
        max_failures: int = 5,
        business_validation_policy: str = "",
        *,
        handoff_manager: HumanHandoffManager | None = None,
        handoff_enabled: bool = True,
        max_interventions: int = 2,
        policy_engine: PolicyEngine | None = None,
        policy_profile_id: str = "read_only_discovery",
    ):
        if max_interventions < 0:
            raise ValueError("max_interventions must not be negative.")

        self.max_steps = max_steps
        self.max_failures = max_failures
        self.business_validation_policy = business_validation_policy
        self.handoff_manager = handoff_manager
        self.policy_engine = policy_engine
        self.policy_profile_id = policy_profile_id
        self.handoff_enabled = handoff_enabled
        self.max_interventions = max_interventions

    @staticmethod
    def _origin(url):
        parsed = urlparse(url)
        port = parsed.port
        if port is None:
            port = {"http": 80, "https": 443}.get(parsed.scheme)
        return parsed.scheme, parsed.hostname, port

    def _session_usable(self, browser, target_url):
        try:
            return (
                not browser.page.is_closed()
                and self._origin(browser.page.url) == self._origin(target_url)
            )
        except Exception:
            return False

    def run(self, user_request: str, target_url: str):
        """Run one LLM-driven discovery session and always close the browser."""
        runtime = self._setup_run(target_url)
        runtime["logger"].log(
            "run_started",
            user_request=user_request,
            target_url=target_url,
        )

        try:
            if not self._start_browser(runtime, target_url):
                return None
            return self._step_loop(runtime, user_request, target_url)
        finally:
            runtime["browser"].close()

    def _setup_run(self, target_url: str):
        browser = BrowserSession(headless=False)
        llm = BrowserLLM()
        logger = DiscoveryLogger()
        state = DiscoveryRunState()

        runtime = {
            "browser": browser,
            "llm": llm,
            "validator": ActionValidator(),
            "value_validator_llm": ValueValidatorLLM(
                business_policy=self.business_validation_policy
            ),
            "outcome_validator": OutcomeValidator(),
            "logger": logger,
            "trajectory_recorder": TrajectoryRecorder(),
            "output_grounder": OutputGrounder(),
            "output_locator_builder": OutputLocatorBuilder(),
            "state": state,
            "executor": None,
        }
        runtime["handoff"] = HandoffCoordinator(
            browser=browser,
            logger=logger,
            manager=self.handoff_manager,
            target_url=target_url,
            handoff_enabled=self.handoff_enabled,
            max_interventions=self.max_interventions,
            max_steps=self.max_steps,
            session_usable=self._session_usable,
            policy_scope_check=lambda step, url: self._check_policy_scope(
                runtime, step=step, url=url
            ),
            state=state,
        )
        return runtime

    def _start_browser(self, runtime, target_url: str) -> bool:
        browser = runtime["browser"]
        browser.start()
        if not self._check_policy_scope(runtime, step=0, url=target_url):
            return False

        browser.open(target_url)
        runtime["executor"] = ActionExecutor(
            page=browser.page,
            allowed_host=urlparse(target_url).hostname,
            policy_engine=self.policy_engine,
            policy_profile_id=self.policy_profile_id,
            on_policy_decision=lambda result: runtime["logger"].log(
                "policy_decision",
                step=runtime["state"].current_step,
                check="click_destination",
                decision=result.decision.value,
                code=result.code,
                reason=result.reason,
            ),
        )
        return True

    def _step_loop(self, runtime, user_request: str, target_url: str):
        for step in range(1, self.max_steps + 1):
            runtime["state"].current_step = step
            logger.debug("Discovery step %s", step)
            observation, current_url = self._observe(runtime, step)
            action = self._decide(runtime, user_request, current_url, observation, step)

            if action.action not in {ActionType.FINISH, ActionType.REQUEST_HUMAN}:
                if not self._check_action_policy(
                    runtime, step=step, action=action, current_url=current_url
                ):
                    return None

            decision = self._validate_action(
                runtime,
                action,
                user_request,
                current_url,
                observation,
                step,
            )
            if decision == "stop":
                return None
            if decision == "retry":
                continue

            logger.debug("Action approved.")

            if action.action == ActionType.FINISH:
                result = self._handle_finish(
                    runtime, action, current_url=current_url, step=step
                )
                if result is not None:
                    return result
                if self._failure_limit_reached(runtime, step):
                    return None
                continue

            if action.action == ActionType.REQUEST_HUMAN:
                resumed = runtime["handoff"].request(
                    step=step,
                    reason=(
                        "The discovery agent requested human inspection "
                        "because it could not safely proceed."
                    ),
                )
                if not resumed:
                    return None
                continue

            execution_status = self._execute_action(
                runtime, action, observation, step
            )
            if execution_status == "stop":
                return None
            if execution_status == "retry":
                continue

        logger.warning("Maximum step limit reached.")
        runtime["logger"].log(
            "run_failed",
            reason="maximum_step_limit_reached",
            max_steps=self.max_steps,
        )
        return None

    def _observe(self, runtime, step: int):
        browser = runtime["browser"]
        state = runtime["state"]
        observation = browser.observe()
        current_url = browser.page.url

        if not state.recorder_initialized:
            runtime["trajectory_recorder"].initialize(
                self._recorded_state(current_url, observation)
            )
            state.recorder_initialized = True

        logger.debug("Current URL: %s", current_url)
        runtime["logger"].log(
            "observation",
            step=step,
            url=current_url,
            observation=observation,
        )
        return observation, current_url

    @staticmethod
    def _decide(runtime, user_request, current_url, observation, step):
        action = runtime["llm"].decide(
            user_request=user_request,
            current_url=current_url,
            observation=observation,
        )
        target = action.target_name or action.target_role or action.target_ref or ""
        logger.debug(
            "Decision: %s%s",
            action.action.value.upper(),
            f' "{target}"' if target else "",
        )
        logger.debug(
            "Full LLM decision: %s",
            action.model_dump_json(),
        )
        runtime["logger"].log(
            "llm_action",
            step=step,
            action=action.model_dump(mode="json"),
        )
        return action

    def _validate_action(
        self,
        runtime,
        action,
        user_request,
        current_url,
        observation,
        step,
    ) -> str:
        state = runtime["state"]
        validation = runtime["validator"].validate(
            action=action,
            user_request=user_request,
            current_url=current_url,
            observation=observation,
            previous_actions=state.action_history,
        )

        logger.debug(
            "Validation: %s",
            validation.status.value.upper(),
        )
        logger.debug(
            "Validation reason: %s",
            validation.reason,
        )
        runtime["logger"].log(
            "deterministic_validation",
            step=step,
            status=validation.status.value,
            reason=validation.reason,
        )

        if validation.status == ValidationStatus.REJECTED:
            self._record_rejection(
                runtime,
                step=step,
                source="deterministic_validator",
                reason=validation.reason,
            )
            return "stop" if self._failure_limit_reached(runtime, step) else "retry"

        if validation.status != ValidationStatus.NEEDS_LLM:
            return "approved"

        logger.info(
            "Deterministic validation inconclusive; using Validator LLM."
        )
        llm_validation = runtime["value_validator_llm"].validate(
            user_request=user_request,
            action=action,
            observation=observation,
            deterministic_reason=validation.reason,
        )

        logger.info(
            "Validator LLM: %s",
            llm_validation.decision.value.upper(),
        )
        logger.debug(
            "Validator LLM reason: %s",
            llm_validation.reason,
        )
        runtime["logger"].log(
            "validator_llm",
            step=step,
            decision=llm_validation.decision.value,
            reason=llm_validation.reason,
        )

        if llm_validation.decision == ValidatorDecision.REJECT:
            self._record_rejection(
                runtime,
                step=step,
                source="validator_llm",
                reason=llm_validation.reason,
            )
            return "stop" if self._failure_limit_reached(runtime, step) else "retry"

        if llm_validation.decision == ValidatorDecision.ESCALATE_TO_HUMAN:
            resumed = runtime["handoff"].request(
                step=step,
                reason=(
                    "An action could not be validated safely. "
                    "Inspect the application within the permitted workflow."
                ),
            )
            return "retry" if resumed else "stop"

        return "approved"

    def _record_rejection(self, runtime, *, step: int, source: str, reason: str) -> None:
        state = runtime["state"]
        state.failure_count += 1
        logger.warning(
            "Action rejected (%s/%s).",
            state.failure_count,
            self.max_failures,
        )
        runtime["logger"].log(
            "action_rejected",
            step=step,
            source=source,
            reason=reason,
            failure_count=state.failure_count,
        )

    def _handle_finish(self, runtime, action, *, current_url: str, step: int):
        state = runtime["state"]
        if not action.result:
            state.failure_count += 1
            logger.warning("Finish action rejected: missing result.")
            runtime["logger"].log(
                "finish_rejected",
                step=step,
                reason="finish_action_missing_result",
                failure_count=state.failure_count,
            )
            return None

        browser = runtime["browser"]
        final_observation = browser.observe()
        if not self._check_policy_scope(runtime, step=step, url=current_url):
            return None
        final_url = browser.page.url
        output_locations = self._build_output_locations(runtime, action)
        final_state = self._recorded_state(final_url, final_observation)

        return DiscoveryResult(
            result=action.result,
            finish_reason=action.reason,
            outputs=action.outputs or [],
            output_locations=output_locations,
            execution_trace=(
                runtime["trajectory_recorder"].get_execution_trace()
                + state.assisted_execution_trace
            ),
            candidate_path=(
                []
                if state.human_assisted
                else runtime["trajectory_recorder"].get_candidate_path()
            ),
            final_state=final_state,
            human_assisted=state.human_assisted,
            intervention_count=state.intervention_count,
            evidence_refs=list(state.intervention_evidence),
        )

    @staticmethod
    def _build_output_locations(runtime, action):
        browser = runtime["browser"]
        binding_llm = OutputBindingLLM(
            client=runtime["llm"].client,
            model=runtime["llm"].model,
        )
        binding_verifier = OutputBindingVerifier()
        locations = []

        for output in action.outputs or []:
            location = runtime["output_locator_builder"].locate(
                output=output,
                page=browser.page,
            )
            proposal = binding_llm.propose(context=location)
            verification = binding_verifier.verify(
                context=location,
                proposal=proposal,
                page=browser.page,
            )

            if not verification.valid:
                raise ValueError(
                    f"Output binding verification failed for "
                    f"'{location.output_name}': {verification.reason}"
                )

            binding = proposal.binding
            locations.append(
                DiscoveredOutputLocation(
                    output_name=location.output_name,
                    output_type=location.output_type,
                    observed_value=location.observed_value,
                    binding=VerifiedTableOutputBinding(
                        kind="table",
                        row_match=TableRowMatchBinding(
                            column=binding.row_match.column,
                            value=binding.row_match.value,
                        ),
                        value_column=binding.value_column,
                    ),
                )
            )
        return locations

    def _execute_action(self, runtime, action, observation, step: int) -> str:
        browser = runtime["browser"]
        state = runtime["state"]

        try:
            before_url = browser.page.url
            runtime["executor"].execute(action)
            runtime["logger"].log(
                "action_executed",
                step=step,
                action=action.model_dump(mode="json"),
            )

            after_url = browser.page.url
            if not self._check_policy_scope(runtime, step=step, url=after_url):
                return "stop"
            after_observation = browser.observe()
            outcome = runtime["outcome_validator"].validate(
                action=action,
                before_url=before_url,
                after_url=after_url,
                before_observation=observation,
                after_observation=after_observation,
            )

            logger.debug(
                "Execution: %s",
                "SUCCESS" if outcome.success else "INVALID",
            )
            logger.debug(
                "Outcome reason: %s",
                outcome.reason,
            )
            runtime["logger"].log(
                "outcome_validation",
                step=step,
                success=outcome.success,
                reason=outcome.reason,
                before_url=before_url,
                after_url=after_url,
            )

            if not outcome.success:
                state.failure_count += 1
                logger.warning(
                    "Action produced an invalid outcome (%s/%s).",
                    state.failure_count,
                    self.max_failures,
                )
                runtime["logger"].log(
                    "invalid_outcome",
                    step=step,
                    reason=outcome.reason,
                    failure_count=state.failure_count,
                )
                return (
                    "stop"
                    if self._failure_limit_reached(runtime, step)
                    else "retry"
                )

            state.action_history.append(action)
            transition = RecordedTransition(
                step=step,
                before_state=self._recorded_state(before_url, observation),
                action=action,
                after_state=self._recorded_state(after_url, after_observation),
                outcome_reason=outcome.reason,
            )

            if state.human_assisted:
                state.assisted_execution_trace.append(transition)
            else:
                runtime["trajectory_recorder"].record_transition(transition)

            execution_trace = (
                runtime["trajectory_recorder"].get_execution_trace()
                + state.assisted_execution_trace
            )
            logger.debug(
                "Execution trace: %s",
                [
                    (recorded.step, recorded.action.action.value)
                    for recorded in execution_trace
                ],
            )

            if state.human_assisted:
                logger.info(
                    "Assisted run: no autonomous candidate path will be emitted."
                )
            else:
                candidate_path = runtime["trajectory_recorder"].get_candidate_path()
                logger.debug(
                    "Candidate path: %s",
                    [
                        (recorded.step, recorded.action.action.value)
                        for recorded in candidate_path
                    ],
                )

            return "ok"

        except PolicyViolation as exc:
            runtime["logger"].log(
                "run_failed",
                step=step,
                source="policy",
                decision=exc.result.decision.value,
                error_code=exc.result.code,
                reason=exc.result.reason,
            )
            logger.error(
                "Action blocked by policy: %s",
                exc.result.code,
            )
            return "stop"

        except Exception as exc:
            state.failure_count += 1
            logger.error(
                "Action failed (%s/%s): %s",
                state.failure_count,
                self.max_failures,
                type(exc).__name__,
            )
            logger.debug(
                "Action execution exception.",
                exc_info=True,
            )
            runtime["logger"].log(
                "execution_error",
                step=step,
                error=str(exc),
                action=action.model_dump(mode="json"),
                failure_count=state.failure_count,
            )
            return (
                "stop"
                if self._failure_limit_reached(runtime, step)
                else "retry"
            )

    def _check_policy_scope(self, runtime, *, step: int, url: str) -> bool:
        if self.policy_engine is None:
            return True

        result = self.policy_engine.check_scope(
            current_url=url,
            profile_id=self.policy_profile_id,
        )
        runtime["logger"].log(
            "policy_decision",
            step=step,
            check="browser_scope",
            decision=result.decision.value,
            code=result.code,
            reason=result.reason,
        )
        if result.decision == PolicyDecision.ALLOWED:
            return True

        runtime["logger"].log(
            "run_failed",
            step=step,
            source="policy",
            error_code=result.code,
            reason=result.reason,
        )
        return False

    def _check_action_policy(
        self, runtime, *, step: int, action, current_url: str
    ) -> bool:
        if self.policy_engine is None:
            return True

        result = self.policy_engine.check(
            action=action.action,
            current_url=current_url,
            profile_id=self.policy_profile_id,
            target_role=action.target_role,
            target_name=action.target_name,
            destination_url=action.url,
        )
        runtime["logger"].log(
            "policy_decision",
            step=step,
            check="proposed_action",
            action_type=action.action.value,
            decision=result.decision.value,
            code=result.code,
            reason=result.reason,
        )
        if result.decision == PolicyDecision.ALLOWED:
            return True

        runtime["logger"].log(
            "run_failed",
            step=step,
            source="policy",
            error_code=result.code,
            decision=result.decision.value,
            reason=result.reason,
        )
        return False

    def _failure_limit_reached(self, runtime, step: int) -> bool:
        state = runtime["state"]
        if state.failure_count < self.max_failures:
            return False

        logger.error("Maximum failure threshold reached.")
        runtime["logger"].log(
            "run_failed",
            step=step,
            reason="maximum_failure_threshold_reached",
            failure_count=state.failure_count,
        )
        return True

    @staticmethod
    def _recorded_state(url: str, observation: str) -> RecordedState:
        return RecordedState(
            url=url,
            observation=observation,
            fingerprint=build_state_fingerprint(
                url=url,
                observation=observation,
            ),
        )
