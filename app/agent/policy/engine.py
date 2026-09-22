"""Shared, deterministic allowlist policy engine."""

from fnmatch import fnmatchcase
from urllib.parse import unquote, urljoin, urlsplit

from app.agent.policy.models import (
    AllowlistConfig,
    PolicyDecision,
    PolicyProfile,
    PolicyResult,
    TargetRule,
)
from app.agent.schemas.discovery import ActionType


class PolicyEngine:
    def __init__(self, config: AllowlistConfig):
        self.config = config

        # Store the configuration independently of the caller.
        self._config = config.model_copy(deep=True)

        self._allowed_origins = frozenset(
            self._parse_origin(origin)
            for origin in self._config.allowed_origins
        )

    @staticmethod
    def _result(
        decision: PolicyDecision,
        code: str,
        reason: str,
    ) -> PolicyResult:
        return PolicyResult(
            decision=decision,
            code=code,
            reason=reason,
        )

    @staticmethod
    def _parse_origin(url: str) -> tuple[str, str, int]:
        parsed = urlsplit(url)

        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
        ):
            raise ValueError("Invalid application origin.")

        port = parsed.port

        if port is None:
            port = 443 if parsed.scheme == "https" else 80

        return (
            parsed.scheme.lower(),
            parsed.hostname.lower(),
            port,
        )

    @staticmethod
    def _matches_route(
        path: str,
        patterns: list[str],
    ) -> bool:
        return any(
            fnmatchcase(path, pattern)
            for pattern in patterns
        )

    @staticmethod
    def _matches_target(
        *,
        rules: list[TargetRule],
        action: ActionType,
        role: str | None,
        name: str | None,
        path: str,
    ) -> bool:
        if not role or not name:
            return False

        normalized_role = role.strip().casefold()
        normalized_name = name.strip().casefold()

        for rule in rules:
            if rule.action != action:
                continue

            if rule.role.strip().casefold() != normalized_role:
                continue

            if rule.name.strip().casefold() != normalized_name:
                continue

            if (
                rule.route_pattern is not None
                and not fnmatchcase(path, rule.route_pattern)
            ):
                continue

            return True

        return False

    def _get_profile(
        self,
        profile_id: str | None,
    ) -> PolicyProfile | None:
        if profile_id is None:
            return None

        return self._config.profiles.get(profile_id)

    def _check_scope(
        self,
        url: str,
        profile: PolicyProfile | None,
    ) -> PolicyResult:
        try:
            parsed = urlsplit(url)

            origin = self._parse_origin(url)

            # Conservative for this demo: reject encoded paths rather
            # than risk interpreting an encoded route differently.
            if unquote(parsed.path) != parsed.path:
                return self._result(
                    PolicyDecision.BLOCKED,
                    "encoded_route_not_allowed",
                    "Encoded routes are not permitted.",
                )

            path = parsed.path or "/"

        except ValueError:
            return self._result(
                PolicyDecision.BLOCKED,
                "invalid_url",
                "The application URL is invalid.",
            )

        if origin not in self._allowed_origins:
            return self._result(
                PolicyDecision.BLOCKED,
                "origin_not_allowed",
                "The application origin is not permitted.",
            )

        if self._matches_route(
            path,
            self._config.blocked_routes,
        ):
            return self._result(
                PolicyDecision.BLOCKED,
                "route_blocked",
                "The route is explicitly prohibited.",
            )

        if profile is not None and self._matches_route(
            path,
            profile.blocked_routes,
        ):
            return self._result(
                PolicyDecision.BLOCKED,
                "route_blocked",
                "The route is prohibited by the selected profile.",
            )

        if not self._matches_route(
            path,
            self._config.allowed_routes,
        ):
            return self._result(
                PolicyDecision.BLOCKED,
                "route_not_allowed",
                "The route is outside the application allowlist.",
            )

        if profile is not None and not self._matches_route(
            path,
            profile.allowed_routes,
        ):
            return self._result(
                PolicyDecision.BLOCKED,
                "route_not_allowed",
                "The route is outside the selected profile.",
            )

        return self._result(
            PolicyDecision.ALLOWED,
            "scope_allowed",
            "The application origin and route are permitted.",
        )

    def check_scope(
        self,
        *,
        current_url: str,
        profile_id: str | None = None,
    ) -> PolicyResult:
        """
        Check the browser's current application location.

        This can also be used after navigation, redirects, or
        human handoff before automation performs another action.
        """
        profile = self._get_profile(profile_id)

        if self._config.profiles and profile is None:
            return self._result(
                PolicyDecision.BLOCKED,
                "profile_not_allowed",
                "An approved policy profile is required.",
            )

        return self._check_scope(current_url, profile)

    def check(
        self,
        *,
        action: ActionType,
        current_url: str,
        profile_id: str | None = None,
        target_role: str | None = None,
        target_name: str | None = None,
        destination_url: str | None = None,
    ) -> PolicyResult:
        """
        Evaluate one proposed or recorded browser action.

        A capability profile can restrict application permissions,
        but it cannot grant permissions beyond the global policy.
        """
        profile = self._get_profile(profile_id)

        if self._config.profiles and profile is None:
            return self._result(
                PolicyDecision.BLOCKED,
                "profile_not_allowed",
                "An approved policy profile is required.",
            )

        current_scope = self._check_scope(
            current_url,
            profile,
        )

        if current_scope.decision == PolicyDecision.BLOCKED:
            return current_scope

        if (
            action in self._config.blocked_actions
            or (
                profile is not None
                and action in profile.blocked_actions
            )
        ):
            return self._result(
                PolicyDecision.BLOCKED,
                "action_blocked",
                "The action type is explicitly prohibited.",
            )

        if (
            action not in self._config.allowed_actions
            or (
                profile is not None
                and action not in profile.allowed_actions
            )
        ):
            return self._result(
                PolicyDecision.BLOCKED,
                "action_not_allowed",
                "The action type is not permitted.",
            )

        # Explicit navigation must be checked against the destination,
        # not just the page from which navigation begins.
        if action == ActionType.NAVIGATE:
            if not destination_url:
                return self._result(
                    PolicyDecision.BLOCKED,
                    "missing_navigation_destination",
                    "Navigation requires a destination.",
                )

            destination = urljoin(
                current_url,
                destination_url,
            )

            destination_scope = self._check_scope(
                destination,
                profile,
            )

            if destination_scope.decision == PolicyDecision.BLOCKED:
                return destination_scope

        path = urlsplit(current_url).path or "/"

        blocked_targets = [
            *self._config.blocked_targets,
            *(
                profile.blocked_targets
                if profile is not None
                else []
            ),
        ]

        if self._matches_target(
            rules=blocked_targets,
            action=action,
            role=target_role,
            name=target_name,
            path=path,
        ):
            return self._result(
                PolicyDecision.BLOCKED,
                "target_blocked",
                "The requested control is prohibited.",
            )

        confirmation_targets = [
            *self._config.confirmation_targets,
            *(
                profile.confirmation_targets
                if profile is not None
                else []
            ),
        ]

        if self._matches_target(
            rules=confirmation_targets,
            action=action,
            role=target_role,
            name=target_name,
            path=path,
        ):
            return self._result(
                PolicyDecision.NEEDS_CONFIRMATION,
                "confirmation_required",
                "The requested operation requires explicit authorization.",
            )

        return self._result(
            PolicyDecision.ALLOWED,
            "action_allowed",
            "The action is permitted by the selected policy.",
        )