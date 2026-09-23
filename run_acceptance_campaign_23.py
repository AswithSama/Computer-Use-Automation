#!/usr/bin/env python3
"""Operator-run acceptance campaign: 23 cases / five question types.

Run from the computer-use-automation repository root:
    python run_acceptance_campaign_23.py
    python run_acceptance_campaign_23.py --start TC-014
    python run_acceptance_campaign_23.py --only TC-020

Keep the demo app running separately with --reload:
    python -m uvicorn app.target_app.main:app --reload --port 8000

The operator grades every case. The runner never auto-approves a draft or
modifies the canonical approved artifact. Negative-test mutations are confined
to deep copies or temporarily edited demo fixture files that are restored in
finally blocks. Stop and restore from the evidence backup if the process is
forcibly terminated mid-fixture.

This runner is adapted from the user's earlier 21-case acceptance runner.
It is an integration harness, not an assertion that all 23 behaviors pass.
"""

from __future__ import annotations

import argparse
import builtins
import csv
import hashlib
import json
import os
import pprint
import re
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
REGISTRY_DIR = Path("capabilities")
EVIDENCE_BASE = Path("evidence") / "acceptance_campaign_23"
DATA_FILE = Path("app/target_app/data.py")
MEMBERS_TEMPLATE = Path("app/target_app/templates/members.html")
DETAIL_TEMPLATE = Path("app/target_app/templates/member_detail.html")
AMBIGUITY_MEMBER = "33333"

# The LLM chooses output names during discovery. Never predict their spelling.
# Keep the actual capability ID + output name from the saved draft for approval
# and replay. The map persists across --start / --only runs and is validated
# against the currently available approved artifacts before it is used.
CAPABILITY_MAP_FILE = EVIDENCE_BASE / "discovered_capabilities.json"
QUESTIONS = {
    "savings": ("Get the current savings balance for member 12345", "Get the current savings balance for member 67890"),
    "checking": ("Get the current checking balance for member 12345", "Get the current checking balance for member 54321"),
    "email": ("Get the email address of member 12345", "Get the email address of member 67890"),
    "phone": ("Get the phone number of member 12345", "Get the phone number of member 54321"),
    "status": ("What is the status of member 12345 in the member search results?", "What is the status of member 67890?"),
}


@dataclass(frozen=True)
class AcceptanceCase:
    test_id: str
    category: str
    scenario: str
    setup: str
    goal: str
    expected: str
    operator_note: str = ""


CASES = [
    AcceptanceCase("TC-001", "Discovery", "Discover savings balance", "Fresh registry", QUESTIONS["savings"][0], "Correct answer; parameterized member_id; verified Savings-row balance binding; checkpoints; documented savings rules."),
    AcceptanceCase("TC-002", "Discovery", "Discover checking balance", "No approved checking capability", QUESTIONS["checking"][0], "Correct checking balance; draft uses Checking row and balance column, not Savings."),
    AcceptanceCase("TC-003", "Discovery", "Discover member email", "Contact information rendered as HTML table", QUESTIONS["email"][0], "New email draft: row Field=Email, value_column=Value; output name may vary."),
    AcceptanceCase("TC-004", "Discovery", "Discover member phone", "Contact information rendered as HTML table", QUESTIONS["phone"][0], "Distinct phone draft: row Field=Phone, value_column=Value."),
    AcceptanceCase("TC-005", "Discovery", "Discover member status", "Status must come from member-search results TABLE", QUESTIONS["status"][0], "Draft binds requested Member ID row and Status column in search-results table; no unsupported detail-page <dl> binding."),
    AcceptanceCase("TC-006", "Approval / Replay", "Approve and cross-member replay: savings", "Savings draft from TC-001", QUESTIONS["savings"][1], "Operator approves; deterministic replay for 67890; correct savings balance; no discovery."),
    AcceptanceCase("TC-007", "Approval / Replay", "Approve and cross-member replay: checking", "Checking draft from TC-002", QUESTIONS["checking"][1], "Operator approves; deterministic replay for 54321; correct checking balance; no discovery."),
    AcceptanceCase("TC-008", "Approval / Replay", "Approve and cross-member replay: email", "Email draft from TC-003", QUESTIONS["email"][1], "Operator approves; replay returns 67890's email, not discovery email; no discovery."),
    AcceptanceCase("TC-009", "Approval / Replay", "Approve and cross-member replay: phone", "Phone draft from TC-004", QUESTIONS["phone"][1], "Operator approves; replay returns 54321's phone, not discovery phone; no discovery."),
    AcceptanceCase("TC-010", "Approval / Replay", "Approve and cross-member replay: status", "Status draft from TC-005", QUESTIONS["status"][1], "Operator approves; replay returns status from 67890's search-results row; no discovery."),
    AcceptanceCase("TC-011", "Selection", "Select each of five approved capabilities", "All five approved", "Run five paraphrased requests", "Every paraphrase reuses its corresponding approved capability; no cross-selection or discovery."),
    AcceptanceCase("TC-012", "Savings rules", "Existing savings business outcomes", "Approved savings capability", "Replay nonexistent member 99999 and no-savings member 22222", "Both existing business-outcome rules yield documented structured outcomes. Record both subresults."),
    AcceptanceCase("TC-013", "Savings recovery", "Savings missing required input", "Approved savings capability", "Request savings balance without member ID; leave prompted member_id blank", "Documented recoverable missing_required_inputs / REQUEST_INPUT behavior; no invented ID. Record any other already-defined savings recovery subconditions separately."),
    AcceptanceCase("TC-014", "Miscellaneous", "External-origin allowlist", "Disposable approved-artifact copy, isolated policy fixture", "Try NAVIGATE https://example.com", "POLICY hard failure / origin_not_allowed; browser does not navigate outside local app."),
    AcceptanceCase("TC-015", "Miscellaneous", "Unexpected checkpoint state", "Disposable approved-artifact copy", "Replay with an intentionally impossible checkpoint URL", "Checkpoint fails; no successful extraction; evidence. If offered a handoff, choose unresolved."),
    AcceptanceCase("TC-016", "Miscellaneous", "Human-assisted checkpoint recovery", "Checkpoint demo support in existing replay engine", "Resolve demo checkpoint in SAME browser and resume", "Checkpoint reverified; SUCCESS; human_assisted=true. Do not bypass verification."),
    AcceptanceCase("TC-017", "Miscellaneous", "Missing action target", "Disposable copy of any supported approved capability", "Make a recorded target name absent", "No click on unrelated control; recorded safe failure/handoff."),
    AcceptanceCase("TC-018", "Miscellaneous", "Ambiguous action target", "Temporary duplicate Open Member link in search-results fixture", "Replay selected capability through duplicate action target", "Do not arbitrarily click either matching link; targeting failure/handoff; fixture restored."),
    AcceptanceCase("TC-019", "Miscellaneous", "Ambiguous table output", "Temporary member 33333 with duplicate matching account rows", "Replay savings or checking for member 33333", "HARD_FAILURE / OUTPUT / ambiguous_output; do not guess; fixture restored."),
    AcceptanceCase("TC-020", "Miscellaneous", "Missing table output", "Temporarily remove Email/Phone row from contact table", "Replay approved email or phone for member 67890", "OUTPUT failure, no stale discovery value or wrong field; fixture restored."),
    AcceptanceCase("TC-021", "Miscellaneous", "Missing / malformed required input", "Approved capability; documented member_id contract", "Try missing member_id and member abc", "No invented ID or false success; classify missing and invalid separately; a generic handoff for malformed ID is not proof of structured invalid-input classification."),
    AcceptanceCase("TC-022", "Miscellaneous", "Member not found / wrong-member protection", "Approved capability; nonexistent member 99999", "Replay a question for member 99999", "No value from a previous/wrong member; documented no-record outcome or safe failure."),
    AcceptanceCase("TC-023", "Miscellaneous", "Validator LLM input serialization regression", "No browser mutation; local BrowserAction object", "Serialize nested BrowserAction through shared transport method", "JSON serialization succeeds with nested model; no BrowserAction TypeError. This checks serialization only, not an actual remote LLM response."),
]


def stamp() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S_%f")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def rule(symbol="─"):
    print(symbol * 72)


def yes(value: str) -> bool:
    return value.strip().lower() in ("", "y", "yes")


def jsonable(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if isinstance(value, dict):
        return {str(k): jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [jsonable(item) for item in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return repr(value)


def write_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(jsonable(obj), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def response(path: str = "/") -> str | None:
    try:
        with urllib.request.urlopen(TARGET_URL + path, timeout=2) as r:
            return r.read().decode("utf-8", errors="replace")
    except (urllib.error.URLError, TimeoutError, ConnectionError):
        return None


def ensure_app() -> None:
    while response("/") is None:
        print("Target app not reachable at", TARGET_URL)
        print("Run in another terminal: python -m uvicorn app.target_app.main:app --reload --port 8000")
        input("Press Enter after starting the target app (Ctrl+C to quit)... ")


@contextmanager
def initial_request(request: str):
    """Only auto-answer the first main prompt; handoff and input prompts stay human."""
    original = builtins.input
    supplied = False

    def prompted(prompt: str = "") -> str:
        nonlocal supplied
        if not supplied and "What do you want to do?" in prompt:
            supplied = True
            print(f"{prompt}{request}")
            return request
        return original(prompt)

    builtins.input = prompted
    try:
        yield
    finally:
        builtins.input = original


@contextmanager
def environment(name: str, value: str):
    prior = os.environ.get(name)
    os.environ[name] = value
    try:
        yield
    finally:
        if prior is None:
            os.environ.pop(name, None)
        else:
            os.environ[name] = prior


def load_project() -> dict[str, Any]:
    try:
        from app.agent import main as agent_main
        from app.agent.handoff.manager import HumanHandoffManager
        from app.agent.handoff.operator import TerminalOperator
        from app.agent.policy.config import load_demo_banking_config
        from app.agent.policy.engine import PolicyEngine
        from app.agent.registry import approve as approval_cli
        from app.agent.registry.registry import CapabilityRegistry
        from app.agent.orchestration.replay_flow import ReplayFlow
        from app.agent.schemas.capability import CapabilityAction
        from app.agent.schemas.discovery import ActionType, BrowserAction
        from app.agent.llm.client import StructuredLLMClient
    except Exception as exc:
        raise RuntimeError("Project import failed. Run from repository root with your .venv active; check import paths against current code.") from exc
    return locals()


def main_request(p: dict[str, Any], request: str) -> Any:
    print("\nREQUEST:", request)
    with initial_request(request):
        return p["agent_main"].main()


def registry(p: dict[str, Any]):
    return p["CapabilityRegistry"]()


def eligible(p: dict[str, Any]):
    return registry(p).list_eligible(tenant_id=TENANT_ID, app_id=APP_ID)


def output_of(stored) -> list[str]:
    return [o.name for o in stored.artifact.outputs]


def load_capability_map() -> dict[str, dict[str, str]]:
    """A local acceptance-runner index, not a registry or capability artifact."""
    if not CAPABILITY_MAP_FILE.exists():
        return {}
    data = json.loads(CAPABILITY_MAP_FILE.read_text(encoding="utf-8"))
    if data.get("tenant_id") != TENANT_ID or data.get("app_id") != APP_ID:
        raise RuntimeError("The saved capability map belongs to another tenant/app.")
    entries = data.get("capabilities", {})
    if not isinstance(entries, dict):
        raise RuntimeError(f"Invalid runner capability map: {CAPABILITY_MAP_FILE}")
    return entries


def save_capability_map(entries: dict[str, dict[str, str]]) -> None:
    write_json(CAPABILITY_MAP_FILE, {
        "tenant_id": TENANT_ID,
        "app_id": APP_ID,
        "capabilities": entries,
    })


def artifact_digest(artifact) -> str:
    """Compare the approved snapshot to the *actual draft*, not an older twin."""
    normalized = json.dumps(artifact.model_dump(mode="json"), sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def approved_matches(mapping: dict[str, str], stored) -> bool:
    return (
        stored.artifact.capability_id == mapping["capability_id"]
        and output_of(stored) == [mapping["output_name"]]
        and artifact_digest(stored.artifact) == mapping["artifact_sha256"]
    )


def remember_capability(kind: str, path: Path, stored, *, source: str) -> None:
    """Save the discovered name once; approval must preserve it unchanged."""
    if len(stored.artifact.outputs) != 1:
        raise RuntimeError(f"{kind} artifact must declare exactly one output.")
    entries = load_capability_map()
    entries[kind] = {
        "capability_id": stored.artifact.capability_id,
        "output_name": stored.artifact.outputs[0].name,
        "artifact_sha256": artifact_digest(stored.artifact),
        "original_path": str(path.resolve()),
        "source": source,
    }
    save_capability_map(entries)
    print(f"Recorded {kind} capability ID: {entries[kind]['capability_id']}")
    print(f"Recorded output name: {entries[kind]['output_name']}")


def approved_for(p: dict[str, Any], kind: str):
    """Find the exact discovered identity, not a guessed output keyword."""
    mapping = load_capability_map().get(kind)
    candidates = eligible(p)
    if mapping is not None:
        matches = [(path, item) for path, item in candidates
                   if approved_matches(mapping, item)]
        if not matches:
            raise RuntimeError(
                f"No approved artifact matches the recorded {kind} identity "
                f"({mapping['capability_id']}, {mapping['output_name']}). "
                "Review/approve that draft, or rerun its discovery test. "
                f"Runner map: {CAPABILITY_MAP_FILE}. The approved snapshot must also match the draft contents."
            )
        return max(matches, key=lambda pair: (pair[1].version, pair[0].stat().st_mtime))

    # --start and --only may be invoked after drafts were created with an older
    # runner, when no capability map exists. Do not silently select a guessed
    # output: the operator explicitly identifies the existing approved artifact.
    if not candidates:
        raise RuntimeError(f"No approved capabilities found for {kind}; discover and approve its draft first.")
    print(f"\nNo recorded identity for {kind}. Select the matching ALREADY APPROVED artifact:")
    for index, (path, item) in enumerate(candidates, start=1):
        print(f"  [{index}] {item.artifact.capability_id} | outputs={output_of(item)} | {path}")
        for output in item.artifact.outputs:
            print(f"      binding={jsonable(output.binding)}")
    while True:
        choice = input(f"Select the approved {kind} artifact [1-{len(candidates)}] (q to cancel): ").strip().lower()
        if choice == "q":
            raise RuntimeError(f"Selection cancelled for {kind}.")
        if choice.isdecimal() and 1 <= int(choice) <= len(candidates):
            selected_path, selected_item = candidates[int(choice) - 1]
            confirmation = input(
                f"Confirm this artifact answers the {kind} question and has a reusable binding? [y/N]: "
            ).strip().lower()
            if confirmation in ("y", "yes"):
                remember_capability(kind, selected_path, selected_item, source="operator-selected-existing-approved")
                return selected_path, selected_item
            print("Selection not confirmed; choose another or q to cancel.")
        else:
            print("Enter a listed number or q.")


def select_approved(p: dict[str, Any], default: str = "email", allowed=None):
    available = list(allowed or QUESTIONS)
    options = "/".join(available)
    answer = input(f"Select approved capability for this miscellaneous case [{options}] (Enter={default}): ").strip().lower() or default
    if answer not in available:
        raise RuntimeError(f"Unsupported choice {answer!r}; choose one of {options}.")
    path, stored = approved_for(p, answer)
    print(f"Using {answer}: {stored.artifact.capability_id} ({path})")
    return answer, path, stored


def record_artifact(case_dir: Path, artifact, filename="artifact_under_test.json"):
    target = case_dir / filename
    target.write_text(artifact.model_dump_json(indent=2) + "\n", encoding="utf-8")
    return target

def replay(
    p,
    case_dir: Path,
    stored,
    *,
    artifact=None,
    member="12345",
    policy_engine=None,
    checkpoint_resume=False,
    handoff_demo=False,
):
    artifact = artifact or stored.artifact.model_copy(deep=True)
    record_artifact(case_dir, artifact)

    operator = p["TerminalOperator"](operator_id="acceptance-operator")
    manager = p["HumanHandoffManager"](
        operator=operator,
        evidence_dir=case_dir / "handoff",
    )
    policy = policy_engine or p["PolicyEngine"](
        p["load_demo_banking_config"]()
    )

    # Classify the ORIGINAL approved artifact, not the disposable test copy.
    is_savings = any(
        output.binding.kind == "table"
        and output.binding.row_match.column == "Type"
        and output.binding.row_match.value == "Savings"
        and output.binding.value_column == "Current Balance"
        for output in stored.artifact.outputs
    )

    policy_profile_id = (
        "get_savings_balance"
        if is_savings
        else "read_only_replay"
    )

    flow = p["ReplayFlow"](
        target_url=TARGET_URL,
        checkpoint_resume_capability_ids=(
            frozenset({artifact.capability_id})
            if checkpoint_resume
            else frozenset()
        ),
        handoff_manager=manager,
        policy_engine=policy,
    )

    kwargs = dict(
        artifact=artifact,
        business_outcome_rules=tuple(stored.business_outcome_rules),
        inputs={"member_id": str(member)},
        policy_profile_id=policy_profile_id,
    )

    if handoff_demo:
        with environment("HANDOFF_DEMO", "1"):
            result = flow(**kwargs)
    else:
        result = flow(**kwargs)

    for evidence_path in result.evidence_refs:
        print(f"Evidence: {evidence_path}")

    return result

def operator_approval(p, kind: str):
    mapping = load_capability_map().get(kind)
    if mapping:
        matches = [(path, item) for path, item in eligible(p)
                   if approved_matches(mapping, item)]
        if matches:
            print(f"The exact recorded {kind} capability is already approved; operator review was completed earlier.")
            return
    print("\nHUMAN APPROVAL — inspect pending drafts; choose A only for those you explicitly approve.")
    if mapping:
        print(f"Expected capability: {mapping['capability_id']} | output: {mapping['output_name']}")
    else:
        print("No saved discovery identity for this question. An existing approved artifact can be selected afterward.")
    p["approval_cli"].main()
    approved_for(p, kind)  # Do not proceed if the operator skipped or quit.


def reset_capability_map(case_dir: Path) -> None:
    if CAPABILITY_MAP_FILE.exists():
        shutil.copy2(CAPABILITY_MAP_FILE, case_dir / "pre_campaign_capability_map.json")
        save_capability_map({})
        print("Old runner capability map archived; new discovery will record fresh names.")


def registry_reset_for_discovery(p, case_dir: Path):
    """Do not silently remove existing approved capabilities."""
    if not REGISTRY_DIR.exists() or not any(REGISTRY_DIR.rglob("*.json")):
        REGISTRY_DIR.mkdir(parents=True, exist_ok=True)
        reset_capability_map(case_dir)
        return
    print("\nAn existing registry would cause discovery cases to select OLD approved capabilities.")
    print("To run a fresh campaign, it must be ARCHIVED, not deleted.")
    print("Existing registry:", REGISTRY_DIR.resolve())
    answer = input("Archive it under this run's TC-001 evidence and start a fresh registry? [y/N]: ").strip().lower()
    if answer not in ("y", "yes"):
        print("Using existing registry; no capabilities were archived.")
        return
    destination = case_dir / "pre_campaign_registry"
    if destination.exists():
        raise RuntimeError(f"Refusing to overwrite registry backup: {destination}")
    shutil.move(str(REGISTRY_DIR), str(destination))
    REGISTRY_DIR.mkdir(parents=True, exist_ok=True)
    print("Registry safely archived at:", destination)
    reset_capability_map(case_dir)


def run_discovery(p, case_dir: Path, kind: str):
    before = {str(path.resolve()) for path in registry(p).list_drafts()}
    result = main_request(p, QUESTIONS[kind][0])
    after = [(path, registry(p).load(path)) for path in registry(p).list_drafts()
             if str(path.resolve()) not in before]
    write_json(case_dir / "new_drafts.json", [
        dict(path=str(path), capability_id=item.artifact.capability_id,
             outputs=output_of(item),
             binding=[jsonable(o.binding) for o in item.artifact.outputs])
        for path, item in after
    ])
    if not after:
        print("WARNING | No NEW draft was saved. A correct-looking discovery answer alone is not a pass.")
        return result

    # Never guess the spelling of an LLM-generated output name. A single newly
    # saved draft is unambiguous; if several were saved, the operator picks the
    # one produced for this question after inspecting the full binding.
    if len(after) == 1:
        chosen_path, chosen_item = after[0]
    else:
        print(f"Discovery saved {len(after)} new drafts. Select the draft for {kind}:")
        for index, (path, item) in enumerate(after, start=1):
            print(f"  [{index}] {item.artifact.capability_id} | outputs={output_of(item)} | {path}")
        choice = input("Draft number (Enter to leave unverified): ").strip()
        if not choice.isdecimal() or not 1 <= int(choice) <= len(after):
            print("WARNING | No draft selected. Do not mark this discovery as passed.")
            return result
        chosen_path, chosen_item = after[int(choice) - 1]

    artifact = chosen_item.artifact
    if len(artifact.outputs) != 1 or not artifact.outputs[0].name.strip():
        print("WARNING | Draft has no single nonempty output name; operator review required.")
        return result
    if not any(inp.name == "member_id" and inp.required for inp in artifact.inputs):
        print("WARNING | Draft does not declare required member_id; operator review required.")
        return result
    print(f"\nDraft to inspect for {kind}: {chosen_path}")
    print(f"Capability ID: {artifact.capability_id}")
    print(f"Actual discovered output name: {artifact.outputs[0].name}")
    print(f"Output binding: {jsonable(artifact.outputs[0].binding)}")
    write_json(case_dir / f"draft_{chosen_path.stem}.json", chosen_item)
    remember_capability(kind, chosen_path, chosen_item, source="newly-discovered-draft")
    write_json(case_dir / "recorded_capability_identity.json", load_capability_map()[kind])
    return result


def choose_action(artifact, *, name: str | None = None):
    for index, action in enumerate(artifact.actions):
        if action.target is not None and (name is None or action.target.name == name):
            return index, action
    raise RuntimeError(f"No action with target name {name!r} was found in approved artifact.")


def print_subcase(title: str, expected: str):
    print("\n" + "─" * 52)
    print("SUBCASE:", title)
    print("Expected:", expected)
    print("─" * 52)


@contextmanager
def edited_fixture(path: Path, updated: str, case_dir: Path, name: str):
    if not path.exists():
        raise RuntimeError(f"Fixture file does not exist: {path}")
    original = path.read_text(encoding="utf-8")
    if original == updated:
        raise RuntimeError(f"Fixture {name} would not change {path}; test not executed.")
    backup = case_dir / f"{name}_original_backup.txt"
    backup.write_text(original, encoding="utf-8")
    if path.read_text(encoding="utf-8") != original:
        raise RuntimeError("Fixture changed concurrently before test; refusing to overwrite.")
    path.write_text(updated, encoding="utf-8")
    print(f"Temporary {name} fixture installed in {path}. Backup: {backup}")
    try:
        yield
    finally:
        path.write_text(original, encoding="utf-8")
        print(f"Restored original {path} (backup retained in evidence).")


def wait_page(path: str, predicate: Callable[[str], bool], label: str, timeout=15.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        body = response(path)
        if body is not None and predicate(body):
            return
        time.sleep(0.4)
    raise RuntimeError(f"The live target app did not expose {label}. Ensure Uvicorn uses --reload; do not grade as a pass.")


# -------------------------------------------------------------------------
# A. DISCOVERY: five different natural-language questions
# -------------------------------------------------------------------------

def tc001(p, d):
    registry_reset_for_discovery(p, d)
    return run_discovery(p, d, "savings")


def tc002(p, d):
    return run_discovery(p, d, "checking")


def tc003(p, d):
    return run_discovery(p, d, "email")


def tc004(p, d):
    return run_discovery(p, d, "phone")


def tc005(p, d):
    return run_discovery(p, d, "status")


# -------------------------------------------------------------------------
# B. HUMAN APPROVAL + REPLAY: operator controls the real approval queue
# -------------------------------------------------------------------------

def approval_replay(p, d, kind: str):
    operator_approval(p, kind)
    path, item = approved_for(p, kind)
    print("Approved artifact:", path)
    write_json(d / "approved_artifact.json", item)
    return main_request(p, QUESTIONS[kind][1])


def tc006(p, d): return approval_replay(p, d, "savings")
def tc007(p, d): return approval_replay(p, d, "checking")
def tc008(p, d): return approval_replay(p, d, "email")
def tc009(p, d): return approval_replay(p, d, "phone")
def tc010(p, d): return approval_replay(p, d, "status")


# -------------------------------------------------------------------------
# C. SELECTOR + D. SAVINGS-SPECIFIC RULES
# -------------------------------------------------------------------------

def tc011(p, d):
    for kind in QUESTIONS:
        approved_for(p, kind)
    paraphrases = {
        "savings": "How much money is in member 67890's savings account?",
        "checking": "What's the current checking account balance for member 54321?",
        "email": "Look up the email for member ID 67890",
        "phone": "Find member 54321's phone number",
        "status": "Look up the membership status for member ID 67890",
    }
    results = {}
    for kind, request in paraphrases.items():
        print_subcase(kind, "Matching APPROVED capability chosen; no discovery; correct runtime-member value.")
        results[kind] = main_request(p, request)
        write_json(d / f"selection_{kind}.json", results[kind])
        input("Inspect selection above, then press Enter for the next paraphrase... ")
    return results


def tc012(p, d):
    _, item = approved_for(p, "savings")
    if not item.business_outcome_rules:
        raise RuntimeError("Approved savings capability has NO business-outcome rules; inspect discovery/approval first.")
    write_json(d / "savings_outcome_rules.json", item.business_outcome_rules)
    results = {}
    for name, member, expected in (
        ("member_not_found", "99999", "BUSINESS_OUTCOME / member_not_found"),
        ("savings_account_not_found", "22222", "BUSINESS_OUTCOME / savings_account_not_found"),
    ):
        print_subcase(name, expected)
        results[name] = main_request(p, f"Get the current savings balance for member {member}")
        write_json(d / f"outcome_{name}.json", results[name])
        input("Record this subresult in your operator note; press Enter to continue... ")
    return results


def tc013(p, d):
    approved_for(p, "savings")
    print("When prompted for member_id, press Enter WITHOUT supplying a value.")
    print("Expected: existing missing_required_inputs / REQUEST_INPUT recovery contract.")
    return main_request(p, "Get the current savings balance")


# -------------------------------------------------------------------------
# E. MISCELLANEOUS: engine-wide behavior, any suitable question/capability
# -------------------------------------------------------------------------

def tc014(p, d):
    _, _, stored = select_approved(p, default="savings")
    artifact = stored.artifact.model_copy(deep=True)

    if not artifact.actions:
        raise RuntimeError("Approved artifact has no actions.")

    artifact.actions[0] = p["CapabilityAction"](
        action=p["ActionType"].NAVIGATE,
        url="https://example.com",
    )

    config = p["load_demo_banking_config"]().model_copy(deep=True)
    cap_id = artifact.capability_id

    # Identify the savings workflow by its output binding,
    # not by the capability ID generated by the LLM.
    is_savings = any(
        output.binding.kind == "table"
        and output.binding.row_match.column == "Type"
        and output.binding.row_match.value == "Savings"
        and output.binding.value_column == "Current Balance"
        for output in artifact.outputs
    )

    profile_name = (
        "get_savings_balance"
        if is_savings
        else "read_only_replay"
    )

    if profile_name not in config.profiles:
        raise RuntimeError(
            f"Required policy profile {profile_name!r} was not found."
        )

    profile = config.profiles[profile_name].model_copy(deep=True)

    # Allow NAVIGATE so the test specifically checks
    # whether the external origin is blocked.
    profile.allowed_actions = (
        set(profile.allowed_actions)
        | {p["ActionType"].NAVIGATE}
    )

    # Apply the selected profile under the capability's actual ID.
    config.profiles[cap_id] = profile

    write_json(
        d / "policy_fixture.json",
        {
            "isolated_test_only": True,
            "selected_capability_id": cap_id,
            "source_policy_profile": profile_name,
            "temporarily_allowed_action": "navigate",
            "expected_block": "origin_not_allowed",
            "production_policy_changed": False,
        },
    )
    result = replay(
    p,
    d,
    stored,
    artifact=artifact,
    policy_engine=p["PolicyEngine"](config),
    )
    print(f"TC-014 evidence directory: {d.resolve()}")
    return result



def tc015(p, d):
    _, _, stored = select_approved(p)
    artifact = stored.artifact.model_copy(deep=True)
    if not artifact.checkpoints:
        raise RuntimeError("Selected capability has no checkpoints.")
    # Replace the first existing URL checkpoint, retaining its after_action.
    index = next((i for i, cp in enumerate(artifact.checkpoints) if cp.url_pattern), None)
    if index is None:
        raise RuntimeError("Selected capability has no URL checkpoint suitable for this test.")
    artifact.checkpoints[index] = artifact.checkpoints[index].model_copy(update={"url_pattern": "/__acceptance_impossible_checkpoint__"})
    print("A deliberately impossible checkpoint is installed in a disposable artifact COPY.")
    print("If a handoff appears, choose unresolved; TC-016 tests recovery separately.")
    return replay(p, d, stored, artifact=artifact)


def tc016(p, d):
    _, _, stored = select_approved(p, default="savings")
    print("Demo: in SAME Playwright browser, click 'Resolve demo checkpoint' when it appears.")
    print("Then follow the existing terminal operator prompts and resume only after verification.")
    return replay(p, d, stored, checkpoint_resume=True, handoff_demo=True)


def tc017(p, d):
    _, _, stored = select_approved(p)
    artifact = stored.artifact.model_copy(deep=True)
    index, action = choose_action(artifact)
    broken = action.target.model_copy(update={"name": "__acceptance_missing_target__"})
    artifact.actions[index] = action.model_copy(update={"target": broken})
    print("Disposable action target changed to a name guaranteed absent from the demo UI.")
    print("At a handoff, choose unresolved to capture a controlled safe failure.")
    return replay(p, d, stored, artifact=artifact)


def tc018(p, d):
    _, _, stored = select_approved(p, default="email", allowed=("savings", "checking", "email", "phone"))
    # Prefer an actual recorded Open Member step, which the fixture duplicates.
    choose_action(stored.artifact, name="Open Member")
    if not MEMBERS_TEMPLATE.exists():
        raise RuntimeError(f"Cannot find {MEMBERS_TEMPLATE}; update fixture path for your project.")
    original = MEMBERS_TEMPLATE.read_text(encoding="utf-8")
    pattern = re.compile(r'<a\b[^>]*\bhref="/members/\{\{\s*member\.member_id\s*\}\}"[^>]*>\s*Open Member\s*</a>', re.I | re.S)
    matches = list(pattern.finditer(original))
    if len(matches) != 1:
        raise RuntimeError(f"Expected one Open Member template link, found {len(matches)}. Inspect members.html before changing the fixture.")
    link = matches[0].group(0)
    modified = original[:matches[0].end()] + "\n                " + link + " <!-- acceptance duplicate -->" + original[matches[0].end():]
    with edited_fixture(MEMBERS_TEMPLATE, modified, d, "duplicate_action_target"):
        url = "/members?member_id=12345"
        wait_page(url, lambda body: body.count('>Open Member</a>') >= 2, "two Open Member links")
        print("Live page contains duplicate 'Open Member' links; do not pick an arbitrary one at handoff.")
        try:
            return replay(p, d, stored, member="12345")
        finally:
            print("The template will now be restored before the next case.")


def _ambiguous_member_data(binding):
    row = binding.row_match
    col = row.column.strip().casefold()
    mapping = {"account": "account_id", "type": "type", "nickname": "nickname", "status": "status"}
    if col not in mapping:
        raise RuntimeError(f"Ambiguous account fixture cannot represent row-match column {row.column!r}; choose savings/checking with a standard accounts-table binding.")
    def account(number, balance):
        acc = dict(account_id=f"AMB-{number}", type="Checking", nickname="Ambiguous Account", status="Open", current_balance=balance, available_balance=balance, restricted=False, transactions=[])
        acc[mapping[col]] = row.value
        return acc
    return dict(member_id=AMBIGUITY_MEMBER, name="Ambiguous Output Fixture", status="Active", joined="2026-01-01", phone="(555) 010-9999", email="ambiguity.fixture@example.test", accounts=[account("01", 111.11), account("02", 222.22)])


def tc019(p, d):
    kind, _, stored = select_approved(p, default="checking", allowed=("savings", "checking"))
    binding = stored.artifact.outputs[0].binding
    if binding.kind != "table":
        raise RuntimeError("Selected capability does not have a table output binding.")
    original = DATA_FILE.read_text(encoding="utf-8")
    marker = "# BEGIN ACCEPTANCE CAMPAIGN 23 AMBIGUOUS MEMBER"
    if marker in original:
        raise RuntimeError("Existing ambiguous fixture detected; restore data.py before running.")
    member = _ambiguous_member_data(binding)
    updated = original + f"\n\n{marker}\nMEMBERS[{AMBIGUITY_MEMBER!r}] = " + pprint.pformat(member, width=100, sort_dicts=False) + "\n# END ACCEPTANCE CAMPAIGN 23 AMBIGUOUS MEMBER\n"
    with edited_fixture(DATA_FILE, updated, d, "ambiguous_output"):
        url = f"/members?member_id={AMBIGUITY_MEMBER}"
        wait_page(url, lambda body: ("111.11" not in body and AMBIGUITY_MEMBER in body), "temporary member in search results")
        wait_page(f"/members/{AMBIGUITY_MEMBER}", lambda body: "111.11" in body and "222.22" in body, "two distinct account balances")
        print("Two account rows match the output binding; no arbitrary selection is permitted.")
        return replay(p, d, stored, member=AMBIGUITY_MEMBER)


def tc020(p, d):
    kind, _, stored = select_approved(p, default="email", allowed=("email", "phone"))
    original = DETAIL_TEMPLATE.read_text(encoding="utf-8")
    label, variable = ("Email", "email") if kind == "email" else ("Phone", "phone")
    # Remove only the explicit row of the TEMPORARY contact <table>, not the
    # other Member information <dl> or the entire app field.
    row = re.compile(r"<tr>\s*<td>\s*" + label + r"\s*</td>\s*<td>\s*\{\{\s*member\." + variable + r"\s*\}\}\s*</td>\s*</tr>", re.I | re.S)
    modified, count = row.subn("<!-- acceptance: temporarily removed " + label + " row -->", original)
    if count != 1:
        raise RuntimeError(f"Expected exactly one {label} table row, found {count}. Keep the temporary contact <table> markup for this campaign.")
    with edited_fixture(DETAIL_TEMPLATE, modified, d, "missing_contact_output"):
        member_page = "/members/67890"
        field_row = re.compile(
            rf"<tr>\s*<td>\s*{re.escape(label)}\s*</td>\s*<td\b",
            re.I | re.S,
        )

        wait_page(
            member_page,
            lambda body: field_row.search(body) is None,
            f"missing {label} field row",
        )        
        return replay(p, d, stored, member="67890")


def tc021(p, d):
    kind, _, stored = select_approved(p, default="savings")
    print_subcase("Missing required member_id", "No invented ID; documented input request / recoverable outcome")
    print("If prompted for member_id, press Enter with no value.")
    missing = main_request(p, QUESTIONS[kind][0].replace(" for member 12345", "").replace(" of member 12345", "").replace(" member 12345", ""))
    write_json(d / "missing_member_id.json", missing)
    input("Record the missing-input result in your notes, then press Enter for malformed ID... ")
    print_subcase("Malformed member_id=abc", "No misleading successful lookup; check documented invalid-input classification separately")
    malformed_request = {
        "savings": "Get the current savings balance for member abc",
        "checking": "Get the current checking balance for member abc",
        "email": "Get the email address of member abc",
        "phone": "Get the phone number of member abc",
        "status": "What is the status of member abc?",
    }[kind]
    malformed = main_request(p, malformed_request)
    write_json(d / "malformed_member_id.json", malformed)
    return {"missing": missing, "malformed": malformed}


def tc022(p, d):
    kind, _, stored = select_approved(p, default="email")
    request = {
        "savings": "Get the current savings balance for member 99999",
        "checking": "Get the current checking balance for member 99999",
        "email": "Get the email address of member 99999",
        "phone": "Get the phone number of member 99999",
        "status": "What is the status of member 99999?",
    }[kind]
    print("Check that no value from another member is returned.")
    return main_request(p, request)


def tc023(p, d):
    # Focused deterministic check of the exact regression path. Does not
    # generate an API call, spend tokens, or require a browser.
    action = p["BrowserAction"](action=p["ActionType"].CLICK, target_role="link", target_name="◉ Members", reason="serialization regression fixture")
    payload = {"validation": {"action": action, "history": [action]}, "query": "Get member email"}
    encoded = p["StructuredLLMClient"]._serialize_input(payload)
    decoded = json.loads(encoded)
    assert decoded["validation"]["action"]["action"] == "click"
    assert decoded["validation"]["history"][0]["target_role"] == "link"
    print("Nested BrowserAction JSON conversion passed; no API request was made.")
    write_json(d / "serialization_result.json", decoded)
    return {"serialization": "passed", "decoded": decoded}


RUNNERS: dict[str, Callable[[dict[str, Any], Path], Any]] = {
    f"TC-{i:03d}": globals()[f"tc{i:03d}"] for i in range(1, 24)
}


def result_hint(result: Any) -> str | None:
    if not hasattr(result, "status") or not hasattr(result, "reason"):
        return None
    status = getattr(result.status, "value", result.status)
    fields = [f"status={status}"]
    for attribute in ("error_code", "completed_steps", "human_assisted", "outputs"):
        value = getattr(result, attribute, None)
        if value is not None and value is not False and value != {}:
            fields.append(f"{attribute}={value}")
    return " | ".join(fields)


def grade() -> tuple[str, str]:
    while True:
        answer = input("\nResult [P]ass / [F]ail / [B]locked / [S]kip / [R]erun / [Q]uit: ").strip().lower()
        mapping = dict(p="Pass", pass_="Pass", f="Fail", fail="Fail", b="Blocked", blocked="Blocked", s="Skipped", skip="Skipped", r="Rerun", rerun="Rerun", q="Quit", quit="Quit")
        status = mapping.get(answer)
        if status:
            break
        print("Enter p, f, b, s, r, or q.")
    note = "" if status in ("Rerun", "Quit") else input("Operator note (recommended: actual result / evidence path): ").strip()
    return status, note


def append_csv(path: Path, case: AcceptanceCase, status: str, note: str, case_dir: Path, started: str, ended: str):
    exists = path.exists()
    with path.open("a", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        if not exists:
            writer.writerow(["Test ID", "Category", "Scenario", "Expected", "Status", "Started At", "Ended At", "Evidence Directory", "Operator Note"])
        writer.writerow([case.test_id, case.category, case.scenario, case.expected, status, started, ended, str(case_dir), note])


def main():
    parser = argparse.ArgumentParser(description="Interactive 23-case acceptance campaign")
    parser.add_argument("--start", help="Run this and following cases, e.g. TC-014")
    parser.add_argument("--only", help="Run exactly one case, e.g. TC-020")
    args = parser.parse_args()
    if not Path("app/agent/main.py").exists():
        raise SystemExit("Run this script from the repository root (containing app/agent/main.py).")
    ids = [c.test_id for c in CASES]
    if args.only and args.start:
        parser.error("Use --only OR --start, not both")
    requested = (args.only or args.start or "").upper()
    if requested and requested not in ids:
        parser.error(f"Unknown case {requested}; use TC-001 through TC-023")
    selected = ([next(c for c in CASES if c.test_id == requested)] if args.only else CASES[ids.index(requested):] if args.start else CASES)
    ensure_app()
    project = load_project()
    run_root = EVIDENCE_BASE / stamp()
    run_root.mkdir(parents=True, exist_ok=False)
    write_json(run_root / "campaign.json", {"started_at": utc_now(), "cases": [asdict(c) for c in selected], "target": TARGET_URL})
    csv_path = run_root / "campaign_results.csv"
    print("\n" + "═" * 72)
    print("COMPUTER-USE AUTOMATION — 23-CASE OPERATOR ACCEPTANCE CAMPAIGN")
    print("═" * 72)
    print(f"Cases: {len(selected)} | Evidence: {run_root}")
    print("Operator decides all approvals, interventions and case verdicts.")
    print(f"LLM-generated output names are recorded from drafts in: {CAPABILITY_MAP_FILE}")
    print("Miscellaneous cases can use any SUITABLE approved question/capability.")
    for number, case in enumerate(selected, 1):
        case_dir = run_root / case.test_id
        case_dir.mkdir(parents=True, exist_ok=True)
        write_json(case_dir / "scenario.json", asdict(case))
        while True:
            print("\n" + "═" * 72)
            print(f"{case.test_id} [{number}/{len(selected)}] {case.scenario}")
            print("═" * 72)
            print("Category: ", case.category)
            print("Setup:    ", case.setup)
            print("Goal:     ", case.goal)
            print("Expected: ", case.expected)
            if case.operator_note:
                print("Note:     ", case.operator_note)
            choice = input(f"Run {case.test_id}? [Y]es / [S]kip / [Q]uit: ").strip().lower()
            if choice in ("q", "quit"):
                print("Campaign paused; evidence at:", run_root)
                return
            if choice in ("s", "skip"):
                now = utc_now()
                append_csv(csv_path, case, "Skipped", "Skipped before execution.", case_dir, now, now)
                write_json(case_dir / "verdict.json", {"status": "Skipped", "at": now})
                break
            if not yes(choice):
                print("Choose Enter/y, s, or q.")
                continue
            started = utc_now()
            result = None
            exception = None
            try:
                result = RUNNERS[case.test_id](project, case_dir)
                write_json(case_dir / "result.json", result)
                hint = result_hint(result)
                if hint:
                    print("Observed:", hint)
            except KeyboardInterrupt:
                exception = "Operator interrupted this case with Ctrl+C."
                print("Case interrupted by operator.")
            except Exception:
                exception = traceback.format_exc()
                print("ERROR | Scenario raised an exception:\n", exception)
            if exception:
                (case_dir / "exception.txt").write_text(exception, encoding="utf-8")
            ended = utc_now()
            status, note = grade()
            if status == "Rerun":
                print("Rerunning; previous evidence is retained where applicable.")
                continue
            if status == "Quit":
                print("Campaign paused; evidence at:", run_root)
                return
            if exception and status == "Pass":
                print("WARNING: this scenario raised an exception. Only mark Pass if the exception itself is the documented EXPECTED safe failure and the evidence confirms it.")
            append_csv(csv_path, case, status, note, case_dir, started, ended)
            write_json(case_dir / "verdict.json", {"test_id": case.test_id, "status": status, "operator_note": note, "started_at": started, "ended_at": ended, "exception": bool(exception)})
            break
        if number < len(selected):
            next_case = selected[number].test_id
            if not yes(input(f"Continue to {next_case}? [Y/n]: ")):
                print("Campaign paused. Resume with --start", next_case, "(a NEW evidence run); current evidence at:", run_root)
                return
    print("\nCAMPAIGN COMPLETE | Results CSV:", csv_path)
    print("Evidence root:", run_root)


if __name__ == "__main__":
    main()
