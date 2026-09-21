from pathlib import Path

from app.agent.capability.registry import CapabilityRegistry


def find_pending_drafts(
    registry: CapabilityRegistry,
) -> list[Path]:
    root = registry.directory

    if not root.exists():
        return []

    pending = []

    # Search draft locations only:
    # capabilities/<tenant>/<app>/<draft>.json
    # This excludes the nested approved/ directories.
    for path in sorted(root.glob("*/*/*.json")):
        try:
            stored = registry.load(path)
        except Exception as exc:
            print(f"[WARNING] Could not load {path}: {exc}")
            continue

        if stored.approval_status != "draft":
            continue

        # Ensure the metadata agrees with the directory.
        if (
            path.parent.name != stored.app_id
            or path.parent.parent.name != stored.tenant_id
        ):
            print(f"[WARNING] Registry location mismatch: {path}")
            continue

        pending.append(path)

    return pending


def already_approved(
    registry: CapabilityRegistry,
    draft,
) -> bool:
    eligible = registry.list_eligible(
        tenant_id=draft.tenant_id,
        app_id=draft.app_id,
    )

    return any(
        existing.artifact.capability_id
        == draft.artifact.capability_id
        and existing.version == draft.version
        for _, existing in eligible
    )


def main():
    registry = CapabilityRegistry()

    pending = find_pending_drafts(registry)

    if not pending:
        print("No pending capability drafts found.")
        return

    print(f"\nFound {len(pending)} draft(s) to review.")

    approved_count = 0

    for index, draft_path in enumerate(pending, start=1):
        try:
            draft = registry.load(draft_path)
        except Exception as exc:
            print(f"[WARNING] Could not load {draft_path}: {exc}")
            continue

        # Avoid repeatedly presenting older drafts of a version
        # that has already been approved.
        if already_approved(registry, draft):
            print(
                f"\nSkipping {draft.artifact.capability_id} "
                f"v{draft.version}: this version is already approved."
            )
            continue

        print("\n" + "=" * 60)
        print(f"CAPABILITY REVIEW {index}/{len(pending)}")
        print("=" * 60)

        print(f"Draft file: {draft_path}")
        print(f"Tenant: {draft.tenant_id}")
        print(f"Application: {draft.app_id}")
        print(f"Capability: {draft.artifact.capability_id}")
        print(f"Version: {draft.version}")

        # Show the complete saved record, including actions,
        # checkpoints, outputs, and business-outcome rules.
        print("\n========== CAPABILITY FOR REVIEW ==========")
        print(draft.model_dump_json(indent=2))

        print("\nOptions:")
        print("  A - Approve this capability")
        print("  S - Skip; leave it pending")
        print("  Q - Quit the review queue")

        while True:
            decision = input(
                "\nYour decision [A/S/Q]: "
            ).strip().upper()

            if decision in {"A", "S", "Q"}:
                break

            print("Please enter A, S, or Q.")

        if decision == "Q":
            print("\nReview stopped.")
            break

        if decision == "S":
            print("Draft left pending.")
            continue

        # Approval is performed only after an explicit decision.
        try:
            approved_path = registry.approve_draft(draft_path)
        except (ValueError, FileExistsError) as exc:
            print(f"[APPROVAL FAILED] {exc}")
            continue

        approved_count += 1
        print(f"\n[APPROVED] Saved to: {approved_path}")

    print(
        f"\nReview session complete. "
        f"Approved {approved_count} capability version(s)."
    )


if __name__ == "__main__":
    main()