# AI-Powered Browser Automation

**From a natural-language goal to an approved, reusable browser capability.**

> **Reading guide:** This README explains what I built, how the individual workflows connect, and the engineering decisions behind the implementation. Use the navigation below to jump to a specific stage, or read in order to follow one request from discovery through replay.

<details>
<summary><strong>Explore the implementation · jump to a section</strong></summary>

- [1. Introduction](#1-introduction)
- [2. System Architecture](#2-system-architecture)
- [3. Technical Deep Dive](#3-technical-deep-dive)
  - [3.1 Orchestration](#31-orchestration)
  - [3.2 Discovery Workflow](#32-discovery-workflow)
  - [3.3 Input and Output Binding](#33-input-and-output-binding)
  - [3.4 Capability Generation, Approval, and Storage](#34-capability-generation-approval-and-storage)
  - [3.5 Replay Workflow](#35-replay-workflow)
  - [3.6 LLM Grounding and Validation](#36-llm-grounding-and-validation)
  - [3.7 Failure Handling and Human Handoff](#37-failure-handling-and-human-handoff)
  - [3.8 Security and Allowlisting](#38-security-and-allowlisting)
  - [3.9 Testing and Verification](#39-testing-and-verification)
- [4. Execution Demonstration](#4-execution-demonstration)
- [Visual asset checklist](#visual-asset-checklist)

</details>

---

## 1. Introduction

This README provides a detailed technical walkthrough of my implementation of the browser automation assessment, focusing on the architecture, engineering decisions, execution workflows, and validation mechanisms that shaped the final system.

Rather than simply demonstrating that the project meets the assessment requirements, I want to provide insight into how I approached the underlying engineering challenges, the design decisions I made, and the reasoning behind them.

The implementation required careful consideration of several interconnected aspects: how workflows should be discovered, how inputs and outputs should be identified and bound, how browser interactions should be recorded, how discovered workflows should be transformed into reusable capabilities, and how approved capabilities should be executed reliably without repeating the discovery process.

Equally important were the decisions surrounding execution boundaries, human approval, failure handling, and validation. Each of these components was designed with consideration for how it would interact with the rest of the system, rather than being implemented as an isolated feature.

### A note on AI-assisted development

AI played a significant role in generating code and accelerating the implementation of this project. However, the architecture, requirements, system behavior, and major engineering decisions were carefully planned, evaluated, and refined throughout development.

My approach was to use AI as an implementation tool while maintaining ownership of the engineering process, from defining requirements and designing component interactions to evaluating implementation choices, identifying potential failure scenarios, and verifying the resulting behavior.

---

## 2. System Architecture

The following architecture diagram provides an overview of the system, illustrating how a natural language request moves through the orchestration layer, capability selection, AI-driven discovery, human approval, capability storage, and deterministic replay.

It also highlights the relationships between the major components and the execution paths that enable the system to discover new workflows and reuse previously approved capabilities.

> **DIAGRAM 01 PLACEHOLDER · End-to-end system architecture**  
> Show request intake → orchestration/eligibility → discovery OR approved replay → verified input/output bindings → compilation → draft review/approval → registry → replay/checkpoints/output. Include validation, policy, evidence and handoff as cross-cutting controls.  
> Suggested asset: `docs/assets/01-system-architecture.png`. Replace this callout with the real diagram or screenshot after adding the asset.

---

## 3. Technical Deep Dive

This section provides a detailed walkthrough of the system's implementation, focusing on how each component operates, the engineering decisions behind its design, and how it interacts with the rest of the architecture.

Rather than describing individual components in isolation, the following sections trace the execution lifecycle, from receiving a natural language request to discovering, approving, storing, and replaying a reusable browser automation capability.

Where relevant, architecture diagrams, code references, execution screenshots, and practical examples will be included to illustrate the implementation and the reasoning behind important design decisions.

**Follow the request:** orchestration → discovery → binding → capability lifecycle → replay. The remaining sections explain the grounding, failure recovery, policy, and tests that support those stages.

### 3.1 Orchestration

The orchestration layer determines whether a natural language request can be fulfilled using an existing approved capability or requires a new discovery workflow. The LLM evaluates the user's request against the eligible capabilities retrieved from the registry, using structured metadata such as capability descriptions, workflow summaries, example goals, declared inputs, and expected outputs. It identifies a matching capability and extracts the required runtime inputs. If a valid match is found, the orchestrator initiates deterministic replay; otherwise, it initiates AI-driven discovery. The LLM is responsible for capability selection, while the application validates its decision and controls execution.

#### LLM Capability Selection

The LLM receives a structured representation of the available capabilities. The following JSON illustrates the capability metadata used to support its selection decision:

```json
{
  "candidate_id": "candidate_1",
  "description": "Retrieve a member's savings balance",
  "example_goals": [
    "Get the savings balance of a member",
    "What is the savings balance for member 12345?"
  ],
  "inputs": [
    {
      "name": "member_id",
      "type": "string"
    }
  ],
  "outputs": [
    {
      "name": "savings_balance",
      "type": "string"
    }
  ]
}
```

Illustrative capability metadata. The exact selection payload is defined by the implementation.

The selection process separates the requested operation from its runtime values, allowing a capability discovered for one member to be reused for another without repeating discovery.

#### Scalability Consideration: RAG-Based Capability Retrieval

The current implementation evaluates eligible capabilities directly through the LLM. As the capability registry grows, passing the entire catalog to the model may introduce unnecessary token consumption and increase selection complexity.

A future enhancement is to introduce a Retrieval-Augmented Generation (RAG) architecture when the number of approved replayable capabilities exceeds 30. This configurable threshold is an initial design consideration rather than an experimentally established limit.

Under this proposed architecture, relevant capabilities would first be retrieved from the registry using semantic similarity to the user's request. The LLM would then evaluate only the shortlisted candidates to determine whether an existing capability can fulfill the request.

This enhancement has intentionally been left as a placeholder. The current implementation prioritizes engineering depth over feature breadth, focusing on the reliability of discovery, capability generation, approval, deterministic replay, and validation before introducing additional retrieval infrastructure.

> **SCREENSHOT 01 PLACEHOLDER · Capability selection in the terminal**  
> Show a paraphrased request matching an eligible approved capability, with the selected capability name and extracted runtime input (avoid real member data).  
> Suggested asset: `docs/assets/02-orchestrator-capability-selection.png`. Replace this callout with the real diagram or screenshot after adding the asset.

### 3.2 Discovery Workflow

The discovery workflow follows an iterative observe–decide–validate–execute cycle. At each step, Playwright captures the current browser observation, which the LLM uses to determine the next action required to complete the user's request. Rather than allowing the LLM to execute arbitrary browser operations, its proposed actions pass through the application's policy and validation mechanisms before being executed through Playwright. Following execution, the system captures the resulting browser state and validates the action's outcome before recording a successful transition. This cycle continues until the task is completed or an execution condition requires the process to stop.

> **DIAGRAM 02 PLACEHOLDER · Discovery control loop**  
> Illustrate observe → LLM proposes → policy/grounding checks → Playwright action → post-action observation/outcome check → successful transition recorded → next step/finish/handoff.  
> Suggested asset: `docs/assets/03-discovery-loop.png`. Replace this callout with the real diagram or screenshot after adding the asset.

> **SCREENSHOT 02 PLACEHOLDER · Discovery in a real browser**  
> Capture the browser alongside representative terminal output showing one observation and proposed action, and the same action executed in the application.  
> Suggested asset: `docs/assets/04-discovery-browser.png`. Replace this callout with the real diagram or screenshot after adding the asset.

#### State Recording and Fingerprinting

One of the key engineering considerations was preserving the complete discovery history while maintaining a separate, shorter path suitable for deterministic replay.

To achieve this, I implemented a TrajectoryRecorder that maintains three structures: an immutable-by-design execution history, a stack of browser states belonging to the current candidate path, and a corresponding stack of recorded actions. Each successfully executed and validated transition is preserved in the execution trace, while the candidate path is updated as discovery progresses. 

Each recorded state contains the browser URL, its accessibility observation, and a deterministic fingerprint. The fingerprint is generated using SHA-256 over the URL and normalized observation. Temporary Playwright element references and inconsistent whitespace are removed before hashing, allowing the system to recognize the same observable browser state even when transient element references change between visits.

The fingerprint construction logic is:

```python
def build_state_fingerprint(

    url: str,

    observation: str,

) -> str:

    normalized_observation = normalize_observation(observation)

    state_content = f"{url}|{normalized_observation}"

    return hashlib.sha256(

        state_content.encode("utf-8")

    ).hexdigest()
```

#### Stack-Based Loop Removal

During discovery, the LLM may explore an unnecessary navigation path before returning to a previously visited browser state. Rather than preserving this entire sequence in the candidate workflow, the recorder uses the state fingerprints to identify navigation loops and remove the corresponding transitions from the candidate path.

For example, consider the following exploration:

```text
A → B → C → B
```

When the system returns to state B, its fingerprint matches an earlier state in the current stack. The recorder removes the intermediate transitions, reducing the candidate path to:

```text
A → B
```

The complete execution trace still preserves the original exploration, including the removed transitions. This allows the system to retain the actual discovery history while maintaining a simplified candidate workflow. 

An important distinction is that an action producing the same observable state is not automatically considered redundant. For example, a successful input action may be necessary for replay even if it does not change the generated fingerprint. Such actions are preserved rather than being incorrectly classified as navigation loops.

> **DIAGRAM 03 PLACEHOLDER · State-stack loop removal**  
> Illustrate A → B → C → B, show how the candidate stack contracts to A → B while the full execution trace still retains the exploratory transitions. Include an annotation that necessary same-state actions are preserved.  
> Suggested asset: `docs/assets/05-state-stack-loop-removal.png`. Replace this callout with the real diagram or screenshot after adding the asset.

#### Verification-Based Path Minimization

Stack-based loop removal handles repeated states, but unnecessary actions may also exist within a sequence of distinct browser states.

To address this, I implemented a separate path-minimization process that identifies consecutive same-page interactions as potential optimization candidates. The minimizer attempts to remove actions individually, but a removal is accepted only when the shortened workflow successfully passes deterministic verification. 

Verification uses a fresh browser session to reproduce the original starting state, execute the proposed action sequence under the applicable execution policy, and confirm that the final observable state matches the original successful discovery. If verification fails, the proposed removal is rejected. The optimization process retains the original candidate path if the shortened workflow cannot be accepted. 

This two-stage approach separates structural loop removal from execution-verified optimization, allowing the system to simplify exploratory workflows without relying solely on the LLM's judgment about which actions are necessary.

> **DIAGRAM 04 PLACEHOLDER · Verified path minimization**  
> Contrast the original candidate path with a shortened proposal tested in a fresh browser session; show accept-on-verification and retain-original-on-failure branches.  
> Suggested asset: `docs/assets/06-verified-path-minimization.png`. Replace this callout with the real diagram or screenshot after adding the asset.

### 3.3 Input and Output Binding

Once discovery successfully completes a task, the next challenge is transforming the recorded browser interactions into a reusable workflow. This requires identifying which values should change between executions and establishing reliable rules for retrieving the requested outputs.

Rather than relying entirely on the LLM's interpretation, the system uses a proposal-and-verification approach: AI identifies potential input parameters and output relationships, while deterministic verification ensures that the proposed bindings are supported by the recorded interactions and observed browser structure.

#### Input Binding

The InputExtractorLLM identifies reusable runtime inputs from the successful discovery path. An important design decision is that only values explicitly supplied through successful FILL interactions and present in the original user request are considered eligible input evidence.

For example, in the request "Get the savings balance for member 12345," the member ID is a reusable input because it was explicitly supplied to the application. However, "Savings" describes the operation being performed and should not automatically become a runtime parameter. This prevents the LLM from introducing unsupported inputs based solely on words appearing in the request.

Each proposed input includes its name, type, observed value, and source interaction step. The InputVerifier then checks the proposal against the recorded discovery evidence before accepting it.

During capability compilation, the verified input is converted into a parameterized value:

```python
if input_candidate is not None:

    value = f"{{{{{input_candidate.name}}}}}"
```

For example, a recorded action containing the literal value 12345 becomes an action referencing {{member_id}}. The compiler also parameterizes matching input values in navigation URLs and supported checkpoint patterns, allowing the same workflow to execute with new runtime inputs.

#### Output Binding

Output binding presented a different engineering challenge: the system must identify the correct output during future executions, even when the underlying data changes.

The OutputLocatorBuilder first identifies the observed output in the browser DOM and collects its surrounding structural context, including table headers, the containing row, and the column holding the output value.

The OutputBindingLLM then uses this evidence, along with the original request and available input evidence, to propose a reusable extraction rule. Its responsibility is to identify the structural relationship that represents what the user requested, rather than simply locating a value that happened to appear during discovery. 

For example, consider a table containing the following information:

| Account | Type | Nickname | Current Balance |
| --- | --- | --- | ---: |
| SAV-40082 | Savings | Holiday Fund | $630.00 |
| CHK-50021 | Checking | Daily Expenses | $240.00 |

If the user requests the savings balance, the system should identify the row using the account's Type rather than its account number, nickname, or current balance.

The proposed reusable output binding would be:

```json
{

  "kind": "table",

  "row_match": {

    "column": "Type",

    "value": "Savings"

  },

  "value_column": "Current Balance"

}
```

This design separates the identity of the requested record from incidental values that may change between executions.

For output requests identified by a runtime input, the compiler can also replace the verified row-matching value with its corresponding input placeholder. For example, a row condition matching member 12345 can become a condition matching {{member_id}}.

> **SCREENSHOT 03 PLACEHOLDER · Browser evidence for output binding**  
> Show the real HTML table and identify the row-match column/value and output column visually. Use demo fixture data only.  
> Suggested asset: `docs/assets/07-output-table-binding.png`. Replace this callout with the real diagram or screenshot after adding the asset.

#### From AI Proposals to Verified Bindings

The LLM does not have the authority to directly commit its proposed output-binding rule to a reusable capability.

The OutputBindingVerifier checks that the proposed columns and row-matching values exist in the observed table, executes the proposed extraction rule against the live DOM, and verifies that it resolves to exactly one value matching the original discovery output. Unsupported, ambiguous, or incorrectly resolved bindings are rejected.

Once the input definitions and output bindings have been verified, the capability compiler incorporates them into the reusable capability alongside its parameterized browser actions and execution checkpoints.

The central design principle is to preserve how the requested information was obtained, rather than preserving the particular values observed during discovery. This allows the system to reuse the same approved workflow across different runtime inputs and changing application data.

**Implementation scope — table bindings only.** The current implementation supports table-based output bindings, with other HTML component types intentionally left outside the project scope to prioritize engineering depth over breadth. The same binding and verification approach can be extended to additional HTML components, while the grounding mechanisms, validation safeguards, and failure-handling strategies are discussed in the dedicated Validation section.

> **SCREENSHOT 04 PLACEHOLDER · Verified binding evidence**  
> Show a binding proposal and its observed DOM verification result (unique matching row and extracted value), with test data redacted where needed.  
> Suggested asset: `docs/assets/08-binding-verification.png`. Replace this callout with the real diagram or screenshot after adding the asset.

### 3.4 Capability Generation, Approval, and Storage

Once discovery is successfully completed and the required inputs and output bindings have been verified, the system transforms the discovered workflow into a structured, reusable capability. This process separates the original exploratory browser session from the execution contract that will be used during future requests.

#### Capability Generation

The CapabilityCompiler converts the verified discovery results into a CapabilityArtifact, containing the capability identity, declared inputs, parameterized browser actions, execution checkpoints, and output bindings. Rather than preserving the original request-specific values, the compiler replaces them with runtime placeholders such as {{member_id}}. It also converts discovered URL transitions into replay checkpoints, preserving the expected navigation behavior while allowing the same workflow to operate with different inputs.

An additional design decision is to generate the capability identity independently of the original request's runtime values. The CapabilityIdentityGenerator uses the requested operation and verified inputs and outputs to produce a semantic identifier and description. This allows capabilities to represent distinct business operations even when their browser navigation paths are identical.

The following JSON excerpt illustrates how the resulting artifact represents a reusable checking-balance operation:

<details>
<summary><strong>Inspect the simplified capability artifact (JSON)</strong></summary>

```json
{
  "capability_id": "get_current_checking_balance",
  "inputs": [
    {
      "name": "member_id",
      "type": "string",
      "required": true
    }
  ],
  "actions": [
    {
      "action": "fill",
      "target": {
        "role": "textbox",
        "name": "Member ID"
      },
      "value": "{{member_id}}"
    }
  ],
  "checkpoints": [
    {
      "after_action": 4,
      "url_pattern": "/members/{{member_id}}"
    }
  ],
  "outputs": [
    {
      "name": "checking_balance",
      "type": "currency",
      "binding": {
        "kind": "table",
        "row_match": {
          "column": "Type",
          "value": "Checking"
        },
        "value_column": "Current Balance"
      }
    }
  ]
}
```

</details>

Simplified excerpt from the generated capability artifact. Intermediate actions, checkpoints, and additional metadata are omitted for readability.

> **SCREENSHOT 05 PLACEHOLDER · Generated draft capability**  
> Show a real draft artifact with the input placeholder, actions, checkpoints, table output binding, and draft status; redact any sensitive data.  
> Suggested asset: `docs/assets/09-draft-capability-json.png`. Replace this callout with the real diagram or screenshot after adding the asset.

#### Human Approval

After compilation, the system generates additional selection metadata and stores the capability with a draft approval status. This establishes a clear separation between successfully discovering a workflow and authorizing that workflow for future execution.

Human approval is a separate operation rather than an automatic consequence of successful discovery. The approved artifact can then be considered for subsequent execution through the capability registry.

An important safeguard is that a discovery requiring human assistance does not automatically produce an autonomous capability draft. Similarly, the system does not save an executable draft if the required output bindings are incomplete or input verification fails.

Capability approval and human intervention during browser execution are separate workflows. Approval is managed by the registry; the `handoff` module manages temporary operator control during discovery or replay and does not authorize a capability for future reuse. The original draft is preserved when the approved snapshot is created.

Once the capability has been compiled and saved as a draft, it enters a separate human approval process. The approve.py module provides a terminal-based review interface that retrieves pending capabilities and presents the complete artifact, including its execution actions, input definitions, checkpoints, output bindings, and selection metadata.

The operator can approve the capability, skip it to leave it pending, or exit the review process. Approval is an explicit authorization step rather than an automatic consequence of successful discovery, ensuring that newly generated workflows cannot immediately become available for autonomous replay.

> **SCREENSHOT 06 PLACEHOLDER · Operator reviews and approves a draft**  
> Capture the terminal review showing the generated draft and the operator approving it, or a paired before/after showing draft → approved.  
> Suggested asset: `docs/assets/10-capability-approval.png`. Replace this callout with the real diagram or screenshot after adding the asset.

#### Capability Storage and Versioning

The registry provides persistent storage for generated capabilities, maintaining their execution definitions alongside the metadata required for future selection.

The stored capability contains the tenant and application identifiers, approval status, version, executable artifact, selection context, and applicable business outcome rules.

The SelectionContextGenerator creates three additional fields from the compiled workflow: use_when, which describes when the capability should be selected; workflow_summary, which summarizes the operation; and example_goals, which provides alternative natural language requests that the same capability can fulfill.

This separates the information required for capability selection from the instructions required for browser execution. The orchestrator can identify the appropriate operation using concise semantic metadata, while the replay engine uses the stored execution contract.

The supplied draft and approved examples illustrate the distinction between the two lifecycle states. Both retain the same execution definition and selection metadata, while their approval_status fields identify whether the capability is awaiting review or has been approved for reuse.

The CapabilityRegistry manages the persistent lifecycle of generated capabilities through a file-based JSON registry, organized by tenant, application, and approval status.

Newly generated capabilities are stored in the drafts directory. When a capability is approved, the registry creates a separate approved snapshot while preserving the original draft. This provides a clear separation between the generated artifact and the version authorized for future execution.

The registry also maintains capability version numbers, assigning a new draft a version based on the highest existing approved version of the same capability within the relevant tenant and application. Approval checks prevent a duplicate capability ID and version from being approved within that scope. 

The registry organizes stored artifacts using the following directory structure:

```text
capabilities/
└── <tenant_id>/
    └── <app_id>/
        ├── drafts/
        │   └── <capability_id>_<unique_id>.json
        └── approved/
            └── <capability_id>_v<version>_approved_<unique_id>.json
```

> **SCREENSHOT 07 PLACEHOLDER · File-based registry and approved snapshot**  
> Show the tenant/application drafts and approved directories plus an approved snapshot retaining its version and status; avoid displaying any real PII.  
> Suggested asset: `docs/assets/11-capability-registry.png`. Replace this callout with the real diagram or screenshot after adding the asset.

#### Capability Eligibility and Reuse

When the orchestrator receives a new request, it retrieves capabilities through the registry's list_eligible() method, scoped to the current tenant and application.

A capability is considered eligible only when it resides in the corresponding approved directory and its stored tenant ID, application ID, and approval status match the requested execution context. Draft capabilities are excluded from selection, regardless of whether discovery was completed successfully.

This design ensures that capability reuse is governed by the application's approval lifecycle rather than by the LLM's decision alone. Only eligible capabilities are presented to the capability selector for matching against subsequent natural language requests.

When a new request is received, the orchestrator retrieves eligible capabilities from the registry using the current tenant and application identifiers.

The CapabilitySelector then evaluates the request against the available capability descriptions, selection context, declared inputs, and expected outputs. If a matching capability is identified, the orchestrator retrieves its stored artifact and forwards it, together with the extracted runtime inputs and applicable execution policy, to the deterministic replay workflow.

If no eligible capability matches the request, the orchestrator initiates discovery instead. This completes the capability lifecycle, allowing previously discovered and approved browser workflows to be reused without repeating the original AI-driven exploration.

### 3.5 Replay Workflow

The replay workflow transforms an approved capability into a repeatable browser execution process without requiring the LLM to rediscover the original workflow. Once the orchestrator selects an eligible capability, the replay engine receives its stored artifact, runtime inputs, and execution policy. It then executes the recorded browser actions in sequence, using the capability's parameterized instructions, checkpoints, and verified output bindings to reproduce the intended operation.

A key design decision is the separation between AI-driven discovery and deterministic replay. The LLM identifies and helps construct the workflow during discovery, but replay does not depend on the LLM deciding the next browser action. Instead, the system follows the previously approved execution contract, verifies the application's behavior at defined checkpoints, and extracts the requested output only after the required execution steps have succeeded.

#### Parameter Resolution and Execution

Before execution begins, the ReplayEngine performs preflight checks to confirm that all required inputs are available, checkpoint references are valid, and the initial browser state is permitted by the execution policy. If a required input is missing, replay returns a recoverable result requesting the missing information instead of proceeding with an incomplete workflow.

The ParameterResolver substitutes runtime values into the stored actions. For example, when the user requests the checking balance of member 67890, the recorded placeholder {{member_id}} is replaced with 67890 before the corresponding browser action is executed. This allows the same approved capability to operate on different records without modifying its stored execution definition.

The following excerpt illustrates the parameter resolution mechanism:

```python
def resolve_action(
    self,
    action: CapabilityAction,
    inputs: dict[str, str],
) -> CapabilityAction:
    resolved_value = self._resolve_text(
        action.value,
        inputs,
    )
    resolved_url = self._resolve_text(
        action.url,
        inputs,
    )
    return action.model_copy(
        update={
            "value": resolved_value,
            "url": resolved_url,
        }
    )
```

Once the runtime values have been resolved, the ReplayActionExecutor performs the recorded actions through Playwright. The current implementation supports CLICK, FILL, NAVIGATE, and WAIT operations. Each action is executed in its original recorded order, and the replay engine advances to the next step only after the current action and its associated execution checks have succeeded.

> **SCREENSHOT 08 PLACEHOLDER · Deterministic replay with a new input**  
> Show the previously approved capability reused with a member ID different from discovery, the replay actions, and the returned structured output.  
> Suggested asset: `docs/assets/12-cross-member-replay.png`. Replace this callout with the real diagram or screenshot after adding the asset.

#### Checkpoint Verification

Successfully performing a browser action does not necessarily mean that the application reached the expected state. For this reason, the replay workflow uses execution checkpoints to verify the application's behavior at predefined stages.

Each checkpoint is associated with a recorded action and may contain an expected URL pattern, required visible text, or both. The CheckpointValidator resolves any runtime placeholders, waits for the expected conditions within a bounded timeout, and verifies the resulting browser state before allowing execution to proceed.

For example, after searching for member 67890, a checkpoint containing /members?member_id={{member_id}} is resolved to the expected member-specific URL. The replay engine verifies that the application has reached that route rather than assuming that the search action succeeded merely because Playwright completed the click.

This separates the successful execution of a browser interaction from verification of its expected application outcome.

> **SCREENSHOT 09 PLACEHOLDER · Checkpoint verification**  
> Show the member-specific destination URL or checkpoint evidence together with the replay checkpoint confirmation; use demo data.  
> Suggested asset: `docs/assets/13-replay-checkpoint.png`. Replace this callout with the real diagram or screenshot after adding the asset.

#### Deterministic Output Extraction

Once all recorded actions and their associated checkpoints have completed successfully, the replay engine extracts the requested outputs using the verified bindings stored in the capability artifact.

The current implementation supports table-based output extraction. Rather than returning a previously observed value or relying on a fixed row position, the engine locates the table containing the required columns, identifies the row matching the stored condition, and retrieves the corresponding output value.

For example, a checking-balance capability identifies the row where Type = Checking and extracts the value from the Current Balance column. The extracted value is returned as part of the structured ReplayResult.

The replay engine requires each declared output binding to resolve to exactly one value. Missing or ambiguous outputs prevent the execution from being reported as successful.

#### Execution Results and Recovery

The replay workflow returns a structured result containing the execution status, completed step count, extracted outputs when successful, and relevant failure information when execution cannot proceed.

An important design consideration is that replay does not automatically rediscover the workflow, skip failed actions, or blindly retry browser interactions when an unexpected condition occurs. Instead, the system distinguishes between missing inputs, application-level business outcomes, execution failures, and situations requiring human intervention.

The detailed mechanisms for failure classification, evidence recording, human handoff, and safe continuation will be explained in the dedicated Failure Handling and Recovery section.

### 3.6 LLM Grounding and Validation

One of the central engineering decisions in this project was ensuring that LLM-generated decisions are grounded in observable application evidence rather than being executed solely on the model's interpretation. To achieve this, I implemented multiple validation layers across discovery, input and output binding, capability selection, and replay. Each layer validates a different aspect of the workflow, establishing a clear separation between what the LLM proposes, what the application can verify, and what is permitted to execute.

#### Action Validation and Grounding

During discovery, the ActionValidator evaluates every proposed browser action before execution. For interactive actions, it checks that the target reference, role, and accessible name correspond to the same element in the current browser observation. For FILL actions, it additionally verifies that the proposed value is grounded in either the original user request or the current page observation. Navigation actions are checked against the current host, and consecutive duplicate actions are rejected to prevent unnecessary repetition. 

An important design decision is that deterministic validation does not have to make a forced approval or rejection when the evidence is insufficient. Instead, the validator returns one of three possible statuses:

```python
class ValidationStatus(str, Enum):

    APPROVED = "approved"

    REJECTED = "rejected"

    NEEDS_LLM = "needs_llm"
```

When a proposed value cannot be directly grounded in the available evidence, the system invokes a separate ValueValidatorLLM. This validator receives the proposed action, original request, browser observation, deterministic validation reason, and applicable business validation policy. Its responsibility is limited to evaluating the proposed value; it cannot generate replacement values or propose additional browser actions.

The validator returns a structured decision of approve, reject, or escalate_to_human. Rejected actions are not executed, while unresolved decisions can trigger human intervention. This provides a controlled evaluation path for values that require contextual reasoning beyond direct evidence matching.

> **DIAGRAM 05 PLACEHOLDER · LLM proposal versus execution authority**  
> Show LLM proposal → deterministic grounding (approve/reject/needs LLM) → bounded value validator when needed (approve/reject/escalate) → policy check → Playwright, with explicit stop/handoff routes.  
> Suggested asset: `docs/assets/14-grounding-decision-boundaries.png`. Replace this callout with the real diagram or screenshot after adding the asset.

#### Post-Execution Validation

Validation does not end when Playwright successfully executes an action. The OutcomeValidator compares the browser state before and after execution to determine whether the action produced an expected observable result.

For example, navigation is expected to change the URL, while a click or browser-back action is expected to produce an observable change in the page or URL. FILL and WAIT operations are treated differently because they may complete successfully without producing a meaningful change in the accessibility snapshot.

Only transitions that satisfy the applicable outcome checks are added to the successful discovery trajectory. Invalid outcomes are handled through the discovery workflow's retry and failure-limit mechanisms rather than being accepted as successful transitions.

#### Input and Output Binding Validation

The grounding process continues when discovered interactions are transformed into reusable capability inputs and outputs.

The InputVerifier ensures that proposed runtime inputs originate from successful FILL interactions, that their source steps exist in the recorded discovery path, and that their observed values match both the recorded interaction and the original user request. This prevents the LLM from introducing unsupported runtime parameters into a reusable capability.

For output binding, the OutputBindingVerifier validates the proposed table structure, row-matching condition, and output column against the observed DOM. It then executes the proposed extraction rule against the live page and requires exactly one matching result that agrees with the original discovery output.

A proposed binding that references nonexistent columns, resolves to multiple values, or retrieves an incorrect value is rejected rather than being incorporated into the capability artifact.

#### Capability Selection and Replay Validation

Grounding also extends beyond discovery. When the orchestrator uses the LLM to select an existing capability, the selection response is validated against the eligible capability catalog and the selected artifact's declared input contract. Invalid candidate identifiers and undeclared input names are rejected before execution begins.

During replay, the system independently validates required runtime inputs, action targets, execution policies, checkpoints, and output extraction results. Missing or ambiguous browser targets are not executed, checkpoint mismatches prevent normal progression, and output extraction must resolve to a unique result. These checks ensure that successful discovery and human approval do not eliminate the need to verify actual application behavior during subsequent executions. 

The underlying design principle is that AI contributes reasoning and proposes actions, while application-controlled validation determines whether those proposals are supported by the available evidence and can proceed through the execution lifecycle.

> **SCREENSHOT 10 PLACEHOLDER · A proposed action rejected by grounding**  
> Show a controlled test with the proposed action, the reason validation rejected or escalated it, and evidence that the browser action was not executed.  
> Suggested asset: `docs/assets/15-grounding-rejection.png`. Replace this callout with the real diagram or screenshot after adding the asset.

### 3.7 Failure Handling and Human Handoff

A key engineering consideration in this project was distinguishing between an unsuccessful business outcome and a technical execution failure. A browser workflow may execute correctly but return an application-level result that differs from the requested output. Conversely, an execution may fail because the application has changed, a required input is missing, or the system can no longer safely determine the current browser state.

The failure-handling architecture distinguishes between business outcomes, recoverable failures, and unrecoverable failures. Rather than automatically retrying every unsuccessful operation, the system uses structured execution results to determine whether it should return an application-level outcome, request additional information, transfer control to a human, or terminate execution safely.

#### Business Outcomes

A business outcome occurs when the application returns a valid, expected result that prevents the requested operation from producing its normal output. For example, the requested member may not exist, or a member may not have the requested savings account. These conditions should not automatically be classified as technical execution failures.

The BusinessOutcomeDetector evaluates predefined rules against the current browser state. These rules use evidence such as the expected URL, visible application messages, and the absence of a matching row in an otherwise valid table. When a configured rule matches, the replay engine returns a structured business_outcome result containing the corresponding outcome code and reason, rather than continuing with normal execution or reporting an output extraction failure. 

The initial implementation includes explicit rules for recognizing a missing member and the absence of a savings account in the supported savings-balance workflow. Business outcomes are recognized only when the configured evidence conditions are satisfied; an arbitrary missing output is not treated as proof that the requested record does not exist.

> **SCREENSHOT 11 PLACEHOLDER · Recognized business outcome**  
> Capture a nonexistent-member or missing-savings-account scenario and its structured business-outcome result. Show that it is not classified as a generic crash.  
> Suggested asset: `docs/assets/16-business-outcome.png`. Replace this callout with the real diagram or screenshot after adding the asset.

#### Recoverable Failures

Recoverable failures represent conditions for which the system has a defined path toward continuing execution safely.

For example, when required runtime inputs are missing, the replay engine returns a recoverable_failure result with a request_input recovery action. This allows the missing information to be requested before another execution attempt, rather than proceeding with an incomplete capability invocation. 

The recovery architecture also supports human-assisted resolution of certain application-level execution problems. However, recovery does not mean that every failed action can be automatically repeated or skipped. The system evaluates whether a valid recovery path exists before permitting execution to continue.

#### Unrecoverable Failures

An unrecoverable failure occurs when the system cannot establish a safe continuation path or encounters a condition that cannot be corrected through the supported recovery mechanisms.

Examples include invalid capability artifacts, unresolved parameter references, policy violations, checkpoint failures, and output extraction errors. These conditions are represented through structured hard_failure results that identify the failure category, error code, affected execution step, and number of successfully completed steps.

A particularly important consideration is handling uncertain browser actions. If an interaction times out, the system cannot always determine whether its effect was applied before the timeout occurred. Blindly retrying the action could therefore produce unintended behavior.

The current implementation does not automatically retry or skip failed actions. If execution cannot be safely resumed through an explicitly supported recovery path, the system terminates the replay and records the failure rather than continuing from an uncertain state.

> **SCREENSHOT 12 PLACEHOLDER · Controlled hard failure**  
> Show an impossible checkpoint, policy denial, or ambiguous output resulting in a structured hard_failure with error code, step and evidence reference.  
> Suggested asset: `docs/assets/17-hard-failure.png`. Replace this callout with the real diagram or screenshot after adding the asset.

#### Human Handoff and Safe Continuation

The HumanHandoffManager provides a controlled mechanism for transferring execution to a human operator when automation cannot safely proceed.

When an eligible application-level failure occurs, the system pauses automation, preserves the live browser session, records the intervention context, and transfers control to the operator. The operator can inspect the application and attempt to resolve the condition without requiring the entire workflow to be rediscovered.

Human intervention does not automatically authorize the system to resume execution. After the operator reports that the issue has been resolved, the system must independently verify that the application has reached a state from which execution can safely continue. For the supported checkpoint-based replay continuation path, this requires the relevant URL and visible-text checkpoint evidence to be satisfied. If verification fails, the intervention is cancelled or execution terminates safely. 

The recovery policy also distinguishes application-level conditions from failures involving the automation runtime, capability artifact, input contract, or execution policy. Conditions that cannot be corrected by interacting with the live application are directed toward failure reporting rather than unnecessary human intervention.

> **SCREENSHOT 13 PLACEHOLDER · Human intervention in the same live session**  
> Capture the paused terminal operator prompt, reason, step and screenshot/evidence reference, alongside the browser window that the human takes over.  
> Suggested asset: `docs/assets/18-human-handoff.png`. Replace this callout with the real diagram or screenshot after adding the asset.

> **SCREENSHOT 14 PLACEHOLDER · Verified return to automation**  
> Capture an operator-completed intervention followed by successful checkpoint verification and resumed replay with human_assisted=true. Do not substitute the operator's manually observed value for the extractor output.  
> Suggested asset: `docs/assets/19-human-assisted-resume.png`. Replace this callout with the real diagram or screenshot after adding the asset.

#### Failure Evidence and Traceability

The ReplayEvidenceRecorder preserves diagnostic information when replay fails, including structured failure reports and, where available, sanitized browser-structure snapshots.

The evidence records are intentionally restricted to reviewed diagnostic fields rather than unrestricted browser content. Sensitive information such as raw input values, page text, URLs, and unfiltered exception messages is excluded from the persisted failure reports and structural snapshots.

This enables failed executions to be investigated while limiting unnecessary exposure of application data.

The underlying design principle is to treat recovery as a verified execution decision rather than an automatic response to failure. The system should return a recognized business outcome when appropriate, recover through a defined mechanism when possible, and stop execution when the required conditions for safe continuation cannot be established.

### 3.8 Security and Allowlisting

#### Policy-Driven Execution Boundaries

The PolicyEngine implements a deterministic allowlist that controls browser execution independently of the LLM. Before an action is executed, the system evaluates the current application URL, requested action type, target element, and applicable policy profile. This ensures that an action is not permitted simply because it was proposed by the LLM or successfully grounded in the browser observation.

An important design decision is the separation between global application permissions and workflow-specific policy profiles. Global permissions establish the maximum execution boundaries, while individual profiles can introduce additional restrictions but cannot expand those permissions. The same policy mechanism can therefore support different execution requirements during discovery and replay.

#### Application and Route Allowlisting

The system restricts browser execution to explicitly permitted application origins and routes. The policy engine validates the URL's scheme, hostname, and port, preventing execution outside the configured application environment.

Route restrictions are evaluated separately, allowing specific application areas to be accessible while prohibiting others. Explicit navigation actions are checked against both the current page and the intended destination.

The current demo banking policy includes the following restrictions:

```json
{
  "allowed_origins": [
    "http://127.0.0.1:8000"
  ],
  "allowed_routes": [
    "/",
    "/members",
    "/members/*",
    "/accounts"
  ],
  "blocked_routes": [
    "/operations",
    "/operations/*"
  ]
}
```

This allows the automation to access the configured member and account interfaces while restricting access to the operations routes. The policy also rejects encoded URL paths and invalid application URLs rather than attempting to interpret potentially ambiguous destinations.

#### Action-Level and Workflow-Specific Permissions

In addition to controlling where the browser can navigate, the policy engine restricts which actions can be performed. The current configuration allows CLICK, FILL, NAVIGATE, and WAIT, while explicitly blocking GO_BACK.

Policy profiles allow these permissions to be narrowed for specific operations. For example, the get_savings_balance profile permits only CLICK and FILL actions within the configured member-related routes, while the broader read-only discovery and replay profiles permit the four globally allowed action types.

The following excerpt illustrates the workflow-specific restrictions:

```json
{
  "get_savings_balance": {
    "allowed_routes": [
      "/",
      "/members",
      "/members/*"
    ],
    "allowed_actions": [
      "click",
      "fill"
    ]
  }
}
```

When profiles are configured, the policy engine also requires a valid profile to be supplied. An absent or unrecognized profile results in a blocked decision rather than unrestricted execution.

#### Target-Level Restrictions and Human Confirmation

Beyond route-level and action-level permissions, the policy engine supports restrictions on individual browser controls. A TargetRule identifies a control using its action type, accessibility role, accessible name, and optional route pattern.

These rules allow particular interactions to be explicitly blocked or designated as requiring human confirmation, even when the action type and application route would otherwise be permitted.

The policy engine returns one of three possible decisions:

```python
class PolicyDecision(str, Enum):

    ALLOWED = "allowed"

    BLOCKED = "blocked"

    NEEDS_CONFIRMATION = "needs_confirmation"
```

The current demo configuration leaves the blocked_targets and confirmation_targets lists empty. The target-specific enforcement mechanism is implemented, but no individual controls have been configured for blocking or confirmation in this application policy.

#### Fail-Closed Policy Enforcement

The policy configuration is loaded through a typed Pydantic model. Missing or invalid configuration raises an exception rather than allowing browser execution to continue without a valid policy.

Likewise, the policy engine returns an explicit blocked decision when the requested operation falls outside the configured permissions.

This establishes a clear separation of responsibilities: the LLM proposes an action, the grounding mechanisms verify its supporting evidence, and the policy engine determines whether the action is authorized within the application's execution boundaries.

> **SCREENSHOT 15 PLACEHOLDER · Blocked action / allowlist evidence**  
> Capture an isolated external-origin navigation attempt and the resulting origin_not_allowed or equivalent policy decision, showing the browser stayed within the permitted app.  
> Suggested asset: `docs/assets/20-policy-block.png`. Replace this callout with the real diagram or screenshot after adding the asset.

### 3.9 Testing and Verification

Testing was an important part of the development process, particularly because the system combines AI-driven discovery with deterministic execution and strict validation requirements. I used pytest to verify individual components, interactions between modules, and failure scenarios that could compromise execution reliability. The tests are designed to evaluate not only whether an operation succeeds, but also whether the system behaves correctly when an action fails, a policy restriction is encountered, or human intervention becomes necessary.

#### Automated Testing

The automated test suite covers the following areas of the implementation.

Discovery and Path Optimization: Tests verify that the trajectory recorder removes unnecessary navigation loops while preserving the original execution history and required same-state actions. Additional tests verify that candidate-path optimization accepts action removal only after successful verification and preserves the original path when optimization fails.

Replay Execution: Tests cover recorded browser actions, runtime parameter resolution, navigation behavior, and execution-policy enforcement. They also verify that blocked actions never reach the browser executor and that changes to execution policy can prevent a previously valid capability from executing.

Security and Allowlisting: Tests verify application origin restrictions, route permissions, blocked actions, target-level restrictions, and workflow-specific policy profiles. These scenarios ensure that an action cannot bypass configured execution boundaries simply because it was previously approved. 

Human Handoff and Recovery: Tests verify control transfer between automation and a human operator, explicit verification before resuming execution, cancellation handling, and safe termination when intervention cannot be completed. Replay-specific tests also verify that uncertain actions are not silently retried or skipped following a handoff.

Architecture Validation: In addition to functional tests, the suite includes architectural checks that enforce the intended module dependency structure. These tests identify circular dependencies, disallowed cross-package imports, and violations of the separation between orchestration and lower-level components. This helps maintain the intended architecture as the implementation evolves.

#### Running the Automated Tests

From the project root directory, activate the Python virtual environment and execute the pytest suite using the following command:

```bash
python -m pytest app/agent/test -v
```

To run an individual test module, specify its path. For example:

```bash
python -m pytest app/agent/test/test_path_optimization.py -v
```

The -v flag enables verbose output, displaying individual test cases and their results.

> **SCREENSHOT 16 PLACEHOLDER · pytest results**  
> Insert the latest complete pytest run with test totals and pass/fail/skip counts visible. Do not pre-fill a pass count until the captured run is complete.  
> Suggested asset: `docs/assets/21-pytest-results.png`. Replace this callout with the real diagram or screenshot after adding the asset.

#### Real-Browser Acceptance Testing

In addition to automated pytest coverage, the project includes a separate real-browser acceptance campaign designed to evaluate the complete execution lifecycle.

Unlike tests that isolate components using mocked browser interactions and controlled application states, the acceptance campaign evaluates the system through actual browser execution. It covers capability discovery, approval, reuse, runtime input handling, output extraction, and failure scenarios.

The acceptance campaign can be launched from the project root using:

```bash
python run_acceptance_campaign_23.py
```

The campaign can also run an individual case (for example, the checkpoint-recovery scenario):

```bash
python run_acceptance_campaign_23.py --only TC-016
```

> **SCREENSHOT 17 PLACEHOLDER · Acceptance campaign summary**  
> Show the run summary and the recorded operator verdicts, and link the generated report/evidence when it is ready. The campaign is operator-graded; do not describe cases as passing merely because the runner completed.  
> Suggested asset: `docs/assets/22-acceptance-results.png`. Replace this callout with the real diagram or screenshot after adding the asset.

---

## 4. Execution Demonstration

A recorded demonstration of the system will be included here to provide a practical walkthrough of the implementation.

The demonstration will illustrate how the system processes a natural language request, discovers a browser workflow, generates a reusable capability, incorporates human approval, and executes the approved capability through deterministic replay.

> **VIDEO PLACEHOLDER · Project execution demonstration**  
> Record one continuous walkthrough: natural-language goal → real discovery → saved draft → operator review/approval → changed runtime input → deterministic replay → structured output. A short follow-up clip may demonstrate a known business outcome and human-assisted checkpoint continuation.  
> Suggested asset: `docs/assets/23-execution-demo.mp4`. Replace this callout with the real diagram or screenshot after adding the asset.

<details>
<summary><strong>Suggested demonstration flow · expand when preparing the recording</strong></summary>

Begin with an unapproved operation so the audience sees a genuine discovery run and generated draft. Review and approve that artifact, then make a second request with a different runtime input to demonstrate reuse. Show the recorded actions, checkpoint validation, structured output, and evidence locations. If demonstrating handoff, label the demo checkpoint as a test fixture rather than an application defect.

</details>

---

## Visual asset checklist

All diagram, screenshot, and video callouts above are placeholders, not claims that evidence has been captured. The suggested `docs/assets/` paths are names to use later; no image or recording is embedded yet. Capture only demo/test data and redact sensitive values before committing media to the public repository.

<details>
<summary><strong>View the complete visual plan</strong></summary>

- **DIAGRAM 01:** End-to-end system architecture — `docs/assets/01-system-architecture.png`
- **SCREENSHOT 01:** Capability selection in the terminal — `docs/assets/02-orchestrator-capability-selection.png`
- **DIAGRAM 02:** Discovery control loop — `docs/assets/03-discovery-loop.png`
- **SCREENSHOT 02:** Discovery in a real browser — `docs/assets/04-discovery-browser.png`
- **DIAGRAM 03:** State-stack loop removal — `docs/assets/05-state-stack-loop-removal.png`
- **DIAGRAM 04:** Verified path minimization — `docs/assets/06-verified-path-minimization.png`
- **SCREENSHOT 03:** Browser evidence for output binding — `docs/assets/07-output-table-binding.png`
- **SCREENSHOT 04:** Verified binding evidence — `docs/assets/08-binding-verification.png`
- **SCREENSHOT 05:** Generated draft capability — `docs/assets/09-draft-capability-json.png`
- **SCREENSHOT 06:** Operator reviews and approves a draft — `docs/assets/10-capability-approval.png`
- **SCREENSHOT 07:** File-based registry and approved snapshot — `docs/assets/11-capability-registry.png`
- **SCREENSHOT 08:** Deterministic replay with a new input — `docs/assets/12-cross-member-replay.png`
- **SCREENSHOT 09:** Checkpoint verification — `docs/assets/13-replay-checkpoint.png`
- **DIAGRAM 05:** LLM proposal versus execution authority — `docs/assets/14-grounding-decision-boundaries.png`
- **SCREENSHOT 10:** A proposed action rejected by grounding — `docs/assets/15-grounding-rejection.png`
- **SCREENSHOT 11:** Recognized business outcome — `docs/assets/16-business-outcome.png`
- **SCREENSHOT 12:** Controlled hard failure — `docs/assets/17-hard-failure.png`
- **SCREENSHOT 13:** Human intervention in the same live session — `docs/assets/18-human-handoff.png`
- **SCREENSHOT 14:** Verified return to automation — `docs/assets/19-human-assisted-resume.png`
- **SCREENSHOT 15:** Blocked action / allowlist evidence — `docs/assets/20-policy-block.png`
- **SCREENSHOT 16:** pytest results — `docs/assets/21-pytest-results.png`
- **SCREENSHOT 17:** Acceptance campaign summary — `docs/assets/22-acceptance-results.png`
- **VIDEO:** Project execution demonstration — `docs/assets/23-execution-demo.mp4`

</details>

> **Additional material to be integrated:** Architecture visuals, actual screenshots, evidence links, and any further engineering insights can be inserted into the labeled positions without changing the technical narrative.
