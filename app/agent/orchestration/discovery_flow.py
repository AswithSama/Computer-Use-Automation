"""Discovery phase: explore the app, compile a capability, save a draft."""

from collections.abc import Callable

from app.agent.capability.checkpoint_detector import CheckpointDetector
from app.agent.capability.compiler import CapabilityCompiler
from app.agent.capability.context import CapabilityContextBuilder
from app.agent.capability.inputs.input_extractor_llm import InputExtractorLLM
from app.agent.capability.inputs.input_verifier import InputVerifier
from app.agent.capability.selection_context_generator import (
    SelectionContextGenerator,
)
from app.agent.discovery.discovery_agent import DiscoveryAgent
from app.agent.discovery.output_binding.output_grounder import OutputGrounder
from app.agent.registry.registry import CapabilityRegistry
from app.agent.schemas.outcomes import BusinessOutcomeRule
from app.agent.handoff.manager import HumanHandoffManager
from app.agent.handoff.operator import TerminalOperator

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
    ):
        self.target_url = target_url
        self.tenant_id = tenant_id
        self.app_id = app_id
        self.registry = registry
        self.ask_llm = ask_llm

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

        This demo's compilation configuration is specifically for the
        savings-balance workflow. Other goals can be discovered, but
        require their own capability ID, description, and outcome rules
        before they can be saved as reusable capabilities.
        """
        print("\n========== DISCOVERY ==========")

        agent = DiscoveryAgent(
            max_steps=20,
            max_failures=5,
            handoff_manager=self.handoff_manager,
            handoff_enabled=self.handoff_enabled,
            max_interventions=self.max_interventions,
        )

        result = agent.run(
            user_request=user_request,
            target_url=self.target_url,
        )

        if result is None:
            print("Discovery did not complete successfully.")
            return None

        print("\n========== DISCOVERY RESULT ==========")
        print(result.result)

        print("\nExecution trace:")
        for transition in result.execution_trace:
            print(
                f"Step {transition.step}: "
                f"{transition.action.action.value}"
            )

        print("\nCandidate path:")
        for transition in result.candidate_path:
            print(
                f"Step {transition.step}: "
                f"{transition.action.action.value}"
            )

        print("\nFinal state:")
        print(result.final_state.url)
        if result.human_assisted or result.intervention_count > 0:
            print(
                "\n[DISCOVERY] The task completed with human assistance."
                "\n[DISCOVERY] Manual actions are recorded separately "
                "and are not part of an autonomous replay path."
                "\n[DISCOVERY] No capability draft was compiled or saved. "
                "An independently verified autonomous run is required."
            )

            for evidence_ref in result.evidence_refs:
                print(f"[DISCOVERY] Intervention evidence: {evidence_ref}")

            return result

        # Do not save an unrelated discovered workflow under the
        # hardcoded savings-balance capability ID.
        if "savings" not in user_request.casefold():
            print(
                "\n[DISCOVERY] Workflow discovery completed, but this "
                "demo's capability compiler is currently configured "
                "for savings-balance requests only. No draft was saved."
            )
            return result

        # ---------------------------------------------------------
        # Build capability context.
        # ---------------------------------------------------------
        context_builder = CapabilityContextBuilder()

        capability_context = context_builder.build(
            user_request=user_request,
            discovery_result=result,
        )

        print("\n========== CAPABILITY CONTEXT ==========")
        print(capability_context.model_dump_json(indent=2))

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

        print("\n========== EXTRACTED INPUTS ==========")
        print(input_result.model_dump_json(indent=2))

        print("\n========== INPUT VERIFICATION ==========")
        print(f"Valid: {verification_result.valid}")
        print(f"Reason: {verification_result.reason}")

        if not verification_result.valid:
            print("Input verification failed. No draft was saved.")
            return None

        # ---------------------------------------------------------
        # Ground observed outputs in the final page state.
        # ---------------------------------------------------------
        output_grounder = OutputGrounder()

        print("\n========== OUTPUT GROUNDING ==========")

        for output in result.outputs:
            evidence = output_grounder.ground(
                output=output,
                observation=result.final_state.observation,
            )

            print(f"\nOutput: {evidence.output_name}")
            print(f"Type: {evidence.output_type}")
            print(f"Value: {evidence.observed_value}")
            print("Matching evidence:")

            for line in evidence.matching_lines:
                print(line)

        # ---------------------------------------------------------
        # Detect checkpoint candidates.
        # ---------------------------------------------------------
        checkpoint_detector = CheckpointDetector()

        checkpoint_candidates = checkpoint_detector.detect(
            candidate_path=result.candidate_path,
        )

        print("\n========== CHECKPOINT DETECTION ==========")

        for candidate in checkpoint_candidates:
            print(f"\nStep: {candidate.source_step}")
            print(
                f"Evidence type: "
                f"{candidate.evidence_type.value}"
            )
            print(f"Before URL: {candidate.before_url}")
            print(f"After URL: {candidate.after_url}")

        # ---------------------------------------------------------
        # Compile the reusable capability.
        # ---------------------------------------------------------
        compiler = CapabilityCompiler()

        artifact = compiler.compile(
            capability_id="get_savings_balance",
            description="Retrieve the savings balance for a member.",
            context=capability_context,
            extracted_inputs=input_result,
            checkpoint_candidates=checkpoint_candidates,
            output_locations=result.output_locations,
        )

        print("\n========== CAPABILITY ARTIFACT ==========")
        print(artifact.model_dump_json(indent=2))

        # ---------------------------------------------------------
        # Generate selection-facing context with a separate LLM call.
        # ---------------------------------------------------------
        selection_context = SelectionContextGenerator(
            ask_llm=self.ask_llm,
        ).generate(
            user_request=user_request,
            artifact=artifact,
        )

        print("\n========== SELECTION CONTEXT ==========")
        print(selection_context.model_dump_json(indent=2))

        # ---------------------------------------------------------
        # Known business outcomes for the local savings-balance demo.
        #
        # These rules are specific to the four-action workflow below.
        # They are not automatically discovered or generalized.
        # ---------------------------------------------------------
        expected_actions = [
            "click",
            "fill",
            "click",
            "click",
        ]

        actual_actions = [
            action.action.value
            for action in artifact.actions
        ]

        if actual_actions != expected_actions:
            print(
                "\n[DISCOVERY] The compiled action sequence differs "
                "from the savings-balance workflow for which the "
                "business-outcome rules were written. "
                "No draft was saved; review the artifact and rules."
            )
            return None

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
        assert loaded.artifact.capability_id == "get_savings_balance"
        assert loaded.selection_context is not None
        assert len(loaded.business_outcome_rules) == 2

        print("\n========== REGISTRY ==========")
        print(f"[DISCOVERY] Capability draft saved: {saved_path}")
        print(
            "[DISCOVERY] Draft is awaiting human review. "
            "It is not eligible for replay yet."
        )

        return saved_path
