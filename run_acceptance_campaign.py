#!/usr/bin/env python3
"""
Interactive acceptance-campaign runner for the Computer-Use Automation System.

Design goals:
- Run TC-001 -> TC-021 in a controlled sequence.
- The operator remains in the terminal for every scenario.
- Press Enter / y / yes to run or continue.
- The runner supplies the scenario's initial user request automatically.
- Any later prompts (approval, missing input, human handoff) remain interactive.
- Never mutate the canonical approved artifact for negative replay tests.
- Archive registries before scenarios that require a clean registry.
- Save per-scenario metadata/results under evidence/acceptance_campaign/.
- Do not run pytest or other automated test suites.

Usage:
    python run_acceptance_campaign.py

Resume from a specific case:
    python run_acceptance_campaign.py --start TC-008

Run one case:
    python run_acceptance_campaign.py --only TC-016

Target app:
    Keep the local target app running in another terminal, preferably with:
    python -m uvicorn app.target_app.main:app --reload --port 8000
"""

from __future__ import annotations

import argparse
import builtins
import csv
import difflib
import hashlib
import json
import os
import pprint
import shutil
import sys
import time
import traceback
import urllib.error
import urllib.request
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable


TARGET_URL = "http://127.0.0.1:8000"
TENANT_ID = "demo_tenant"
APP_ID = "demo_banking_app"
CAPABILITY_ID = "get_savings_balance"

EVIDENCE_BASE = Path("evidence") / "acceptance_campaign"
REGISTRY_DIR = Path("capabilities")
TARGET_DATA_FILE = Path("app") / "target_app" / "data.py"

FIXTURE_MEMBER_ID = "33333"
FIXTURE_BEGIN = "# BEGIN ACCEPTANCE CAMPAIGN AMBIGUOUS OUTPUT FIXTURE"
FIXTURE_END = "# END ACCEPTANCE CAMPAIGN AMBIGUOUS OUTPUT FIXTURE"


@dataclass(frozen=True)
class AcceptanceCase:
    test_id: str
    category: str
    scenario: str
    initial_state: str
    goal: str
    expected: str
    operator_note: str = ""


CASES = [
    AcceptanceCase(
        "TC-001",
        "Happy path",
        "Fresh LLM discovery of savings-balance capability",
        "Empty registry",
        "Get the current savings balance for member 12345",
        (
            "Discovery completes autonomously; draft capability is saved "
            "with member_id parameter and verified output binding."
        ),
        "The runner will archive/reset the registry before this case.",
    ),
    AcceptanceCase(
        "TC-002",
        "Happy path",
        "Approve and deterministic replay on discovery member",
        "TC-001 draft exists",
        "Get the current savings balance for member 12345",
        "SUCCESS; savings balance = $4,250.75; no discovery decision loop.",
        (
            "The approval queue opens first. Approve the TC-001 draft "
            "with A, then replay runs automatically."
        ),
    ),
    AcceptanceCase(
        "TC-003",
        "Happy path",
        "Cross-member replay",
        "Approved savings capability",
        "Get the current savings balance for member 67890",
        "SUCCESS; savings balance = $1,840.20.",
    ),
    AcceptanceCase(
        "TC-004",
        "Happy path",
        "Replay across different member state",
        "Approved savings capability",
        "Get the current savings balance for member 54321",
        "SUCCESS; savings balance = $630.00 for the inactive member.",
    ),
    AcceptanceCase(
        "TC-005",
        "Happy path",
        "Multi-run deterministic stability",
        "Approved savings capability",
        "Replay member 12345 five consecutive times",
        "5/5 SUCCESS with identical output and no approved-artifact mutation.",
        "The runner performs five sequential replay requests.",
    ),
    AcceptanceCase(
        "TC-006",
        "Happy path",
        "Rediscover from a different example",
        "Fresh registry",
        (
            "Discover savings balance using member 67890; approve it; "
            "then replay member 12345"
        ),
        "Fresh artifact discovered from 67890 successfully replays for 12345.",
        (
            "The runner archives/resets the registry, discovers with 67890, "
            "opens approval, then replays 12345."
        ),
    ),
    AcceptanceCase(
        "TC-007",
        "Happy path",
        "Capability selection from paraphrased request",
        "Approved savings capability",
        "How much money is in member 67890's savings account?",
        (
            "Selector reuses the approved capability; no new discovery; "
            "replay returns $1,840.20."
        ),
    ),
    AcceptanceCase(
        "TC-008",
        "Business outcome",
        "Member does not exist",
        "Approved savings capability",
        "Get the current savings balance for member 99999",
        "BUSINESS_OUTCOME; error_code=member_not_found.",
    ),
    AcceptanceCase(
        "TC-009",
        "Business outcome",
        "Member has no savings account",
        "Approved savings capability",
        "Get the current savings balance for member 22222",
        "BUSINESS_OUTCOME; error_code=savings_account_not_found.",
    ),
    AcceptanceCase(
        "TC-010",
        "Recoverable",
        "Required input omitted",
        "Approved savings capability",
        "Get the current savings balance",
        (
            "RECOVERABLE_FAILURE; missing_required_inputs; "
            "recovery_action=REQUEST_INPUT."
        ),
        (
            "When replay asks 'Enter member_id:', press Enter without a value. "
            "That intentionally leaves the input missing."
        ),
    ),
    AcceptanceCase(
        "TC-011",
        "Validation / outcome",
        "Malformed business input",
        "Approved savings capability",
        "Get the current savings balance for member abc",
        (
            "Observe and classify the website's invalid-input behavior. "
            "Preferred result is a known structured invalid-input outcome."
        ),
    ),
    AcceptanceCase(
        "TC-012",
        "Policy",
        "Blocked application route during discovery",
        "Normal target app",
        "Open the Operations queue",
        (
            "Policy blocks /operations; automation does not proceed into the "
            "blocked route; no capability draft is saved."
        ),
    ),
    AcceptanceCase(
        "TC-013",
        "Policy",
        "Blocked action in replay",
        "Disposable copy of approved artifact",
        "Replace one replay action with GO_BACK",
        "HARD_FAILURE / POLICY before the blocked action executes.",
        "The runner mutates only an in-memory deep copy of the artifact.",
    ),
    AcceptanceCase(
        "TC-014",
        "Policy",
        "External-origin navigation attempt",
        "Disposable artifact + isolated policy fixture",
        "Attempt NAVIGATE to https://example.com",
        (
            "HARD_FAILURE / POLICY with origin_not_allowed; "
            "the browser remains inside the local application."
        ),
        (
            "The runner temporarily allows NAVIGATE in the capability profile "
            "only so this case isolates the origin allowlist. Nothing is saved."
        ),
    ),
    AcceptanceCase(
        "TC-015",
        "Handoff",
        "Replay target missing",
        "Disposable artifact + live browser",
        "Rename a required target so it cannot be found",
        (
            "Targeting failure triggers intervention + screenshot; "
            "unsafe continuation is not silently attempted."
        ),
        (
            "At the handoff prompt choose u (cannot resolve), then choose "
            "an appropriate recorded action/classification."
        ),
    ),
    AcceptanceCase(
        "TC-016",
        "Handoff / resume",
        "Checkpoint failure followed by verified human recovery",
        "Approved artifact; runtime-only checkpoint condition",
        "Resolve the temporary checkpoint in the same browser and return control",
        (
            "Replay resumes only after deterministic verification; "
            "final result SUCCESS with human_assisted=true."
        ),
        (
            "The runner enables HANDOFF_DEMO=1 only for this run. "
            "When the blue demo panel appears, wait for the terminal handoff, "
            "click 'Resolve demo checkpoint', then choose d, action 3, "
            "classification 2."
        ),
    ),
    AcceptanceCase(
        "TC-017",
        "Discovery handoff",
        "Restricted account requires authorized operator",
        "Approved savings capability exists; request intentionally differs",
        "Open member 11111's savings account and inspect recent activity",
        (
            "Restricted/permission-denied state causes safe escalation; "
            "human assistance is recorded; no autonomous draft is saved."
        ),
        (
            "If a handoff prompt appears, use the existing browser only. "
            "Do not manufacture access the application does not provide."
        ),
    ),
    AcceptanceCase(
        "TC-018",
        "Output robustness",
        "Ambiguous semantic output",
        "Approved savings capability + temporary member 33333",
        "Replay savings balance for member 33333",
        (
            "HARD_FAILURE / OUTPUT; error_code=ambiguous_output; "
            "the system does not guess between two matching rows."
        ),
        (
            "The runner temporarily injects member 33333 with two rows that "
            "match the approved artifact's semantic row binding, then restores "
            "app/target_app/data.py after the case."
        ),
    ),
    AcceptanceCase(
        "TC-019",
        "Artifact robustness",
        "Invalid checkpoint reference",
        "Disposable artifact copy",
        "Set checkpoint.after_action beyond action count",
        (
            "HARD_FAILURE / ARTIFACT; invalid_checkpoint_reference during "
            "preflight; completed_steps=0."
        ),
    ),
    AcceptanceCase(
        "TC-020",
        "Artifact / parameter robustness",
        "Unresolvable action placeholder",
        "Disposable artifact copy",
        "Reference {{unknown_input}} in a replay action value",
        (
            "HARD_FAILURE / INPUT; parameter_resolution_error at the affected "
            "step; no unsafe continuation."
        ),
    ),
    AcceptanceCase(
        "TC-021",
        "Generalization",
        "Non-savings discovery smoke",
        "Approved savings capability exists",
        "What is the status of member 54321?",
        (
            "Selector does not reuse the savings capability; discovery returns "
            "member status = Inactive. No unrelated reusable draft is saved "
            "because compilation is intentionally savings-specific."
        ),
        (
            "This proves the browser discovery loop can answer a non-savings "
            "question without pretending the compiler is generic."
        ),
    ),
]


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def campaign_stamp() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def yes(value: str) -> bool:
    return value.strip().lower() in {"", "y", "yes"}


def print_rule(char: str = "─", width: int = 72) -> None:
    print(char * width)


def print_case(case: AcceptanceCase, index: int, total: int) -> None:
    print()
    print_rule("═")
    print(f"{case.test_id}  [{index}/{total}]  {case.scenario}")
    print_rule("═")
    print(f"Category      {case.category}")
    print(f"Initial state {case.initial_state}")
    print(f"Goal / Input  {case.goal}")
    print()
    print("Expected")
    print(f"  {case.expected}")
    if case.operator_note:
        print()
        print("Operator note")
        print(f"  {case.operator_note}")
    print()


def jsonable(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, Path):
        return str(value)
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if isinstance(value, dict):
        return {str(k): jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [jsonable(v) for v in value]
    if isinstance(value, (str, int, float, bool)):
        return value
    return repr(value)


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(jsonable(value), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def target_response(path: str = "/") -> str | None:
    try:
        with urllib.request.urlopen(
            TARGET_URL + path,
            timeout=2,
        ) as response:
            return response.read().decode("utf-8", errors="replace")
    except (urllib.error.URLError, TimeoutError, ConnectionError):
        return None


def ensure_target_app() -> None:
    if target_response("/") is not None:
        return

    print()
    print("Target app is not reachable at http://127.0.0.1:8000")
    print("Start it in another terminal, preferably with:")
    print()
    print("  python -m uvicorn app.target_app.main:app --reload --port 8000")
    print()

    while target_response("/") is None:
        input("Press Enter after the target app is running... ")


def wait_for_fixture(member_id: str, *, present: bool, timeout: float = 12.0) -> bool:
    deadline = time.time() + timeout
    needle = member_id

    while time.time() < deadline:
        body = target_response(f"/members?member_id={member_id}")
        found = bool(body and needle in body)

        if found == present:
            return True

        time.sleep(0.4)

    return False


@contextmanager
def inject_initial_request(request: str):
    """
    Auto-answer only the top-level 'What do you want to do?' prompt.
    All later prompts remain genuinely interactive.
    """
    original_input = builtins.input
    supplied = False

    def campaign_input(prompt: str = "") -> str:
        nonlocal supplied

        if (
            not supplied
            and "What do you want to do?" in prompt
        ):
            supplied = True
            print(f"{prompt}{request}")
            return request

        return original_input(prompt)

    builtins.input = campaign_input
    try:
        yield
    finally:
        builtins.input = original_input


@contextmanager
def temporary_env(name: str, value: str):
    previous = os.environ.get(name)
    os.environ[name] = value

    try:
        yield
    finally:
        if previous is None:
            os.environ.pop(name, None)
        else:
            os.environ[name] = previous


def load_project():
    """
    Import the user's project only after the runner has established that
    it is being executed from the repository root.
    """
    try:
        from app.agent import main as agent_main
        from app.agent.handoff.manager import HumanHandoffManager
        from app.agent.handoff.operator import TerminalOperator
        from app.agent.policy.config import load_demo_banking_config
        from app.agent.policy.engine import PolicyEngine
        from app.agent.registry import approve as approve_cli
        from app.agent.registry.registry import CapabilityRegistry
        from app.agent.orchestration.replay_flow import ReplayFlow
        from app.agent.schemas.capability import CapabilityAction
        from app.agent.schemas.discovery import ActionType
    except Exception as exc:
        raise RuntimeError(
            "Could not import the project. Run this script from the "
            "computer-use-automation repository root with your .venv active."
        ) from exc

    return {
        "agent_main": agent_main,
        "HumanHandoffManager": HumanHandoffManager,
        "TerminalOperator": TerminalOperator,
        "load_demo_banking_config": load_demo_banking_config,
        "PolicyEngine": PolicyEngine,
        "approve_cli": approve_cli,
        "CapabilityRegistry": CapabilityRegistry,
        "ReplayFlow": ReplayFlow,
        "CapabilityAction": CapabilityAction,
        "ActionType": ActionType,
    }


def run_main_request(project: dict[str, Any], request: str) -> Any:
    with inject_initial_request(request):
        return project["agent_main"].main()


def registry(project: dict[str, Any]):
    return project["CapabilityRegistry"]()


def latest_approved_savings(project: dict[str, Any]):
    eligible = registry(project).list_eligible(
        tenant_id=TENANT_ID,
        app_id=APP_ID,
    )

    savings = [
        (path, stored)
        for path, stored in eligible
        if stored.artifact.capability_id == CAPABILITY_ID
    ]

    if not savings:
        raise RuntimeError(
            "No approved get_savings_balance capability exists. "
            "Run/approve TC-001 or TC-006 first."
        )

    return max(
        savings,
        key=lambda item: (
            item[1].version,
            item[0].stat().st_mtime,
        ),
    )


def archive_and_reset_registry(case_dir: Path, label: str) -> Path | None:
    if not REGISTRY_DIR.exists():
        REGISTRY_DIR.mkdir(parents=True, exist_ok=True)
        return None

    has_content = any(REGISTRY_DIR.iterdir())

    if not has_content:
        return None

    destination = case_dir / f"{label}_registry_archive"

    if destination.exists():
        raise RuntimeError(f"Registry archive already exists: {destination}")

    shutil.move(str(REGISTRY_DIR), str(destination))
    REGISTRY_DIR.mkdir(parents=True, exist_ok=True)

    print(f"Registry archived to: {destination}")
    return destination


def run_approval_queue(project: dict[str, Any]) -> None:
    print()
    print_rule()
    print("HUMAN APPROVAL")
    print_rule()
    print("Review the draft carefully. Choose A only if the artifact is correct.")
    project["approve_cli"].main()


def make_replay_flow(
    project: dict[str, Any],
    *,
    case_dir: Path,
    policy_engine=None,
    checkpoint_resume: bool = False,
):
    handoff_manager = project["HumanHandoffManager"](
        operator=project["TerminalOperator"](
            operator_id="acceptance-operator"
        ),
        evidence_dir=case_dir / "handoff",
    )

    if policy_engine is None:
        policy_engine = project["PolicyEngine"](
            project["load_demo_banking_config"]()
        )

    resume_ids = (
        frozenset({CAPABILITY_ID})
        if checkpoint_resume
        else frozenset()
    )

    return project["ReplayFlow"](
        target_url=TARGET_URL,
        checkpoint_resume_capability_ids=resume_ids,
        handoff_manager=handoff_manager,
        policy_engine=policy_engine,
    )


def save_artifact_snapshot(
    case_dir: Path,
    name: str,
    artifact,
) -> Path:
    path = case_dir / name
    path.write_text(
        artifact.model_dump_json(indent=2) + "\n",
        encoding="utf-8",
    )
    return path


def direct_replay(
    project: dict[str, Any],
    *,
    case_dir: Path,
    artifact,
    business_outcome_rules,
    inputs: dict[str, str],
    policy_engine=None,
    checkpoint_resume: bool = False,
    handoff_demo: bool = False,
):
    save_artifact_snapshot(
        case_dir,
        "artifact_under_test.json",
        artifact,
    )

    flow = make_replay_flow(
        project,
        case_dir=case_dir,
        policy_engine=policy_engine,
        checkpoint_resume=checkpoint_resume,
    )

    if handoff_demo:
        with temporary_env("HANDOFF_DEMO", "1"):
            return flow(
                artifact=artifact,
                business_outcome_rules=business_outcome_rules,
                inputs=inputs,
            )

    return flow(
        artifact=artifact,
        business_outcome_rules=business_outcome_rules,
        inputs=inputs,
    )


def find_first_targeted_action(artifact):
    for index, action in enumerate(artifact.actions):
        if action.target is not None:
            return index, action

    raise RuntimeError("Artifact contains no targeted action.")


def find_fill_action(artifact, action_type):
    for index, action in enumerate(artifact.actions):
        if action.action == action_type:
            return index, action

    raise RuntimeError("Artifact contains no FILL action.")


def approved_file_hash(project: dict[str, Any]) -> tuple[Path, str]:
    path, _ = latest_approved_savings(project)
    return path, sha256(path)


def add_ambiguous_fixture(data_file: Path, artifact) -> str:
    """
    Add one temporary member whose two account rows match the approved
    output binding's row_match, while their balances differ.
    """
    if not data_file.exists():
        raise RuntimeError(f"Target data file not found: {data_file}")

    original = data_file.read_text(encoding="utf-8")

    if FIXTURE_BEGIN in original or FIXTURE_END in original:
        raise RuntimeError(
            "An acceptance ambiguity fixture is already present in data.py."
        )

    if not artifact.outputs:
        raise RuntimeError("Approved artifact declares no outputs.")

    binding = artifact.outputs[0].binding
    row_match = binding.row_match
    column = row_match.column.strip().casefold()
    value = row_match.value

    account_1 = {
        "account_id": "SAV-AMB-01",
        "type": "Savings",
        "nickname": "Ambiguous Savings",
        "status": "Open",
        "current_balance": 111.11,
        "available_balance": 111.11,
        "restricted": False,
        "transactions": [],
    }
    account_2 = {
        "account_id": "SAV-AMB-02",
        "type": "Savings",
        "nickname": "Ambiguous Savings",
        "status": "Open",
        "current_balance": 222.22,
        "available_balance": 222.22,
        "restricted": False,
        "transactions": [],
    }

    column_to_key = {
        "account": "account_id",
        "type": "type",
        "nickname": "nickname",
        "status": "status",
    }

    key = column_to_key.get(column)

    if key is None:
        raise RuntimeError(
            "TC-018 fixture does not know how to reproduce row-match "
            f"column {row_match.column!r}."
        )

    account_1[key] = value
    account_2[key] = value

    member = {
        "member_id": FIXTURE_MEMBER_ID,
        "name": "Ambiguous Output Fixture",
        "status": "Active",
        "joined": "2026-01-01",
        "phone": "(555) 010-9999",
        "email": "ambiguity.fixture@example.test",
        "accounts": [account_1, account_2],
    }

    block = (
        "\n\n"
        + FIXTURE_BEGIN
        + "\n"
        + f"MEMBERS[{FIXTURE_MEMBER_ID!r}] = "
        + pprint.pformat(member, width=100, sort_dicts=False)
        + "\n"
        + FIXTURE_END
        + "\n"
    )

    data_file.write_text(original + block, encoding="utf-8")
    return original


def restore_file(path: Path, original: str) -> None:
    path.write_text(original, encoding="utf-8")


def write_diff(
    before_text: str,
    after_text: str,
    path: Path,
    before_name: str = "before",
    after_name: str = "after",
) -> None:
    diff = difflib.unified_diff(
        before_text.splitlines(keepends=True),
        after_text.splitlines(keepends=True),
        fromfile=before_name,
        tofile=after_name,
    )
    path.write_text("".join(diff), encoding="utf-8")


# ---------------------------------------------------------------------------
# Scenario implementations
# ---------------------------------------------------------------------------

def tc001(project, case_dir):
    archive_and_reset_registry(case_dir, "before_tc001")
    return run_main_request(
        project,
        "Get the current savings balance for member 12345",
    )


def tc002(project, case_dir):
    run_approval_queue(project)
    return run_main_request(
        project,
        "Get the current savings balance for member 12345",
    )


def tc003(project, case_dir):
    return run_main_request(
        project,
        "Get the current savings balance for member 67890",
    )


def tc004(project, case_dir):
    return run_main_request(
        project,
        "Get the current savings balance for member 54321",
    )


def tc005(project, case_dir):
    approved_path, before_hash = approved_file_hash(project)
    results = []

    for iteration in range(1, 6):
        print()
        print_rule()
        print(f"TC-005 deterministic replay {iteration}/5")
        print_rule()

        result = run_main_request(
            project,
            "Get the current savings balance for member 12345",
        )
        results.append(result)

        write_json(
            case_dir / f"replay_{iteration}.json",
            result,
        )

    after_hash = sha256(approved_path)

    mutation_check = {
        "approved_artifact": str(approved_path),
        "sha256_before": before_hash,
        "sha256_after": after_hash,
        "unchanged": before_hash == after_hash,
    }
    write_json(case_dir / "artifact_stability.json", mutation_check)

    return {
        "runs": results,
        "artifact_stability": mutation_check,
    }


def tc006(project, case_dir):
    archive = archive_and_reset_registry(case_dir, "before_tc006")

    old_approved_text = None
    if archive is not None:
        approved_candidates = sorted(
            archive.rglob("*_approved_*.json")
        )
        if approved_candidates:
            old_approved_text = approved_candidates[-1].read_text(
                encoding="utf-8"
            )

    discovery = run_main_request(
        project,
        "Get the current savings balance for member 67890",
    )

    run_approval_queue(project)

    new_path, new_stored = latest_approved_savings(project)
    new_text = new_path.read_text(encoding="utf-8")
    shutil.copy2(new_path, case_dir / "new_approved_capability.json")

    if old_approved_text is not None:
        write_diff(
            old_approved_text,
            new_text,
            case_dir / "artifact_diff_vs_previous.diff",
            "previous_approved.json",
            "rediscovered_approved.json",
        )

    replay = run_main_request(
        project,
        "Get the current savings balance for member 12345",
    )

    return {
        "discovery": discovery,
        "approved_capability": {
            "path": str(new_path),
            "version": new_stored.version,
        },
        "replay": replay,
    }


def tc007(project, case_dir):
    return run_main_request(
        project,
        "How much money is in member 67890's savings account?",
    )


def tc008(project, case_dir):
    return run_main_request(
        project,
        "Get the current savings balance for member 99999",
    )


def tc009(project, case_dir):
    return run_main_request(
        project,
        "Get the current savings balance for member 22222",
    )


def tc010(project, case_dir):
    return run_main_request(
        project,
        "Get the current savings balance",
    )


def tc011(project, case_dir):
    return run_main_request(
        project,
        "Get the current savings balance for member abc",
    )


def tc012(project, case_dir):
    return run_main_request(
        project,
        "Open the Operations queue",
    )


def tc013(project, case_dir):
    _, stored = latest_approved_savings(project)
    artifact = stored.artifact.model_copy(deep=True)

    if not artifact.actions:
        raise RuntimeError("Approved artifact contains no actions.")

    artifact.actions[0] = project["CapabilityAction"](
        action=project["ActionType"].GO_BACK,
    )

    return direct_replay(
        project,
        case_dir=case_dir,
        artifact=artifact,
        business_outcome_rules=tuple(stored.business_outcome_rules),
        inputs={"member_id": "12345"},
    )


def tc014(project, case_dir):
    _, stored = latest_approved_savings(project)
    artifact = stored.artifact.model_copy(deep=True)

    if not artifact.actions:
        raise RuntimeError("Approved artifact contains no actions.")

    artifact.actions[0] = project["CapabilityAction"](
        action=project["ActionType"].NAVIGATE,
        url="https://example.com",
    )

    # Controlled in-memory test fixture:
    # production profile normally blocks NAVIGATE entirely. For TC-014 we
    # permit the action type only so the destination-origin rule is exercised.
    config = project["load_demo_banking_config"]().model_copy(deep=True)
    profile = config.profiles[CAPABILITY_ID].model_copy(deep=True)
    profile.allowed_actions = set(profile.allowed_actions) | {
        project["ActionType"].NAVIGATE
    }
    config.profiles[CAPABILITY_ID] = profile
    policy_engine = project["PolicyEngine"](config)

    write_json(
        case_dir / "policy_fixture.json",
        {
            "purpose": (
                "Allow NAVIGATE only for this isolated test so the "
                "external-origin allowlist is reached."
            ),
            "destination": "https://example.com",
            "saved_to_production_config": False,
        },
    )

    return direct_replay(
        project,
        case_dir=case_dir,
        artifact=artifact,
        business_outcome_rules=tuple(stored.business_outcome_rules),
        inputs={"member_id": "12345"},
        policy_engine=policy_engine,
    )


def tc015(project, case_dir):
    _, stored = latest_approved_savings(project)
    artifact = stored.artifact.model_copy(deep=True)

    index, action = find_first_targeted_action(artifact)
    broken_target = action.target.model_copy(
        update={"name": "__acceptance_missing_target__"}
    )
    artifact.actions[index] = action.model_copy(
        update={"target": broken_target}
    )

    return direct_replay(
        project,
        case_dir=case_dir,
        artifact=artifact,
        business_outcome_rules=tuple(stored.business_outcome_rules),
        inputs={"member_id": "12345"},
    )


def tc016(project, case_dir):
    _, stored = latest_approved_savings(project)
    artifact = stored.artifact.model_copy(deep=True)

    return direct_replay(
        project,
        case_dir=case_dir,
        artifact=artifact,
        business_outcome_rules=tuple(stored.business_outcome_rules),
        inputs={"member_id": "12345"},
        checkpoint_resume=True,
        handoff_demo=True,
    )


def tc017(project, case_dir):
    return run_main_request(
        project,
        "Open member 11111's savings account and inspect recent activity",
    )


def tc018(project, case_dir):
    _, stored = latest_approved_savings(project)
    artifact = stored.artifact.model_copy(deep=True)

    original = add_ambiguous_fixture(TARGET_DATA_FILE, artifact)

    try:
        print()
        print("Temporary member 33333 fixture written to target-app data.")

        if not wait_for_fixture(FIXTURE_MEMBER_ID, present=True):
            print()
            print(
                "The target server did not appear to reload the fixture. "
                "If you are not running Uvicorn with --reload, restart the "
                "target app now."
            )
            input("Press Enter when member 33333 is available... ")

        return direct_replay(
            project,
            case_dir=case_dir,
            artifact=artifact,
            business_outcome_rules=tuple(stored.business_outcome_rules),
            inputs={"member_id": FIXTURE_MEMBER_ID},
        )

    finally:
        restore_file(TARGET_DATA_FILE, original)
        print()
        print("Temporary TC-018 fixture removed from app/target_app/data.py.")
        wait_for_fixture(FIXTURE_MEMBER_ID, present=False, timeout=8.0)


def tc019(project, case_dir):
    _, stored = latest_approved_savings(project)
    artifact = stored.artifact.model_copy(deep=True)

    if not artifact.checkpoints:
        raise RuntimeError("Approved artifact contains no checkpoints.")

    artifact.checkpoints[0] = artifact.checkpoints[0].model_copy(
        update={"after_action": len(artifact.actions) + 10}
    )

    return direct_replay(
        project,
        case_dir=case_dir,
        artifact=artifact,
        business_outcome_rules=tuple(stored.business_outcome_rules),
        inputs={"member_id": "12345"},
    )


def tc020(project, case_dir):
    _, stored = latest_approved_savings(project)
    artifact = stored.artifact.model_copy(deep=True)

    index, action = find_fill_action(
        artifact,
        project["ActionType"].FILL,
    )

    artifact.actions[index] = action.model_copy(
        update={"value": "{{unknown_input}}"}
    )

    return direct_replay(
        project,
        case_dir=case_dir,
        artifact=artifact,
        business_outcome_rules=tuple(stored.business_outcome_rules),
        inputs={"member_id": "12345"},
    )


def tc021(project, case_dir):
    return run_main_request(
        project,
        "What is the status of member 54321?",
    )


RUNNERS: dict[str, Callable[[dict[str, Any], Path], Any]] = {
    "TC-001": tc001,
    "TC-002": tc002,
    "TC-003": tc003,
    "TC-004": tc004,
    "TC-005": tc005,
    "TC-006": tc006,
    "TC-007": tc007,
    "TC-008": tc008,
    "TC-009": tc009,
    "TC-010": tc010,
    "TC-011": tc011,
    "TC-012": tc012,
    "TC-013": tc013,
    "TC-014": tc014,
    "TC-015": tc015,
    "TC-016": tc016,
    "TC-017": tc017,
    "TC-018": tc018,
    "TC-019": tc019,
    "TC-020": tc020,
    "TC-021": tc021,
}


def result_hint(value: Any) -> str | None:
    """
    Print a concise structured observation when the returned object is a
    ReplayResult (or contains ReplayResults). This is informational only;
    the human still records the acceptance verdict.
    """
    if value is None:
        return None

    if hasattr(value, "status") and hasattr(value, "reason"):
        status = getattr(value.status, "value", value.status)
        error_code = getattr(value, "error_code", None)
        completed = getattr(value, "completed_steps", None)
        human_assisted = getattr(value, "human_assisted", None)
        outputs = getattr(value, "outputs", None)

        parts = [f"status={status}"]

        if error_code:
            parts.append(f"error_code={error_code}")
        if completed is not None:
            parts.append(f"completed_steps={completed}")
        if human_assisted:
            parts.append("human_assisted=true")
        if outputs:
            parts.append(f"outputs={outputs}")

        return " | ".join(parts)

    return None


def grade_case() -> tuple[str, str]:
    print()
    while True:
        value = input(
            "Record result: [p]ass / [f]ail / [b]locked / "
            "[s]kipped / [r]erun / [q]uit: "
        ).strip().lower()

        mapping = {
            "p": "Pass",
            "pass": "Pass",
            "f": "Fail",
            "fail": "Fail",
            "b": "Blocked",
            "blocked": "Blocked",
            "s": "Skipped",
            "skip": "Skipped",
            "skipped": "Skipped",
            "r": "Rerun",
            "rerun": "Rerun",
            "q": "Quit",
            "quit": "Quit",
        }

        if value in mapping:
            status = mapping[value]
            break

        print("Enter p, f, b, s, r, or q.")

    note = ""

    if status not in {"Rerun", "Quit"}:
        note = input("Optional note (Enter to leave blank): ").strip()

    return status, note


def append_result_csv(
    csv_path: Path,
    *,
    case: AcceptanceCase,
    status: str,
    note: str,
    case_dir: Path,
    started_at: str,
    ended_at: str,
) -> None:
    exists = csv_path.exists()

    with csv_path.open("a", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)

        if not exists:
            writer.writerow(
                [
                    "Test ID",
                    "Category",
                    "Scenario",
                    "Status",
                    "Started At",
                    "Ended At",
                    "Evidence Directory",
                    "Operator Note",
                ]
            )

        writer.writerow(
            [
                case.test_id,
                case.category,
                case.scenario,
                status,
                started_at,
                ended_at,
                str(case_dir),
                note,
            ]
        )


def select_cases(
    *,
    start: str | None,
    only: str | None,
) -> list[AcceptanceCase]:
    ids = [case.test_id for case in CASES]

    if only:
        only = only.upper()
        if only not in ids:
            raise SystemExit(f"Unknown test ID: {only}")
        return [case for case in CASES if case.test_id == only]

    if start:
        start = start.upper()
        if start not in ids:
            raise SystemExit(f"Unknown test ID: {start}")
        index = ids.index(start)
        return CASES[index:]

    return CASES


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--start",
        help="Start at a specific test ID, e.g. TC-008.",
    )
    parser.add_argument(
        "--only",
        help="Run only one test ID, e.g. TC-016.",
    )
    args = parser.parse_args()

    if not (Path("app") / "agent" / "main.py").exists():
        raise SystemExit(
            "Run this script from the repository root "
            "(the folder containing app/agent/main.py)."
        )

    ensure_target_app()
    project = load_project()

    selected = select_cases(
        start=args.start,
        only=args.only,
    )

    run_root = EVIDENCE_BASE / campaign_stamp()
    run_root.mkdir(parents=True, exist_ok=False)

    write_json(
        run_root / "campaign.json",
        {
            "started_at": utc_now(),
            "target_url": TARGET_URL,
            "tenant_id": TENANT_ID,
            "app_id": APP_ID,
            "selected_tests": [case.test_id for case in selected],
            "cases": [asdict(case) for case in selected],
        },
    )

    results_csv = run_root / "campaign_results.csv"

    print()
    print_rule("═")
    print("COMPUTER-USE AUTOMATION — INTERACTIVE ACCEPTANCE CAMPAIGN")
    print_rule("═")
    print(f"Scenarios       {len(selected)}")
    print(f"Evidence root   {run_root}")
    print()
    print(
        "Enter / y / yes = continue. "
        "You remain in control for approvals and handoffs."
    )

    completed = 0

    for position, case in enumerate(selected, start=1):
        case_dir = run_root / case.test_id
        case_dir.mkdir(parents=True, exist_ok=True)

        write_json(
            case_dir / "scenario.json",
            asdict(case),
        )

        while True:
            print_case(case, position, len(selected))

            choice = input(
                f"Run {case.test_id}? [Y]es / [S]kip / [Q]uit: "
            ).strip().lower()

            if choice in {"q", "quit"}:
                print(f"\nCampaign stopped. Evidence retained at: {run_root}")
                return

            if choice in {"s", "skip"}:
                started_at = utc_now()
                ended_at = utc_now()

                append_result_csv(
                    results_csv,
                    case=case,
                    status="Skipped",
                    note="Skipped before execution.",
                    case_dir=case_dir,
                    started_at=started_at,
                    ended_at=ended_at,
                )
                completed += 1
                break

            if not yes(choice):
                print("Enter y/yes/Enter, s/skip, or q/quit.")
                continue

            started_at = utc_now()
            result = None
            exception_text = None

            try:
                print()
                print_rule()
                print(f"RUNNING {case.test_id}")
                print_rule()

                result = RUNNERS[case.test_id](
                    project,
                    case_dir,
                )

                write_json(
                    case_dir / "result.json",
                    result,
                )

                hint = result_hint(result)
                if hint:
                    print()
                    print(f"Observed       {hint}")

            except KeyboardInterrupt:
                exception_text = "Operator interrupted the case with Ctrl+C."
                print("\nCase interrupted by operator.")

            except BaseException:
                exception_text = traceback.format_exc()
                print()
                print("ERROR | Scenario raised an exception.")
                print(exception_text)

            if exception_text:
                (case_dir / "exception.txt").write_text(
                    exception_text,
                    encoding="utf-8",
                )

            ended_at = utc_now()

            status, note = grade_case()

            if status == "Rerun":
                print(f"\nRerunning {case.test_id}. Existing evidence is retained.")
                continue

            if status == "Quit":
                print(f"\nCampaign stopped. Evidence retained at: {run_root}")
                return

            append_result_csv(
                results_csv,
                case=case,
                status=status,
                note=note,
                case_dir=case_dir,
                started_at=started_at,
                ended_at=ended_at,
            )

            write_json(
                case_dir / "verdict.json",
                {
                    "test_id": case.test_id,
                    "status": status,
                    "operator_note": note,
                    "started_at": started_at,
                    "ended_at": ended_at,
                },
            )

            completed += 1
            break

        if position < len(selected):
            print()
            answer = input(
                f"Continue to {selected[position].test_id}? [Y/n]: "
            )
            if not yes(answer):
                print(f"\nCampaign paused. Evidence retained at: {run_root}")
                print(
                    "Resume later with: "
                    f"python {Path(sys.argv[0]).name} "
                    f"--start {selected[position].test_id}"
                )
                return

    print()
    print_rule("═")
    print("ACCEPTANCE CAMPAIGN COMPLETE")
    print_rule("═")
    print(f"Cases recorded  {completed}")
    print(f"Results CSV     {results_csv}")
    print(f"Evidence root   {run_root}")
    print()
    print(
        "Your original pre-campaign registry, if one existed, was archived "
        "inside the TC-001 evidence directory rather than deleted."
    )


if __name__ == "__main__":
    main()
