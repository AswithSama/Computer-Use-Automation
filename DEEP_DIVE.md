# AI-Powered Browser Automation

**From a natural-language goal to an approved, reusable browser capability.**

> **How to explore:** Follow a single request from routing to replay, or open the contents below to jump straight to the engineering question you care about.

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

The assessment starts with a deceptively simple message request: let an agent use a browser to get something done, then make that work reusable. This DEEPDIVE walks through my implementation of that requirement—the architecture, engineering decisions, execution workflows, and validation mechanisms that shaped the final system. The interesting part is not just whether the request succeeds once; it is what happens the second time, when the inputs differ, the browser behaves unexpectedly, or a human has to take over. I want to show how I approached those engineering challenges, which decisions I made, and why.

The implementation required careful consideration of several interconnected aspects: how workflows should be discovered, how inputs and outputs should be identified and bound, how browser interactions should be recorded, how discovered workflows should be transformed into reusable capabilities, and how approved capabilities should be executed reliably without repeating the discovery process. Equally important were the decisions surrounding execution boundaries, human approval, failure handling, and validation. Each of these components was designed with consideration for how it would interact with the rest of the system, rather than being implemented as an isolated feature.

### A note on AI-assisted development

AI played a role in generating code and accelerating the implementation of this project. However, the architecture, requirements, system behavior, and major engineering decisions were carefully planned, evaluated, and refined throughout development. My approach was to use AI as an implementation tool while maintaining ownership of the engineering process, from defining requirements and designing component interactions to evaluating implementation choices, identifying potential failure scenarios, and verifying the resulting behavior.

---

## 2. System Architecture

Before looking at individual classes, follow the message request across the entire system. The architecture below shows where a natural-language request enters orchestration, how it is routed to capability selection or AI-driven discovery, and how successful discovery leads through human approval and capability storage to deterministic replay. It also highlights the relationships between the major components and the execution paths that enable the system to discover new workflows and reuse previously approved capabilities.

                         NATURAL-LANGUAGE REQUEST
                                    │
                                    ▼
                    ORCHESTRATION + CAPABILITY REGISTRY
                    Retrieve eligible approved capabilities
                    (scoped to tenant + application)
                                    │
                                    ▼
                         CAPABILITY SELECTOR
                                    │
                    ┌───────────────┴───────────────┐
                    │ NO MATCH                      │ MATCH
                    ▼                               ▼
              AI DISCOVERY                    APPROVED REPLAY
                    │                               │
          Observe browser state               Resolve runtime inputs
                    │                               │
          LLM proposes action                 Execute stored actions
                    │                               │
          Validate + execute                  Verify checkpoints
                    │                               │
          Record verified path                Extract verified outputs
                    │                               │
                    ▼                               ▼
           INPUT / OUTPUT BINDINGS             STRUCTURED RESULT
           Extract → verify rules
                    │
                    ▼
             CAPABILITY COMPILER
             Parameterized actions
             + checkpoints
             + selection metadata
                    │
                    ▼
                DRAFT CAPABILITY
                    │
                    ▼
             HUMAN REVIEW + APPROVAL
                    │
                    ▼
              CAPABILITY REGISTRY
              Store approved version
                    │
                    └────► Eligible for selection
                           on future requests


────────────────── CROSS-CUTTING CONTROLS ──────────────────

  Grounding + validation ── Verify proposals, actions and bindings

  Policy enforcement ────── Check permitted browser operations

  Execution evidence ────── Record transitions, results and failures

  Human handoff ─────────── Pause, transfer control and verify
                            a safe checkpoint before resuming

---

## 3. Technical Deep Dive

Imagine the message request “Get the savings balance for member 12345.” Follow how that request is routed, discovered, turned into a capability, and eventually replayed for a different member. The examples are illustrative; the implementation details below explain the actual mechanisms. Now follow one request as it becomes something the system can execute again. The sections below trace how each component operates, which engineering decisions shaped it, and how it hands work to the next stage of the architecture. Rather than describing individual components in isolation, the following sections trace the execution lifecycle, from receiving a natural language request to discovering, approving, storing, and replaying a reusable browser automation capability. Where relevant, architecture diagrams, code references, execution screenshots, and practical examples will be included to illustrate the implementation and the reasoning behind important design decisions.

**Follow the message request:** orchestration → discovery → binding → capability lifecycle → replay. Grounding, failure recovery, policy, and tests then show what happens when the expected path is not enough.

### 3.1 Orchestration

The first decision is whether the browser needs to learn anything at all. The orchestration layer determines whether a natural-language request can be fulfilled using an existing approved capability or requires a new discovery workflow. The LLM evaluates the user's request against the eligible capabilities retrieved from the registry, using structured metadata such as capability descriptions, workflow summaries, example goals, declared inputs, and expected outputs. It identifies a matching capability and extracts the required runtime inputs. If a valid match is found, the orchestrator initiates deterministic replay; otherwise, it initiates AI-driven discovery. The LLM is responsible for capability selection, while the application validates its decision and controls execution.

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

Illustrative capability metadata. The exact selection payload is defined by the implementation. The selection process separates the requested operation from its runtime values, allowing a capability discovered for one member to be reused for another without repeating discovery.

#### Scalability Consideration: RAG-Based Capability Retrieval

The current implementation evaluates eligible capabilities directly through the LLM. As the capability registry grows, passing the entire catalog to the model may introduce unnecessary token consumption and increase selection complexity. A future enhancement is to introduce a Retrieval-Augmented Generation (RAG) architecture when the number of approved replayable capabilities exceeds 30. This configurable threshold is an initial design consideration rather than an experimentally established limit. Under this proposed architecture, relevant capabilities would first be retrieved from the registry using semantic similarity to the user's request. The LLM would then evaluate only the shortlisted candidates to determine whether an existing capability can fulfill the request.

This enhancement has intentionally been left as a placeholder. The current implementation prioritizes engineering depth over feature breadth, focusing on the reliability of discovery, capability generation, approval, deterministic replay, and validation before introducing additional retrieval infrastructure.

#### Capability Selection — Reusing an Approved Workflow

A new request does not always require the system to explore the browser again. When an approved capability matches the request, the orchestrator selects it and passes the extracted runtime inputs to deterministic replay.

```text
[REQUEST]
"Could you check the savings balance for member DEMO-12345?"

[CAPABILITY SELECTION]
Registry scope       : Current tenant + application
Eligibility          : Approved capabilities only
Selected capability  : get_member_savings_balance

[RUNTIME INPUTS]
member_id            : DEMO-12345

[EXECUTION PATH]
Approved capability → Deterministic replay
```

The capability is reused with a new runtime input, without repeating the original AI-driven discovery process.


### 3.2 Discovery Workflow

If no approved capability matches, the request enters discovery. Here the central question changes from “which workflow should run?” to “what must the browser do, and how can each step be justified?” The discovery workflow follows an iterative observe–decide–validate–execute cycle. At each step, Playwright captures the current browser observation, which the LLM uses to determine the next action required to complete the user's request. Rather than allowing the LLM to execute arbitrary browser operations, its proposed actions pass through the application's policy and validation mechanisms before being executed through Playwright. Following execution, the system captures the resulting browser state and validates the action's outcome before recording a successful transition. This cycle continues until the task is completed or an execution condition requires the process to stop.

NOTE: The video walkthrough demonstrates the test case.

┌──────────────────────────┐
│   OBSERVE BROWSER STATE  │◄──────────────────────┐
└────────────┬─────────────┘                       │
             ▼                                     │
┌──────────────────────────┐                       │
│   LLM PROPOSES NEXT STEP │                       │
└────────────┬─────────────┘                       │
             ▼                                     │
       ┌─────────────┐                             │
       │  DECISION?  │                             │
       └──────┬──────┘                             │
              │                                    │
     ┌────────┼──────────┐                         │
     ▼        ▼          ▼                         │
   ACTION   FINISH     HANDOFF                     │
     │        │          │                         │
     ▼        ▼          ▼                         │
┌─────────┐ ┌────────┐ ┌──────────────┐             │
│ Policy +│ │ Verify │ │ Human takes │             │
│grounding│ │ goal   │ │ control     │             │
└────┬────┘ └───┬────┘ └──────┬───────┘             │
     ▼          ▼             ▼                     │
┌─────────┐  Complete     Verify safe              │
│Playwright│             continuation ─────────────┤
│ action  │                                       │
└────┬────┘                                       │
     ▼                                            │
┌──────────────────────────┐                      │
│ Observe + verify outcome │                      │
└────────────┬─────────────┘                      │
             ▼                                    │
┌──────────────────────────┐                      │
│ Record successful        │                      │
│ transition               │──────────────────────┘
└──────────────────────────┘


#### State Recording and Fingerprinting

Discovery seldom follows the shortest route on its first try: the LLM may inspect a page, follow a link, and come back. I wanted to preserve that complete exploration for evidence without forcing replay to repeat every detour. That meant maintaining the full discovery history alongside a separate, shorter candidate path suitable for deterministic replay. To achieve this, I implemented a `TrajectoryRecorder` that maintains three structures: an immutable-by-design execution history, a stack of browser states belonging to the current candidate path, and a corresponding stack of recorded actions. Each successfully executed and validated transition is preserved in the execution trace, while the candidate path is updated as discovery progresses.

Each recorded state contains the browser URL, its accessibility observation, and a deterministic fingerprint. The fingerprint is generated using SHA-256 over the URL and normalized observation. Temporary Playwright element references and inconsistent whitespace are removed before hashing, allowing the system to recognize the same observable browser state even when transient element references change between visits. The fingerprint construction logic is:

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

Consider an agent that goes from A to B, explores C, and then returns to B. The detour may have helped the agent discover the right route, but it should not automatically become part of the reusable workflow. When discovery returns to a previously visited browser state, rather than preserving this entire sequence in the candidate workflow, the recorder uses the state fingerprints to identify navigation loops and remove the corresponding transitions from the candidate path. For example, consider the following exploration:

```text
A → B → C → B
```

When the system returns to state B, its fingerprint matches an earlier state in the current stack. The recorder removes the intermediate transitions, reducing the candidate path to:

```text
A → B
```

The complete execution trace still preserves the original exploration, including the removed transitions. This allows the system to retain the actual discovery history while maintaining a simplified candidate workflow. An important distinction is that an action producing the same observable state is not automatically considered redundant. For example, a successful input action may be necessary for replay even if it does not change the generated fingerprint. Such actions are preserved rather than being incorrectly classified as navigation loops.

FULL EXECUTION TRACE
(Every exploratory transition is retained)

    A ──────► B ──────► C ──────► B
             ▲                   │
             └──── Revisited ────┘


CANDIDATE PATH — BEFORE LOOP REMOVAL

    [ A ] ──► [ B ] ──► [ C ] ──► [ B ]


                  │
                  ▼
       B already exists in stack
       Remove loop segment: B → C → B
                  │
                  ▼


CANDIDATE PATH — AFTER LOOP REMOVAL

    [ A ] ──► [ B ]


#### Verification-Based Path Minimization

Removing a visible loop is only the first pass. What if an unnecessary action changes the page, so none of the intermediate fingerprints repeat? Stack-based loop removal handles repeated states, but unnecessary actions may also exist within a sequence of distinct browser states. To address this, I implemented a separate path-minimization process that identifies consecutive same-page interactions as potential optimization candidates. The minimizer attempts to remove actions individually, but a removal is accepted only when the shortened workflow successfully passes deterministic verification.

Verification uses a fresh browser session to reproduce the original starting state, execute the proposed action sequence under the applicable execution policy, and confirm that the final observable state matches the original successful discovery. If verification fails, the proposed removal is rejected. The optimization process retains the original candidate path if the shortened workflow cannot be accepted. This two-stage approach separates structural loop removal from execution-verified optimization, allowing the system to simplify exploratory workflows without relying solely on the LLM's judgment about which actions are necessary.

Original path:   A → B → C → D → E
                       │
                       ▼
Shorter proposal: A → C → E
                       │
                       ▼
              Fresh browser test
                       │
                  Verified?
                  /       \
                YES        NO
                 │          │
                 ▼          ▼
          Accept shorter  Keep original
             A → C → E    A → B → C → D → E

### 3.3 Input and Output Binding

A successful discovery may have used member `12345`, but the approved capability should work for member `67890` without learning the same clicks again. Once discovery completes a task, the next challenge is to turn recorded browser interactions into a reusable workflow. This requires identifying which values should change between executions and establishing reliable rules for retrieving the requested outputs. Rather than relying entirely on the LLM's interpretation, the system uses a proposal-and-verification approach: AI identifies potential input parameters and output relationships, while deterministic verification ensures that the proposed bindings are supported by the recorded interactions and observed browser structure.

#### Input Binding

What should change from one invocation to another? The `InputExtractorLLM` identifies reusable runtime inputs from the successful discovery path. An important design decision is that only values explicitly supplied through successful FILL interactions and present in the original user request are considered eligible input evidence. For example, in the request "Get the savings balance for member 12345," the member ID is a reusable input because it was explicitly supplied to the application. However, "Savings" describes the operation being performed and should not automatically become a runtime parameter. This prevents the LLM from introducing unsupported inputs based solely on words appearing in the request.

Each proposed input includes its name, type, observed value, and source interaction step. The `InputVerifier` then checks the proposal against the recorded discovery evidence before accepting it.

During capability compilation, the verified input is converted into a parameterized value:

```python
if input_candidate is not None:
    value = f"{{{{{input_candidate.name}}}}}"
```

For example, a recorded action containing the literal value 12345 becomes an action referencing {{member_id}}. The compiler also parameterizes matching input values in navigation URLs and supported checkpoint patterns, allowing the same workflow to execute with new runtime inputs.

#### Output Binding

Inputs tell the workflow what to search for; outputs tell it how to find the answer after the search. I initially underestimated how difficult reliable output extraction would be, and after completing discovery, I had to revisit my design before moving forward with replay. Finding a value once was not enough—the system needed to find the correct value again, even when the underlying data changed. To address this, the OutputLocatorBuilder identifies the observed output in the browser DOM and gathers its surrounding table structure, including the relevant row, headers, and value column. The OutputBindingLLM then uses that evidence to propose a reusable extraction rule based on the relationship between the requested information and the table structure, rather than on the particular value observed during discovery.
For example, consider a table containing the following information:

| Account | Type | Nickname | Current Balance |
| --- | --- | --- | ---: |
| SAV-40082 | Savings | Holiday Fund | $630.00 |
| CHK-50021 | Checking | Daily Expenses | $240.00 |

If the user requests the savings balance, the system should identify the row using the account's Type rather than its account number, nickname, or current balance. The proposed reusable output binding would be:

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

This design separates the identity of the requested record from incidental values that may change between executions. For output requests identified by a runtime input, the compiler can also replace the verified row-matching value with its corresponding input placeholder. For example, a row condition matching member 12345 can become a condition matching {{member_id}}.

| Type | Account ID | Current Balance |
|---|---|---:|
| Checking | DEMO-001 | $2,450.00 |
| **Savings** | DEMO-002 | **$8,750.00** |
| Credit | DEMO-003 | $1,200.00 |

**Row match:** `Type = Savings`  
**Output column:** `Current Balance`  
**Extracted value:** `$8,750.00`

NOTE: The video walkthrough demonstrates the test case.

#### From AI Proposals to Verified Bindings

The OutputBindingVerifier checks the proposed table columns and row-matching values against the live DOM, requiring the extraction rule to return exactly one value matching the original discovery output. Unsupported, ambiguous, or incorrect bindings are rejected. Only verified inputs and outputs are incorporated into the reusable capability, ensuring that replay preserves how to find the requested information, rather than the value observed during discovery.

**Implementation scope — Table-based output bindings only**. The current implementation intentionally focuses on HTML tables to prioritize reliable extraction and verification. Support for other HTML components remains a potential future extension.

### 3.4 Capability Generation, Approval, and Storage

Discovery has gathered evidence, but the registry should receive a reviewable execution contract—not a transcript of everything the LLM thought or every page it explored. At this point, the browser has completed the task and the relevant inputs and outputs have been verified. The next question is what, exactly, should be kept for future requests. The system transforms the discovered workflow into a structured, reusable capability. This compilation step separates the original exploratory browser session from the execution contract that will be used during future requests.

#### Capability Generation

The `CapabilityCompiler` converts the verified discovery results into a `CapabilityArtifact`, containing the capability identity, declared inputs, parameterized browser actions, execution checkpoints, and output bindings. Rather than preserving the original request-specific values, the compiler replaces them with runtime placeholders such as {{member_id}}. It also converts discovered URL transitions into replay checkpoints, preserving the expected navigation behavior while allowing the same workflow to operate with different inputs.

An additional design decision is to generate the capability identity independently of the original request's runtime values. The `CapabilityIdentityGenerator` uses the requested operation and verified inputs and outputs to produce a semantic identifier and description. This allows capabilities to represent distinct business operations even when their browser navigation paths are identical.

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

#### Human Approval

A workflow that succeeded once is not automatically authorized to run unattended again. After compilation, the system generates additional selection metadata and stores the capability with a draft approval status. This establishes a clear separation between successfully discovering a workflow and authorizing that workflow for future execution. Human approval therefore remains a separate operation rather than an automatic consequence of successful discovery. The approved artifact can then be considered for subsequent execution through the capability registry. An important safeguard is that a discovery requiring human assistance does not automatically produce an autonomous capability draft. Similarly, the system does not save an executable draft if the required output bindings are incomplete or input verification fails.

Capability approval and human intervention during browser execution are separate workflows. Approval is managed by the registry; the `handoff` module manages temporary operator control during discovery or replay and does not authorize a capability for future reuse. The original draft is preserved when the approved snapshot is created. For actual review, the generated draft enters a separate human approval process. The approve.py module provides a terminal-based review interface that retrieves pending capabilities and presents the complete artifact, including its execution actions, input definitions, checkpoints, output bindings, and selection metadata.

The operator can approve the capability, skip it to leave it pending, or exit the review process. That explicit authorization step ensures that newly generated workflows cannot immediately become available for autonomous replay.

#### Capability Storage and Versioning

Once generated, a capability needs a clear distinction between “draft” and “authorized.” The CapabilityRegistry manages this lifecycle through a file-based JSON registry organized by tenant, application, and approval status. Each stored capability includes its version, executable artifact, business outcome rules, and selection metadata. The SelectionContextGenerator produces three fields—use_when, workflow_summary, and example_goals—to help the orchestrator identify the appropriate capability without examining its execution instructions. Approval checks prevent a duplicate capability ID and version from being approved within that scope. The registry organizes stored artifacts using the following directory structure:

```text
capabilities/
└── <tenant_id>/
    └── <app_id>/
        ├── drafts/
        │   └── <capability_id>_<unique_id>.json
        └── approved/
            └── <capability_id>_v<version>_approved_<unique_id>.json
```


#### Capability Eligibility and Reuse

When a new request arrives, the orchestrator retrieves eligible capabilities through the registry’s list_eligible() method, scoped to the current tenant and application. Only capabilities stored in the corresponding approved directory, with matching tenant ID, application ID, and approval status, are considered eligible. Draft capabilities remain excluded, even after successful discovery, ensuring that the LLM can select only workflows explicitly authorized for reuse.

The CapabilitySelector then compares the request against each eligible capability’s description, selection context, declared inputs, and expected outputs. If it identifies a valid match, the orchestrator passes the stored artifact, extracted runtime inputs, and applicable execution policy to deterministic replay. Otherwise, the system initiates discovery to build a new workflow. This closes the capability lifecycle: discover once, approve explicitly, and reuse without repeating AI-driven exploration.

### 3.5 Replay Workflow

Now return to the same business question with a different member ID. Instead of asking the LLM to work out the navigation again, replay follows the approved contract. The replay workflow transforms an approved capability into a repeatable browser execution process without requiring the LLM to rediscover the original workflow. Once the orchestrator selects an eligible capability, the replay engine receives its stored artifact, runtime inputs, and execution policy. It then executes the recorded browser actions in sequence, using the capability's parameterized instructions, checkpoints, and verified output bindings to reproduce the intended operation.

A key design decision is the separation between AI-driven discovery and deterministic replay. The LLM identifies and helps construct the workflow during discovery, but replay does not depend on the LLM deciding the next browser action. Instead, the system follows the previously approved execution contract, verifies the application's behavior at defined checkpoints, and extracts the requested output only after the required execution steps have succeeded.

#### Parameter Resolution and Execution

Before execution begins, the `ReplayEngine` performs preflight checks to confirm that all required inputs are available, checkpoint references are valid, and the initial browser state is permitted by the execution policy. If a required input is missing, replay returns a recoverable result requesting the missing information instead of proceeding with an incomplete workflow. The `ParameterResolver` substitutes runtime values into the stored actions. For example, when the user requests the checking balance of member 67890, the recorded placeholder {{member_id}} is replaced with 67890 before the corresponding browser action is executed. This allows the same approved capability to operate on different records without modifying its stored execution definition.

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

Once the runtime values have been resolved, the `ReplayActionExecutor` performs the recorded actions through Playwright. The current implementation supports CLICK, FILL, NAVIGATE, and WAIT operations. Each action is executed in its original recorded order, and the replay engine advances to the next step only after the current action and its associated execution checks have succeeded.

#### Checkpoint Verification

Clicking Search is easy to observe; knowing that the correct member page actually loaded is a separate problem. Successfully performing a browser action does not necessarily mean that the application reached the expected state. For this reason, the replay workflow uses execution checkpoints to verify the application's behavior at predefined stages. Each checkpoint is associated with a recorded action and may contain an expected URL pattern, required visible text, or both. The `CheckpointValidator` resolves any runtime placeholders, waits for the expected conditions within a bounded timeout, and verifies the resulting browser state before allowing execution to proceed.

For example, after searching for member 67890, a checkpoint containing /members?member_id={{member_id}} is resolved to the expected member-specific URL. The replay engine verifies that the application has reached that route rather than assuming that the search action succeeded merely because Playwright completed the click. This separates the successful execution of a browser interaction from verification of its expected application outcome.

[REPLAY]
Runtime input : member_id = DEMO-12345
Current URL   : /members/DEMO-12345/accounts
                         │
                         ▼
[CHECKPOINT VERIFICATION]
Expected member : DEMO-12345
Observed member : DEMO-12345
Result          : PASSED
                         │
                         ▼
              Continue replay

#### Deterministic Output Extraction

Only after the expected route has been verified does the workflow ask for its answer. Once all recorded actions and their associated checkpoints have completed successfully, the replay engine extracts the requested outputs using the verified bindings stored in the capability artifact. The current implementation supports table-based output extraction. Rather than returning a previously observed value or relying on a fixed row position, the engine locates the table containing the required columns, identifies the row matching the stored condition, and retrieves the corresponding output value. For example, a checking-balance capability identifies the row where Type = Checking and extracts the value from the Current Balance column. The extracted value is returned as part of the structured `ReplayResult`.

The replay engine requires each declared output binding to resolve to exactly one value. Missing or ambiguous outputs prevent the execution from being reported as successful.

#### Execution Results and Recovery

The replay workflow returns a structured result containing the execution status, completed step count, extracted outputs when successful, and relevant failure information when execution cannot proceed. An important design consideration is that replay does not automatically rediscover the workflow, skip failed actions, or blindly retry browser interactions when an unexpected condition occurs. Instead, the system distinguishes between missing inputs, application-level business outcomes, execution failures, and situations requiring human intervention. The detailed mechanisms for failure classification, evidence recording, human handoff, and safe continuation will be explained in the dedicated Failure Handling and Recovery section.

### 3.6 LLM Grounding and Validation

Throughout the story so far, the LLM has proposed a candidate capability, browser actions, inputs, and output relationships. What stops a convincing but unsupported proposal from turning into a real click or a reusable artifact? One of the central engineering decisions in this project was ensuring that LLM-generated decisions are grounded in observable application evidence rather than executed solely on the model's interpretation. To achieve this, I implemented multiple validation layers across discovery, input and output binding, capability selection, and replay. Each layer validates a different aspect of the workflow, establishing a clear separation between what the LLM proposes, what the application can verify, and what is permitted to execute.

#### Action Validation and Grounding

During discovery, the `ActionValidator` evaluates every proposed browser action before execution. For interactive actions, it checks that the target reference, role, and accessible name correspond to the same element in the current browser observation. For FILL actions, it additionally verifies that the proposed value is grounded in either the original user request or the current page observation. Navigation actions are checked against the current host, and consecutive duplicate actions are rejected to prevent unnecessary repetition. An important design decision is that deterministic validation does not have to make a forced approval or rejection when the evidence is insufficient. Instead, the validator returns one of three possible statuses:

```python
class ValidationStatus(str, Enum):
    APPROVED = "approved"
    REJECTED = "rejected"
    NEEDS_LLM = "needs_llm"
```

When a proposed value cannot be directly grounded in the available evidence, the system invokes a separate `ValueValidatorLLM`. This validator receives the proposed action, original request, browser observation, deterministic validation reason, and applicable business validation policy. Its responsibility is limited to evaluating the proposed value; it cannot generate replacement values or propose additional browser actions. The validator returns a structured decision of approve, reject, or escalate_to_human. Rejected actions are not executed, while unresolved decisions can trigger human intervention. This provides a controlled evaluation path for values that require contextual reasoning beyond direct evidence matching.

LLM proposes action
        │
        ▼
Deterministic grounding
        │
        ├── REJECT ───────────────────────► Stop / handoff
        │
        ├── NEEDS LLM
        │       │
        │       ▼
        │   Bounded value validator
        │       ├── REJECT ───────────────► Stop / handoff
        │       ├── ESCALATE ─────────────► Human handoff
        │       └── APPROVE ──┐
        │                     │
        └── APPROVE ──────────┘
                              │
                              ▼
                         Policy check
                         ├── DENY ───────► Stop / handoff
                         └── ALLOW
                              │
                              ▼
                       Playwright action

#### Post-Execution Validation

Validation does not end when Playwright successfully executes an action. The `OutcomeValidator` compares the browser state before and after execution to determine whether the action produced an expected observable result. For example, navigation is expected to change the URL, while a click or browser-back action is expected to produce an observable change in the page or URL. FILL and WAIT operations are treated differently because they may complete successfully without producing a meaningful change in the accessibility snapshot. Only transitions that satisfy the applicable outcome checks are added to the successful discovery trajectory. Invalid outcomes are handled through the discovery workflow's retry and failure-limit mechanisms rather than being accepted as successful transitions.

#### Input and Output Binding Validation

The grounding process continues when discovered interactions are transformed into reusable capability inputs and outputs. The `InputVerifier` ensures that proposed runtime inputs originate from successful FILL interactions, that their source steps exist in the recorded discovery path, and that their observed values match both the recorded interaction and the original user request. This prevents the LLM from introducing unsupported runtime parameters into a reusable capability. For output binding, the `OutputBindingVerifier` validates the proposed table structure, row-matching condition, and output column against the observed DOM. It then executes the proposed extraction rule against the live page and requires exactly one matching result that agrees with the original discovery output.

A proposed binding that references nonexistent columns, resolves to multiple values, or retrieves an incorrect value is rejected rather than being incorporated into the capability artifact.

#### Capability Selection and Replay Validation

Grounding also extends beyond discovery. When the orchestrator uses the LLM to select an existing capability, the selection response is validated against the eligible capability catalog and the selected artifact's declared input contract. Invalid candidate identifiers and undeclared input names are rejected before execution begins. During replay, the system independently validates required runtime inputs, action targets, execution policies, checkpoints, and output extraction results. Missing or ambiguous browser targets are not executed, checkpoint mismatches prevent normal progression, and output extraction must resolve to a unique result. These checks ensure that successful discovery and human approval do not eliminate the need to verify actual application behavior during subsequent executions.

The underlying design principle is that AI contributes reasoning and proposes actions, while application-controlled validation determines whether those proposals are supported by the available evidence and can proceed through the execution lifecycle.

[LLM PROPOSAL]
Action : CLICK
Target : "Transfer Funds"

          │
          ▼

[GROUNDING VALIDATION]
Decision : REJECT
Reason   : Proposed target is not grounded
           in the observed browser state.

          │
          ▼

[EXECUTION]
Playwright action : NOT EXECUTED
Browser state     : UNCHANGED
Result            : Validation failure

### 3.7 Failure Handling and Human Handoff

**A useful way to read this section:** ask whether the application returned a legitimate answer, whether the automation has a verified route to continue, or whether the only safe result is to stop. The same missing balance can mean very different things depending on the evidence.

Not every run without the requested value is a broken run. A member might not exist, the application might need a missing input, or a browser action might leave the system in an uncertain state. A key engineering consideration was distinguishing between an unsuccessful business outcome and a technical execution failure. A browser workflow may execute correctly but return an application-level result that differs from the requested output. Conversely, an execution may fail because the application has changed, a required input is missing, or the system can no longer safely determine the current browser state.

The failure-handling architecture distinguishes between business outcomes, recoverable failures, and unrecoverable failures. Rather than automatically retrying every unsuccessful operation, the system uses structured execution results to determine whether it should return an application-level outcome, request additional information, transfer control to a human, or terminate execution safely.

#### Business Outcomes

Start with a member who genuinely has no matching record. A business outcome occurs when the application returns a valid, expected result that prevents the requested operation from producing its normal output. For example, the requested member may not exist, or a member may not have the requested savings account. These conditions should not automatically be classified as technical execution failures. The `BusinessOutcomeDetector` evaluates predefined rules against the current browser state. These rules use evidence such as the expected URL, visible application messages, and the absence of a matching row in an otherwise valid table. When a configured rule matches, the replay engine returns a structured business_outcome result containing the corresponding outcome code and reason, rather than continuing with normal execution or reporting an output extraction failure.

The initial implementation includes explicit rules for recognizing a missing member and the absence of a savings account in the supported savings-balance workflow. Business outcomes are recognized only when the configured evidence conditions are satisfied; an arbitrary missing output is not treated as proof that the requested record does not exist.

#### Recoverable Failures

Now imagine the system could complete the same request if it had one missing piece of information. Recoverable failures represent conditions for which the system has a defined path toward continuing execution safely. For example, when required runtime inputs are missing, the replay engine returns a recoverable_failure result with a request_input recovery action. This allows the missing information to be requested before another execution attempt, rather than proceeding with an incomplete capability invocation. The recovery architecture also supports human-assisted resolution of certain application-level execution problems. However, recovery does not mean that every failed action can be automatically repeated or skipped. The system evaluates whether a valid recovery path exists before permitting execution to continue.

#### Unrecoverable Failures

Finally, consider the point where no verified continuation exists. An unrecoverable failure occurs when the system cannot establish a safe continuation path or encounters a condition that cannot be corrected through the supported recovery mechanisms. Examples include invalid capability artifacts, unresolved parameter references, policy violations, checkpoint failures, and output extraction errors. These conditions are represented through structured hard_failure results that identify the failure category, error code, affected execution step, and number of successfully completed steps. A particularly important consideration is handling uncertain browser actions. If an interaction times out, the system cannot always determine whether its effect was applied before the timeout occurred. Blindly retrying the action could therefore produce unintended behavior.

The current implementation does not automatically retry or skip failed actions. If execution cannot be safely resumed through an explicitly supported recovery path, the system terminates the replay and records the failure rather than continuing from an uncertain state.

#### Human Handoff and Safe Continuation

The `HumanHandoffManager` provides a controlled mechanism for transferring execution to a human operator when automation cannot safely proceed. When an eligible application-level failure occurs, the system pauses automation, preserves the live browser session, records the intervention context, and transfers control to the operator. The operator can inspect the application and attempt to resolve the condition without requiring the entire workflow to be rediscovered.

Human intervention does not automatically authorize the system to resume execution. After the operator reports that the issue has been resolved, the system must independently verify that the application has reached a state from which execution can safely continue. For the supported checkpoint-based replay continuation path, this requires the relevant URL and visible-text checkpoint evidence to be satisfied. If verification fails, the intervention is cancelled or execution terminates safely. The recovery policy also distinguishes application-level conditions from failures involving the automation runtime, capability artifact, input contract, or execution policy. Conditions that cannot be corrected by interacting with the live application are directed toward failure reporting rather than unnecessary human intervention. The checkpoint demonstration is deliberately narrow: the operator restores a predefined observable condition, and the engine verifies that condition before continuing. It does not treat a manually supplied final answer or arbitrary manual navigation as a verified replay output.

NOTE: The video walkthrough demonstrates the test case.

#### Failure Evidence and Traceability

The `ReplayEvidenceRecorder` preserves diagnostic information when replay fails, including structured failure reports and, where available, sanitized browser-structure snapshots. The evidence records are intentionally restricted to reviewed diagnostic fields rather than unrestricted browser content. Sensitive information such as raw input values, page text, URLs, and unfiltered exception messages is excluded from the persisted failure reports and structural snapshots. This enables failed executions to be investigated while limiting unnecessary exposure of application data.

The underlying design principle is to treat recovery as a verified execution decision rather than an automatic response to failure. The system should return a recognized business outcome when appropriate, recover through a defined mechanism when possible, and stop execution when the required conditions for safe continuation cannot be established.

### 3.8 Security and Allowlisting

#### Policy-Driven Execution Boundaries

Even a perfectly grounded action may still be outside the permissions of the application. The `PolicyEngine` implements a deterministic allowlist that controls browser execution independently of the LLM. Before an action is executed, the system evaluates the current application URL, requested action type, target element, and applicable policy profile. This ensures that an action is not permitted simply because it was proposed by the LLM or successfully grounded in the browser observation.

An important design decision is the separation between global application permissions and workflow-specific policy profiles. Global permissions establish the maximum execution boundaries, while individual profiles can introduce additional restrictions but cannot expand those permissions. The same policy mechanism can therefore support different execution requirements during discovery and replay.

#### Application and Route Allowlisting

The system restricts browser execution to explicitly permitted application origins and routes. The policy engine validates the URL's scheme, hostname, and port, preventing execution outside the configured application environment. Route restrictions are evaluated separately, allowing specific application areas to be accessible while prohibiting others. Explicit navigation actions are checked against both the current page and the intended destination.

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

In addition to controlling where the browser can navigate, the policy engine restricts which actions can be performed. The current configuration allows CLICK, FILL, NAVIGATE, and WAIT, while explicitly blocking GO_BACK. Policy profiles allow these permissions to be narrowed for specific operations. For example, the get_savings_balance profile permits only CLICK and FILL actions within the configured member-related routes, while the broader read-only discovery and replay profiles permit the four globally allowed action types.

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

Beyond route-level and action-level permissions, the policy engine supports restrictions on individual browser controls. A `TargetRule` identifies a control using its action type, accessibility role, accessible name, and optional route pattern. These rules allow particular interactions to be explicitly blocked or designated as requiring human confirmation, even when the action type and application route would otherwise be permitted. The policy engine returns one of three possible decisions:

```python
class PolicyDecision(str, Enum):
    ALLOWED = "allowed"
    BLOCKED = "blocked"
    NEEDS_CONFIRMATION = "needs_confirmation"
```

The current demo configuration leaves the blocked_targets and confirmation_targets lists empty. The target-specific enforcement mechanism is implemented, but no individual controls have been configured for blocking or confirmation in this application policy.

#### Fail-Closed Policy Enforcement

The policy configuration is loaded through a typed Pydantic model. Missing or invalid configuration raises an exception rather than allowing browser execution to continue without a valid policy. Likewise, the policy engine returns an explicit blocked decision when the requested operation falls outside the configured permissions. This establishes a clear separation of responsibilities: the LLM proposes an action, the grounding mechanisms verify its supporting evidence, and the policy engine determines whether the action is authorized within the application's execution boundaries.

### 3.9 Testing and Verification

A demonstration of one successful balance lookup would show the happy path, but not what happens when a row is missing, a target is ambiguous, or a handoff cannot be verified. Testing therefore became an important part of development, particularly because the system combines AI-driven discovery with deterministic execution and strict validation requirements. I used pytest to verify individual components, interactions between modules, and failure scenarios that could compromise execution reliability. The tests are designed to evaluate not only whether an operation succeeds, but also whether the system behaves correctly when an action fails, a policy restriction is encountered, or human intervention becomes necessary.

#### Automated Testing

The automated test suite covers the following areas of the implementation. Discovery and Path Optimization: Tests verify that the trajectory recorder removes unnecessary navigation loops while preserving the original execution history and required same-state actions. Additional tests verify that candidate-path optimization accepts action removal only after successful verification and preserves the original path when optimization fails. Replay Execution: Tests cover recorded browser actions, runtime parameter resolution, navigation behavior, and execution-policy enforcement. They also verify that blocked actions never reach the browser executor and that changes to execution policy can prevent a previously valid capability from executing.

Security and Allowlisting: Tests verify application origin restrictions, route permissions, blocked actions, target-level restrictions, and workflow-specific policy profiles. These scenarios ensure that an action cannot bypass configured execution boundaries simply because it was previously approved. Human Handoff and Recovery: Tests verify control transfer between automation and a human operator, explicit verification before resuming execution, cancellation handling, and safe termination when intervention cannot be completed. Replay-specific tests also verify that uncertain actions are not silently retried or skipped following a handoff.

Architecture Validation: In addition to functional tests, the suite includes architectural checks that enforce the intended module dependency structure. These tests identify circular dependencies, disallowed cross-package imports, and violations of the separation between orchestration and lower-level components. This helps maintain the intended architecture as the implementation evolves.

#### Real-Browser Acceptance Testing

In addition to automated pytest coverage, the project includes a separate real-browser acceptance campaign designed to evaluate the complete execution lifecycle. Unlike tests that isolate components using mocked browser interactions and controlled application states, the acceptance campaign evaluates the system through actual browser execution. It covers capability discovery, approval, reuse, runtime input handling, output extraction, and failure scenarios. The acceptance campaign can be launched from the project root using:

```bash
python run_acceptance_campaign_23.py
```

The campaign can also run an individual case (for example, the checkpoint-recovery scenario):

```bash
python run_acceptance_campaign_23.py --only TC-016
```

## Test Results

The system was tested using 23 acceptance test cases covering discovery, approval, replay, capability selection, error handling, safety, and human intervention.

All 23 test cases passed.

| Test ID | Test Case | Expected Behavior | Result |
|---------|-----------|-------------------|--------|
| TC-001 | Discover savings balance | Find the correct savings balance, identify the required member ID, and save a reusable workflow. | PASS |
| TC-002 | Discover checking balance | Find the correct checking balance without confusing it with the savings balance. | PASS |
| TC-003 | Discover member email | Find the correct member email and save a reusable workflow. | PASS |
| TC-004 | Discover member phone | Find the correct member phone number and save a reusable workflow. | PASS |
| TC-005 | Discover member status | Find the correct member status from the search results and save a reusable workflow. | PASS |
| TC-006 | Approve and replay savings | Approve the saved savings workflow and replay it for a different member without repeating discovery. | PASS |
| TC-007 | Approve and replay checking | Approve the saved checking workflow and retrieve another member's checking balance without repeating discovery. | PASS |
| TC-008 | Approve and replay email | Reuse the approved email workflow and return the requested member's email instead of the original discovery value. | PASS |
| TC-009 | Approve and replay phone | Reuse the approved phone workflow and return the requested member's phone number instead of the original discovery value. | PASS |
| TC-010 | Approve and replay status | Reuse the approved status workflow and return the correct status for a different member. | PASS |
| TC-011 | Capability selection | Select the correct approved workflow for different ways of asking the same question without selecting an unrelated workflow. | PASS |
| TC-012 | Savings business outcomes | Detect and report both existing savings business outcomes using structured results. | PASS |
| TC-013 | Missing savings input | Detect a missing member ID and request the required input without inventing a value. | PASS |
| TC-014 | External website protection | Block navigation outside the permitted application and report a policy failure. | PASS |
| TC-015 | Unexpected checkpoint state | Detect when the expected application state is not reached, stop safely, and record failure evidence. | PASS |
| TC-016 | Human-assisted checkpoint recovery | Allow human intervention, verify the expected state again, and complete the workflow after successful recovery. | PASS |
| TC-017 | Missing action target | Stop safely when the recorded target is missing. Do not click unrelated controls. Record the failure and request human intervention. | PASS |
| TC-018 | Ambiguous action target | Stop when multiple controls match the recorded target instead of clicking an arbitrary control. | PASS |
| TC-019 | Ambiguous table output | Report a failure when multiple table values match the expected output instead of guessing which value is correct. | PASS |
| TC-020 | Missing table output | Report an output failure when the expected value is missing. Do not return an old value or an unrelated field. | PASS |
| TC-021 | Missing or malformed required input | Do not invent a member ID or report false success when the required input is missing or invalid. | PASS |
| TC-022 | Member not found / wrong-member protection | Do not return another member's information when the requested member does not exist. Report a no-record outcome or stop safely. | PASS |
| TC-023 | Validator LLM input serialization | Verify that nested action data can be converted into JSON without a serialization error. This test does not verify a remote LLM response. | PASS |

### Test Summary

| Metric | Result |
|--------|--------|
| Total test cases | 23 |
| Passed | 23 |
| Failed | 0 |
| Pass rate | 100% |

**Note:** A test is considered successful when the system behaves as expected. For example, TC-017 and TC-022 pass because the system stops safely rather than performing an incorrect action or returning another member's information. A successful safety test does not necessarily mean the requested browser operation was completed.

PACKAGE DEPENDENCY RULE

main.py
  |    entry point; may import anything
  v    (only main.py is allowed to import orchestration)
orchestration
  |    imports: capability, discovery, handoff, policy, registry, replay, recording, schemas
  v
discovery
  |    imports: llm, policy, observability, recording, schemas, validation, handoff
  v
replay ----------- schemas, policy
capability ------- schemas
registry --------- schemas
  |    (these three sit at the same layer as discovery -- none of them
  |     import discovery; orchestration is what sequences them together)
  v
llm ---------- schemas
recording ----- schemas
validation ---- schemas
policy -------- schemas
  |
  v
schemas | handoff | observability     <-- leaves: zero agent-internal imports
