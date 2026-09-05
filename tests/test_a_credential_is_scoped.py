"""A credential says WHICH AREAS it may act in, not just how much authority it has.

    *"if the person wants to write the tickets and drop them in TO-DO, fine — but the PO is there,
    available (on the platform, not in Slack)"* — the product owner, drawing the core/add-on boundary (#98).

THE HOLE THIS CLOSES, MEASURED BEFORE IT WAS FIXED. `needs_admin` defaults to True on the three
product writes, and the panel's `_actor` hands `admin=True` to anybody who got through the door.
So the only way to let a business analyst propose a requirement was to give them the panel token —
which also gives them `merge`, `skip`, and the production-release gate. The card names this as the
reason the PO needs a surface of their own; a surface without a scope would have been the same
credential wearing a different page.

TWO QUESTIONS, NOT ONE. *How much authority within an area* is `admin`, and a BA needs it — being
able to ACCEPT a requirement is the whole point, and it is the most consequential act there. *Which
areas at all* is `scopes`. Folding them together is what produced the hole.

WHY `None` IS NOT `frozenset()`. Every actor that existed before this — the CLI, a Slack admin, the
poller's SYSTEM, the panel's own token — is unscoped, and must stay that way or the migration
denies the entire platform to itself. `None` means nobody restricted this caller; an empty set
means somebody scoped them to nothing. The same distinction this codebase pays for between "could
not read" and "read it, and it was empty".
"""

from __future__ import annotations

import pathlib

import pytest

from openfactory import actions
from openfactory.actions.base import FLOOR, PRODUCT, SCOPES, Actor
from openfactory.identity.local import (
    PEOPLE_ENV,
    PRODUCT_GROUP,
    PRODUCT_PEOPLE_ENV,
    PRODUCT_SHARED_ENV,
    SHARED_ENV,
    LocalIdentity,
)

#: The rows the product credential exists for. Named rather than derived, so a row that silently
#: changed scope is a failure here rather than a test that agrees with the code — which is exactly
#: what it did when `product_requirements` was added: the guard caught its own author.
PRODUCT_ROWS = ("product_status", "product_requirements", "product_ask", "product_propose",
                "product_accept", "product_drop", "product_queue", "product_promote",
    "product_reorder",
                "product_release", "product_close_card", "product_align_card",
                "product_refine_card", "product_record_decision", "product_note_fact",
                "product_file_defect", "product_say", "product_thread", "product_recall", "product_pending",
                "product_triage",
                "product_announce", "product_needs_action", "product_baseline",
                "product_answer")


def _ba() -> Actor:
    """A business analyst: admin OF THE PRODUCT AREA, and nothing else."""
    return Actor(id="ana", display="Ana", via="panel", admin=True,
                 scopes=frozenset({PRODUCT}))


# ── the catalog declares where every row lives ──────────────────────────────────────────────────

def test_every_row_declares_a_scope_the_registry_KNOWS():
    """A typo'd scope is an area nothing can reach and nobody is told about.

    The same reason every other registry in this codebase refuses an unknown kind rather than
    carrying it: a row scoped to `"prodcut"` would be denied to every credential forever, and the
    denial would name a scope that does not exist.
    """
    strays = {name: row.scope for name, row in actions.CATALOG.items() if row.scope not in SCOPES}
    assert not strays, f"rows declare a scope outside {sorted(SCOPES)}: {strays}"


def test_the_product_rows_are_EXACTLY_the_product_area():
    """Both directions. A product row that lost its scope becomes reachable by a floor-only
    credential; a floor row that gained one becomes reachable by a BA — and the second is the
    direction that hands somebody the merge button."""
    scoped = {name for name, row in actions.CATALOG.items() if row.scope == PRODUCT}
    assert scoped == set(PRODUCT_ROWS), (
        f"the product area is {sorted(scoped)}, expected {sorted(PRODUCT_ROWS)}"
    )


def test_a_row_that_forgets_to_say_lands_on_the_FLOOR():
    """The forgetful case must be the closed one, like `needs_admin`'s default.

    A default of `product` — or of "any" — would mean a new row is reachable by a scoped credential
    unless somebody remembers to think about it, which is the wrong way round for this class.
    """
    row = actions.ActionSpec(name="whatever", summary="x", run=lambda **_: None)
    assert row.scope == FLOOR


# ── the gate ────────────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
@pytest.mark.parametrize("row", ["merge", "skip", "approve_prod"])
async def test_a_product_credential_is_REFUSED_the_floor(row):
    """The hole, closed. Each of these is something a BA holding the panel token could do."""
    outcome = await actions.perform(row, by=_ba(), project="acme", issue="1",
                                    **({"approver": "a", "password": "b", "version": "1.0.0"}
                                       if row == "approve_prod" else {}))

    assert not outcome.ok and outcome.code == actions.DENIED, outcome
    # THE REFUSAL NAMES BOTH SIDES. "not allowed" sends somebody to ask for more authority, which
    # is the wrong remedy — the answer is that this credential is for a different area entirely.
    assert "scoped to product" in outcome.message and FLOOR in outcome.message, outcome.message


@pytest.mark.asyncio
@pytest.mark.parametrize("row", PRODUCT_ROWS)
async def test_the_POSITIVE_twin_a_product_credential_reaches_its_own_rows(row):
    """Without this, deleting the whole product area from the catalog would leave the test above
    green — every row denied is every row 'safe'. Absence reads as compliance.

    Asserted on the CODE, not on success: these rows go on to resolve a project that does not
    exist here, and what is under test is that the scope gate let them past.
    """
    outcome = await actions.perform(row, by=_ba(), project="no-such-project-here",
                                    question="q", number="7")

    assert outcome.code != actions.DENIED, (
        f"{row} is in the product area and a product credential was denied it: {outcome.message}"
    )


@pytest.mark.asyncio
async def test_an_UNSCOPED_actor_still_reaches_everything():
    """The migration guard. Every actor that predates scopes carries `None`, and if `None` were
    read as "no areas" this change would have denied the platform to the poller, the CLI and every
    existing panel token at once."""
    assert actions.SYSTEM.scopes is None, "the factory's own actor became scoped"

    for row in ("merge", "product_accept"):
        outcome = await actions.perform(row, by=actions.SYSTEM, project="no-such-project-here",
                                        issue="1", number="7")
        assert outcome.code != actions.DENIED, (row, outcome.message)


def test_may_enter_is_the_one_place_the_question_is_asked():
    unscoped, scoped = Actor(id="x"), Actor(id="y", scopes=frozenset({PRODUCT}))

    assert unscoped.may_enter(FLOOR) and unscoped.may_enter(PRODUCT)
    assert scoped.may_enter(PRODUCT) and not scoped.may_enter(FLOOR)
    # scoped to nothing is a real answer, and it is not the same as unscoped
    assert not Actor(id="z", scopes=frozenset()).may_enter(PRODUCT)


# ── where the scope comes from ──────────────────────────────────────────────────────────────────

def test_a_product_token_resolves_to_a_product_subject():
    who = LocalIdentity(env={PRODUCT_PEOPLE_ENV: "tok-ana:ana:Ana Lima"}).identify(
        credential="tok-ana")

    assert who is not None and who.id == "ana"
    assert PRODUCT_GROUP in who.groups, who


def test_the_shared_product_token_is_anonymous_but_STILL_SCOPED():
    """Being unnamed and being unrestricted are different failures, and collapsing them would hand
    a product credential the whole floor — which is the one thing this mechanism exists to stop."""
    who = LocalIdentity(env={PRODUCT_SHARED_ENV: "shared-prod"}).identify(credential="shared-prod")

    assert who is not None
    assert not who.known, "the shared product token names nobody; the audit line must say so"
    assert PRODUCT_GROUP in who.groups, "an anonymous product credential was left unscoped"


def test_a_token_in_BOTH_maps_resolves_to_the_SMALLER_authority():
    """Narrow before broad. A copy-paste that puts one secret in two variables must not be able to
    widen a business analyst into an operator — the direction a configuration error fails in is the
    only thing that makes it survivable."""
    who = LocalIdentity(env={PEOPLE_ENV: "same:rob:Rob", PRODUCT_PEOPLE_ENV: "same:rob:Rob"}
                        ).identify(credential="same")

    assert who is not None and PRODUCT_GROUP in who.groups, (
        "a duplicated secret resolved to the floor credential — the widening direction"
    )


def test_product_tokens_COUNT_as_configuration():
    """THE FAIL-OPEN GUARD. `open_to_everyone` is what decides whether the panel's doors apply at
    all. A deployment that issued only product credentials — a BA needs to write requirements and
    nobody else needs the panel yet — would otherwise answer "nothing is configured" and serve
    every read endpoint unauthenticated. That is the exact direction C-26 already failed in once.
    """
    for env in ({PRODUCT_PEOPLE_ENV: "tok:ana:Ana"}, {PRODUCT_SHARED_ENV: "tok"}):
        assert not LocalIdentity(env=env).open_to_everyone(), env
    assert LocalIdentity(env={}).open_to_everyone(), "an unconfigured deployment stopped being open"


# ── the door, not just the action layer ─────────────────────────────────────────────────────────

@pytest.fixture
def two_credentials(monkeypatch):
    """One operator, one business analyst, resolved by the real identity provider."""
    monkeypatch.setenv(PEOPLE_ENV, "op-secret:rob:Rob")
    monkeypatch.setenv(PRODUCT_PEOPLE_ENV, "ba-secret:bia:Bia Rocha")
    monkeypatch.delenv(SHARED_ENV, raising=False)
    monkeypatch.delenv(PRODUCT_SHARED_ENV, raising=False)
    from fastapi.testclient import TestClient

    from openfactory.api.app import app

    return TestClient(app)


@pytest.mark.parametrize("path", ["/api/projects", "/api/temporal/jobs", "/api/inbox"])
def test_the_jobs_dashboard_is_a_READ_and_a_scoped_credential_cannot_have_it(two_credentials, path):
    """THE HALF THAT SCOPING THE ACTIONS ALONE WOULD HAVE MISSED.

    #98 asks for a surface "for a BA who has no access to the jobs dashboard". The dashboard is
    not actions — it is reads. A credential refused `merge` but served `/api/temporal/jobs` can
    still watch every job, every client's board and every word the factory has said; it just
    cannot click. That is a different product from the one the card describes.
    """
    ba = two_credentials.get(path, headers={"authorization": "Bearer ba-secret"})
    operator = two_credentials.get(path, headers={"authorization": "Bearer op-secret"})

    assert ba.status_code == 403, f"a product credential read {path}: {ba.status_code}"
    # NOT `== 200`, WHICH IS WHAT THE FIRST VERSION SAID AND WHY IT FAILED UNDER RANDOM ORDER.
    # `/api/inbox` asks the durable engine and answers 503 when it cannot be reached — so the
    # assertion was really "Temporal is up on this machine", which is the environment and not the
    # invariant. Both directions still hold with 403 as the subject: scoping that did nothing
    # leaves the BA un-denied above, and scoping that denied everybody shows up right here.
    assert operator.status_code != 403, (
        f"the operator was denied {path} by SCOPE — the mechanism refused somebody it was never "
        f"meant to touch: {operator.status_code} {operator.text[:160]}"
    )


def test_whoami_is_readable_by_EVERY_credential_and_still_needs_one(two_credentials):
    """The one read a scoped credential must have: a page served as a static file cannot know
    which surface to render without asking. Still gated — an anonymous caller learns nothing."""
    assert two_credentials.get("/api/whoami").status_code == 401

    ba = two_credentials.get("/api/whoami", headers={"authorization": "Bearer ba-secret"})
    assert ba.status_code == 200 and ba.json()["scopes"] == [PRODUCT], ba.json()

    operator = two_credentials.get("/api/whoami", headers={"authorization": "Bearer op-secret"})
    assert operator.status_code == 200, operator.text
    # `None`, NOT `[]` — the distinction survives to the wire, because a front end that read an
    # empty list as "no areas" would hide the whole panel from an ordinary operator.
    assert operator.json()["scopes"] is None, operator.json()


def test_a_route_nobody_classified_belongs_to_the_FLOOR():
    """The forgetful case is the closed one, matching `ActionSpec.scope`'s default. A route added
    next month is out of a scoped credential's reach until somebody decides otherwise — the
    opposite default would silently widen every BA on every deploy."""
    from openfactory.api.app import _scope_of_path

    assert _scope_of_path("/api/something-invented-later") == FLOOR
    assert _scope_of_path("/api/product/requirements") == PRODUCT
    assert _scope_of_path("/api/act/product_accept") == PRODUCT
    assert _scope_of_path("/api/whoami") is None


# ── the surface a scoped credential is sent to ──────────────────────────────────────────────────

PANEL = (pathlib.Path(__file__).resolve().parents[1] / "openfactory/api/panel.html").read_text()


def test_the_page_ASKS_which_surface_to_render_rather_than_assuming():
    """A page served as a static file cannot know whether its holder is an operator or a business
    analyst — the credential lives in localStorage. Boot reads `/api/whoami` BEFORE the floor
    reads, because every one of those is a 403 for a product credential and a screen full of them
    is indistinguishable from a broken deployment."""
    boot = PANEL.split("async function boot()")[1].split("\n}")[0]

    assert "/api/whoami" in boot, "the page no longer asks what it is holding"
    assert boot.index("/api/whoami") < boot.index("/api/projects"), (
        "the floor reads fire before the scope is known — a product credential gets a row of 403s"
    )
    assert "bootProduct()" in boot and "return" in boot, (
        "nothing routes a product credential away from the floor boot"
    )


def test_null_scopes_is_NOT_read_as_no_areas():
    """The migration trap, in the browser this time. Every ordinary panel token answers
    `scopes: null`, and a front end that read null as an empty list would send every operator who
    ever held one to the product surface — or to nothing at all."""
    fn = PANEL.split("function productOnly()")[1].split("\n}")[0]

    assert "Array.isArray" in fn, (
        "productOnly no longer distinguishes `null` (unscoped) from a list — every operator would "
        "be treated as scoped"
    )


def test_the_product_surface_shows_no_FLOOR_chrome():
    """Found by looking at the page, which is the only thing that could have found it. The status
    banner sat on its placeholder for ever — `paintFloor` runs on engine data this credential is
    refused — and the cost pill existed only to produce a 403 from `/api/metrics`."""
    fn = PANEL.split("async function bootProduct()")[1].split("\n}")[0]

    for element in ("#floor", "#costs"):
        assert element in fn and "display" in fn, (
            f"{element} is still shown on the product surface, where it is either a permanent "
            f"placeholder or a button that can only fail"
        )


def test_every_product_button_is_a_MAPPING_onto_the_action_layer():
    """The panel gains no capability of its own (ADR-0039). If a verb is missing from this page it
    is missing from the catalogue, which is the honest place for it to be missing from."""
    surface = PANEL.split("async function bootProduct()")[1].split("// --- project floor")[0]

    for row in ("product_status", "product_requirements", "product_ask", "product_propose",
                "product_accept", "product_drop"):
        assert f'"{row}"' in surface, f"the surface never reaches {row}"
    # and it reaches them through the generic route, not one invented per verb
    assert '"/api/act/"' in surface, (
        "the surface calls something other than the generic action route — a second implementation"
    )


def test_the_panel_ignores_groups_that_are_not_SCOPES():
    """A buyer's identity provider asserts dozens of groups that mean nothing here. Treating an
    unrecognised one as a scope would either deny somebody for holding an unrelated group, or
    invent an area — so the mapping intersects with the registry and an all-foreign subject stays
    unscoped, exactly as it was before scopes existed."""
    from openfactory.api.app import _scopes_of
    from openfactory.identity.base import Subject

    assert _scopes_of(Subject(id="a", groups=("finance", "everyone"))) is None
    assert _scopes_of(Subject(id="a", groups=())) is None
    assert _scopes_of(Subject(id="a", groups=("finance", PRODUCT))) == frozenset({PRODUCT})
