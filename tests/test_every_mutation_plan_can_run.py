"""Every mutation plan in `tools/mutations/` can run — or says which plan carries its claims now.

THE NUMBER THIS HOLDS AT ZERO WAS FORTY-SIX. The review of #78 (2026-09-07) ran the runner's own
anchor rule over the whole directory: 46 of the 154 plans were refused on `main` `1026a76` — 136
anchors pointing at lines a refactor had moved or renamed, and two `TEST` files that no longer
existed — and each one was a set of claims nobody had verified since the refactor. Four had been killed by one PR (#76)
and reported green beside it, because the PR ran only the plans it added, never the pre-existing
plans its refactors touched. A plan that cannot run looks exactly like a plan that ran.

`tests/test_the_mutation_runner_is_not_decoration.py` proves the RUNNER refuses a twice-matching
anchor and a missing path — on a synthetic arena. This points the same rule at the real plans:

  · every row's anchor matches its file exactly once (the runner's `check_anchors` rule);
  · every plan's `TEST`, and every row's own target, is a file in the tree;
  · a plan whose claims moved elsewhere declares `SUPERSEDED_BY = "<plan>.py"` — the runner
    then says so instead of refusing, and this guard skips it — and the plan it names exists,
    is not itself superseded (a chain would hide a dead end), AND NAMES IT BACK in its own
    `SUPERSEDES`. The second end is what turns the declaration into a check: a superseded plan is
    skipped by both rules above, so on its own the word is a silencer — the review of #84 planted
    `SUPERSEDED_BY` naming an unrelated live plan over a rotten anchor and a missing `TEST`, and
    this file passed 5/5. Two ends is a pairing written in two diffs a reviewer reads.

Rows on a path the public cut removes (docs/STATUS.md's excluded-paths table) are not rot: a
plan proves the tree it was written in, and the runner refuses those rows by name. Skipped here
for the same reason.
"""

from __future__ import annotations

import runpy
from pathlib import Path

from tests.test_the_public_cut_is_written_down import _excluded, _is_excluded

ROOT = Path(__file__).resolve().parents[1]
PLANS = sorted((ROOT / "tools" / "mutations").glob("*.py"))


def _plans() -> dict[str, dict]:
    return {plan.name: runpy.run_path(str(plan)) for plan in PLANS}


def test_there_are_plans_to_hold_to_this():
    assert len(PLANS) > 100, "the directory the runner reads is where the plans live"


def test_every_anchor_matches_its_file_exactly_once():
    """The runner's own rule (`mutate.check_anchors`): zero matches means the plan rotted, two
    means `replace(old, new, 1)` would cut a site nobody chose. Either way the plan is refused
    whole, and every claim in it goes unverified until somebody notices."""
    excluded = _excluded()
    problems: list[str] = []
    for name, ns in _plans().items():
        if ns.get("SUPERSEDED_BY"):
            continue
        for row in ns.get("MUTATIONS") or []:
            label, rel, old = row[0], row[1], row[2]
            if _is_excluded(rel, excluded):
                continue
            path = ROOT / rel
            if not path.exists():
                problems.append(f"{name}: [{label[:60]}] {rel} is not in the tree and not in "
                                f"docs/STATUS.md's excluded-paths table")
                continue
            if old and (n := path.read_text().count(old)) != 1:
                problems.append(f"{name}: [{label[:60]}] anchor matches {n}x in {rel}")
    assert not problems, (
        f"{len(problems)} anchor(s) the runner would refuse — re-pin each to the line it means, "
        f"retire the row if the code it cut is gone, or declare the plan SUPERSEDED_BY the plan "
        f"that carries its claims:\n  " + "\n  ".join(problems))


def _file_of(target: str) -> str:
    """The runner hands its target straight to pytest, which takes a node id as readily as a
    path (`tests/x.py::test_y` runs the one test). Only the part before `::` is a file."""
    return target.split("::")[0]


def test_every_test_a_plan_names_is_in_the_tree():
    """A plan's `TEST`, and a row's own target (its fifth element), are what the runner hands
    pytest for a baseline; a name that left the tree is a plan that can never be green.

    A row on an excluded path is skipped here for the reason it is skipped above: the code it
    cuts is not in this tree, and neither is the test that covers it — `openfactory-aws` keeps
    `tests/test_fargate_launcher.py` and `test_dynamo_metrics_sink.py`, `openfactory-slack` keeps
    its own `tests/`. The plan still names them, because the package they belong to still runs."""
    excluded = _excluded()
    problems: list[str] = []
    for name, ns in _plans().items():
        if ns.get("SUPERSEDED_BY"):
            continue
        test = ns.get("TEST") or ""
        if not test or not (ROOT / _file_of(test)).exists():
            problems.append(f"{name}: TEST {test!r} is not in the tree")
        for row in ns.get("MUTATIONS") or []:
            if _is_excluded(row[1], excluded):
                continue
            own = row[4] if len(row) > 4 and row[4] else ""
            if own and not (ROOT / _file_of(own)).exists():
                problems.append(f"{name}: [{row[0][:60]}] targets {own!r}, not in the tree")
    assert not problems, "\n  ".join(["", *problems])


def test_a_row_proved_only_elsewhere_names_a_row_of_its_own_and_an_excluded_path():
    """`PROVED_ONLY_WHERE` turns a row off in the tree that cannot prove it, so both halves of it
    are held here. The label must be one of the plan's own rows — a marker that matches nothing
    is a row somebody believes is covered and is not, and it would be silent. And the path must
    be one `docs/STATUS.md`'s excluded-paths table names, because that table is the one place the
    map of what leaves and with which package is written down: a marker free to name any path
    could switch a row off in every tree, which is the decoration this file exists to prevent."""
    excluded = _excluded()
    problems: list[str] = []
    for name, ns in _plans().items():
        labels = {row[0] for row in ns.get("MUTATIONS") or []}
        for label, needs in (ns.get("PROVED_ONLY_WHERE") or {}).items():
            if label not in labels:
                problems.append(f"{name}: PROVED_ONLY_WHERE names [{label[:60]}], which is not a "
                                f"row of this plan")
            if not _is_excluded(needs.rstrip("/"), excluded):
                problems.append(f"{name}: [{label[:50]}] needs {needs!r}, which docs/STATUS.md's "
                                f"excluded-paths table does not name")
    assert not problems, "\n  ".join(["", *problems])


def supersession_problems(plans: dict[str, dict]) -> list[str]:
    """Every supersession written on both ends, both ends live. `plans` is name → namespace, so
    the rule can be fed a planted directory as readily as the real one."""
    problems: list[str] = []
    for name, ns in plans.items():
        if by := ns.get("SUPERSEDED_BY"):
            if by not in plans:
                problems.append(f"{name} is superseded by {by!r}, which is not a plan here")
            elif plans[by].get("SUPERSEDED_BY"):
                problems.append(f"{name} is superseded by {by}, which is itself superseded by "
                                f"{plans[by]['SUPERSEDED_BY']} — point at the live one")
            elif name not in (plans[by].get("SUPERSEDES") or ()):
                problems.append(f"{name} says it is superseded by {by}, and {by} does not name "
                                f"it back in SUPERSEDES — one end is the author's word, not a "
                                f"check; add {name!r} to the successor's SUPERSEDES")
        for named in ns.get("SUPERSEDES") or ():
            if named not in plans:
                problems.append(f"{name} claims to supersede {named!r}, which is not a plan here")
            elif plans[named].get("SUPERSEDED_BY") != name:
                problems.append(f"{name} claims to supersede {named}, which does not declare "
                                f"SUPERSEDED_BY = {name!r} — the other end is missing")
    return problems


def test_every_supersession_is_written_on_both_ends_and_both_are_live():
    """The declaration is only worth having if it points at a plan that runs and that plan says
    so too: a successor that is gone, or itself superseded, is the dead end the declaration
    exists to name; a successor that does not name the plan back is the silencer #84's review
    found."""
    problems = supersession_problems(_plans())
    assert not problems, "\n  ".join(["", *problems])


def test_the_pairing_rule_can_SEE_each_way_a_supersession_is_written_on_one_end():
    """Verify the verifier, on a planted directory: the pairing as it is meant, then each of the
    four ways one end can be missing, each named in the sentence that reports it."""
    assert supersession_problems({
        "old.py": {"SUPERSEDED_BY": "new.py"},
        "new.py": {"SUPERSEDES": ("old.py",)},
    }) == []

    one_ended = supersession_problems({"old.py": {"SUPERSEDED_BY": "new.py"}, "new.py": {}})
    assert len(one_ended) == 1 and "does not name it back" in one_ended[0], one_ended

    claimed = supersession_problems({"new.py": {"SUPERSEDES": ("old.py",)}, "old.py": {}})
    assert len(claimed) == 1 and "does not declare SUPERSEDED_BY" in claimed[0], claimed

    gone = supersession_problems({"new.py": {"SUPERSEDES": ("gone.py",)}})
    assert len(gone) == 1 and "not a plan here" in gone[0], gone

    dead_end = supersession_problems({
        "old.py": {"SUPERSEDED_BY": "mid.py"},
        "mid.py": {"SUPERSEDED_BY": "new.py", "SUPERSEDES": ("old.py",)},
        "new.py": {"SUPERSEDES": ("mid.py",)},
    })
    assert len(dead_end) == 1 and "point at the live one" in dead_end[0], dead_end
