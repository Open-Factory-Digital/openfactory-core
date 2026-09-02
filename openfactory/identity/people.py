"""People this deployment registered by invitation — the local row's durable half (#33, slice 2).

`local` had one way to know a person: a `token:id:display` row in an environment variable, edited
by whoever can edit the deployment's environment and delivered on the next restart. That is right
for the first operator and wrong for the tenth person: a business analyst does not get an SSM
parameter changed to be able to say yes to a requirement, and a deployment without an identity
provider to plug in (`oidc.py`) still has to be able to name everybody who acts on it.

BY INVITATION, NOT SIGN-UP. An operator issues a one-time link (`openfactory people invite`, or
the `people_invite` action on the panel); the person opens it, chooses a name and a credential,
and becomes a `known` subject `via=local` with WHO VOUCHED FOR THEM recorded on the row. Open
sign-up is refused on the identity module's own rule: an unknown caller who gets a plausible
identity is worse than one who is refused, because the wrong name is written into an audit line
as fact — and an invitation is exactly the act that makes the name somebody's responsibility.

THE SAME SINK THE MESSAGES AND THE STAGING ALREADY USE, for the same reason they use it: it is
the one store the worker and the panel share (`docker-compose.yml` mounts one `metrics.db` into
both; `~/.openfactory/` is each container's own). An invitation minted in the worker's shell has
to be redeemable on the panel, and a person registered on the panel has to be listed from the
shell. Rows are append-only events of kind `person` under one deployment-wide key, and the
current state is FOLDED from them on every read (ADR-0023: derive, don't cache) — an invitation
is pending until a registration names its hash, a session is live until its row expires or a
revocation names it.

PASSWORDS ARE SCRYPT, from the standard library, in the format `approvals.py` already stores the
release passwords in — one hash scheme per platform, not one per door. Tokens (invitations,
sessions) are stored as their SHA-256 and shown ONCE, at minting; a store that held them plain
would make every read of it a credential leak.

NEVER RAISES OUT OF A READ. `identify` calls this on requests and the port's rule is that a
provider closes the door rather than taking it down: a store that cannot be read is an empty
store with one warning, and an empty store identifies nobody.
"""

from __future__ import annotations

import hashlib
import itertools
import logging
import os
import secrets
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime

from openfactory.approvals import _password_matches, hash_password

log = logging.getLogger("openfactory.identity")

#: The record kind, and the deployment-wide partition every row lives under. Not a project: the
#: underscores are the fence, and a project registered under this name would share the partition
#: — `tests/test_a_person_is_invited_not_signed_up.py` holds that no example registry names one.
KIND = "person"
PROJECT = "_deployment_"

#: How long a link stays redeemable. A week: an invitation is sent to a person, and people are
#: away for a week; longer, and a link in an old email is a door somebody forgot they opened.
INVITE_TTL_SECONDS = 7 * 24 * 3600
#: How long a registered person stays logged in. Thirty days, the panel's own cookie horizon.
SESSION_TTL_SECONDS = 30 * 24 * 3600
#: Fewer characters than this is refused at registration. Twelve, because the credential opens a
#: panel that merges code, and a password policy shorter than a passphrase is theatre.
PASSWORD_MIN_CHARS = 12
#: How many rows a fold reads. A deployment with more people than this has outgrown a fold.
READ_LAST = 5000

_SEQ = itertools.count()


@dataclass(frozen=True)
class Person:
    id: str
    display: str = ""
    password_hash: str = ""
    groups: tuple[str, ...] = ()
    invited_by: str = ""
    registered_at: str = ""


@dataclass(frozen=True)
class Invitation:
    id: str
    token_hash: str
    display: str = ""
    groups: tuple[str, ...] = ()
    by: str = ""
    issued_at: str = ""
    expires_at: int = 0


@dataclass(frozen=True)
class Session:
    token_hash: str
    person_id: str
    expires_at: int = 0


@dataclass(frozen=True)
class Snapshot:
    """The state the rows fold to — people by id, pending invitations and live sessions by hash."""

    people: dict[str, Person] = field(default_factory=dict)
    invitations: dict[str, Invitation] = field(default_factory=dict)
    sessions: dict[str, Session] = field(default_factory=dict)


def digest(token: str) -> str:
    return hashlib.sha256(str(token or "").encode("utf-8")).hexdigest()


# ── the sink ────────────────────────────────────────────────────────────────────────────────────

def _read_rows() -> list[dict]:
    """Every `person` row, oldest first. Empty — and one WARNING — when the store will not
    answer, because this runs inside `identify`."""
    from openfactory.observability.query import StoreUnreadable, records_of_kind

    try:
        return records_of_kind(PROJECT, KIND, limit=READ_LAST)
    except StoreUnreadable as exc:
        log.warning("OPENFACTORY_PEOPLE_UNREADABLE the people store could not be read (%s) — "
                    "nobody registered by invitation can be identified until it can", exc)
        return []


def _write_row(event: str, extra: dict, *, expires_at: int | None = None) -> bool:
    """One event row. Returns whether it LANDED — the null sink says False, honestly, and a
    caller that minted a link must not hand it to a person when nothing recorded it."""
    from openfactory.observability.metrics import MetricRecord
    from openfactory.runtime.temporal.activities import _metrics_sink

    return bool(_metrics_sink().record(MetricRecord(
        project=PROJECT, kind=KIND, role=event,
        ticket=f"{event}.{os.getpid()}.{next(_SEQ)}",
        ts=datetime.now(UTC).isoformat(),
        expires_at=expires_at,
        extra={"event": event, **extra},
    )))


def sink_is_durable() -> str:
    """`""` when this deployment's sink keeps what it is given, else one sentence naming the sink
    that does not — asked BEFORE an invitation is minted, so the operator is told at the shell
    and not by a person whose link answers 404."""
    from openfactory.observability.registry import metrics_sink_kind

    kind = metrics_sink_kind()
    if kind in ("null", "memory"):
        return (f"the metrics sink is `{kind}`, which keeps nothing between processes — people "
                f"registered by invitation live in that store. Set OPENFACTORY_METRICS_SINK=sqlite "
                f"(the compose default) where the worker and the panel run")
    return ""


# ── the store ───────────────────────────────────────────────────────────────────────────────────

class PeopleStore:
    """Registered people, pending invitations and live sessions, folded from the sink."""

    def __init__(self, *, read=None, write=None, now=None) -> None:
        self._read = read or _read_rows
        self._write = write or _write_row
        self._now = now or time.time
        #: The fold, once per store — a provider is built per request and asks three questions
        #: of it (is anybody registered, where is the login, whose session is this); three
        #: reads of the same rows would be three queries for one answer.
        self._snap: Snapshot | None = None

    def _record(self, event: str, extra: dict, *, expires_at: int | None = None) -> bool:
        self._snap = None
        return bool(self._write(event, extra, expires_at=expires_at))

    # ── reads ──

    def snapshot(self) -> Snapshot:
        if self._snap is not None:
            return self._snap
        snap = Snapshot()
        now = int(self._now())
        try:
            rows = self._read()
        except Exception as exc:  # noqa: BLE001 — a store that cannot be read is an empty store
            log.warning("OPENFACTORY_PEOPLE_UNREADABLE %s", exc)
            return snap
        for row in rows:
            extra = row.get("extra") if isinstance(row, dict) else None
            if not isinstance(extra, dict):
                continue
            event = str(extra.get("event") or row.get("role") or "")
            try:
                self._fold(snap, event, extra, now)
            except (KeyError, TypeError, ValueError) as exc:
                # A MALFORMED ROW COSTS ONLY ITSELF (the messages store's rule): one bad row must
                # not blind the panel to every person registered after it.
                log.warning("OPENFACTORY_PEOPLE_BAD_ROW ignoring a %r row (%s)", event, exc)
        self._snap = snap
        return snap

    @staticmethod
    def _fold(snap: Snapshot, event: str, x: dict, now: int) -> None:
        if event == "invited":
            inv = Invitation(id=str(x["id"]), token_hash=str(x["token_hash"]),
                             display=str(x.get("display") or ""),
                             groups=tuple(str(g) for g in (x.get("groups") or ())),
                             by=str(x.get("by") or ""), issued_at=str(x.get("issued_at") or ""),
                             expires_at=int(x.get("expires_at") or 0))
            if inv.expires_at > now and inv.id not in snap.people:
                snap.invitations[inv.token_hash] = inv
        elif event == "registered":
            person = Person(id=str(x["id"]), display=str(x.get("display") or x["id"]),
                            password_hash=str(x.get("password_hash") or ""),
                            groups=tuple(str(g) for g in (x.get("groups") or ())),
                            invited_by=str(x.get("by") or ""),
                            registered_at=str(x.get("registered_at") or ""))
            snap.people[person.id] = person
            snap.invitations.pop(str(x.get("token_hash") or ""), None)
            for h, inv in list(snap.invitations.items()):
                if inv.id == person.id:
                    del snap.invitations[h]
        elif event == "session":
            s = Session(token_hash=str(x["token_hash"]), person_id=str(x["id"]),
                        expires_at=int(x.get("expires_at") or 0))
            if s.expires_at > now:
                snap.sessions[s.token_hash] = s
        elif event == "revoked":
            snap.sessions.pop(str(x.get("token_hash") or ""), None)

    def people(self) -> list[Person]:
        return sorted(self.snapshot().people.values(), key=lambda p: p.id)

    def pending(self) -> list[Invitation]:
        return sorted(self.snapshot().invitations.values(), key=lambda i: i.issued_at)

    def has_people(self) -> bool:
        return bool(self.snapshot().people)

    def invitation_for(self, token: str) -> Invitation | None:
        """The pending invitation this link carries, or None — used, expired, or never issued
        all answer the same, on purpose: which one it was is not the link-holder's business."""
        if not str(token or "").strip():
            return None
        return self.snapshot().invitations.get(digest(token.strip()))

    def session_of(self, token: str) -> Person | None:
        """Who holds this session token, or None. Constant-time on the hash: the lookup is by
        digest, and a digest comparison leaks nothing about the token."""
        if not str(token or "").strip():
            return None
        snap = self.snapshot()
        session = snap.sessions.get(digest(token.strip()))
        if session is None:
            return None
        return snap.people.get(session.person_id)

    # ── writes ──

    def invite(self, ident: str, *, display: str = "", groups: tuple[str, ...] = (),
               by: str = "") -> tuple[str, Invitation] | str:
        """Mint a one-time link's token. `(token, invitation)` — the token is shown to the
        operator ONCE and stored only as its hash — or a sentence saying why not."""
        ident = str(ident or "").strip()
        if not ident or any(c.isspace() for c in ident):
            return "a person's id is one word — an email or a handle, spelled the way the " \
                   "project's `admins` will spell it"
        if not str(by or "").strip():
            return "an invitation records who vouched for the person, and nobody did"
        snap = self.snapshot()
        if ident in snap.people:
            return f"{ident} is already registered"
        token = secrets.token_urlsafe(32)
        now = int(self._now())
        inv = Invitation(id=ident, token_hash=digest(token), display=str(display or "").strip(),
                         groups=tuple(groups), by=str(by).strip(),
                         issued_at=datetime.fromtimestamp(now, UTC).isoformat(),
                         expires_at=now + INVITE_TTL_SECONDS)
        landed = self._record("invited", {
            "id": inv.id, "token_hash": inv.token_hash, "display": inv.display,
            "groups": list(inv.groups), "by": inv.by, "issued_at": inv.issued_at,
            "expires_at": inv.expires_at,
        }, expires_at=inv.expires_at)
        if not landed:
            return "the invitation was not recorded — the metrics sink kept nothing, so a link " \
                   "would answer 404 to the person who opens it"
        return token, inv

    def register(self, *, token: str, display: str, password: str) -> Person | str:
        """Redeem an invitation: the person chooses a name and a credential. A `Person`, or why
        not — in one sentence the form can show."""
        inv = self.invitation_for(token)
        if inv is None:
            return "this invitation is not one this deployment issued, was already used, or " \
                   "has expired — ask the operator for a new link"
        if len(str(password or "")) < PASSWORD_MIN_CHARS:
            return f"the password must be at least {PASSWORD_MIN_CHARS} characters"
        person = Person(id=inv.id, display=str(display or "").strip() or inv.display or inv.id,
                        password_hash=hash_password(password), groups=inv.groups,
                        invited_by=inv.by,
                        registered_at=datetime.fromtimestamp(int(self._now()), UTC).isoformat())
        landed = self._record("registered", {
            "id": person.id, "display": person.display, "password_hash": person.password_hash,
            "groups": list(person.groups), "by": person.invited_by,
            "registered_at": person.registered_at, "token_hash": inv.token_hash,
        })
        if not landed:
            return "the registration was not recorded — nothing durable is configured to keep it"
        return person

    def login(self, ident: str, password: str) -> str:
        """A session token for this person, or `""`. One answer for an unknown id and a wrong
        password — which of the two it was is not the caller's business."""
        person = self.snapshot().people.get(str(ident or "").strip())
        if person is None or not person.password_hash:
            # burn the same time an existing person would, so the two are not told apart
            hash_password("x")
            return ""
        if not _password_matches(str(password or ""), person.password_hash):
            return ""
        return self.open_session(person)

    def open_session(self, person: Person) -> str:
        token = secrets.token_urlsafe(32)
        expires = int(self._now()) + SESSION_TTL_SECONDS
        landed = self._record("session", {"id": person.id, "token_hash": digest(token),
                                         "expires_at": expires}, expires_at=expires)
        return token if landed else ""

    def revoke(self, token: str) -> bool:
        """End a session. True when a live one was named; a token nobody holds is a no-op."""
        if self.session_of(token) is None:
            return False
        return bool(self._record("revoked", {"token_hash": digest(str(token).strip())}))
