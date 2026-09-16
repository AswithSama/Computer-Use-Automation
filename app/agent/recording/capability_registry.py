import json
from pathlib import Path

from app.agent.discovery.models import CapabilitySummary


class CapabilityRegistry:
    def __init__(self, artifact_directory: str = "artifacts"):
        self.artifact_directory = Path(artifact_directory)

    def list_capabilities(self) -> list[CapabilitySummary]:
        capabilities: list[CapabilitySummary] = []

        if not self.artifact_directory.exists():
            return capabilities

        for artifact_path in self.artifact_directory.glob("*.json"):
            try:
                with artifact_path.open("r", encoding="utf-8") as file:
                    artifact = json.load(file)

                capability = CapabilitySummary(
                    capability_id=artifact["capability_id"],
                    version=artifact["version"],
                    description=artifact["description"],
                    inputs=artifact.get("inputs", {}),
                    outputs=artifact.get("outputs", {}),
                )

                capabilities.append(capability)

            except (KeyError, json.JSONDecodeError):
                # Ignore malformed/incomplete artifacts for now.
                continue

        return capabilities