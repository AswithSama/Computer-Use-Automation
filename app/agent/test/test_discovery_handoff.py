import app.agent.discovery.discovery_agent as discovery_module
import app.agent.orchestration.discovery_flow as discovery_flow_module
from pathlib import Path
from app.agent.discovery.discovery_agent import DiscoveryAgent
from app.agent.handoff.manager import HumanHandoffManager
from app.agent.handoff.models import (
    ExecutionPhase,
    InterventionOutcome,
    InterventionResolution,
    InterventionStatus,
)
from app.agent.orchestration.discovery_flow import DiscoveryFlow
from app.agent.schemas.discovery import ActionType, BrowserAction
from app.agent.validation.validator import (
    ValidationResult,
    ValidationStatus,
)
from app.agent.validation.value_validator_llm import (
    ValidatorDecision,
    ValidatorLLMResult,
)


# =========================================================
# Shared browser fakes
# =========================================================


class FakePage:
    def __init__(self):
        self.url = "about:blank"

    def is_closed(self):
        return False


class FakeBrowserSession:
    last_instance = None

    def __init__(self, headless=False):
        self.headless = headless
        self.page = FakePage()
        self.observe_calls = 0
        self.closed = False

        FakeBrowserSession.last_instance = self

    def start(self):
        pass

    def open(self, url):
        self.page.url = url

    def observe(self):
        self.observe_calls += 1
        return f"observation-{self.observe_calls}"

    def close(self):
        self.closed = True
    
    def capture_handoff_screenshot(
        self,
        *,
        evidence_dir,
        intervention_id,
        ):
        screenshot_dir = Path(evidence_dir) / "screenshots"
        screenshot_dir.mkdir(parents=True, exist_ok=True)

        screenshot_path = (
            screenshot_dir / f"{intervention_id}.png"
        )

        screenshot_path.write_bytes(
            b"synthetic-screenshot-data"
        )

        return str(screenshot_path)


# =========================================================
# Validator-escalation LLM
# =========================================================


class FakeBrowserLLM:
    last_instance = None

    def __init__(self):
        # DiscoveryAgent expects these when FINISH is reached.
        self.client = object()
        self.model = "fake-model"

        self.decide_calls = []

        self.actions = [
            BrowserAction(
                action=ActionType.FILL,
                target_ref="amount",
                target_role="textbox",
                target_name="Amount",
                value="derived-value",
                reason="Value requires validator review.",
            ),
            BrowserAction(
                action=ActionType.FINISH,
                result="Completed after human inspection.",
                outputs=[],
                reason="The task can now finish.",
            ),
        ]

        FakeBrowserLLM.last_instance = self

    def decide(
        self,
        *,
        user_request,
        current_url,
        observation,
    ):
        self.decide_calls.append(
            {
                "user_request": user_request,
                "current_url": current_url,
                "observation": observation,
            }
        )

        return self.actions.pop(0)


class FakeActionValidator:
    def __init__(self):
        self.calls = 0

    def validate(self, **kwargs):
        self.calls += 1

        # First proposed action requires Validator LLM review.
        if self.calls == 1:
            return ValidationResult(
                status=ValidationStatus.NEEDS_LLM,
                reason="Value requires additional review.",
            )

        # Allow the second action, FINISH.
        return ValidationResult(
            status=ValidationStatus.APPROVED,
            reason="Finish is supported by the current observation.",
        )


class FakeValueValidatorLLM:
    def __init__(self, business_policy=""):
        self.business_policy = business_policy

    def validate(self, **kwargs):
        return ValidatorLLMResult(
            decision=ValidatorDecision.ESCALATE_TO_HUMAN,
            reason=(
                "The value cannot be safely approved "
                "or rejected."
            ),
        )


# =========================================================
# Direct REQUEST_HUMAN LLM
# =========================================================


class RequestHumanBrowserLLM:
    last_instance = None

    def __init__(self):
        self.client = object()
        self.model = "fake-model"
        self.decide_calls = []

        self.actions = [
            BrowserAction(
                action=ActionType.REQUEST_HUMAN,
                reason="Human inspection is required.",
            ),
            BrowserAction(
                action=ActionType.FINISH,
                result="Completed after human inspection.",
                outputs=[],
                reason="The task can now finish.",
            ),
        ]

        RequestHumanBrowserLLM.last_instance = self

    def decide(
        self,
        *,
        user_request,
        current_url,
        observation,
    ):
        self.decide_calls.append(
            {
                "user_request": user_request,
                "current_url": current_url,
                "observation": observation,
            }
        )

        return self.actions.pop(0)


class AlwaysApprovedActionValidator:
    """
    Used for REQUEST_HUMAN tests.

    REQUEST_HUMAN must reach its own DiscoveryAgent branch rather than
    accidentally being redirected through NEEDS_LLM.
    """

    def validate(self, **kwargs):
        return ValidationResult(
            status=ValidationStatus.APPROVED,
            reason="Approved for this test.",
        )


class NeverCalledValueValidatorLLM:
    """
    Direct REQUEST_HUMAN should not require Validator LLM escalation.
    """

    def __init__(self, business_policy=""):
        self.business_policy = business_policy

    def validate(self, **kwargs):
        raise AssertionError(
            "ValueValidatorLLM must not be called "
            "for direct REQUEST_HUMAN."
        )


# =========================================================
# Other shared fakes
# =========================================================


class FakeActionExecutor:
    executed_actions = []

    def __init__(
        self,
        page,
        allowed_host: str,
        *,
        policy_engine=None,
        policy_profile_id="read_only_discovery",
        on_policy_decision=None,
    ):
        self.page = page
        self.allowed_host = allowed_host

        # Retain any other existing setup in your fake.
        self.policy_engine = policy_engine
        self.policy_profile_id = policy_profile_id
        self.on_policy_decision = on_policy_decision

    def execute(self, action):
        FakeActionExecutor.executed_actions.append(action)


class FakeDiscoveryLogger:
    def log(self, event_type, **data):
        pass


# =========================================================
# Fake human operators
# =========================================================


class ResolvedOperator:
    def __init__(self):
        self.requests = []

    def handle(self, request):
        self.requests.append(request)

        return InterventionOutcome(
            intervention_id=request.intervention_id,
            resolution=InterventionResolution.RESOLVED,
            operator_id="test-operator",
        )


class UnresolvedOperator:
    def __init__(self):
        self.requests = []

    def handle(self, request):
        self.requests.append(request)

        return InterventionOutcome(
            intervention_id=request.intervention_id,
            resolution=InterventionResolution.UNRESOLVED,
            operator_id="test-operator",
        )


# =========================================================
# Fake registry
# =========================================================


class NoSaveRegistry:
    def __init__(self):
        self.save_draft_called = False

    def save_draft(self, **kwargs):
        self.save_draft_called = True

        raise AssertionError(
            "Assisted discovery must not save a capability draft."
        )


# =========================================================
# Shared patch helper for direct REQUEST_HUMAN scenarios
# =========================================================


def patch_direct_request_human_dependencies(monkeypatch):
    FakeActionExecutor.executed_actions = []

    monkeypatch.setattr(
        discovery_module,
        "BrowserSession",
        FakeBrowserSession,
    )

    monkeypatch.setattr(
        discovery_module,
        "BrowserLLM",
        RequestHumanBrowserLLM,
    )

    monkeypatch.setattr(
        discovery_module,
        "ActionValidator",
        AlwaysApprovedActionValidator,
    )

    monkeypatch.setattr(
        discovery_module,
        "ValueValidatorLLM",
        NeverCalledValueValidatorLLM,
    )

    monkeypatch.setattr(
        discovery_module,
        "ActionExecutor",
        FakeActionExecutor,
    )

    monkeypatch.setattr(
        discovery_module,
        "DiscoveryLogger",
        FakeDiscoveryLogger,
    )


# =========================================================
# TEST 1
#
# Validator cannot safely approve an action.
# Discovery must use the existing handoff mechanism.
# =========================================================


def test_validator_escalation_uses_existing_handoff_and_reobserves(
    monkeypatch,
    tmp_path,
):
    FakeActionExecutor.executed_actions = []

    monkeypatch.setattr(
        discovery_module,
        "BrowserSession",
        FakeBrowserSession,
    )

    monkeypatch.setattr(
        discovery_module,
        "BrowserLLM",
        FakeBrowserLLM,
    )

    monkeypatch.setattr(
        discovery_module,
        "ActionValidator",
        FakeActionValidator,
    )

    monkeypatch.setattr(
        discovery_module,
        "ValueValidatorLLM",
        FakeValueValidatorLLM,
    )

    monkeypatch.setattr(
        discovery_module,
        "ActionExecutor",
        FakeActionExecutor,
    )

    monkeypatch.setattr(
        discovery_module,
        "DiscoveryLogger",
        FakeDiscoveryLogger,
    )

    operator = ResolvedOperator()

    manager = HumanHandoffManager(
        operator=operator,
        evidence_dir=tmp_path / "handoff",
    )

    agent = DiscoveryAgent(
        max_steps=3,
        handoff_manager=manager,
        handoff_enabled=True,
        max_interventions=1,
    )

    result = agent.run(
        user_request="Complete the task.",
        target_url="http://example.test/start",
    )

    assert result is not None

    assert result.human_assisted is True
    assert result.intervention_count == 1
    assert result.candidate_path == []
    assert len(result.evidence_refs) == 1

    assert len(operator.requests) == 1
    assert operator.requests[0].phase == ExecutionPhase.DISCOVERY

    assert manager.state.status == InterventionStatus.RESOLVED

    # Critical:
    # the action proposed BEFORE handoff must never execute.
    assert FakeActionExecutor.executed_actions == []

    browser = FakeBrowserSession.last_instance
    llm = FakeBrowserLLM.last_instance

    # Initial observation
    # + resume verification observation
    # + next discovery observation
    # + final observation.
    assert browser.observe_calls >= 4

    assert len(llm.decide_calls) == 2

    assert (
        llm.decide_calls[0]["observation"]
        == "observation-1"
    )

    # observation-2 was used for resume verification.
    # Discovery reasons again from observation-3.
    assert (
        llm.decide_calls[1]["observation"]
        == "observation-3"
    )

    assert browser.closed is True


# =========================================================
# TEST 2
#
# Discovery LLM explicitly asks for a human.
# This must hit the REQUEST_HUMAN branch directly.
# =========================================================


def test_request_human_uses_existing_handoff_and_reobserves(
    monkeypatch,
    tmp_path,
):
    patch_direct_request_human_dependencies(monkeypatch)

    operator = ResolvedOperator()

    manager = HumanHandoffManager(
        operator=operator,
        evidence_dir=tmp_path / "handoff",
    )

    agent = DiscoveryAgent(
        max_steps=3,
        handoff_manager=manager,
        handoff_enabled=True,
        max_interventions=1,
    )

    result = agent.run(
        user_request="Complete the task.",
        target_url="http://example.test/start",
    )

    assert result is not None

    assert result.human_assisted is True
    assert result.intervention_count == 1
    assert result.candidate_path == []
    assert len(result.evidence_refs) == 1

    assert len(operator.requests) == 1
    assert operator.requests[0].phase == ExecutionPhase.DISCOVERY

    assert manager.state.status == InterventionStatus.RESOLVED

    # REQUEST_HUMAN itself must never be executed as a browser action.
    assert FakeActionExecutor.executed_actions == []

    browser = FakeBrowserSession.last_instance
    llm = RequestHumanBrowserLLM.last_instance

    assert browser.observe_calls >= 4
    assert len(llm.decide_calls) == 2

    assert (
        llm.decide_calls[0]["observation"]
        == "observation-1"
    )

    assert (
        llm.decide_calls[1]["observation"]
        == "observation-3"
    )

    assert browser.closed is True


# =========================================================
# TEST 3
#
# Human cannot resolve the problem.
# Discovery must stop instead of resuming unsafely.
# =========================================================


def test_unresolved_handoff_stops_discovery(
    monkeypatch,
    tmp_path,
):
    patch_direct_request_human_dependencies(monkeypatch)

    operator = UnresolvedOperator()

    manager = HumanHandoffManager(
        operator=operator,
        evidence_dir=tmp_path / "handoff",
    )

    agent = DiscoveryAgent(
        max_steps=3,
        handoff_manager=manager,
        handoff_enabled=True,
        max_interventions=1,
    )

    result = agent.run(
        user_request="Complete the task.",
        target_url="http://example.test/start",
    )

    # Discovery must stop.
    assert result is None

    assert len(operator.requests) == 1
    assert operator.requests[0].phase == ExecutionPhase.DISCOVERY

    # Human returned UNRESOLVED, so manager must not enter RESUMING.
    assert manager.state.status == InterventionStatus.CANCELLED

    # Nothing should have executed.
    assert FakeActionExecutor.executed_actions == []

    browser = FakeBrowserSession.last_instance
    llm = RequestHumanBrowserLLM.last_instance

    # Only the initial discovery observation happened.
    # Because the human reported UNRESOLVED,
    # resume verification should not occur.
    assert browser.observe_calls == 1

    # Discovery must not ask the LLM for another action.
    assert len(llm.decide_calls) == 1

    # Browser still gets cleaned up by finally.
    assert browser.closed is True


# =========================================================
# TEST 4
#
# Full DiscoveryFlow integration.
#
# Human-assisted discovery may complete the current request,
# but must NOT become an autonomous reusable capability.
# =========================================================


def test_discovery_flow_assisted_run_does_not_save_capability_draft(
    monkeypatch,
    tmp_path,
):
    patch_direct_request_human_dependencies(monkeypatch)

    # If DiscoveryFlow reaches capability compilation after an assisted
    # result, this immediately fails the test.
    def must_not_build_capability_context(*args, **kwargs):
        raise AssertionError(
            "Assisted discovery must return before "
            "capability compilation."
        )

    monkeypatch.setattr(
        discovery_flow_module,
        "CapabilityContextBuilder",
        must_not_build_capability_context,
    )

    operator = ResolvedOperator()

    manager = HumanHandoffManager(
        operator=operator,
        evidence_dir=tmp_path / "handoff",
    )

    registry = NoSaveRegistry()

    flow = DiscoveryFlow(
        target_url="http://example.test/start",
        tenant_id="tenant-test",
        app_id="app-test",
        registry=registry,
        ask_llm=lambda prompt: "unused",
        handoff_manager=manager,
        handoff_enabled=True,
        max_interventions=1,
    )

    # Use "savings" deliberately.
    #
    # Without the human-assisted safety guard,
    # this request would continue into the capability compiler.
    result = flow(
        "Get the savings balance."
    )

    assert result is not None

    assert result.human_assisted is True
    assert result.intervention_count == 1
    assert result.candidate_path == []

    assert len(operator.requests) == 1
    assert operator.requests[0].phase == ExecutionPhase.DISCOVERY

    assert manager.state.status == InterventionStatus.RESOLVED

    # Core safety guarantee:
    # assisted discovery cannot become a reusable capability draft.
    assert registry.save_draft_called is False

    assert FakeActionExecutor.executed_actions == []

    assert FakeBrowserSession.last_instance.closed is True