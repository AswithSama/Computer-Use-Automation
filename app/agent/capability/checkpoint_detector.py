from dataclasses import dataclass
from enum import Enum

from app.agent.schemas.discovery import ActionType
from app.agent.schemas.recording import RecordedTransition


class CheckpointEvidenceType(str, Enum):
    URL = "url"
    STRUCTURAL = "structural"


@dataclass
class CheckpointCandidate:
    source_step: int
    evidence_type: CheckpointEvidenceType
    before_url: str
    after_url: str
    after_observation: str


class CheckpointDetector:

    CHECKPOINT_ACTIONS = {
        ActionType.CLICK,
        ActionType.NAVIGATE,
        ActionType.GO_BACK,
    }

    def detect(
        self,
        candidate_path: list[RecordedTransition],
    ) -> list[CheckpointCandidate]:

        candidates = []

        for transition in candidate_path:

            # FILL, WAIT, etc. are not checkpoint-producing
            # actions in our initial replay contract.
            if transition.action.action not in self.CHECKPOINT_ACTIONS:
                continue

            before = transition.before_state
            after = transition.after_state

            # Nothing observable changed.
            if before.fingerprint == after.fingerprint:
                continue

            # Strong deterministic evidence.
            if before.url != after.url:
                evidence_type = CheckpointEvidenceType.URL

            # State changed, but URL cannot explain the transition.
            # This becomes a candidate for structural evidence.
            else:
                evidence_type = CheckpointEvidenceType.STRUCTURAL

            candidates.append(
                CheckpointCandidate(
                    source_step=transition.step,
                    evidence_type=evidence_type,
                    before_url=before.url,
                    after_url=after.url,
                    after_observation=after.observation,
                )
            )

        return candidates