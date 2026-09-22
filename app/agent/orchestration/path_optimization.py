
from app.agent.orchestration.candidate_path_verifier import (
    CandidatePathVerifier,
)
from app.agent.policy.engine import PolicyEngine
from app.agent.recording.path_minimizer import PathMinimizer
from app.agent.recording.path_segments import SamePageSegmentDetector
from app.agent.schemas.discovery import ActionType
from app.agent.schemas.recording import DiscoveryResult


def minimize_discovery_result(
    result: DiscoveryResult,
    *,
    policy_engine: PolicyEngine,
    required_action_sequence: tuple[ActionType, ...] | None = None,
) -> DiscoveryResult:
    """
    Try to shorten a fully autonomous, read-only discovery path.

    Return the original result whenever minimization is inapplicable,
    fails verification, or produces an action sequence that is not
    compatible with the caller's capability contract.

    Never alter the original execution trace.
    """

    if result.human_assisted or result.intervention_count > 0:
        return result

    original_path = result.candidate_path

    if len(original_path) < 2:
        return result

    # For a workflow whose existing action sequence is already
    # canonical, there is no benefit in trying to shorten it.
    if required_action_sequence is not None:
        original_actions = tuple(
            transition.action.action
            for transition in original_path
        )

        if original_actions == required_action_sequence:
            return result

    segments = SamePageSegmentDetector().detect(original_path)

    # Ordinary discoveries incur no extra browser session.
    if not segments:
        return result

    verifier = CandidatePathVerifier(
        policy_engine=policy_engine,
        policy_profile_id="read_only_discovery",
    )

    initial_state = original_path[0].before_state
    expected_final_state = result.final_state

    try:
        # First establish that the original candidate path can
        # reproduce the successful discovery result.
        if not verifier.verify(
            transitions=original_path,
            initial_state=initial_state,
            expected_final_state=expected_final_state,
        ):
            return result

        candidate = list(original_path)
        minimizer = PathMinimizer()

        def verify_trial(trial):
            if not trial:
                return False

            return verifier.verify(
                transitions=trial,
                initial_state=initial_state,
                expected_final_state=expected_final_state,
            )

        # Process later segments first. Removing actions in a later
        # segment cannot shift the indices of an earlier segment.
        for segment in sorted(
            segments,
            key=lambda item: item.start_index,
            reverse=True,
        ):
            outcome = minimizer.minimize(
                transitions=candidate,
                segment=segment,
                verify=verify_trial,
            )

            candidate = outcome.transitions

        if len(candidate) == len(original_path):
            return result

        # This demo's business-outcome rules depend on the exact
        # action sequence. Do not substitute a shorter but incompatible
        # workflow into the existing savings capability.
        if required_action_sequence is not None:
            candidate_actions = tuple(
                transition.action.action
                for transition in candidate
            )

            if candidate_actions != required_action_sequence:
                return result

        # Verification during removal returned only True/False.
        # Replay the final candidate again to obtain fresh, internally
        # consistent before/after states for checkpoint generation.
        verified_path = verifier.verify_and_record(
            transitions=candidate,
            initial_state=initial_state,
            expected_final_state=expected_final_state,
        )

        if verified_path is None:
            return result

        # Keep result.execution_trace, completion data, outputs and
        # output locations from the original successful discovery.
        # Replace only the candidate path with newly observed evidence.
        return result.model_copy(
            update={
                "candidate_path": verified_path.transitions,
            }
        )

    except Exception:
        # An optimization failure must not corrupt the successful
        # original discovery or make an uncertain path eligible
        # for compilation.
        return result