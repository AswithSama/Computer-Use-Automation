# AI-Powered Browser Automation

**From a natural-language goal to a reviewed, reusable browser capability.** This repository implements a focused computer-use system for a local, simulated banking application. An LLM explores a live browser to accomplish a requested task; the successful path is recorded, checked, parameterized, and saved as a draft capability. A human explicitly approves the draft before the system can select it for subsequent deterministic replay. Replay uses the saved actions and verified extraction rules, rather than asking an LLM to plan each browser step again.

> **Scope:** This is a local demonstration using synthetic banking records, not an integration with a real financial institution. Browser/HTML-table automation is implemented; desktop adapters and cross-tenant artifact sharing are design extensions, not implemented features. Read [REPORT.md](REPORT.md) for design decisions, trade-offs, and deliberate cuts.

## 1. System at a glance

```text
User's natural-language goal
             |
             v
Orchestrator -> tenant/app-scoped approved capability registry
             |                                     |
       no valid match                           valid match
             |                                     |
             v                                     v
  LLM-driven discovery                      Deterministic replay
  observe -> propose ->                    resolve runtime inputs
  ground -> policy check ->                 -> execute saved actions
  execute -> verify -> record               -> verify checkpoints
             |                              -> extract unique outputs
             v                                     |
   verify input/output bindings                    v
   -> compile versioned artifact             structured result
   -> save DRAFT                                   |
             |                              business outcome / failure
             v
      HUMAN REVIEW / APPROVAL
             |
             v
     approved registry -> available to future requests

Cross-cutting: allowlists, redacted evidence, bounded execution, operator handoff.
```

The LLM is used to select an eligible capability or discover a new path, but *the application* validates selection, browser action proposals, input/output bindings, and execution permission. A successful discovery is not authorization for unattended use: the artifact remains a draft until explicitly approved. The registry scopes eligibility to a tenant and application.

## 2. Project structure

| Path | Purpose |
| --- | --- |
| `app/target_app/` | Local FastAPI/Jinja2 demo banking website and synthetic records. |
| `app/agent/main.py` | Interactive request entry point and local demo configuration. |
| `app/agent/orchestration/` | Approved-capability selection, discovery/replay routing, and path verification. |
| `app/agent/discovery/`, `app/agent/llm/`, `app/agent/validation/` | Live browser observation/action loop, structured model calls, proposal and outcome validation. |
| `app/agent/recording/` | Discovery trajectory, state fingerprints, loop removal, and verification-based minimization. |
| `app/agent/capability/`, `app/agent/schemas/` | Input/output binding, capability compilation, typed models, and checkpoints. |
| `app/agent/registry/` | Draft/approved artifact storage and terminal approval. |
| `app/agent/replay/` | Parameter resolution, deterministic execution, business outcomes, checkpoints, and structured results. |
| `app/agent/policy/`, `app/agent/handoff/`, `app/agent/observability/` | Action/route restrictions, same-session operator intervention, and run evidence. |
| `app/agent/test/` | Automated pytest tests. |
| `evidence/` | Saved acceptance-campaign results, example artifacts and handoff records. |

## 3. Setup

Run these commands **from the repository root**. Python 3.12 is the version indicated by the provided development archive's bytecode; the final published repository should state the Python version actually tested on a clean checkout.

```bash
python3 -m venv .venv
source .venv/bin/activate       # Windows PowerShell: .venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m playwright install chromium
```

Create a local `.env` file, **not committed to Git**. An optional `.env.example` can contain the following keys without real secrets:

```dotenv
OPENAI_API_KEY=replace_with_your_own_api_key
OPENAI_MODEL=gpt-5-mini
LOG_LEVEL=INFO
```

`OPENAI_MODEL` is optional; the uploaded client defaults to `gpt-5-mini`. The interactive main entry point calls the model-backed selector, and discovery requires model access; do not assume that `python -m app.agent.main` works fully offline. Unit tests with fakes may run without live model access. The live acceptance campaign's requirements depend on the cases being run. The demo uses synthetic data; never put real bank credentials or customer information into the repo, `.env.example`, artifacts, or evidence.

**Terminal 1 — start the local application:**

```bash
uvicorn app.target_app.main:app --host 127.0.0.1 --port 8000
```

Open `http://127.0.0.1:8000` to check that the local demo loads. The agent's checked-in demo settings target this URL, tenant `demo_tenant`, and app `demo_banking_app`; its policy allows the configured read-only member/account routes and blocks `/operations`.

**Terminal 2 — run the agent:** activate the same environment and use the repository root. Keep the first terminal running while driving the browser.

## 4. Demonstration: discover, approve, replay

### First request: discover a capability

```bash
python -m app.agent.main
```

At `What do you want to do?`, enter a goal using a **synthetic member ID present in the local demo data**, for example: `Get the savings balance for member 12345` (substitute an actual demo member ID if your checkout uses a different identifier). When no eligible approved capability matches, orchestration launches live LLM-driven discovery. The browser observes the app; proposed actions are grounded in the current observation, policy-checked, executed, and checked for observable outcomes. The recorder retains exploration evidence while deriving a candidate replay path. A subsequent verification pass may remove unnecessary steps only if the shorter path succeeds in a fresh browser session.

Successful discovery is followed by verified input/output binding and compilation of a **draft**, not an immediately reusable approved capability. The implementation currently verifies outputs using HTML table structure: find exactly one row using a meaningful column/value condition (for example, `Type = Savings`), then read a declared value column (`Current Balance`). The resulting artifact uses runtime placeholders such as `{{member_id}}`, not a hardcoded member ID and balance from the first run. A human-assisted discovery does not automatically become an autonomous draft.

### Approve a draft

```bash
python -m app.agent.registry.approve
```

The terminal reviewer sees the complete draft artifact and can **A**pprove, **S**kip, or **Q**uit. Approval saves an approved snapshot while leaving the original draft intact. Only eligible approved artifacts for the current tenant and application can be selected for future requests. **Human review of an artifact is distinct from operator handoff during a running browser session.**

### Request the operation for another member

```bash
python -m app.agent.main
```

Ask for the *same operation* using a different member ID that exists in the demo. The model-backed selector chooses among approved capabilities and proposes runtime inputs; the application validates that selection against the eligible catalog and declared contract. Once selected, replay executes the saved browser actions **without an LLM making the next browser-action decision**, checks application state at recorded checkpoints, and extracts a new output from the current member's page. A request for a different business operation may instead require its own discovery and approval.

**Important offline distinction:** the underlying replay engine is model-free, but the interactive `main.py` uses an LLM-backed capability selector. Do not advertise the complete interactive command as offline. To demonstrate a model-free invocation, call the replay path with an already selected approved artifact and supplied inputs, or use the acceptance runner if it provides that direct path.

## 5. Replay contract, safety, and recovery

A versioned capability has a semantic identity and description, typed required inputs, ordered actions with locator information, checkpoints, and typed outputs with deterministic extraction bindings. The registry additionally stores the tenant/application scope, approval state, version, selection context, and supported business-outcome rules. Review the actual schema in `app/agent/schemas/capability.py` and saved examples under `evidence/acceptance_campaign_23/`.

Before acting, replay checks the input contract and artifact references, resolves `{{...}}` placeholders, and enforces the active policy. It uses stored target roles/names and bounded waits; a missing or ambiguous target cannot silently become an arbitrary click. A completed click alone is not proof of task success: checkpoint verification requires the expected URL pattern and/or visible-text evidence. Output extraction must return **exactly one** matching value. The result is a structured `ReplayResult`, including status, outputs on success, completed/failed steps, machine-readable error or business-outcome codes, and sanitized evidence references when applicable.

The result contract distinguishes a valid `business_outcome` (for instance, a verified member-not-found condition) from `recoverable_failure` (such as a missing required input) and `hard_failure` (such as invalid artifact data or an unrecoverable checkpoint/output mismatch). It also supports `needs_intervention`. A timeout may have taken effect before the exception was raised; replay therefore does not blindly retry or skip uncertain actions. When a supported application-level obstacle requires an operator, automation pauses, transfers control of **the same live browser session**, records the intervention, and resumes only after an independently verified safe checkpoint. This is a deliberately bounded continuation path, not general-purpose human repair of arbitrary artifacts.

The policy restricts permitted origins, routes, browser actions, and, where configured, targets requiring additional handling. The demo's read-only policy does not authorize money movement. Discovery validation and artifact approval do not override the execution policy. Failure evidence uses restricted, reviewed diagnostic fields rather than unrestricted page text, input values, URLs, or raw exceptions; inspect any screenshots or logs before publishing them.

## 6. Tests and evaluator walkthrough

### Unit and component tests

```bash
python -m pytest app/agent/test -q
```

These tests cover architecture boundaries, trajectory/path handling, policy, replay behavior, and handoff components. They are separate from the live browser campaign; a passing pytest run does **not** replace the assignment's required genuine LLM-driven discovery evidence.

### Real-browser acceptance campaign

```bash
python run_acceptance_campaign_23.py
```

The author's organized documentation specifies the above command for the full **23-case** interactive campaign, and `python run_acceptance_campaign_23.py --only TC-016` for an individual case. **Packaging check:** the campaign script was referenced in the supplied README but was **not present in the uploaded source archive** used to prepare these documents. Include `run_acceptance_campaign_23.py` in the final public repository before representing these commands as runnable from a fresh checkout. Start the demo web server first, configure model access for model-dependent cases, and follow the prompts for approval and operator handoff.

For the clearest evaluation, read this README and run **TC-001 through TC-023 sequentially**, without starting in the middle: the early cases discover capabilities, the next cases approve/replay them, and subsequent cases test selection, outcomes, safe failure, and handoff. The `--only` option is useful for focused retesting but may require preexisting approved artifacts or other case-specific state; refer to the script's actual preconditions.

| Case(s) | Expected demonstration |
| --- | --- |
| TC-001–005 | Real-browser discovery of savings, checking, email, phone, and member-status capabilities. |
| TC-006–010 | Approval and deterministic replay of those operations with another member's data. |
| TC-011 | Select an eligible operation across varied natural-language requests. |
| TC-012 | Recognize verified savings-related business outcomes. |
| TC-013, TC-021 | Reject missing/malformed required input without inventing a member identifier. |
| TC-014 | Block navigation outside the permitted application. |
| TC-015–016 | Detect a checkpoint mismatch and demonstrate bounded, human-assisted checkpoint recovery. |
| TC-017–018 | Stop on missing/ambiguous action targets rather than clicking an unrelated target. |
| TC-019–020 | Fail on ambiguous/missing output rather than guessing or returning stale values. |
| TC-022 | Protect against returning information for the wrong member. |
| TC-023 | Serialize nested validator-LLM input data; **does not test a remote model response**. |

The supplied `evidence/acceptance_campaign_23/20260923_160221_123381/campaign_results.csv` records **23 passes out of 23 cases** in that saved campaign; these are historical results, not a claim that a new checkout has just been executed. A *passing safety test* can correctly end in a reported failure or business outcome rather than successfully retrieving a balance.

## 7. Evidence and inspection path

Start with `evidence/acceptance_campaign_23/20260923_160221_123381/campaign_results.csv` and the corresponding `campaign.json`. In the same run folder, `TC-001/` contains the savings discovery scenario, result, verdict, and a saved draft; `TC-006/` contains the savings replay scenario, result, verdict, and approved-artifact example. Inspect `TC-012/` for business outcomes, `TC-015/` for a checkpoint failure, `TC-016/` for checkpoint recovery plus handoff evidence, and `TC-017`–`TC-022` for targeting, extraction, and member-safety cases. `evidence/handoff/` includes additional handoff records and screenshots.

**Final evidence check:** the provided archive contains campaign evidence but no obvious standalone, full discovery-run and replay-run `.jsonl` logs for the named end-to-end demonstration. The implementation has a discovery logger that writes `evidence/discovery_*.jsonl`; include a sanitized genuine discovery log and a corresponding replay execution log in the final repo, with links here, to satisfy the assignment's explicit demonstration deliverable. Do not treat a saved result JSON alone as a full execution trace, and do not claim any missing files exist.

## 8. Scope and design report

Implemented scope: local web demo, LLM-guided browser discovery, grounded proposals, recorded/minimized paths, verified parameter/output bindings, draft/approval registry, deterministic browser replay, checkpoints, structured outcomes, policy enforcement, evidence, and bounded human intervention. Current output binding is table-specific. Actual desktop/screenshot control, automatic cross-tenant capability sharing, generalized UI adaptation and unrestricted AI recovery are *not* implemented. Proposed extension seams, trade-offs, and deliberate cuts are described in [REPORT.md](REPORT.md).

This project used AI-assisted coding while retaining engineering ownership of the design, integration, validation, and testing. The demo and supplied campaign are for evaluating a focused end-to-end vertical slice, not a production-ready banking integration.
