"""Language-independent triage decision engine.

The tree (data/triage_tree.json) knows nothing about languages. Every node id
doubles as a prompt key that each language pack must supply, so adding a
language never touches this code.
"""
from __future__ import annotations

import json
from pathlib import Path

LEVELS = ("emergency", "today", "within_3_days", "home")  # most to least urgent
LEVEL_RANK = {level: i for i, level in enumerate(LEVELS)}
DATA_DIR = Path(__file__).resolve().parent.parent / "data"
MAX_QUESTIONS = 8  # callers on feature phones lose patience after this


class TreeError(ValueError):
    """Raised for malformed trees or impossible transitions."""


class Tree:
    def __init__(self, data: dict):
        self.data = data
        self.start = data.get("start", "")
        self.nodes = data.get("nodes", {})

    @classmethod
    def load(cls, path=None) -> "Tree":
        path = Path(path) if path else DATA_DIR / "triage_tree.json"
        with open(path, encoding="utf-8") as fh:
            return cls(json.load(fh))

    # ---- navigation -------------------------------------------------------
    def node(self, node_id: str) -> dict:
        try:
            return self.nodes[node_id]
        except KeyError:
            raise TreeError(f"unknown node {node_id!r}") from None

    def is_outcome(self, node_id: str) -> bool:
        return self.node(node_id)["type"] == "outcome"

    def answers(self, node_id: str) -> tuple:
        node = self.node(node_id)
        if node["type"] == "yesno":
            return ("yes", "no")
        if node["type"] == "choice":
            return tuple(node["options"])
        return ()

    def next_node(self, node_id: str, answer: str) -> str:
        node = self.node(node_id)
        if node["type"] == "yesno" and answer in ("yes", "no"):
            return node[answer]
        if node["type"] == "choice" and answer in node["options"]:
            return node["options"][answer]
        raise TreeError(f"invalid answer {answer!r} for node {node_id!r}")

    def prompt_keys(self) -> set:
        """Every node id is a prompt key a language pack must provide."""
        return set(self.nodes)

    def iter_paths(self):
        """Yield (trail, outcome_id) for every route through the tree."""

        def walk(node_id, trail):
            if self.is_outcome(node_id):
                yield trail, node_id
                return
            for answer in self.answers(node_id):
                yield from walk(self.next_node(node_id, answer), trail + [(node_id, answer)])

        yield from walk(self.start, [])

    def max_questions(self) -> int:
        return max(len(trail) for trail, _ in self.iter_paths())

    def summarize(self, trail, outcome_id: str) -> dict:
        """Staff-facing summary: patient group plus the signs the caller reported."""
        group, reported = "", []
        for node_id, answer in trail:
            node = self.node(node_id)
            if node["type"] == "choice":
                group = node.get("labels", {}).get(answer, answer)
            elif answer == "yes":
                reported.append(node["label"])
        return {"level": self.node(outcome_id)["level"], "group": group, "reported": reported}

    # ---- validation -------------------------------------------------------
    def validate(self) -> list:
        """Return a list of problems; an empty list means the tree is sound."""
        if self.start not in self.nodes:
            return [f"start node {self.start!r} does not exist"]
        problems = []
        for nid, node in self.nodes.items():
            kind = node.get("type")
            if kind == "yesno":
                if not node.get("label"):
                    problems.append(f"{nid}: missing staff label")
                for branch in ("yes", "no"):
                    if node.get(branch) not in self.nodes:
                        problems.append(f"{nid}: '{branch}' points to unknown node {node.get(branch)!r}")
            elif kind == "choice":
                options = node.get("options") or {}
                if not options:
                    problems.append(f"{nid}: no options")
                for key, target in options.items():
                    if not (len(key) == 1 and key in "123456789"):
                        problems.append(f"{nid}: option key {key!r} must be a single digit 1-9")
                    if target not in self.nodes:
                        problems.append(f"{nid}: option {key!r} points to unknown node {target!r}")
                    if key not in node.get("labels", {}):
                        problems.append(f"{nid}: option {key!r} has no staff label")
            elif kind == "outcome":
                if node.get("level") not in LEVELS:
                    problems.append(f"{nid}: level must be one of {LEVELS}")
            else:
                problems.append(f"{nid}: unknown node type {kind!r}")
        if problems:
            return problems

        def visit(nid, stack):
            if nid in stack:
                problems.append(f"cycle through {nid!r}")
                return
            for answer in self.answers(nid):
                visit(self.next_node(nid, answer), stack | {nid})

        visit(self.start, frozenset())
        if problems:
            return problems

        paths = list(self.iter_paths())
        reached, levels = {self.start}, set()
        for trail, outcome in paths:
            reached.update(nid for nid, _ in trail)
            reached.add(outcome)
            levels.add(self.node(outcome)["level"])
        for nid in sorted(set(self.nodes) - reached):
            problems.append(f"{nid}: unreachable from start")
        for level in LEVELS:
            if level not in levels:
                problems.append(f"no path reaches level {level!r}")
        longest = max(len(trail) for trail, _ in paths)
        if longest > MAX_QUESTIONS:
            problems.append(f"longest path asks {longest} questions; limit is {MAX_QUESTIONS}")
        return problems
