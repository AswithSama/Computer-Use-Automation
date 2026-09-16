from enum import Enum

from pydantic import BaseModel, ConfigDict


class ActionType(str, Enum):
    CLICK = "click"
    FILL = "fill"
    GO_BACK = "go_back"
    NAVIGATE = "navigate"
    WAIT = "wait"
    FINISH = "finish"
    REQUEST_VISUAL = "request_visual"
    REQUEST_HUMAN = "request_human"


class BrowserAction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: ActionType

    # Reference from the Playwright AI snapshot.
    target_ref: str | None = None

    # Semantic locator used by Playwright.
    target_role: str | None = None
    target_name: str | None = None

    # Used for fill actions.
    value: str | None = None

    # Used for navigation.
    url: str | None = None

    # Used when action == finish.
    result: str | None = None

    reason: str