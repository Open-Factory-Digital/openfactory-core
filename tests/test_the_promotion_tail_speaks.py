"""The post-merge tail announces like every other stall (C-41, #84).

`workflow.py`'s `break` ends the loop that contains the park/announce block, and everything after
it returned raw:

    staging failure            `return staging`
    prod-approval expiry       `RunResult(ON_HOLD, "prod approval window elapsed")`
    release result             `return await execute_activity(release_prod, ...)`

No `_coord_say`, no `mark_needs_action`, no diagnosis. So a production approval nobody answered
within `approval_deadline_days` ended with the workflow COMPLETED, the board card still reading
"In review", and not one message sent — surfacing only if a human opened `/api/inbox` unprompted.

That is a literal silent forever-wait on the one gate that puts software in front of the client's
users: the exact failure the platform's headline invariant names.
"""

from __future__ import annotations

import ast
import inspect

from openfactory.runtime.temporal import workflow as wf


def _promotion_source() -> str:
    """The tail, as the workflow actually defines it."""
    return inspect.getsource(wf.PromotionWorkflow if hasattr(wf, "PromotionWorkflow")
                             else wf.JobWorkflow)


def _returns_in(src: str) -> list[ast.Return]:
    return [n for n in ast.walk(ast.parse(src.lstrip())) if isinstance(n, ast.Return)]


#: HOW EACH EXIT IS IDENTIFIED, since #160 moved the sentences into `techlead/voice.NARRATION`.
#: The key IS the identity — the sentence is prose, and prose that a guard matches on is prose
#: nobody can translate without breaking the guard, which is how this file would have blocked the
#: very card it now cooperates with.
TAIL_KEYS = ("stage.unverified", "prod.window-elapsed", "prod.released", "prod.failed")


def test_every_tail_exit_is_announced():
    """Each of the three exits must have a `_coord_say` before it. AST rather than substring: the
    docstrings in this file name the three paths while explaining why they were silent."""
    src = _promotion_source()
    for key in TAIL_KEYS:
        assert f'"{key}"' in src, f"the {key!r} exit says nothing"


def test_and_every_key_it_announces_with_EXISTS():
    """`say` returns the key itself for one it does not know — deliberately, so a channel never
    goes silent — which means a typo here ships as `prod.window-elapsed` in a client's Slack and
    every guard above still passes."""
    from openfactory.techlead import voice

    for key in TAIL_KEYS:
        assert key in voice.NARRATION, f"{key} is announced and has no entry"
        assert set(voice.NARRATION[key]) >= {"en", "pt-BR"}, f"{key} is not translated"


def test_the_announcements_are_needs_action_where_a_human_must_act():
    """A failed staging and an elapsed window need somebody; a successful release is news. The
    level is what decides whether the panel raises it — the wrong one is a message nobody sees."""
    src = _promotion_source()
    assert src.count('"needs_action")') >= 3


def test_the_release_outcome_is_announced_on_FAILURE_too():
    """A production release that succeeded and one that failed were equally silent, and the second
    is the one somebody needs to hear."""
    src = _promotion_source()
    assert '"prod.failed"' in src


def test_the_tail_is_behind_a_SINGLE_patch_marker():
    """TMPRL1100: adding commands to a workflow with jobs in flight breaks replay. One marker,
    used at each new call site, is what lets an in-flight job skip all three consistently — three
    different markers would let it skip one and emit another."""
    src = _promotion_source()
    markers = {m for m in ast.walk(ast.parse(src.lstrip()))
               if isinstance(m, ast.Constant) and isinstance(m.value, str)
               and "promotion-tail" in m.value}
    assert {m.value for m in markers} == {"promotion-tail-speaks"}


def test_every_new_say_is_INSIDE_the_patched_block():
    """A `_coord_say` outside the patch emits during the replay of an in-flight job and diverges
    (TMPRL1100) — a failure this codebase has already paid for once.

    ENCLOSURE, not order. An earlier version of this test asked whether the marker appeared
    anywhere ABOVE the call, which the first block's marker satisfies for all three: removing the
    guard from the second say left it green. A guard that cannot fail proves nothing, so this
    walks the tree and asks which `if` each call actually sits in."""
    tree = ast.parse(_promotion_source().lstrip())

    guarded, bare = 0, []
    for node in ast.walk(tree):
        if not isinstance(node, ast.If):
            continue
        test_src = ast.unparse(node.test)
        if "patched" not in test_src or "promotion-tail" not in test_src:
            continue
        for inner in ast.walk(node):
            if (isinstance(inner, ast.Call)
                    and getattr(inner.func, "attr", "") == "_coord_say"):
                guarded += 1

    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and getattr(node.func, "attr", "") == "_coord_say"):
            continue
        text = ast.unparse(node)
        if any(f"'{k}'" in text for k in TAIL_KEYS):
            bare.append(text[:60])

    assert len(bare) == 3, f"expected the three tail announcements, found {len(bare)}"
    assert guarded >= 3, (
        f"only {guarded} of the tail's announcements sit inside a `workflow.patched` block — one "
        f"outside it diverges on replay for every job already in flight"
    )
