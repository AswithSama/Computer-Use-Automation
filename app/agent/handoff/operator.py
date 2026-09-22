"""Terminal interface for a human operating the existing browser."""

from typing import Protocol

from app.agent.handoff.models import (
    IncidentClassification,
    InterventionOutcome,
    InterventionRequest,
    InterventionResolution,
)


# Controlled descriptions are safe to persist as operator-reported actions.
# These are declarations, not independently verified browser events.
ACTION_SUMMARIES = {
    "1": "Inspected the application without changing its state.",
    "2": "Dismissed a blocking dialog.",
    "3": "Restored the expected application screen.",
    "4": "Completed an authorized manual application step.",
}


INCIDENT_CLASSIFICATIONS = {
    "1": IncidentClassification.BUSINESS_OUTCOME,
    "2": IncidentClassification.RECOVERABLE_CONDITION,
    "3": IncidentClassification.HARD_FAILURE,
    "4": IncidentClassification.NEEDS_REVIEW,
}


class HumanOperator(Protocol):
    def handle(
        self,
        request: InterventionRequest,
    ) -> InterventionOutcome:
        ...


class TerminalOperator:
    def __init__(self, *, operator_id: str):
        if not operator_id.strip():
            raise ValueError("operator_id must not be empty.")

        # A local audit label, not an authentication mechanism.
        self.operator_id = operator_id.strip()

    def handle(
        self,
        request: InterventionRequest,
    ) -> InterventionOutcome:
        print("\n========== HUMAN INTERVENTION ==========")
        print(f"Phase: {request.phase.value}")
        print(
            f"Step: "
            f"{request.current_step or 'Not associated with a step'}"
        )
        print(f"Reason: {request.reason}")

        if request.screenshot_ref:
            print("\nScreenshot captured for this intervention:")
            print(request.screenshot_ref)
        else:
            print(
                "\nNo screenshot is attached to this intervention."
            )

        print(
            "\nAutomation is waiting. Use the existing browser window."
            "\nStay within the permitted workflow."
            "\nDo not repeat an action whose effect is uncertain."
        )

        if request.risky_action:
            print(
                "\nA risky action requires your attention."
                "\nReporting completion does not authorize automation "
                "to repeat that action."
            )

        try:
            while True:
                choice = input(
                    "\n[d] Finished intervention"
                    "\n[u] Cannot resolve"
                    "\n[c] Cancel run"
                    "\nYour choice: "
                ).strip().lower()

                if choice == "c":
                    return self._outcome(
                        request,
                        InterventionResolution.CANCELLED,
                    )

                if choice not in {"d", "u"}:
                    print("Enter d, u, or c.")
                    continue

                summary = self._collect_action_summary()

                if summary is None:
                    return self._outcome(
                        request,
                        InterventionResolution.CANCELLED,
                    )

                classification = self._collect_classification()

                if classification is None:
                    return self._outcome(
                        request,
                        InterventionResolution.CANCELLED,
                        action_summary=summary,
                    )

                resolution = (
                    InterventionResolution.RESOLVED
                    if choice == "d"
                    else InterventionResolution.UNRESOLVED
                )

                if (
                    classification
                    == IncidentClassification.HARD_FAILURE
                    and resolution == InterventionResolution.RESOLVED
                ):
                    print(
                        "\nYou classified this incident as a hard failure."
                        "\nAutomation cannot resume this run under "
                        "that classification."
                        "\nThe current intervention will be recorded "
                        "as unresolved."
                    )

                    resolution = InterventionResolution.UNRESOLVED

                return self._outcome(
                    request,
                    resolution,
                    action_summary=summary,
                    incident_classification=classification,
                )

        except (EOFError, KeyboardInterrupt):
            print("\nHuman intervention cancelled.")

            return self._outcome(
                request,
                InterventionResolution.CANCELLED,
            )

    def _collect_action_summary(self) -> str | None:
        print("\nWhat did you do?")

        for key, description in ACTION_SUMMARIES.items():
            print(f"{key}. {description}")

        print("c. Cancel")

        while True:
            choice = input("Your choice: ").strip().lower()

            if choice == "c":
                return None

            if choice in ACTION_SUMMARIES:
                return ACTION_SUMMARIES[choice]

            print("Select one of the listed choices.")

    def _collect_classification(
        self,
    ) -> IncidentClassification | None:
        print("\nHow would you classify the incident?")

        print("1. Business outcome")
        print("   The application returned a legitimate business result.")

        print("2. Recoverable condition")
        print("   A known procedure might resolve this automatically")
        print("   in a future capability version.")

        print("3. Hard failure")
        print("   Automation should stop for this condition.")

        print("4. Needs review")
        print("   The appropriate classification is uncertain.")

        print("c. Cancel intervention")

        while True:
            choice = input(
                "\nClassification: "
            ).strip().lower()

            if choice == "c":
                return None

            if choice in INCIDENT_CLASSIFICATIONS:
                return INCIDENT_CLASSIFICATIONS[choice]

            print("Select one of the listed choices.")

    def _outcome(
        self,
        request: InterventionRequest,
        resolution: InterventionResolution,
        *,
        action_summary: str | None = None,
        incident_classification: IncidentClassification | None = None,
    ) -> InterventionOutcome:
        return InterventionOutcome(
            intervention_id=request.intervention_id,
            resolution=resolution,
            operator_id=self.operator_id,
            action_summary=action_summary,
            incident_classification=incident_classification,
        )