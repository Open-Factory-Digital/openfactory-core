"""PreviewRuntime — what runs a preview of the product, once the core has assembled it (ADR-0050
D11; the design on #265, §2.4 and §5.1).

THE CORE DECIDES WHAT RUNS; A ROW DECIDES WHERE. Everything that makes a preview safe is decided
before a runtime is asked anything: the shape is read from the base branch, admitted key by key,
re-rooted per service and bounded by the operator's policy (`openfactory/preview/`). What reaches
a row is a `PreviewPlan` — a compose document plus its provenance, all data — and what comes back
is data too. No handle, no client, no callback crosses this port (docs/core/07-extensibility.md
§9), so a row an add-on declares can run the same plan on a machine the worker cannot see: the
plan carries the layout and every path as `(tree, side, rel)`, enough to materialise the trees
itself.

TWO ROWS SHIP, AND ONE OF THEM RUNS NOTHING. `compose` runs the plan on the deployment's own Docker
daemon through the compose CLI; `none` refuses by name, which is the true answer on a deployment
with no daemon (a cloud worker, the one-machine kind before it opts in). Any other runtime — a
Kubernetes namespace, a vendor's ephemeral environments — is a `preview.<kind>` row in the
`openfactory.adapters` entry-point group, validated by the same check as ours.

A ROW RE-JUDGES WHAT IT IS HANDED. `refusals(plan)` is the plan-level half of admission, pure and
exported so an add-on row can call it: a document carrying a key admission refuses, a volume the
unit's name does not prefix, a network nobody declared, a container without its containment. The
assembler never produces one; a row that ran one anyway would be running something nobody
admitted, and the conformance suite plants exactly that plan to see which rows refuse it.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict

from openfactory import preview
from openfactory.preview.admit import PASS_BUILD, PASS_SERVICE, SET_SERVICE
from openfactory.preview.plan import PreviewPlan, PreviewUp, RunningPreview

#: Every compose project, network, volume and work directory a preview owns starts with this.
#: THE ONLY THING THAT AUTHORISES A DELETE: a label is metadata anybody with the daemon can write,
#: so a row deletes what it can DERIVE — never what a label names.
PREFIX = "openfactory-pv-"


class PreviewTraits(BaseModel):
    """What the core may know about a runtime without asking it anything.

    `builds` — whether it can build an image from a service's context (a row that can only pull
    would preview every change as the base). `reaches` — the reaches the panel may route through
    it (`network`: the panel joins the unit's edge network; `loopback`: exposed services on
    127.0.0.1 of the worker's host); empty for a row that runs nothing."""

    model_config = ConfigDict(frozen=True)

    name: str
    builds: bool
    reaches: tuple[str, ...] = ()


@runtime_checkable
class PreviewRuntime(Protocol):
    """The seven things the core asks of a runtime, and nothing a provider happens to offer.

    Every method answers data and none raises past its own boundary: a preview that could not
    start is a sentence on a card, never a failed activity retried into a half-created stack."""

    def prerequisites(self) -> list[str]:
        """What this deployment lacks for this runtime, each by name; `[]` = ready."""
        ...

    def up(self, plan: PreviewPlan) -> PreviewUp:
        """Bring the plan up and judge readiness: an exposed service is ready when its
        healthcheck passed (`healthy`) or, with none, when it runs (`started`); a one-shot that
        exited 0 ran and finished; any non-zero exit is the failure, named."""
        ...

    def watch(self, compose_project: str) -> RunningPreview | None:
        """One poll of one unit — None when nothing of it exists. Never raises."""
        ...

    def logs(self, compose_project: str, log_dir: str) -> list[str]:
        """Write every service's log under `log_dir`; the paths written. Called before ANY down,
        because a stack taken down first leaves nobody able to say why it failed."""
        ...

    def down(self, compose_project: str, workdir: str) -> list[str]:
        """Take one unit down — containers, volumes, images it built, its networks, its work
        directory — and say what was removed. `[]` for a project that does not exist. Never
        raises."""
        ...

    def running(self) -> list[RunningPreview]:
        """Every unit this runtime holds, EXITED ONES INCLUDED: a crashed stack is exactly the one
        the reaper must still see."""
        ...

    def prove(self, plan: PreviewPlan) -> PreviewUp:
        """Up, wait, down — the BASE product only, for a proposal's proof. A plan with a change in
        it is refused: a proof builds nothing an agent wrote."""
        ...


@runtime_checkable
class PrunesCaches(Protocol):
    """A runtime whose daemon keeps what a unit's own `down` never touches — dangling images a
    failed build left, the build cache — and can prune it. Optional: a row that keeps nothing
    between units has nothing to prune and does not declare it."""

    def prune(self) -> list[str]:
        """Prune what previews left on this runtime; what was pruned, in words."""
        ...


_TOP = frozenset({"services", "volumes", "networks"})


def refusals(plan: PreviewPlan) -> list[str]:
    """Why a row must NOT run this plan, each a sentence; `[]` when the plan is what admission and
    the assembler produce.

    Pure, and a second look rather than a second admission: the keys a service may carry are the
    ones admission passes or the assembler sets; every volume is named under the unit's compose
    project (compose writes a `name:` un-prefixed, which is how a document could mount the
    factory's own state); every network is the unit's internal default, its edge network or the
    operator's egress network; every container drops every capability and cannot gain one; every
    bind source is inside the unit's work directory."""
    out: list[str] = []
    cp = plan.compose_project
    if not cp.startswith(PREFIX):
        out.append(f"the compose project `{cp}` is not a preview's (`{PREFIX}…`).")
    if plan.workdir.rstrip("/").rsplit("/", 1)[-1] != cp:
        out.append(f"the work directory `{plan.workdir}` is not named after the unit (`{cp}`).")
    doc = plan.doc or {}
    for key in sorted(set(doc) - _TOP):
        out.append(f"the document carries `{key}:` at its top level, which a preview never runs.")
    services = doc.get("services") or {}
    if not isinstance(services, dict) or not services:
        out.append("the document runs no service.")
        services = {}
    allowed = PASS_SERVICE | SET_SERVICE
    for name, svc in sorted(services.items()):
        svc = svc or {}
        for key in sorted(set(svc) - allowed):
            if key == "ports" and plan.reach == "loopback" and name in plan.expose and all(
                    isinstance(p, dict) and p.get("host_ip") == "127.0.0.1"
                    for p in svc.get("ports") or []):
                continue
            out.append(f"`{name}` carries `{key}:`, which admission never passes.")
        build = svc.get("build")
        if isinstance(build, dict):
            for key in sorted(set(build) - PASS_BUILD):
                out.append(f"`{name}`'s build carries `{key}:`, which admission never passes.")
        if "ALL" not in (svc.get("cap_drop") or []):
            out.append(f"`{name}` keeps capabilities it was never granted (`cap_drop: [ALL]` is "
                       f"missing).")
        if "no-new-privileges:true" not in (svc.get("security_opt") or []):
            out.append(f"`{name}` may gain privileges (`no-new-privileges` is missing).")
        labels = svc.get("labels") or {}
        if not isinstance(labels, dict) or labels.get(preview.LABEL) != cp:
            out.append(f"`{name}` is not labelled as this unit's (`{preview.LABEL}={cp}`).")
        for mount in svc.get("volumes") or []:
            if not isinstance(mount, dict):
                out.append(f"`{name}` carries a mount in a form admission never writes.")
                continue
            kind, source = mount.get("type"), str(mount.get("source") or "")
            if kind == "bind" and not source.startswith(plan.workdir.rstrip("/") + "/"):
                out.append(f"`{name}` mounts `{source}`, outside the unit's work directory.")
            elif kind == "volume" and source and source not in (doc.get("volumes") or {}):
                out.append(f"`{name}` mounts the volume `{source}`, which the document does not "
                           f"declare.")
            elif kind not in ("bind", "volume", "tmpfs"):
                out.append(f"`{name}` mounts a `{kind}`, which a preview never runs.")
    for vol, spec in sorted((doc.get("volumes") or {}).items()):
        spec = spec or {}
        if str(spec.get("name") or "") != f"{cp}_{vol}":
            out.append(f"the volume `{vol}` is not named `{cp}_{vol}` — a name outside the unit's "
                       f"could be any volume on the daemon, the factory's own included.")
        for key in sorted({"external", "driver", "driver_opts"} & set(spec)):
            out.append(f"the volume `{vol}` carries `{key}:`, which a preview never runs.")
    ours = {plan.edge_network} | ({plan.egress_network} if plan.egress_network else set())
    for net, spec in sorted((doc.get("networks") or {}).items()):
        spec = spec or {}
        if net == "default":
            if spec.get("internal") is not True or spec.get("name") or spec.get("external"):
                out.append("the unit's default network is not an internal network of its own.")
        elif not (spec.get("external") and spec.get("name") in ours):
            out.append(f"the network `{net}` is neither the unit's edge network nor the "
                       f"operator's egress network.")
    return out
