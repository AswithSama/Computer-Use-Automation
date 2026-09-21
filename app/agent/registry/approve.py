
from app.agent.registry.registry import CapabilityRegistry


def main():
    registry = CapabilityRegistry()

    pending = registry.list_drafts()

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

        if registry.is_approved(draft):
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