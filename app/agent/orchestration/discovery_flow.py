"""Discovery phase: explore the app, compile a capability, save a draft."""

import logging
from collections.abc import Callable

from app.agent.console import field, section, step, success
from app.agent.capability.checkpoint_detector import CheckpointDetector
from app.agent.capability.compiler import CapabilityCompiler
from app.agent.capability.identity_generator import CapabilityIdentityGenerator
from app.agent.capability.context import CapabilityContextBuilder
from app.agent.capability.inputs.input_extractor_llm import InputExtractorLLM
from app.agent.capability.inputs.input_verifier import InputVerifier
from app.agent.capability.selection_context_generator import (
    SelectionContextGenerator,
)
from app.agent.discovery.discovery_agent import DiscoveryAgent
from app.agent.discovery.output_binding.output_grounder import OutputGrounder
from app.agent.handoff.manager import HumanHandoffManager
from app.agent.handoff.operator import TerminalOperator
from app.agent.orchestration.path_optimization import (
    minimize_discovery_result,
)
from app.agent.policy.engine import PolicyEngine
from app.agent.registry.registry import CapabilityRegistry
from app.agent.schemas.discovery import ActionType
from app.agent.schemas.outcomes import BusinessOutcomeRule


logger = logging.getLogger(__name__)


class DiscoveryFlow:
    """
    Discovery phase workflow: explore -> compile -> save a draft.

    Called by the Orchestrator when no approved capability matches.
    Approval of the saved draft remains a separate human action.
    """

    def __init__(
        self,
        *,
        target_url: str,
        tenant_id: str,
        app_id: str,
        registry: CapabilityRegistry,
        ask_llm: Callable[[str], str],
        handoff_manager: HumanHandoffManager | None = None,
        handoff_enabled: bool = True,
        max_interventions: int = 2,
        policy_engine: PolicyEngine | None = None,
    ):
        self.target_url = target_url
        self.tenant_id = tenant_id
        self.app_id = app_id
        self.registry = registry
        self.ask_llm = ask_llm
        self.policy_engine = policy_engine

        self.handoff_manager = (
            handoff_manager
            if handoff_manager is not None
            else HumanHandoffManager(
                operator=TerminalOperator(
                    operator_id="local-operator"
                )
            )
        )

        self.handoff_enabled = handoff_enabled
        self.max_interventions = max_interventions

    def __call__(self, user_request: str):
        """
        Discover a workflow when no approved capability matches.

        Compile autonomous workflows only when their outputs have
        verified table bindings. Never auto-approve a draft.
        """
        section("DISCOVERY")
        field("Mode", "LLM-guided exploration")
        logger.debug("Starting discovery.")

        agent = DiscoveryAgent(
            max_steps=20,
            max_failures=5,
            handoff_manager=self.handoff_manager,
            handoff_enabled=self.handoff_enabled,
            max_interventions=self.max_interventions,
            policy_engine=self.policy_engine,  # Add this line.
        )

        result = agent.run(
            user_request=user_request,
            target_url=self.target_url,
        )

        if result is None:
            logger.warning("Discovery did not complete successfully.")
            return None

        for transition in result.candidate_path:
            action = transition.action
            target = (
                action.target_name
                or action.target_role
                or action.target_ref
                or ""
            )
            step(
                transition.step,
                action.action.value,
                target,
            )

        success("Discovery completed")
        print()
        field("Result", result.result)
        logger.debug(
            "Actions executed: %s | Candidate actions: %s | Final URL: %s",
            len(result.execution_trace),
            len(result.candidate_path),
            result.final_state.url,
        )
        logger.debug(
            "Execution trace: %s",
            [
                (transition.step, transition.action.action.value)
                for transition in result.execution_trace
            ],
        )
        logger.debug(
            "Candidate path: %s",
            [
                (transition.step, transition.action.action.value)
                for transition in result.candidate_path
            ],
        )
        if result.human_assisted or result.intervention_count > 0:
            logger.warning(
                "Task completed with human assistance; no autonomous "
                "capability draft will be saved."
            )
            logger.debug(
                "Intervention evidence: %s",
                result.evidence_refs,
            )

            return result

        # An answer without a complete verified table-binding set is
        # not yet reusable. Keep the review evidence, not an executable draft.
        if not result.outputs or len(result.output_locations) != len(result.outputs):
            logger.warning(
                "Discovery answered the question, but the output binding "
                "requires review; no capability draft saved."
            )
            for ref in result.evidence_refs:
                logger.info("Review evidence: %s", ref)
            return result

        # Optional, verified path minimization; no business-specific action
        # sequence is required for generic table-based capabilities.
        if self.policy_engine is not None:
            original_path_length = len(result.candidate_path)

            result = minimize_discovery_result(
                result,
                policy_engine=self.policy_engine,
                required_action_sequence=None,
            )

            minimized_path_length = len(result.candidate_path)

            if minimized_path_length < original_path_length:
                logger.debug(
                    "Verified path minimization: %s -> %s actions.",
                    original_path_length,
                    minimized_path_length,
                )
            else:
                logger.debug("Original candidate path retained.")
        else:
            logger.warning(
                "Path minimization skipped: no shared policy engine supplied."
            )

        section("VERIFICATION")
        field(
            "Path",
            f"{len(result.candidate_path)} actions retained ✓",
        )

        # ---------------------------------------------------------
        # Build capability context.
        # ---------------------------------------------------------
        context_builder = CapabilityContextBuilder()

        capability_context = context_builder.build(
            user_request=user_request,
            discovery_result=result,
        )

        logger.debug(
            "Capability context: %s",
            capability_context.model_dump_json(),
        )

        # ---------------------------------------------------------
        # Extract and verify reusable inputs.
        # ---------------------------------------------------------
        input_extractor = InputExtractorLLM()

        input_result = input_extractor.extract(
            capability_context
        )

        input_verifier = InputVerifier()

        verification_result = input_verifier.verify(
            extraction=input_result,
            context=capability_context,
        )


        logger.debug(
            "Inputs extracted: %s",
            [
                (item.name, item.type)
                for item in input_result.inputs
            ],
        )
        logger.debug(
            "Input verification: %s",
            "PASS" if verification_result.valid else "FAIL",
        )
        logger.debug(
            "Extracted inputs: %s",
            input_result.model_dump_json(),
        )
        logger.debug(
            "Input verification reason: %s",
            verification_result.reason,
        )

        if not verification_result.valid:
            logger.error("Input verification failed; no draft saved.")
            return None

        for rejected in verification_result.rejected_inputs:
            logger.debug(
                "Rejected input proposal %s: %s",
                rejected.name,
                rejected.reason,
            )

        input_result = verification_result.verified_extraction

        verified_input_summary = ", ".join(
            f"{item.name} [{item.type}]"
            for item in input_result.inputs
        ) or "None"
        field("Inputs", f"{verified_input_summary} ✓")

        logger.debug(
            "Verified inputs: %s",
            [
                (candidate.name, candidate.type)
                for candidate in input_result.inputs
            ],
        )
        # ---------------------------------------------------------
        # Ground observed outputs in the final page state.
        # ---------------------------------------------------------
        output_grounder = OutputGrounder()

        logger.debug("Grounding declared outputs.")

        for output in result.outputs:
            evidence = output_grounder.ground(
                output=output,
                observation=result.final_state.observation,
            )

            field(
                "Output",
                f"{evidence.output_name} [{evidence.output_type}] ✓",
            )
            logger.debug(
                "Grounded output %s value=%s evidence=%s",
                evidence.output_name,
                evidence.observed_value,
                evidence.matching_lines,
            )

        # ---------------------------------------------------------
        # Detect checkpoint candidates.
        # ---------------------------------------------------------
        checkpoint_detector = CheckpointDetector()

        checkpoint_candidates = checkpoint_detector.detect(
            candidate_path=result.candidate_path,
        )

        field(
            "Checkpoints",
            f"{len(checkpoint_candidates)} ✓",
        )
        logger.debug(
            "Checkpoint candidates: %s",
            [
                {
                    "step": candidate.source_step,
                    "evidence_type": candidate.evidence_type.value,
                    "before_url": candidate.before_url,
                    "after_url": candidate.after_url,
                }
                for candidate in checkpoint_candidates
            ],
        )

        # ---------------------------------------------------------
        # Compile the reusable capability.
        # ---------------------------------------------------------
        compiler = CapabilityCompiler()

        try:
            identity = CapabilityIdentityGenerator().generate(
                context=capability_context,
                extracted_inputs=input_result,
            )
            artifact = compiler.compile(
                capability_id=identity.capability_id,
                description=identity.description,
                context=capability_context,
                extracted_inputs=input_result,
                checkpoint_candidates=checkpoint_candidates,
                output_locations=result.output_locations,
            )
        except ValueError as exc:
            logger.warning(
                "Capability compilation requires review; no draft saved: %s", exc
            )
            return result

        section("CAPABILITY")
        field("ID", artifact.capability_id)
        field("Actions", len(artifact.actions))
        field("Inputs", len(artifact.inputs))
        field("Outputs", len(artifact.outputs))
        field("Checkpoints", len(artifact.checkpoints))
        logger.debug(
            "Full capability artifact: %s",
            artifact.model_dump_json(),
        )

        # ---------------------------------------------------------
        # Generate selection-facing context with a separate LLM call.
        # ---------------------------------------------------------
        selection_context = SelectionContextGenerator().generate(
            user_request=user_request,
            artifact=artifact,
        )

        logger.debug(
            "Selection context: %s",
            selection_context.model_dump_json(),
        )

        # The existing specialized outcome rules are valid only for the
        # reviewed, four-action savings workflow; other drafts start with
        # an empty list. Missing rules never remove generic replay safety.
        business_outcome_rules = ()
        savings_contract = (
            [action.action.value for action in artifact.actions]
            == ["click", "fill", "click", "click"]
            and any(
                parameter.name == "member_id"
                for parameter in artifact.inputs
            )
            and any(
                output.name == "savings_balance"
                and output.binding.value_column == "Current Balance"
                and output.binding.row_match.column == "Type"
                and output.binding.row_match.value == "Savings"
                for output in artifact.outputs
            )
        )
        if savings_contract:
            business_outcome_rules = (
                BusinessOutcomeRule(
                    after_action=3,
                    code="member_not_found",
                    reason="The requested member was not found.",
                    url_pattern="/members?member_id={{member_id}}",
                    visible_text=(
                        "No member record was found for ID {{member_id}}."
                    ),
                ),
                BusinessOutcomeRule(
                    after_action=4,
                    code="savings_account_not_found",
                    reason="The requested member has no savings account.",
                    url_pattern="/members/{{member_id}}",
                    kind="table_row_absent",
                    row_match_column="Type",
                    row_match_value="Savings",
                    required_column="Current Balance",
                ),
            )

        # ---------------------------------------------------------
        # Save a draft. Approval remains a separate human action.
        # ---------------------------------------------------------
        registry = self.registry

        saved_path = registry.save_draft(
            tenant_id=self.tenant_id,
            app_id=self.app_id,
            artifact=artifact,
            selection_context=selection_context,
            business_outcome_rules=business_outcome_rules,
        )

        loaded = registry.load(saved_path)

        assert loaded.tenant_id == self.tenant_id
        assert loaded.app_id == self.app_id
        assert loaded.approval_status == "draft"
        assert loaded.artifact.capability_id == identity.capability_id
        assert loaded.selection_context is not None
        assert len(loaded.business_outcome_rules) == len(business_outcome_rules)

        success("Draft saved")
        field("File", saved_path)
        field("Status", "Awaiting human approval")

        return saved_path
