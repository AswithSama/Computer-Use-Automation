from app.agent.recording.models import (
    RecordedState,
    RecordedTransition,
)


class TrajectoryRecorder:
    def __init__(self) -> None:
        # Complete history of every successfully executed + validated transition.
        # We NEVER remove anything from this.
        self.execution_trace: list[RecordedTransition] = []

        # States belonging to our current candidate replay path.
        self.state_stack: list[RecordedState] = []

        # Transitions belonging to our current candidate replay path.
        self.path_stack: list[RecordedTransition] = []

    def initialize(self, initial_state: RecordedState) -> None:
        """
        Initialize the recorder with the state where discovery begins.
        """
        self.execution_trace.clear()
        self.path_stack.clear()

        self.state_stack = [initial_state]

    def record_transition(
        self,
        transition: RecordedTransition,
    ) -> None:
        """
        Record a successfully executed and post-validated transition.

        The full execution trace always keeps the transition.

        The candidate path removes loops when the new state matches
        a state that already exists in the current state stack.
        """

        # Always preserve the real successful execution history.
        self.execution_trace.append(transition)

        new_fingerprint = transition.after_state.fingerprint
        before_fingerprint = transition.before_state.fingerprint

        # A successful action may leave the observable browser state unchanged.
        #
        # Example:
        #
        # B --FILL--> B
        #
        # This is NOT backtracking. The action may still be required during
        # deterministic replay, so we preserve it.
        if new_fingerprint == before_fingerprint:
            self.path_stack.append(transition)
            self.state_stack.append(transition.after_state)
            return

        existing_state_index = self._find_state_index(
            new_fingerprint
        )

        # The resulting state is different from the state we started from,
        # but it already exists somewhere in our current path.
        #
        # Example:
        #
        # A -> B -> C -> B
        #
        # C != B, and the resulting B already exists in the stack.
        # Therefore this represents a return to an earlier state.
        if existing_state_index is not None:
            self.state_stack = self.state_stack[
                : existing_state_index + 1
            ]

            self.path_stack = self.path_stack[
                :existing_state_index
            ]

            return

        # Otherwise this is a genuinely new state.
        self.path_stack.append(transition)
        self.state_stack.append(transition.after_state)

    def _find_state_index(
        self,
        fingerprint: str,
    ) -> int | None:
        """
        Find a state with the given fingerprint in the current
        candidate path.

        Returns its index if found, otherwise None.
        """

        for index, state in enumerate(self.state_stack):
            if state.fingerprint == fingerprint:
                return index

        return None

    def get_execution_trace(
        self,
    ) -> list[RecordedTransition]:
        """
        Return the complete successful execution trace.
        """
        return list(self.execution_trace)

    def get_candidate_path(
        self,
    ) -> list[RecordedTransition]:
        """
        Return the current stack-cleaned candidate replay path.
        """
        return list(self.path_stack)