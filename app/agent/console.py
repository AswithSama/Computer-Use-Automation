"""Small dependency-free helpers for evaluator-friendly terminal output."""

WIDTH = 58


def section(title: str) -> None:
    label = f" {title.strip().upper()} "
    remaining = max(WIDTH - len(label), 2)
    left = remaining // 2
    right = remaining - left

    print()
    print("─" * left + label + "─" * right)


def field(label: str, value: object) -> None:
    print(f"{label:<13}{value}")


def success(message: str) -> None:
    print(f"✓ {message}")


def step(number: int, action: str, target: str = "") -> None:
    target_text = target.strip()
    action_text = action.upper()
    print(f"  Step {number:02d}   {action_text:<7} {target_text:<26} ✓")
