import hashlib
import re


def normalize_observation(observation: str) -> str:
    """
    Normalize a browser observation before generating a state fingerprint.

    Playwright accessibility refs are temporary identifiers used for
    interacting with elements in the current observation. They may change
    when the same logical page is revisited, so they should not contribute
    to browser-state identity.
    """

    # Remove transient Playwright element references.
    #
    # Examples:
    # [ref=e14]
    # [ref=f2e14]
    # [ref=f10e51]
    normalized = re.sub(
        r"\s*\[ref=[^\]]+\]",
        "",
        observation,
    )

    # Normalize whitespace.
    normalized = re.sub(
        r"\s+",
        " ",
        normalized,
    )

    return normalized.strip()


def build_state_fingerprint(
    url: str,
    observation: str,
) -> str:
    """
    Generate a deterministic fingerprint representing a browser state.

    Two states with the same URL and normalized observation will produce
    the same fingerprint.
    """
    normalized_observation = normalize_observation(observation)

    state_content = f"{url}|{normalized_observation}"

    return hashlib.sha256(
        state_content.encode("utf-8")
    ).hexdigest()