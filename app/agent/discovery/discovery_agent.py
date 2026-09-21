from urllib.parse import urlparse

from app.agent.discovery.browser import BrowserSession
from app.agent.discovery.executor import ActionExecutor
from app.agent.schemas.discovery import ActionType

from app.agent.llm.browser_llm import BrowserLLM
from app.agent.validation.value_validator_llm import ValueValidatorLLM, ValidatorDecision
from app.agent.validation.validator import ActionValidator, ValidationStatus
from app.agent.validation.outcome_validator import OutcomeValidator
from app.agent.discovery.output_binding.output_grounder import OutputGrounder
from app.agent.discovery.output_binding.output_locator import OutputLocatorBuilder
from app.agent.discovery.output_binding.output_binding_llm import (
    OutputBindingLLM,
)
from app.agent.discovery.output_binding.output_binding_verifier import (
    OutputBindingVerifier,
)
from app.agent.observability.discovery_logger import DiscoveryLogger
from app.agent.schemas.recording import (
    DiscoveryResult,
    DiscoveredOutputLocation,
    RecordedState,
    RecordedTransition,
    VerifiedTableOutputBinding,
    TableRowMatchBinding,
)
from app.agent.recording.state_fingerprint import build_state_fingerprint
from app.agent.recording.trajectory_recorder import TrajectoryRecorder

class DiscoveryAgent:
    def __init__(
        self,
        max_steps: int = 20,
        max_failures: int = 5,
        business_validation_policy: str = "",
    ):
        self.max_steps = max_steps
        self.max_failures = max_failures
        self.business_validation_policy = business_validation_policy

    def run(self, user_request: str, target_url: str):
        # -------------------------
        # COMPONENTS
        # -------------------------

        browser = BrowserSession(headless=False)

        # Main LLM that decides what browser action to take.
        llm = BrowserLLM()

        # Deterministic pre-action validator.
        validator = ActionValidator()

        # LLM fallback used only when deterministic
        # value validation cannot make a decision.
        value_validator_llm = ValueValidatorLLM(
            business_policy=self.business_validation_policy
        )

        # Deterministic post-action validator.
        outcome_validator = OutcomeValidator()

        # Structured evidence logger.
        logger = DiscoveryLogger()

        # Records the complete successful execution trace
        # and maintains the stack-cleaned candidate path.
        trajectory_recorder = TrajectoryRecorder()
        # Grounds discovered outputs against the final
        # browser state and collects reusable structural evidence.
        output_grounder = OutputGrounder()
        output_locator_builder = OutputLocatorBuilder()

        failure_count = 0

        # Stores successfully executed actions.
        # Also allows the validator to detect repeated actions.
        action_history = []

        # The recorder is initialized after the first browser
        # observation becomes available.
        recorder_initialized = False

        # Record the beginning of the discovery run.
        logger.log(
            "run_started",
            user_request=user_request,
            target_url=target_url,
        )

        try:
            # -------------------------
            # START BROWSER
            # -------------------------

            browser.start()
            browser.open(target_url)

            allowed_host = urlparse(target_url).hostname
            executor = ActionExecutor(page=browser.page, allowed_host=allowed_host)

            # -------------------------
            # DISCOVERY LOOP
            # -------------------------

            for step in range(1, self.max_steps + 1):
                print(f"\n========== STEP {step} ==========")

                # -------------------------
                # OBSERVE CURRENT PAGE
                # -------------------------

                observation = browser.observe()
                current_url = browser.page.url
                # Initialize trajectory recording from the first observed state.
                if not recorder_initialized:
                    initial_state = RecordedState(
                        url=current_url,
                        observation=observation,
                        fingerprint=build_state_fingerprint(
                            url=current_url,
                            observation=observation,
                        ),
                    )

                    trajectory_recorder.initialize(initial_state)
                    recorder_initialized = True

                
                print("\nCurrent URL:")
                print(current_url)

                # Save the page observation as evidence.
                logger.log(
                    "observation",
                    step=step,
                    url=current_url,
                    observation=observation,
                )

                # -------------------------
                # ASK MAIN LLM
                # -------------------------

                action = llm.decide(
                    user_request=user_request,
                    current_url=current_url,
                    observation=observation,
                )

                print("\nLLM decision:")
                print(action.model_dump_json(indent=2))

                # Save the LLM's proposed action.
                logger.log(
                    "llm_action",
                    step=step,
                    action=action.model_dump(mode="json"),
                )

                # -------------------------
                # PRE-ACTION VALIDATION
                # -------------------------

                validation = validator.validate(
                    action=action,
                    user_request=user_request,
                    current_url=current_url,
                    observation=observation,
                    previous_actions=action_history,
                )

                print("\nDeterministic validation:")
                print(validation.status.value)
                print(validation.reason)

                # Save deterministic validation result.
                logger.log(
                    "deterministic_validation",
                    step=step,
                    status=validation.status.value,
                    reason=validation.reason,
                )

                # -------------------------
                # DETERMINISTIC REJECTION
                # -------------------------

                if validation.status == ValidationStatus.REJECTED:
                    failure_count += 1

                    print(f"\nAction rejected ({failure_count}/{self.max_failures})")

                    logger.log(
                        "action_rejected",
                        step=step,
                        source="deterministic_validator",
                        reason=validation.reason,
                        failure_count=failure_count,
                    )

                    if failure_count >= self.max_failures:
                        print("\nMaximum failure threshold reached.")

                        logger.log(
                            "run_failed",
                            step=step,
                            reason="maximum_failure_threshold_reached",
                            failure_count=failure_count,
                        )

                        return None

                    continue

                # -------------------------
                # VALIDATOR LLM FALLBACK
                # -------------------------

                if validation.status == ValidationStatus.NEEDS_LLM:
                    print("\nDeterministic validation was inconclusive.")
                    print("Sending action to Validator LLM...")

                    llm_validation = value_validator_llm.validate(
                        user_request=user_request,
                        action=action,
                        observation=observation,
                        deterministic_reason=validation.reason,
                    )

                    print("\nValidator LLM decision:")
                    print(llm_validation.decision.value)
                    print(llm_validation.reason)

                    # Save Validator LLM decision.
                    logger.log(
                        "validator_llm",
                        step=step,
                        decision=llm_validation.decision.value,
                        reason=llm_validation.reason,
                    )

                    # Validator LLM rejected the action.
                    if llm_validation.decision == ValidatorDecision.REJECT:
                        failure_count += 1

                        print(
                            f"\nValidator LLM rejected action "
                            f"({failure_count}/{self.max_failures})"
                        )

                        logger.log(
                            "action_rejected",
                            step=step,
                            source="validator_llm",
                            reason=llm_validation.reason,
                            failure_count=failure_count,
                        )

                        if failure_count >= self.max_failures:
                            print("\nMaximum failure threshold reached.")

                            logger.log(
                                "run_failed",
                                step=step,
                                reason="maximum_failure_threshold_reached",
                                failure_count=failure_count,
                            )

                            return None

                        continue

                    # Validator LLM could not safely decide.
                    if llm_validation.decision == ValidatorDecision.ESCALATE_TO_HUMAN:
                        print("\nHuman assistance required:")
                        print(llm_validation.reason)

                        logger.log(
                            "human_handoff_requested",
                            step=step,
                            source="validator_llm",
                            reason=llm_validation.reason,
                        )

                        return None

                    # If APPROVE, execution continues below.

                print("\nAction approved.")

                # -------------------------
                # FINISH
                # -------------------------

                if action.action == ActionType.FINISH:
                    if not action.result:
                        failure_count += 1

                        print(
                            "\nRejected: finish action did not contain a result."
                        )

                        logger.log(
                            "finish_rejected",
                            step=step,
                            reason="finish_action_missing_result",
                            failure_count=failure_count,
                        )

                        if failure_count >= self.max_failures:
                            print("\nMaximum failure threshold reached.")

                            logger.log(
                                "run_failed",
                                step=step,
                                reason="maximum_failure_threshold_reached",
                                failure_count=failure_count,
                            )

                            return None

                        continue

                    final_observation = browser.observe()
                    final_url = browser.page.url

                    output_locations = []

                    binding_llm = OutputBindingLLM(
                        client=llm.client,
                        model=llm.model,
                    )
                    binding_verifier = OutputBindingVerifier()

                    for output in action.outputs or []:
                        print("\n========== OUTPUT DOM LOCATION ==========")

                        location = output_locator_builder.locate(
                            output=output,
                            page=browser.page,
                        )

                        print(
                            "\n========== OUTPUT STRUCTURAL CONTEXT =========="
                        )
                        print(f"Output: {location.output_name}")
                        print(f"Type: {location.output_type}")
                        print(f"Observed value: {location.observed_value}")
                        print(f"Structure: {location.structure}")
                        print(f"Tag: {location.tag_name}")
                        print(f"Selector: {location.selector}")
                        print(f"Headers: {location.headers}")
                        print(f"Containing row: {location.containing_row}")
                        print(f"Output column: {location.output_column}")

                        binding_proposal = binding_llm.propose(
                            context=location,
                        )

                        print(
                            "\n========== OUTPUT BINDING PROPOSAL =========="
                        )
                        print(binding_proposal.model_dump_json(indent=2))

                        binding_verification = binding_verifier.verify(
                            context=location,
                            proposal=binding_proposal,
                            page=browser.page,
                        )

                        print(
                            "\n========== OUTPUT BINDING VERIFICATION =========="
                        )
                        print(f"Valid: {binding_verification.valid}")
                        print(f"Reason: {binding_verification.reason}")
                        print(
                            f"Resolved value: "
                            f"{binding_verification.resolved_value}"
                        )

                        if not binding_verification.valid:
                            raise ValueError(
                                f"Output binding verification failed for "
                                f"'{location.output_name}': "
                                f"{binding_verification.reason}"
                            )

                        binding = binding_proposal.binding

                        output_locations.append(
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

                    # All output bindings have now been processed.
                    final_state = RecordedState(
                        url=final_url,
                        observation=final_observation,
                        fingerprint=build_state_fingerprint(
                            url=final_url,
                            observation=final_observation,
                        ),
                    )

                    discovery_result = DiscoveryResult(
                        result=action.result,
                        finish_reason=action.reason,
                        outputs=action.outputs or [],
                        output_locations=output_locations,
                        execution_trace=(
                            trajectory_recorder.get_execution_trace()
                        ),
                        candidate_path=(
                            trajectory_recorder.get_candidate_path()
                        ),
                        final_state=final_state,
                    )

                    logger.log(
                        "run_finished",
                        step=step,
                        result=action.result,
                        execution_trace_length=len(
                            discovery_result.execution_trace
                        ),
                        candidate_path_length=len(
                            discovery_result.candidate_path
                        ),
                        final_url=final_state.url,
                    )

                    return discovery_result
                
                # -------------------------
                # HUMAN HANDOFF
                # -------------------------

                if action.action == ActionType.REQUEST_HUMAN:
                    print("\nHuman assistance requested:")
                    print(action.reason)

                    logger.log(
                        "human_handoff_requested",
                        step=step,
                        source="browser_llm",
                        reason=action.reason,
                    )

                    return None

                # -------------------------
                # EXECUTE ACTION
                # -------------------------

                try:
                    # Capture browser state before execution.
                    before_url = browser.page.url
                    before_observation = observation

                    # Execute the approved browser action.
                    executor.execute(action)

                    # Record successful Playwright execution.
                    logger.log(
                        "action_executed",
                        step=step,
                        action=action.model_dump(mode="json"),
                    )

                    # Capture browser state after execution.
                    after_url = browser.page.url
                    after_observation = browser.observe()

                    # -------------------------
                    # POST-ACTION VALIDATION
                    # -------------------------

                    outcome = outcome_validator.validate(
                        action=action,
                        before_url=before_url,
                        after_url=after_url,
                        before_observation=before_observation,
                        after_observation=after_observation,
                    )

                    print("\nPost-action validation:")
                    print(outcome.success)
                    print(outcome.reason)

                    # Save post-action validation evidence.
                    logger.log(
                        "outcome_validation",
                        step=step,
                        success=outcome.success,
                        reason=outcome.reason,
                        before_url=before_url,
                        after_url=after_url,
                    )

                    if not outcome.success:
                        failure_count += 1

                        print(
                            f"\nAction produced an invalid outcome "
                            f"({failure_count}/{self.max_failures})"
                        )

                        logger.log(
                            "invalid_outcome",
                            step=step,
                            reason=outcome.reason,
                            failure_count=failure_count,
                        )

                        if failure_count >= self.max_failures:
                            print("\nMaximum failure threshold reached.")

                            logger.log(
                                "run_failed",
                                step=step,
                                reason="maximum_failure_threshold_reached",
                                failure_count=failure_count,
                            )

                            return None

                        continue

                    # Only store an action after:
                    #
                    # 1. pre-action validation passed
                    # 2. execution succeeded
                    # 3. post-action validation passed
                    action_history.append(action)
                    # Build the recorded browser states for this transition.
                    before_state = RecordedState(
                        url=before_url,
                        observation=before_observation,
                        fingerprint=build_state_fingerprint(
                            url=before_url,
                            observation=before_observation,
                        ),
                    )

                    after_state = RecordedState(
                        url=after_url,
                        observation=after_observation,
                        fingerprint=build_state_fingerprint(
                            url=after_url,
                            observation=after_observation,
                        ),
                    )

                    # Record the successful transition.
                    transition = RecordedTransition(
                        step=step,
                        before_state=before_state,
                        action=action,
                        after_state=after_state,
                        outcome_reason=outcome.reason,
                    )

                    trajectory_recorder.record_transition(transition)
                    print("\nRecorded execution trace:")
                    for recorded in trajectory_recorder.get_execution_trace():
                        print(
                            f"Step {recorded.step}: "
                            f"{recorded.action.action.value}"
                        )

                    print("\nCurrent candidate path:")
                    for recorded in trajectory_recorder.get_candidate_path():
                        print(
                            f"Step {recorded.step}: "
                            f"{recorded.action.action.value}"
                        )

                # -------------------------
                # EXECUTION FAILURE
                # -------------------------

                except Exception as exc:
                    failure_count += 1

                    print(f"\nAction failed ({failure_count}/{self.max_failures}):")
                    print(exc)

                    # Save execution failure evidence.
                    logger.log(
                        "execution_error",
                        step=step,
                        error=str(exc),
                        action=action.model_dump(mode="json"),
                        failure_count=failure_count,
                    )

                    if failure_count >= self.max_failures:
                        print("\nMaximum failure threshold reached.")

                        logger.log(
                            "run_failed",
                            step=step,
                            reason="maximum_failure_threshold_reached",
                            failure_count=failure_count,
                        )

                        return None

            # -------------------------
            # STEP LIMIT
            # -------------------------

            print("\nMaximum step limit reached.")

            logger.log(
                "run_failed",
                reason="maximum_step_limit_reached",
                max_steps=self.max_steps,
            )

            return None

        finally:
            browser.close()