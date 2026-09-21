from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class BusinessOutcomeRule:
    after_action: int
    code: str
    reason: str
    url_pattern: str

    kind: Literal["visible_text", "table_row_absent"] = "visible_text"

    # Used for visible_text rules.
    visible_text: str | None = None

    # Used for table_row_absent rules.
    row_match_column: str | None = None
    row_match_value: str | None = None
    required_column: str | None = None

