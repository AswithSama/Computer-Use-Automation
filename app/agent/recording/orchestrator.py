from app.agent.second_phase.capability_registry import CapabilityRegistry
from app.agent.second_phase.capability_router import CapabilityRouter
from app.agent.discovery.models import RouteDecision, TaskRequest


class AutomationOrchestrator:
    def __init__(self):
        self.registry = CapabilityRegistry()
        self.router = CapabilityRouter()

    def handle(self, request: TaskRequest) -> RouteDecision:
        capabilities = self.registry.list_capabilities()

        decision = self.router.route(
            request=request,
            capabilities=capabilities,
        )

        return decision