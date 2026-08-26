"""Nothing in a process that never restarts may grow without a stated bound.

TWO REAL LEAKS MOTIVATED THIS, both found by reading rather than by any test:

  * `ProductModule._workspace` called `tempfile.mkdtemp()` while the module was constructed fresh
    for every Slack message — one directory per message, removed by nothing. 33 accumulated in one
    afternoon of local testing.
  * `_do_coordinate` did the same per PARKED DECISION, in the Temporal worker, which never restarts.

And two caps that existed in one file and not its sibling: `product_channel._PENDING` was capped at
200 with a comment explaining exactly why; `bot._PENDING`, written for the same purpose in the same
process, had no cap. The panel memoised one entry per terminal job and removed none.

None of that is a bug a behaviour test can catch — the code is correct on every single call. It
fails only in aggregate, on a timescale no test runs for. So the guard is STRUCTURAL: every site
that allocates or memoises must have decided, in writing, what bounds it. A new site fails this
test until somebody decides. That is the point — the decision is cheap, and discovering it from a
full disk is not.
"""

from __future__ import annotations

import ast
import importlib
import re
from pathlib import Path

import add_ons
import pytest

SDLC = Path(__file__).resolve().parent.parent / "openfactory"


def _modules() -> list[tuple[Path, ast.Module]]:
    out = []
    for path in sorted(SDLC.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        out.append((path, ast.parse(path.read_text(), filename=str(path))))
    return out


def _rel(path: Path) -> str:
    return str(path.relative_to(SDLC.parent))


# ── guard 1: temporary directories ─────────────────────────────────────────────────────────────
#: Sites where the directory outlives the call ON PURPOSE, with the reason. Everything else must
#: remove what it made, in the same function, on every exit path.
_LIVES_FOR_THE_PROCESS = {
    ("openfactory/runtime/temporal/worker.py", "main"):
        "holds the materialised GitHub App private key for the worker's whole life",
    ("openfactory/api/app.py", "<module>"): "same key, panel process",
    ("openfactory/runtime/slack/bot.py", "main"): "same key, bot process",
    ("openfactory/testing/local_flow.py", "_tiny_repo"): "a throwaway repo in a throwaway local run",
}

#: Ownership handed to the caller. The releaser is NAMED, because "it returns the path" is not
#: evidence — `ProductModule._workspace` returned its path too, and nothing ever released it.
_RELEASED_BY_CALLER = {
    ("openfactory/adapters/sandbox/container.py", "prepare"): "ContainerSandbox.cleanup()",
    ("openfactory/techlead/conversation.py", "clone_repo"):
        "conversation._answer()'s finally, via scratch.discard()",
    ("openfactory/techlead/diagnosis.py", "_checkout"):
        "diagnosis.diagnose()'s finally, via scratch.discard()",
    ("openfactory/util/scratch.py", "make"):
        "scratch.discard(), and the split IS the mechanism rather than a convenience: `make` "
        "stamps the directory with the prefix that `discard` requires before it will delete "
        "anything. Both halves are asserted, including that the two techlead call sites use "
        "`discard` and no bare rmtree, in "
        "tests/test_a_scratch_directory_is_the_only_thing_we_delete.py — which exists because on "
        "2026-08-21 the bare version ran `rmtree(\"/tmp\")` three times per suite run, silently on "
        "macOS and fatally on Linux, where it deleted pytest's own temp root and failed 898 tests.",
    ("openfactory/onboarding/propose_manifest.py", "clone_for_proposal"):
        "catalog._env_apply()'s finally — the clone must outlive the function that makes it "
        "(the caller writes the manifest into it, then commits and pushes), and every exit "
        "between the clone and the push is a refusal that would otherwise leak it. Same shape, "
        "same reason, as conversation.clone_repo and diagnosis._checkout above.",
    ("openfactory/product/workspace.py", "compose"):
        "module._workspace(), since 2026-08-01. Flagged 2026-07-29 as 'no production caller at "
        "all (only its own test)' — it was the right observation and the wrong conclusion: the "
        "mechanism was correct and simply unreached, while the conversational path had invented a "
        "third layout out of symlinks. It is called on every client message now, at a STABLE root "
        "(idempotent), so what bounds it is one directory per project rather than one per call.",
}

_RELEASES = {"rmtree", "cleanup", "TemporaryDirectory"}


def _enclosing(tree: ast.Module, node: ast.AST) -> str:
    """Innermost def containing `node`, or '<module>'."""
    best = "<module>"
    for fn in ast.walk(tree):
        if not isinstance(fn, ast.FunctionDef | ast.AsyncFunctionDef):
            continue
        if getattr(fn, "lineno", 0) <= node.lineno <= getattr(fn, "end_lineno", 0):
            best = fn.name
    return best


def _scope_body(tree: ast.Module, name: str) -> list[ast.AST]:
    if name == "<module>":
        return list(tree.body)
    for fn in ast.walk(tree):
        if isinstance(fn, ast.FunctionDef | ast.AsyncFunctionDef) and fn.name == name:
            return list(ast.walk(fn))
    return []


def test_every_temporary_directory_is_released_or_declared():
    offenders = []
    for path, tree in _modules():
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            fname = getattr(node.func, "attr", None) or getattr(node.func, "id", None)
            if fname != "mkdtemp":
                continue
            scope = _enclosing(tree, node)
            if (_rel(path), scope) in _LIVES_FOR_THE_PROCESS:
                continue
            if (_rel(path), scope) in _RELEASED_BY_CALLER:
                continue
            names = {getattr(n, "attr", None) or getattr(n, "id", None)
                     for n in _scope_body(tree, scope)}
            if names & _RELEASES:
                continue
            offenders.append(f"{_rel(path)}:{node.lineno} in {scope}()")

    assert not offenders, (
        "these make a temporary directory and never remove it:\n  " + "\n  ".join(offenders)
        + "\n\nEither remove it in the same function (`finally: shutil.rmtree(tmp, "
          "ignore_errors=True)`) or, if it must outlive the call, add it to "
          "_LIVES_FOR_THE_PROCESS in this file WITH the reason.")


def test_the_declared_exemptions_still_exist():
    """An exemption for a site that moved is a hole nobody can see. Sabotage-proofing the guard."""
    seen = set()
    for path, tree in _modules():
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and (
                    getattr(node.func, "attr", None) or getattr(node.func, "id", None)) == "mkdtemp":
                seen.add((_rel(path), _enclosing(tree, node)))
    stale = (set(_LIVES_FOR_THE_PROCESS) | set(_RELEASED_BY_CALLER)) - seen
    # an exemption for a site in a module that LEAVES the public tree (docs/STATUS.md) is not
    # stale where that module is absent — it is the add-on's, and this tree does not hold it
    stale = {site for site in stale
             if not (add_ons.package_for(site[0]) and not (SDLC.parent / site[0]).exists())}
    assert not stale, f"exemptions for sites that no longer allocate anything: {sorted(stale)}"


# ── guard 2: module-level mutable caches ───────────────────────────────────────────────────────
#: Every module-level dict that gets written by key, and what bounds it. A cache with no bound in
#: a process that never restarts is a slow leak; a cache bounded "by nature" must say by what.
_CACHES = {
    ("openfactory/runtime/repo_cache.py", "_locks"): "one lock per project — bounded by the registry",
    ("openfactory/runtime/slack/people.py", "_RESOLVED"): "one per GitHub login in the org",
    ("openfactory/product/board.py", "_SNAPSHOT"): "one per project — bounded by the registry",
    ("openfactory/runtime/temporal/view.py", "_state_cache"): "BoundedDict(2000)",
    ("openfactory/runtime/temporal/view.py", "_deploy_cache"): "BoundedDict(2000)",
    ("openfactory/runtime/slack/bot.py", "_PENDING"): "BoundedDict(200)",
    ("openfactory/runtime/slack/bot.py", "_ASKED"): "BoundedDict(200)",
    ("openfactory/product/staging.py", "_PENDING"): "_MAX_PENDING = 200, evicts oldest",
    ("openfactory/product/staging.py", "_EXPIRED_TOMBSTONES"):
        "_MAX_TOMBSTONES = 64, evicts oldest",
    ("openfactory/product/staging.py", "_ENTRY_MODELS"):
        "one per pydantic model class that can appear in a staged entry — a registry, not traffic",
    ("openfactory/adapters/agent/registry.py", "NATIVE_REVIEWERS"):
        "one per harness kind — bounded by the HARNESSES table",
    ("openfactory/ops/impediment.py", "_LAST"): "BoundedDict(256)",
    # MOVED WITH THE PROBE (#162). The panel spelled a GitHub board URL by hand, so it carried
    # GitHub's org-vs-user asymmetry and this cache; both now live in the adapter that knows which
    # vendor has one.
    ("openfactory/adapters/tracker/github_project.py", "_OWNER_KIND"):
        "one per board owner in the registry — the key is a project's board_owner, not traffic",
}


def _module_dicts(tree: ast.Module) -> dict[str, ast.AST]:
    out: dict[str, ast.AST] = {}
    for node in tree.body:
        target, value = None, None
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            target, value = node.target.id, node.value
        elif isinstance(node, ast.Assign) and len(node.targets) == 1 \
                and isinstance(node.targets[0], ast.Name):
            target, value = node.targets[0].id, node.value
        if not target or value is None:
            continue
        is_empty_dict = (isinstance(value, ast.Dict) and not value.keys) or (
            isinstance(value, ast.Call)
            and (getattr(value.func, "id", None) or getattr(value.func, "attr", None)) == "dict"
            and not value.args)
        is_bounded = (isinstance(value, ast.Call)
                      and (getattr(value.func, "id", None)
                           or getattr(value.func, "attr", None)) == "BoundedDict")
        if is_empty_dict or is_bounded:
            out[target] = node
    return out


def _written_names(tree: ast.Module) -> set[str]:
    """Every name a module grows through — not only `d[k] = v`. `_locks.setdefault(...)` and
    `d.update(...)` grow a dict without a single Subscript store, so the first version of this
    net registered such dicts as never-written and silently stopped covering them."""
    written: set[str] = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Subscript) and isinstance(n.value, ast.Name) \
                and isinstance(n.ctx, ast.Store):
            written.add(n.value.id)
        elif isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) \
                and isinstance(n.func.value, ast.Name) \
                and n.func.attr in {"setdefault", "update"}:
            written.add(n.func.value.id)
        elif isinstance(n, ast.AugAssign) and isinstance(n.target, ast.Name):
            written.add(n.target.id)
    return written


def test_every_module_level_cache_has_a_declared_bound():
    """A dict declared empty at module level and written by key IS a cache, whatever it is called.

    Constant lookup tables (`_ATTEMPTS`, `_STATE_KEYS`) are literals with contents and never
    written to — they do not match, which is why this guard is quiet about them.
    """
    offenders = []
    for path, tree in _modules():
        candidates = _module_dicts(tree)
        if not candidates:
            continue
        for name in sorted(set(candidates) & _written_names(tree)):
            if (_rel(path), name) not in _CACHES:
                offenders.append(f"{_rel(path)}:{candidates[name].lineno} — {name}")

    assert not offenders, (
        "these module-level caches grow by key with no declared bound:\n  "
        + "\n  ".join(offenders)
        + "\n\nUse sdlc.util.bounded.BoundedDict, or add it to _CACHES in this file with what "
          "bounds it (a registry, a login list — something that cannot grow with traffic).")


def test_the_net_sees_growth_that_never_uses_a_subscript():
    """Sabotage-proofing the net itself: a dict grown solely via `setdefault`/`update` must
    register as written, or the guard is quiet about exactly the class it exists for."""
    tree = ast.parse("_X = {}\n\ndef f(k, v):\n    _X.setdefault(k, []).append(v)\n"
                     "\ndef g(d):\n    _X.update(d)\n")
    assert "_X" in _written_names(tree)
    assert "_X" in _module_dicts(tree)


def _declared_cap(site) -> int | None:
    """The cap a `BoundedDict(N)` declaration in _CACHES promises, or None for caches bounded by
    something structural (a registry, a login list)."""
    m = re.search(r"BoundedDict\((\d+)\)", _CACHES[site])
    return int(m.group(1)) if m else None


@pytest.mark.parametrize("site", sorted(_CACHES))
def test_declared_caches_still_exist(site):
    """Same sabotage-proofing: a bound declared for a cache that was renamed protects nothing —
    and a declaration saying `BoundedDict(N)` over a plain `{}` protects even less: reverting
    `bot._PENDING = BoundedDict(200)` to `{}` used to keep every guard here green."""
    rel, name = site
    tree = ast.parse(add_ons.source(rel).read_text())
    node = _module_dicts(tree).get(name)
    assert node is not None, f"{rel} no longer declares {name}"
    cap = _declared_cap(site)
    if cap is not None:
        value = node.value
        assert isinstance(value, ast.Call) and value.args \
            and isinstance(value.args[0], ast.Constant) and value.args[0].value == cap, (
            f"{rel}:{name} is declared here as BoundedDict({cap}) but the code says "
            f"{ast.unparse(value)} — the declared bound protects nothing")


# ── guard 3: the bound is a BEHAVIOUR, not a declaration ───────────────────────────────────────
# The declarations above are prose until something overfills the real object through the real
# write path. Disabling BoundedDict's eviction wholesale used to pass the ENTIRE suite: every
# "BoundedDict(N)" in _CACHES was an unverified claim.


def test_BoundedDict_evicts_the_oldest_and_counts_what_it_dropped():
    from openfactory.util.bounded import BoundedDict

    d: BoundedDict[int, int] = BoundedDict(3)
    for i in range(5):
        d[i] = i
    assert len(d) == 3, "the cap did not hold"
    assert 0 not in d and 1 not in d, "the oldest entries were not the ones evicted"
    assert 4 in d
    assert d.evicted == 2, "silent discarding — nobody can tell the cap is being hit"

    d[4] = 99
    assert len(d) == 3 and d.evicted == 2, "replacing an existing key must not evict anybody"

    with pytest.raises(ValueError):
        BoundedDict(0)


_BOUNDED_SITES = sorted(site for site in _CACHES if _declared_cap(site) is not None)


@pytest.mark.parametrize("site", _BOUNDED_SITES)
def test_a_declared_bound_actually_holds_on_the_live_object(site):
    """Import the real module-level object and hammer it past its declared cap through its own
    write path. len() must never exceed the cap, the oldest entry must be the one gone, and the
    newest must be present — whatever class the object is, today or after a refactor."""
    rel, name = site
    cap = _declared_cap(site)
    add_ons.source(rel)
    obj = getattr(importlib.import_module(rel[:-3].replace("/", ".")), name)
    obj.clear()
    try:
        for i in range(cap + 50):
            obj[f"growth-guard-{i}"] = ("growth", "guard")
        assert len(obj) == cap, f"{rel}:{name} grew past its declared bound of {cap}"
        assert "growth-guard-0" not in obj, "nothing was evicted — the bound is prose"
        assert f"growth-guard-{cap + 49}" in obj, "the NEWEST entry was dropped instead"
    finally:
        obj.clear()


def test_the_channel_staging_cap_holds_through_remember():
    """product_channel's cap is hand-rolled rather than a BoundedDict, so it gets its own proof —
    through `remember()`, the only production write path into that dict."""
    import openfactory.product.channel as pc

    pc._PENDING.clear()
    try:
        for i in range(250):
            pc.remember(f"growth-guard-T{i}", {"kind": "fact", "term": str(i)})
        assert len(pc._PENDING) == 200, "the staging dict grew past the cap _CACHES declares"
        assert pc.pending_for("growth-guard-T0") is None, "the oldest draft was not evicted"
        assert pc.pending_for("growth-guard-T249") is not None
    finally:
        pc._PENDING.clear()
