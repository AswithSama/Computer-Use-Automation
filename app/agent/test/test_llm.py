from dotenv import load_dotenv

from app.agent.capability.context_builder import CapabilityContextBuilder
from app.agent.discovery.discovery_agent import DiscoveryAgent

from app.agent.capability.input_extractor_llm import InputExtractorLLM
from app.agent.capability.input_verifier import InputVerifier

load_dotenv()


def main():
    user_request = input("What do you want to do? ").strip()

    agent = DiscoveryAgent(
        max_steps=20,
        max_failures=5,
    )

    result = agent.run(
        user_request=user_request,
        target_url="http://127.0.0.1:8000",
    )

    print("\n========== RESULT ==========")

    if result is None:
        print("Discovery did not complete successfully.")
        return

    context_builder = CapabilityContextBuilder()

    capability_context = context_builder.build(
        user_request=user_request,
        discovery_result=result,
    )
    input_extractor = InputExtractorLLM()

    input_result = input_extractor.extract(capability_context)
    input_verifier = InputVerifier()

    verification_result = input_verifier.verify(extraction=input_result,context=capability_context)
    print("\nFinal result:")
    print(result.result)

    print("\nExecution trace:")
    for transition in result.execution_trace:
        print(
            f"Step {transition.step}: "
            f"{transition.action.action.value}"
        )

    print("\nCandidate path:")
    for transition in result.candidate_path:
        print(f"Step {transition.step}: "f"{transition.action.action.value}")

    print("\nFinal state:")
    print(result.final_state.url)

    print("\n========== CAPABILITY CONTEXT ==========")
    print(capability_context.model_dump_json(indent=2,))
    print("\n========== EXTRACTED INPUTS ==========")
    print(input_result.model_dump_json(indent=2,))
    print("\n========== INPUT VERIFICATION ==========")
    print(f"Valid: {verification_result.valid}")
    print(f"Reason: {verification_result.reason}")


if __name__ == "__main__":
    main()