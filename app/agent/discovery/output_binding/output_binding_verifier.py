from dataclasses import dataclass

from app.agent.discovery.output_binding.output_binding_llm import (
    OutputBindingProposal,
)
from app.agent.discovery.output_binding.output_locator import (
    OutputStructuralContext,
)


@dataclass
class OutputBindingVerificationResult:
    valid: bool
    reason: str
    resolved_value: str | None = None


class OutputBindingVerifier:

    def verify(
        self,
        context: OutputStructuralContext,
        proposal: OutputBindingProposal,
        page,
    ) -> OutputBindingVerificationResult:

        # -------------------------------------------------
        # 1. VERIFY OUTPUT IDENTITY
        # -------------------------------------------------

        if proposal.output_name != context.output_name:
            return OutputBindingVerificationResult(
                valid=False,
                reason=(
                    f"Output name mismatch. Expected "
                    f"'{context.output_name}', got "
                    f"'{proposal.output_name}'."
                ),
            )

        binding = proposal.binding

        if binding.kind != "table":
            return OutputBindingVerificationResult(
                valid=False,
                reason=(
                    f"Unsupported binding kind: "
                    f"'{binding.kind}'."
                ),
            )

        if context.structure != "table":
            return OutputBindingVerificationResult(
                valid=False,
                reason=(
                    "Table binding proposed for a "
                    "non-table output."
                ),
            )


        # -------------------------------------------------
        # 2. VERIFY PROPOSED VALUES CAME FROM
        #    THE COLLECTED STRUCTURE
        # -------------------------------------------------

        headers = context.headers or []
        row = context.containing_row or []

        row_match_column = binding.row_match.column
        row_match_value = binding.row_match.value
        value_column = binding.value_column

        if row_match_column not in headers:
            return OutputBindingVerificationResult(
                valid=False,
                reason=(
                    f"Row-match column "
                    f"'{row_match_column}' does not exist "
                    f"in the verified table headers."
                ),
            )

        if value_column not in headers:
            return OutputBindingVerificationResult(
                valid=False,
                reason=(
                    f"Value column '{value_column}' "
                    f"does not exist in the verified "
                    f"table headers."
                ),
            )

        row_match_index = headers.index(
            row_match_column
        )

        value_column_index = headers.index(
            value_column
        )

        if row_match_index >= len(row):
            return OutputBindingVerificationResult(
                valid=False,
                reason=(
                    "Row-match column does not map to "
                    "a value in the discovered row."
                ),
            )

        if value_column_index >= len(row):
            return OutputBindingVerificationResult(
                valid=False,
                reason=(
                    "Value column does not map to "
                    "a value in the discovered row."
                ),
            )

        if row[row_match_index] != row_match_value:
            return OutputBindingVerificationResult(
                valid=False,
                reason=(
                    f"Proposed row-match value "
                    f"'{row_match_value}' is not under "
                    f"column '{row_match_column}' in "
                    f"the discovered row."
                ),
            )

        if value_column != context.output_column:
            return OutputBindingVerificationResult(
                valid=False,
                reason=(
                    f"Proposed value column "
                    f"'{value_column}' does not match "
                    f"the verified output column "
                    f"'{context.output_column}'."
                ),
            )


        # -------------------------------------------------
        # 3. EXECUTE THE PROPOSED RULE AGAINST
        #    THE LIVE DOM
        # -------------------------------------------------

        extraction_result = page.evaluate(
            """
            (args) => {

                function normalize(value) {
                    return (value || "")
                        .replace(/\\s+/g, " ")
                        .trim();
                }

                const tables = Array.from(
                    document.querySelectorAll(
                        "table, [role='table'], [role='grid']"
                    )
                );

                const matches = [];

                for (const table of tables) {

                    let headerElements = Array.from(
                        table.querySelectorAll(
                            "thead th, [role='columnheader']"
                        )
                    );

                    if (headerElements.length === 0) {
                        const firstRow =
                            table.querySelector("tr");

                        if (firstRow) {
                            headerElements = Array.from(
                                firstRow.querySelectorAll(
                                    "th, td"
                                )
                            );
                        }
                    }

                    const headers = headerElements.map(
                        (header) =>
                            normalize(header.textContent)
                    );

                    const rowMatchIndex =
                        headers.indexOf(
                            args.row_match_column
                        );

                    const valueColumnIndex =
                        headers.indexOf(
                            args.value_column
                        );

                    if (
                        rowMatchIndex === -1 ||
                        valueColumnIndex === -1
                    ) {
                        continue;
                    }

                    const rows = Array.from(
                        table.querySelectorAll(
                            "tbody tr, [role='row']"
                        )
                    );

                    for (const row of rows) {
                        const cells = Array.from(
                            row.querySelectorAll(
                                [
                                    "td",
                                    "th",
                                    "[role='cell']",
                                    "[role='gridcell']"
                                ].join(",")
                            )
                        );

                        if (
                            rowMatchIndex >= cells.length ||
                            valueColumnIndex >= cells.length
                        ) {
                            continue;
                        }

                        const candidateValue = normalize(
                            cells[
                                rowMatchIndex
                            ].textContent
                        );

                        if (
                            candidateValue ===
                            normalize(
                                args.row_match_value
                            )
                        ) {
                            matches.push(
                                normalize(
                                    cells[
                                        valueColumnIndex
                                    ].textContent
                                )
                            );
                        }
                    }
                }

                return matches;
            }
            """,
            {
                "row_match_column":
                    row_match_column,

                "row_match_value":
                    row_match_value,

                "value_column":
                    value_column,
            },
        )


        # -------------------------------------------------
        # 4. REQUIRE EXACTLY ONE MATCH
        # -------------------------------------------------

        if len(extraction_result) == 0:
            return OutputBindingVerificationResult(
                valid=False,
                reason=(
                    "Proposed binding did not resolve "
                    "to any value in the live DOM."
                ),
            )

        if len(extraction_result) > 1:
            return OutputBindingVerificationResult(
                valid=False,
                reason=(
                    "Proposed binding is ambiguous. "
                    f"It resolved to "
                    f"{len(extraction_result)} values."
                ),
            )

        resolved_value = extraction_result[0]


        # -------------------------------------------------
        # 5. MOST IMPORTANT CHECK:
        #    DOES THE RULE RESOLVE TO THE KNOWN
        #    DISCOVERY OUTPUT?
        # -------------------------------------------------

        if resolved_value != context.observed_value:
            return OutputBindingVerificationResult(
                valid=False,
                reason=(
                    f"Binding resolved to "
                    f"'{resolved_value}', but the "
                    f"verified discovery output was "
                    f"'{context.observed_value}'."
                ),
                resolved_value=resolved_value,
            )

        return OutputBindingVerificationResult(
            valid=True,
            reason=(
                "Proposed output binding is grounded "
                "in the DOM and resolves exactly to "
                "the verified discovery output."
            ),
            resolved_value=resolved_value,
        )