import pytest

from voicetriage.engine import LEVELS, Tree, TreeError


@pytest.fixture(scope="module")
def tree():
    return Tree.load()


def test_shipped_tree_is_valid(tree):
    assert tree.validate() == []


def test_voice_friendly_length(tree):
    assert tree.max_questions() <= 8


def test_every_urgency_level_is_reachable(tree):
    reached = {tree.node(out)["level"] for _, out in tree.iter_paths()}
    assert reached == set(LEVELS)


def test_a_yes_answer_never_ends_in_home_care(tree):
    """Safety invariant: reporting any sign must always send the caller to a facility."""
    for trail, outcome in tree.iter_paths():
        reported_yes = any(ans == "yes" for _, ans in trail)
        if reported_yes:
            assert tree.node(outcome)["level"] != "home", trail


def test_first_danger_signs_are_emergencies(tree):
    for first in ("c_drink", "p_bleeding", "a_unconscious"):
        assert tree.node(first)["yes"] == "outcome_emergency"


def test_summarize_lists_only_yes_answers(tree):
    trail = [("who", "1"), ("c_drink", "no"), ("c_fits", "yes")]
    summary = tree.summarize(trail, "outcome_emergency")
    assert summary == {
        "level": "emergency",
        "group": "Child under 5 years",
        "reported": ["Convulsions, or very sleepy / floppy / hard to wake"],
    }


def test_invalid_answer_is_rejected(tree):
    with pytest.raises(TreeError):
        tree.next_node("c_drink", "maybe")
    with pytest.raises(TreeError):
        tree.next_node("who", "9")


def test_validate_catches_broken_trees():
    broken_ref = Tree({"start": "a", "nodes": {"a": {"type": "yesno", "label": "x", "yes": "nowhere", "no": "a"}}})
    assert any("unknown node" in p for p in broken_ref.validate())

    cycle = Tree({"start": "a", "nodes": {
        "a": {"type": "yesno", "label": "x", "yes": "a", "no": "o"},
        "o": {"type": "outcome", "level": "home"},
    }})
    assert any("cycle" in p for p in cycle.validate())

    orphan = Tree({"start": "a", "nodes": {
        "a": {"type": "yesno", "label": "x", "yes": "e", "no": "h"},
        "e": {"type": "outcome", "level": "emergency"},
        "h": {"type": "outcome", "level": "home"},
        "lost": {"type": "outcome", "level": "today"},
    }})
    problems = orphan.validate()
    assert any("unreachable" in p for p in problems)
    assert any("within_3_days" in p for p in problems)
