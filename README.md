# Computer-Use Automation System

A small working example of an AI-assisted system that operates a banking-style website through its user interface. It learns a task once, saves the steps for review, and can run an approved task again without asking the AI to choose every click.

This project was built for the interface.ai Computer-Use Automation take-home assignment. It uses a **local demo website with made-up banking data**; it does not access a real bank or real customer accounts.

> **Screenshot placeholder — Project overview:** Add a clear screenshot of the local demo application's home page here. Save it as `docs/screenshots/demo-home.png`, then replace this note with `![Local banking demo](docs/screenshots/demo-home.png)`.

## What the project does

A user can ask a question such as **“Look up member 12345 and tell me their current savings balance.”** When no suitable approved workflow exists, the system opens the local banking website, observes its pages, and uses an AI model to choose the next permitted action. If it completes the task and can verify how to retrieve the requested output, it saves a reusable workflow as a **draft**.

A person must review and approve that draft before it can be reused. On a later request, the system can select the approved workflow, fill in the new input, follow its saved steps without using the model to decide the browser actions, check that each important page was reached, and return the requested information. The AI may still be used to select a saved workflow and interpret the user's request; **the replayed browser steps themselves do not use the AI to choose actions**.

When an action is unsafe, a page gives an unexpected result, or automation cannot continue confidently, the system can stop and request human help instead of blindly proceeding.

## Quick start

Run these commands from the **project root**, the folder containing `app/`. The uploaded project snapshot contains the `app/` source folder but does **not** contain a dependency file or a pre-populated `evidence/` folder. The commands below install the packages used by the supplied source; if your final repository has a maintained `requirements.txt`, use that instead.

**1. Create a Python environment and install packages.** Python 3.12 is a suitable version for this project snapshot.

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install fastapi uvicorn jinja2 python-dotenv openai playwright pydantic pytest
python -m playwright install chromium
```

On Windows, activate the environment with `.venv\Scripts\activate` instead. Playwright needs a browser installed even if the Python packages are already present.

**2. Set the model API key.** Create a file named `.env` in the project root:

```dotenv
OPENAI_API_KEY=your_api_key_here
OPENAI_MODEL=gpt-5-mini
LOG_LEVEL=INFO
```

Replace the sample key with your own. `OPENAI_MODEL` is optional; the source defaults to `gpt-5-mini`. Do **not** commit `.env`, API keys, credentials, or private run data to GitHub. A valid API key and network access are needed for a genuine AI-guided discovery run and for model-based capability selection. The tests described below can run without calling a live model.

**3. Start the local banking demo.** Open a terminal at the project root and run:

```bash
source .venv/bin/activate
python -m uvicorn app.target_app.main:app --host 127.0.0.1 --port 8000
```

Leave this terminal running and open [http://127.0.0.1:8000](http://127.0.0.1:8000). The agent's target URL and safety settings currently use this exact local address and port; changing them requires updating the corresponding configuration.

> **Screenshot placeholder — Demo application:** Capture the dashboard and member-search page, using only the included synthetic records. Suggested image paths: `docs/screenshots/dashboard.png` and `docs/screenshots/member-search.png`.

**4. Open a second terminal and start the automation.** From the same project root:

```bash
source .venv/bin/activate
python -m app.agent.main
```

When you see `What do you want to do?`, enter:

```text
Look up member 12345 and tell me their current savings balance.
```

The first successful run with no matching approved capability starts **discovery**: a visible browser opens and the model explores the site. Depending on what the run verifies, it may save a draft for approval. If discovery fails or cannot verify a reusable output, it will not necessarily produce a draft. Check the terminal result rather than assuming one was saved.

> **Screenshot placeholder — Discovery:** Capture the agent terminal during the actual AI-guided run and the browser showing the result. Suggested paths: `docs/screenshots/discovery-terminal.png` and `docs/screenshots/discovery-result.png`.

## Review and approve a saved workflow

A saved workflow is called a **capability**. Discovery saves new capabilities as drafts rather than making them immediately available for automatic replay. To review the drafts, run the following command in another terminal, or after the discovery command exits:

```bash
python -m app.agent.registry.approve
```

The review command shows each pending draft and offers **A** to approve, **S** to skip, or **Q** to quit. Read the saved steps, inputs, expected outputs, and checkpoints before approving. Approval saves a separate approved record; it does not edit the original draft in place.

By default, the project stores drafts and approved records under `capabilities/demo_tenant/demo_banking_app/`. The filenames include generated identifiers, so do not rely on one fixed artifact filename.

> **Screenshot placeholder — Capability review:** Capture a draft in the approval terminal, with the approval action visible. Suggested path: `docs/screenshots/capability-approval.png`. If showing the JSON file, hide anything that should not be published.

## Replay an approved workflow

Keep the demo website running, then launch the same entry point:

```bash
python -m app.agent.main
```

Enter the same type of request, for example:

```text
Look up member 12345 and tell me their current savings balance.
```

The system checks the approved capability list. When its selector finds a suitable match, it runs the saved steps in the browser using the inputs for this request. It checks the expected page states and retrieves the declared output. If it finds no approved match, it starts discovery instead. The selected path is shown in the terminal, so confirm that the run actually says it is **reusing an approved capability** before presenting it as replay evidence.

> **Screenshot placeholder — Replay:** Capture the terminal displaying the approved capability selection, replay status, completed steps, and returned output. Suggested path: `docs/screenshots/replay-success.png`.

## How the pieces fit together

```text
User request
    |
    v
Check approved capabilities ---- matching capability ----> Replay saved steps
    |                                                     |
    | no suitable match                                   v
    v                                               Check page states
AI-guided discovery                                        |
    |                                                     v
    v                                               Read verified output
Record actions and verify output                           |
    |                                                     v
    v                                                Return result
Save capability as draft
    |
    v
Human reviews and approves
    |
    +-------------------------------> Available for later replay

At any blocked or unsafe point: stop / request human help.
```

The `app/target_app/` folder contains the local website and fake account data. The `app/agent/` folder contains the automation. Inside it, `discovery/` explores the live site; `recording/` records and shortens the observed path; `capability/` builds the reusable workflow and its inputs and outputs; `registry/` saves and approves capabilities; and `replay/` executes approved steps and reports results. The `orchestration/` folder connects discovery, selection, and replay. The `policy/` folder controls which pages and actions are allowed; `handoff/` manages human intervention; `observability/` records discovery evidence; `schemas/` defines the saved data shapes; `validation/` checks actions and results; and `llm/` contains model calls.

## What a saved capability contains

A capability is a structured JSON record rather than a pasted transcript of the AI conversation. It records a version and capability name, the inputs that must be provided, the ordered browser actions, the page elements those actions target, the conditions to check along the way, and the outputs to read at the end. The approved registry record also contains information used to decide whether it matches a new request. The current output-reading approach is built around verified table rows and columns in the demo application; it should not be described as a general-purpose extractor for every possible screen.

You can inspect a draft or approved JSON record in `capabilities/demo_tenant/demo_banking_app/` after running discovery and approval. The saved artifact should be understandable without the original AI conversation. It is still important to review its recorded actions and output rules before using it.

> **Screenshot placeholder — Saved capability:** Capture a short, readable part of a real generated JSON record showing its version, inputs, actions, checkpoints, and outputs. Suggested path: `docs/screenshots/capability-json.png`.

## Safety and handling unexpected results

The example policy is defined in `app/agent/policy/demo_banking.json`. It restricts the agent to the local demo origin, lists permitted routes and action types, and blocks the demo's `/operations` pages. The example workflows focus on reading information rather than performing banking transactions. A blocked action should not be retried by bypassing the policy. Do not use this demo against real banking systems or with real customer information.

Replay reports a clear status rather than assuming every click worked. Its result distinguishes a successful run, a known business outcome, a condition that may be recoverable, a case needing human intervention, and a hard failure. The result can include the completed step count, failed step, a short reason, and paths to available evidence. A missing member, for example, is a business result to communicate, not the same thing as a browser crash. A permission problem or a failed page check should not be silently treated as success.

This is a local demonstration, not a production security guarantee. The demo uses made-up account data. Real deployments would also need secure handling of browser sessions, access to screenshots, logs, credentials, and approval permissions.

> **Screenshot placeholder — Unexpected result:** Capture a controlled replay with a missing demo member or another safe, repeatable error, showing the resulting status and explanation. Suggested path: `docs/screenshots/replay-error.png`.

## Human help and handing control back

When discovery or replay cannot safely finish, the system can ask a person to intervene. The local operator interface runs in the terminal and uses the **same live browser session**: automation pauses, the operator can inspect the page and perform the required manual action, and the operator then records what they did and whether the condition is resolved. The system decides whether it can continue or should stop. The handoff stores an intervention record, and the local demo can capture a screenshot of the stopped page.

A repeatable **replay handoff demo** is available after a suitable reviewed `get_savings_balance` capability has been approved. With the demo website running, start the agent using:

```bash
HANDOFF_DEMO=1 python -m app.agent.main
```

Enter a request that selects the approved savings-balance capability. This local-only demo adds a temporary checkpoint condition during replay to create a human-intervention moment; it does **not** modify the saved capability. Follow the terminal's instructions, work in the already-open browser window, and report the outcome in the terminal. The demo depends on the approved capability and its allowed checkpoint-resume setting, so it will not activate for every possible saved workflow. Remove the `HANDOFF_DEMO=1` prefix for normal runs.

> **Screenshot placeholder — Human handoff:** Capture the paused automation, the terminal intervention prompt, and the same browser window being used by the operator. Suggested paths: `docs/screenshots/handoff-request.png`, `docs/screenshots/handoff-browser.png`, and `docs/screenshots/handoff-result.png`. Do not portray an injected demo condition as an unplanned production failure.

## Tests and running without live model services

The included automated tests are under `app/agent/test/`. From the project root, run:

```bash
python -m pytest app/agent/test -q
```

These tests cover parts of the architecture, policy checks, path handling, recording, replay actions, and handoff. They are useful for checking code behavior without doing a new paid AI-guided discovery run. The included local demo server itself does not need an OpenAI key. **Tests are not a substitute for the required genuine live discovery and replay demonstration.** In particular, a fully offline run of the main agent is not provided as a documented supported mode in this snapshot: its capability-selection path uses a model.

> **Screenshot placeholder — Tests:** Capture the completed test summary from your final repository after running the command above. Suggested path: `docs/screenshots/pytest-results.png`. Use actual test output, not a mock terminal image.

## Evidence for reviewers

The assignment requires an `evidence/` directory containing a **real AI-driven discovery run**, a saved example capability, and logs from both discovery and replay. It also recommends including a replay with an expected error or exceptional result; a short screen recording is optional. The code writes discovery logs and replay evidence under `evidence/` and stores handoff records under `evidence/handoff/`, but the uploaded source snapshot does **not** include these generated run files. Create the required evidence by running the complete demo before submitting the public repository.

Keep a reviewable copy of the actual saved example artifact inside `evidence/` in addition to the runtime copy under `capabilities/`. For each run, include an easily recognized log or result file and, where useful, the corresponding screenshots. Redact secrets and avoid publishing sensitive browser state. In the final repository, replace the screenshot notes in this README with links to real images that you have captured. Only claim that a scenario passed if its included log or image actually demonstrates it.

## Design details, limitations, and next steps

See [`REPORT.md`](REPORT.md) for the separate short design write-up required by the assignment. It should use these **exact seven headings**: **Architecture**, **Artifact schema**, **Determinism & error handling**, **Heterogeneity & multi-tenant**, **Escalation & handoff**, **Safety**, and **Cuts**. That report is the place to explain key decisions and trade-offs, how another website or desktop application could be supported, how workflows could be reused safely across institutions, which parts are simplified or mocked, and what would be built next. The current implementation operates on one local browser-based surface; desktop automation and a full multi-institution deployment are not demonstrated by this repository snapshot.

For final submission, publish the source, `README.md`, `REPORT.md`, and the required sanitized `evidence/` folder in a **public GitHub repository**. As specified in the assignment, email the repository URL on its own line to `assignments@interface.ai` from the email address used for the application; submit the GitHub link, **not a ZIP file**.
