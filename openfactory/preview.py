"""A card's preview: the validated box, served, before its pull request merges (ADR-0050).

Everything here is docker-free and engine-free, so the three processes that meet over a preview —
the worker that starts it, the reaper that ends it and the panel that routes to it — agree on one
set of names without importing each other:

- the NAMES a preview wears on the daemon (container, image, labels);
- the HOST it is served on, and how a request's `Host:` is read back into one;
- the TOKEN that lets a person in, and how it is checked;
- the RECORD the worker writes and the panel reads, because the panel holds no docker socket.

WHY A HOST OF ITS OWN, AND NEVER A PATH UNDER THE PANEL (the ADR-0050 amendment). A preview runs
code the agent wrote. The panel's credential is deliberately readable by any script on the panel's
origin — `openfactory_token` is not HttpOnly, and the page keeps a copy in localStorage
(`api/app.py`, the OIDC callback says so in its own words). Served at `/p/<project>/card/<n>/…`,
the preview's own JavaScript would read the credential of whoever opened it and could act as that
person: answer a gate, approve a merge. A different PORT on the same host does not help either —
browsers send a host's cookies to every port. A different HOST does: the panel's cookie is
host-only, so it never reaches `<label>.<preview domain>`, and a script there cannot read the
panel's storage. The app also gets the root path it was written for, rather than a sub-path most
front ends cannot live under.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import os
import re
import secrets
import time
from dataclasses import dataclass
from datetime import UTC, datetime

log = logging.getLogger("openfactory.preview")

#: The label every preview container carries, so the reaper can find them all with one filter and
#: never mistake a job's box for one.
LABEL = "openfactory.preview"
LABEL_PROJECT = "openfactory.preview.project"
LABEL_CARD = "openfactory.preview.card"
LABEL_EXPIRES = "openfactory.preview.expires"
LABEL_CLONE = "openfactory.preview.clone"
LABEL_PR = "openfactory.preview.pr"

#: How long a preview lives when the registry says nothing (ADR-0050 D5). A day: long enough for a
#: person to find the link the morning after, short enough that a forgotten one is not a server.
DEFAULT_TTL_HOURS = 24
#: The longest a registry may ask for. A preview is a look before a merge, not an environment, and
#: a week-long one is a staging server nobody decided to run.
MAX_TTL_HOURS = 24 * 7

#: How long one entry token is good for. Short, because it travels in a URL; the cookie it is
#: exchanged for lasts no longer than the preview itself.
TOKEN_TTL_SECONDS = 8 * 3600

#: The door on the preview's host that turns a token into a cookie. Namespaced so it cannot shadow
#: a route of the application being previewed.
ENTER_PATH = "/__openfactory_preview/enter"
#: The cookie on the PREVIEW host. Never the panel's `openfactory_token`.
COOKIE = "openfactory_preview"

#: The metrics-sink kind the worker records a preview under, and the panel reads it by.
KIND = "preview"

#: What a host label is made of: the project's slug, two dashes, the card number. DNS labels are
#: at most 63 characters of `[a-z0-9-]`.
_LABEL_RE = re.compile(r"^(?P<slug>[a-z0-9](?:[a-z0-9-]*[a-z0-9])?)--(?P<card>[0-9]+)$")


def slug(text: str) -> str:
    """`text` as a DNS-safe lowercase slug. Registry project names are free text."""
    return re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")


def card_of(ticket_id: str) -> str:
    """The card NUMBER a ticket id carries (`#12`, `12`, `acme#12` → `12`), or "" when it has none.

    A preview is addressed by card number because that is what the panel, the board and a person
    say. A ticket whose id holds no number (a local tracker's opaque id) gets no preview rather
    than a made-up address."""
    found = re.findall(r"[0-9]+", str(ticket_id or ""))
    return found[-1] if found else ""


def container_name(project: str, card: str) -> str:
    """The preview's container. NOT the job box's name (`openfactory-<project>-<issue>`), and that
    is the point: a CI repair or a re-review of the same card prepares a box under the job's name
    and removes whatever wears it as debris (#165) — a preview under that name would be killed by
    the next repair of its own card."""
    safe = re.sub(r"[^a-zA-Z0-9_.-]+", "-", project or "").strip("-") or "project"
    return f"openfactory-preview-{safe}-{card}"


def image_name(project: str, card: str) -> str:
    """The frozen filesystem of the validated box. Image references must be lowercase."""
    return f"openfactory-preview/{slug(project) or 'project'}:{card}"


def host_label(project: str, card: str) -> str:
    """The first DNS label of the preview's host: `<project slug>--<card>`, at most 63 chars."""
    label = f"{slug(project) or 'project'}"[: 63 - len(card) - 2].rstrip("-")
    return f"{label}--{card}"


def domain() -> str:
    """The domain previews are served under (`OPENFACTORY_PREVIEW_DOMAIN`), or "" when previews
    are not exposed on this deployment. `preview.localhost` works on one machine with no DNS at
    all: browsers resolve every `*.localhost` to the loopback."""
    return (os.environ.get("OPENFACTORY_PREVIEW_DOMAIN") or "").strip().strip(".").lower()


def label_of_host(host: str, preview_domain: str) -> str:
    """The preview label a request's `Host:` names, or "" when it names no preview.

    Exactly one label in front of the domain, in the `<slug>--<card>` shape — so the panel's own
    host can never be read as a preview, whatever it is called."""
    if not preview_domain:
        return ""
    name = (host or "").split(":", 1)[0].strip().lower().rstrip(".")
    suffix = f".{preview_domain}"
    if not name.endswith(suffix):
        return ""
    label = name[: -len(suffix)]
    return label if _LABEL_RE.fullmatch(label) else ""


def url_for(label: str, *, scheme: str, preview_domain: str, port: int | None = None,
            path: str = "/") -> str:
    default = {"http": 80, "https": 443}.get(scheme)
    suffix = f":{port}" if port and port != default else ""
    return f"{scheme}://{label}.{preview_domain}{suffix}{path}"


# ── the token ────────────────────────────────────────────────────────────────────────────────────

_PROCESS_SECRET = secrets.token_bytes(32)


def _secret() -> bytes:
    """`OPENFACTORY_PREVIEW_SECRET`, else a secret born with this process.

    The fallback is safe and merely inconvenient: only the panel mints and checks tokens, so a
    restart makes every open preview ask its viewer to come back through the panel — it never
    makes a token valid that should not be."""
    configured = (os.environ.get("OPENFACTORY_PREVIEW_SECRET") or "").strip()
    return configured.encode() if configured else _PROCESS_SECRET


def _mac(label: str, expires: int) -> str:
    return hmac.new(_secret(), f"v1|{label}|{expires}".encode(), hashlib.sha256).hexdigest()


def mint(label: str, *, expires: int) -> str:
    """A token that opens exactly one preview host until `expires` (epoch seconds)."""
    return f"v1.{label}.{int(expires)}.{_mac(label, int(expires))}"


def admits(token: str, *, label: str, now: float | None = None) -> bool:
    """Whether `token` opens `label` right now. A token for another card opens nothing."""
    parts = (token or "").split(".")
    if len(parts) != 4 or parts[0] != "v1" or parts[1] != label or not parts[2].isdigit():
        return False
    expires = int(parts[2])
    if expires < (time.time() if now is None else now):
        return False
    return hmac.compare_digest(parts[3], _mac(label, expires))


def expiry_of(token: str) -> int:
    parts = (token or "").split(".")
    return int(parts[2]) if len(parts) == 4 and parts[2].isdigit() else 0


# ── the record ───────────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Preview:
    """What the panel knows about one card's preview."""

    project: str
    card: str
    label: str
    container: str
    port: int
    expires_at: int
    pr_url: str = ""
    live: bool = True
    why: str = ""

    def expired(self, now: float | None = None) -> bool:
        return self.expires_at <= (time.time() if now is None else now)


def _write(project: str, card: str, *, state: str, extra: dict) -> bool:
    try:
        from openfactory.observability.metrics import MetricRecord
        from openfactory.observability.registry import deployment_metrics_sink

        return bool(deployment_metrics_sink().record(MetricRecord(
            project=project, ticket=card, ts=datetime.now(UTC).isoformat(), kind=KIND,
            role=state, state=state, extra=extra)))
    except Exception as exc:  # noqa: BLE001 — a preview the panel cannot see is said, not raised
        log.warning("[%s] could not record the preview of #%s as %s (%s)", project, card, state,
                    exc)
        return False


def record_live(p: Preview) -> bool:
    return _write(p.project, p.card, state="live", extra={
        "label": p.label, "container": p.container, "port": p.port,
        "expires_at": p.expires_at, "pr_url": p.pr_url})


def record_ended(project: str, card: str, why: str) -> bool:
    return _write(project, card, state="ended", extra={"why": why})


def latest(project: str, card: str) -> Preview | None:
    """The newest record of one card's preview, live or ended; None when there never was one.

    The store is append-only, so the newest row is the truth — a preview replaced by a later run
    of the same card is the later row, and one the reaper ended is an `ended` row after it."""
    from openfactory.observability.query import records_of_kind

    rows = [r for r in records_of_kind(project, KIND) if str(r.get("ticket", "")) == str(card)]
    if not rows:
        return None
    row = max(rows, key=lambda r: str(r.get("ts", "")))
    extra = row.get("extra") or {}
    if str(row.get("state") or row.get("role")) != "live":
        return Preview(project=project, card=str(card), label="", container="", port=0,
                       expires_at=0, live=False, why=str(extra.get("why", "")))
    try:
        return Preview(project=project, card=str(card), label=str(extra.get("label", "")),
                       container=str(extra.get("container", "")),
                       port=int(extra.get("port") or 0),
                       expires_at=int(extra.get("expires_at") or 0),
                       pr_url=str(extra.get("pr_url", "")))
    except (TypeError, ValueError):
        return None


def serving(label: str, projects) -> Preview | None:
    """The live, unexpired preview a host label names, looked up among `projects`' records.

    THE LABEL IS NEVER DECODED BACK INTO A PROJECT NAME. Slugs collide (`Acme` and `acme` share
    one), so the label only narrows which projects to read, and the RECORD says which one it is.
    Two live previews claiming one label is ambiguity, and ambiguity serves nothing."""
    m = _LABEL_RE.fullmatch(label or "")
    if not m:
        return None
    found: list[Preview] = []
    for project in projects:
        name = getattr(project, "name", project)
        if host_label(name, m.group("card")) != label:
            continue
        try:
            p = latest(name, m.group("card"))
        except Exception as exc:  # noqa: BLE001 — an unreadable store serves nothing
            log.warning("could not read the preview records of %s (%s)", name, exc)
            continue
        # THE TARGET IS DERIVED, NEVER READ: the panel is about to make a request to the host a
        # record names, so the record must name the container this card's preview can only be.
        if (p is not None and p.live and p.label == label and not p.expired()
                and p.container == container_name(name, m.group("card"))):
            found.append(p)
    return found[0] if len(found) == 1 else None
