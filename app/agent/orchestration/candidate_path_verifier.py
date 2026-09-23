
from collections.abc import Callable
from dataclasses import dataclass
from urllib.parse import urlparse

from app.agent.discovery.browser import BrowserSession
from app.agent.discovery.executor import ActionExecutor
from app.agent.policy.engine import PolicyEngine
from app.agent.policy.models import PolicyDecision
from app.agent.recording.state_fingerprint import (
    build_state_fingerprint,
)
from app.agent.schemas.recording import (
    RecordedState,
    RecordedTransition,
)

BrowserFactory = Callable[[], BrowserSession]


@dataclass(frozen=True)
class VerifiedCandidatePath:
    transitions: list[RecordedTransition]
    final_state: RecordedState


class CandidatePathVerifier:
    """
    Deterministically verify a proposed discovery path.

    Every verification attempt uses a fresh browser session.

    Verification succeeds only when:
    1. the original starting state can be reproduced,
    2. every candidate action executes successfully,
    3. policy remains satisfied, and
    4. the resulting final state matches the original successful state.

    A successful verification also returns newly observed transitions
    from the fresh-browser run, rather than reusing stale recorded states.
    """

    def __init__(
        self,
        *,
        policy_engine: PolicyEngine | None = None,
        policy_profile_id: str = "read_only_discovery",
        browser_factory: BrowserFactory | None = None,
    ):
        self.policy_engine = policy_engine
        self.policy_profile_id = policy_profile_id

        self.browser_factory = (
            browser_factory
            if browser_factory is not None
            else lambda: BrowserSession(headless=True)
        )

    def verify(
        self,
        *,
        transitions: list[RecordedTransition],
        initial_state: RecordedState,
        expected_final_state: RecordedState,
    ) -> bool:
        """
        Boolean interface used by PathMinimizer.

        Return True only when a fresh-browser verification succeeds.
        """
        return (
            self.verify_and_record(
                transitions=transitions,
                initial_state=initial_state,
                expected_final_state=expected_final_state,
            )
            is not None
        )

    def verify_and_record(
        self,
        *,
        transitions: list[RecordedTransition],
        initial_state: RecordedState,
        expected_final_state: RecordedState,
    ) -> VerifiedCandidatePath | None:
        """
        Replay a candidate path from the original starting state.

        On success, return the actual transitions observed during this
        fresh-browser run.

        On any execution, policy, or verification failure, return None.
        """
        browser = None

        try:
            # -------------------------------------------------
            # 1. Check whether the initial URL is permitted.
            # -------------------------------------------------

            if self.policy_engine is not None:
                scope = self.policy_engine.check_scope(
                    current_url=initial_state.url,
                    profile_id=self.policy_profile_id,
                )

                if scope.decision != PolicyDecision.ALLOWED:
                    return None

            allowed_host = urlparse(initial_state.url).hostname

            if not allowed_host:
                return None

            # -------------------------------------------------
            # 2. Start a completely fresh browser session.
            # -------------------------------------------------

            browser = self.browser_factory()
            browser.start()
            browser.open(initial_state.url)

            actual_initial_url = browser.page.url
            actual_initial_observation = browser.observe()

            actual_initial_state = RecordedState(
                url=actual_initial_url,
                observation=actual_initial_observation,
                fingerprint=build_state_fingerprint(
                    url=actual_initial_url,
                    observation=actual_initial_observation,
                ),
            )

            # A minimization trial is not trustworthy unless it
            # reproduces the original candidate path's starting state.
            if (
                actual_initial_state.fingerprint
                != initial_state.fingerprint
            ):
                return None

            # Check the actual loaded URL as well. The browser may
            # have redirected while opening the initial URL.
            if self.policy_engine is not None:
                scope = self.policy_engine.check_scope(
                    current_url=actual_initial_url,
                    profile_id=self.policy_profile_id,
                )

                if scope.decision != PolicyDecision.ALLOWED:
                    return None

            executor = ActionExecutor(
                page=browser.page,
                allowed_host=allowed_host,
                policy_engine=self.policy_engine,
                policy_profile_id=self.policy_profile_id,
            )

            # These transitions will describe the actual shortened
            # execution, not the original discovery execution.
            replayed_transitions: list[RecordedTransition] = []

            previous_state = actual_initial_state

            # -------------------------------------------------
            # 3. Replay and record each candidate action.
            # -------------------------------------------------

            for transition in transitions:
                action = transition.action

                # Check the current page before executing the action.
                if self.policy_engine is not None:
                    scope = self.policy_engine.check_scope(
                        current_url=browser.page.url,
                        profile_id=self.policy_profile_id,
                    )

                    if scope.decision != PolicyDecision.ALLOWED:
                        return None

                    # A trial must obey the same action policy
                    # as ordinary discovery.
                    decision = self.policy_engine.check(
                        action=action.action,
                        current_url=browser.page.url,
                        profile_id=self.policy_profile_id,
                        target_role=action.target_role,
                        target_name=action.target_name,
                        destination_url=action.url,
                    )

                    if decision.decision != PolicyDecision.ALLOWED:
                        return None

                # Observe the real state immediately before this action.
                before_url = browser.page.url
                before_observation = browser.observe()

                before_state = RecordedState(
                    url=before_url,
                    observation=before_observation,
                    fingerprint=build_state_fingerprint(
                        url=before_url,
                        observation=before_observation,
                    ),
                )

                # Reject a trial if the page changed unexpectedly
                # between the previous observation and this action.
                if (
                    before_state.fingerprint
                    != previous_state.fingerprint
                ):
                    return None

                # Execute the candidate action deterministically.
                executor.execute(action)

                # An allowed action may still cause a redirect to
                # an unauthorized route. Check again after execution.
                if self.policy_engine is not None:
                    scope = self.policy_engine.check_scope(
                        current_url=browser.page.url,
                        profile_id=self.policy_profile_id,
                    )

                    if scope.decision != PolicyDecision.ALLOWED:
                        return None

                # Observe the real state after the action.
                after_url = browser.page.url
                after_observation = browser.observe()

                after_state = RecordedState(
                    url=after_url,
                    observation=after_observation,
                    fingerprint=build_state_fingerprint(
                        url=after_url,
                        observation=after_observation,
                    ),
                )

                # Preserve the original source step ID for mapping
                # capability actions and checkpoint candidates.
                #
                # However, before_state and after_state come from
                # this fresh-browser run.
                replayed_transitions.append(
                    RecordedTransition(
                        step=transition.step,
                        action=action,
                        before_state=before_state,
                        after_state=after_state,
                        outcome_reason=(
                            "Action executed during deterministic "
                            "candidate-path verification."
                        ),
                    )
                )

                previous_state = after_state

            # -------------------------------------------------
            # 4. Verify the final state.
            # -------------------------------------------------

            final_url = browser.page.url
            final_observation = browser.observe()

            actual_final_state = RecordedState(
                url=final_url,
                observation=final_observation,
                fingerprint=build_state_fingerprint(
                    url=final_url,
                    observation=final_observation,
                ),
            )

            # Do not accept a trial if the state changes unexpectedly
            # after its final action but before final verification.
            if transitions and (
                actual_final_state.fingerprint
                != previous_state.fingerprint
            ):
                return None

            if (
                actual_final_state.fingerprint
                != expected_final_state.fingerprint
            ):
                return None

            # -------------------------------------------------
            # 5. Return the newly observed, verified path.
            # -------------------------------------------------

            return VerifiedCandidatePath(
                transitions=replayed_transitions,
                final_state=actual_final_state,
            )

        except Exception:
            # An execution error or uncertain result is never
            # evidence that an action is safe to remove.
            return None

        finally:
            if browser is not None:
                try:
                    browser.close()
                except Exception:
                    pass