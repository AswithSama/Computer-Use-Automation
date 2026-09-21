from dataclasses import dataclass

from app.agent.schemas.discovery import DiscoveredOutput


@dataclass
class GroundedOutputEvidence:
    output_name: str
    output_type: str
    observed_value: str
    matching_lines: list[str]


@dataclass
class TableStructureEvidence:
    headers: list[str]
    matching_row: list[str]
    output_column: str


class OutputGrounder:

    def ground(
        self,
        output: DiscoveredOutput,
        observation: str,
    ) -> GroundedOutputEvidence:

        matching_lines = [
            line.strip()
            for line in observation.splitlines()
            if output.value in line
        ]

        if not matching_lines:
            raise ValueError(
                f"Output '{output.name}' with value "
                f"'{output.value}' is not grounded in "
                f"the final page observation."
            )

        return GroundedOutputEvidence(
            output_name=output.name,
            output_type=output.type,
            observed_value=output.value,
            matching_lines=matching_lines,
        )

    def collect_structure(
        self,
        output: DiscoveredOutput,
        page,
    ) -> TableStructureEvidence | None:

        # For the MVP, table structure is the first
        # supported output-binding structure.
        table_evidence = self._collect_table_structure(
            output=output,
            page=page,
        )

        if table_evidence is not None:
            return table_evidence

        # Other structure strategies can be added here later.
        return None

    def _collect_table_structure(
        self,
        output: DiscoveredOutput,
        page,
    ) -> TableStructureEvidence | None:

        tables = page.get_by_role("table")

        for table_index in range(tables.count()):
            table = tables.nth(table_index)

            headers = [
                header.inner_text().strip()
                for header in table.get_by_role("columnheader").all()
            ]

            rows = table.get_by_role("row")

            for row_index in range(rows.count()):
                row = rows.nth(row_index)

                cells = [
                    cell.inner_text().strip()
                    for cell in row.get_by_role("cell").all()
                ]

                if not cells:
                    continue

                matching_indexes = [
                    index
                    for index, value in enumerate(cells)
                    if value == output.value
                ]

                if not matching_indexes:
                    continue

                if len(matching_indexes) > 1:
                    raise ValueError(
                        f"Output '{output.name}' appears multiple times "
                        f"in the same table row."
                    )

                output_index = matching_indexes[0]

                if output_index >= len(headers):
                    raise ValueError(
                        f"Could not map output '{output.name}' "
                        f"to a table column."
                    )

                return TableStructureEvidence(
                    headers=headers,
                    matching_row=cells,
                    output_column=headers[output_index],
                )

        return None