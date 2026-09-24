# Design Report — Computer-Use Automation System

## 1. Architecture

### Target application: a local banking demo

I built a local banking website using FastAPI and Jinja2, populated with synthetic member and account records. A user can search for a member by ID, view their email, phone number, and membership status, and retrieve savings or checking balances.

The website presents this information through browser pages and HTML tables. It gives the automation system a controlled environment in which to test navigation, member lookup, data extraction, error handling, and human intervention without accessing real banking systems or customer information.

The demo also includes an `/operations` area that the automation policy intentionally blocks.

### The execution lifecycle

The system follows two paths depending on whether an approved capability already exists for the request:

| Request                                | Execution path                                                                                      |
| -------------------------------------- | --------------------------------------------------------------------------------------------------- |
| An eligible approved capability exists | Select the capability and replay its saved browser actions using the current runtime inputs.        |
| No valid capability matches            | Start live LLM-driven discovery, verify the resulting workflow, and compile a new draft capability. |

During discovery, Playwright observes the live application and the LLM proposes the next browser action. The application—not the model alone—grounds the proposal, checks policy, executes the action, and verifies its outcome before recording it.

The trajectory recorder preserves the exploration trace while constructing a candidate path. Fingerprint-based loop removal and fresh-session verification can shorten that path without assuming that every apparently redundant action is safe to remove.

Once the input and output bindings have been verified, the compiler produces a versioned **draft capability**. A human must explicitly approve that draft before it becomes eligible for future requests.

### Why this architecture?

I used Python and Pydantic to make component contracts explicit, Playwright to interact with a real browser, and a local JSON registry to keep artifact storage simple and inspectable.

**The key trade-off:** I prioritized a coherent, testable browser implementation over building generalized computer-use infrastructure before validating the core workflow.

An LLM still helps *select* a capability in the interactive entry point. “Model-free replay” refers specifically to the saved browser-action execution path—not to every surrounding orchestration call.

For the complete architecture diagram and component-level walkthrough, see [DEEPDIVE.md — System Architecture](DEEPDIVE.md#2-system-architecture).

## 2. Artifact schema

### A capability is an execution contract, not a transcript

The durable artifact is typed, serializable, versioned, and designed for reuse. `CapabilityArtifact` defines:

* A semantic capability ID and description.
* Typed required inputs.
* Ordered `CapabilityAction` records, including action type, target, value, and URL.
* Action-indexed checkpoints.
* Typed outputs and their extraction bindings.

The registry record adds tenant/application scope, version, approval state, selection context, and relevant business-outcome rules.

### How the workflow becomes reusable

The compiler replaces verified request-specific values with runtime placeholders such as `{{member_id}}` in supported actions and checkpoint patterns. An input is accepted only when it is grounded in both the original request and a successfully recorded fill action.

For outputs, the implemented binding uses a meaningful HTML-table relationship:

| Binding component      | Example                                                       |
| ---------------------- | ------------------------------------------------------------- |
| Row condition          | `Type = Savings`                                              |
| Value column           | `Current Balance`                                             |
| Extraction requirement | Exactly one value matching the verified discovery observation |

This means replay retrieves the balance associated with the *current member’s savings row*, rather than returning a value cached from the original discovery run.

**The key trade-off:** I implemented narrow, verifiable table extraction instead of claiming support for arbitrary page structures. Draft and approved snapshots also remain separate: a successful discovery does not authorize unattended execution.

## 3. Determinism & error handling

### Replay follows a verified path

Before acting, replay resolves required inputs and validates artifact references. It then executes the recorded actions in order using role/name-oriented targeting, bounded waits, active policy checks, and action-indexed URL/text checkpoints.

A completed browser command is not automatically considered a successful step. The relevant checkpoint must confirm that the application reached the expected state, and output extraction must produce exactly one unambiguous match.

### Not every unsuccessful run means the same thing

The structured `ReplayResult` distinguishes outcomes so the caller can respond appropriately:

| Result                | Meaning                                                                                  |
| --------------------- | ---------------------------------------------------------------------------------------- |
| `success`             | The workflow completed and returned its declared outputs.                                |
| `business_outcome`    | Configured evidence confirms an expected result, such as member-not-found.               |
| `recoverable_failure` | A condition such as missing required input prevents execution.                           |
| `needs_intervention`  | The run requires a supported human handoff.                                              |
| `hard_failure`        | Execution cannot safely continue; the result includes structured, sanitized diagnostics. |

A missing value is not automatically interpreted as a missing member. That business outcome must be supported by configured application evidence.

Similarly, a missing or ambiguous target, failed checkpoint, or missing or ambiguous output cannot become a guessed success. Because a timed-out action may already have affected the application, replay does not blindly retry or skip uncertain interactions.

**The key trade-off:** The system primarily stops safely or follows a specifically supported, checkpoint-verified human recovery path. It does not attempt open-ended model-driven repair during replay.

These guarantees apply to the observed demo application, recorded workflow, and supported selectors and bindings; they are not a guarantee against arbitrary UI changes.

## 4. Heterogeneity & multi-tenant

### What works today

The implemented execution surface is browser-based and uses Playwright with accessibility-oriented action targeting. Registry eligibility is scoped to `tenant_id` and `app_id`.

### How I would extend it

To support legacy web and native desktop applications, I would introduce a surface-adapter interface separating observation, control location, action execution, and state extraction from the artifact’s typed business contract and replay result.

An adapter could use DOM/accessibility information, screenshots and coordinates, or OS-level desktop automation. Locator and checkpoint variants would still need to reflect the capabilities of each surface; a browser locator cannot directly operate a desktop application.

For reuse across institutions, I would maintain a versioned vendor/application-level capability definition with tenant-specific configuration or explicitly reviewed locator and route overrides.

Before allowing reuse, the system would verify the tenant’s vendor/application version, allowed routes, required controls, checkpoints, and output schema. An incompatible variant would be held for review or rediscovery rather than silently redirected to a similar-looking target. Tenant-specific authorization and policy would still apply at invocation.

**Implementation boundary:** Surface adapters, cross-tenant artifact sharing, and automatic vendor-version drift detection are design extensions—not features of the current system.

## 5. Escalation & handoff

### When automation cannot safely continue

Discovery can request human intervention when an action cannot be grounded or safely continued. Replay can hand off when it encounters a supported application-level obstacle.

The handoff manager pauses automation, preserves the **same live browser session**, records the intervention reason and context, and temporarily transfers control to a terminal-based human operator. Automation and the operator must not act on the session simultaneously.

### What happens when the operator finishes?

During handoff, automation pauses while the authorized operator works in the same live browser session. The intervention preserves the execution phase, current step, reason for escalation, relevant evidence references, and available screenshot evidence.

Before returning control, the operator records what they did using a constrained set of reviewed action summaries. This is persisted as `operator_reported_action` in the handoff evidence rather than as unrestricted free-form text. These summaries are operator-reported declarations, not independently captured browser events.

After the operator signals completion, returning control does not by itself authorize automation to continue. Supported replay continuation independently rechecks the relevant URL or visible-text checkpoint. Only successful verification allows the suspended flow to resume; if the expected state cannot be verified, the run stops. A human-entered answer or arbitrary page position is therefore never treated as a verified replay result.

The resulting handoff record preserves why intervention occurred, what the operator reported doing, how the intervention was resolved, and whether the post-intervention state was verified for safe continuation.


## 6. Safety

### Policy remains application-owned

The policy engine constrains permitted origins, routes, action types, and configured targets independently of the LLM’s proposal or a capability’s approval state.

The demo treats configured member and account lookup operations as read-only safe actions. The `/operations` area represents the risky or potentially irreversible action class and is blocked by policy rather than exercised by the automation. This keeps the implemented demonstration read-only while making the safety boundary explicit; the system does not claim to validate real money movement or other irreversible banking operations.

During discovery, grounding checks that proposed elements and certain values are supported by the observed UI and user request. A bounded validator-LLM path can handle cases where deterministic evidence is insufficient, but it does not grant arbitrary new action authority.

Replay rechecks the active policy rather than assuming that an approved artifact remains authorized indefinitely.

### Evidence is useful, but must be constrained

Failure reports retain restricted, reviewed diagnostic fields instead of unrestricted page text, raw inputs, URLs, or exception payloads.

This reduces exposure, but it is not a production security audit. Screenshots, demo data, logging configuration, and operator access would still require review before use with real regulated information.

## 7. Cuts

### What I prioritized

I focused on completing one observable execution lifecycle:

**Natural-language goal → discovery → verified artifact → human approval → deterministic replay → structured outcome or handoff**

The aim was to demonstrate that these pieces work together, including their validation and safety boundaries, rather than implementing a broad collection of partially connected features.

### What I deliberately left out

| Area                | Outside the implemented scope                                                                                      |
| ------------------- | ------------------------------------------------------------------------------------------------------------------ |
| Execution surfaces  | Native desktop and screenshot/coordinate adapters.                                                                 |
| Extraction          | Generalized non-table output bindings.                                                                             |
| Reuse and scale     | Automatic cross-tenant/vendor-version reuse, drift handling, distributed workers, and production tenant isolation. |
| Human intervention  | A full operator co-browsing console.                                                                               |
| Recovery            | Unrestricted model-driven replay repair.                                                                           |
| Production security | Handling of real regulated data and irreversible banking actions at production standard.                           |

Semantic/RAG-based *capability retrieval* is another proposed scaling option, not implemented selection infrastructure. It should not be confused with any application-context retrieval used during discovery.

### What I would build next

The current implementation already demonstrates the complete capability lifecycle, including live LLM-driven discovery, verified capability generation, human approval, deterministic replay, structured outcomes, failure handling, human-assisted recovery, and saved execution evidence.

The next step would be to validate the architecture against a second, deliberately different application surface through the proposed surface-adapter seam. This would test whether the separation between the capability contract and the underlying browser or desktop interaction mechanism holds beyond the original demo application.

From there, I would introduce explicit application/version compatibility checks and tenant-specific overrides to support controlled capability reuse across institutions running variants of the same vendor product. After establishing those reuse boundaries, I would expand the supported output-binding strategies and add narrowly scoped recovery mechanisms for additional runtime conditions, with explicit verification criteria for each extension.

**The guiding decision:** Keep the verified core lifecycle stable while extending the system outward—first across application surfaces and tenant variants, then into broader extraction and recovery behavior—without weakening the validation, policy, and evidence guarantees already established.

