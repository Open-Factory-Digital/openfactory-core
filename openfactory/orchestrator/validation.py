"""Resolve which components a diff touched, which validation commands apply, and
whether the diff outgrew what one ticket should be.

The diff is the source of truth for touched components (ADR-0001 D-6). Applicable
validation = repo-wide ∪ (for each touched component: its stack preset ∪ its own
overrides), with precedence preset < repo-wide < component-specific.

`scope_explosion` is D-6's OTHER half, and until it existed here it was a promise with
no code behind it: the manifest has carried `max_touched_components`/`max_diff_lines`
since before ADR-0013's transitional plan-gate rewrite, commented "abort to refinement
past this" — and nothing ever read them. ADR-0002 §3 names this explicitly as the
COMPLEMENT to the pre-execution plan gate: the plan gate catches an oversized ticket
before any code is written (a judgment about the request); this catches it after,
from what the ticket actually became (a fact about the diff) — the same discipline
D-6 applies to touched components applied to their COUNT.
"""

from __future__ import annotations

from openfactory.contracts import Manifest
from openfactory.policy import load_preset


def resolve_touched_components(diff_paths: list[str], manifest: Manifest) -> list[str]:
    touched: list[str] = []
    for name, comp in manifest.components.items():
        if any(_touches(p, comp.path) for p in diff_paths):
            touched.append(name)
    return touched


def _touches(path: str, pattern: str) -> bool:
    """Whether one diff path falls under one component's declared path.

    FOUND LIVE BY THE FIRST fx-mono RUN (F-03, 2026-08-04). `Component.path` is documented as a
    GLOB — the docs' own example is `services/api/**` — and this resolver treated it as a string
    prefix: no diff path starts with the literal characters `functions/**/`, so every component
    declared in the documented shape was INVISIBLE. The per-component gates never ran (the
    repo-wide one masked it), `touched_components` came back empty, and the scope-explosion cap
    had nothing to count. Silently, on every manifest that followed the documentation.

    Glob characters → fnmatch (whose `*` crosses `/`, so `dir/**` covers the whole subtree and
    `dir/*.py` reaches nested files too — the generous reading, documented rather than
    surprising). No glob characters → the original prefix rule, unchanged: `services/api` covers
    `services/api/routes.py` and never `services/api2/…`."""
    pattern = pattern.rstrip("/")
    if any(ch in pattern for ch in "*?["):
        from fnmatch import fnmatch

        # `dir/**` must also cover a file directly at `dir`'s root and the dir itself
        bare = pattern.rstrip("*").rstrip("/")
        return fnmatch(path, pattern) or path == bare or path.startswith(bare + "/")
    return path == pattern or path.startswith(pattern + "/")


def as_gate(value):
    """A `Gate` from either shape a manifest may hold. One place, because a consumer that has to
    remember both is a consumer that will forget: `box prove`, the command hash, the runner and
    the conformance floor all read this map."""
    from openfactory.contracts.manifest import Gate

    if isinstance(value, Gate):
        return value
    # A MAPPING, because a PRESET never passes through Manifest validation — `load_preset` is
    # `yaml.safe_load`, so its gates arrive as plain dicts. `Gate(command=str(value))` turned one
    # into `command="{'command': 'semgrep …', 'advisory': True}"` and the platform would have run
    # a dict's repr as a shell command: a silent, total failure of the gate, on the preset shipped
    # to make security free. Found by asserting the preset's property rather than reading it.
    if isinstance(value, dict):
        return Gate(**value)
    return Gate(command=str(value))


def gate_commands(gates: dict) -> dict[str, str]:
    """`{name: command}` — for the consumers that only ever wanted the string (the proof, the
    hash). Keeping them on strings is what makes the schema change invisible to them."""
    return {name: as_gate(g).command for name, g in (gates or {}).items()}


def applicable_validations(touched: list[str], manifest: Manifest) -> dict:
    cmds: dict[str, str] = {}
    # 1. preset base for each touched component's stack
    for name in touched:
        comp = manifest.components[name]
        cmds.update(load_preset(comp.stack).get("validate", {}))
    # 2. repo-wide overlays the presets (the project's explicit choice wins)
    cmds.update(manifest.validation)
    # 3. component-specific overrides win for their area
    for name in touched:
        cmds.update(manifest.components[name].validation)
    return cmds


def scope_explosion(touched: list[str], diff: str, manifest: Manifest) -> str:
    """Why this diff has grown past what one ticket should be, or "" when it hasn't.

    TWO SEPARATE SHAPES OF EXPLOSION, checked independently because either can happen
    without the other: a ticket can spread across many components while touching only a
    few lines in each (a rename that ripples), or grow enormous within a single
    component (one function nobody split). `max_touched_components` catches the first;
    `max_diff_lines` catches the second. Neither threshold is required — `None` (the
    manifest default) means this project has not opted in, and the check is silent.

    COUNTS `+`/`-` CONTENT LINES ONLY. `git diff`'s own `+++`/`---` file headers use the
    same prefix as an added/removed blank line; counting them would over-report by
    exactly the number of files touched, worst on a diff that adds many small files."""
    cap = manifest.max_touched_components
    if cap is not None and len(touched) > cap:
        return (f"the diff touches {len(touched)} components ({', '.join(sorted(touched))}) — "
                f"past this project's limit of {cap}. That is more than one outcome; split it.")
    limit = manifest.max_diff_lines
    if limit is not None:
        changed = sum(1 for line in diff.splitlines()
                     if line.startswith(("+", "-")) and not line.startswith(("+++", "---")))
        if changed > limit:
            return (f"the diff changes {changed} lines — past this project's limit of {limit}. "
                    f"That is more than one changeset a person can review; split it.")
    return ""
