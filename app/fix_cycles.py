#!/usr/bin/env python3
"""
Break the circular package dependencies in app/agent.

Run from the directory that CONTAINS `app/`:

    python fix_cycles.py            # dry run: prints what it would do
    python fix_cycles.py --apply    # actually does it

What it does
------------
1. Creates a leaf package `app/agent/schemas/` (types only, imports nothing
   from sibling packages) and moves the shared models into it.
2. Extracts the BusinessOutcomeRule dataclass out of replay/business_outcomes.py
   (data goes to schemas; the detector logic stays in replay).
3. Moves capability/outputs/* and capability/output_locator.py into
   discovery/output_binding/, because discovery is their only real consumer.
4. Rewrites every `app.agent....` import to the new locations.
5. Verifies the result has no package-level cycles.

Uses `git mv` when inside a git repo so history is preserved.
"""
import ast
import re
import shutil
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

APPLY = "--apply" in sys.argv
ROOT = Path("app/agent")
A = "app.agent"

# (old file, new file)
FILE_MOVES = [
    ("discovery/models.py",              "schemas/discovery.py"),
    ("recording/models.py",              "schemas/recording.py"),
    ("capability/artifact_models.py",    "schemas/capability.py"),
    ("capability/output_locator.py",     "discovery/output_binding/output_locator.py"),
    ("capability/outputs/output_grounder.py",         "discovery/output_binding/output_grounder.py"),
    ("capability/outputs/output_binding_llm.py",      "discovery/output_binding/output_binding_llm.py"),
    ("capability/outputs/output_binding_verifier.py", "discovery/output_binding/output_binding_verifier.py"),
]

# old module path -> new module path (applied to every .py file)
MODULE_REWRITES = {
    f"{A}.discovery.models":                          f"{A}.schemas.discovery",
    f"{A}.recording.models":                          f"{A}.schemas.recording",
    f"{A}.capability.artifact_models":                f"{A}.schemas.capability",
    f"{A}.capability.output_locator":                 f"{A}.discovery.output_binding.output_locator",
    f"{A}.capability.outputs.output_grounder":        f"{A}.discovery.output_binding.output_grounder",
    f"{A}.capability.outputs.output_binding_llm":     f"{A}.discovery.output_binding.output_binding_llm",
    f"{A}.capability.outputs.output_binding_verifier": f"{A}.discovery.output_binding.output_binding_verifier",
}

NEW_PACKAGES = ["schemas", "discovery", "discovery/output_binding", "capability/inputs"]


def say(msg):
    print(("" if APPLY else "[dry-run] ") + msg)


def in_git():
    return subprocess.run(
        ["git", "rev-parse", "--is-inside-work-tree"],
        capture_output=True,
    ).returncode == 0


def move(src: Path, dst: Path):
    say(f"move  {src}  ->  {dst}")
    if not APPLY:
        return
    dst.parent.mkdir(parents=True, exist_ok=True)
    if in_git() and subprocess.run(["git", "mv", str(src), str(dst)],
                                   capture_output=True).returncode == 0:
        return
    shutil.move(str(src), str(dst))


def split_business_outcome_rule():
    """Cut the dataclass out of replay/business_outcomes.py into schemas/outcomes.py."""
    path = ROOT / "replay/business_outcomes.py"
    text = path.read_text()
    m = re.search(r"(@dataclass\(frozen=True\)\nclass BusinessOutcomeRule:.*?)(?=\n\nclass )",
                  text, re.S)
    if not m:
        sys.exit("Could not locate BusinessOutcomeRule in replay/business_outcomes.py")
    rule_src = m.group(1)

    say("extract BusinessOutcomeRule -> schemas/outcomes.py "
        "(replay/business_outcomes.py re-imports it)")
    if not APPLY:
        return
    out = ROOT / "schemas/outcomes.py"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("from dataclasses import dataclass\nfrom typing import Literal\n\n\n"
                   + rule_src + "\n")
    new_text = text.replace(rule_src,
                            f"# Data lives in schemas so registry/capability can use it\n"
                            f"# without importing the replay package.\n"
                            f"from {A}.schemas.outcomes import BusinessOutcomeRule  # noqa: F401")
    path.write_text(new_text)


def rewrite_imports():
    files = [p for p in Path("app").rglob("*.py")]
    for p in files:
        text = orig = p.read_text()
        # longest keys first so nothing partially matches
        for old in sorted(MODULE_REWRITES, key=len, reverse=True):
            text = re.sub(rf"\b{re.escape(old)}\b", MODULE_REWRITES[old], text)

        # The two sites that must stop reaching into `replay` for the data class.
        if p.name in ("registry.py", "main.py"):
            text = text.replace(
                f"from {A}.replay.business_outcomes import BusinessOutcomeRule",
                f"from {A}.schemas.outcomes import BusinessOutcomeRule",
            )
        # replay_engine needs both names; keep detector from replay, rule from schemas.
        if p.name == "replay_engine.py":
            text = re.sub(
                rf"from {A}\.replay\.business_outcomes import \(\s*BusinessOutcomeDetector,\s*BusinessOutcomeRule,\s*\)",
                f"from {A}.replay.business_outcomes import BusinessOutcomeDetector\n"
                f"from {A}.schemas.outcomes import BusinessOutcomeRule",
                text,
            )
        if text != orig:
            say(f"rewrite imports in {p}")
            if APPLY:
                p.write_text(text)


def add_init_files():
    for pkg in NEW_PACKAGES:
        init = ROOT / pkg / "__init__.py"
        if not init.exists():
            say(f"create {init}")
            if APPLY:
                init.parent.mkdir(parents=True, exist_ok=True)
                init.touch()


def remove_empty_dirs():
    for d in [ROOT / "capability/outputs"]:
        if d.exists():
            leftovers = [f for f in d.rglob("*") if f.is_file() and "__pycache__" not in f.parts
                         and f.name != "__init__.py"]
            if not leftovers:
                say(f"remove empty {d}")
                if APPLY:
                    shutil.rmtree(d)


# ---------------------------------------------------------------- verification
def package_of(module: str):
    parts = module.split(".")
    return parts[2] if len(parts) > 2 else None


def find_cycles():
    edges = defaultdict(set)
    for p in ROOT.rglob("*.py"):
        if "__pycache__" in p.parts or p.parts[2] == "test":
            continue
        rel = p.relative_to(ROOT)
        if len(rel.parts) == 1:          # main.py etc: allowed to import anything
            continue
        src = rel.parts[0]
        for n in ast.walk(ast.parse(p.read_text())):
            if isinstance(n, ast.ImportFrom) and n.module and n.module.startswith(A + "."):
                dst = package_of(n.module)
                if dst and dst != src:
                    edges[src].add(dst)
    return edges, [(a, b) for a in edges for b in edges[a]
                   if a < b and a in edges.get(b, ())]


def report():
    edges, cycles = find_cycles()
    print("\nPackage dependency graph:")
    for a in sorted(edges):
        print(f"  {a:14} -> {', '.join(sorted(edges[a]))}")
    if cycles:
        print("\nSTILL CYCLIC:", cycles)
        return False
    print("\nNo package-level cycles.")
    return True


if __name__ == "__main__":
    if not ROOT.exists():
        sys.exit("Run this from the directory that contains app/")

    split_business_outcome_rule()      # before rewrites so the regex sees original text
    for old, new in FILE_MOVES:
        move(ROOT / old, ROOT / new)
    add_init_files()
    rewrite_imports()
    remove_empty_dirs()

    if APPLY:
        ok = report()
        sys.exit(0 if ok else 1)
    print("\nRe-run with --apply to perform these changes.")