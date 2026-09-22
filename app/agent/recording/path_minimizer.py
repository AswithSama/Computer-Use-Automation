from collections.abc import Callable
from dataclasses import dataclass

from app.agent.recording.path_segments import SamePageSegment
from app.agent.schemas.recording import RecordedTransition


PathVerifier = Callable[
    [list[RecordedTransition]],
    bool,
]


@dataclass(frozen=True)
class PathMinimizationResult:
    transitions: list[RecordedTransition]
    attempted_removals: int
    accepted_removals: int


class PathMinimizer:
    """
    Conservatively removes actions from a detected same-page segment.

    An action is removed only when the supplied verifier confirms
    that the complete shortened path still succeeds.

    The minimizer itself does not decide whether an action is
    semantically unnecessary.
    """

    def minimize(
        self,
        *,
        transitions: list[RecordedTransition],
        segment: SamePageSegment,
        verify: PathVerifier,
    ) -> PathMinimizationResult:

        if (
            segment.start_index < 0
            or segment.end_index < segment.start_index
            or segment.end_index >= len(transitions)
        ):
            raise ValueError(
                "Same-page segment is outside the candidate path."
            )

        # Never mutate the recorder's original candidate path.
        candidate = list(transitions)

        # Track each transition by its position in the original path.
        #
        # This prevents index shifting from causing us to remove the
        # wrong action after earlier removals are accepted.
        original_indices = list(range(len(transitions)))

        removable_indices = range(
            segment.start_index,
            segment.end_index + 1,
        )

        attempted_removals = 0
        accepted_removals = 0

        for original_index in removable_indices:

            # An earlier accepted removal may already have changed
            # the candidate list's positions.
            if original_index not in original_indices:
                continue

            current_index = original_indices.index(
                original_index
            )

            trial_candidate = [
                *candidate[:current_index],
                *candidate[current_index + 1:],
            ]

            trial_indices = [
                *original_indices[:current_index],
                *original_indices[current_index + 1:],
            ]

            attempted_removals += 1

            try:
                verified = bool(
                    verify(trial_candidate)
                )

            except Exception:
                # Verification failure is never evidence that an
                # action is safe to remove.
                verified = False

            if not verified:
                continue

            candidate = trial_candidate
            original_indices = trial_indices
            accepted_removals += 1

        return PathMinimizationResult(
            transitions=candidate,
            attempted_removals=attempted_removals,
            accepted_removals=accepted_removals,
        )