"""A preview of the product, assembled for one change, before its pull request merges (ADR-0050).

Everything here is docker-free and engine-free, so the three processes that meet over a preview —
the worker that assembles it, the reaper that ends it and the panel that routes to it — agree on one
set of names without importing each other:

- the NAMES a preview wears: its unit, its compose project, its edge network, the host of each
  exposed service;
- how a request's `Host:` is read back into one service of one unit;
- the KEY that lets a person in, and the cookie it becomes;
- the RECORD the worker writes and the panel reads, because the panel holds no docker socket.

THE UNIT (D1). A preview is keyed by what the person asked for: a card (`34`) or a requirement
(`req0012`). Every name below is built from the project's slug and that token.

WHY HOSTS OF THEIR OWN, AND NEVER A PATH UNDER THE PANEL (D7). A preview runs code the agent wrote,
and the panel's credential is readable by any script on the panel's own origin — on plain http the
cookie is not HttpOnly and the page keeps a copy in localStorage. Served under the panel's address,
the preview's JavaScript would read the credential of whoever opened it and could act as that
person. A different PORT on the same host does not help: browsers send a host's cookies to every
port. A different HOST does, and each exposed service also gets the root path it was written for.
Every exposed service is `<service>--<project>--<unit>.<domain>`: one DNS label, so one wildcard
record covers them all, split unambiguously on `--` because a slug never holds two dashes in a row.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import os
import re
import secrets
import time
from datetime import UTC, datetime

from pydantic import BaseModel, ConfigDict

log = logging.getLogger("openfactory.preview")

#: How long the key in a link is good for. MINUTES: it travels in a URL, and a URL lives on in
#: access logs and browser history. The cookie it is exchanged for lasts as long as the preview.
LINK_TTL_SECONDS = 10 * 60

#: The door on a preview's host that turns a key into a cookie. Namespaced so it cannot shadow a
#: route of the application being previewed.
ENTER_PATH = "/__openfactory_preview/enter"

#: Every cookie a preview's key becomes starts with this. PER UNIT, so two open previews never
#: overwrite each other's — and matched by PREFIX wherever the platform's own cookies are kept away
#: from an application, because an exact name would let every per-unit cookie slip past.
COOKIE_PREFIX = "openfactory_preview_"

#: The metrics-sink kind the worker records a preview under, and the panel reads it by.
KIND = "preview"

#: The states a preview's record moves through. `offered`: the pull request waits for a person
#: and a preview can be started. `starting`: somebody pressed start. `live`: it is up. `failed`: it
#: could not be assembled or it stopped, and says why. `ended`: it was taken down, and says why.
OFFERED, STARTING, LIVE, FAILED, ENDED = "offered", "starting", "live", "failed", "ended"

_SLUG = r"[a-z0-9]+(?:-[a-z0-9]+)*"
#: A unit's token: a card number, or a requirement's number as `req` + four digits.
UNIT_RE = re.compile(r"^(?:[0-9]+|req[0-9]{4})$")
_HOST_RE = re.compile(rf"^(?P<service>{_SLUG})--(?P<slug>{_SLUG})--(?P<unit>[0-9]+|req[0-9]{{4}})$")


def slug(text: str) -> str:
    """`text` as a DNS-safe lowercase slug with no double dash. Project and service names are
    free text."""
    return re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")


def card_of(ticket_id: str) -> str:
    """The card NUMBER a ticket id carries (`#12`, `12`, `acme#12` → `12`), or "" when it has none.
    A ticket whose id holds no number gets no preview rather than a made-up address."""
    found = re.findall(r"[0-9]+", str(ticket_id or ""))
    return found[-1] if found else ""


def unit_name(project: str, token: str) -> str:
    """`<project slug>--<unit token>` — what a key opens and a cookie is named after."""
    return f"{slug(project) or 'project'}--{token}"


def compose_project(project: str, token: str) -> str:
    """The compose project a preview runs as. Its containers, networks and volumes are namespaced
    by it, which is what keeps two previews apart on one daemon."""
    return f"openfactory-pv-{slug(project) or 'project'}-{token}"


def edge_network(project: str, token: str) -> str:
    """The one network a unit's exposed services share with the panel — per unit, so no preview
    can resolve or reach another's."""
    return f"{compose_project(project, token)}-edge"


#: The longest a service's part of a host label may be; the project's slug gets the rest.
_SERVICE_MAX = 20


def host_label(project: str, token: str, service: str) -> str:
    """The first DNS label of one exposed service's host — and its alias on the unit's edge
    network, which is how the panel reaches it: the router's target is DERIVED from the name a
    person opened, never read from a record (D7).

    AT MOST 63 CHARACTERS, AND THE UNIT IS NEVER THE PART THAT IS CUT. A long project name is
    shortened in the middle of the label, where only the slug is — cutting the end would drop the
    unit, and a host without its unit names no preview at all."""
    svc = (slug(service) or "service")[:_SERVICE_MAX].rstrip("-") or "s"
    room = 63 - len(svc) - len(token) - 4
    proj = (slug(project) or "project")[: max(1, room)].rstrip("-") or "p"
    return f"{svc}--{proj}--{token}"


def cookie_name(project: str, token: str) -> str:
    return f"{COOKIE_PREFIX}{slug(project) or 'project'}_{token}"


def domain() -> str:
    """The domain previews are served under (`OPENFACTORY_PREVIEW_DOMAIN`), or "" when previews
    are not exposed on this deployment."""
    return (os.environ.get("OPENFACTORY_PREVIEW_DOMAIN") or "").strip().strip(".").lower()


class Host(BaseModel):
    """What a preview host names: one service of one unit."""

    model_config = ConfigDict(frozen=True)

    label: str
    service: str
    slug: str
    unit: str


def host_of(host: str, preview_domain: str) -> Host | None:
    """The preview service a request's `Host:` names, or None when it names none.

    Exactly one label in front of the domain, in the `<service>--<project>--<unit>` shape — so the
    panel's own host can never be read as a preview, whatever it is called."""
    if not preview_domain:
        return None
    name = (host or "").split(":", 1)[0].strip().lower().rstrip(".")
    suffix = f".{preview_domain}"
    if not name.endswith(suffix):
        return None
    label = name[: -len(suffix)]
    m = _HOST_RE.fullmatch(label)
    if not m:
        return None
    return Host(label=label, service=m.group("service"), slug=m.group("slug"),
                unit=m.group("unit"))


def under_domain(host: str, preview_domain: str) -> bool:
    """Whether a `Host:` is the preview domain or anything under it — the hosts the panel never
    serves, whether or not they name a preview."""
    name = (host or "").split(":", 1)[0].strip().lower().rstrip(".")
    return bool(preview_domain) and (name == preview_domain or name.endswith(f".{preview_domain}"))


def url_for(label: str, *, scheme: str, preview_domain: str, port: int | None = None,
            path: str = "/") -> str:
    default = {"http": 80, "https": 443}.get(scheme)
    suffix = f":{port}" if port and port != default else ""
    return f"{scheme}://{label}.{preview_domain}{suffix}{path}"


# ── the key ──────────────────────────────────────────────────────────────────────────────────────

_PROCESS_SECRET = secrets.token_bytes(32)


def _secret() -> bytes:
    """`OPENFACTORY_PREVIEW_SECRET`, else a secret born with this process. The fallback only means
    a restart sends an open preview's viewer back through the panel."""
    configured = (os.environ.get("OPENFACTORY_PREVIEW_SECRET") or "").strip()
    return configured.encode() if configured else _PROCESS_SECRET


def _mac(project: str, token: str, expires: int) -> str:
    """Over the EXACT project name, not its slug: two projects whose slugs collide never share a
    key, whatever the registry let through."""
    return hmac.new(_secret(), f"v1|{project}|{token}|{expires}".encode(),
                    hashlib.sha256).hexdigest()


def mint(project: str, token: str, *, expires: int) -> str:
    """A key that opens every exposed service of exactly one unit of one project until
    `expires`."""
    return f"v1.{token}.{int(expires)}.{_mac(project, token, int(expires))}"


def admits(key: str, *, project: str, token: str, now: float | None = None) -> bool:
    """Whether `key` opens this unit of this project right now. A key for another unit, or the
    same unit number of another project, opens nothing."""
    parts = (key or "").split(".")
    if len(parts) != 4 or parts[0] != "v1" or parts[1] != token or not parts[2].isdigit():
        return False
    expires = int(parts[2])
    if expires < (time.time() if now is None else now):
        return False
    return hmac.compare_digest(parts[3], _mac(project, token, expires))


def expiry_of(key: str) -> int:
    parts = (key or "").split(".")
    return int(parts[2]) if len(parts) == 4 and parts[2].isdigit() else 0


# ── the record ───────────────────────────────────────────────────────────────────────────────────


class Preview(BaseModel):
    """What the worker records about one unit's preview, and the panel reads.

    Written as one `MetricRecord` row PER CARD of the unit at every state change, with `ticket` a
    card number (every other reader of the sink treats that column as one) and the unit in `extra` —
    so the card → unit index IS the record."""

    model_config = ConfigDict(frozen=True)

    project: str
    unit: str
    kind: str = "card"
    cards: tuple[str, ...] = ()
    state: str
    #: exposed service → its port inside its container
    services: dict[str, int] = {}
    #: exposed service → "healthy" (its healthcheck passed) | "started" (it has none)
    health: dict[str, str] = {}
    from_change: dict[str, bool] = {}
    commits: dict[str, str] = {}
    images: dict[str, str] = {}
    base_moved: dict[str, str] = {}
    pr_urls: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()
    missing: tuple[str, ...] = ()
    stale: tuple[str, ...] = ()
    proposal_url: str = ""
    why: str = ""
    log_dir: str = ""
    started_by: str = ""
    expires_at: int = 0
    started_at: int = 0
    ended_at: int = 0

    @property
    def live(self) -> bool:
        return self.state == LIVE

    def expired(self, now: float | None = None) -> bool:
        return self.expires_at <= (time.time() if now is None else now)


def record(p: Preview) -> bool:
    """Write the record, one row per card of the unit. Best-effort and said: a preview the panel
    cannot see is a log line, never a failed start."""
    try:
        from openfactory.observability.metrics import MetricRecord
        from openfactory.observability.registry import deployment_metrics_sink

        sink = deployment_metrics_sink()
        now = datetime.now(UTC).isoformat()
        extra = p.model_dump(mode="json")
        ok = True
        for card in p.cards or (p.unit,):
            ok = bool(sink.record(MetricRecord(
                project=p.project, ticket=str(card), ts=now, kind=KIND, role=p.state,
                state=p.state, extra=extra))) and ok
        return ok
    except Exception as exc:  # noqa: BLE001
        log.warning("[%s] could not record the preview of %s as %s (%s)", p.project, p.unit,
                    p.state, exc)
        return False


def latest(project: str, token: str) -> Preview | None:
    """The newest record of one unit's preview; None when there never was one. The store is
    append-only, so the newest row is the truth."""
    from openfactory.observability.query import records_of_kind

    rows = [r for r in records_of_kind(project, KIND)
            if str((r.get("extra") or {}).get("unit", "")) == str(token)]
    if not rows:
        return None
    row = max(rows, key=lambda r: str(r.get("ts", "")))
    try:
        return Preview.model_validate(row.get("extra") or {})
    except ValueError:
        log.warning("[%s] the preview record of %s could not be read back", project, token)
        return None


def serving(host: Host, projects) -> tuple[Preview, int] | None:
    """The live, unexpired preview a host names, and the port of the service it names — looked up
    among `projects`' records.

    THE HOST IS NEVER DECODED BACK INTO A PROJECT NAME. Slugs collide (`Acme` and `acme` share
    one), so the host only narrows which projects to read and the RECORD says which one it is. Two
    live previews claiming one host is ambiguity, and ambiguity serves nothing."""
    found: list[tuple[Preview, int]] = []
    for project in projects:
        name = getattr(project, "name", project)
        if host_label(name, host.unit, host.service) != host.label:
            continue
        try:
            p = latest(name, host.unit)
        except Exception as exc:  # noqa: BLE001 — an unreadable store serves nothing
            log.warning("could not read the preview records of %s (%s)", name, exc)
            continue
        if p is None or not p.live or p.expired() or p.project != name:
            continue
        port = next((port for svc, port in p.services.items()
                     if host_label(name, host.unit, svc) == host.label), None)
        if port:
            found.append((p, port))
    return found[0] if len(found) == 1 else None
