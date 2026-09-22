from dataclasses import dataclass

from app.agent.schemas.recording import RecordedTransition


@dataclass(frozen=True)
class SamePageSegment:
    """
    A consecutive section of the candidate path where actions
    changed observable state while remaining on the same URL.
    """

    start_index: int
    end_index: int
    url: str

    @property
    def transition_count(self) -> int:
        return self.end_index - self.start_index + 1


class SamePageSegmentDetector:
    """
    Finds portions of a candidate path that may contain
    unnecessary same-page exploration.

    Detection does NOT mean the actions are removable.
    It only identifies regions worth verifying later.
    """

    def detect(
        self,
        transitions: list[RecordedTransition],
    ) -> list[SamePageSegment]:

        segments: list[SamePageSegment] = []

        start_index: int | None = None
        segment_url: str | None = None

        for index, transition in enumerate(transitions):

            before = transition.before_state
            after = transition.after_state

            stayed_on_same_url = (
                before.url == after.url
            )

            observable_state_changed = (
                before.fingerprint
                != after.fingerprint
            )

            candidate = (
                stayed_on_same_url
                and observable_state_changed
            )

            if not candidate:
                self._finish_segment(
                    segments=segments,
                    start_index=start_index,
                    end_index=index - 1,
                    url=segment_url,
                )

                start_index = None
                segment_url = None
                continue

            # Start a new candidate section.
            if start_index is None:
                start_index = index
                segment_url = before.url
                continue

            # Still same logical page as current segment.
            if before.url == segment_url:
                continue

            # URL changed between candidate regions.
            self._finish_segment(
                segments=segments,
                start_index=start_index,
                end_index=index - 1,
                url=segment_url,
            )

            start_index = index
            segment_url = before.url

        # Flush final segment.
        self._finish_segment(
            segments=segments,
            start_index=start_index,
            end_index=len(transitions) - 1,
            url=segment_url,
        )

        return segments

    @staticmethod
    def _finish_segment(
        *,
        segments: list[SamePageSegment],
        start_index: int | None,
        end_index: int,
        url: str | None,
    ) -> None:

        if start_index is None or url is None:
            return

        # One same-page action by itself isn't an exploration
        # sequence worth minimizing.
        if end_index <= start_index:
            return

        segments.append(
            SamePageSegment(
                start_index=start_index,
                end_index=end_index,
                url=url,
            )
        )