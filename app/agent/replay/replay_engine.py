from typing import Callable

from app.agent.schemas.capability import CapabilityArtifact
from app.agent.schemas.outcomes import BusinessOutcomeRule
from app.agent.replay.business_outcomes import BusinessOutcomeDetector
from app.agent.replay.checkpoint_validator import CheckpointValidator
from app.agent.replay.evidence import ReplayEvidenceRecorder
from app.agent.replay.executor import ReplayActionExecutor
from app.agent.replay.models import (
    ReplayActionStatus,
    ReplayFailureCategory,
    ReplayRecoveryAction,
    ReplayResult,
    ReplayStatus,
)
from app.agent.replay.parameter_resolver import (
    ParameterResolutionError,
    ParameterResolver,
)
from app.agent.policy.engine import PolicyEngine
from app.agent.policy.models import PolicyDecision


class ReplayEngine:
    def __init__(
        self,
        page,
        business_outcome_rules: tuple[BusinessOutcomeRule, ...] = (),
        *,
        on_intervention: Callable[
            [ReplayResult, Callable[[], bool] | None], bool
        ] | None = None,
        checkpoint_resume_allowed: bool = False,
        max_interventions: int = 2,
        policy_engine: PolicyEngine | None = None,
        policy_profile_id: str | None = None,
    ):
        if max_interventions < 0:
            raise ValueError("max_interventions must not be negative.")

        self.page = page
        self.resolver = ParameterResolver()
        self.executor = ReplayActionExecutor(page)
        self.checkpoint_validator = CheckpointValidator()
        self.evidence_recorder = ReplayEvidenceRecorder()
        self.business_outcome_detector = BusinessOutcomeDetector()
        self.business_outcome_rules = business_outcome_rules

        self.on_intervention = on_intervention
        self.checkpoint_resume_allowed = checkpoint_resume_allowed
        self.max_interventions = max_interventions

        self._intervention_count = 0
        self._human_assisted = False
        self._intervention_evidence: list[str] = []
        self.policy_engine = policy_engine
        self.policy_profile_id = policy_profile_id

    def _record_failure(self, result, phase):
        try:
            refs = self.evidence_recorder.record(
                result=result,
                page=None if phase == "preflight" else self.page,
                phase=phase,
            )

            # Preserve evidence collected before or during handoff.
            result.evidence_refs = list(
                dict.fromkeys([*result.evidence_refs, *refs])
            )

        except Exception:
            print("[REPLAY] Evidence could not be saved.")

        return result

    def replay(
        self,
        artifact: CapabilityArtifact,
        inputs: dict[str, str],
    ) -> ReplayResult:
        self._intervention_count = 0
        self._human_assisted = False
        self._intervention_evidence = []

        result = self._run(
            artifact.model_copy(deep=True),
            dict(inputs),
        )

        result.intervention_count = self._intervention_count
        result.human_assisted = self._human_assisted
        result.evidence_refs = list(
            dict.fromkeys([
                *self._intervention_evidence,
                *result.evidence_refs,
            ])
        )

        return result

    def _business_outcome(self, step, inputs, completed_steps):
        try:
            outcome = self.business_outcome_detector.detect(
                page=self.page,
                step=step,
                inputs=inputs,
                rules=self.business_outcome_rules,
            )

        except Exception:
            return self._record_failure(
                ReplayResult(
                    status=ReplayStatus.HARD_FAILURE,
                    failure_category=ReplayFailureCategory.EXECUTION,
                    reason="Business-outcome evaluation raised an error.",
                    error_code="business_outcome_detection_error",
                    completed_steps=completed_steps,
                    failed_step=step,
                ),
                phase="business_outcome",
            )

        if outcome is None:
            return None

        return ReplayResult(
            status=ReplayStatus.BUSINESS_OUTCOME,
            reason=outcome.reason,
            error_code=outcome.code,
            # Count only the previously verified action prefix.
            completed_steps=completed_steps,
        )

    def _offer_handoff(self, failure, verify_resume=None):
        # None means the checked continuation was accepted.
        # A ReplayResult means execution must stop.
        if self.on_intervention is None:
            return failure

        if self._intervention_count >= self.max_interventions:
            return self._record_failure(
                failure.model_copy(
                    update={
                        "reason": "The intervention limit was reached.",
                        "error_code": "intervention_limit_reached",
                    }
                ),
                phase="handoff",
            )

        self._intervention_count += 1

        suspended = failure.model_copy(deep=True)
        suspended.status = ReplayStatus.NEEDS_INTERVENTION
        suspended.recovery_action = ReplayRecoveryAction.HUMAN_HANDOFF
        suspended.intervention_count = self._intervention_count
        suspended.human_assisted = self._human_assisted

        try:
            resumed = self.on_intervention(
                suspended,
                verify_resume,
            )

        except Exception:
            resumed = False
            suspended.error_code = "handoff_error"
            suspended.reason = (
                "The human-intervention mechanism failed."
            )

        else:
            suspended.reason = (
                "Replay stopped because safe continuation was not verified."
            )

        self._intervention_evidence.extend(
            suspended.evidence_refs
        )

        if resumed and verify_resume is not None:
            self._human_assisted = True
            return None

        suspended.status = ReplayStatus.HARD_FAILURE
        suspended.recovery_action = None

        return self._record_failure(
            suspended,
            phase="handoff",
        )

    def _resume_verifier(self, checkpoints, inputs):
        if not self.checkpoint_resume_allowed:
            return None

        # Require route AND visible-text evidence for this initial
        # read-only continuation path.
        if not any(cp.url_pattern for cp in checkpoints):
            return None

        if not any(cp.required_text for cp in checkpoints):
            return None

        def verify():
            if self.page.is_closed():
                return False

            return all(
                self.checkpoint_validator.validate(
                    checkpoint=checkpoint,
                    current_url=self.page.url,
                    inputs=inputs,
                    page=self.page,
                )[0]
                for checkpoint in checkpoints
            )

        return verify
    def _policy_failure(
        self,
        *,
        result,
        completed_steps: int,
        failed_step: int | None,
        action_may_have_executed: bool = False,
    ):
        if result.decision == PolicyDecision.NEEDS_CONFIRMATION:
            error_code = "policy_confirmation_required"
        else:
            error_code = "policy_blocked"

        return self._record_failure(
            ReplayResult(
                status=ReplayStatus.HARD_FAILURE,
                failure_category=ReplayFailureCategory.POLICY,
                reason="Replay stopped by the current execution policy.",
                error_code=error_code,
                completed_steps=completed_steps,
                failed_step=failed_step,
                action_may_have_executed=action_may_have_executed,
            ),
            phase="policy",
        )


    def _check_policy_scope(
        self,
        *,
        completed_steps: int,
        failed_step: int | None,
        action_may_have_executed: bool = False,
    ):
        if self.policy_engine is None:
            return None

        result = self.policy_engine.check_scope(
            current_url=self.page.url,
            profile_id=self.policy_profile_id,
        )

        if result.decision == PolicyDecision.ALLOWED:
            return None

        return self._policy_failure(
            result=result,
            completed_steps=completed_steps,
            failed_step=failed_step,
            action_may_have_executed=action_may_have_executed,
        )


    def _check_action_policy(
        self,
        *,
        action,
        completed_steps: int,
        failed_step: int,
    ):
        if self.policy_engine is None:
            return None

        target_role = None
        target_name = None

        if action.target is not None:
            target_role = action.target.role
            target_name = action.target.name

        result = self.policy_engine.check(
            action=action.action,
            current_url=self.page.url,
            profile_id=self.policy_profile_id,
            target_role=target_role,
            target_name=target_name,
            destination_url=action.url,
        )

        if result.decision == PolicyDecision.ALLOWED:
            return None

        return self._policy_failure(
            result=result,
            completed_steps=completed_steps,
            failed_step=failed_step,
            action_may_have_executed=False,
        )

    def _run(self, artifact, inputs):
        completed_steps = 0
        outputs: dict[str, str] = {}

        missing_inputs = [
            parameter.name
            for parameter in artifact.inputs
            if parameter.required
            and not inputs.get(parameter.name, "").strip()
        ]

        if missing_inputs:
            return ReplayResult(
                status=ReplayStatus.RECOVERABLE_FAILURE,
                failure_category=ReplayFailureCategory.INPUT,
                reason="Required replay inputs are missing.",
                error_code="missing_required_inputs",
                recovery_action=ReplayRecoveryAction.REQUEST_INPUT,
            )

        checkpoints_by_action = {}

        for checkpoint in artifact.checkpoints:
            if not 1 <= checkpoint.after_action <= len(artifact.actions):
                return self._record_failure(
                    ReplayResult(
                        status=ReplayStatus.HARD_FAILURE,
                        failure_category=ReplayFailureCategory.ARTIFACT,
                        reason=(
                            "A checkpoint references an invalid action index."
                        ),
                        error_code="invalid_checkpoint_reference",
                    ),
                    phase="preflight",
                )

            checkpoints_by_action.setdefault(
                checkpoint.after_action, []
            ).append(checkpoint)

        initial_policy_failure = self._check_policy_scope(
            completed_steps=completed_steps,
            failed_step=None,
        )

        if initial_policy_failure is not None:
            return initial_policy_failure
        
        for step, action in enumerate(artifact.actions, start=1):
            print(f"[REPLAY] Step {step}: {action.action.value}")

            try:
                resolved_action = self.resolver.resolve_action(
                    action=action,
                    inputs=inputs,
                )

            except ParameterResolutionError:
                return self._record_failure(
                    ReplayResult(
                        status=ReplayStatus.HARD_FAILURE,
                        failure_category=ReplayFailureCategory.INPUT,
                        reason="An action references a missing replay input.",
                        error_code="parameter_resolution_error",
                        completed_steps=completed_steps,
                        failed_step=step,
                    ),
                    phase="parameters",
                )

            policy_failure = self._check_action_policy(
                action=resolved_action,
                completed_steps=completed_steps,
                failed_step=step,
            )

            if policy_failure is not None:
                return policy_failure
            
            try:
                action_result = self.executor.execute(
                    resolved_action
                )

            except Exception:
                return self._record_failure(
                    ReplayResult(
                        status=ReplayStatus.HARD_FAILURE,
                        failure_category=ReplayFailureCategory.EXECUTION,
                        reason=(
                            "An unexpected action execution error occurred."
                        ),
                        error_code="execution_error",
                        completed_steps=completed_steps,
                        failed_step=step,
                    ),
                    phase="action",
                )

            if not action_result.success:
                categories = {
                    ReplayActionStatus.INVALID_ACTION: (
                        ReplayFailureCategory.ARTIFACT
                    ),
                    ReplayActionStatus.TARGET_NOT_FOUND: (
                        ReplayFailureCategory.TARGETING
                    ),
                    ReplayActionStatus.TARGET_NOT_INTERACTABLE: (
                        ReplayFailureCategory.TARGETING
                    ),
                    ReplayActionStatus.TIMEOUT: (
                        ReplayFailureCategory.TIMEOUT
                    ),
                    ReplayActionStatus.EXECUTION_ERROR: (
                        ReplayFailureCategory.EXECUTION
                    ),
                }

                failure = self._record_failure(
                    ReplayResult(
                        status=ReplayStatus.HARD_FAILURE,
                        failure_category=categories.get(
                            action_result.status,
                            ReplayFailureCategory.UNKNOWN,
                        ),
                        reason="The action did not complete successfully.",
                        error_code=action_result.status.value,
                        completed_steps=completed_steps,
                        failed_step=step,
                        action_may_have_executed=(
                            action_result.action_may_have_executed
                        ),
                    ),
                    phase="action",
                )

                application_conditions = {
                    ReplayActionStatus.TARGET_NOT_FOUND,
                    ReplayActionStatus.TARGET_NOT_INTERACTABLE,
                    ReplayActionStatus.TIMEOUT,
                }

                if action_result.status in application_conditions:
                    outcome = self._business_outcome(
                        step,
                        inputs,
                        completed_steps,
                    )

                    if outcome is not None:
                        return outcome

                    # Inspection is permitted, but this initial version
                    # never retries or skips a failed action.
                    return self._offer_handoff(failure)

                return failure
            post_action_policy_failure = self._check_policy_scope(
                completed_steps=completed_steps,
                failed_step=step,
                action_may_have_executed=True,
            )

            if post_action_policy_failure is not None:
                return post_action_policy_failure
            
            # Expected business outcomes take precedence over checkpoints.
            outcome = self._business_outcome(
                step,
                inputs,
                completed_steps,
            )

            if outcome is not None:
                return outcome

            step_checkpoints = checkpoints_by_action.get(step, [])

            for checkpoint in step_checkpoints:
                try:
                    valid, _ = (
                        self.checkpoint_validator.wait_and_validate(
                            checkpoint=checkpoint,
                            page=self.page,
                            inputs=inputs,
                            timeout_ms=5000,
                        )
                    )

                except Exception:
                    return self._record_failure(
                        ReplayResult(
                            status=ReplayStatus.HARD_FAILURE,
                            failure_category=ReplayFailureCategory.CHECKPOINT,
                            reason="Checkpoint validation raised an error.",
                            error_code="checkpoint_validation_error",
                            completed_steps=completed_steps,
                            failed_step=step,
                        ),
                        phase="checkpoint",
                    )

                if not valid:
                    # A business-outcome screen may have appeared while
                    # waiting for the normal checkpoint.
                    outcome = self._business_outcome(
                        step,
                        inputs,
                        completed_steps,
                    )

                    if outcome is not None:
                        return outcome

                    failure = self._record_failure(
                        ReplayResult(
                            status=ReplayStatus.HARD_FAILURE,
                            failure_category=ReplayFailureCategory.CHECKPOINT,
                            reason=(
                                "The expected application state "
                                "was not verified."
                            ),
                            error_code="checkpoint_failed",
                            completed_steps=completed_steps,
                            failed_step=step,
                            action_may_have_executed=True,
                        ),
                        phase="checkpoint",
                    )

                    terminal = self._offer_handoff(
                        failure,
                        verify_resume=self._resume_verifier(
                            step_checkpoints,
                            inputs,
                        ),
                    )

                    if terminal is not None:
                        return terminal

                    # The callback verified ALL checkpoints for this step.
                    # Continue below without executing this action again.
                    break

            completed_steps += 1
            print(f"[REPLAY] Step {step} completed.")

        # Keep your existing Layer 3 output-extraction code below here.

        # Layer 3: Extract outputs using the saved bindings.
        print("\n========== REPLAY OUTPUT EXTRACTION ==========")

        for output in artifact.outputs:
            if output.name in outputs:
                return self._record_failure(
                    ReplayResult(
                        status=ReplayStatus.HARD_FAILURE,
                        failure_category=ReplayFailureCategory.ARTIFACT,
                        reason="The artifact contains duplicate output names.",
                        completed_steps=completed_steps,
                        error_code="duplicate_output_name",
                    ),
                    phase="output",
                )

            binding = output.binding

            if binding.kind != "table":
                return self._record_failure(
                    ReplayResult(
                        status=ReplayStatus.HARD_FAILURE,
                        failure_category=ReplayFailureCategory.ARTIFACT,
                        reason="The output binding type is not supported.",
                        completed_steps=completed_steps,
                        error_code="unsupported_output_binding",
                    ),
                    phase="output",
                )

            try:
                values = self._extract_table_output(
                    row_match_column=binding.row_match.column,
                    row_match_value=binding.row_match.value,
                    value_column=binding.value_column,
                )
            except Exception:
                return self._record_failure(
                    ReplayResult(
                        status=ReplayStatus.HARD_FAILURE,
                        failure_category=ReplayFailureCategory.OUTPUT,
                        reason="Output extraction raised an error.",
                        completed_steps=completed_steps,
                        error_code="output_extraction_error",
                    ),
                    phase="output",
                )

            if len(values) == 0:
                return self._record_failure(
                    ReplayResult(
                        status=ReplayStatus.HARD_FAILURE,
                        failure_category=ReplayFailureCategory.OUTPUT,
                        reason="A declared output could not be located.",
                        completed_steps=completed_steps,
                        error_code="output_not_found",
                        expected="Exactly one matching output value.",
                        observed="Zero matching values.",
                    ),
                    phase="output",
                )

            if len(values) > 1:
                return self._record_failure(
                    ReplayResult(
                        status=ReplayStatus.HARD_FAILURE,
                        failure_category=ReplayFailureCategory.OUTPUT,
                        reason="An output binding matched multiple values.",
                        completed_steps=completed_steps,
                        error_code="ambiguous_output",
                        expected="Exactly one matching output value.",
                        observed=f"{len(values)} matching values.",
                    ),
                    phase="output",
                )

            outputs[output.name] = values[0]
            print("[REPLAY] Output extracted successfully.")

        return ReplayResult(
            status=ReplayStatus.SUCCESS,
            reason="Capability replay completed successfully.",
            outputs=outputs,
            completed_steps=completed_steps,
        )

    def _extract_table_output(
        self,
        row_match_column: str,
        row_match_value: str,
        value_column: str,
    ) -> list[str]:

        return self.page.evaluate(
            """
            (args) => {
                function normalize(value) {
                    return (value || "")
                        .replace(/\\s+/g, " ")
                        .trim();
                }

                const tables = Array.from(
                    document.querySelectorAll(
                        "table, [role='table'], [role='grid']"
                    )
                );

                const matches = [];

                for (const table of tables) {
                    // Find table headers.
                    let headerElements = Array.from(
                        table.querySelectorAll(
                            "thead th, [role='columnheader']"
                        )
                    );

                    // Fallback for tables without an explicit thead.
                    if (headerElements.length === 0) {
                        const firstRow = table.querySelector("tr");

                        if (firstRow) {
                            headerElements = Array.from(
                                firstRow.querySelectorAll("th, td")
                            );
                        }
                    }

                    const headers = headerElements.map(
                        (header) => normalize(header.textContent)
                    );

                    const rowMatchIndex = headers.indexOf(
                        args.row_match_column
                    );

                    const valueColumnIndex = headers.indexOf(
                        args.value_column
                    );

                    // Skip tables without the required columns.
                    if (
                        rowMatchIndex === -1 ||
                        valueColumnIndex === -1
                    ) {
                        continue;
                    }

                    const rows = Array.from(
                        table.querySelectorAll(
                            "tbody tr, [role='row']"
                        )
                    );

                    for (const row of rows) {
                        const cells = Array.from(
                            row.querySelectorAll(
                                [
                                    "td",
                                    "th",
                                    "[role='cell']",
                                    "[role='gridcell']"
                                ].join(",")
                            )
                        );

                        if (
                            rowMatchIndex >= cells.length ||
                            valueColumnIndex >= cells.length
                        ) {
                            continue;
                        }

                        const candidateRowValue = normalize(
                            cells[rowMatchIndex].textContent
                        );

                        if (
                            candidateRowValue !==
                            normalize(args.row_match_value)
                        ) {
                            continue;
                        }

                        const extractedValue = normalize(
                            cells[valueColumnIndex].textContent
                        );

                        matches.push(extractedValue);
                    }
                }

                return matches;
            }
            """,
            {
                "row_match_column": row_match_column,
                "row_match_value": row_match_value,
                "value_column": value_column,
            },
        )