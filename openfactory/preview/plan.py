"""The data a preview is assembled from and assembled into (ADR-0050; the design on #265, §2.3).

Everything here is a frozen pydantic model and nothing else, for two reasons that are the same
reason. A preview crosses processes — the worker assembles it, a runtime row runs it, and a row an
add-on declares may run it on another machine entirely — so what crosses must be data:
`tests/test_ports_are_serialisable.py` admits scalars, containers, `BaseModel`, `Enum` and
`Literal`, and refuses a dataclass. And frozen, because a plan that a step downstream could edit in
place would be a plan nobody admitted.

THE UNIT (D1). What a person asked to see: one card, or one requirement and every card that
executes it. THE TREES. One repository of the unit, checked out at most twice under the unit's
work directory — `base/<dir>` at the base branch's tip, and `change/<dir>` at the head the forge
reported open, only where the unit has a pull request in that repository (D5). THE PLAN. The
admitted compose document plus its provenance: which service is built from which tree, which names
it may receive, how it is reached, what it may use.
"""

from __future__ import annotations

import posixpath
from typing import Literal

from pydantic import BaseModel, ConfigDict

_FROZEN = ConfigDict(frozen=True)

Side = Literal["base", "change"]


class CardRef(BaseModel):
    """One card of a unit, qualified: `acme/api#13` in `acme/api`."""

    model_config = _FROZEN

    ref: str
    repo: str = ""


class Unit(BaseModel):
    """What a preview is OF (D1): a card, or a requirement with every card that executes it.

    `token` is what every name is built from — the card's number (`34`) or the requirement's
    (`req0012`) — so one key, one cookie and one compose project serve the whole unit."""

    model_config = _FROZEN

    project: str
    kind: Literal["card", "requirement"]
    id: str
    cards: tuple[CardRef, ...] = ()
    token: str


class Tree(BaseModel):
    """One repository of the unit.

    `diff_paths` is the CHANGE'S OWN diff — merge base to the head the forge reported — never a
    tree diff against today's base tip, which would attribute every commit the base gained since
    the branch point to the change and rebuild services it never touched."""

    model_config = _FROZEN

    repo: str
    dir: str
    #: tokenless: a credential is an argument of whoever fetches, never a field of the plan
    clone_url: str = ""
    base_branch: str = ""
    base_commit: str = ""
    merge_base: str = ""
    branch: str = ""
    #: "" when the unit has no pull request in this repository — it then contributes base only
    change_commit: str = ""
    pr_url: str = ""
    diff_paths: tuple[str, ...] = ()

    @property
    def has_change(self) -> bool:
        return bool(self.change_commit)


class Layout(BaseModel):
    """The unit's work directory and the repositories in it, keyed by directory name.

    Side by side under their short names, so a compose file's `../web` names the `web`
    repository in the base layout exactly as it does on a developer's laptop (§6.3)."""

    model_config = _FROZEN

    workdir: str
    trees: dict[str, Tree]

    def root(self, dir: str, side: Side) -> str:
        """`<workdir>/<side>/<dir>` — where one repository is checked out on one side."""
        return posixpath.join(self.workdir, side, dir)


class TreePath(BaseModel):
    """A path the compose document carries, said as (repository directory, side, relative path).

    The absolute form is what the local compose row runs; this form is what lets a row on another
    machine materialise the same trees itself and rewrite the absolute ones (§5.6)."""

    model_config = _FROZEN

    tree: str
    side: Side
    rel: str


class Refused(BaseModel):
    """A preview that will not be assembled, and every reason, each a sentence a person can act
    on. Never raised: a refusal is an answer the card shows, not a crash in an activity."""

    model_config = _FROZEN

    reasons: tuple[str, ...]
    notes: tuple[str, ...] = ()


class PreviewPlan(BaseModel):
    """The assembler's output, and the only input a runtime row receives (D11).

    `doc` IS a compose document — the client's own, canonicalised by the compose CLI and admitted
    key by key — so what the client's developers run and what the preview runs are the same text
    wherever the factory did not say otherwise in `notes`."""

    model_config = _FROZEN

    unit: Unit
    project: str
    compose_project: str
    workdir: str
    layout: Layout
    doc: dict
    #: service → every path the doc carries for it, as (tree, side, rel)
    paths: dict[str, list[TreePath]]
    expose: dict[str, int]
    data: tuple[tuple[str, str | list[str]], ...] = ()
    from_change: dict[str, bool]
    #: repository → the commit it was built from
    commits: dict[str, str]
    #: service → {name inside the container: name in the worker's environment}. NAMES ONLY:
    #: a value never reaches the plan, the document on disk, an argument list or a label.
    env_names: dict[str, dict[str, str]]
    #: the same, for the BUILD of a service — only what the operator listed under `build_args`
    build_arg_names: dict[str, dict[str, str]]
    urls: dict[str, str]
    internal_urls: dict[str, str]
    reach: Literal["network", "loopback"] = "network"
    edge_network: str
    loopback_ports: dict[str, int] = {}
    limits: dict[str, str] = {}
    egress_network: str = ""
    expires_at: int = 0
    pr_urls: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()


class PreviewUp(BaseModel):
    """What bringing a plan up answered. `health` per exposed service: "healthy" (its healthcheck
    passed) or "started" (it has none) — the card says which, because the second proves less."""

    model_config = _FROZEN

    ok: bool
    services: dict[str, int] = {}
    health: dict[str, str] = {}
    images: dict[str, str] = {}
    log_dir: str = ""
    why: str = ""


class RunningPreview(BaseModel):
    """One preview a runtime found running (or exited — a crashed stack is still the reaper's)."""

    model_config = _FROZEN

    compose_project: str
    unit: str
    project: str
    state: str
    expires_at: int = 0
    started_at: int = 0
    pr_urls: tuple[str, ...] = ()
