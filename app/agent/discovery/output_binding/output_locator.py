from dataclasses import dataclass

from app.agent.schemas.discovery import DiscoveredOutput


@dataclass
class OutputStructuralContext:
    """
    Deterministically collected DOM evidence surrounding
    a discovered output.

    This does NOT decide the reusable extraction rule.
    That responsibility belongs to the Output Binding LLM.
    """

    output_name: str
    output_type: str
    observed_value: str

    structure: str

    # Generic DOM information.
    tag_name: str
    selector: str | None

    # Table-specific structural evidence.
    headers: list[str] | None = None
    containing_row: list[str] | None = None
    output_column: str | None = None


class OutputLocatorBuilder:

    def locate(
        self,
        output: DiscoveredOutput,
        page,
    ) -> OutputStructuralContext:

        result = page.evaluate(
            """
            (outputValue) => {

                function normalize(value) {
                    return (value || "")
                        .replace(/\\s+/g, " ")
                        .trim();
                }


                // -------------------------------------------------
                // 1. FIND THE EXACT OUTPUT VALUE IN THE DOM
                // -------------------------------------------------

                const elements = Array.from(
                    document.querySelectorAll("body *")
                );

                const matches = elements.filter((element) => {
                    const text = normalize(element.textContent);

                    if (text !== normalize(outputValue)) {
                        return false;
                    }

                    // Prefer the deepest element containing
                    // exactly the output value.
                    const childHasSameValue = Array.from(
                        element.children
                    ).some(
                        (child) =>
                            normalize(child.textContent) ===
                            normalize(outputValue)
                    );

                    return !childHasSameValue;
                });

                if (matches.length === 0) {
                    return null;
                }

                // If the value appears in a profile field and a table,
                // prefer the table representation for table-only binding.
                // The subsequent verifier still requires a unique match.
                const tableMatches = matches.filter((element) => {
                    return Boolean(element.closest(
                        "td, th, [role='cell'], [role='gridcell']"
                    ));
                });
                const target = (tableMatches.length ? tableMatches : matches)[0];


                // -------------------------------------------------
                // 2. BUILD GENERIC DOM SELECTOR
                // -------------------------------------------------
                //
                // We keep this as structural evidence / fallback.
                // It is NOT automatically considered the reusable
                // output binding.
                // -------------------------------------------------

                function buildSelector(element) {
                    const parts = [];

                    let current = element;

                    while (
                        current &&
                        current.nodeType === Node.ELEMENT_NODE &&
                        current.tagName.toLowerCase() !== "html"
                    ) {
                        const tag =
                            current.tagName.toLowerCase();

                        let part = tag;

                        const parent = current.parentElement;

                        if (parent) {
                            const sameTagSiblings =
                                Array.from(parent.children).filter(
                                    (child) =>
                                        child.tagName ===
                                        current.tagName
                                );

                            if (sameTagSiblings.length > 1) {
                                const index =
                                    sameTagSiblings.indexOf(current) + 1;

                                part +=
                                    `:nth-of-type(${index})`;
                            }
                        }

                        parts.unshift(part);
                        current = parent;
                    }

                    return parts.join(" > ");
                }

                const selector = buildSelector(target);


                // -------------------------------------------------
                // 3. DETECT WHETHER OUTPUT BELONGS TO A TABLE
                // -------------------------------------------------

                const cell = target.closest(
                    [
                        "td",
                        "th",
                        "[role='cell']",
                        "[role='gridcell']"
                    ].join(",")
                );

                const row = cell
                    ? cell.closest("tr, [role='row']")
                    : null;

                const table = row
                    ? row.closest(
                        "table, [role='table'], [role='grid']"
                    )
                    : null;


                // -------------------------------------------------
                // 4. COLLECT TABLE STRUCTURE
                // -------------------------------------------------

                if (cell && row && table) {

                    let headerElements = Array.from(
                        table.querySelectorAll(
                            "thead th, [role='columnheader']"
                        )
                    );

                    // Fallback for basic tables without <thead>.
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


                    // ---------------------------------------------
                    // Read the row containing the output.
                    // ---------------------------------------------

                    const rowCells = Array.from(
                        row.querySelectorAll(
                            [
                                "td",
                                "th",
                                "[role='cell']",
                                "[role='gridcell']"
                            ].join(",")
                        )
                    );

                    const containingRow = rowCells.map(
                        (rowCell) =>
                            normalize(rowCell.textContent)
                    );


                    // ---------------------------------------------
                    // Determine which column physically contains
                    // the known output value.
                    //
                    // This is deterministic DOM evidence.
                    // ---------------------------------------------

                    const outputCellIndex =
                        rowCells.indexOf(cell);

                    let outputColumn = null;

                    if (
                        outputCellIndex >= 0 &&
                        outputCellIndex < headers.length
                    ) {
                        outputColumn =
                            headers[outputCellIndex];
                    }


                    return {
                        structure: "table",

                        tag_name:
                            target.tagName.toLowerCase(),

                        selector: selector,

                        headers: headers,

                        containing_row: containingRow,

                        output_column: outputColumn
                    };
                }


                // -------------------------------------------------
                // 5. GENERIC NON-TABLE STRUCTURE
                // -------------------------------------------------
                //
                // For now we simply return the exact target and
                // selector. Later we can collect richer local DOM
                // context for non-table outputs.
                // -------------------------------------------------

                return {
                    structure: "dom",

                    tag_name:
                        target.tagName.toLowerCase(),

                    selector: selector,

                    headers: null,
                    containing_row: null,
                    output_column: null
                };
            }
            """,
            output.value,
        )

        if result is None:
            raise ValueError(
                f"Could not locate DOM structure for output "
                f"'{output.name}' with value "
                f"'{output.value}'."
            )

        return OutputStructuralContext(
            output_name=output.name,
            output_type=output.type,
            observed_value=output.value,
            structure=result["structure"],
            tag_name=result["tag_name"],
            selector=result["selector"],
            headers=result["headers"],
            containing_row=result["containing_row"],
            output_column=result["output_column"],
        )