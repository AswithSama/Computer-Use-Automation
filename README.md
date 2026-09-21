## Value Grounding and Validation Strategy

During LLM-driven discovery, the system must prevent the model from introducing unsupported values into browser actions. A proposed value can generally fall into one of three categories:

* **User-grounded value** — directly supported by the original user request or invocation inputs.
* **Page-grounded value** — directly supported by information observed from the application during the current session.
* **Derived or unverified value** — a value that cannot be directly grounded in either trusted source and may have been transformed, inferred, calculated, or hallucinated by the model.

### Keep provenance outside the main LLM

The main discovery LLM should not be responsible for declaring where its own proposed value came from. For example, the model should not be trusted to return:

```text
value = "12345"
source = "user_input"
```

and have the system accept that source declaration.

The discovery LLM's responsibility should remain narrow:

```text
Observe → decide what to do next → propose an action
```

For a fill action, it can propose the target and value. The validation layer is responsible for determining whether that value is actually grounded.

This keeps responsibilities separated:

```text
Discovery LLM
    → What should I do next?

Deterministic Validator
    → Can the proposed action/value be proven from trusted information?

Validator LLM
    → Is an unverified or derived value acceptable under business policy?

Human Operator
    → Resolve cases that cannot be safely approved automatically.
```

### Deterministic grounding first

Whenever the discovery LLM proposes a value, deterministic validation should be attempted before involving another model.

Conceptually:

```text
LLM proposes value
        ↓
Can it be directly grounded in trusted user input?
        ↓
YES → grounded

NO
        ↓
Can it be directly grounded in trusted page/session information?
        ↓
YES → grounded

NO
        ↓
DERIVED / UNVERIFIED
        ↓
Validator LLM
```

The exact grounding implementation can evolve. A simple implementation can normalize and compare values against the user request and browser observations. A more mature implementation can maintain structured trusted session state containing values encountered during the run and their origins.

For example:

```text
member_id = 12345
origin = user_input

account_id = SAV-10022
origin = page_observation

balance = $4,250.75
origin = page_observation
```

Maintaining session-level evidence is useful because a value observed on one page may legitimately be needed several steps later, after it is no longer present in the current browser observation.

### Derived values

Derived values are legitimate in computer-use workflows. Examples include converting "tomorrow" into an absolute date, joining a first and last name, formatting a phone number, or transforming a value into the format expected by an application.

However, a value that cannot be directly grounded should not automatically be trusted.

There is also an important distinction between **derived** and **unknown**. If deterministic validation cannot find a proposed value in trusted inputs or observations, that does not prove that the model correctly derived it. The value could also be hallucinated.

Therefore, the safest internal classification is effectively:

```text
DIRECTLY GROUNDED
or
DERIVED / UNVERIFIED
```

Any derived or otherwise unverified value is route


## Validation Notes

* Do not let the main LLM decide whether a value came from the user request or from page information. The system should determine this deterministically.

* If the value proposed by the LLM cannot be directly grounded in either trusted user input or trusted page/session information, treat it as derived or unverified.

* A derived/unverified value should always be sent to a separate Validator LLM before it is used in a browser action.

* The Validator LLM should make one of three decisions:

  * `APPROVE`
  * `ESCALATE_TO_HUMAN`
  * `REJECT`

* The Validator LLM should not perform the browser action itself. It only decides whether the proposed value is safe and justified. The normal executor performs the action after approval.

* Deterministic validation should happen before invoking the Validator LLM wherever possible. These checks can include:

  * text normalization
  * exact/value grounding against the user request
  * value grounding against current or previous trusted page observations
  * data type and format checks
  * duplicate action checks
  * browser action validation
  * target/reference validation
  * allowed-action and navigation checks
  * semantic similarity checks where deterministic matching is insufficient

### High-level flow

```text
Main LLM proposes action + value
            ↓
Deterministic validation
            ↓
Can value be directly grounded?
      ↓                   ↓
     YES                  NO
      ↓                   ↓
   APPROVE        DERIVED / UNVERIFIED
                              ↓
                       Validator LLM
                              ↓
                 APPROVE / HUMAN / REJECT
                              ↓
                    Browser Executor
```

The general principle is:

> Use deterministic checks for anything that can be proven directly. Use the Validator LLM only when interpretation is required. Escalate to a human when the system still cannot safely justify the value.


## Field-Value Compatibility and Semantic Validation

### Grounding does not guarantee field correctness

The deterministic validator verifies whether a proposed value is supported by trusted information. However, a value being grounded does not necessarily mean it belongs in the target field.

For example:

```text
User request:
"John is 42 years old."

Target field:
Name

Proposed value:
42
```

The value `42` is genuinely present in the user request, so provenance/grounding validation succeeds. However, it is clearly inappropriate for a `Name` field.

This creates two separate validation questions:

```text
1. PROVENANCE / GROUNDING
   Did this value come from trusted information?

2. FIELD-VALUE COMPATIBILITY
   Is this trusted value appropriate for this particular field?
```

The current implementation focuses primarily on the first problem.

### Why semantic similarity was considered

One possible approach for field-value compatibility is semantic similarity.

Instead of only checking the raw value, the system could compare the context in which the value appeared with the target field.

For example:

```text
Source evidence:
"from checking account 12345"

Target:
"Destination account"
```

Although `12345` is a valid and grounded account number, the surrounding context indicates that it represents the source account rather than the destination account.

Similarly:

```text
Source evidence:
"to savings account 67890"

Target:
"Destination account"
```

is semantically much more appropriate.

This is important because comparing only the raw values is often insufficient. Values such as account numbers, IDs, dates, and numeric amounts carry little semantic meaning by themselves. Their surrounding context provides the useful information.

### Why semantic similarity is not currently implemented

Semantic compatibility is a legitimate additional safety layer, but it is intentionally not part of the current implementation.

Adding it would introduce additional complexity:

* embedding/model dependency,
* similarity thresholds,
* threshold tuning,
* false positives and false negatives,
* additional latency and cost,
* more validation logic to test and explain.

The expected benefit is relatively small for the current vertical slice because most actions are reversible and the system already has multiple validation layers.

Therefore, the current implementation prioritizes a smaller and more deterministic validation pipeline rather than attempting to solve every possible field-value mismatch.

### Current validation strategy

Before a browser action is executed, the system performs deterministic checks where possible:

```text
Proposed Action
      ↓
Target/reference validation
      ↓
Value normalization
      ↓
Value grounding
   ┌───────────────┐
   │               │
User input     Page/session
   │               │
   └───────┬───────┘
           ↓
      Grounded?
      /       \
    YES        NO
     ↓          ↓
 Continue    Validator LLM
 validation      ↓
             APPROVE
             REJECT
             HUMAN
```

A value that cannot be directly grounded is never automatically trusted. It is routed to the Validator LLM for additional evaluation.

### Downstream validation as an additional safety net

A grounded value can still be used incorrectly. For reversible operations, the system can often detect this through the subsequent application state.

For example:

```text
Wrong grounded value entered
        ↓
Application produces unexpected state
        ↓
Expected element/result does not appear
        ↓
Checkpoint or success condition fails
        ↓
Retry / failure / human escalation
```

Therefore, validation does not stop when an action is approved.

The system also verifies that the workflow continues toward the expected state and ultimately reaches its declared checkpoint or success condition.

This provides defense at two points:

```text
BEFORE ACTION
- Is the target valid?
- Is the action allowed?
- Is the value grounded?
- Is navigation permitted?

AFTER ACTION
- Did the application respond as expected?
- Is the workflow still progressing?
- Was the expected state reached?
- Did the final checkpoint succeed?
```

### Risk-based distinction

Relying partly on downstream validation is reasonable for safe and reversible actions such as:

* searches,
* filters,
* navigation,
* opening records,
* reading information.

It is not sufficient for risky or irreversible operations.

For actions such as:

```text
transfer funds
delete a record
submit a transaction
change account settings
confirm an irreversible operation
```

the system should apply stronger validation before execution because discovering the mistake afterward may be too late.

The architecture therefore leaves room for stricter pre-execution validation or mandatory human confirmation for risky actions.

### Future extension

Field-value compatibility can be added later as another validation layer:

```text
Value grounded
      ↓
Basic deterministic compatibility checks
      ↓
Semantic compatibility signal
      ↓
Clearly compatible → APPROVE
Clearly incompatible → REJECT
Ambiguous → Validator LLM / Human
```

Basic deterministic checks could handle obvious cases first, such as email, date, numeric, phone, or other strongly typed fields.

Semantic similarity would then only provide additional evidence for ambiguous fields such as:

```text
Primary Contact
Applicant
Beneficiary
Recipient
Customer Legal Name
```

Importantly, semantic similarity would not independently authorize an action. It would be treated as a weaker validation signal, with uncertain cases routed to the Validator LLM.

### Design decision

For the current implementation, semantic field-value compatibility is deliberately left out.

The system instead prioritizes:

```text
deterministic grounding
        +
action/target safety checks
        +
risk-aware execution
        +
post-action/checkpoint validation
        +
Validator LLM for unverified values
        +
human escalation when necessary
```

This keeps the core implementation small, understandable, and deterministic while leaving a clear extension point for semantic compatibility validation if production experience shows that wrong-grounded-value errors are significant.

The guiding trade-off is:

> Grounding protects against invented values. Checkpoints protect against workflows that do not reach the intended result. Semantic field-value compatibility is a useful additional defense, but its complexity is not justified for the current implementation and can be introduced later if real failure patterns require it.

ITS NOT RIGHT TO LET LLM DECIDE ON THE JSON JUST AFTER IT SEES THE NATURAL LANGUAGE QUESTION BECAUSE IT DOESN'T HAVE EXPLICIT CONTEXT AND MAY MISS THE 
IMP PART OF THE QUESTION

THE REASONING IT PERFORMED WHILE IT IS EXPLORING THE WEBSITE IS REALLY IMPORTANT FOR THE NEXT REPLAY STEPS. THAT REASONING SAYS A LOT ABOUT HOW IT MADE
DECISION AND WHAT CAN BE THE INPUTS AND OUTPUTS AND WHAT ARE THE KEY WORDS AND THAT CAN BE LATER USED TO FETCH THE SIMILARITY BETWEEN THE NEW QUESTION 
AND EXISTING SAVED WORKFLOW RECORDS

I only use model reasoning where semantics are genuinely required. State-transition detection itself is deterministic because the discovery trace already contains before/after state evidence.