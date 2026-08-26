"""One all-green `doctor.Probes`, DERIVED from the dataclass's own fields.

WHY THIS FILE EXISTS, and it is the same accident twice. A doctor test that means to measure ONE
thing built its probe set with `dataclasses.replace(doctor.probes_for(project), **a_few_pins)` —
so every member it did not name went on reading the real machine. Twice now a new member joined
`doctor.Probes` and answered differently somewhere:

  * 2026-08-21 — `agent_credential`. Green on a laptop whose `.env` carries a token, red on a
    clean runner. Three tests went red on GitHub Actions and nowhere else, and the repair was to
    pin that one probe in each of them, by hand, one call site at a time.
  * 2026-08-24 — `api_budget`. Green on a laptop where `gh` is logged in (the doctor's probe
    shells out, so the session's credential firewall — which strips environment variables —
    cannot see it), red in any clean environment, where it answers "the API budget could not be
    read". Three tests, the same three shapes, the same repair proposed.

The repair that keeps being proposed is the one that keeps failing: pinning what today's machine
happens to disagree about. THE MEMBER THAT BREAKS THE NEXT TEST IS ALWAYS THE ONE NOBODY HAD
THOUGHT OF, so the default has to be inverted. Here every member of `doctor.Probes` is pinned to
a green answer, derived from `dataclasses.fields`, and a test unpins exactly what it measures. A
probe added tomorrow is green by default in every one of these tests, and a probe added tomorrow
with NO green answer here fails LOUDLY at construction, naming itself — because a helper that
quietly left a member unpinned would be the very defect it exists to end, absence read as
compliance.

WHAT THIS DELIBERATELY DOES NOT COVER. Nothing here proves that `probes_for` wires the real
world: this is a synthetic machine. The wiring is a separate behaviour with its own guards, which
already exist and name themselves as such (`test_the_real_probes_actually_wire_the_gate`,
`test_the_lookup_is_wired_and_asks_both_proposal_branches`) — one asks the probe, the other
watches the function it must reach. Mixing the two is what produced the nine call sites above:
a test that says "the verdict at §2" and silently also measures whether this laptop has `gh`.
"""

from __future__ import annotations

import dataclasses
import time
from typing import Any

from openfactory import doctor


def _a_manifest_that_meets_the_floor():
    """A REAL `Manifest`, never a stub with two attributes on it.

    `_manifest`, `_floor`, `_merge_policy`, `_post_merge` and `_ci_declared` all read this one
    object, and three of them ask it questions a stub cannot answer (`declared_keys()`,
    `stage_a_person_confirms()`, `model_fields`). A double that cannot exist proves nothing about
    the code that meets the real thing.
    """
    from openfactory.contracts import Manifest

    return Manifest(
        version=1,
        base_branch="main",
        validate={"test": "pytest -q",
                  "security": {"command": "bandit -q -r .", "advisory": True}},
    )


def _no_product_module():
    """`product_link`'s green answer: the module is OFF, which is a legitimate setup and an `ok`
    finding carrying a note — not a failure, and not silence either."""
    from openfactory.product.config import ProductLink

    return ProductLink(active=False, kind="off", reason="no product module")


def _a_budget_with_room():
    """`api_budget`'s green answer: a real `Budget` well above the ADAPTER's own floor.

    `Budget` and not `NOT_REPORTED`, deliberately. Both are green findings, and only this one is
    green for the reason a healthy GitHub deployment is: the quota was READ and there is room in
    it. `NOT_REPORTED` is a different fact ("this vendor publishes no budget"), and a test that
    wants it says so.
    """
    from openfactory.adapters.tracker.base import Budget

    return Budget(resource="graphql", remaining=4800, limit=5000, floor=200,
                  reset_epoch=int(time.time()) + 3600, vendor="a tracker")


#: One green answer per member of `doctor.Probes`, by field name. The KEYS are the contract: they
#: are compared against `dataclasses.fields(doctor.Probes)` by
#: `tests/test_a_probe_set_is_pinned_whole.py`, in both directions, so neither a new member nor a
#: retired one can sit here unnoticed.
#:
#: A "green" answer is one `diagnose` renders as an `ok` finding — measured by that same guard
#: running the real `diagnose` over this set, never asserted by the fact that it is written here.
GREEN_ANSWERS: dict[str, Any] = {
    "docker_running": lambda: (True, ""),
    "harness_on_path": lambda kind: True,
    "manifest": _a_manifest_that_meets_the_floor,
    "forge_reachable": lambda: (True, ""),
    "board_columns": lambda: ["Backlog", "TO-DO", "In progress", "In review", "Needs Action",
                              "Done"],
    "pickup_column": lambda: "TO-DO",
    "requires_review": lambda: False,
    "floor_enforced": lambda: True,
    "harness_kind": lambda: "claude_code",
    "product_link": _no_product_module,
    "agent_credential": lambda: (True, "an agent credential is present"),
    # `{}` is "the CI was read and declares nothing", which compares cleanly against any manifest.
    # `None` — "could not read it" — is also an `ok` finding, and it is a degraded machine, which
    # is not what a baseline should describe.
    "ci_checks": lambda: {},
    "box_gate": lambda: None,  # nothing holds pickup — the box is proven
    "foreign_proofs": lambda: False,  # a single-repo project: no foreign proof recorded
    "api_budget": _a_budget_with_room,
    "open_proposal": lambda: "",  # no proposal is open; the manifest above is merged
}


def a_fully_pinned_probe_set(**over) -> doctor.Probes:
    """Every member of `doctor.Probes` pinned to a green answer, except the ones named in `over`.

    Nothing in the returned set reads this machine: no PATH, no docker socket, no network, no
    credential, no `gh`. That is the point — a test using it measures what it names and nothing
    else, on any machine, in any environment.

    RAISES rather than skipping when a member has no green answer here. A member left out would
    fall back to the dataclass's own default — `None` for every optional probe, which makes
    `diagnose` skip that check entirely — and a check that silently stops being run is exactly
    the shape ("built, tested, reached by nothing") this suite spends most of its guards on.
    """
    answers = {}
    unanswered = []
    for member in dataclasses.fields(doctor.Probes):
        if member.name in over:
            continue  # the caller is measuring this one
        if member.name not in GREEN_ANSWERS:
            unanswered.append(member.name)
            continue
        answers[member.name] = GREEN_ANSWERS[member.name]
    if unanswered:
        raise AssertionError(
            f"doctor.Probes has {len(unanswered)} member(s) with no green answer in "
            f"tests/pinned_probes.py: {', '.join(unanswered)}. Add one per member — until then "
            f"every test built on this helper is measuring an unpinned probe, which is how "
            f"`agent_credential` (2026-08-21) and `api_budget` (2026-08-24) each turned three "
            f"green tests red on a machine that was not the author's.")
    return doctor.Probes(**answers, **over)
