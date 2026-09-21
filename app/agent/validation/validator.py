import re
from enum import Enum
from urllib.parse import urljoin, urlparse

from pydantic import BaseModel

from app.agent.schemas.discovery import ActionType, BrowserAction


class ValidationStatus(str, Enum):
    APPROVED = "approved"
    REJECTED = "rejected"
    NEEDS_LLM = "needs_llm"


class ValidationResult(BaseModel):
    status: ValidationStatus
    reason: str


class ActionValidator:
    def validate(
        self,
        action: BrowserAction,
        user_request: str,
        observation: str,
        current_url: str,
        previous_actions: list[BrowserAction],
    ) -> ValidationResult:

        duplicate_result = self._check_duplicate(action, previous_actions)

        if duplicate_result:
            return duplicate_result

        if action.action == ActionType.CLICK:
            return self._validate_target(action, observation)

        if action.action == ActionType.FILL:
            return self._validate_fill(action, user_request, observation)

        if action.action == ActionType.NAVIGATE:
            return self._validate_navigation(action, current_url)

        if action.action == ActionType.FINISH:
            return self._validate_finish(action, observation)

        if action.action in {
            ActionType.GO_BACK,
            ActionType.WAIT,
            ActionType.REQUEST_VISUAL,
            ActionType.REQUEST_HUMAN,
        }:
            return ValidationResult(
                status=ValidationStatus.APPROVED,
                reason=f"{action.action.value} does not require additional deterministic validation.",
            )

        return ValidationResult(
            status=ValidationStatus.REJECTED,
            reason=f"Unsupported action type: {action.action}",
        )

    # =====================================================
    # TARGET VALIDATION
    # =====================================================

    def _validate_target(
        self,
        action: BrowserAction,
        observation: str,
    ) -> ValidationResult:

        if not action.target_ref:
            return ValidationResult(
                status=ValidationStatus.REJECTED,
                reason="Interactive action is missing target_ref.",
            )

        if not action.target_role:
            return ValidationResult(
                status=ValidationStatus.REJECTED,
                reason="Interactive action is missing target_role.",
            )

        if not action.target_name:
            return ValidationResult(
                status=ValidationStatus.REJECTED,
                reason="Interactive action is missing target_name.",
            )

        # Find the exact observation line containing this ref.
        matching_line = None

        for line in observation.splitlines():
            if f"[ref={action.target_ref}]" in line:
                matching_line = line
                break

        if matching_line is None:
            return ValidationResult(
                status=ValidationStatus.REJECTED,
                reason=(
                    f"Target ref {action.target_ref} does not exist "
                    "in the current page observation."
                ),
            )

        normalized_line = self._normalize_text(matching_line)
        normalized_role = self._normalize_text(action.target_role)
        normalized_name = self._normalize_text(action.target_name)

        # Validate role and name against the SAME observed line
        # containing the reference.
        if normalized_role not in normalized_line:
            return ValidationResult(
                status=ValidationStatus.REJECTED,
                reason=(
                    f'Target role "{action.target_role}" does not '
                    f"match ref {action.target_ref}."
                ),
            )

        if normalized_name not in normalized_line:
            return ValidationResult(
                status=ValidationStatus.REJECTED,
                reason=(
                    f'Target name "{action.target_name}" does not '
                    f"match ref {action.target_ref}."
                ),
            )

        return ValidationResult(
            status=ValidationStatus.APPROVED,
            reason=(
                f"Target {action.target_ref}, role "
                f'"{action.target_role}", and name '
                f'"{action.target_name}" match the same observed element.'
            ),
        )

    # =====================================================
    # FILL VALIDATION
    # =====================================================

    def _validate_fill(
        self,
        action: BrowserAction,
        user_request: str,
        observation: str,
    ) -> ValidationResult:

        target_validation = self._validate_target(action, observation)

        if target_validation.status != ValidationStatus.APPROVED:
            return target_validation

        if action.value is None:
            return ValidationResult(
                status=ValidationStatus.REJECTED,
                reason="Fill action is missing a value.",
            )

        # First trusted source: original user input.
        user_result = self._validate_value_from_user(action.value, user_request)

        if user_result.status == ValidationStatus.APPROVED:
            return user_result

        # Second trusted source: current browser observation.
        #
        # Later this can be extended to trusted previous
        # observations/session evidence without changing
        # the overall validation pipeline.
        page_result = self._validate_value_from_page(action.value, observation)

        if page_result.status == ValidationStatus.APPROVED:
            return page_result

        # We cannot prove where this value came from.
        # It might be legitimately derived or hallucinated.
        return ValidationResult(
            status=ValidationStatus.NEEDS_LLM,
            reason=(
                f'Value "{action.value}" could not be directly grounded '
                "in trusted user input or trusted page information. "
                "It must be reviewed as a derived/unverified value."
            ),
        )

    # =====================================================
    # USER GROUNDING
    # =====================================================

    def _validate_value_from_user(
        self,
        value: str,
        user_request: str,
    ) -> ValidationResult:

        normalized_value = self._normalize_text(value)
        normalized_request = self._normalize_text(user_request)

        if normalized_value in normalized_request:
            return ValidationResult(
                status=ValidationStatus.APPROVED,
                reason=f'Value "{value}" is directly grounded in the original user request.',
            )

        # Numeric normalization.
        value_digits = self._digits_only(value)

        if value_digits:
            request_numbers = [
                self._digits_only(number)
                for number in re.findall(r"\d[\d,.-]*", user_request)
            ]

            if value_digits in request_numbers:
                return ValidationResult(
                    status=ValidationStatus.APPROVED,
                    reason=f'Numeric value "{value}" matches a value in the original user request.',
                )

        return ValidationResult(
            status=ValidationStatus.NEEDS_LLM,
            reason=f'Value "{value}" is not directly grounded in the original user request.',
        )

    # =====================================================
    # PAGE GROUNDING
    # =====================================================

    def _validate_value_from_page(
        self,
        value: str,
        observation: str,
    ) -> ValidationResult:

        normalized_value = self._normalize_text(value)
        normalized_observation = self._normalize_text(observation)

        if normalized_value in normalized_observation:
            return ValidationResult(
                status=ValidationStatus.APPROVED,
                reason=f'Value "{value}" is directly grounded in the current page observation.',
            )

        value_digits = self._digits_only(value)

        if value_digits:
            observation_numbers = [
                self._digits_only(number)
                for number in re.findall(r"\d[\d,.-]*", observation)
            ]

            if value_digits in observation_numbers:
                return ValidationResult(
                    status=ValidationStatus.APPROVED,
                    reason=f'Numeric value "{value}" matches trusted page information.',
                )

        return ValidationResult(
            status=ValidationStatus.NEEDS_LLM,
            reason=f'Value "{value}" is not directly grounded in the current page observation.',
        )

    # =====================================================
    # FINISH VALIDATION
    # =====================================================

    def _validate_finish(
        self,
        action: BrowserAction,
        observation: str,
    ) -> ValidationResult:

        if not action.result:
            return ValidationResult(
                status=ValidationStatus.REJECTED,
                reason="Finish action is missing a result.",
            )

        result_facts = re.findall(r"\$?\d[\d,]*(?:\.\d+)?", action.result)

        if not result_facts:
            return ValidationResult(
                status=ValidationStatus.NEEDS_LLM,
                reason=(
                    "The result contains no simple numeric facts "
                    "that deterministic validation can verify."
                ),
            )

        normalized_observation = self._normalize_text(observation)
        unsupported = []

        for fact in result_facts:
            normalized_fact = self._normalize_text(fact)

            if normalized_fact not in normalized_observation:
                unsupported.append(fact)

        if unsupported:
            return ValidationResult(
                status=ValidationStatus.REJECTED,
                reason=(
                    "Final result contains facts not supported by "
                    f"the current page observation: {unsupported}"
                ),
            )

        return ValidationResult(
            status=ValidationStatus.APPROVED,
            reason=(
                "All numeric facts in the final result are supported "
                "by the current page observation."
            ),
        )

    # =====================================================
    # NAVIGATION
    # =====================================================

    def _validate_navigation(
        self,
        action: BrowserAction,
        current_url: str,
    ) -> ValidationResult:

        if not action.url:
            return ValidationResult(
                status=ValidationStatus.REJECTED,
                reason="Navigate action is missing a URL.",
            )

        destination = urljoin(current_url, action.url)
        current_host = urlparse(current_url).hostname
        destination_host = urlparse(destination).hostname

        if destination_host != current_host:
            return ValidationResult(
                status=ValidationStatus.REJECTED,
                reason=(
                    f"Navigation to host {destination_host} is blocked. "
                    f"Allowed host is {current_host}."
                ),
            )

        return ValidationResult(
            status=ValidationStatus.APPROVED,
            reason=f"Navigation remains inside allowed host {current_host}.",
        )

    # =====================================================
    # DUPLICATE DETECTION
    # =====================================================

    def _check_duplicate(
        self,
        action: BrowserAction,
        previous_actions: list[BrowserAction],
    ) -> ValidationResult | None:

        if not previous_actions:
            return None

        previous = previous_actions[-1]

        same_action = (
            previous.action == action.action
            and previous.target_ref == action.target_ref
            and previous.value == action.value
            and previous.url == action.url
        )

        if same_action:
            return ValidationResult(
                status=ValidationStatus.REJECTED,
                reason="The exact same action was proposed twice consecutively.",
            )

        return None

    # =====================================================
    # HELPERS
    # =====================================================

    def _normalize_text(self, text: str) -> str:
        return " ".join(text.casefold().split())

    def _digits_only(self, text: str) -> str:
        return "".join(character for character in text if character.isdigit())