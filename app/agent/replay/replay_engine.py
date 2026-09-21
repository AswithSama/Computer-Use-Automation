from app.agent.schemas.capability import CapabilityArtifact
from app.agent.replay.checkpoint_validator import CheckpointValidator
from app.agent.replay.executor import ReplayActionExecutor
from app.agent.replay.models import (
    ReplayActionStatus,
    ReplayFailureCategory,
    ReplayResult,
    ReplayRecoveryAction,
    ReplayStatus,
)
from app.agent.replay.parameter_resolver import (
    ParameterResolutionError,
    ParameterResolver,
)
from app.agent.replay.business_outcomes import BusinessOutcomeDetector
from app.agent.schemas.outcomes import BusinessOutcomeRule
from app.agent.replay.evidence import ReplayEvidenceRecorder


class ReplayEngine:
    def __init__(self, page, business_outcome_rules: tuple[BusinessOutcomeRule, ...] = (),):
        self.page = page
        self.resolver = ParameterResolver()
        self.executor = ReplayActionExecutor(page)
        self.checkpoint_validator = CheckpointValidator()
        self.evidence_recorder = ReplayEvidenceRecorder()
        self.business_outcome_detector = BusinessOutcomeDetector()
        self.business_outcome_rules = business_outcome_rules

    def _record_failure(
        self,
        result: ReplayResult,
        phase: str,
    ) -> ReplayResult:

        # Capture while the live page is available. Preflight failures should
        # not need to interact with the browser before input validation.
        try:
            result.evidence_refs = self.evidence_recorder.record(
                result=result,
                page=None if phase == "preflight" else self.page,
                phase=phase,
            )
        except Exception:
            # Evidence is best-effort; never mask the underlying replay error.
            print("[REPLAY] Evidence could not be saved.")

        return result

    def replay(
        self,
        artifact: CapabilityArtifact,
        inputs: dict[str, str],
    ) -> ReplayResult:

        completed_steps = 0
        outputs: dict[str, str] = {}

        # Validate required inputs before interacting with the UI.
        missing_inputs = [
            parameter.name
            for parameter in artifact.inputs
            if parameter.required
            and (
                parameter.name not in inputs
                or not inputs[parameter.name].strip()
            )
        ]

        if missing_inputs:
            return ReplayResult(
                status=ReplayStatus.RECOVERABLE_FAILURE,
                failure_category=ReplayFailureCategory.INPUT,
                reason=(
                    "Required replay inputs are missing: "
                    + ", ".join(missing_inputs)
                ),
                error_code="missing_required_inputs",
                recovery_action=ReplayRecoveryAction.REQUEST_INPUT,
                completed_steps=0,
            )
        # Preserve every checkpoint attached to each action.
        checkpoints_by_action = {}

        for checkpoint in artifact.checkpoints:
            if not 1 <= checkpoint.after_action <= len(artifact.actions):
                return self._record_failure(
                    ReplayResult(
                        status=ReplayStatus.HARD_FAILURE,
                        failure_category=ReplayFailureCategory.ARTIFACT,
                        reason="A checkpoint references an invalid action index.",
                        error_code="invalid_checkpoint_reference",
                    ),
                    phase="preflight",
                )

            checkpoints_by_action.setdefault(
                checkpoint.after_action, []
            ).append(checkpoint)

        for step, action in enumerate(artifact.actions, start=1):
            print(
                f"[REPLAY] Step {step}: "
                f"{action.action.value}"
            )

            # Resolve this action's input parameters.
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
                        completed_steps=completed_steps,
                        failed_step=step,
                        error_code="parameter_resolution_error",
                    ),
                    phase="parameters",
                )

            # Layer 1: Execute the UI action.
            try:
                action_result = self.executor.execute(resolved_action)
            except Exception:
                return self._record_failure(
                    ReplayResult(
                        status=ReplayStatus.HARD_FAILURE,
                        failure_category=ReplayFailureCategory.EXECUTION,
                        reason="An unexpected action execution error occurred.",
                        completed_steps=completed_steps,
                        failed_step=step,
                        error_code="execution_error",
                    ),
                    phase="action",
                )

            if not action_result.success:
                category_by_status = {
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

                failure_category = category_by_status.get(
                    action_result.status,
                    ReplayFailureCategory.UNKNOWN,
                )

                # A timeout does not automatically make retrying safe.
                # The action may have taken effect before it timed out.
                return self._record_failure(
                    ReplayResult(
                        status=ReplayStatus.HARD_FAILURE,
                        failure_category=failure_category,
                        reason=(
                            "The action did not complete successfully. "
                            "Inspect the current state before retrying."
                        ),
                        completed_steps=completed_steps,
                        failed_step=step,
                        error_code=action_result.status.value,
                    ),
                    phase="action",
                )

            # Layer 2: Validate all checkpoints for this action.
            for checkpoint in checkpoints_by_action.get(step, []):
                try:
                    checkpoint_valid, _ = self.checkpoint_validator.validate(
                        checkpoint=checkpoint,
                        current_url=self.page.url,
                        inputs=inputs,
                    )

                    if not checkpoint_valid:
                        print(
                            "[REPLAY] Checkpoint not reached. "
                            "Waiting up to 5 seconds..."
                        )

                        checkpoint_valid, _ = (
                            self.checkpoint_validator.wait_and_validate(
                                checkpoint=checkpoint,
                                page=self.page,
                                inputs=inputs,
                                timeout_ms=5000,
                            )
                        )

                        if checkpoint_valid:
                            print(
                                "[REPLAY] Expected state reached after waiting."
                            )
                except Exception:
                    return self._record_failure(
                        ReplayResult(
                            status=ReplayStatus.HARD_FAILURE,
                            failure_category=ReplayFailureCategory.CHECKPOINT,
                            reason="Checkpoint validation raised an error.",
                            completed_steps=completed_steps,
                            failed_step=step,
                            error_code="checkpoint_validation_error",
                        ),
                        phase="checkpoint",
                    )

                if not checkpoint_valid:
                    return self._record_failure(
                        ReplayResult(
                            status=ReplayStatus.HARD_FAILURE,
                            failure_category=ReplayFailureCategory.CHECKPOINT,
                            reason=(
                                "The action executed, but its expected "
                                "application state was not verified."
                            ),
                            completed_steps=completed_steps,
                            failed_step=step,
                            error_code="checkpoint_failed",
                        ),
                        phase="checkpoint",
                    )
            if step == 3:
                message = self.page.get_by_text(
                    "Member not found",
                    exact=True,
                )

            # Check for a declared business outcome before continuing.
            business_outcome = self.business_outcome_detector.detect(
                page=self.page,
                step=step,
                inputs=inputs,
                rules=self.business_outcome_rules,
            )

            if business_outcome is not None:
                return ReplayResult(
                    status=ReplayStatus.BUSINESS_OUTCOME,
                    reason=business_outcome.reason,
                    error_code=business_outcome.code,
                    completed_steps=step,
                )

            completed_steps += 1
            print(f"[REPLAY] Step {step} completed.")

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