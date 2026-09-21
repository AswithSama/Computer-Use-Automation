import os

from dotenv import load_dotenv
from openai import OpenAI

from app.agent.capability.checkpoint_detector import CheckpointDetector
from app.agent.capability.compiler import CapabilityCompiler
from app.agent.capability.context_builder import CapabilityContextBuilder
from app.agent.capability.inputs.input_extractor_llm import InputExtractorLLM
from app.agent.capability.inputs.input_verifier import InputVerifier
from app.agent.discovery.output_binding.output_grounder import OutputGrounder
from app.agent.capability.registry import CapabilityRegistry
from app.agent.capability.selection_context_generator import (
    SelectionContextGenerator,
)
from app.agent.discovery.browser import BrowserSession
from app.agent.discovery.discovery_agent import DiscoveryAgent
from app.agent.orchestration.capability_selector import CapabilitySelector
from app.agent.orchestration.orchestrator import Orchestrator
from app.agent.schemas.outcomes import BusinessOutcomeRule
from app.agent.replay.models import (
    ReplayRecoveryAction,
    ReplayStatus,
)
from app.agent.replay.replay_engine import ReplayEngine


load_dotenv()


# Local demo configuration.
TARGET_URL = "http://127.0.0.1:8000"
TENANT_ID = "demo_tenant"
APP_ID = "demo_banking_app"


def ask_selection_llm(prompt: str) -> str:
    """
    Reusable LLM adapter for:
      1. Selecting an approved capability.
      2. Generating selection context after discovery.

    Both callers supply their own task-specific prompts.
    """
    model = "gpt-5-mini"

    client = OpenAI()

    response = client.chat.completions.create(
        model=model,
        messages=[
            {
                "role": "system",
                "content": (
                    "Follow the supplied task instructions. "
                    "Return only a valid JSON object."
                ),
            },
            {
                "role": "user",
                "content": prompt,
            },
        ],
        response_format={"type": "json_object"},
    )

    content = response.choices[0].message.content

    if not content:
        raise ValueError("The LLM returned an empty response.")

    return content


def run_discovery(user_request: str):
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
    )

    result = agent.run(
        user_request=user_request,
        target_url=TARGET_URL,
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
        ask_llm=ask_selection_llm,
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
    registry = CapabilityRegistry()

    saved_path = registry.save_draft(
        tenant_id=TENANT_ID,
        app_id=APP_ID,
        artifact=artifact,
        selection_context=selection_context,
        business_outcome_rules=business_outcome_rules,
    )

    loaded = registry.load(saved_path)

    assert loaded.tenant_id == TENANT_ID
    assert loaded.app_id == APP_ID
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


def run_replay(
    *,
    artifact,
    business_outcome_rules,
    inputs,
):
    """
    Execute an existing approved capability.

    The artifact and business-outcome rules are loaded from the
    approved registry entry by the orchestrator.
    """
    print("\n========== DETERMINISTIC REPLAY ==========")

    replay_browser = BrowserSession(
        headless=False,
    )

    try:
        replay_browser.start()

        replay_browser.open(TARGET_URL)

        replay_engine = ReplayEngine(
            page=replay_browser.page,
            business_outcome_rules=business_outcome_rules,
        )

        # Use values extracted from the user's request.
        # Missing required inputs will be handled below.
        replay_inputs = dict(inputs)

        replay_result = replay_engine.replay(
            artifact=artifact,
            inputs=replay_inputs,
        )

        # -----------------------------------------------------
        # Recover from missing required inputs.
        # -----------------------------------------------------
        if (
            replay_result.status == ReplayStatus.RECOVERABLE_FAILURE
            and replay_result.recovery_action
            == ReplayRecoveryAction.REQUEST_INPUT
        ):
            print("\n========== INPUT RECOVERY ==========")

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

            all_required_inputs_present = all(
                replay_inputs.get(
                    parameter.name, ""
                ).strip()
                for parameter in artifact.inputs
                if parameter.required
            )

            if all_required_inputs_present:
                replay_result = replay_engine.replay(
                    artifact=artifact,
                    inputs=replay_inputs,
                )
            else:
                print(
                    "[REPLAY] Required inputs are still missing. "
                    "Replay will not be retried."
                )

        print("\n========== REPLAY RESULT ==========")
        print(replay_result.model_dump_json(indent=2))

        print(
            f"\nReplay successful: "
            f"{replay_result.success}"
        )

        return replay_result

    finally:
        replay_browser.close()


def main():
    user_request = input(
        "What do you want to do? "
    ).strip()

    if not user_request:
        print("A user request is required.")
        return None

    registry = CapabilityRegistry()

    selector = CapabilitySelector(
        ask_llm=ask_selection_llm,
    )

    orchestrator = Orchestrator(
        registry=registry,
        selector=selector,
        run_discovery=run_discovery,
        run_replay=run_replay,
    )

    return orchestrator.run(
        user_request=user_request,
        tenant_id=TENANT_ID,
        app_id=APP_ID,
    )


if __name__ == "__main__":
    main()