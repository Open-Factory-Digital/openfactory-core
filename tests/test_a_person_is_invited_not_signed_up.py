"""A person is invited, not signed up — the local row's durable half (#33, slice 2).

`local` knew a person one way: a `token:id:display` row in an environment variable, edited by
whoever edits the deployment's environment and delivered on the next restart. Right for the first
operator, wrong for the tenth person. `people.py` keeps the people an operator INVITED — a one-time
link, a name and a credential chosen on first use, who vouched for them recorded — in the store
the worker and the panel share, and a session of theirs resolves in `identify` between the
per-person rows and the shared ones.

Not open sign-up, on the identity module's own rule: an unknown caller who gets a plausible
identity is written into an audit line as fact, and an invitation is the act that makes the name
somebody's responsibility.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from openfactory.identity import people
from openfactory.identity.base import IdentityProvider
from openfactory.identity.local import PRODUCT_GROUP, LocalIdentity
from openfactory.identity.people import PASSWORD_MIN_CHARS, PeopleStore, digest

ROOT = Path(__file__).resolve().parent.parent
GOOD = "correct horse battery staple"
#: Captured at import, before any fixture replaces it: the real sink check, for the one test
#: that asks what it says of a sink that keeps nothing.
_REAL_SINK_IS_DURABLE = people.sink_is_durable


class Rows:
    """The sink in memory, as the fold reads it back: one dict per event row."""

    def __init__(self) -> None:
        self.rows: list[dict] = []
        self.durable = True
        self.reads = 0

    def read(self) -> list[dict]:
        self.reads += 1
        return list(self.rows)

    def write(self, event: str, extra: dict, *, expires_at: int | None = None) -> bool:
        if not self.durable:
            return False
        self.rows.append({"kind": people.KIND, "role": event, "expires_at": expires_at,
                          "extra": {"event": event, **extra}})
        return True


def store(rows: Rows, now=None) -> PeopleStore:
    return PeopleStore(read=rows.read, write=rows.write, now=now)


def invite_and_register(rows: Rows, ident="ana@acme.example", *, by="roberto", groups=(),
                        display="Ana Lima", password=GOOD, now=None):
    s = store(rows, now)
    token, _ = s.invite(ident, display=display, groups=groups, by=by)
    person = s.register(token=token, display=display, password=password)
    assert not isinstance(person, str), person
    return s, person


@pytest.fixture
def local(monkeypatch) -> Rows:
    """The panel as a token deployment with nothing configured, its people store in memory."""
    for name in ("OPENFACTORY_IDENTITY", "OPENFACTORY_PANEL_TOKEN", "OPENFACTORY_PANEL_TOKENS",
                 "OPENFACTORY_PRODUCT_TOKEN", "OPENFACTORY_PRODUCT_TOKENS"):
        monkeypatch.delenv(name, raising=False)
    rows = Rows()
    monkeypatch.setattr(people, "_read_rows", rows.read)
    monkeypatch.setattr(people, "_write_row", rows.write)
    monkeypatch.setattr(people, "sink_is_durable", lambda: "")
    return rows


# ── the store ───────────────────────────────────────────────────────────────────────────────────

def test_an_invitation_is_a_link_shown_once_and_a_hash_kept():
    rows = Rows()
    token, invitation = store(rows).invite("ana@acme.example", display="Ana", by="roberto")

    assert invitation.id == "ana@acme.example" and invitation.by == "roberto"
    assert invitation.token_hash == digest(token)
    assert token not in str(rows.rows), "the token is shown once; the store keeps its hash"
    assert rows.rows[0]["extra"]["token_hash"] == digest(token)
    assert rows.rows[0]["expires_at"] == invitation.expires_at, "the row expires with the link"
    assert [i.id for i in store(rows).pending()] == ["ana@acme.example"]


def test_an_invitation_needs_a_voucher_and_a_one_word_id():
    s = store(Rows())
    assert "vouched" in s.invite("ana@acme.example", by="")
    assert "one word" in s.invite("ana lima", by="roberto")
    assert "one word" in s.invite("", by="roberto")


def test_registering_redeems_the_link_once_and_keeps_only_a_hash():
    rows = Rows()
    s = store(rows)
    token, _ = s.invite("ana@acme.example", display="Ana", groups=(PRODUCT_GROUP,), by="roberto")

    person = s.register(token=token, display="Ana Lima", password=GOOD)

    assert person.id == "ana@acme.example" and person.display == "Ana Lima"
    assert person.groups == (PRODUCT_GROUP,) and person.invited_by == "roberto"
    assert person.password_hash.startswith("scrypt$") and GOOD not in str(rows.rows)
    assert store(rows).pending() == [], "redeemed"
    assert "already used" in store(rows).register(token=token, display="X", password=GOOD)


def test_a_short_password_is_refused_by_number():
    rows = Rows()
    s = store(rows)
    token, _ = s.invite("ana@acme.example", by="roberto")

    why = s.register(token=token, display="Ana", password="x" * (PASSWORD_MIN_CHARS - 1))

    assert isinstance(why, str) and str(PASSWORD_MIN_CHARS) in why
    assert store(rows).pending(), "the link survives a refused attempt"


def test_an_expired_or_unknown_link_is_nobody_s():
    rows = Rows()
    clock = [1_000_000]
    s = store(rows, now=lambda: clock[0])
    token, _ = s.invite("ana@acme.example", by="roberto")
    clock[0] += people.INVITE_TTL_SECONDS + 1

    assert "expired" in store(rows, now=lambda: clock[0]).register(token=token, display="A",
                                                                   password=GOOD)
    assert s.invitation_for("never-issued") is None and s.invitation_for("") is None


def test_an_already_registered_person_cannot_be_invited_again():
    rows = Rows()
    s, _ = invite_and_register(rows)

    assert "already registered" in s.invite("ana@acme.example", by="roberto")


def test_login_mints_a_session_and_the_wrong_password_does_not():
    rows = Rows()
    s, person = invite_and_register(rows)

    token = s.login("ana@acme.example", GOOD)
    assert token and store(rows).session_of(token).id == "ana@acme.example"
    assert token not in str(rows.rows)
    assert s.login("ana@acme.example", "not it, not it") == ""
    assert s.login("nobody@acme.example", GOOD) == ""
    assert s.session_of("never-minted") is None and s.session_of("") is None


def test_a_session_expires_and_a_revoked_one_dies_now():
    rows = Rows()
    clock = [1_000_000]
    s, _ = invite_and_register(rows, now=lambda: clock[0])
    token = s.login("ana@acme.example", GOOD)

    clock[0] += people.SESSION_TTL_SECONDS + 1
    assert store(rows, now=lambda: clock[0]).session_of(token) is None, "expired"

    clock[0] -= people.SESSION_TTL_SECONDS
    late = store(rows, now=lambda: clock[0])
    assert late.session_of(token) is not None
    assert late.revoke(token) is True
    assert late.session_of(token) is None and store(rows).revoke(token) is False


def test_a_bad_row_costs_only_itself_and_an_unreadable_store_is_empty(caplog):
    rows = Rows()
    rows.rows.append({"kind": people.KIND, "role": "registered", "extra": {"event": "registered"}})
    rows.rows.append({"kind": people.KIND, "role": "session", "extra": "not a dict"})
    invite_and_register(rows)

    assert [p.id for p in store(rows).people()] == ["ana@acme.example"]

    def unreadable():
        raise RuntimeError("database is locked")

    with caplog.at_level("WARNING", logger="openfactory.identity"):
        snap = PeopleStore(read=unreadable, write=rows.write).snapshot()
    assert snap.people == {} and snap.sessions == {}
    assert "OPENFACTORY_PEOPLE_UNREADABLE" in caplog.text


def test_a_write_that_did_not_land_is_not_a_link():
    rows = Rows()
    rows.durable = False

    assert "not recorded" in store(rows).invite("ana@acme.example", by="roberto")

    rows.durable = True
    token, _ = store(rows).invite("ana@acme.example", by="roberto")
    rows.durable = False
    assert "not recorded" in store(rows).register(token=token, display="A", password=GOOD)


# ── the local row ───────────────────────────────────────────────────────────────────────────────

def test_a_registered_persons_session_is_that_person_via_local():
    rows = Rows()
    s, _ = invite_and_register(rows, groups=(PRODUCT_GROUP,))
    token = s.login("ana@acme.example", GOOD)

    who = LocalIdentity(env={}, store=store(rows)).identify(credential=token, via="panel")

    assert who is not None and who.known
    assert (who.id, who.display, who.via, who.groups) == \
        ("ana@acme.example", "Ana Lima", "local", (PRODUCT_GROUP,))
    assert LocalIdentity(env={}, store=store(rows)).identify(credential="x" * 43) is None


def test_the_environment_rows_are_consulted_before_the_store():
    """Narrow before broad, and the map before the store: an operator's own row must not cost a
    read of a store that may be slow, and must win over it."""
    rows = Rows()
    provider = LocalIdentity(env={"OPENFACTORY_PANEL_TOKENS": "s3cret-a:alice:Alice"},
                             store=store(rows))

    assert provider.identify(credential="s3cret-a").id == "alice"
    assert rows.reads == 0


def test_a_registered_person_closes_the_door_but_an_open_invitation_does_not():
    """An invitation nobody redeemed must not lock the operator out of an open panel before the
    first person can get in; a registered person is a configured credential, like a token row."""
    rows = Rows()
    token, _ = store(rows).invite("ana@acme.example", by="roberto")
    invited = LocalIdentity(env={}, store=store(rows))
    assert invited.open_to_everyone() is True and invited.login_path == ""

    store(rows).register(token=token, display="Ana", password=GOOD)
    registered = LocalIdentity(env={}, store=store(rows))
    assert registered.open_to_everyone() is False and registered.login_path == "/auth/login"


def test_the_conformance_suite_passes_the_local_row_with_a_store():
    from openfactory.conformance.adapters import check_identity

    rows = Rows()
    invite_and_register(rows)
    assert isinstance(LocalIdentity(env={}, store=store(rows)), IdentityProvider)
    assert check_identity(LocalIdentity(env={}, store=store(rows))) == []


# ── the panel ───────────────────────────────────────────────────────────────────────────────────

def test_the_link_lands_on_a_form_and_the_form_registers_and_signs_in(local):
    from openfactory.api.app import app

    token, _ = PeopleStore().invite("ana@acme.example", display="Ana", by="roberto")
    client = TestClient(app)

    page = client.get(f"/auth/register?invite={token}")
    assert page.status_code == 200 and 'value="Ana"' in page.text and "Register" in page.text

    r = client.post("/auth/register", data={"invite": token, "display": "Ana Lima",
                                            "password": GOOD, "again": GOOD},
                    follow_redirects=False)

    assert r.status_code == 303 and r.headers["location"] == "/", r.text
    session = client.cookies["openfactory_token"]
    me = client.get("/api/whoami", headers={"authorization": f"Bearer {session}"}).json()
    assert me["known"] and me["id"] == "ana@acme.example" and me["display"] == "Ana Lima"
    assert me["logout"] == "/auth/logout"
    assert [p.invited_by for p in PeopleStore().people()] == ["roberto"]


def test_a_link_this_deployment_did_not_issue_is_one_404_sentence(local):
    from openfactory.api.app import app

    client = TestClient(app)
    r = client.get("/auth/register?invite=never-issued")
    assert r.status_code == 404 and "not one this deployment issued" in r.text
    assert "people invite" in r.text, "the remedy names the command"

    r = client.post("/auth/register", data={"invite": "never-issued", "display": "X",
                                            "password": GOOD, "again": GOOD})
    assert r.status_code == 404 and "openfactory_token" not in client.cookies


def test_mismatched_and_short_passwords_are_told_on_the_form(local):
    from openfactory.api.app import app

    token, _ = PeopleStore().invite("ana@acme.example", by="roberto")
    client = TestClient(app)

    r = client.post("/auth/register", data={"invite": token, "display": "Ana",
                                            "password": GOOD, "again": GOOD + "!"})
    assert r.status_code == 400 and "differ" in r.text and "<form" in r.text

    r = client.post("/auth/register", data={"invite": token, "display": "Ana",
                                            "password": "short", "again": "short"})
    assert r.status_code == 400 and str(PASSWORD_MIN_CHARS) in r.text
    assert "openfactory_token" not in client.cookies and PeopleStore().pending()


def test_once_somebody_is_registered_the_panel_has_a_sign_in_form_and_is_closed(local):
    from openfactory.api.app import app

    client = TestClient(app)
    assert client.get("/auth/login").status_code == 404
    assert client.get("/api/whoami").status_code == 200, "nothing configured: open"

    invite_and_register(local)

    assert client.get("/auth/login").status_code == 200 and "<form" in client.get("/auth/login").text
    refused = client.get("/api/whoami")
    assert refused.status_code == 401 and refused.json()["login"] == "/auth/login"


def test_the_form_signs_in_a_registered_person_and_refuses_the_rest(local):
    from openfactory.api.app import app

    invite_and_register(local)
    client = TestClient(app)

    r = client.post("/auth/login", data={"id": "ana@acme.example", "password": "not it, not it",
                                         "next": "/p/demo"}, follow_redirects=False)
    assert r.status_code == 401 and "not a registered person" in r.text and "<form" in r.text
    assert "openfactory_token" not in client.cookies

    r = client.post("/auth/login", data={"id": "ana@acme.example", "password": GOOD,
                                         "next": "//evil.example/"}, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/", "next stays on this origin"
    session = client.cookies["openfactory_token"]
    assert client.get("/api/whoami", headers={"authorization": f"Bearer {session}"}) \
        .json()["id"] == "ana@acme.example"


def test_logout_revokes_the_session_in_the_store(local):
    from openfactory.api.app import app

    invite_and_register(local)
    client = TestClient(app)
    client.post("/auth/login", data={"id": "ana@acme.example", "password": GOOD, "next": "/"},
                follow_redirects=False)
    session = client.cookies["openfactory_token"]

    assert client.get("/auth/logout").status_code == 200

    copied = TestClient(app)
    assert copied.get("/api/whoami", headers={"authorization": f"Bearer {session}"}) \
        .status_code == 401, "a copied cookie is dead too"


def test_on_an_sso_deployment_the_registration_link_is_a_404(local, monkeypatch):
    monkeypatch.setenv("OPENFACTORY_IDENTITY", "oidc")
    from openfactory.api.app import app

    assert TestClient(app).get("/auth/register?invite=x").status_code == 404


# ── the shell and the panel's action ───────────────────────────────────────────────────────────

def test_the_shell_prints_the_link_once_and_names_who_vouched(local):
    from typer.testing import CliRunner

    from openfactory.cli import app

    r = CliRunner().invoke(app, ["people", "invite", "ana@acme.example", "--by", "roberto",
                                 "--product", "--display", "Ana"])
    assert r.exit_code == 0, r.output
    assert "/auth/register?invite=" in r.output and "roberto" in r.output
    token = r.output.split("invite=")[1].split()[0]
    assert PeopleStore().invitation_for(token).groups == (PRODUCT_GROUP,)

    listed = CliRunner().invoke(app, ["people", "list"])
    assert listed.exit_code == 0 and "ana@acme.example" in listed.output
    assert "not yet registered" in listed.output and token not in listed.output


def test_a_sink_that_keeps_nothing_is_refused_at_the_shell_by_name(local, monkeypatch):
    from typer.testing import CliRunner

    from openfactory.cli import app

    monkeypatch.setattr(people, "sink_is_durable", _REAL_SINK_IS_DURABLE)
    monkeypatch.setattr("openfactory.observability.registry.metrics_sink_kind", lambda: "null")

    r = CliRunner().invoke(app, ["people", "invite", "ana@acme.example", "--by", "roberto"])

    assert r.exit_code == 1
    assert "OPENFACTORY_METRICS_SINK" in (r.output + str(getattr(r, "stderr", "") or ""))
    assert local.rows == [], "nothing minted, nothing to hand to anybody"


def test_the_panel_action_issues_the_link_vouched_for_by_the_actor(local):
    from openfactory import actions

    spec = actions.CATALOG["people_invite"]
    assert spec.needs_admin and spec.scope == actions.FLOOR

    out = asyncio.run(actions.perform(
        "people_invite", by=actions.Actor(id="roberto", display="Roberto", via="panel",
                                          admin=True),
        person="ana@acme.example", product="yes"))
    assert out.ok, out.message
    assert out.data["link"].startswith("/auth/register?invite=") and out.data["by"] == "roberto"
    assert PeopleStore().pending()[0].groups == (PRODUCT_GROUP,)

    anonymous = asyncio.run(actions.perform(
        "people_invite", by=actions.Actor(id="", display="somebody with the panel token",
                                          via="panel", admin=True),
        person="bia@acme.example"))
    assert not anonymous.ok and anonymous.code == actions.INVALID and "vouched" in anonymous.message


# ── the documents, and the partition nobody may name ───────────────────────────────────────────

def test_the_kind_is_declared_and_no_example_registry_names_the_partition():
    from typing import get_args

    from openfactory.observability.metrics import MetricKind

    assert people.KIND in get_args(MetricKind)
    for example in ROOT.glob("deploy/*.example"):
        assert people.PROJECT not in example.read_text(), example


def test_the_operators_documents_name_the_invitation():
    for path in ("docs/configuration.md", "docs/reference/cli.md", ".env.compose.example"):
        assert "people invite" in (ROOT / path).read_text(), path
    assert "people_invite" in (ROOT / "docs/configuration.md").read_text()
