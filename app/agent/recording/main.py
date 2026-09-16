from app.agent.discovery.models import TaskRequest
from app.agent.second_phase.orchestrator import AutomationOrchestrator


def main():
    print("\nComputer-Use Automation\n")

    goal = input("Goal: ").strip()

    target = input(
        "Target [http://127.0.0.1:8000]: "
    ).strip()

    if not target:
        target = "http://127.0.0.1:8000"

    request = TaskRequest(
        goal=goal,
        target=target,
    )

    orchestrator = AutomationOrchestrator()

    decision = orchestrator.handle(request)

    print("\nRouting decision:")
    print(decision.model_dump_json(indent=2))


if __name__ == "__main__":
    main()