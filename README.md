# AI-Powered Browser Automation

> **Video Demonstration:** A short end-to-end video walkthrough of the system — covering live discovery, capability approval, deterministic replay, and the supporting evidence — will be added shortly.


**From a natural-language goal to an approved, reusable browser capability.**

This repository implements a focused end-to-end computer-use automation system against a local, simulated banking application.

The system uses an LLM to discover how to complete a browser task, records the verified workflow as a structured capability, requires explicit human approval, and later replays the approved capability with new runtime inputs without using an LLM to decide each browser action.

This README is intentionally limited to **setup, execution, demo instructions, and evidence**.

For the architecture and implementation walkthrough, see **[DEEPDIVE.md — System Architecture](DEEPDIVE.md#2-system-architecture)** and **[DEEPDIVE.md — Technical Deep Dive](DEEPDIVE.md#3-technical-deep-dive)**.

For design decisions, trade-offs, scope boundaries, and future extensions, see **[REPORT.md](REPORT.md)**.

---

## Setup

Run all commands from the repository root.

### 1. Create a virtual environment

```bash
python3 -m venv .venv
source .venv/bin/activate
```

Windows PowerShell:

```powershell
.venv\Scripts\Activate.ps1
```

### 2. Install dependencies

```bash
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m playwright install chromium
```

### 3. Configure environment variables

Create a local `.env` file:

```dotenv
OPENAI_API_KEY=replace_with_your_own_api_key
OPENAI_MODEL=gpt-5-mini
LOG_LEVEL=INFO
```

`OPENAI_API_KEY` is required for live discovery and the model-backed capability-selection path.

Do not commit `.env` or real secrets. The demo application uses synthetic banking data only.

---

## Start the local application

Open the first terminal and run:

```bash
uvicorn app.target_app.main:app --host 127.0.0.1 --port 8000
```

The demo application will be available at:

```text
http://127.0.0.1:8000
```

Keep this terminal running while using the agent.

---

## Demo path: discover → approve → replay

The following is the manual end-to-end path through the system.

### 1. Discover a capability

Open a second terminal, activate the environment, and run:

```bash
source .venv/bin/activate
python -m app.agent.main
```

At:

```text
What do you want to do?
```

enter a goal using a synthetic member ID available in the demo data.

Example:

```text
Get the savings balance for member 12345
```

If no eligible approved capability matches the request, the system starts a genuine LLM-driven browser discovery run.

The discovered workflow is validated, recorded, parameterized, and compiled into a **draft capability** rather than becoming immediately reusable.

For the detailed implementation, see:

**[DEEPDIVE.md — Discovery Workflow](DEEPDIVE.md#32-discovery-workflow)**

**[DEEPDIVE.md — Input and Output Binding](DEEPDIVE.md#33-input-and-output-binding)**

---

### 2. Approve the capability

Run:

```bash
python -m app.agent.registry.approve
```

The reviewer can inspect the generated draft and approve, skip, or quit.

Only an explicitly approved artifact becomes eligible for future reuse.

For the complete lifecycle, see:

**[DEEPDIVE.md — Capability Generation, Approval, and Storage](DEEPDIVE.md#34-capability-generation-approval-and-storage)**

---

### 3. Replay with a different input

Run the agent again:

```bash
python -m app.agent.main
```

Ask for the same operation using another synthetic member ID.

Example:

```text
Get the savings balance for member 67890
```

The approved capability is selected and supplied with the new runtime input.

Replay then executes the stored browser actions, verifies the expected checkpoints, and extracts the declared output from the current browser state.

The replay engine does **not** use an LLM to decide the next browser action. The interactive `main.py` entry point does use a model-backed capability selector before replay begins.

For the replay implementation and structured result handling, see:

**[DEEPDIVE.md — Replay Workflow](DEEPDIVE.md#35-replay-workflow)**

---

## Automated tests

Run:

```bash
python -m pytest app/agent/test -q
```

The test suite covers the implemented discovery, replay, policy, validation, handoff, failure-handling, and architecture-boundary behavior.

For the detailed testing strategy, see:

**[DEEPDIVE.md — Testing and Verification](DEEPDIVE.md#39-testing-and-verification)**

---

## Real-browser acceptance campaign

The repository includes a separate 23-case acceptance campaign:

```bash
python run_acceptance_campaign_23.py
```

For the clearest evaluation, run **TC-001 through TC-023 sequentially**. The sequence is connected: early cases discover capabilities, later cases approve and replay them, and the remaining cases exercise capability selection, business outcomes, policy enforcement, failure handling, output safety, and human intervention.

A focused case can also be run with:

```bash
python run_acceptance_campaign_23.py --only TC-016
```

Some focused cases may depend on artifacts or state created by earlier cases.

The saved acceptance campaign records **23 passes out of 23 cases**.

---

## Evidence

The repository includes evidence from the real-browser acceptance campaign under:

`evidence/acceptance_campaign_23/`

The campaign exercises 23 sequential cases across live discovery, capability approval, deterministic replay, capability selection, business outcomes, policy enforcement, runtime failures, output validation, and human-assisted recovery.

### Start here — core lifecycle evidence

For the fastest review of the required lifecycle, start with the representative discovery evidence, saved capability artifact, and corresponding replay case.

#### 1. Live LLM-driven discovery

A representative discovery execution log is included in the evidence directory:

`evidence/discovery_20260923_210223_303985.jsonl`

This JSONL trace records the discovery run chronologically: the original user request and target application, browser observations, LLM-proposed actions, policy decisions, deterministic grounding checks, executed browser actions, outcome validation, and the final grounded result.

For example, the retained trace shows the model proposing navigation to the Members module, followed separately by policy approval, deterministic target validation, actual execution, and validation of the resulting browser state. It then repeats that observe → propose → validate → execute → verify cycle until the requested savings balance is found and grounded in the observed page.

Detailed traces of this form were generated during the broader acceptance campaign. One representative trace is retained in the submitted evidence to demonstrate the discovery mechanism without adding many large, substantially repetitive raw execution logs. The acceptance campaign can be rerun to reproduce equivalent evidence for the other applicable cases.

#### 2. Saved capability artifact

The discovery flow produces a typed capability artifact that captures the reusable procedure rather than the original one-off interaction.

The corresponding saved/approved artifact can be inspected at:

`capabilities/demo_tenant/demo_banking_app/approved`

It contains the typed input contract, parameterized browser actions, stable targets, checkpoints, verified output binding, tenant/application scope, version information, and approval state used for subsequent replay.

#### 3. Deterministic replay

The corresponding replay case executes the approved capability with new runtime input rather than asking the LLM to rediscover the browser-action sequence.

Start with:

`evidence/acceptance_campaign_23/20260923_160221_123381/TC-006`

The submitted replay evidence includes the exact approved artifact used for execution, the replay scenario, the structured `ReplayResult`, and the case verdict. Together these show which stored capability was executed, the new runtime input supplied to it, whether the recorded actions and checkpoints completed successfully, and the structured output returned by replay.

A separate raw chronological replay trace is not included in the submitted evidence. Replay behavior is instead evidenced by the approved artifact plus the structured replay result and acceptance verdict, and can be reproduced directly by running the corresponding acceptance case.

### Why only one detailed discovery trace?

The acceptance campaign covers 23 cases, and detailed browser/discovery evidence can become large and repetitive. The submitted evidence therefore favors a **representative end-to-end trace plus structured results for the broader campaign** rather than committing every generated raw trace and browser-state snapshot.

This is an evidence-packaging decision, not a limitation of the discovery instrumentation. Running the campaign regenerates the applicable execution evidence.

For broader validation, inspect the campaign summary and individual case folders under:

`evidence/acceptance_campaign_23/`

The remaining cases exercise additional discovery paths, deterministic replay, capability selection, business outcomes, policy boundaries, missing inputs, checkpoint failures, missing or ambiguous targets, missing or ambiguous outputs, wrong-member protection, validator behavior, and human-assisted recovery.

Human-handoff evidence is additionally preserved under `evidence/handoff/`, including structured intervention records and available screenshots.


## Safety and handoff

The application enforces execution policy independently of the LLM and independently of capability approval. The local banking demo is read-only and blocks the configured `/operations` area.

When a supported condition requires intervention, automation can pause and transfer the **same live browser session** to a human operator. Replay resumes only after the required checkpoint is independently verified.

Implementation details are documented in:

**[DEEPDIVE.md — Failure Handling and Human Handoff](DEEPDIVE.md#37-failure-handling-and-human-handoff)**

**[DEEPDIVE.md — Security and Allowlisting](DEEPDIVE.md#38-security-and-allowlisting)**

---

## Scope

This submission implements one complete browser-based vertical slice. It does not claim implemented native-desktop automation, generalized screenshot/coordinate control, automatic cross-tenant capability reuse, automatic vendor-version drift handling, generalized non-table extraction, or unrestricted model-driven replay repair.

Those design extensions and the reasoning behind the project boundaries are documented in:

**[REPORT.md — Heterogeneity & Multi-tenant](REPORT.md#4-heterogeneity--multi-tenant)**

**[REPORT.md — Cuts](REPORT.md#7-cuts)**

---

## Where to read next

For the full internal execution flow:

**[DEEPDIVE.md — System Architecture](DEEPDIVE.md#2-system-architecture)**

For orchestration and capability selection:

**[DEEPDIVE.md — Orchestration](DEEPDIVE.md#31-orchestration)**

For discovery:

**[DEEPDIVE.md — Discovery Workflow](DEEPDIVE.md#32-discovery-workflow)**

For binding:

**[DEEPDIVE.md — Input and Output Binding](DEEPDIVE.md#33-input-and-output-binding)**

For capability approval and storage:

**[DEEPDIVE.md — Capability Generation, Approval, and Storage](DEEPDIVE.md#34-capability-generation-approval-and-storage)**

For replay:

**[DEEPDIVE.md — Replay Workflow](DEEPDIVE.md#35-replay-workflow)**

For grounding and validation:

**[DEEPDIVE.md — LLM Grounding and Validation](DEEPDIVE.md#36-llm-grounding-and-validation)**

For human handoff:

**[DEEPDIVE.md — Failure Handling and Human Handoff](DEEPDIVE.md#37-failure-handling-and-human-handoff)**

For policy and safety:

**[DEEPDIVE.md — Security and Allowlisting](DEEPDIVE.md#38-security-and-allowlisting)**

For tests:

**[DEEPDIVE.md — Testing and Verification](DEEPDIVE.md#39-testing-and-verification)**

For the required design discussion:

**[REPORT.md](REPORT.md)**
