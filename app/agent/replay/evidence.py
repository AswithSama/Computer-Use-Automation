import json
from datetime import datetime, timezone
from pathlib import Path

from app.agent.replay.models import ReplayResult


FAILURE_SUMMARIES = {
    "missing_required_inputs": "Required replay inputs were not supplied.",
    "invalid_checkpoint_reference": "A checkpoint references an invalid action index.",
    "parameter_resolution_error": "An action references an unavailable input.",
    "target_not_found": "The target was absent or matched more than one element.",
    "target_not_interactable": "The target could not be interacted with.",
    "timeout": "Action execution timed out; its effect may be uncertain.",
    "execution_error": "An error occurred during action execution.",
    "checkpoint_validation_error": "Checkpoint evaluation raised an error.",
    "checkpoint_failed": "The expected application state was not verified.",
    "duplicate_output_name": "The artifact declares duplicate output names.",
    "unsupported_output_binding": "An output binding is unsupported.",
    "output_extraction_error": "Output extraction raised an error.",
    "output_not_found": "An output binding returned zero matches.",
    "ambiguous_output": "An output binding returned multiple matches.",
}


class ReplayEvidenceRecorder:
    """Saves replay failure evidence in the existing evidence folder."""

    def __init__(self, evidence_dir: str = "evidence"):
        self.evidence_dir = Path(evidence_dir)

    def record(
        self,
        result: ReplayResult,
        page=None,
        phase: str = "unknown",
    ) -> list[str]:
        try:
            return self._record(result, page, phase)
        except Exception:
            print(
                "[REPLAY] Evidence could not be saved. "
                "The original replay failure is preserved."
            )
            return []

    def _record(
        self,
        result: ReplayResult,
        page,
        phase: str,
    ) -> list[str]:
        now = datetime.now(timezone.utc)
        timestamp = now.strftime("%Y%m%d_%H%M%S_%f")

        directory = self.evidence_dir.resolve()
        directory.mkdir(parents=True, exist_ok=True)

        report_path = directory / f"replay_failure_{timestamp}.json"
        snapshot_path = directory / f"replay_{timestamp}.json"

        refs: list[str] = []
        snapshot_status = "not_requested"

        if page is not None:
            try:
                snapshot = self._capture_structure(page)
                self._write_json(snapshot_path, snapshot)

                refs.append(str(snapshot_path))
                snapshot_status = "saved"
            except Exception:
                snapshot_status = "unavailable"

        known_code = result.error_code in FAILURE_SUMMARIES

        report = {
            "schema_version": "1.0",
            "timestamp_utc": now.isoformat(),
            "status": result.status.value,
            "failure_category": (
                result.failure_category.value
                if result.failure_category is not None
                else None
            ),
            "error_code": (
                result.error_code if known_code else "unknown"
            ),
            "reason": FAILURE_SUMMARIES.get(
                result.error_code,
                "An unclassified replay failure occurred.",
            ),
            "phase": (
                phase
                if phase in {
                    "preflight",
                    "parameters",
                    "action",
                    "checkpoint",
                    "output",
                }
                else "unknown"
            ),
            "failed_step": result.failed_step,
            "completed_steps": result.completed_steps,
            "snapshot_status": snapshot_status,
            "snapshot_file": (
                snapshot_path.name
                if snapshot_status == "saved"
                else None
            ),
            "handling": (
                "Replay stopped; no retry or human handoff performed."
            ),
            "snapshot_scope": (
                "Main-document DOM structure only; no page text, names, "
                "field values, URLs, or arbitrary attributes. "
                "Iframe and shadow-root contents are not captured."
            ),
        }

        try:
            self._write_json(report_path, report)
        except Exception:
            print(
                "[REPLAY] Failure report could not be saved. "
                "The original replay failure is preserved."
            )
            return refs

        print(f"[REPLAY] Failure report saved: {report_path}")

        return [str(report_path), *refs]

    @staticmethod
    def _write_json(path: Path, payload: dict) -> None:
        # Serialize before opening the file to avoid writing invalid JSON.
        content = json.dumps(
            payload,
            indent=2,
            ensure_ascii=False,
        )

        # Avoid overwriting another capture if timestamps ever collide.
        with path.open("x", encoding="utf-8") as stream:
            stream.write(content + "\n")

    @staticmethod
    def _capture_structure(page) -> dict:
        # Save structure and selected states without page text or values.
        return page.evaluate(
            """() => {
                const tags = new Set([
                    'html', 'body', 'main', 'nav', 'header', 'footer',
                    'section', 'article', 'aside', 'div', 'span', 'p',
                    'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'form', 'label',
                    'input', 'button', 'select', 'option', 'textarea',
                    'a', 'table', 'thead', 'tbody', 'tfoot', 'tr', 'th',
                    'td', 'ul', 'ol', 'li', 'dialog', 'iframe', 'img',
                    'canvas', 'svg', 'details', 'summary', 'fieldset'
                ]);

                const roles = new Set([
                    'alert', 'alertdialog', 'dialog', 'button', 'link',
                    'textbox', 'checkbox', 'radio', 'combobox', 'listbox',
                    'option', 'table', 'grid', 'row', 'cell', 'gridcell',
                    'columnheader', 'rowheader', 'heading', 'status',
                    'progressbar', 'navigation', 'main', 'form', 'region'
                ]);

                const states = new Set(['true', 'false', 'mixed']);
                const nodes = [];
                const limit = 2000;
                let truncated = false;

                function visit(element, parent) {
                    if (nodes.length >= limit) {
                        truncated = true;
                        return;
                    }

                    const tag = element.tagName.toLowerCase();

                    if (
                        ['script', 'style', 'noscript', 'template']
                            .includes(tag)
                    ) {
                        return;
                    }

                    const role = element.getAttribute('role');
                    const rect = element.getBoundingClientRect();
                    const style = getComputedStyle(element);

                    const node = {
                        index: nodes.length,
                        parent,
                        tag: tags.has(tag) ? tag : 'other',
                        role: roles.has(role) ? role : null,
                        visible: (
                            rect.width > 0 &&
                            rect.height > 0 &&
                            style.visibility !== 'hidden' &&
                            style.visibility !== 'collapse' &&
                            style.display !== 'none'
                        ),
                        disabled: (
                            element.matches(':disabled') ||
                            element.getAttribute('aria-disabled') === 'true'
                        )
                    };

                    for (
                        const attr of [
                            'aria-busy',
                            'aria-invalid',
                            'aria-expanded'
                        ]
                    ) {
                        const value = element.getAttribute(attr);

                        if (states.has(value)) {
                            node[attr] = value;
                        }
                    }

                    nodes.push(node);

                    for (const child of element.children) {
                        visit(child, node.index);

                        if (nodes.length >= limit) {
                            truncated = true;
                            break;
                        }
                    }
                }

                if (document.body) {
                    visit(document.body, null);
                }

                return {
                    ready_state: document.readyState,
                    node_limit: limit,
                    truncated,
                    nodes
                };
            }""",
        )