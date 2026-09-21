from dataclasses import dataclass
from typing import Literal
from urllib.parse import urlparse


# Data lives in schemas so registry/capability can use it
# without importing the replay package.
from app.agent.schemas.outcomes import BusinessOutcomeRule  # noqa: F401

class BusinessOutcomeDetector:

    @staticmethod
    def _resolve(value: str, inputs: dict[str, str]) -> str:
        for name, input_value in inputs.items():
            value = value.replace(
                f"{{{{{name}}}}}",
                input_value,
            )
        return value

    @staticmethod
    def _normalize(value: str) -> str:
        return " ".join(value.split())

    def _table_row_absent(
        self,
        page,
        rule: BusinessOutcomeRule,
    ) -> bool:

        if not all((
            rule.row_match_column,
            rule.row_match_value,
            rule.required_column,
        )):
            return False

        matching_tables = []

        for table in page.locator("table").all():
            if not table.is_visible():
                continue

            headers = [
                self._normalize(text)
                for text in table.locator(
                    "thead th"
                ).all_text_contents()
            ]

            if (
                rule.row_match_column in headers
                and rule.required_column in headers
            ):
                matching_tables.append((table, headers))

        # Do not infer account absence if the expected table
        # is missing or ambiguous.
        if len(matching_tables) != 1:
            return False

        table, headers = matching_tables[0]
        type_index = headers.index(rule.row_match_column)

        rows = table.locator("tbody tr")

        # For this initial implementation, require at least
        # one account row before concluding Savings is absent.
        if rows.count() == 0:
            return False

        for row in rows.all():
            cells = [
                self._normalize(text)
                for text in row.locator(
                    "td, th"
                ).all_text_contents()
            ]

            if type_index >= len(cells):
                return False

            if cells[type_index] == rule.row_match_value:
                return False

        return True

    def detect(
        self,
        *,
        page,
        step: int,
        inputs: dict[str, str],
        rules: tuple[BusinessOutcomeRule, ...],
    ) -> BusinessOutcomeRule | None:

        current_url = urlparse(page.url)
        current_path = current_url.path

        if current_url.query:
            current_path += f"?{current_url.query}"

        for rule in rules:
            if rule.after_action != step:
                continue

            expected_url = self._resolve(
                rule.url_pattern,
                inputs,
            )

            if current_path != expected_url:
                continue

            if rule.kind == "visible_text":
                if rule.visible_text is None:
                    continue

                expected_text = self._resolve(
                    rule.visible_text,
                    inputs,
                )

                message = page.get_by_text(
                    expected_text,
                    exact=False,
                )

                if (
                    message.count() == 1
                    and message.is_visible()
                ):
                    return rule

            elif rule.kind == "table_row_absent":
                if self._table_row_absent(page, rule):
                    return rule

        return None