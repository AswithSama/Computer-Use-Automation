"""Fails if any two top-level packages under app/agent import each other."""
import ast
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve()
while ROOT.name != "app":          # walk up to the app/ folder
    ROOT = ROOT.parent
AGENT = ROOT / "agent"
PREFIX = "app.agent."


def _package_edges():
    edges = defaultdict(set)
    for path in AGENT.rglob("*.py"):
        rel = path.relative_to(AGENT)
        if len(rel.parts) == 1 or rel.parts[0] in {"test", "__pycache__"}:
            continue                # main.py / tests may import anything
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.ImportFrom) and (node.module or "").startswith(PREFIX):
                dst = node.module[len(PREFIX):].split(".")[0]
                if dst != rel.parts[0]:
                    edges[rel.parts[0]].add(dst)
    return edges


def test_no_package_cycles():
    edges = _package_edges()
    cycles = sorted({tuple(sorted((a, b))) for a in edges for b in edges[a]
                     if a in edges.get(b, ())})
    assert not cycles, f"circular package dependencies: {cycles}"


def test_schemas_is_a_leaf():
    assert not _package_edges().get("schemas"), "schemas must not import sibling packages"