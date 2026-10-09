"""Keeps the machine-readable project memory (docs/context/graph.json) honest.

Other agents rely on that graph to understand the project. These tests fail
if it drifts from the repository, so it cannot silently go stale.
"""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
GRAPH = ROOT / "docs" / "context" / "graph.json"
SRC = ROOT / "backend" / "src" / "nexa"
STATUSES = {"planned", "in_progress", "done"}


def _load() -> dict[str, list[dict[str, str]]]:
    data: dict[str, list[dict[str, str]]] = json.loads(GRAPH.read_text(encoding="utf-8"))
    return data


def test_node_ids_unique_and_statuses_valid() -> None:
    nodes = _load()["nodes"]
    ids = [n["id"] for n in nodes]
    assert len(ids) == len(set(ids)), "duplicate node ids"
    for n in nodes:
        assert n["status"] in STATUSES, f"{n['id']} has invalid status {n['status']}"


def test_edges_reference_existing_nodes() -> None:
    data = _load()
    ids = {n["id"] for n in data["nodes"]}
    for e in data["edges"]:
        assert e["from"] in ids and e["to"] in ids, f"dangling edge {e}"


def test_paths_exist() -> None:
    for n in _load()["nodes"]:
        path = n.get("path")
        if path:
            assert (ROOT / path).exists(), f"{n['id']} points to missing path {path}"


def test_every_package_is_in_the_graph() -> None:
    in_graph = {n["id"] for n in _load()["nodes"] if n["type"] == "module"}
    on_disk = {f"module:{p.name}" for p in SRC.iterdir() if p.is_dir() and p.name != "__pycache__"}
    assert on_disk == in_graph, f"graph out of sync with src: {on_disk ^ in_graph}"
