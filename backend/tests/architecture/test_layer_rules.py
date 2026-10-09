"""Architecture guard: packages may only import from the layers allowed below.

This is the executable form of the dependency rule in docs/architecture.md.
If you add a cross-package import and this test fails, either the import is
wrong, or the rule needs a deliberate change plus a new ADR in docs/adr/.
"""

import ast
from pathlib import Path

SRC = Path(__file__).resolve().parents[2] / "src" / "nexa"

# package -> packages it is allowed to import (besides itself)
ALLOWED: dict[str, set[str]] = {
    "domain": set(),
    "config": {"domain"},
    "security": {"domain", "config"},
    "audit": {"domain", "config"},
    "bank_sim": {"domain", "config"},
    "llm": {"domain", "config"},
    "rag": {"domain", "config", "llm"},
    "tools": {"domain", "config", "security", "audit", "bank_sim", "rag"},
    "decision": {"domain", "config", "llm"},
    "approvals": {"domain", "config", "security", "audit", "tools"},
    "agents": {"domain", "config", "llm", "rag", "tools", "decision"},
    "orchestration": {
        "domain",
        "config",
        "security",
        "audit",
        "tools",
        "decision",
        "approvals",
        "agents",
    },  # fmt: skip
    "api": {
        "domain",
        "config",
        "security",
        "audit",
        "bank_sim",
        "llm",
        "rag",
        "tools",
        "decision",
        "approvals",
        "agents",
        "orchestration",
    },  # fmt: skip
}


def _imported_nexa_packages(path: Path, own_package: str) -> set[str]:
    """Return the top-level nexa packages that `path` imports."""
    found: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            for alias in node.names:
                parts = alias.name.split(".")
                if parts[0] == "nexa" and len(parts) > 1:
                    found.add(parts[1])
        elif isinstance(node, ast.ImportFrom):
            if node.level == 0 and node.module:
                parts = node.module.split(".")
                if parts[0] == "nexa" and len(parts) > 1:
                    found.add(parts[1])
                elif parts == ["nexa"]:
                    found.update(a.name for a in node.names)
            elif node.level >= 2:  # `from ..other import x` escapes our own package
                parts = (node.module or "").split(".")
                if parts[0]:
                    found.add(parts[0])
    found.discard(own_package)
    return found


def test_every_package_has_a_rule() -> None:
    packages = {p.name for p in SRC.iterdir() if p.is_dir() and (p / "__init__.py").exists()}
    assert packages == set(ALLOWED), f"packages without a rule: {packages ^ set(ALLOWED)}"


def test_imports_respect_layers() -> None:
    violations: list[str] = []
    for package, allowed in ALLOWED.items():
        for file in (SRC / package).rglob("*.py"):
            illegal = _imported_nexa_packages(file, package) - allowed
            if illegal:
                violations.append(f"{file.relative_to(SRC)} imports {sorted(illegal)}")
    assert not violations, "Layer violations:\n" + "\n".join(violations)


def test_agents_never_touch_the_bank_directly() -> None:
    """Agents reach the bank only through tools (PRD principle 3)."""
    assert "bank_sim" not in ALLOWED["agents"]
    assert "bank_sim" not in ALLOWED["decision"]
