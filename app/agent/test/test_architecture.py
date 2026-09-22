"""
Architecture guard for app/agent.

1. No two top-level packages may import each other (directly).
2. Each package may only import the packages listed in ALLOWED below.
   This encodes the layering:

       schemas                       (leaf: types only)
         ^
       llm, recording, validation, observability
         ^
       discovery      capability      registry      replay
         ^               ^              ^             ^
       handoff        (shared leaf: intervention contracts and policy)
         ^
       orchestration  (top layer: the only package that knows every stage)
         ^
       main.py         (entry point; may import anything)

If you add a dependency on purpose, update ALLOWED. The point of this test
is that a new cross-package import is a decision, not an accident.
"""
import ast
from collections import defaultdict
from pathlib import Path

PREFIX = "app.agent."

ALLOWED = {
    "schemas": set(),
    "handoff": set(),
    "observability": set(),
    "llm": {"schemas"},
    "recording": {"schemas"},
    "validation": {"schemas"},
    "capability": {"schemas"},
    "registry": {"schemas"},
    "replay": {"schemas","policy"},
    "discovery": {"llm", "policy","observability", "recording", "schemas", "validation", "handoff"},
    "orchestration": {
        "capability",
        "discovery",
        "handoff",
        "policy",
        "registry",
        "replay",
        "schemas",
        "recording"
    },
    "policy": {"schemas"},
}


def _agent_dir() -> Path:
    for parent in Path(__file__).resolve().parents:
        if (parent / "app" / "agent").is_dir():
            return parent / "app" / "agent"
    raise RuntimeError("could not locate app/agent")


def _package_edges():
    agent = _agent_dir()
    edges = defaultdict(set)
    for path in agent.rglob("*.py"):
        rel = path.relative_to(agent)
        if len(rel.parts) == 1 or rel.parts[0] in {"test", "tests", "__pycache__"}:
            continue                       # main.py and tests may import anything
        src = rel.parts[0]
        for node in ast.walk(ast.parse(path.read_text())):
            modules = []
            if isinstance(node, ast.ImportFrom) and node.module:
                modules.append(node.module)
            elif isinstance(node, ast.Import):
                modules.extend(alias.name for alias in node.names)
            for module in modules:
                if module.startswith(PREFIX):
                    dst = module[len(PREFIX):].split(".")[0]
                    if dst != src:
                        edges[src].add(dst)
    return edges


def test_no_package_cycles():
    edges = _package_edges()
    cycles = sorted({tuple(sorted((a, b))) for a in edges for b in edges[a]
                     if a in edges.get(b, ())})
    assert not cycles, f"circular package dependencies: {cycles}"


def test_layering():
    edges = _package_edges()
    unknown = sorted(set(edges) - set(ALLOWED))
    assert not unknown, f"new package(s) {unknown}: add them to ALLOWED"

    violations = [
        f"{src} -> {dst}"
        for src, dsts in sorted(edges.items())
        for dst in sorted(dsts - ALLOWED[src])
    ]
    assert not violations, (
        "disallowed cross-package imports (fix the import, or update ALLOWED "
        "if this dependency is intentional): " + ", ".join(violations)
    )


def test_only_main_imports_orchestration():
    importers = sorted(src for src, dsts in _package_edges().items()
                       if "orchestration" in dsts)
    assert not importers, f"only main.py may import orchestration, found: {importers}"
