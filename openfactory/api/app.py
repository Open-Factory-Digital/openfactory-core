"""The web panel — observability + management over the job journal.

Not a new system: it reads the registry (projects) and the JobEvent journal (what
each job is doing, live) and triggers runs into the worker. The self-contained HTML
panel is served at `/`. Run with `openfactory serve`.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import re
import time
from dataclasses import dataclass
from html import escape as _h
from pathlib import Path
from typing import NamedTuple
from urllib.parse import parse_qsl, quote, urlencode

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, Header, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import (
    HTMLResponse,
    JSONResponse,
    PlainTextResponse,
    RedirectResponse,
    Response,
    StreamingResponse,
)
from pydantic import BaseModel

from openfactory import actions, doors
from openfactory.contracts.project import Project, ProviderRef
from openfactory.floor import reading as _floor_reading
from openfactory.floor.reading import INTAKE_TTL_S as _INTAKE_TTL_S
from openfactory.identity import oidc as _sso
from openfactory.identity.base import REGISTER_PATH as _REGISTER_PATH
from openfactory.paths import events_file, project_log_dir
from openfactory.registry import ProjectRegistry

log = logging.getLogger("openfactory.panel")

def _load_environment() -> None:
    """Pick up `.env` WHEN THE PANEL SERVES, never when it is imported.

    This was a bare `load_dotenv()` at module scope — the exact defect `openfactory/cli.py` already
    carries a docstring about, surviving in a second entry point. Importing this module mutated
    the whole process's environment, and the harness axis is what made it visible again: resolving
    a project's model gave `opus` from a `.env` that nothing in the caller had asked for, so the
    cockpit reported a model no registry had chosen and a route derived from it.

    Worse in a test run than in production. `pytest-randomly` ordering a test that imports the
    panel ahead of others hands them live `OPENFACTORY_GH_APP_*` credentials for a real client's
    repository — write-capable, on some seeds and not others.

    A library module must not have side effects on import. `serve()` is the entry point.
    """
    load_dotenv()

# deployed panel: Secrets Manager delivers the bot App key as CONTENT — materialize it
# so token minting (forge reads) works, same as the worker/task do.
if os.environ.get("OPENFACTORY_GH_APP_KEY_CONTENT") and not os.environ.get("OPENFACTORY_GH_APP_KEY"):
    import tempfile as _tmp

    from openfactory.runtime.boxed_job import materialize_app_key

    materialize_app_key(dict(os.environ), dest_dir=Path(_tmp.mkdtemp(prefix="openfactory-panel-")))

#: What this half of the deployment calls itself when it announces its build (#135). Named here
#: because two places must agree on the spelling — `cli serve`, which announces it, and
#: `_build_report`, which must not compare this process against its own announcement and conclude
#: the deployment agrees with itself.
PANEL_ROLE = "panel"

app = FastAPI(title=os.environ.get("OPENFACTORY_PLATFORM_NAME", "OpenFactory"))

# ── SOMEBODY ELSE'S DASHBOARD ───────────────────────────────────────────────────────────────────
#
# CLOSED UNTIL A DEPLOYMENT SAYS OTHERWISE, and the default is the point. This API is now the way a
# customer builds their own panel or wires the floor into something else (#144) — and without CORS
# that is impossible: a browser on another origin cannot read a single one of these routes.
#
# But "allow everything" would mean any page a logged-in operator happens to visit can read their
# whole factory using the cookie in their browser, so the safe default is no cross-origin at all
# and an explicit list to open it. `OPENFACTORY_PANEL_ORIGINS=https://ops.acme.com,https://…`.
#
# `*` IS REFUSED WITH CREDENTIALS ON PURPOSE — the spec forbids the combination, and a deployment
# that asked for both would otherwise get a config that silently does not do what it reads like.
_ORIGINS = [o.strip() for o in os.environ.get("OPENFACTORY_PANEL_ORIGINS", "").split(",")
            if o.strip()]
if _ORIGINS:
    from fastapi.middleware.cors import CORSMiddleware

    if "*" in _ORIGINS:
        logging.getLogger("openfactory.panel").warning(
            "OPENFACTORY_PANEL_ORIGINS contains `*`, which browsers refuse alongside credentials "
            "— naming the origins explicitly is the only form that works")
    app.add_middleware(CORSMiddleware, allow_origins=_ORIGINS, allow_credentials=True,
                       allow_methods=["GET", "POST"], allow_headers=["authorization",
                                                                     "content-type"])


@app.middleware("http")
async def _panel_gate(request: Request, call_next):
    """Gate EVERY /api/* route on a credential the deployment configured — reads included.

    THE SECOND GATE C-26 MISSED, found by the adversarial review of that very commit. The
    identity work taught `require_auth` about per-person tokens and never touched this
    middleware, which still compared against `OPENFACTORY_PANEL_TOKEN` alone. Two live failures:
    mid-migration (both variables set) a personal token was 401'd on every route before
    `require_auth` ever ran; migrated (per-person tokens only) the middleware saw no shared
    token and DISABLED ITSELF — every read endpoint on an internet-facing panel open, the
    exact direction the whole gate exists to never fail in. Both gates now ask the SAME
    identity provider, so they cannot drift again.

    The credential may arrive as a Bearer header (fetch), a same-origin cookie, or a
    ?token= query param — the last because EventSource (SSE) cannot set headers. Nothing
    configured → open (the local-development posture). The HTML shell (/ and /p/*) stays
    open; it is useless without a credential for the API.

    IT GATES SCOPE TOO, AND HAS TO. `perform` refuses a scoped credential the rows outside its
    area — but that is the WRITE path, and #98's whole point is a business analyst "who has no
    access to the jobs dashboard". The dashboard is READS: `/api/temporal/jobs`, `/api/projects`,
    `/api/inbox`. Scoping only the actions would have left a BA able to watch every job, every
    client's board and every word the factory has said, and merely unable to click. That is not
    the thing the card asked for."""
    # A CORS PREFLIGHT CARRIES NO CREDENTIAL, BY SPEC (#145). The browser sends `OPTIONS` before
    # the real request and attaches nothing — so gating it 401s every cross-origin call before it
    # is made, and the CORS support added for a customer's own dashboard would never work once.
    # Answering a preflight discloses only which methods and headers are permitted; the request
    # that follows is gated exactly as before.
    if request.method == "OPTIONS" and request.headers.get("access-control-request-method"):
        return await call_next(request)
    refused = await _ask_the_gate(request.url.path, _credential_of(request))
    if refused is not None:
        return JSONResponse(refused.body, status_code=refused.status)
    return await call_next(request)


# ── A PREVIEW OF THE PRODUCT, ON HOSTS OF ITS OWN (ADR-0050 D7) ─────────────────────────────────
#
# Registered AFTER the gate, which makes it the OUTER middleware: a request for any host under the
# preview domain is answered here and never reaches the gate, the panel's routes or its page — and
# a request for the panel never reaches a preview. A preview's door is a key minted by
# `/api/preview/<project>/<unit>` for somebody the panel already let in, exchanged on the
# service's host for a cookie that exists only there.

#: Headers that describe ONE hop and must not be forwarded (RFC 9110 §7.6.1), plus the length this
#: proxy recomputes. `Host` is NOT among them: the browser's is forwarded unchanged (§5.4), so an
#: application's host checks and the absolute URLs it emits are the preview's own.
_HOP = frozenset({"connection", "keep-alive", "proxy-authenticate", "proxy-authorization", "te",
                  "trailer", "transfer-encoding", "upgrade", "content-length"})


#: The largest body a preview answers with. A preview is pages and their assets, not downloads.
_PREVIEW_BODY_CAP = 50 * 1024 * 1024
#: How long the router waits for a service to answer. A development server compiling its first
#: page routinely takes more than a minute, so a short read timeout would call a slow start dead.
_PREVIEW_UPSTREAM_TIMEOUT_S = 180.0


def _upstream_timeout(projects, record) -> float:
    """How long the router waits for this preview's services: the operator's
    `upstream_timeout_seconds` for the project the record names, else the default."""
    owner = next((p for p in projects if getattr(p, "name", None) == record.project), None)
    seconds = getattr(getattr(owner, "preview", None), "upstream_timeout_seconds", None)
    return float(seconds) if isinstance(seconds, int) and seconds > 0 else \
        _PREVIEW_UPSTREAM_TIMEOUT_S


def _preview_page(status: int, title: str, text: str) -> HTMLResponse:
    return HTMLResponse(
        f"<!doctype html><meta charset=utf-8><title>{_h(title)}</title>"
        f"<body style='font-family:system-ui;max-width:36rem;margin:4rem auto;line-height:1.5'>"
        f"<h1 style='font-size:1.3rem'>{_h(title)}</h1><p>{_h(text)}</p>",
        status_code=status, headers=_NO_CACHE)


def _is_ours(name: str) -> bool:
    """A cookie this platform sets — the panel's credential in either spelling, its login flight,
    its visitor mark, or ANY preview's key (matched by prefix: every unit has its own name)."""
    from openfactory import preview
    from openfactory.identity.base import SECURE_TOKEN_COOKIE, TOKEN_COOKIE
    from openfactory.identity.oidc import FLIGHT_COOKIE

    name = (name or "").strip()
    return (name in {TOKEN_COOKIE, SECURE_TOKEN_COOKIE, FLIGHT_COOKIE, "openfactory_visitor"}
            or name.startswith(preview.COOKIE_PREFIX))


def _without_our_cookies(header: str) -> str:
    """The request's Cookie header minus every cookie of the platform's — the application being
    previewed is agent-written code, and none of them is its business."""
    keep = [c for c in (header or "").split(";") if c.strip() and not _is_ours(c.split("=", 1)[0])]
    return ";".join(keep).strip()


def _a_cookie_a_preview_may_set(set_cookie: str) -> bool:
    """Whether one `Set-Cookie` from the application may reach the browser.

    THE OTHER DIRECTION OF D7. The panel's cookie never travels TO a preview; a preview must not
    write one that travels to the PANEL either. A cookie with a `Domain` is sent to every host
    under it — the panel's too, whenever the two share a parent, as `preview.localhost` and
    `localhost` do — and one named like a cookie of ours sits beside the real one. So a preview
    keeps its host-only cookies, which is what an application with a login needs, and loses any
    that name a domain or a cookie of the platform's. A script can still write one through
    `document.cookie`; the panel refusing a credential cookie that arrives twice, and `__Host-`
    over TLS (#271), are the halves that answer that."""
    name, _, rest = (set_cookie or "").partition("=")
    attrs = [a.split("=", 1)[0].strip().lower() for a in rest.split(";")[1:]]
    return not _is_ours(name) and "domain" not in attrs


def _is_secure(request) -> bool:
    """Whether the browser reached this over TLS — directly, or through a terminator that says so.
    A socket's handshake asks too (`wss`), and a caller that hands over no URL at all is not TLS."""
    proto = (request.headers.get("x-forwarded-proto") or "").split(",")[0].strip().lower()
    scheme = proto or str(getattr(getattr(request, "url", None), "scheme", "") or "")
    return scheme in ("https", "wss")


def _door_after(request: Request, record, host, *, secure: bool) -> str:
    """Where the enter door sends the browser once this host has its cookie: the next exposed
    service's door, so one click opens every service of the unit (each host needs a cookie of its
    own), and at the end the page the button was for.

    EVERY HOP IS DERIVED, NONE IS READ: `preview.next_door` only selects among the services the
    RECORD lists, and the host is built from the record's project, this unit and that service on
    the preview domain — so a `next` naming another unit, another project or a URL is a door with
    no `next` at all. The key travels with the chain because each door checks it again for this
    unit; it is the link's own key, which lives minutes."""
    from openfactory import preview

    service, nxt, to = preview.next_door(record, host.service,
                                         next_=request.query_params.get("next", ""),
                                         to=request.query_params.get("to", ""))
    if service == host.service and not nxt and not to:
        return "/"
    port = request.headers.get("host", "").rpartition(":")[2]
    target = preview.url_for(preview.host_label(record.project, host.unit, service),
                             scheme="https" if secure else "http",
                             preview_domain=preview.domain(),
                             port=int(port) if port.isdigit() else None, path="/")
    if not nxt and not to:
        return target
    query = {"t": request.query_params.get("t", ""), **({"next": nxt} if nxt else {}), "to": to}
    return f"{target.rstrip('/')}{preview.ENTER_PATH}?{urlencode(query)}"


async def _serve_preview(request: Request, host):
    import httpx

    from openfactory import preview

    projects = await asyncio.to_thread(lambda: ProjectRegistry().list())
    found = await asyncio.to_thread(lambda: preview.serving(host, projects))
    if found is None:
        return _preview_page(404, "This preview is not running",
                             "It may have ended when its pull request merged or closed, or when "
                             "its time was up. Open the card on the panel to see its state.")
    record, port = found
    secure = _is_secure(request)
    cookie = preview.cookie_name(record.project, host.unit)
    if request.url.path == preview.ENTER_PATH:
        if not preview.admits(request.query_params.get("t", ""), project=record.project,
                              token=host.unit):
            return _preview_page(403, "This link has expired",
                                 "Open the preview again from the card on the panel.")
        # THE LINK'S KEY LIVES MINUTES, THE COOKIE AS LONG AS THE PREVIEW: a URL is kept by access
        # logs and browser history, so the cookie carries a fresh key of its own.
        kept = preview.mint(record.project, host.unit, expires=record.expires_at)
        response = RedirectResponse(_door_after(request, record, host, secure=secure),
                                    status_code=303, headers=_NO_CACHE)
        response.set_cookie(cookie, kept, httponly=True, samesite="lax", secure=secure, path="/",
                            max_age=max(1, record.expires_at - int(time.time())))
        return response
    if not preview.admits(request.cookies.get(cookie, ""), project=record.project,
                          token=host.unit):
        return _preview_page(401, "Open this preview from the panel",
                             "A preview is opened from its card on the panel, which lets you in "
                             "for as long as the preview is up.")
    headers = {k: v for k, v in request.headers.items() if k.lower() not in _HOP
               and k.lower() not in ("cookie", "authorization")}
    kept = _without_our_cookies(request.headers.get("cookie", ""))
    if kept:
        headers["cookie"] = kept
    headers["x-forwarded-host"] = request.headers.get("host", "")
    headers["x-forwarded-proto"] = "https" if secure else "http"
    # THE TARGET IS DERIVED FROM THE NAME THE PERSON OPENED — the service's alias on its unit's
    # edge network — never read from a record (D7).
    upstream_base = f"http://{host.label}:{port}"
    target = f"{upstream_base}{request.url.path}"
    if request.url.query:
        target += f"?{request.url.query}"
    # A WHOLE RESPONSE, NOT A STREAM. The panel builds a streaming response in exactly one place,
    # the seam that re-asks the gate while it stays open (#208), and a proxy is not a second one.
    async with httpx.AsyncClient(timeout=httpx.Timeout(_upstream_timeout(projects, record),
                                                       connect=5.0),
                                 follow_redirects=False) as client:
        try:
            upstream = await client.request(request.method, target, headers=headers,
                                            content=await request.body())
        except httpx.TimeoutException:
            return _preview_page(504, f"{host.service} is still starting",
                                 "It did not answer in time — a first page can take minutes to "
                                 "build. Try again in a moment.")
        except httpx.HTTPError as exc:
            log.info("preview %s did not answer (%s)", host.label, exc)
            return _preview_page(502, f"{host.service} is not answering",
                                 f"Is it listening on 0.0.0.0:{port}? It may also have stopped; "
                                 "the card on the panel shows its logs and says if it ended.")
    if len(upstream.content) > _PREVIEW_BODY_CAP:
        return _preview_page(502, "This response is too large for a preview",
                             f"The application answered with more than "
                             f"{_PREVIEW_BODY_CAP // (1024 * 1024)} MB.")
    # `.content` is DECODED, so the encoding and the length the upstream declared no longer hold.
    out = []
    for k, v in upstream.headers.multi_items():
        low = k.lower()
        if low in _HOP or low == "content-encoding":
            continue
        if low == "set-cookie" and not _a_cookie_a_preview_may_set(v):
            continue
        if low == "location" and v.startswith(upstream_base):
            # a redirect that names the alias the router reached is rewritten to the preview's own
            # address; every other `Location` is the application's business
            v = f"{'https' if secure else 'http'}://{request.headers.get('host', '')}" + \
                v[len(upstream_base):]
        out.append((k, v))
    response = Response(content=upstream.content, status_code=upstream.status_code)
    response.raw_headers = [(k.lower().encode("latin-1"), v.encode("latin-1")) for k, v in out]
    response.headers["content-length"] = str(len(upstream.content))
    return response


@app.middleware("http")
async def _preview_router(request: Request, call_next):
    """Route a preview host to its preview; everything else to the panel, untouched."""
    from openfactory import preview

    dom = preview.domain()
    if dom and preview.under_domain(request.headers.get("host", ""), dom):
        host = preview.host_of(request.headers.get("host", ""), dom)
        if host is None:
            # UNDER THE PREVIEW DOMAIN, THE PANEL IS NEVER SERVED — not even for a host that names
            # no preview. Serving the panel on a host a preview's scripts share a site with would
            # give them a page of the panel to frame.
            return _preview_page(404, "No such preview", "This address names no preview.")
        return await _serve_preview(request, host)
    response = await call_next(request)
    # THE PANEL IS NEVER FRAMED. Its buttons merge pull requests and release to production, and a
    # preview is a page on a sibling host running code nobody reviewed yet: cross-origin it cannot
    # read the panel, but it could lay it under its own page and steer a click.
    response.headers.setdefault("content-security-policy", "frame-ancestors 'none'")
    response.headers.setdefault("x-frame-options", "DENY")
    return response


def _proposal_said(record, project: str) -> dict:
    """`{proposal_url, why}` for a card whose base declares no shape — the forge asked now. An
    unreadable registry or forge falls back to what the record carries, said as it is."""
    from openfactory.onboarding.preview_propose import proposal_said

    try:
        found = ProjectRegistry().get(project)
    except Exception as exc:  # noqa: BLE001 — a card must never take the panel down
        log.info("preview: could not read %s from the registry (%s)", project, exc)
        found = project
    return proposal_said(record, found) or {}


@app.get("/api/preview/{project}/{unit}")
async def preview_link(project: str, unit: str, request: Request):
    """One unit's preview as the panel shows it, and the way into it, for somebody the panel
    already let in (ADR-0050; the design on #265, §5.5).

    `{state, live, services: [{name, url, from_change, health}], images, base_moved, notes,
    missing, stale, proposal_url, why, log_dir, expires_at, commits, can_start, ...}`. Each URL is
    on the service's own host and carries a key that opens this unit only, for minutes — never the
    panel's credential, which a preview's scripts must not be able to read — and CHAINS through
    every other exposed service's door first, so one click opens them all. The service NOT from
    the change comes first: the screens a person opens are usually the part the change did not
    touch.

    `can_start` and `stale` ARE JUDGED HERE, NOT READ: from the deployment (a runtime named) and
    the forge (an open pull request of the unit, the head it points at now), asked at most once a
    minute per unit (`preview/demand.py`). What the job wrote when it offered the preview is never
    the answer — the moment a person merges what was missing, the card can start one."""
    from openfactory import preview
    from openfactory.contracts.project import PreviewPolicy
    from openfactory.preview import demand
    from openfactory.runtime.temporal.io import default_preview_runtime

    unit = (unit or "").lower()
    if not preview.UNIT_RE.fullmatch(unit):
        return {"state": "", "live": False, "can_start": False,
                "why": "a preview is addressed by a card number or a requirement (req0012)"}
    dom = preview.domain()
    if not dom:
        return {"state": "", "live": False, "can_start": False,
                "why": "previews are not exposed on this deployment "
                       "(OPENFACTORY_PREVIEW_DOMAIN is not set)"}
    try:
        registered = await asyncio.to_thread(lambda: ProjectRegistry().list())
        # A CARD OF A REQUIREMENT IS PREVIEWED AS THE REQUIREMENT (D1): the record says which.
        unit = await asyncio.to_thread(lambda: preview.unit_of_card(project, unit))
        found = await asyncio.to_thread(lambda: preview.latest(project, unit))
    except Exception as exc:  # noqa: BLE001 — an unreadable store is said, not a 500
        return {"state": "", "live": False, "can_start": False,
                "why": f"the preview records could not be read ({str(exc)[:120]})"}
    owner = next((p for p in registered if getattr(p, "name", None) == project), None)
    if owner is None:
        return {"state": "", "live": False, "can_start": False,
                "why": f"there is no project called {project!r} on this deployment"}
    if found is not None and found.project != project:
        found = None  # a record that names another project is none of this one's
    policy = getattr(owner, "preview", None) or PreviewPolicy()
    forge = await asyncio.to_thread(lambda: demand.forge_state(owner, unit, found))
    judged = demand.judge(found, kind=default_preview_runtime(), forge=forge,
                          required=bool(getattr(policy, "required", False)))
    body = {"unit": unit, "state": found.state if found else "", "live": False, "services": [],
            "images": dict(found.images) if found else {},
            "base_moved": dict(found.base_moved) if found else {},
            "notes": list(found.notes) if found else [],
            "missing": list(found.missing) if found else [],
            "stale": judged.stale,
            "proposal_url": found.proposal_url if found else "",
            "log_dir": found.log_dir if found else "",
            "expires_at": found.expires_at if found else 0,
            "commits": dict(found.commits) if found else {},
            "cards": list(found.cards) if found else [],
            "pr_urls": list(found.pr_urls) if found else [],
            "started_by": found.started_by if found else "",
            "can_start": judged.can_start}
    if found is not None and found.shape and not found.live:
        # THE BASE DECLARES NO SHAPE (#265 slice 4): which proposal is open is the forge's answer
        # NOW — a person merges it after the job wrote this record — so the sentence naming it is
        # computed here, per read (cached a minute), never taken from the record.
        body.update(await asyncio.to_thread(lambda: _proposal_said(found, project)))
        body["can_start"] = False  # nothing declares how it runs until that proposal merges
        return body
    if found is None or not found.live or found.expired():
        if found is not None and found.state in (preview.FAILED, preview.ENDED):
            said = found.why
        elif found is not None and found.live:
            said = "its time was up"
        elif found is not None and found.state == preview.STARTING:
            said = ""
        else:
            said = judged.why
        if not said and found is None and not judged.can_start:
            said = "no preview of this card yet"
        body["why"] = said
        return body
    expires = min(int(time.time()) + preview.LINK_TTL_SECONDS, found.expires_at)
    key = preview.mint(found.project, unit, expires=expires)
    scheme = "https" if _is_secure(request) else "http"
    body["live"] = True
    body["why"] = ""

    def door(svc: str) -> str:
        query = {"t": key}
        nxt = preview.first_hop(found, svc)
        if nxt:
            query.update({"next": nxt, "to": svc})
        return preview.url_for(preview.host_label(found.project, unit, svc), scheme=scheme,
                               preview_domain=dom, port=request.url.port,
                               path=f"{preview.ENTER_PATH}?{urlencode(query)}")

    body["services"] = [{
        "name": svc,
        "url": door(svc),
        "from_change": bool(found.from_change.get(svc)),
        "health": found.health.get(svc, ""),
    } for svc in found.ordered()]
    return body


class _Refusal(NamedTuple):
    """The gate's "no": the status and the body a request is answered with."""

    status: int
    body: dict


def _credential_of(request) -> str:
    """What a request presents: a Bearer header (fetch), else the same-origin cookie, else
    `?token=` — the last because EventSource cannot set headers. "" when it presents nothing.

    A WEBSOCKET IS ASKED THE SAME WAY, IN THE SAME ORDER. Starlette's `WebSocket` is an
    `HTTPConnection` like `Request` — `.headers`, `.cookies` and `.query_params` are the
    handshake's — so there is ONE answer to "what did this connection present". The socket
    used to read `?token=`, else the cookie, and never the header: measured on 2026-09-19, a
    Bearer credential every route accepts was refused the socket, and a wrong header in front of
    a good cookie (the gate's 401) was let in. A browser cannot set a header on a WebSocket; a
    customer's own dashboard, server side, sets nothing else."""
    auth = request.headers.get("authorization", "")
    return (
        auth[7:] if auth.startswith("Bearer ")
        else (_one_credential_cookie(request)
              or request.query_params.get("token") or "")
    )


def _credential_cookie_name(request) -> str:
    """Which spelling of the credential cookie this request's panel uses: `__Host-` over TLS
    (#271), the plain name on plain http, where the prefix cannot be set."""
    from openfactory.identity.base import SECURE_TOKEN_COOKIE, TOKEN_COOKIE

    return SECURE_TOKEN_COOKIE if _is_secure(request) else TOKEN_COOKIE


def _one_credential_cookie(request) -> str:
    """The credential cookie — in THIS panel's spelling, and only when the browser sent exactly
    ONE. Two is nobody's.

    A cookie of the same name set by a sibling host with a `Domain` (a preview's host is exactly
    such a host, ADR-0050 D7) arrives beside the real one, and the parse is last-wins: the panel
    would act as whoever the sibling chose. The browser does not say which cookie came from where,
    so an ambiguous credential is refused rather than guessed; a fetch still carries its Bearer
    header, which is how the page authenticates every call.

    OVER TLS ONLY `__Host-` COUNTS (#271). No sibling can set a `__Host-` cookie — browsers refuse
    one with a `Domain` — so there the plain name is ignored outright, and a planted plain cookie
    cannot sign in a browser that holds none."""
    name = _credential_cookie_name(request)
    raw = request.headers.get("cookie")
    if raw is None:
        # no header to count — a caller that hands over parsed cookies only; nothing is ambiguous
        return request.cookies.get(name, "") or ""
    seen = sum(1 for part in raw.split(";") if part.split("=", 1)[0].strip() == name)
    return request.cookies.get(name, "") if seen == 1 else ""


def _set_credential_cookie(response, request, token: str, *, max_age: int) -> None:
    """The credential cookie, in the spelling `_one_credential_cookie` will read back. NOT
    HttpOnly, deliberately: the page reads it once into localStorage and sends it as a Bearer
    header from then on, which is how every mutating route authenticates."""
    secure = _is_secure(request)
    response.set_cookie(_credential_cookie_name(request), token, max_age=max(1, max_age),
                        samesite="lax", secure=secure, path="/")


def _clear_credential_cookies(response) -> None:
    """Both spellings: a browser that moved between http and https may hold either."""
    from openfactory.identity.base import SECURE_TOKEN_COOKIE, TOKEN_COOKIE

    response.delete_cookie(TOKEN_COOKIE, path="/")
    response.delete_cookie(SECURE_TOKEN_COOKIE, path="/", secure=True)


def _gate_verdict(path: str, credential: str) -> _Refusal | None:
    """WHO IS THIS, AND MAY THEY READ THAT — the HTTP gate's whole decision, in one function.

    None when `credential` opens `path`; otherwise the refusal a request is answered with. This
    lived inline in `_panel_gate`, which was enough while a request was the only thing that needed
    the answer. A stream needs it AGAIN, minutes after the middleware has returned (#208: one
    opened before `/auth/logout` went on pushing every running job to a browser that had signed
    out), and the socket had already written its own copy by hand and checked half of what it
    copied (#145). Two copies of an authorization rule is how they drift, so what is asked again
    is this, never a third copy: the middleware, the socket's handshake and `_CredentialWatch`
    all ask it, through `_ask_the_gate`.

    WHO is `_admission`'s answer — the one decision every door renders, and the reason a 503 here
    can be either of that function's two. What this adds is the half only the HTTP gate has: which
    area the PATH belongs to, and the status and body each refusal is answered with.

    SYNCHRONOUS, AND IT MAY WAIT — `_admission` folds the people store for a session token, and a
    row may go further than that. So nothing on the event loop calls it directly; see
    `_ask_the_gate` for what that was measured to cost, and what it cost not to."""
    if not _gated(path):
        return None
    door = _admission(credential)
    if door.unavailable:
        return _Refusal(503, {"detail": door.unavailable})
    if door.open:
        return None
    subject = door.subject
    if subject is None:
        return _Refusal(401, _unauthorized(door.provider))
    scopes = _scopes_of(subject)
    wanted = _scope_of_path(path)
    if scopes is not None and wanted is not None and wanted not in scopes:
        log.warning("DENIED_SCOPE_READ %s (%s) for a credential scoped to %s",
                    path, wanted, ", ".join(sorted(scopes)) or "nothing")
        return _Refusal(403, {
            "detail": f"this credential is scoped to "
                      f"{', '.join(sorted(scopes)) or 'nothing'} and that is part of the "
                      f"{wanted}."})
    return None


#: What a door says when it cannot check anybody. Two causes, one posture — CLOSED — and neither
#: sentence carries the cause: it goes to a caller nobody has identified, and the cause (a
#: variable's name, a file's path) is in the log line beside it.
IDENTITY_UNAVAILABLE = "identity provider unavailable"
PEOPLE_UNAVAILABLE = ("identity provider unavailable: the people registered on this deployment "
                      "cannot be read right now, so nobody can be checked — the panel's log says "
                      "why, and this clears by itself when the store answers again")


@dataclass(frozen=True)
class _Admission:
    """What the door decided about ONE credential — decided once, rendered by each transport."""

    provider: object = None
    #: who, when the provider named somebody (`UNKNOWN` for a shared token); None = nobody
    subject: object = None
    #: nothing is configured: the local-development posture, every request permitted
    open: bool = False
    #: the door cannot check anybody — 503 / close 1011. Never open, and never "unauthorized"
    unavailable: str = ""


def _admission(credential: str) -> _Admission:
    """THE ONE DECISION EVERY DOOR RENDERS — the HTTP gate, `require_auth` and the socket.

    Three doors each spelled this sequence by hand, and this file's history is the list of times
    one copy learned something the others did not (C-26: the middleware; #145: the socket's
    scope). So the fourth thing a door has to know lives here, once:

    A PROVIDER THAT COULD NOT LOOK IS NOT A PROVIDER THAT FOUND NOBODY. The local row reads the
    people registered by invitation to say whether the door is open at all and whose session a
    token is. When that store cannot be read it says so (`unavailable()`), and the answer is
    "cannot check" — 503, by name — for everybody it could not resolve: never open, and not 401
    either, because "unauthorized" sends a signed-in person to sign in again against a store
    that cannot record it, and clears the session that would have worked a minute later. A
    credential the provider DID resolve without the store (an environment token) is admitted as
    ever — one working door is how the operator gets in to see what is wrong.

    Asked by `getattr`, and only a non-empty `str` counts: a row that never declared it keeps
    the behaviour it had, and a test double that answers everything has declared nothing."""
    from openfactory.identity import build_identity

    try:
        provider = build_identity()
    except ValueError as exc:
        # a deployment naming a provider this build lacks — or one it did not finish
        # configuring (#33: an `oidc` row with no issuer) — must fail CLOSED: "I cannot
        # check credentials" is not "let everyone in". The sentence is the provider's own, so
        # the log names the variable and not a guess.
        log.error("OPENFACTORY_IDENTITY_UNKNOWN the configured identity provider cannot be "
                  "built — refusing every request rather than falling back to open: %s", exc)
        return _Admission(unavailable=IDENTITY_UNAVAILABLE)
    if getattr(provider, "open_to_everyone", lambda: False)():
        return _Admission(provider=provider, open=True)
    subject = provider.identify(credential=credential, via="panel")
    if subject is None:
        why = _why_unavailable(provider)
        if why:
            log.error("OPENFACTORY_IDENTITY_UNAVAILABLE the identity provider could not check "
                      "this request — refusing it rather than reading \"could not look\" as "
                      "\"nobody is registered\": %s", why)
            return _Admission(provider=provider, unavailable=PEOPLE_UNAVAILABLE)
    return _Admission(provider=provider, subject=subject)


def _why_unavailable(provider) -> str:
    """The provider's own sentence when it answered WITHOUT a store it depends on, else `""`."""
    ask = getattr(provider, "unavailable", None)
    why = ask() if callable(ask) else ""
    return why.strip() if isinstance(why, str) else ""


def _gated(path: str) -> bool:
    """Whether the gate has anything to say about `path`. The HTML shell (/ and /p/*), the login
    doors and the health check are open by design: useless, or necessary, without a credential."""
    return path.startswith("/api/")


async def _ask_the_gate(path: str, credential: str) -> _Refusal | None:
    """`_gate_verdict`, for whoever is ON THE EVENT LOOP — which is everyone who asks it.

    THE ASK LEAVES THE LOOP, ALWAYS, AND THAT WAS DECIDED WITH NUMBERS (2026-09-19, this
    machine, Python 3.13). The middleware used to call the verdict inline, on the one loop that
    also serves both event streams, the socket and every other request:

    - what one ask costs, the real sqlite people store, 300 asks each: 0.021 ms for a token-map
      row (no store read); 0.32 ms on an open panel (`has_people` folds the store); 0.35 ms for
      a session with one person registered; 1.39 ms (p95 1.46) with forty people and three
      sessions each. A millisecond of stall per request — by itself, not worth a thread;
    - what the hop costs: `asyncio.to_thread` of nothing on an idle loop, 0.027 ms (p95 0.030).
      Under uvicorn on a real socket — the same process answering batches each way, turn about,
      on a machine that was busy: `GET /api/whoami` (forty people, three sessions each) 7.6 ms
      inline against 8.7 ms hopped one at a time, and 74 against 64 requests a second at sixteen
      at a time. So on a SATURATED box the hop is about a millisecond, and a tenth of the
      throughput, of a request that already costs eight — paid by the request that asks;
    - what NOT hopping costs is not bounded by sqlite. The people store reads through the
      metrics sink, which an add-on may put across a network; and the in-tree `oidc` row's
      `identify` fetches the issuer's discovery document and keys over HTTP, inline, with a
      five-second timeout — for ANY JWT-shaped credential, good or not, whenever its cache
      cannot answer. Measured under uvicorn against an issuer that takes one second: a
      stranger's `GET /api/whoami` took 1035 ms, and somebody else's `GET /` — the HTML
      shell, not gated at all — took 1024 ms behind it. After: 3 ms.

    So: a millisecond at worst on the request that asks, against a panel that ONE slow ask stops
    for everybody — every tab, every stream, the health check. A provider capability ("my lookup
    may block", asked with `getattr`) was weighed and rejected: the local row cannot know what its
    sink costs, a row that never heard of the question would have to be assumed to block anyway,
    and asking it means building the provider on the loop and splitting the verdict in two — for a
    saving that is invisible beside the request it sits in.
    WHAT WOULD CHANGE THIS: a hop measured at more than a fifth of the whole request on an idle
    box (it is 0.5% of one there), or an identity axis where no row can block — which would mean
    dropping the `oidc` row's inline fetch and declaring the port non-blocking, a bigger decision
    than this one.

    AN UNGATED PATH NEVER TAKES A THREAD. The default executor has `min(32, cpus + 4)` workers,
    shared with the streams' snapshots. When every one is held by an ask that waits, the next
    ASK queues — behind other asks, never in front of the loop — and the shell, the login page
    and the health check, which present nothing, must not queue with it."""
    if not _gated(path):
        return None
    return await asyncio.to_thread(_gate_verdict, path, credential)


def _unauthorized(provider) -> dict:
    """The 401's body. A provider with a login page NAMES it (#33), so the page can send the
    browser there instead of prompting for a token that no such deployment issues; `local` has
    none, and its body stays exactly what it was."""
    login = str(getattr(provider, "login_path", "") or "")
    return {"detail": "unauthorized", "login": login} if login else {"detail": "unauthorized"}


#: Routes every credential may read, whatever it is scoped to. Deliberately tiny: `whoami` is how
#: a browser discovers which surface to render for itself, and a page that cannot ask that would
#: have to guess — which for a scoped credential means rendering the dashboard it may not read and
#: filling it with 403s.
_UNSCOPED_ROUTES = ("/api/whoami",)

#: Path prefixes that belong to the product area. Everything else under `/api/` is the FLOOR, by
#: default and on purpose: a route added later is out of a scoped credential's reach until
#: somebody decides otherwise, which is the same direction `ActionSpec.scope` defaults in.
_PRODUCT_ROUTES = ("/api/product/", "/api/act/product_")


#: Routes BOTH areas read. A card's preview is exactly what a product-scoped person — the business
#: analyst who asked for the change — wants to click through before it merges (ADR-0050); keeping
#: it on the floor side would hand the link to everybody except the person it is for.
_EVERY_AREA_PREFIXES = ("/api/preview/",)


def _scope_of_path(path: str) -> str | None:
    """Which area a request belongs to, or None when every credential may read it."""
    if path in _UNSCOPED_ROUTES or path.startswith(_EVERY_AREA_PREFIXES):
        return None
    if path.startswith(_PRODUCT_ROUTES):
        return actions.PRODUCT
    return actions.FLOOR


# ── A STREAM ENDS WHEN ITS CREDENTIAL DOES (#208) ───────────────────────────────────────────────
#
# THE GATE RUNS WHEN A REQUEST ARRIVES, AND A STREAM'S REQUEST LASTS AS LONG AS THE TAB. Both
# event streams (and the socket) were authorized exactly once, at the open, and then looped on
# `is_disconnected()` and nothing else. So `/auth/logout` revoked the session in the store and
# the stream it had opened went on delivering every running job, its state and its pull request
# to a browser that was signed out; a credential replaced by a product-only one kept receiving
# the floor it is refused everywhere else; an expired session never expired. The window closed at
# the next reconnect, which on a stable network is when the tab closes.
#
# So whatever stays open re-asks `_gate_verdict` — the SAME function the middleware asks, so it
# holds for whatever answers `identify`: the local rows, a session, OIDC, an add-on's provider —
# with the credential it was OPENED with, on its own clock, and ends when the answer is no.

#: How long a stream runs on its last answer before it asks again. TEN SECONDS, measured rather
#: than felt (2026-09-19, the real sqlite people store, 200 asks each): one ask costs 0.37 ms with
#: one registered person and 1.5 ms with forty (three sessions each, ~200 rows) — it is a fold of
#: up to `READ_LAST` rows, so it grows with the deployment. PER FRAME would be that every 1-2 s
#: for every open tab, for a fact that changes a few times a day. The page's own polls already
#: pay the same ask about three times in ten seconds (every 6, 15, 20 and 60 s, through the
#: middleware), so one more per stream is the same order as what an open tab costs today, and
#: keeps "signed out" from meaning "still streaming for minutes".
#: THE BOUND THIS GIVES: no frame leaves on an answer older than this, and
#: the stream closes at its first frame after that — both streams heartbeat at least every 3 s —
#: so at most `_STREAM_RECHECK_S` + 3 s + one ask after the credential stopped being good. No
#: environment override: neither `_STREAM_TICK` nor `_STREAM_SLOW_S` has one, and a knob that can
#: be set to an hour is this defect, configurable.
_STREAM_RECHECK_S = 10.0

#: What the final event calls each of the gate's refusals — the page's vocabulary, so it does not
#: have to know status codes. Anything else (the 503 of a provider that cannot be built, a check
#: that raised) is `unavailable`: the stream ended and NOBODY was judged.
_ENDED_WHY = {401: "signed_out", 403: "not_allowed"}
_ENDED_UNAVAILABLE = "unavailable"

#: What the socket's watcher puts on a subscriber's queue in place of a project name. An object,
#: compared by identity: no project can be called this.
_CREDENTIAL_ENDED = object()

#: The SSE event's name. A NAMED event on purpose: `onmessage` never sees one, so a page that has
#: not heard of it (a cached copy, a customer's own dashboard) cannot mistake the goodbye for a
#: frame and paint it — which is #181's defect, one transport over.
STREAM_ENDED_EVENT = "ended"


def _stream_clock() -> float:
    """The clock a stream's re-check runs on. A function so a guard can move it, not sleep."""
    return time.monotonic()


class _CredentialWatch:
    """The credential something long-lived was opened with, asked again on the stream's clock."""

    def __init__(self, path: str, credential: str) -> None:
        self.path = path
        self._credential = credential
        self._due = _stream_clock() + _STREAM_RECHECK_S

    def due(self) -> bool:
        return _stream_clock() >= self._due

    def seconds_left(self) -> float:
        return max(0.0, self._due - _stream_clock())

    async def asked(self) -> dict | None:
        """None while the credential opens this path; else the gate's answer, typed: `why`,
        `status`, and the gate's own body. THE SOCKET'S HANDSHAKE IS THIS, ASKED FIRST — so what
        a socket is opened on and what it is ended on ten seconds later cannot be two rules.

        A CHECK THAT COULD NOT BE MADE IS NOT A VERDICT, AND THE STREAM STILL ENDS. The gate does
        the same to a request: a provider that cannot be built is a 503, and one that raises — the
        contract says it never does, an add-on may — is a 500; neither is served. Failing OPEN
        here would make an already-open stream the one surface still delivering the floor while
        the deployment can vouch for nobody, including for this stream's own reconnect. So it
        ends, says `unavailable` rather than accusing anybody of having signed out, and the page
        reopens it once a read is answered again. To reverse: `return None` from the `except`.

        OFF THE EVENT LOOP, as every ask is: see `_ask_the_gate`."""
        try:
            refused = await _ask_the_gate(self.path, self._credential)
        except Exception as exc:  # noqa: BLE001 — said by name below; a stream must not die mute
            # THE CREDENTIAL NEVER REACHES A LOG. An add-on's exception text is not ours, and
            # "invalid token <the token>" is a sentence somebody would write.
            said = str(exc)[:160]
            if self._credential:
                said = said.replace(self._credential, "<credential>")
            log.error("OPENFACTORY_STREAM_UNCHECKED the credential behind %s could not be asked "
                      "about (%s: %s) — nothing is streamed on an answer nobody can give",
                      self.path, type(exc).__name__, said)
            refused = _Refusal(503, {"detail": "the credential this stream was opened with "
                                               "could not be checked again"})
        self._due = _stream_clock() + _STREAM_RECHECK_S
        if refused is None:
            return None
        why = _ENDED_WHY.get(refused.status, _ENDED_UNAVAILABLE)
        return {"why": why, "status": refused.status, **refused.body}

    async def ended(self) -> dict | None:
        """`asked`, of something ALREADY OPEN: what the final event says, and the log line that
        says a stream was cut. A refused open is not a stream that ended, and is not logged as
        one — the gate already logs the refusals it always did (`DENIED_SCOPE_READ`)."""
        said = await self.asked()
        if said is not None:
            log.info("OPENFACTORY_STREAM_ENDED %s ended: %s (%s)", self.path, said["why"],
                     said["status"])
        return said


def _close_code(why: str) -> int:
    """The WebSocket close code for one of the gate's answers: 1008 (policy violation) for a
    refusal, 1011 (the server could not) when nobody was judged. One mapping, for a socket
    refused at the open and one ended later."""
    return 1011 if why == _ENDED_UNAVAILABLE else 1008


async def _while_the_credential_holds(request: Request, frames):
    """`frames`, for as long as the credential `request` arrived with still opens its path.

    ASKED BEFORE A FRAME LEAVES, not after: the property is that nothing is delivered on an answer
    older than `_STREAM_RECHECK_S`, and asking after the `yield` would hand over one more frame
    of the floor first. When the answer is no the stream says so ONCE, in a typed event, and
    ends — EventSource cannot see a status code, so a bare close would read as a network drop
    and be reconnected into a refusal it also cannot see."""
    watch = _CredentialWatch(request.url.path, _credential_of(request))
    async with contextlib.aclosing(frames):
        async for frame in frames:
            if watch.due():
                ended = await watch.ended()
                if ended is not None:
                    yield f"event: {STREAM_ENDED_EVENT}\ndata: {json.dumps(ended, sort_keys=True)}\n\n"
                    return
            yield frame


def _event_stream(request: Request, frames) -> StreamingResponse:
    """THE ONLY WAY THIS PANEL ANSWERS `text/event-stream`. One seam, so a third stream cannot
    forget to ask: `tests/test_a_stream_ends_when_its_credential_does.py` enumerates `app.routes`
    and fails the suite for any route that builds a streaming response some other way."""
    return StreamingResponse(_while_the_credential_holds(request, frames),
                             media_type="text/event-stream")


def require_auth(authorization: str = Header(default="")) -> None:
    """Gate every mutating endpoint on a credential the deployment configured.

    OPEN ONLY WHEN NOTHING IS CONFIGURED — the documented local-development posture, and the one
    question `LocalIdentity.open_to_everyone` exists to answer separately from `identify`. The two
    point opposite ways: with nothing set every request is unauthenticated AND permitted, while
    with something set an unresolvable credential must be refused. An earlier version of this
    function asked only whether `OPENFACTORY_PANEL_TOKEN` was set, so a deployment that migrated to
    per-person tokens (C-26) and removed the shared one would have had a WIDE OPEN panel — the
    exact direction this gate must never fail in.

    Honours both: a per-person token from `OPENFACTORY_PANEL_TOKENS`, and the legacy shared one."""
    door = _admission(authorization.removeprefix("Bearer ").strip())
    if door.unavailable:
        # A provider that cannot be built, or one that could not read the people it answers
        # from: the safe reading of "I cannot check credentials" is not "let everyone in".
        raise HTTPException(status_code=503, detail=door.unavailable)
    if not door.open and door.subject is None:
        raise HTTPException(status_code=401, detail="unauthorized")


_AUTH = [Depends(require_auth)]


# ── the panel as a transport over the action layer (C-23) ────────────────────────────────────────

#: `Outcome.code` → HTTP status. A test asserts every code in `actions.CODES` has a row here: a
#: code with no mapping falls through to 200 and reports a refusal as a success, which is the
#: silent-failure shape this platform exists to make impossible.
_STATUS = {
    actions.OK: 200,
    actions.INVALID: 400,
    actions.DENIED: 403,
    actions.NOT_FOUND: 404,
    actions.CONFLICT: 409,
    actions.UNAVAILABLE: 503,
    actions.FAILED: 500,
    actions.UNIMPLEMENTED: 501,
}


def _subject(request: Request):
    """WHO is asking, resolved by the deployment's identity provider (C-26).

    The panel's credential used to be a shared password, so "who approved that production release"
    had no answer: everybody holding the token was the same person. `OPENFACTORY_PANEL_TOKENS` now names
    one secret per person, and the provider turns the bearer token into a `Subject`.

    THE LEGACY SHARED TOKEN STILL RESOLVES — to `UNKNOWN`, deliberately. Breaking every existing
    deployment's panel to close an audit gap would close it by locking everyone out; instead the
    gap appears in the audit line as the word `anonymous`, which is a thing you can grep for.

    `X-OpenFactory-Actor` remains a LABEL and is only honoured for a caller the provider could not name —
    a person it DID name must not be able to rename themselves in the audit trail."""
    from openfactory.identity import build_identity
    from openfactory.identity.base import UNKNOWN

    token = (request.headers.get("authorization") or "").removeprefix("Bearer ").strip()
    try:
        subject = build_identity().identify(credential=token, via="panel") or UNKNOWN
    except Exception:  # noqa: BLE001 — a door that throws is a door nobody can walk through
        log.warning("the identity provider could not answer; treating the caller as anonymous",
                    exc_info=True)
        subject = UNKNOWN
    if subject.known:
        return subject
    label = (request.headers.get("x-openfactory-actor") or "").strip()[:80]
    return UNKNOWN if not label else type(subject)(
        id="", display=label, via=subject.via, groups=subject.groups)


def _actor(request: Request) -> actions.Actor:
    """Who the panel says is asking, as the action layer's subject.

    `admin` IS STILL TRUE FOR ANY CALLER THAT GOT THIS FAR, and that is the panel's own posture
    rather than an oversight: holding a panel credential is what admin means on this surface, and
    `require_auth` already refused everyone else. What changed in C-26 is that the audit line now
    carries WHO, instead of the word "panel" for every person who ever held one token.

    Per-project authorization — `policy.authz` over `project.admins` — is deliberately NOT applied
    here. The panel is the operator's console for the whole deployment; making it obey a per-project
    allowlist is a real decision with a real migration behind it (every existing deployment would
    have to list its own operators before the panel worked again), and it belongs to whoever turns
    that on, not to the commit that made identity possible.

    SCOPE IS A DIFFERENT QUESTION FROM ADMIN, and this is where the deployment's answer arrives
    (#98). A credential issued from `OPENFACTORY_PRODUCT_TOKENS` asserts the `product` group, and that
    becomes `Actor.scopes` — so the holder is an admin OF THE PRODUCT AREA (they must be; accepting
    a requirement is the most consequential act there) and is refused `merge`, `skip` and every
    other floor row by name. A credential asserting no groups is unscoped, which is every actor
    that existed before this and is why the mapping is `None` rather than an empty set."""
    subject = _subject(request)
    scopes = _scopes_of(subject)
    return actions.Actor(id=subject.id or "panel",
                         display=subject.display or subject.id or "panel",
                         via="panel", admin=True, scopes=scopes,
                         conversation=_conversation_of(request, subject))


#: The cookie a browser nobody has identified carries, so that ITS conversation with the product
#: role is its own (#33). Minted by the page (`panel.html::boot`), read here; a client that sends
#: none shares the project-wide conversation, which is what every client did before.
VISITOR_COOKIE = "openfactory_visitor"
_VISITOR_SHAPE = re.compile(r"^[A-Za-z0-9_-]{8,64}$")


def _conversation_of(request: Request, subject) -> str:
    """Which conversation with the product role this request belongs to.

    A KNOWN PERSON IS THEIR OWN KEY, from either identity row — a token, an invitation, an SSO
    login — so what Ana said yesterday from her phone is the thread Ana continues today from her
    laptop, and never Bruno's. Reads stay ungated (*"what the product promises is not a secret
    from the channel it is discussed in"*): an unidentified browser gets a conversation keyed by
    the visitor cookie the page set, isolated and directed even before anybody is known — and
    filing, confirming and accepting still require a known subject, which the rows check."""
    # MINTED WITH THE PREFIXES THE ROWS REFUSE TO TAKE FROM A CALLER (`product/conversation.py`):
    # one definition, so a surface that spelled its key differently would be a room by accident.
    from openfactory.product.conversation import PERSON, VISITOR
    if getattr(subject, "known", False):
        return f"{PERSON}{subject.id}"
    # A request without a cookie jar (a script's, a test's) is a request with no cookie — the
    # answer is the project-wide conversation, never an exception at the door.
    cookies = getattr(request, "cookies", None) or {}
    visitor = str(cookies.get(VISITOR_COOKIE, "") or "").strip()
    return f"{VISITOR}{visitor}" if _VISITOR_SHAPE.match(visitor) else ""


def _scopes_of(subject) -> frozenset[str] | None:
    """The action-layer scopes a subject's asserted groups grant, or None for an unscoped one.

    ONLY GROUPS THAT NAME A REAL SCOPE COUNT. A buyer's identity provider asserts dozens of groups
    that mean nothing here, and treating an unrecognised one as a scope would either deny somebody
    for holding an unrelated group or, worse, invent an area. So this INTERSECTS with the registry:
    a subject carrying only foreign groups is unscoped, exactly as it was before scopes existed."""
    known = frozenset(getattr(subject, "groups", ()) or ()) & actions.SCOPES
    return known or None


def _raise_unless_ok(outcome: actions.Outcome) -> None:
    """Turn a refusal into the HTTP error the panel already knows how to render.

    `detail` carries the action's own sentence rather than a status phrase, because that sentence
    is the entire reason the layer returns prose alongside a code — a 409 reading "Conflict" sends
    an operator to the logs, and one reading "#250 is not parked waiting for anybody" does not."""
    if not outcome.ok:
        raise HTTPException(status_code=_STATUS.get(outcome.code, 500), detail=outcome.message)


def _read_panel() -> str:
    # Per-deployment branding: each install sets OPENFACTORY_PLATFORM_NAME (default neutral). The panel
    # ships with a __BRAND__ token so the same code serves any brand without a rebuild.
    brand = os.environ.get("OPENFACTORY_PLATFORM_NAME", "OpenFactory")
    page = (Path(__file__).parent / "panel.html").read_text().replace("__BRAND__", brand)
    # AND THE FACTS THE SERVER OWNS (#164). The page carried hand copies of three of them — the
    # attention states, the rate-limit floor and the engine's own merge-wait sentences — and two
    # had already drifted: `ALARM` was missing `paused` AND `awaiting_prod_approval`, so the bar
    # that counts what needs a person did not count a production gate.
    #
    # INJECTED RATHER THAN FETCHED, because a fetch has a failure mode and this does not: a page
    # that renders before its vocabulary arrives would either flash the wrong colours or need a
    # fallback copy, which is the defect coming back through the door marked resilience.
    return page.replace("__VOCABULARY__", json.dumps(_panel_vocabulary(), ensure_ascii=False))


def _panel_vocabulary() -> dict:
    """The server-owned words the page renders — one definition, rendered by a surface (ADR-0038).

    Every entry here was a literal in `panel.html` and every one of them is decided somewhere the
    page cannot see: which states need a person is the engine's list, and what a standing
    pull-request wait is ON is the workflow's own sentence. The rate floor left this table when
    it left core: it is the adapter's own number now and travels on the budget it judges, so the
    page never has to compare a count against a threshold at all.

    READ FROM `vocabulary`, NOT FROM `view` AND `workflow` (#178). Those two import `temporalio` at
    the top, and this runs on EVERY render of the page — so on an install without the `runtime`
    extra the panel process was up and `/` answered 500, under three docstrings that said the panel
    serves without that extra. The words are the same objects; only the module they are reached
    through is one a page can afford.
    """
    from openfactory.runtime.temporal.vocabulary import ATTENTION_STATES, merge_wait_note

    return {
        "alarm": sorted(ATTENTION_STATES),
        "merge_wait": {"auto": merge_wait_note(True), "human": merge_wait_note(False)},
        # The name of the event a stream ends with (#208). The page LISTENS for it by name, and
        # a name spelled twice is a goodbye nobody hears the day one of them is edited.
        "stream_ended": STREAM_ENDED_EVENT,
    }


def _read_events(path: Path) -> list[dict]:
    if not path.exists():
        return []
    out: list[dict] = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if line:
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                log.debug("skipping an unreadable journal line")
    return out


def _box_health(project) -> dict:
    """The box's verdict — now `box_prove.health`, kept here as the web layer's name for
    it (#144). Moved because the floor ladder and the CLI need the same answer, and a
    second copy is how two surfaces come to disagree about whether a card gets taken."""
    from openfactory.box_prove import health

    return health(project)


@app.get("/api/floor")
@app.get("/api/floor/{project}")
async def floor_state(project: str = "") -> dict:
    """Is the factory working? — the platform's answer, for anybody who asks (#144).

    A THIN MAPPING ONTO A NEUTRAL MODULE, deliberately. The nine-rung ladder that produces this
    lived in `panel.html`'s JavaScript, so it was a capability of one screen: a Slack bot asked the
    same question would have had to re-implement it, and the two would have drifted exactly as the
    five computations inside the panel already had (#141). This route derives nothing — every word
    it returns was decided by `openfactory.floor`.

    WHAT THIS ENDPOINT CANNOT ANSWER, and no server can: whether the CLIENT has gone blind. "This
    page has heard nothing for three minutes" is a fact about a socket in somebody's tab. A caller
    wraps that around this; see `openfactory/floor/__init__.py`.

    Scoped like every other floor read (`_scope_of_path` → `actions.FLOOR`), so a product-scoped
    credential is refused here exactly as it is on `/api/projects`.
    """
    from openfactory import floor

    inputs = await floor.gather(want=floor.EVERYTHING)
    return floor.state(inputs, project).as_dict()


@app.get("/api/projects")
def list_projects() -> list[dict]:
    return [
        {
            "name": p.name, "repo_path": p.repo_path,
            "tracker": p.tracker.kind,
            "forge": p.forge.kind if p.forge else p.tracker.kind,
            "ci": p.ci.kind if p.ci else p.tracker.kind,
            "board": p.tracker.options.get("board_number"),
            "enabled": p.enabled,
            # WHY IT TRAVELS WITH THE PROJECT ROW rather than on its own endpoint: `enabled` is
            # already here and the two are read together — "the poller includes this project" and
            # "the poller will refuse every card anyway" is one answer, and splitting it across two
            # requests is how a panel comes to show a green project with a dead queue.
            "box": _box_health(p),
        }
        for p in ProjectRegistry().list()
    ]


class Toggle(BaseModel):
    enabled: bool


@app.post("/api/projects/{name}/enabled", dependencies=_AUTH)
async def set_enabled(name: str, body: Toggle, request: Request) -> dict:
    """Turn the framework on/off for a board — pickup only happens when enabled.

    A mapping onto the `enable` action (C-23), which is what makes the same switch reachable from
    Slack and from `openfactory act` — #51 names "a human in Slack cannot enable a project" as one of the
    two live defects the missing layer caused."""
    outcome = await actions.perform("enable", by=_actor(request), project=name,
                                    enabled=body.enabled)
    _raise_unless_ok(outcome)
    return {"ok": True, "enabled": body.enabled, "message": outcome.message}


class NewProject(BaseModel):
    name: str
    repo_path: str
    #: UNSET, NOT `"github"` (ADR-0049 D2). A model default here is a door answering a question
    #: nobody asked it: the panel's form sends no kind, so every project registered from the panel
    #: was written as GitHub — a path on the operator's own disk included, which then reads as a
    #: repository on github.com that nobody owns. Empty means *derive it from the address*, which
    #: is what `doors.kind_for` is for, and an explicit kind still overrides.
    provider: str = ""
    repo: str | None = None
    board_owner: str | None = None
    board_number: str | None = None


# NO `_AUTH` HERE, AND THAT IS MEASURED. Every read on this panel is gated by `_panel_gate`, which
# asks the same identity provider and accepts the three credential shapes a browser has — Bearer,
# a same-origin COOKIE, `?token=`. `require_auth` reads the Authorization header alone, so the
# first version of this route (which carried it, out of habit) answered 401 to a cookie the
# middleware had just admitted: `/api/projects` 200 and `/api/address` 401 in the same page, with
# the form's reading silently blank. The mutation that removed `_AUTH` survived every test here —
# the middleware answers first — which is how the extra dependency turned out to be decoration
# that only cost something.
@app.get("/api/address")
def read_address(repo_path: str = "", repo: str = "", provider: str = "") -> dict:
    """What the door below would write for this address — the READING the panel's form asks for.

    THE FORM ASKED FOR GITHUB COORDINATES WHATEVER YOU TYPED (ADR-0049 slice 4c). `Repo
    (owner/name)` and a board owner/number sat under every path, including a directory on the
    operator's own disk that has no owner and no board — and a person who filled them because the
    form asked turned their own checkout into a hosted row, which is the one thing `kind_for` was
    moved into `doors.py` to stop.

    SO THE FORM ASKS THE RULE RATHER THAN CARRYING A COPY OF IT. A second implementation in
    JavaScript would be a fourth door — the three that write a row agree since 4a, and a fourth
    that only *shows* what they will do is exactly how a surface comes to promise what the door
    refuses. This route runs `foreign_host` and `kind_for` and nothing else; it writes nothing,
    reads no disk, and answers about the STRING it was handed.

      · `kind` — what every axis would be written as, `""` when the address is refused;
      · `coordinates` — whether `owner/name` and a board apply at all;
      · `refusal` — the door's own sentence, so the form can say it BEFORE the person fills in
        the rest of the modal rather than after.
    """
    try:
        foreign = doors.foreign_host(repo_path, provider=provider)
    except ValueError as exc:
        # A KIND NOBODY IMPLEMENTS, or a shipped kind claiming another's host. `foreign_host`
        # raises it for the command line to print; here it is the same refusal, read by a form.
        return {"kind": "", "coordinates": False, "refusal": str(exc)}
    if foreign:
        return {"kind": "", "coordinates": False, "refusal": doors.foreign_refusal(foreign)}
    kind = doors.kind_for(repo_path, repo=repo, provider=provider)
    # COORDINATES ARE A HOSTED IDEA. `local` names a path, and a path has no owner to name and no
    # board to number — D5's file beside the registry is the board. Anything else is on somebody's
    # host, where the repository has a name this deployment must be told.
    return {"kind": kind, "coordinates": kind != "local", "refusal": ""}


@app.post("/api/projects", dependencies=_AUTH)
def add_project(body: NewProject) -> dict:
    options: dict[str, str] = {}
    if body.board_owner and body.board_number:
        options = {"board_owner": body.board_owner, "board_number": body.board_number}
    # WHOSE HOST IS IT (#162), asked at this door too since D2. It was asked at `project init`
    # and nowhere else, so the same GitLab URL was refused on the command line and written as a
    # GitHub row through the panel — and the row is what hands a github.com credential to
    # whatever host the URL actually names.
    try:
        foreign = doors.foreign_host(body.repo_path, provider=body.provider or "")
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if foreign:
        # THE SENTENCE IS `doors.foreign_refusal`'s (slice 4c) — this door had its own copy of it,
        # and the panel in front of the door had none at all.
        raise HTTPException(status_code=422, detail=doors.foreign_refusal(foreign))
    kind = doors.kind_for(body.repo_path, repo=body.repo or "", provider=body.provider or "")
    if kind == "local":
        # EVERY AXIS, SPELLED (D2) — see `openfactory project add`, which writes the same row. An
        # axis left unwritten inherits `ProviderRef`'s `github` default, and a local project that
        # inherited it would be handed the deployment's GitHub credential.
        axes = {"tracker": ProviderRef(kind="local", repo=body.name),
                "forge": ProviderRef(kind="local", repo=body.name),
                "ci": ProviderRef(kind="none", repo=body.name)}
    else:
        axes = {"tracker": ProviderRef(kind=kind,
                                       repo=body.repo or doors.infer_repo(body.repo_path) or None,
                                       options=options)}
    try:
        ProjectRegistry().add(Project(name=body.name, repo_path=body.repo_path, **axes))
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"ok": True}


@app.get("/api/jobs")
def list_jobs() -> list[dict]:
    jobs: list[dict] = []
    for p in ProjectRegistry().list():
        d = project_log_dir(p)
        if not d.exists():
            continue
        for f in d.glob("*-events.jsonl"):
            evs = _read_events(f)
            if not evs:
                continue
            # tolerate a malformed event line — a single bad event must not 500 the grid
            state = next(
                (e.get("message") for e in reversed(evs) if e.get("kind") == "state"), "?"
            )
            pr = next(
                ((e.get("data") or {}).get("url") for e in reversed(evs)
                 if e.get("kind") == "pr" and (e.get("data") or {}).get("url")),
                None,
            )
            # THE TICKET, NOT ITS LAST PASS (#257). This took the most recent event carrying a
            # cost, and every agent pass emits its own — the executor's note, each `repair N`, the
            # review — so a job with one repair reported the repair alone. Measured on the
            # deployment that reported it: `Cost: $4.0265` on the pull request against
            # `cost_usd: 0.6126` here, for the same job.
            #
            # `None` WHEN NOBODY REPORTED, never `0.0`, which is the rule `_reported_cost` keeps
            # one module over: a harness that emits no price must read as unknown rather than as
            # free, or it wins every cost comparison this column exists to make.
            charged = [(e.get("data") or {}).get("cost_usd") for e in evs]
            charged = [c for c in charged if isinstance(c, (int, float))]
            cost = sum(charged) if charged else None
            jobs.append({
                "project": p.name, "issue": f.name.replace("-events.jsonl", ""),
                "state": state, "updated": evs[-1].get("ts", ""), "events": len(evs),
                "pr_url": pr, "cost_usd": cost,
            })
    jobs.sort(key=lambda j: j["updated"], reverse=True)
    return jobs


def _boxes_are_remote() -> bool:
    """Does this deployment run jobs on a machine the panel cannot see?

    ASKED OF THE BOX'S TRAITS, not of a vendor's cluster variable. It used to answer True for
    `OPENFACTORY_FARGATE_CLUSTER` or a sandbox literally named `fargate` — the panel knowing one
    connector by heart, and blind to any other remote box. Now the deployment's box (the same
    `default_sandbox()` the worker uses, add-ons in view) answers `remote` for itself.

    AN UNKNOWN KIND ANSWERS FALSE, WITH A LINE. Measured before choosing: raising here turns every
    job page on a mistyped deployment into a 500, and the worker already refuses that kind by name
    the moment it tries to start a job — so the panel reads what it has locally and says why."""
    from openfactory.adapters.sandbox.registry import installed_box_traits
    from openfactory.runtime.temporal.io import default_sandbox

    kind = default_sandbox()
    try:
        return installed_box_traits(kind).remote
    except (ValueError, TypeError) as exc:
        # ValueError: a kind nobody installed. TypeError: an add-on whose row does not answer for
        # itself (`_check_row`) — the same configuration defect one layer in, and it was a 500 on
        # every job page while the unknown kind beside it was a warning.
        log.warning("this deployment's box %r is unknown (%s) — the panel reads local journals "
                    "only until it is corrected", kind, exc)
        return False


def _remote_tail(project: str, issue: str, *, quiet: bool = False):
    """The remote box's own event tail (`RemoteBox.tail`), or None SAID OUT LOUD.

    A remote deployment whose add-on is missing used to render an idle feed for ever: the tail's
    import failed, the failure was swallowed into `arns = []`, and an empty feed is what a quiet
    job looks like. The refusal from `remote_box` names the entry point that is absent, and it is
    logged as a WARNING because it is the deployment's configuration, not the weather.

    `quiet` is for a RETRY of a build that already warned (`_StreamTail`): the same line at
    DEBUG, so a stream that backs off does not say the same thing every time it tries again."""
    from openfactory.adapters.sandbox.registry import remote_box
    from openfactory.runtime.temporal.io import default_sandbox

    try:
        return remote_box(default_sandbox()).tail(project, issue)
    except Exception as exc:  # noqa: BLE001 — the panel shows what it has, and says why
        (log.debug if quiet else log.warning)(
            "the remote box's event tail cannot be built for %s#%s (%s) — the panel shows local "
            "events only", project, issue, exc)
        return None


class _StreamTail:
    """The remote tail of ONE event stream: built once, and when it cannot be built, retried on a
    bounded backoff with ONE warning.

    `job_stream` used to ask `_remote_tail` again on every tick while the build failed — a 3-second
    cadence, so a remote deployment missing its add-on (or its cluster variables) logged the same
    WARNING ~28,800 times per open card per day: the log-flood that reader's own comment condemns,
    now at a level somebody pages on. Measured by driving the generator: 5 builds and 5 warnings
    in 5 ticks.

    The schedule is in TICKS of the stream's own loop (one tick = one `fetch_new` cadence), not in
    seconds, so it can be asserted without a clock: retries at 2, 4, 8, … ticks apart, capped at
    `MAX_WAIT`. A build that succeeds after failures says so once at INFO, because the operator
    who read the warning deserves the other half of the story."""

    #: The longest a stream waits between two attempts, in ticks (~15 min at the 3 s cadence).
    MAX_WAIT = 300

    def __init__(self, project: str, issue: str) -> None:
        self.project, self.issue = project, issue
        self.tail = None
        self.failures = 0
        self.next_try = 0

    def get(self, tick: int):
        """The tail, or None — building it only when one is due."""
        if self.tail is not None:
            return self.tail
        if tick < self.next_try:
            return None
        self.tail = _remote_tail(self.project, self.issue, quiet=self.failures > 0)
        if self.tail is None:
            self.failures += 1
            self.next_try = tick + min(2 ** self.failures, self.MAX_WAIT)
        elif self.failures:
            log.info("the remote box's event tail for %s#%s is up after %d failed builds",
                     self.project, self.issue, self.failures)
        return self.tail


def _events(project: str, issue: str) -> list[dict]:
    """The job's events: the local journal, else the remote box's tail when — and only when — the
    box that wrote them is somewhere this panel cannot reach.

    The guard is not an optimisation. Without it, every request for a job that has simply not
    written its first event yet costs an import, a failed credential lookup and an `INFO` line
    saying the remote feed was unavailable. On a `docker compose` install that is every request,
    and a log full of alarms about a service the operator deliberately does not run teaches them
    that log lines are noise — the same cost a false alarm has anywhere else in this platform."""
    local = _read_events(events_file(ProjectRegistry().get(project), issue))
    if local or not _boxes_are_remote():
        return local
    tail = _remote_tail(project, issue)
    if tail is None:
        return local
    try:
        return tail.fetch_new()
    except Exception as exc:  # noqa: BLE001 — the remote feed unreachable → show what we have
        log.info("remote events unavailable for %s#%s (%s) — showing local events only",
                 project, issue, exc)
        return local


# THE WORD IS OWNED BY ONE MODULE (#144). This file used to carry its own literal
# `_ATTENTION` set beside `view.ATTENTION_STATES`, and they had ALREADY DRIFTED: the
# view carried `awaiting_your_merge` and this did not. The route below asks `tv`,
# which it already holds — so there is no second name to edit, not even an alias.


@app.get("/api/attention")
def attention() -> list[dict]:
    """Jobs that need a human — the operator's inbox (A5). One place to see every
    on-hold / needs-refinement / paused / awaiting-approval job across projects."""
    # The engine's list, read where it costs no `temporalio` (#178): this route reads the JOURNAL
    # (`list_jobs()` here is this module's own), so it answers on an install without the extra.
    from openfactory.runtime.temporal.vocabulary import ATTENTION_STATES

    return [j for j in list_jobs() if j.get("state") in ATTENTION_STATES]


def _verdict_of(read: dict, job: dict) -> dict:
    """This platform's own reading of the change a person is being asked about (#149).

    UNREADABLE IS A VALUE, NOT AN ABSENCE. A workflow that will not answer the query is usually one
    whose worker is gone; rendering that as "no review" would tell somebody at a merge gate that
    nothing checked their diff, which is a different and much worse claim than "I could not look".

    `read` IS WHAT `tv.review_verdicts` ANSWERED for the jobs on this screen, and `None` in it is a
    job that did not say inside the read deadline. This made the query itself, raw, once per call;
    the route below says what that cost.
    """
    from openfactory.review import verdict as verdict_read

    wf_id = job.get("workflow_id")
    if not wf_id:
        return verdict_read.headline(None)
    # AND THE ENGINE WENT WITH IT (#178). This asked the workflow itself, which meant importing
    # `runtime.temporal.workflow` — a module that costs `temporalio` — on a route the panel serves
    # on an install without the extra. The read now happens once, in `tv.review_verdicts`, inside
    # `runtime/temporal/` where that import is at home; nothing here reaches the engine, so nothing
    # here has to be guarded against its absence. Do not put the query back at this line.
    raw = read.get(str(wf_id))
    if raw is None:
        return verdict_read.headline(None, unread=True)
    return verdict_read.headline(raw)


@app.get("/api/inbox")
async def inbox() -> list[dict]:
    """THE single 'what needs a human right now' feed — one shape for every channel (panel,
    Slack, Telegram, curl). Each item is self-describing: `kind` says what to present, `options`
    (when present) are the executable choices, and `answer` tells the client exactly how to POST
    the reply. API-first foundation for the future chat bots: read this, present it, POST back."""
    tv, addr, ns = _temporal_or_503()
    try:
        client = await tv.connect()
    except Exception as exc:
        raise HTTPException(
            status_code=503, detail=f"durable engine unreachable: {str(exc)[:150]}"
        ) from exc
    from openfactory.floor.ladder import need_kind

    out: list[dict] = []
    waiting: list[tuple[dict, dict]] = []  # (the job, its item's `review`), filled after the loop
    for j in await tv.list_jobs(client, ns):
        state, act = j.get("state"), (j.get("action") or {})
        items_before = len(out)
        # WHAT THIS PLATFORM'S OWN REVIEWER FOUND, on the one screen where somebody is deciding
        # (#149). It was computed at the REVIEW station, published by a query, and shown nowhere
        # near the gate — so a pull request the review REJECTED and one it approved produced
        # byte-identical cards, and the pilot found out only by asking the tech-lead in words.
        # Read HERE rather than in `list_jobs`: it is one query RPC per item and the inbox is, by
        # construction, only the jobs that need a person.
        #
        # …WHICH WAS TRUE OF THE COMMENT AND NOT OF THE CODE. This line awaited the query for
        # EVERY listed job, before any branch below had decided the job is an item, and one job
        # after another. A query is answered by a WORKER: measured 2026-09-19 on a dev server,
        # four completed jobs that need nobody, with no worker polling, took **116.0 s** to
        # answer `[]` (four times the SDK's own 30 s), and the list's limit is fifty. So the item
        # is built first, around a `review` that is still empty, and the jobs that BECAME items
        # are asked together below the loop, inside one read deadline.
        review: dict = {}
        base = {"project": j.get("project"), "issue": j.get("issue"), "title": j.get("title"),
                "state": state, "note": act.get("note") or "", "pr_url": act.get("pr_url"),
                # STRUCTURED AND RENDERED, both: a client that wants to lay it out itself has the
                # findings, and one that just prints gets a sentence nobody had to compose.
                "review": review,
                # WHEN IT WAKES BY ITSELF, and when it was parked (#140). Every channel could say
                # a job was paused and none could say until when, so a 30-minute backoff and a job
                # nobody will ever resume read identically. `wakes_at` is `None` for a park that
                # holds until a human answers — which is a real answer, not a missing one.
                "parked_at": act.get("parked_at"), "wakes_at": act.get("wakes_at"),
                # The vendor's own claim, kept apart from ours on purpose: this workflow refuses
                # to obey it (see `_pause_backoff`), so no reader may present it as the wake-up.
                "retry_at": act.get("retry_at")}
        act_url = f"/api/temporal/act/{j.get('project')}/{j.get('issue')}"
        # THE WORD COMES FROM THE FLOOR (#164); the branches below decide only what can be
        # ANSWERED, which is this endpoint's own knowledge. Two vocabularies for "why does this
        # need a person" is two answers about one job — measured, they disagreed on
        # `rate_limit` and on which of `wedged`/`decision` wins.
        kind = need_kind(j)
        if act.get("decision"):  # a design/process decision with concrete options
            out.append({**base, "kind": kind, "decision": act["decision"],
                        "answer": {"method": "POST", "url": act_url,
                                   "body": {"action": "resume", "choice": "<option key>"}}})
        elif state == "awaiting_your_merge":  # a PR the human must answer (#68)
            # A QUESTION WITH EXECUTABLE OPTIONS, not prose. This used to answer
            # {"how": "review + merge the PR, then it lands on its own"} — which was true and
            # useless: it sent the reader to github.com, which is the work this product exists to
            # remove, and "then it lands on its own" was not even accurate, because the human path
            # never self-heals. The gate now has three real answers (ADR-0038 D2: a wait is a
            # question, never a state).
            options = [
                {"key": "merge", "label": "Merge",
                 "consequence": "lands the PR — the forge may still refuse it if "
                                "branch protection says so, and the job will say why"},
                {"key": "adjust", "label": "Adjust", "needs_text": True,
                 "consequence": "one more agent pass on the SAME branch and PR, "
                                "against your own words"},
                {"key": "discard", "label": "Discard",
                 "consequence": "closes the PR without merging and frees the floor; "
                                "the branch and its commits are untouched"},
            ]
            # THE FOURTH ANSWER, AND ONLY WHERE IT IS REAL (#181). `adjust` fixed what the review
            # rejected and nothing could ask whether it worked, so the person was left merging on
            # their own reading of the diff — the work an independent review exists to remove.
            # WHETHER IT EXISTS IS THE FLOOR'S ANSWER, NOT THIS SCREEN'S: the job knows whether it
            # ran with review on, whether a reviewer ever spoke and whether the cap is spent, and
            # a button offered where none of that holds is advice nobody can take.
            if act.get("can_review"):
                options.insert(1, {
                    "key": "review", "label": "Re-review",
                    "consequence": "reads the pull request AS IT STANDS and replaces the verdict "
                                   "on this card — it changes no code, and it costs a model pass",
                })
            out.append({**base, "kind": kind,
                        "options": options,
                        "answer": {"method": "POST",
                                   "url": "/api/act/<merge|adjust|discard|review>",
                                   "body": {"params": {"project": j.get("project"),
                                                       "issue": j.get("issue"),
                                                       "instruction": "<adjust only>"}}}})
        elif state == "awaiting_prod_approval":  # a prod release gate
            out.append({**base, "kind": kind,
                        "answer": {"method": "POST",
                                   "url": f"/api/temporal/approve/{j.get('project')}/{j.get('issue')}"}})
        elif state == "paused":  # rate-limited — auto-resumes, but retry/skip are available
            out.append({**base, "kind": kind, "answer": {"method": "POST", "url": act_url,
                        "body": {"action": "resume | skip"}}})
        elif j.get("wedged"):
            # A JOB THAT IS RUNNING AND CANNOT MOVE (#140). Its `state` is `running`, so it
            # matched none of the branches above and none of `_ATTENTION` — a wedged job produced
            # ZERO inbox items. It was visible only to somebody looking at that one project's page
            # in the panel, and invisible to Slack, to `/api/inbox` and to every other channel, on
            # the one surface whose whole job is "does anything need me?".
            #
            # It holds the floor slot while it sits there, so nothing else starts either: the
            # quietest possible way for a factory to stop.
            out.append({**base, "kind": kind,
                        "note": act.get("note") or ("it has been running for hours with no gate "
                                                    "and no park — nothing left can advance it"),
                        "options": [{"key": "stop", "label": "Stop — free the floor",
                                     "consequence": "ends the run and puts the card back; the "
                                                    "branch and any commits are untouched"}],
                        "answer": {"method": "POST", "url": "/api/act/stop",
                                   "body": {"params": {"project": j.get("project"),
                                                       "issue": j.get("issue"),
                                                       "reason": "<why>"}}}})
        elif state in tv.ATTENTION_STATES:  # a generic impediment — resume (retry) or skip (free the floor)
            out.append({**base, "kind": kind,
                        "options": [{"key": "resume", "label": "Retry from the top"},
                                    {"key": "skip", "label": "Skip — free the floor"}],
                        "answer": {"method": "POST", "url": act_url,
                                   "body": {"action": "resume | skip"}}})
        if len(out) > items_before:
            waiting.append((j, review))
    # EVERY ITEM SHARES ITS `review` WITH `base` (`{**base}` copies the reference), so filling it
    # here fills it on the item. One job that does not say is UNREADABLE on its own card, and the
    # rest of the inbox still goes out.
    read = await tv.review_verdicts(client, [j for j, _review in waiting])
    for j, review in waiting:
        review.update(_verdict_of(read, j))
    return out


@app.get("/api/budget")
def api_budget() -> dict:
    """The API budget of the trackers this deployment reads — one row per credential, plus the
    ONE row a single sentence renders (`summary`), so the panel can SHOW when the engine is
    throttled — no more 'nothing is happening' with no reason.

    IT WAS `/api/github/ratelimit`, a vendor-named route that ran `gh` for every deployment and
    answered `remaining: null` for BOTH "unreadable" and "this vendor has no budget". Every row
    now carries a `state` — `ok | low | unread | not_reported` — so a Jira deployment is told the
    truth ("no budget on this vendor") instead of a probe failure, and a broken `gh` on a GitHub
    deployment is told `unread` instead of nothing. Read through `openfactory.floor`, the same
    definition `/api/floor` judges by; this route only renders it."""
    from openfactory.floor.reading import budget_summary, budgets

    rows = budgets()
    return {"summary": budget_summary(rows), "rows": rows}


def _project_or_404(project: str) -> Project:
    """The registered project — or a 404 in ONE sentence, for every route that takes `{project}`.

    THE FIFTH ROUTE FORGOT (#204). `registry.get` refuses a name it does not hold with a
    `KeyError`, and four routes each caught it by hand, in three spellings — `no project called
    'x'`, `no project called 'x' here`, `no project named 'x' in this deployment`. `promote_info`
    caught only `FileNotFoundError`, so the production-approval dialog was told "500 Internal
    Server Error" about a project somebody had renamed while a card waited for its approval, and
    the page printed that as the panel's own fault. A route that needs the project asks here; the
    sweep in `tests/test_a_project_nobody_registered_is_never_a_500.py` calls every `{project}`
    route with a name nobody registered, so the next one cannot forget quietly.

    NOT THE ACTION LAYER'S SENTENCE, which also lists what IS registered (`catalog._project`).
    That roster is the remedy for a typo in a command somebody typed. These routes are reached by
    a page or a stale bookmark — there is no typo to correct, and the sentence two of the four
    already gave says all there is to say."""
    try:
        return ProjectRegistry().get(project)
    except KeyError:
        raise HTTPException(
            status_code=404, detail=f"no project named {project!r} in this deployment") from None


@app.get("/api/board/{project}")
def board_view(project: str, card: str = "", pr: str = "") -> dict:
    """This project's board, through the ports — one read, for every kind (ADR-0049 D6).

    ONE ROUTE, AND THE REASON IS THE THREE-SECOND TICK. The panel already polls the floor; a board
    that fanned out into a request per column, or per card, would multiply that against somebody's
    hosted API every time an operator left the overlay open. So this is opened on demand, answers
    the whole board, and takes an optional `card` for the one card a person actually opened.

    IT COMPARES NO PROVIDER KIND, which is the panel's standing rule. What differs between a board
    in a file on this machine and a board behind somebody's API is how often it may be re-read, and
    that is the ROW's answer (`Watchable.poll_seconds`), not a name this surface matches on. A row
    that does not implement it is simply not watched.

    THE THREE ANSWERS TRAVEL. `None` for the columns or the cards means the board could not be
    read, `[]`/`{}` means it was read and is empty, and the page renders those differently — the
    distinction the whole read side is built on, and the one a surface destroys by being helpful.
    """
    from openfactory.adapters.board import build_board
    from openfactory.adapters.board.base import Watchable
    from openfactory.adapters.tracker.registry import build_tracker
    from openfactory.credentials import deployment_tracker_token, tracker_token_for

    proj = _project_or_404(project)
    token = tracker_token_for(proj) or deployment_tracker_token(proj)
    board = build_board(proj, token=token)
    tracker = build_tracker(proj, token=token)
    if board is None:
        # A DEPLOYMENT CAN RUN ON TICKETS ALONE, which is a first-class answer on this axis and not
        # an error: the page says so instead of showing an empty board somebody will try to drag on.
        return {"project": proj.name, "columns": None, "cards": None, "poll_seconds": None,
                "board": False, "card": None}

    names = board.column_names()
    placed = board.columns()
    summaries = tracker.list_tickets(state="open")

    cards = None
    if placed is not None and summaries is not None:
        # THE BOARD SAYS WHERE, THE TRACKER SAYS WHAT. Two ports, one row on the page, and the seam
        # stays visible: a card the board does not place is still listed, with no column, because
        # dropping it would hide work from the person looking for it.
        cards = [{"ref": s.ref, "column": placed.get(s.ref, ""), "title": s.title,
                  "labels": list(s.labels or []), "updated_at": s.updated_at or ""}
                 for s in summaries]

    detail = None
    if (wanted := (card or "").strip()):
        detail = _card_detail(tracker, wanted)

    proposal = None
    if (asked := (pr or "").strip()):
        proposal = _pr_detail(proj, asked)

    return {
        "project": proj.name,
        "columns": names,
        "cards": cards,
        # The row's own answer, or nothing. `getattr` is not used here: the protocol is the
        # question, and `isinstance` is how a row answers it.
        "poll_seconds": board.poll_seconds() if isinstance(board, Watchable) else None,
        "board": True,
        "card": detail,
        "pr": proposal,
    }


def _pr_detail(project, ref: str) -> dict:
    """One pull request, for its own page (ADR-0049 D4/D6).

    THROUGH THE FORGE PORT, so this page renders a GitHub pull request as readily as one that
    lives in a file — `pr_body`, `pr_diff` and `pr_status` are the port's, and the last two keep
    their `None` for *could not look*.

    THE REFUSAL IS WHY THIS PAGE EXISTS AT ALL. When a merge is refused the person needs the words
    the forge used, not this platform's paraphrase: git names the file that is in the way, and the
    reader is standing in the repository it is about. A row that has none answers `""`, which is
    the honest answer for every hosted vendor."""
    from openfactory.adapters.forge.registry import build_forge
    from openfactory.credentials import deployment_forge_token, forge_token_for

    forge = build_forge(project, token=forge_token_for(project) or deployment_forge_token(project))

    def _ask(what, *, default=None):
        try:
            return what()
        except Exception:  # noqa: BLE001 — a page must never take the cockpit down
            log.info("the pull-request page could not read %r on %s", ref, project.name,
                     exc_info=True)
            return default

    state = _ask(lambda: forge.pr_status(pr=ref), default="")
    return {
        "ref": ref,
        "state": state,
        "readable": bool(state),
        "body": _ask(lambda: forge.pr_body(pr=ref)),
        "diff": _ask(lambda: forge.pr_diff(pr=ref)),
        # THE PORT DOES NOT CARRY THESE, AND THAT IS WHY THEY ARE ASKED DEFENSIVELY. A forge whose
        # pull requests live in a file can hand back the review events it recorded and the sentence
        # it wrote; every hosted row answers neither, and the page renders what it has.
        "events": _ask(lambda: getattr(forge, "pr_events", lambda **_: [])(pr=ref), default=[]),
        "refused": _ask(lambda: getattr(forge, "pr_refusal", lambda **_: "")(pr=ref), default=""),
        # WHETHER THIS PAGE MAY LAND IT ITSELF (ADR-0049 D9). The Merge on a card answers the
        # DURABLE gate — the job is parked inside its merge watch and the engine is holding it —
        # and a pull request that no job is waiting on has no gate to answer: one `openfactory
        # run`, one `poll` on a machine with no engine, or a card whose job ended at `pr_open`.
        # For THIS forge the fast-forward is the whole act, so the page offers it directly; for a
        # hosted row it is not, because the merge there is the workflow's — CI, the promotion
        # chain and the gate all live on the other side of it.
        "can_merge_here": (getattr(getattr(project, "forge", None), "kind", "") == "local"
                           and state == "open"),
    }


def _opened_by_product(body: str) -> str:
    from openfactory.product.authoring import filed_by_the_product_role

    return filed_by_the_product_role(body)


def _card_detail(tracker, ref: str) -> dict:
    """One card's body and thread — the drawer's read.

    `comments` KEEPS ITS THREE ANSWERS all the way to the browser: `None` could not be read, `[]`
    nobody has commented. The page renders those differently on purpose, because the reader of a
    thread is deciding whether something has already been tried, and an unreadable thread shown as
    an empty one is how it concludes nobody has looked."""
    try:
        ticket = tracker.get_ticket(ref)
    except Exception:  # noqa: BLE001 — a card that cannot be read is an answer, not a 500
        log.info("the board could not read card %r — the page says so", ref, exc_info=True)
        return {"ref": ref, "readable": False, "body": "", "comments": None, "title": ""}
    thread = tracker.comments(ref)
    return {
        "ref": ref,
        "readable": True,
        # WHETHER IT IS STILL OPEN (#150). The drawer offers Close on an open card and Reopen on a
        # closed one, and until this field existed the page could not tell them apart — it would
        # have had to offer both and let the tracker refuse one, which is a button that cannot work.
        "state": getattr(ticket, "state", "") or "open",
        # WHO MAY CHANGE IT (#150). A card the product role opened is the product owner's, and the
        # drawer shows no button the row would refuse. The row decides; this only spares the click.
        "opened_by_product": _opened_by_product(getattr(ticket, "raw", "") or ""),
        "title": ticket.title,
        "body": getattr(ticket, "raw", "") or "",
        "comments": None if thread is None else [
            {"author": c.author, "body": c.body, "created_at": c.created_at} for c in thread],
    }


@app.get("/api/loops/{project}")
def open_loops(project: str) -> dict:
    """Everything the agents are still waiting on (ADR-0021) — the VISIBLE list.

    This surface is load-bearing, not decorative. The chase policy is deliberately bounded to one
    reminder, and the ledger's own docstring answers continued silence with "a person looking at
    the list" — a list which, until this endpoint, existed nowhere: after its single chase, an
    unacknowledged finding was alive in the store and visible to nothing. A review finding that
    can only be closed by a human `ack` NEEDS a place where that human can see it is still open."""
    from openfactory.memory import store as loop_store
    from openfactory.memory.ledger import waiting

    loops = waiting(loop_store.read(project))
    return {
        "project": project,
        "waiting": [
            {
                "kind": x.kind, "subject": x.subject, "about": x.about, "owner": x.owner,
                "state": x.state, "opened": x.ts, "chased": x.chased_ts,
                "context": x.context,
            }
            for x in loops
        ],
    }


@contextlib.contextmanager
def _readable_store(what: str):
    """Turn an unreadable message store into a 503 that SAYS SO (#126).

    503, not 200-with-nothing and not 409. Every route this wraps is one half of a human gate: the
    inbox that shows a question, and the click that answers one. An outage used to render as a
    factory with nothing to say and — for a question the operator could still see on their screen —
    as "that question is not open; it was answered already", which blames a person for a decision
    nobody made. A status a client can retry, with a sentence naming the store, is the honest
    answer to "I could not look".
    """
    from openfactory.observability.query import StoreUnreadable

    try:
        yield
    except StoreUnreadable as exc:
        log.error("the message store would not answer while trying to %s: %s", what, exc)
        raise HTTPException(
            status_code=503,
            detail=f"could not {what} — the message store did not answer. Nothing was lost and "
                   f"nothing was decided; try again in a moment.") from exc


@app.get("/api/messages/{project}")
def channel_messages(project: str) -> dict:
    """What the factory has said to this project, and what it is waiting to hear back (C-25).

    THE PANEL'S HALF OF THE CHANNEL AXIS. Everything this platform produces goes to
    `ChannelAdapter.say`, and until the panel became a provider there was exactly one adapter
    behind it — so a deployment with no Slack workspace got the messages written, delivered and
    dropped. Not a quieter factory: a silent one.

    Pull, deliberately. There is no socket here and no push; the browser asks, which is also why
    an operator who never opens the panel is not reached. That limitation is real and is why a
    deployment needing to reach somebody who is NOT looking still wants a push channel."""
    from openfactory.memory import messages as channel

    with _readable_store("read this project's messages"):
        history = channel.read(project)
    return {
        "project": project,
        "messages": [
            {"kind": m.kind, "text": m.text, "ts": m.ts, "channel": m.channel,
             "token": m.token, "answer": m.answer, "by": m.by}
            # `told` rows travel with the rest: the operator's own turns are part of the thread,
            # and the panel needs them to render a conversation rather than a monologue (#123).
            for m in history
        ],
        "pending": [
            {"token": q.token, "text": q.text, "ts": q.ts,
             "options": [{"key": "approve", "label": q.approve},
                         {"key": "reject", "label": q.reject}],
             "answer": {"method": "POST", "url": f"/api/messages/{project}/answer",
                        "body": {"token": q.token, "answer": "approve | reject"}}}
            for q in channel.pending(project)
        ],
        # THE STAGED SUGGESTION, SERVED RATHER THAN REMEMBERED BY THE TAB (#123). It used to live
        # only in the browser array that produced it, so a refresh at the moment the platform was
        # waiting on a decision discarded that decision silently.
        #
        # WHETHER IT MAY STILL BE PRESSED IS DECIDED HERE, not in the browser. The rules —
        # superseded, answered, expired — are a fold over the same append-only rows, and a second
        # copy of them in JavaScript is the kind of second spelling this codebase keeps paying
        # for. `reason` is non-empty for one that must be shown and NOT offered: a suggestion that
        # quietly stops working teaches the same lesson as one that vanishes.
        "suggestion": _staged_suggestion(project, channel),
    }


def _labels_for(action: str) -> dict[str, str]:
    """What each parameter of `action` is, or `{}` for a row this deployment does not have."""
    spec = actions.CATALOG.get(action)
    return spec.described if spec else {}


def _staged_suggestion(project: str, channel) -> dict | None:
    """What the tech-lead last proposed, and whether a person may still act on it.

    ITS OWN GUARD, not its caller's. This runs after `channel_messages` has already read the
    history, OUTSIDE that `with` — so a store that failed on this second read escaped as a 500
    while the first read was carefully turned into a 503. Found by the guard for this card rather
    than by looking, which is the point of deriving it from the app instead of listing routes."""
    with _readable_store("read what the tech-lead is proposing"):
        found = channel.staged(project)
    if found is None:
        return None
    message, reason = found
    proposal = channel.read_suggestion(message)
    if proposal is None:  # pragma: no cover — `staged` only returns rows that decode
        return None
    return {
        "token": message.token, "ts": message.ts,
        "action": proposal[0], "issue": proposal[1],
        # WHAT THE BUTTON WILL ACTUALLY DO (#170). Approving `adjust #87` without seeing the
        # instruction is approving a blank cheque — the panel renders these beside the verb.
        "params": proposal[2],
        # AND WHAT EACH ONE IS, from the catalogue row (#172). The page paints `labels[k] || k`;
        # resolving it here is what keeps the panel from growing its own opinion about what an
        # `instruction` is — and what lets a client's own front end render the same card without
        # re-implementing the vocabulary.
        "labels": _labels_for(proposal[0]),
        "live": not reason, "reason": reason,
        "act": {"method": "POST", "url": f"/api/messages/{project}/suggestion",
                "body": {"token": message.token}},
    }


@app.post("/api/messages/{project}/answer", dependencies=_AUTH)
def answer_channel_message(project: str, body: dict, request: Request) -> dict:
    """A person answering a question the factory asked on the panel.

    THE TOKEN IS THE SUBJECT, not the position in a list. It identifies what the reader was SHOWN,
    so an answer arriving after the staged proposal changed cannot be applied to its replacement —
    the difference between approving a proposal and approving something else in its name.

    Refuses an answer to a question that does not exist or is already answered, rather than
    recording it: a second click on a stale page must not read as a second decision.

    WHO ANSWERED IS RESOLVED, NEVER DECLARED (adversarial review of C-25/C-26). The first
    version read `by` from the request body: the panel sent none — so every answer's audit row
    named nobody — and any caller holding a panel credential could write somebody ELSE's name
    into the append-only record, the precise spoofing `_subject`'s named-person rule exists to
    prevent. The body's `by` is now ignored; identity comes from the credential, and an
    anonymous caller may at most label itself via X-OpenFactory-Actor, which carries no id."""
    from openfactory.memory import messages as channel

    token = str((body or {}).get("token") or "").strip()
    answer = str((body or {}).get("answer") or "").strip().lower()
    who = _subject(request)
    by = who.id or who.display
    if not token:
        raise HTTPException(status_code=400, detail="which question — the token is missing")
    if answer not in ("approve", "reject"):
        raise HTTPException(
            status_code=400,
            detail=f"an answer is 'approve' or 'reject', not {answer!r} — a question with two "
                   f"buttons cannot be answered with a third thing")
    # THE READ COMES FIRST AND IT MAY FAIL OUT LOUD (#126). This `if` used to read an unreadable
    # store as an EMPTY pending list, so an outage answered a person's click with "it was answered
    # already" — the platform inventing a decision, in a sentence that blames them for it.
    with _readable_store("check that question"):
        open_now = [q.token for q in channel.pending(project)]
    if token not in open_now:
        raise HTTPException(
            status_code=409,
            detail="that question is not open — it was answered already, or it belongs to another "
                   "project. Nothing was recorded.")
    # A STAGED PRODUCT PROPOSAL RESOLVES THROUGH THE SAME GATE THE SLACK CLICK USES (C-33, #70).
    # Its token carries a `|fingerprint`; a plain question's does not. The staging is DURABLE now
    # — remember() mirrors every proposal into this store with a frozen payload, and the gate's
    # pending_for/consume read and record through it — so this resolution works across processes:
    # the first wiring of this branch read another process's memory and was reverted for it.
    #
    # NO LONGER A REACH INTO THE VENDOR PACKAGE (#105). The EXECUTOR of a confirmation moved to
    # `openfactory/product/confirm.py`, so this route calls the core gate directly and the documented
    # exception this file used to carry in `test_provider_seams` is deleted — the panel and the
    # Slack click now run the SAME function rather than the panel running Slack's.
    # AUTHORIZATION: `may_act` reads `project.product.admins`, which holds the subject ids the
    # deployment's surfaces mint — panel ids for a panel deployment. Registry configuration, not
    # code.
    if "|" in token:
        from openfactory.product import confirm as staged_gate

        proj = _project_or_404(project)
        code, sentence = staged_gate.answer_staged(
            proj, token=token, approved=(answer == "approve"), user=by, via="panel")
        if code == "unauthorized":
            raise HTTPException(status_code=403, detail=sentence)
        if code in ("gone", "replaced", "expired"):
            channel.answer(project, token=token, answer=answer, by=by)  # clears the pending list
            raise HTTPException(status_code=409, detail=sentence)
        # `consume` already recorded the durable answer row inside the gate — recording it again
        # here would double the append-only history for one decision
        return {"project": project, "token": token, "answer": answer, "by": by,
                "outcome": code, "message": sentence}
    if not channel.answer(project, token=token, answer=answer, by=by):
        raise HTTPException(
            status_code=503,
            detail="the answer could not be recorded, so nothing was decided — try again")
    return {"project": project, "token": token, "answer": answer, "by": by}


@app.post("/api/messages/{project}/suggestion", dependencies=_AUTH)
async def approve_suggestion(project: str, body: dict, request: Request) -> JSONResponse:
    """A person approving the one action the tech-lead proposed (#123).

    THE WHOLE GESTURE IN ONE PLACE. The panel used to press this by posting to `/api/act/<verb>`
    with a verb it had remembered in a JavaScript array — so the approval was a fresh, unattached
    action, the thread kept no record that a decision had been made, and a refresh in between lost
    the proposal entirely.

    IT EXECUTES THROUGH `actions.perform`, exactly like every other door. The scope and admin check
    are applied to the credential that pressed the button, not to the one that composed the
    suggestion — a credential that could not resume a job cannot approve a proposal to resume it,
    even one addressed to somebody else.

    THE TOKEN IS THE SUBJECT, the rule this file already states for the product gate: it names WHAT
    was proposed, about which ticket, and when. An approval that arrives after the tech-lead has
    proposed something else is refused rather than applied to the replacement, and a second click
    on a stale page is refused rather than read as a second decision.
    """
    token = str((body or {}).get("token") or "").strip()
    if not token:
        raise HTTPException(status_code=400, detail="which suggestion — the token is missing")

    # THE SEQUENCE LIVES IN THE ACTION LAYER (#156). It used to live here, and the day the chat
    # learned to accept a proposal in words there would have been two implementations of
    # `perform` → retire the button → put the outcome in the thread. This route is the mapping
    # onto it, like every other door.
    outcome = await actions.run_staged(project=project, by=_actor(request), token=token)
    if not outcome.ok and outcome.code in (actions.CONFLICT, actions.UNAVAILABLE):
        raise HTTPException(status_code=_STATUS[outcome.code], detail=outcome.message)
    payload: dict[str, object] = {"ok": outcome.ok, "message": outcome.message,
                                  "code": outcome.code, "data": dict(outcome.data),
                                  "token": outcome.data.get("token", token),
                                  "action": outcome.data.get("action"),
                                  "issue": outcome.data.get("issue")}
    if not outcome.ok:
        payload["detail"] = outcome.message
    return JSONResponse(payload, status_code=_STATUS.get(outcome.code, 200))


@app.get("/api/coordinator/messages")
async def coordinator_messages() -> list[dict]:
    """The tech-lead coordinators' recent narrated updates (pickup / merge / deploy) — the panel
    polls this and toasts what's new; the SAME feed a future Slack/PO bot reads (API-first)."""
    tv, addr, ns = _temporal_or_503()
    try:
        client = await tv.connect()
    except Exception as exc:
        raise HTTPException(
            status_code=503, detail=f"durable engine unreachable: {str(exc)[:150]}") from exc
    return await tv.coordinator_messages(client)


# ── the live stream ──────────────────────────────────────────────────────────────────────────────
#
# `channel_messages` says of itself: *"Pull, deliberately. There is no socket here and no push;
# the browser asks."* That was an honest limitation and it is the one a client feels first — the
# panel polled the AGENT CONVERSATION every fifteen seconds, so a reply typed by the tech-lead
# sat invisible for up to fifteen seconds while somebody watched the screen. A chat that lags
# like that does not read as slow, it reads as broken.
#
# SERVER-SIDE DIFFING, NOT AN EVENT BUS, and the choice is deliberate rather than lazy. The
# producers (the worker, the coordinator, the tech-lead) are OTHER PROCESSES that write to a
# store; a true bus between them and the panel is a queue, a broker and a delivery guarantee —
# a change to every producer for a benefit the reader alone can have. So one watcher per
# connection reads the same store the endpoints read, at a tick nobody can perceive, and pushes
# only what CHANGED. The browser stops asking; the latency stops being visible.
#
# THE FALLBACK IS THE POINT, NOT THE FEATURE. A socket dies for reasons no code here controls —
# a proxy that does not pass Upgrade, a laptop lid, an App Runner idle timeout. This platform's
# headline invariant is that nothing stalls in silence, and a chat that quietly stopped receiving
# would be the purest possible violation of it: the screen looks fine and the factory is talking
# to nobody. So the client falls back to polling AND SAYS SO, and the server sends a `bye` frame
# with a reason whenever it can.

#: How often the watcher re-reads the store. Two seconds: fast enough that a reply feels immediate
#: and slow enough that a dozen panels open on a laptop deployment cost nothing measurable. The
#: read is a small file, not a query.
_STREAM_TICK = 2.0


def _stream_snapshot(project: str) -> dict:
    """Everything the panel watches, as one comparable value. Never raises.

    A failure here must not kill the socket — it must be REPORTED as an unreadable section, for
    the reason every port in this codebase separates `None` from `[]`: a chat that renders empty
    because the store could not be read is a claim about the conversation, and the truth is a
    claim about us.
    """
    out: dict = {}
    try:
        out["projects"] = list_projects()
    except Exception as exc:  # noqa: BLE001 — a broken registry read must not end the stream
        log.warning("stream: could not read the projects (%s)", str(exc)[:160])
        out["projects"] = None
    if project:
        try:
            out["chat"] = channel_messages(project)
        except Exception as exc:  # noqa: BLE001
            log.warning("stream: could not read %s's messages (%s)", project, str(exc)[:160])
            out["chat"] = None
    return out


# ── ONE READ, MANY SUBSCRIBERS ──────────────────────────────────────────────────────────────────
#
# EVERY CONNECTED BROWSER USED TO RUN ITS OWN LOOP (#145). This endpoint's docstring claimed "one
# backend poll feeds every connected client" and the code did the opposite: `gen()` was defined
# inside the handler, so N open tabs meant N registry reads and N store reads every two seconds,
# for ever. That is invisible with one operator and untenable the moment a customer connects a
# dashboard of their own — which is the thing this API is being opened up for.
#
# So the shared work is done ONCE, here, and handed to whoever is listening. What stays per
# subscriber is only what differs per subscriber: which project they are watching, and what they
# have already been told.
#
# NOT AN EVENT BUS, and that is still deliberate. The producers (the worker, the coordinator, the
# tech-lead) are OTHER PROCESSES writing to a store; a true bus between them and the panel is a
# queue, a broker and a delivery guarantee. This is one watcher reading the same store the
# endpoints read — the change is that there is now one of it rather than one per tab.
class _Broadcast:
    """The panel's shared reader. Started on the first subscriber, stopped after the last."""

    def __init__(self) -> None:
        self._subs: set[asyncio.Queue] = set()
        self._task: asyncio.Task | None = None
        #: Per project, the last snapshot read — so two people watching the same project cost one
        #: read, and a third watching another costs one more, not one per tab.
        self._seen: dict[str, dict] = {}

    def subscribe(self) -> asyncio.Queue:
        # BOUNDED. A subscriber whose socket has stalled must not grow a queue until the process
        # dies; it loses frames instead, and the next full snapshot repairs it.
        q: asyncio.Queue = asyncio.Queue(maxsize=8)
        self._subs.add(q)
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._run())
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        self._subs.discard(q)
        if not self._subs and self._task is not None:
            self._task.cancel()
            self._task = None

    def wants(self, project: str) -> None:
        """Somebody started watching a project. Read it on the next tick."""
        self._seen.setdefault(project, {})

    async def _run(self) -> None:
        while self._subs:
            try:
                for project in list(self._seen):
                    snap = await asyncio.to_thread(_stream_snapshot, project)
                    if snap != self._seen.get(project):
                        self._seen[project] = snap
                        self._publish(project, snap)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 — one bad tick must not end the fan-out for
                # everybody. Named rather than swallowed: a reader that dies silently here looks
                # exactly like a factory with nothing to report.
                log.warning("the panel broadcast tick failed (%s)", str(exc)[:200])
            await asyncio.sleep(_STREAM_TICK)

    def _publish(self, project: str, snap: dict) -> None:
        for q in list(self._subs):
            try:
                q.put_nowait((project, snap))
            except asyncio.QueueFull:
                # A stalled subscriber drops this frame. It is repaired by the next snapshot it
                # does read, which is why every frame carries the whole section rather than a
                # delta against something the client may have missed.
                log.debug("a panel subscriber is not keeping up; dropping a frame")


_broadcast = _Broadcast()


@app.websocket("/api/stream")
async def stream(ws: WebSocket) -> None:
    """Push what changed, as it changes. `?token=` + optional `?project=`.

    AUTHENTICATED HERE, EXPLICITLY, AND THAT IS NOT BELT-AND-BRACES. `_panel_gate` is an
    `@app.middleware("http")`, and Starlette's own first line is `if scope["type"] != "http":
    await self.app(...)` — a WebSocket bypasses it entirely. Mounting this route without its own
    check would have put every project name, every job and every word the factory has said to a
    client behind a URL with no credential at all, on the same service whose HTTP half is
    correctly gated. Read in the source before writing this, not assumed.

    The client may re-subscribe at any time by sending `{"project": "<name>"}` — opening a
    project's cockpit changes what it wants without dropping the socket.
    """
    # THE GATE THE MIDDLEWARE CANNOT SEE IS ASKED, NOT WRITTEN AGAIN. This was the rule copied out
    # by hand, and a copy checks what its author remembered: first identity and not scope (#145);
    # then, measured on 2026-09-19, identity and scope of a DIFFERENT credential — `?token=`, else
    # the cookie, never the header — so the socket and `GET` gave seven different answers to
    # thirteen presentations. It also logged no `DENIED_SCOPE_READ`, remembered no credential when
    # the panel happened to be open, and let a provider's exception escape with whatever it quotes.
    # So the open is the watch's FIRST ask: the same function, path, credential and failure
    # handling as every ask after it. Refused BEFORE `accept()` — the server answers the upgrade
    # with a 403 and no socket ever exists — with the codes the watch closes on below.
    #
    # THE DOOR'S TWO REFUSALS SURVIVE THE MOVE, because the verdict renders `_admission` (which
    # the hand-written copy had just been rewritten to call): a store that cannot be read is the
    # gate's 503, which maps to `unavailable` and closes 1011 — never 1008, never "signed out" —
    # and a credential scoped away from the floor is its 403, closed 1008 and logged
    # `DENIED_SCOPE_READ`, which the copy never wrote.
    watch = _CredentialWatch(ws.url.path, _credential_of(ws))
    refused = await watch.asked()
    if refused is not None:
        await ws.close(code=_close_code(refused["why"]), reason=refused["why"])
        return


    await ws.accept()
    project = (ws.query_params.get("project") or "").strip()
    last: dict = {}
    queue = _broadcast.subscribe()
    _broadcast.wants(project)

    async def _resubscribe() -> None:
        """Follow the client between projects without dropping the socket."""
        nonlocal project, last
        while True:
            raw = await ws.receive_text()
            try:
                asked = json.loads(raw)
            except ValueError:
                continue
            if isinstance(asked, dict) and "project" in asked:
                project = str(asked.get("project") or "").strip()
                last = {}  # everything is new to this subscriber
                _broadcast.wants(project)

    # …AND IT IS ASKED AGAIN WHILE THE SOCKET IS OPEN (#208). The handshake above is this
    # socket's only gate, and a socket outlives a session by as long as the tab stays open: it
    # went on pushing the project list and a project's conversation after `/auth/logout`. Same
    # watch as the event streams — the one the handshake asked. IT SPEAKS THROUGH THE
    # SUBSCRIBER'S OWN QUEUE, so the loop below stays the one place this socket is written to
    # and ended from — a second task closing it would leave that loop waiting on a queue for ever.
    async def _until_the_credential_ends() -> None:
        while True:
            await asyncio.sleep(watch.seconds_left())
            ended = await watch.ended() if watch.due() else None
            if ended is None:
                continue
            if queue.full():  # a stalled subscriber still hears the goodbye: a frame makes room
                queue.get_nowait()
            queue.put_nowait((_CREDENTIAL_ENDED, ended))
            return

    reader = asyncio.create_task(_resubscribe())
    watcher = asyncio.create_task(_until_the_credential_ends())
    try:
        # THE FIRST FRAME IS A FULL SNAPSHOT, so a client that connects mid-conversation renders
        # immediately instead of waiting for the next thing to change. A stream that only carries
        # deltas makes an empty screen indistinguishable from a quiet factory.
        await ws.send_text(json.dumps({"kind": "hello", "tick": _STREAM_TICK}))
        first = await asyncio.to_thread(_stream_snapshot, project)
        await ws.send_text(json.dumps({"kind": "update", "project": project, **first}))
        last = first
        while True:
            # THE DIFF IS STILL PER SUBSCRIBER, because two people watching the same project may
            # have connected at different moments and been told different things. Only the READ
            # is shared — which is the expensive half.
            for_project, snap = await queue.get()
            if for_project is _CREDENTIAL_ENDED:
                # The `bye` the page already reads, carrying the same typed answer the event
                # streams end with; 1008 (policy) for a refusal, 1011 when nobody could be asked.
                await ws.send_text(json.dumps({"kind": "bye", "reason": snap.get("detail", ""),
                                               "ended": snap}))
                await ws.close(code=_close_code(snap["why"]), reason=snap["why"])
                return
            if for_project != project:
                continue
            changed = {k: v for k, v in snap.items() if last.get(k) != v}
            if changed:
                await ws.send_text(json.dumps({"kind": "update", "project": project, **changed}))
                last = snap
    except WebSocketDisconnect:
        pass
    except Exception as exc:  # noqa: BLE001 — say goodbye rather than vanish
        log.warning("the panel stream ended (%s)", str(exc)[:200])
        try:
            await ws.send_text(json.dumps({"kind": "bye", "reason": str(exc)[:200]}))
        except Exception as bye_failed:  # noqa: BLE001 — the socket is likely already gone
            # SAID, NOT SWALLOWED — `test_no_silent_failures` caught this as a bare `pass` and it
            # was right to. "The socket is already gone" is the LIKELY cause and not a measured
            # one; a serialisation bug here would look identical and would mean every stream ends
            # without its goodbye, which is the client's only signal to fall back deliberately
            # rather than by timeout. DEBUG, because on an ordinary disconnect it is noise.
            log.debug("could not send the stream's goodbye frame (%s)", bye_failed)
    finally:
        reader.cancel()
        watcher.cancel()
        _broadcast.unsubscribe(queue)


@app.get("/api/metrics")
def cost_metrics(project: str | None = None) -> dict:
    """The PER-PROJECT cost dashboard payload — spend by period / model / harness / role + a
    per-task table, from the metrics table (observability.metrics). `project` scopes it (defaults
    to the first project). Best-effort: empty series when the table is unset/unreadable, so the
    Costs view renders 'no data yet' instead of erroring."""
    from openfactory.api.metrics_view import cost_dashboard

    return cost_dashboard(project=project)


@app.get("/api/jobs/{project}/{issue}/events")
def job_events(project: str, issue: str) -> list[dict]:
    """One run's log. A project this deployment does not have is a 404 — `registry.get` raises
    KeyError, which reached the client as a 500 and read as "the panel is broken" for what is
    only a stale bookmark or a de-registered project."""
    _project_or_404(project)
    return _events(project, issue)


@app.get("/api/jobs/{project}/{issue}/stream")
async def job_stream(project: str, issue: str, request: Request) -> StreamingResponse:
    # a de-registered project is a 404, not a 500 — see `job_events`
    path = events_file(_project_or_404(project), issue)
    # Resume from where a reconnecting client left off (Last-Event-ID), by EVENT COUNT
    # with a versioned id (`v2-<n>`) — an old/foreign id is ignored rather than
    # misinterpreted, so a reconnect can never skip or duplicate the feed (M12/R5).
    last_id = request.headers.get("last-event-id") or ""
    start = int(last_id[3:]) if last_id.startswith("v2-") and last_id[3:].isdigit() else 0

    async def gen():
        emitted = start
        seen: list[str] = []  # one canonical, append-only event sequence for this stream
        # the remote box's incremental tail (built only if needed — R6; once per stream, with a
        # bounded retry — `_StreamTail`)
        stream_tail = _StreamTail(project, issue)
        remote: bool | None = None  # asked once per stream: the answer is the deployment's
        for tick in range(86400):  # up to ~24h; a client disconnect ends the generator
            if path.exists():  # local journal — cheap live tail (co-located worker)
                seen = [ln for ln in path.read_text().splitlines() if ln.strip()]
            else:
                # GUARDED, like `_events` — C-11c fixed that reader and left this one, with
                # nothing asserting the two agree. On a local install the journal is absent (the
                # panel reads a volume the journal is not written to, #67), so this branch was not
                # a fallback: it was the ONLY path the stream ever took, at ~28,800 remote reads
                # per open card per day against a log group the operator does not have.
                if remote is None:
                    remote = _boxes_are_remote()  # once: an unknown kind warns, not per tick
                tail = (await asyncio.to_thread(stream_tail.get, tick)) if remote else None
                if tail is not None:
                    try:
                        seen += [json.dumps(e) for e in await asyncio.to_thread(tail.fetch_new)]
                    except Exception:
                        logging.getLogger("openfactory.panel").warning("remote tail failed",
                                                                exc_info=True)
            if len(seen) > emitted:
                for line in seen[emitted:]:
                    yield f"data: {line}\n\n"
                emitted = len(seen)
                yield f"id: v2-{emitted}\n\n"  # a reconnect resumes from this count
            else:
                yield ": hb\n\n"  # heartbeat — keep the idle SSE alive (App Runner drops it)
            await asyncio.sleep(1 if path.exists() else 3)

    return _event_stream(request, gen())


class NewJob(BaseModel):
    project: str
    issue: str
    sandbox: str = "worktree"
    promote: bool = False  # request the staging→prod path after the PR (C3)


@app.post("/api/jobs", dependencies=_AUTH)
async def trigger_job(body: NewJob, request: Request) -> dict:
    """Launch a local (subprocess) job. A mapping onto the `start` action (C-23) — the ref
    validation that used to live in `_valid_issue` now happens once, inside `perform`, for every
    transport rather than for this route alone."""
    outcome = await actions.perform("start", by=_actor(request), project=body.project,
                                    issue=body.issue, sandbox=body.sandbox, promote=body.promote,
                                    durable=False)
    _raise_unless_ok(outcome)
    return {"ok": True, "project": body.project, "issue": outcome.data.get("issue", body.issue)}


@app.get("/api/promote/{project}/{issue}")
def promote_info(project: str, issue: str) -> dict:
    """Info for the prod-approval dialog: current version + suggested bumps + approvers.

    Read-only, and deliberately NOT an action (C-23): it does nothing, it only fetches what a
    form needs to populate itself with. `_forge_and_manifest` and `_env_prod_approvers` are
    imported from the action layer's catalog rather than duplicated here — they are the same
    lookups `approve_prod` and `promote` use to decide who may release, and a second copy is
    exactly the drift moving those two actions was meant to end."""
    from openfactory.actions.catalog import _env_prod_approvers, _forge_and_manifest
    from openfactory.semver import suggest

    # ASKED FIRST, AND BY THE ONE HELPER (#204): this `try` catches the deployed panel's missing
    # checkout and nothing else, so the registry's `KeyError` for a project somebody removed while
    # a card waited for its approval went out as a bare 500 — which the dialog reads as "the
    # panel's own API answered 500" about a release a person is trying to approve.
    p = _project_or_404(project)
    try:
        _, manifest, forge = _forge_and_manifest(project)
        approvers, tag_prefix = manifest.prod_approvers, manifest.prod_tag_prefix
    except FileNotFoundError:
        # deployed panel: the registry's repo_path is a placeholder, no checkout exists —
        # the forge needs only the registry + token, and the approvers come from the same
        # sources the approve route accepts (env allowlist, else the password store)
        from openfactory.adapters.forge.registry import build_forge
        from openfactory.approvals import list_approvers
        from openfactory.credentials import deployment_forge_token, forge_token_for

        # THE FORGE AXIS ASKS ITS OWN CREDENTIAL. `github_app.token_from_env()` stood here —
        # one vendor's mint handed to `build_forge` for ANY forge kind, and it overrode a
        # project's own `token_env` because an explicit `token=` wins over what a row resolves.
        forge = build_forge(p, token=forge_token_for(p) or deployment_forge_token(p))
        approvers, tag_prefix = _env_prod_approvers() or list_approvers(), "v"
    latest = forge.latest_tag()
    return {
        "latest_tag": latest,
        "suggestions": suggest(latest),
        "approvers": approvers,
        "tag_prefix": tag_prefix,
    }


class PromoteBody(BaseModel):
    approver: str
    password: str
    version: str
    comment: str = ""


@app.post("/api/promote/{project}/{issue}", dependencies=_AUTH)
async def promote_prod(project: str, issue: str, body: PromoteBody, request: Request) -> dict:
    """Authenticated human action to release to prod (ADR-0001 D-12). A mapping onto the
    `promote` action (C-23)."""
    outcome = await actions.perform("promote", by=_actor(request), project=project, issue=issue,
                                    version=body.version, approver=body.approver,
                                    password=body.password, comment=body.comment)
    _raise_unless_ok(outcome)
    return {"ok": True, "state": outcome.data.get("state"), "note": outcome.data.get("note")}


def _temporal():
    """(temporal_view module, address, namespace) — or RuntimeError if the runtime
    extra isn't installed. Kept lazy so the panel serves without temporalio."""
    try:
        from openfactory.runtime.temporal import view as tv
    except ImportError as exc:  # runtime extra absent
        # The one sentence every surface gives for this condition (#178), not a second spelling —
        # and only when the library IS what is missing.
        from openfactory.runtime.host import why_the_engine_cannot_be_read

        raise RuntimeError(why_the_engine_cannot_be_read(exc)) from exc
    addr, ns = tv.temporal_config()
    return tv, addr, ns


def _engine_ui(tv) -> dict:
    """The engine UI's address for a frame, and the sentence that stands in for it (#183).

    `ui_hint` IS ON EVERY FRAME, empty where the address is known, so the page never inherits a
    "nobody said" from a frame that predates somebody saying. Where the base is `""` every job's
    `temporal_url` is `""` too, and the page draws the engine link greyed with this as its title
    rather than as a link to wherever an empty `href` happens to resolve."""
    base = tv.ui_base()
    return {"ui_base": base, "ui_hint": "" if base else _engine_ui_unsaid()}


def _engine_ui_unsaid() -> str:
    """The sentence that stands in for an engine link nobody can draw — the definition's own."""
    from openfactory.listeners import ENGINE_UI

    return ENGINE_UI.unsaid()


def _temporal_or_503():
    """`_temporal()` for the routes that answer 503 rather than degrading in the body.

    THE UNDECLARED ENGINE ARRIVES HERE NOW (#163). `temporal_config()` used to answer
    `localhost:7233` when nobody had said anything, so this could not fail — and a panel on a
    deployment that never configured Temporal reported "durable engine unreachable", which sent
    whoever read it looking at the network. The reason is a different sentence and it is the one
    that names the fix, so it is carried through rather than flattened into the connect failure
    below it.
    """
    try:
        return _temporal()
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)[:300]) from exc


@app.get("/api/temporal/jobs")
async def temporal_jobs() -> dict:
    """Live job state from the durable engine. Degrades gracefully: if the runtime
    extra is missing or the engine is down, the panel still renders (connected=False)."""
    # WHICH CODE EACH HALF OF THIS DEPLOYMENT RUNS (#135), on the payload the page already streams.
    # A stack rebuilt by halves is a DEPLOYMENT fact, not a project's, so it belongs here and not in
    # the cockpit: it reaches every screen, it needs nobody to remember to fetch it, and it clears
    # ITSELF the moment the two halves match — no reload. That last part is the point. The operator
    # who is reading a stale panel is exactly the person who cannot tell whether a reload gave him
    # anything (pilot, 2026-08-17: rebuilt the worker, pressed F5, read a 28-hour-old page).
    #
    # Computed BEFORE the engine calls, and returned on every branch: a panel that cannot reach the
    # engine is if anything MORE likely to be the stale half, and that is the reading where the
    # operator most needs to be told which code is answering him.
    build = _build_report()
    try:
        tv, addr, ns = _temporal()
    except RuntimeError as exc:
        return {"connected": False, "error": str(exc), "jobs": [], "build": build}
    try:
        client = await tv.connect()
        return {
            "connected": True, "address": addr, **_engine_ui(tv), "build": build,
            "jobs": await tv.list_jobs(client, ns),
            # WHETHER WORK IS PICKED UP AT ALL — a different fact from `connected`, which only
            # says the engine answers. See `tv.intake`: a paused poller under a live engine
            # rendered as a healthy factory, beneath a line promising that TO-DO cards start on
            # their own. Carried on the SAME payload the header already reads, so nothing has to
            # remember to fetch it.
            #
            # THROUGH THE SHARED MEMO, not `tv.intake` directly (#146, second pass). `loadEngine`
            # calls this on a 20-second interval AND ~600-800 ms after most manual actions, and one
            # `intake` is 1 + N + P sequential describes — 11 for five projects with products
            # (measured 2026-09-16). Each of the three readers used to pay that separately: driving
            # all three inside one window counted 3 reads at `tv.intake` before this and 1 after
            # (measured 2026-09-17). `intake_cached` RAISES like `tv.intake` did, so a failed read
            # still reaches the `except` below as a `connected: False` frame rather than arriving
            # as `"intake": None` beside `connected: True`.
            "intake": await _floor_reading.intake_cached(client),
        }
    except Exception as exc:  # engine unreachable — never break the panel, but don't hide it
        logging.getLogger("openfactory.panel").warning("temporal_jobs failed: %r", exc)
        return {"connected": False, "address": addr, "error": str(exc)[:200], "jobs": [],
                "build": build}


@app.get("/api/jobs/{project}/{issue}/detail")
async def job_detail(project: str, issue: str) -> dict:
    """The card-click briefing: runtime, cost, PR, WHY the job is in its state, the review
    verdict + findings, the added suppressions (with location), the platform gates, and the
    GitHub CI checks — so an operator understands a `pr_open` at a glance (observability, not a
    bare status). Degrades gracefully."""
    try:
        tv, _addr, ns = _temporal()
    except RuntimeError as exc:
        return {"connected": False, "error": str(exc)}
    try:
        client = await tv.connect()
        return {"connected": True, **await tv.job_detail(client, project, issue, ns)}
    except Exception as exc:
        logging.getLogger("openfactory.panel").warning("job_detail failed: %r", exc)
        return {"connected": False, "error": str(exc)[:200]}


#: How often the SSE stream re-reads the SLOW facts (the schedules, the build stamps) rather than
#: the job list. The stream ticks every 2s; these describe 1+N+P Temporal schedules (2 for one
#: project, 11 for five with products — measured 2026-09-16) and read a file, so they ride a
#: longer clock. Ten seconds is far inside the poller's own 3-minute tick.
#:
#: ONE NUMBER, TWO CALLERS (GitHub issue #146). `/api/floor` now throttles the same schedule read
#: on the same window, and the number lives in the neutral module rather than in this front end
#: (C-23) — the panel's comment claimed the route cached "server-side (`_STREAM_SLOW_S`)" while
#: the route cached nothing, and two constants is how that claim drifted without an edit.
_STREAM_SLOW_S = _INTAKE_TTL_S


@app.get("/api/temporal/stream")
async def temporal_stream(request: Request) -> StreamingResponse:
    """Push the durable engine's job state to the panel AS IT CHANGES (SSE) — the floor
    updates in real time, no client polling, no refresh. One backend poll feeds every
    connected client; a frame is sent only when the state actually changes (plus the
    first frame on connect). Degrades to a single 'disconnected' frame if the engine or
    runtime extra is absent — the panel still renders.

    IT CARRIES WHAT THE HEADER READS, and until #139 it did not. This frame held `jobs` alone,
    while the page REPLACED its whole engine object with it — so `intake` (is the poller
    running?) and `build` (are the two halves the same code?) were wiped by every frame and
    restored only by the 20-second safety-net poll. Measured on the pilot: for the first 20
    seconds after every reload the header said `floor: running` whatever the poller was doing,
    and the build-split banner could not appear at all. That is the contradiction the operator
    reported — a screen stating a fact it had, at that instant, no way to know.

    THE SCHEDULE READS ARE CACHED, deliberately. `tv.intake` describes `1 + N + P` Temporal
    schedules — the poller, one per enabled project, one more per project declaring a `product`:
    2 for one project, 4 for three, 7 for three with products, 11 for five with products (measured
    2026-09-16, counting `get_schedule_handle(...).describe()`). Doing that every 2 seconds for
    every connected browser turns a status line into load. Ten seconds is far inside the poller's
    own 3-minute tick, so nothing observable lags.

    "3-5 schedules" stood here until 2026-09-17, four lines under the constant #146 rewrote, and
    was never a measurement — an unchecked number in a comment is the defect #146 is about, so it
    is corrected in the file that argument edits rather than left for the next reader to re-earn."""

    async def gen():
        try:
            tv, addr, ns = _temporal()
        except RuntimeError as exc:
            yield f"data: {json.dumps({'connected': False, 'error': str(exc), 'jobs': []})}\n\n"
            return
        client = None
        last = None
        slow: dict = {}          # the cached intake/build pair
        slow_at = 0.0            # loop clock; 0.0 = never read
        while not await request.is_disconnected():
            try:
                if client is None:
                    client = await tv.connect()
                now = asyncio.get_event_loop().time()
                if not slow or now - slow_at >= _STREAM_SLOW_S:
                    # `intake` answers `known: False` on its own when a schedule cannot be read,
                    # so a failed read reaches the page as "I could not check" rather than as a
                    # stale answer wearing a fresh timestamp.
                    #
                    # THE INTAKE READ IS THE SHARED MEMO'S NOW (#146, second pass); `_build_report`
                    # keeps this per-connection window. Two levels, on purpose: the local one bounds
                    # the file read and drops everything on a blip (`slow, slow_at = {}, 0.0`, which
                    # a process-wide memo has nothing to hang on), and the shared one stops N
                    # connected browsers each paying 1 + N + P describes on their own clocks.
                    #
                    # AND THE BLIP CLEARS BOTH, which is what keeps #139's claim true now that the
                    # read is shared: see the `except` branch below. Clearing only the local pair
                    # would force a re-read the process-wide memo could answer with a value from
                    # before the failure — the guard would still have read its line and the page
                    # would still have been shown a poller state from before the engine died.
                    slow = {"intake": await _floor_reading.intake_cached(client),
                            "build": _build_report()}
                    slow_at = now
                frame = {"connected": True, "address": addr, **_engine_ui(tv),
                         "jobs": await tv.list_jobs(client, ns), **slow}
            except Exception as exc:  # engine blip — emit a disconnected frame, retry
                logging.getLogger("openfactory.panel").warning("temporal_stream: %r", exc)
                # THIS IS NO LONGER A RECONNECT, and it reads like one — so it says so here
                # (GitHub issue #134). `tv.connect()` hands back the client this process already
                # holds for the engine, so the next pass through the loop gets the SAME object;
                # nothing here can evict it, and nothing tries. That is intended: an engine blip
                # already reaches every caller as a degraded read, and dropping the pooled client
                # on each one would reopen the per-request leak on exactly the path that is already
                # unhappy. What dropping the LOCAL name still does is force the `if client is None`
                # branch on the next pass, so the stream asks `tv.connect()` for the engine's
                # client again instead of carrying this generator's own stale binding forward —
                # which is what picks up a client the pool has since replaced (a re-keyed target:
                # a moved address, a rotated API key, a cert rewritten in place).
                client = None
                # NEVER CARRY AN INTAKE READ FROM BEFORE THE BLIP (#139) — BOTH COPIES OF IT.
                # Dropping the local pair stopped being enough the moment the schedule read became
                # process-wide (#146, second pass): it forces a re-read, and the shared memo could
                # answer that re-read with the very value this line exists to discard. So the blip
                # clears the memo too, and the claim holds for every surface rather than for this
                # generator's own dict. Costs one fresh 1 + N + P read after a blip, on the
                # exceptional path; during a real outage there is nothing cached to drop, because
                # a read that raised is never stored.
                slow, slow_at = {}, 0.0
                _floor_reading.forget_intake()
                frame = {"connected": False, "address": addr, "error": str(exc)[:200], "jobs": [],
                         "build": _build_report()}
            payload = json.dumps(frame, sort_keys=True)
            if payload != last:
                yield f"data: {payload}\n\n"
                last = payload
            else:
                # HEARTBEAT: with no state change nothing would traverse the wire, and App
                # Runner (and any proxy) silently drops an idle SSE connection — the browser
                # tab then freezes on the last frame it got, showing a finished job as still
                # 'in production' (the exact stale-panel bug). A comment line every tick keeps
                # the stream alive; EventSource ignores it but the socket stays open.
                yield ": hb\n\n"
            await asyncio.sleep(2)

    return _event_stream(request, gen())


@app.post("/api/temporal/jobs", dependencies=_AUTH)
async def temporal_start(body: NewJob, request: Request) -> dict:
    """Launch a durable job into Temporal (needs a worker running). A mapping onto the `start`
    action (C-23) with `durable=True`."""
    outcome = await actions.perform("start", by=_actor(request), project=body.project,
                                    issue=body.issue, sandbox=body.sandbox, promote=body.promote,
                                    durable=True)
    _raise_unless_ok(outcome)
    return {"ok": True, "workflow_id": outcome.data.get("workflow_id")}


@app.post("/api/projects/{project}/scan", dependencies=_AUTH)
async def scan_now(project: str, request: Request) -> dict:
    """Scan this project's board TO-DO column right now — the 'don't wait for the 3-min tick'
    button. A mapping onto the `scan` action (C-23); the implementation (and the three defects
    that made it non-trivial to get right) lives in `openfactory/actions/catalog.py`."""
    outcome = await actions.perform("scan", by=_actor(request), project=project)
    _raise_unless_ok(outcome)
    return {"started": outcome.data.get("started", []), "skipped": outcome.data.get("skipped", []),
            "todo": outcome.data.get("todo", []), "running": outcome.data.get("running", []),
            "message": outcome.message}


@app.post("/api/temporal/approve/{project}/{issue}", dependencies=_AUTH)
async def temporal_approve(project: str, issue: str, body: PromoteBody, request: Request) -> dict:
    """Authenticated prod approval delivered as a durable signal to the parked workflow (D-12) —
    the human-in-the-loop path of the runtime. A mapping onto the `approve_prod` action (C-23)."""
    outcome = await actions.perform("approve_prod", by=_actor(request), project=project,
                                    issue=issue, version=body.version, approver=body.approver,
                                    password=body.password, comment=body.comment)
    _raise_unless_ok(outcome)
    return {"ok": True, "signaled": True}


class ActBody(BaseModel):
    action: str  # "resume" | "skip"
    choice: str = ""  # a DecisionRequest option key, when the park carried options


@app.get("/api/decisions")
async def decisions() -> list[dict]:
    """Every job currently PARKED on a human decision, with its question + options — the
    headless feed a panel, a Slack bot, a Telegram bot, or `curl` all read to present the choice
    (API-first: the panel is just one client). POST the picked key back to /api/temporal/act."""
    tv, addr, ns = _temporal_or_503()
    try:
        client = await tv.connect()
    except Exception as exc:
        raise HTTPException(
            status_code=503, detail=f"durable engine unreachable: {str(exc)[:150]}"
        ) from exc
    out: list[dict] = []
    for j in await tv.list_jobs(client, ns):
        act = j.get("action") or {}
        if act.get("decision"):
            out.append({"project": j.get("project"), "issue": j.get("issue"),
                        "title": j.get("title"), "state": j.get("state"),
                        "decision": act["decision"]})
    return out


@app.post("/api/temporal/act/{project}/{issue}", dependencies=_AUTH)
async def temporal_act(project: str, issue: str, body: ActBody, request: Request) -> dict:
    """Single-line strict (ADR-0010): the operator's (or a bot's — same API) decision on a
    PARKED job — 'resume' (re-run / retry a rate-limit now / proceed with a chosen option) or
    'skip' (free the floor). `choice` is the DecisionRequest option key when the park asked a
    question.

    A MAPPING NOW, not an implementation (C-23). It keeps its URL and its response shape because
    `panel.html` and ADR-0010 both name them, and it forwards to the same `resume`/`skip` rows the
    Slack bot and `openfactory act` reach. That is the whole point: this route and the Slack verb used to
    be two independent pieces of code for one decision, and the panel's `choice` — the key of the
    option the job actually offered — existed on this side only."""
    if body.action not in ("resume", "skip"):
        raise HTTPException(status_code=400, detail="action must be 'resume' or 'skip'")
    params: dict[str, object] = {"project": project, "issue": issue}
    if body.action == "resume":
        params["choice"] = body.choice or ""
    outcome = await actions.perform(body.action, by=_actor(request), **params)
    _raise_unless_ok(outcome)
    return {"ok": True, "action": body.action, "choice": body.choice or None,
            "message": outcome.message}


# ── the whole catalog, by name (C-23) ────────────────────────────────────────────────────────────
#
# ONE ROUTE FOR EVERY ACTION, so a new action is reachable from HTTP the moment it is catalogued —
# rather than the moment somebody remembers to write a route for it. That "the moment somebody
# remembers" is exactly how the two front ends came to disagree: `ack` was written for Slack and
# never for here, `enable` and `scan` here and never for Slack, and nothing in either codebase
# could notice.
#
# The named routes above and below stay, because URLs are a contract and ADR-0010 publishes some of
# them. They are mappings onto the same rows, and a test asserts each one reaches the row it claims.

class ActRequest(BaseModel):
    """Whatever the action takes. Free-form on purpose — the catalog owns the parameter list and
    `perform` checks it in both directions (missing AND unexpected), so a typed model here would be
    a second copy of that list, drifting from the first."""

    params: dict[str, object] = {}


@app.get("/api/product/projects")
def product_projects() -> list[dict]:
    """The projects that have a product role, for a credential that may not list the rest.

    THE SURFACE NEEDS A WAY IN. A product credential is refused `/api/projects` — that is the
    jobs dashboard and the whole point of scoping it — so without this a business analyst can
    only reach their own page by being handed an exact URL, and landing anywhere else shows them
    a row of 403s. Names and nothing else: which clients this deployment runs is not a thing a
    requirements author needs, and `/api/projects` carries box health, board coordinates and the
    forge for every one of them.

    THE SAME RULE THE ROWS USE, not a second one. `catalog._product_module` reads a missing
    `enabled` as TRUE — a project that declares `product:` at all has the role on — and a list
    that defaulted the other way would hide projects the actions then happily served, which is
    the "fix one, forget the neighbour" shape this codebase keeps paying for."""
    def _has_product(p) -> bool:
        cfg = getattr(p, "product", None)
        return cfg is not None and bool(getattr(cfg, "enabled", True))

    return [{"name": p.name} for p in ProjectRegistry().list() if _has_product(p)]


@app.get("/api/whoami")
def whoami(request: Request) -> dict:
    """Who this credential is, and which areas it may act in.

    THE ONE READ EVERY CREDENTIAL MAY MAKE, and the reason it exists: a single-page app served
    from a static file cannot know at load time whether the person holding the token is an
    operator or a business analyst — the credential lives in the browser, not in the HTML. Without
    this the page would have to render the operator's dashboard and discover its own scope from a
    row of 403s, which is indistinguishable on screen from a broken deployment.

    `scopes: null` means unscoped — every actor that predates #98, and the answer for an ordinary
    panel token. It is not the same as `[]`, and a front end must not read it as "no areas"."""
    subject = _subject(request)
    scopes = _scopes_of(subject)
    return {"id": subject.id, "display": subject.display or subject.id or "",
            "known": subject.known,
            "scopes": sorted(scopes) if scopes is not None else None,
            # WHERE TO END THIS SESSION, when the deployment has a login to end (#33). Null on a
            # token deployment: there is nothing to sign out of, and a page must not draw a door.
            "logout": _sso.LOGOUT_PATH
            if (_login_provider() is not None or _has_form_login()) else None}


def _has_form_login() -> bool:
    """`_form_login`, for the one caller that only draws a link. Whoever reaches `whoami` while
    the people store cannot be read was admitted on a credential that needs no store (the gate
    refused everybody else), and what they hold is a token: there is no session to end, so no
    door is drawn — and the gate has already logged the store by name on this very request."""
    from openfactory.observability.query import StoreUnreadable

    try:
        return _form_login() is not None
    except StoreUnreadable:
        return False


@app.get("/api/actions")
def list_actions() -> list[dict]:
    """What this deployment can be asked to do — the catalogue a front end renders and a script
    reads. Open (no auth): knowing an action exists is not authority to run it, and a panel that
    cannot list its own capabilities before the operator has pasted a token is a panel that shows
    an empty screen and no explanation."""
    return [
        {"name": s.name, "summary": s.summary, "required": list(s.required),
         "optional": list(s.optional), "needs_admin": s.needs_admin,
         # WHAT TO PUT IN EACH PARAMETER, and when to choose this row over its neighbours (#172).
         # Resolved HERE rather than by each front end, because the catalogue is the only thing
         # that knows: a panel or a script inventing a label from the parameter's name is the
         # second definition this card exists to remove. `choose_when` is empty for most rows —
         # only the proposable few are ever offered as a choice — and empty means nobody said,
         # not that the row is interchangeable with its neighbours.
         "params": s.described, "choose_when": s.choose_when or None,
         "available": not s.pending, "still_in": s.pending or None}
        for s in actions.CATALOG.values()
    ]


@app.post("/api/act/{name}", dependencies=_AUTH)
async def act(name: str, body: ActRequest, request: Request) -> JSONResponse:
    """Run any catalogued action. `POST /api/act/resume {"params":{"project":"x","issue":"12"}}`.

    Returns the Outcome verbatim — `ok`, `message`, `code`, `data` — with the HTTP status mapped
    from `code`, and `detail` mirroring `message` so the panel's existing error handling (which
    reads `d.detail`, the FastAPI convention) works unchanged."""
    outcome = await actions.perform(name, by=_actor(request), **(body.params or {}))
    payload: dict[str, object] = {"ok": outcome.ok, "message": outcome.message,
                                  "code": outcome.code, "data": dict(outcome.data)}
    if not outcome.ok:
        payload["detail"] = outcome.message
    return JSONResponse(payload, status_code=_STATUS.get(outcome.code, 200))


# ── a card's preview, on demand (ADR-0050 D6): the three rows, under the prefix both areas read ──


@app.post("/api/preview/{project}/{unit}/start", dependencies=_AUTH)
async def preview_start(project: str, unit: str, request: Request) -> JSONResponse:
    """Start a preview of this unit — the `preview_start` row, as whoever the panel let in. Under
    `/api/preview/`, which both areas read: the product-scoped person who asked for the change is
    who presses it. A second start while one is starting answers `starting`."""
    return await _preview_act("preview_start", project, unit, request)


@app.post("/api/preview/{project}/{unit}/stop", dependencies=_AUTH)
async def preview_stop(project: str, unit: str, request: Request) -> JSONResponse:
    """Take this unit's preview down now, its logs kept — the `preview_stop` row."""
    return await _preview_act("preview_stop", project, unit, request)


@app.post("/api/preview/{project}/{unit}/rebuild", dependencies=_AUTH)
async def preview_rebuild(project: str, unit: str, request: Request) -> JSONResponse:
    """Build this unit's preview again from its pull request's head — the `preview_rebuild` row;
    a unit with nothing up is started."""
    return await _preview_act("preview_rebuild", project, unit, request)


async def _preview_act(name: str, project: str, unit: str, request: Request) -> JSONResponse:
    """One of the three rows, its outcome as `/api/act` renders one — `ok`, `message`, `code`,
    `data` (with `state`), `detail` on a refusal — the status mapped from the code. The scope the
    row belongs to (`product`) is checked by `perform`, against the credential that asked."""
    outcome = await actions.perform(name, by=_actor(request), project=project, unit=unit)
    payload: dict[str, object] = {"ok": outcome.ok, "message": outcome.message,
                                  "code": outcome.code, "data": dict(outcome.data),
                                  "state": str(outcome.data.get("state", ""))}
    if not outcome.ok:
        payload["detail"] = outcome.message
    return JSONResponse(payload, status_code=_STATUS.get(outcome.code, 200))


_NO_CACHE = {"Cache-Control": "no-store"}  # the panel HTML changes on every deploy —
# a browser must never serve a stale copy (else "I don't see the change" confusion).


@app.get("/")
def index() -> HTMLResponse:
    return HTMLResponse(_read_panel(), headers=_NO_CACHE)


@app.get("/p/{project}")
@app.get("/p/{project}/board")
@app.get("/p/{project}/card/{ref}")
@app.get("/p/{project}/pr/{ref}")
def project_page(project: str, ref: str = "") -> HTMLResponse:
    """The same single-page app; the client reads the path to focus one project's floor.

    THE DEEPER ADDRESSES ARE DECLARED HERE OR THEY 404 BEFORE THE PAGE CAN READ THEM (ADR-0049
    D6). `/p/x/board` and `/p/x/card/7` are the Board and one card, and a person who bookmarks
    one, or is sent one, must land on it rather than on the server's own not-found — which is
    what a single-page app looks like when only its root is served."""
    return HTMLResponse(_read_panel(), headers=_NO_CACHE)


# ── the login, for a provider that has one (#33) ────────────────────────────────────────────────
#
# THREE ROUTES OUTSIDE `/api/`, so the gate does not stand in front of the door that hands out the
# credential the gate asks for. They are mounted on every deployment and answer BY NAME on the
# ones whose provider has no login page — `local` presents a token, and a 404 that says so is the
# difference between "this deployment does not do SSO" and "the panel is broken".
#
# WHAT A LOGIN LEAVES BEHIND is the provider's own id_token in the cookie the panel already reads,
# for exactly as long as the token is valid. No session table: every request afterwards is
# verified against the issuer's published keys by the same `identify` the gate calls for a local
# token, which is the whole reason the axis was built before the provider (`identity/base.py`).


def _login_provider():
    """The deployment's provider when it can run a login flow, else None — a misconfigured one
    is None too, and the gate has already logged why on every request it refused."""
    from openfactory.identity import build_identity

    try:
        provider = build_identity()
    except (ValueError, TypeError):
        return None
    if hasattr(provider, "begin_login") and hasattr(provider, "finish_login"):
        return provider
    return None


def _callback_url(request: Request, provider) -> str:
    """As the provider knows it: the configured one, else derived from THIS request. Derived is
    right on a laptop and wrong behind a proxy that terminates TLS (the request arrives as http),
    which is what the variable exists for; a wrong one is refused by the provider, by name, and
    never silently accepted."""
    configured = str(getattr(getattr(provider, "settings", None), "redirect_url", "") or "")
    if configured:
        return configured
    host = request.headers.get("host") or request.url.netloc
    return f"{request.url.scheme}://{host}{_sso.CALLBACK_PATH}"


def _form_login():
    """The local row, when anybody is registered by invitation — the provider whose login is a
    FORM rather than a redirect. None on an SSO deployment, and None on a token deployment where
    nobody has registered yet: a form nobody can fill in is a dead end, not a door.

    RAISES `StoreUnreadable` WHEN IT CANNOT TELL. This asked the row's `login_path`, which is `""`
    both when nobody is registered and when the store could not be read — so the login routes
    answered an outage with "nobody is registered by invitation yet". The store is asked directly
    and each caller says what unreadable means for it."""
    local = _local_provider()
    if local is not None and local.people().has_people():
        return local
    return None


def _people_unreadable(exc: Exception, doing: str) -> PlainTextResponse:
    """The forms' answer when the people store cannot be read: 503, by name, and NOTHING done.

    The three forms used to answer for an empty store instead — "nobody is registered by
    invitation yet", "that is not a registered person, or not their password", "this invitation
    is not one this deployment issued" — each one a sentence about the PERSON that was really a
    fact about the store, and the last one tells somebody holding a good link to go and ask for
    another. The cause stays in the log: this page is read by somebody nobody has identified."""
    log.error("OPENFACTORY_PEOPLE_UNAVAILABLE %s was refused — the people store could not be "
              "read, and \"could not look\" is not \"nobody\": %s", doing, exc)
    return PlainTextResponse(
        f"{doing} is unavailable: the people registered on this deployment cannot be read right "
        f"now. Nothing was changed and nothing you hold has stopped being valid — try again "
        f"shortly; the operator will find the cause in the panel's log.",
        status_code=503, headers=_NO_CACHE)


def _no_login_page() -> PlainTextResponse:
    """Why there is no login here — and there are two answers, which must not share a sentence:
    a token deployment has no login page by design (404), and an `oidc` row missing a variable
    has one that cannot open yet (503, naming the variable)."""
    from openfactory.identity import build_identity
    from openfactory.identity.registry import identity_kind

    try:
        build_identity()
    except (ValueError, TypeError) as exc:
        return PlainTextResponse(f"login unavailable: {exc}", status_code=503)
    return PlainTextResponse(
        f"this deployment's identity provider is `{identity_kind()}`, which has no login page — a "
        f"credential is presented as a token, and nobody is registered by invitation yet. "
        f"`openfactory people invite <id>` issues a link that registers a person and opens a "
        f"login form here; OPENFACTORY_IDENTITY=oidc and the provider's variables "
        f"(docs/configuration.md) log in through an identity provider instead.",
        status_code=404)


def _auth_page(title: str, body: str, *, status: int = 200) -> HTMLResponse:
    """The one page the login and the registration share. No script, no fetch: it is the page
    that exists BECAUSE the browser holds no credential yet, so nothing on it may need one."""
    brand = _h(os.environ.get("OPENFACTORY_PLATFORM_NAME", "OpenFactory"))
    return HTMLResponse(
        f"<!doctype html><html><head><meta charset=utf-8><meta name=viewport "
        f"content=\"width=device-width,initial-scale=1\"><title>{_h(title)} · {brand}</title>"
        f"<style>body{{font:15px/1.5 system-ui,sans-serif;margin:0;background:#f5f5f4;color:#1c1917}}"
        f"main{{max-width:26rem;margin:12vh auto;background:#fff;padding:2rem;border-radius:12px;"
        f"box-shadow:0 1px 3px rgba(0,0,0,.12)}}h1{{font-size:1.15rem;margin:0 0 .25rem}}"
        f"label{{display:block;margin:1rem 0 .3rem;font-weight:600}}input{{width:100%;box-sizing:"
        f"border-box;padding:.55rem .7rem;border:1px solid #d6d3d1;border-radius:8px;font:inherit}}"
        f"button{{margin-top:1.25rem;width:100%;padding:.65rem;border:0;border-radius:8px;"
        f"background:#1c1917;color:#fff;font:inherit;font-weight:600}}.why{{color:#b91c1c;margin:"
        f".75rem 0 0}}.brand{{color:#78716c;font-size:.85rem;margin:0 0 1.25rem}}</style></head>"
        f"<body><main><p class=brand>{brand}</p><h1>{_h(title)}</h1>{body}</main></body></html>",
        status_code=status, headers=_NO_CACHE)


def _login_form(next_path: str, *, why: str = "") -> str:
    return (f"<form method=post action=\"{_sso.LOGIN_PATH}\">"
            f"<input type=hidden name=next value=\"{_h(next_path)}\">"
            f"<label for=id>Who are you</label><input id=id name=id autocomplete=username "
            f"autofocus required>"
            f"<label for=password>Password</label><input id=password name=password type=password "
            f"autocomplete=current-password required>"
            f"{'<p class=why>' + _h(why) + '</p>' if why else ''}"
            f"<button>Sign in</button></form>")


def _register_form(token: str, display: str, *, why: str = "") -> str:
    from openfactory.identity.people import PASSWORD_MIN_CHARS

    return (f"<form method=post action=\"{_REGISTER_PATH}\">"
            f"<input type=hidden name=invite value=\"{_h(token)}\">"
            f"<label for=display>Your name, as the team will see it</label>"
            f"<input id=display name=display value=\"{_h(display)}\" autocomplete=name required>"
            f"<label for=password>Choose a password (at least {PASSWORD_MIN_CHARS} characters)"
            f"</label><input id=password name=password type=password "
            f"autocomplete=new-password minlength={PASSWORD_MIN_CHARS} required>"
            f"<label for=again>The same password again</label><input id=again name=again "
            f"type=password autocomplete=new-password required>"
            f"{'<p class=why>' + _h(why) + '</p>' if why else ''}"
            f"<button>Register</button></form>")


async def _form_fields(request: Request) -> dict[str, str]:
    """An HTML form's fields, without `python-multipart`: the two forms here are
    urlencoded, and a dependency for parsing two forms is a dependency too many."""
    raw = (await request.body()).decode("utf-8", "replace")
    return {k: v for k, v in parse_qsl(raw, keep_blank_values=True)}


@app.get(_sso.LOGIN_PATH)
def auth_login(request: Request, next: str = "/"):
    from openfactory.observability.query import StoreUnreadable

    provider = _login_provider()
    if provider is None:
        try:
            local = _form_login()
        except StoreUnreadable as exc:
            return _people_unreadable(exc, "signing in")
        if local is not None:
            return _auth_page("Sign in", _login_form(_sso.safe_next(next)))
        return _no_login_page()
    began = provider.begin_login(callback_url=_callback_url(request, provider), next_path=next)
    if isinstance(began, str):
        log.error("OPENFACTORY_OIDC_LOGIN_FAILED %s", began)
        return PlainTextResponse(f"login unavailable: {began}", status_code=503)
    url, flight = began
    response = RedirectResponse(url, status_code=302, headers=_NO_CACHE)
    # HttpOnly and Lax: the callback ARRIVES as a cross-site navigation from the issuer, and a
    # Strict cookie is not sent on one. Scoped to /auth/ so no other route ever sees it.
    response.set_cookie(_sso.FLIGHT_COOKIE, flight, max_age=_sso.FLIGHT_TTL_SECONDS, httponly=True,
                        samesite="lax", secure=request.url.scheme == "https", path="/auth/")
    return response


@app.get(_sso.CALLBACK_PATH)
def auth_callback(request: Request, code: str = "", state: str = "", error: str = "",
                  error_description: str = ""):
    provider = _login_provider()
    if provider is None:
        return _no_login_page()
    login = provider.finish_login(
        callback_url=_callback_url(request, provider), code=code, state=state,
        flight_cookie=request.cookies.get(_sso.FLIGHT_COOKIE, ""), error=error,
        error_description=error_description)
    if login.refused:
        log.warning("OPENFACTORY_OIDC_LOGIN_REFUSED %s", login.refused)
        response = PlainTextResponse(f"login refused: {login.refused}", status_code=401)
        response.delete_cookie(_sso.FLIGHT_COOKIE, path="/auth/")
        return response
    log.info("OPENFACTORY_OIDC_LOGIN %s (%s) logged in", login.subject.id, login.subject.display)
    response = RedirectResponse(login.next_path, status_code=302, headers=_NO_CACHE)
    response.delete_cookie(_sso.FLIGHT_COOKIE, path="/auth/")
    # NOT HttpOnly, deliberately: the page reads it once into localStorage and sends it as a
    # Bearer header from then on, which is how every mutating route already authenticates. The
    # exposure — a script on this origin can read the credential — is the one the panel has had
    # since the shared token lived in localStorage, and this adds none to it.
    _set_credential_cookie(response, request, login.id_token,
                           max_age=login.expires_at - int(time.time()))
    return response


@app.post(_sso.LOGIN_PATH)
async def auth_login_form(request: Request):
    """The local row's login: a registered person, their password, a session (#33)."""
    from openfactory.observability.query import StoreUnreadable

    try:
        local = _form_login()
    except StoreUnreadable as exc:
        return _people_unreadable(exc, "signing in")
    if local is None:
        return _no_login_page()
    fields = await _form_fields(request)
    next_path = _sso.safe_next(fields.get("next", "/"))
    # the fold `_form_login` just read is the one `login` checks the password against — one
    # store, one read — so there is no second place for this request to meet an unreadable store
    token = local.people().login(fields.get("id", ""), fields.get("password", ""))
    if not token:
        log.info("OPENFACTORY_LOGIN_REFUSED a sign-in for %r was refused", fields.get("id", "")[:80])
        return _auth_page("Sign in", _login_form(next_path, why="that is not a registered person, "
                                                 "or not their password"), status=401)
    return _session_response(request, next_path, token)


def _session_response(request, next_path: str, token: str) -> RedirectResponse:
    """A session token in the cookie the panel reads, then `next`. Not HttpOnly, for the reason
    `_set_credential_cookie` gives."""
    from openfactory.identity.people import SESSION_TTL_SECONDS

    response = RedirectResponse(next_path, status_code=303, headers=_NO_CACHE)
    _set_credential_cookie(response, request, token, max_age=SESSION_TTL_SECONDS)
    return response


@app.get(_REGISTER_PATH)
def auth_register(request: Request, invite: str = ""):
    """The one-time link's landing: choose a name and a credential. 404 for a link this
    deployment did not issue, already used or expired — one sentence for all three, on purpose."""
    from openfactory.observability.query import StoreUnreadable

    local = _local_provider()
    try:
        invitation = local.people().invitation_for(invite) if local is not None else None
    except StoreUnreadable as exc:
        return _people_unreadable(exc, "registering")
    if invitation is None:
        return _no_invitation()
    return _auth_page("Register", _register_form(invite, invitation.display))


@app.post(_REGISTER_PATH)
async def auth_register_form(request: Request):
    local = _local_provider()
    if local is None:
        return _no_invitation()
    from openfactory.observability.query import StoreUnreadable

    fields = await _form_fields(request)
    try:
        return _redeem(request, local, fields)
    except StoreUnreadable as exc:
        # REFUSED BEFORE ANYTHING IS MINTED. `register` reads the invitation first, so a store
        # that cannot be read raises before a row is written or a session opened — and the link
        # is still good afterwards: a redemption that did not happen did not spend it.
        return _people_unreadable(exc, "registering")


def _redeem(request, local, fields: dict[str, str]):
    """The registration form, against a store that answers. Raises `StoreUnreadable` otherwise —
    from whichever read met it — and its one caller turns that into the named refusal."""
    token = fields.get("invite", "")
    if fields.get("password", "") != fields.get("again", ""):
        invitation = local.people().invitation_for(token)
        if invitation is None:
            return _no_invitation()
        return _auth_page("Register", _register_form(token, fields.get("display", ""),
                                                     why="the two passwords differ"), status=400)
    got = local.people().register(token=token, display=fields.get("display", ""),
                                  password=fields.get("password", ""))
    if isinstance(got, str):
        invitation = local.people().invitation_for(token)
        if invitation is None:
            return _no_invitation()
        return _auth_page("Register", _register_form(token, fields.get("display", ""), why=got),
                          status=400)
    session = local.people().open_session(got)
    log.info("OPENFACTORY_PEOPLE_REGISTERED %s (%s) registered, vouched for by %s", got.id,
             got.display, got.invited_by)
    if not session:
        return _auth_page("Registered", f"<p>You are registered as <b>{_h(got.id)}</b>. "
                          f"<a href=\"{_sso.LOGIN_PATH}\">Sign in</a>.</p>")
    return _session_response(request, "/", session)


def _local_provider():
    """The local row itself, registered people or not — the registration link is what makes
    the first person, so it cannot wait for `login_path` to say there is one."""
    from openfactory.identity import build_identity
    from openfactory.identity.local import LocalIdentity

    try:
        provider = build_identity()
    except (ValueError, TypeError):
        return None
    return provider if isinstance(provider, LocalIdentity) else None


def _no_invitation() -> PlainTextResponse:
    return PlainTextResponse(
        "this invitation is not one this deployment issued, was already used, or has expired — "
        "ask the operator for a new link (`openfactory people invite <id>`).", status_code=404)


@app.get(_sso.LOGOUT_PATH)
def auth_logout(request: Request):
    """Both halves of the credential: the cookie goes here, the localStorage copy goes in the page
    this answers with — a logout that cleared one would be undone by `boot()` copying the other
    back. A registered person's session is REVOKED in the store, so the token in a copied cookie
    is dead too. The OIDC provider's own session is NOT ended: the next login is the provider's to
    answer, silently or with a prompt, and RP-initiated logout is a later slice of #33."""
    from openfactory.observability.query import StoreUnreadable

    local = _local_provider()
    if local is not None:
        auth = request.headers.get("authorization", "")
        held = auth[7:] if auth.startswith("Bearer ") else _one_credential_cookie(request)
        try:
            if held and local.people().revoke(held):
                log.info("OPENFACTORY_LOGOUT a registered person's session was revoked")
        except StoreUnreadable as exc:
            # THE BROWSER IS STILL SIGNED OUT — refusing to clear a cookie because a store is
            # down would keep somebody signed in on a machine they are walking away from. What
            # could not be done is said by name: a COPY of this session stays valid until it
            # expires, and no revocation is written blind, because a revocation row for a
            # session nobody looked up is a row anybody could write (`people.READ_LAST`).
            log.warning("OPENFACTORY_LOGOUT_NOT_REVOKED the people store could not be read, so "
                        "this session was cleared from the browser and NOT revoked in the store "
                        "— a copy of it stays valid until it expires: %s", exc)
    response = HTMLResponse(
        "<!doctype html><meta charset=utf-8><title>signed out</title>"
        "<script>try{localStorage.removeItem('openfactory_token')}catch(e){}"
        "location.replace('/')</script>signed out.", headers=_NO_CACHE)
    _clear_credential_cookies(response)
    return response


@app.get("/logs")
@app.get("/logs/{project}")
@app.get("/logs/{project}/{issue}")
def logs_page(project: str = "", issue: str = "") -> HTMLResponse:
    """The Logs page, and a single run's log at its own address.

    SERVED HERE TOO, not only reachable by clicking. A client-side route that the server does not
    answer works until somebody refreshes the page or pastes the link they were sent — and then it
    is a 404 on a URL the product handed them."""
    return HTMLResponse(_read_panel(), headers=_NO_CACHE)


@app.get("/product/{project}")
def product_page(project: str) -> HTMLResponse:
    """The product role's own surface (#98).

    A SEPARATE ADDRESS, not a tab on the floor, because it is a separate JOB: the person who
    writes what the product must do is not the person who watches jobs run, and the card asks for
    a page "for a BA who has no access to the jobs dashboard". A link to this URL is the whole
    onboarding for somebody holding a product credential.

    Still the same single-page app and the same open HTML shell — the credential lives in the
    browser and every byte of content behind this arrives through `/api/*`, which is gated and
    scoped. Serving different HTML per scope would put an authorization decision in a file that is
    handed out unauthenticated."""
    return HTMLResponse(_read_panel(), headers=_NO_CACHE)


def _token_pool_from_env() -> dict:
    """The pool this process can see, with no cloud involved. What a local deployment HAS — the
    `env` row of the token-pool seam, which is also its default."""
    from openfactory.adapters.agent.token_pool import token_pool

    return token_pool("env")


def _token_pool_meta() -> dict:
    """Agent credential pool for the cockpit: count + ids + auth format, NEVER values.
    Reads the source this deployment DECLARES (`adapters/agent/token_pool.py`: the environment
    unless it says otherwise); degrades to what this process can see in its own env when that
    source will not answer. A token value never leaves here."""
    from openfactory.adapters.agent.token_pool import token_pool, token_pool_source_kind

    kind = token_pool_source_kind()
    try:
        return token_pool(kind)
    except ValueError as exc:
        # A SOURCE NOBODY INSTALLED is the deployment's configuration (a typo, or the add-on that
        # declares the row absent from the image), not an outage — it was folded into the INFO
        # line below and read as weather. The refusal names what IS known.
        log.warning("the declared token pool source %r is unknown (%s) — reporting the env pool "
                    "until it is corrected", kind, exc)
        return _token_pool_from_env()
    except Exception as exc:  # noqa: BLE001 — a source that will not answer → the env pool, said
        # Worth saying: the env pool and a remote pool can differ, and "how many tokens do we
        # have" answered from the wrong source is the number somebody sizes a night's work
        # against. It used to gate this read on a vendor's cluster variable and a literal
        # parameter path — the first deployment's — so a second deployment's panel queried a tree
        # in another account and read the failure as "a local deployment" (#163).
        log.info("token pool not readable from the %r source (%s) — reporting the env pool "
                 "instead", kind, exc)
        return _token_pool_from_env()


#: How a harness kind reads to a human. A kind with no entry shows its own name, which is right —
#: a new harness must not need this table to be displayed honestly, only to be displayed prettily.
_HARNESS_LABELS = {"claude_code": "Claude Code", "codex": "Codex", "kimi": "Kimi",
                   "opencode": "OpenCode"}


def _auth_credential() -> str:
    """"subscription" | "api key" | "" — WHICH credential the harness will present.

    Read from the environment this process shares with the worker (compose forwards the whole
    `.env.compose` to both). Empty when neither variable is visible here, because the honest
    answer to "which of these two is paying" is sometimes "I cannot see from here"."""
    import os as _os

    if _os.environ.get("CLAUDE_CODE_OAUTH_TOKEN"):
        return "subscription"
    if _os.environ.get("ANTHROPIC_API_KEY"):
        return "api key"
    return ""


def _axes(project: str) -> tuple[str, dict, str]:
    """`(harness, {role: model}, auth route)` for this project — every value RESOLVED.

    Degrades to the deployment defaults if the project cannot be read, because the cockpit is
    informational and must render; but it says the default's real name rather than a vendor's.
    """
    from openfactory.adapters.agent.registry import harness_kind, known_roles, model_for

    proj = None
    try:
        proj = ProjectRegistry().get(project)
    except Exception as exc:  # noqa: BLE001 — informational surface; render the defaults
        log.warning("panel: no registry entry for %r, showing deployment defaults (%s)",
                    project, str(exc)[:120])

    kinds, models = {}, {}
    # `known_roles()` and not the shipped table: a role this deployment installed as an add-on
    # has a `harness:` / `model:` line of its own, and a cockpit that cannot show it is a line a
    # person cannot check. An add-on role is registered only by the package that invokes it, so
    # every row shown here is one somebody on this deployment runs.
    for role in known_roles():
        try:
            kinds[role] = harness_kind(proj, role)
            models[role] = model_for(proj, role) or "default"
        except Exception as exc:  # noqa: BLE001 — one bad role must not blank the cockpit
            log.warning("panel: could not resolve the %s axis for %r (%s)",
                        role, project, str(exc)[:120])
            kinds[role], models[role] = "?", "default"

    distinct = sorted(set(kinds.values()))
    label = (_HARNESS_LABELS.get(distinct[0], distinct[0]) if len(distinct) == 1
             # MIXED IS THE INTERESTING CASE, so it is said out loud rather than collapsed to the
             # executor's: "an independent reviewer on a different engine" is exactly what the
             # per-role axis is for, and a single name would hide the thing worth seeing.
             else " · ".join(f"{r}:{_HARNESS_LABELS.get(k, k)}" for r, k in sorted(kinds.items())))

    route = ""
    try:
        # DECLARED, not resolved. `resolve_route` reads an ENVIRONMENT, and the panel's container
        # carries none of the discriminating variables (its terraform enumerates them), so asking
        # it here fell through every branch and reported `anthropic` for a Bedrock deployment —
        # a vendor name reached by absence, indistinguishable from a real answer.
        from openfactory.adapters.agent.routes import declared_route

        route = declared_route(proj)
    except Exception as exc:  # noqa: BLE001
        log.warning("panel: could not resolve the auth route for %r (%s)", project, str(exc)[:120])
    return label, models, route


def _hosted_boards() -> list[str]:
    """`board_names()` for the cockpit, best-effort: a broken add-on must not blank the cockpit,
    and an empty list makes the page drop the clause rather than say something false."""
    try:
        from openfactory.adapters.board.factory import board_names

        return board_names(hosted=True)
    except Exception:  # noqa: BLE001 — the how-to loses one clause; the cockpit still draws
        log.warning("could not list the boards this deployment can build", exc_info=True)
        return []


@app.get("/api/factory/{project}")
def factory(project: str) -> dict:
    """A project's cockpit: what harness / auth / tokens it runs on, plus deep-links to
    that project's sources of truth (its board, its workflows on the engine, its logs,
    its parameters). Read-only — a place to SEE and jump out to, never to configure."""
    # A REGION IS A CLOUD'S WORD, and this deployment may not have a cloud. The literal
    # `eu-west-2` was shown to an operator who has never configured AWS at all, on a stack that
    # is entirely local and free — which is the product's DEFAULT shape, not a degraded one
    # (2026-08-14: *"I never set up anything on amazon… this scenario here is 100% free"*). Empty means
    # "this installation has no region", and the panel drops the gauge rather than inventing
    # somebody else's.
    region = _region()
    tokens = _token_pool_meta()
    # AND THE LINK OBEYS THE SAME RULE THE COMMENT ABOVE STATES (#163). It ended
    # `or 'eu-west-2'` — inventing the first deployment's region three lines under a sentence
    # promising the panel "drops the gauge rather than inventing somebody else's". No region, no
    # console button: `_links` already drops the ones this deployment cannot honour.
    console = f"https://{region}.console.aws.amazon.com" if region else ""

    # NO ENGINE LINK IS A BUTTON THAT SAYS WHY, never a guess (#183). This started from
    # `https://cloud.temporal.io`, so a deployment with no engine declared — and a log line saying
    # its "engine links" were "hidden" — drew a working button to somebody else's console; and
    # `ui_base()` answered a local port nothing had been started on. An empty base is no link:
    # `jump()` greys the button and its title is the sentence `_links` carries.
    temporal_base, namespace = "", ""
    try:
        from openfactory.runtime.temporal.view import temporal_config, ui_base

        temporal_base, (_, namespace) = ui_base().rstrip("/"), temporal_config()
    except Exception as exc:  # noqa: BLE001 — the panel renders without the engine links
        log.warning("panel: no Temporal coordinates, engine links hidden (%s)", str(exc)[:120])
    if namespace and temporal_base:
        q = quote(f'WorkflowId STARTS_WITH "openfactory-{project}-"')
        temporal = f"{temporal_base}/namespaces/{namespace}/workflows?query={q}"
    else:
        temporal = temporal_base

    board = None
    # NOT DEFAULTS — UNKNOWNS. `load_manifest` always raises on the deployed panel: the registry's
    # `repo_path` is a placeholder (`/work/<project>`) that exists only in the Fargate job, so the
    # except branch below fired on every cockpit load and these two literals were what shipped. A
    # project configured `review_mode: blocking` was described to its operator as advisory.
    # WHETHER THIS PROJECT IS PICKED UP AT ALL (#134). `None` = the registry could not be read,
    # which the panel renders as its own sentence — a project whose pickup we cannot check is not
    # a project we may describe as armed.
    pickup: bool | None = None
    single_agent, review_mode = True, ""
    try:
        proj = ProjectRegistry().get(project)
        pickup = bool(getattr(proj, "enabled", True))
        # ASKED OF THE BOARD, NOT SPELLED HERE (#162). This built
        # `https://github.com/{orgs|users}/{owner}/projects/{n}` by hand, from GitHub Projects v2
        # vocabulary, on the reference surface of a product sold as vendor-agnostic — so an Azure
        # or Jira deployment's operator got a github.com link to a page that does not exist. The
        # org-vs-user asymmetry that used to live here moved with it, into the adapter that knows
        # which vendor has one.
        board = _board_url(proj) or None
        try:  # the pipeline shape depends on whether this project runs a separate planner
            from openfactory.loader import load_manifest
            mf = load_manifest(proj)
            single_agent, review_mode = (not mf.planner_stage), mf.review_mode
        except Exception as exc:  # noqa: BLE001 — fall back to the default pipeline shape
            # The cockpit then DESCRIBES A PIPELINE THIS PROJECT MAY NOT RUN, which is worse than
            # describing none: somebody reads stations that never execute.
            log.warning("panel: could not read %s's manifest; showing the default pipeline (%s)",
                        getattr(proj, "name", "?"), str(exc)[:120])
    except Exception as exc:  # noqa: BLE001 — the cockpit is informational
        log.warning("panel: could not resolve the project for the cockpit (%s)", str(exc)[:120])

    # WHAT THIS PROJECT ACTUALLY RUNS ON, resolved — not asserted.
    #
    # `harness` was the literal string "Claude Code" and `models` was read from the process's
    # environment. Both predate the axes being configurable, and both survived the axes becoming
    # configurable, so the cockpit told every reader the same answer whatever the registry said: a
    # project on `harness: opencode` with `model: amazon-bedrock/...` still displayed "Claude Code"
    # and "default". On the surface ADR-0038 calls the REFERENCE one, and about the axis whose
    # entire purpose is being a per-project choice.
    #
    # Per ROLE, because the axis is per role: a deployment that reviews on a different engine from
    # the one that wrote the code is the case the seam exists for, and one string cannot say it.
    harness, models, auth_route = _axes(project)

    return {
        "project": project,
        "harness": harness,
        # the token pool's SHAPE is still worth showing, but it is not the auth story: a Bedrock or
        # gateway deployment has no pool at all, and "unknown" was the honest-but-useless answer
        "auth_format": auth_route or tokens["format"],
        # THE ROUTE IS NOT THE CREDENTIAL, and the panel showed only the route. An operator on a
        # Claude subscription read "anthropic" and could not tell whether the factory was
        # spending his subscription or an API key — two very different bills (2026-08-14:
        # *"não está o tipo subscription"*). Named from the variable that is actually present,
        # and "unknown" when this process cannot see either: a guess about somebody's billing is
        # worse than a blank.
        "auth_credential": _auth_credential(),
        "auth_pool_format": tokens["format"],
        "tokens": tokens,
        # ADR-0014: single-agent projects have no separate planner — the panel drops the plan
        # station and shows one "agent" model instead of "plan · exec".
        # THE FLOOR CARD SAYS WHETHER A CARD IN TO-DO WILL BE PICKED UP, and until now it could
        # only see the poller SCHEDULE — a deployment-wide thing. A project disabled with
        # `enable false` was still described as "goes into production on its own", which is the
        # screen promising work the platform will not do (pilot, 2026-08-17).
        "pickup_enabled": pickup,
        "single_agent": single_agent,
        "review_mode": review_mode,
        "models": models,  # per-role, resolved through the registry (env → project → default)
        "region": region,
        # THE BOARDS THIS DEPLOYMENT CAN BUILD ON SOMEBODY'S SERVICE, EACH BY ITS ROW'S OWN NAME.
        # The cockpit's how-to spelled three vendors in the page — so an installed add-on's board
        # was missing from the list that says what is supported, and a row shipped tomorrow would
        # be too. The page says what this field says and spells no vendor of its own.
        "hosted_boards": _hosted_boards(),
        # LINKS TO PLACES THIS DEPLOYMENT ACTUALLY HAS. Three of these five addressed an AWS
        # account a compose install does not own — CloudWatch, SSM, ECS — and one of them named
        # a log group from the product's OLD name (`sdlc-sandbox`), so the operator's panel
        # offered four buttons and three led to somebody else's console (2026-08-14). A local
        # deployment keeps the two that are real; the cloud ones appear when there IS a cloud.
        "links": _links(board, temporal, console, region),
        # THE GREYED ENGINE BUTTON'S OWN SENTENCE (#183) — which variable says where the engine's
        # UI is, asked of the definition so the page never spells one of its own. BESIDE `links`,
        # NOT IN IT: `links` is the set of BUTTONS, and the how-to's guard holds every key there to
        # a paragraph that teaches it. A sentence is not a button — it went in as
        # `links["temporal_hint"]` first, and that guard said so.
        "engine_ui_hint": "" if temporal else _engine_ui_unsaid(),
    }


def _build_report() -> dict:
    """Which code each half of this deployment runs — now `namespace.build_agreement`,
    kept here as the web layer's name for it (#144). Moved because the floor ladder and
    the CLI need the same answer, and a second copy is how two surfaces disagree about
    what is running."""
    from openfactory.namespace import build_agreement

    return build_agreement(PANEL_ROLE)


def _region() -> str:
    """The cloud region this deployment runs in, or `""` when it has no cloud.

    A REGION IS A CLOUD'S WORD. The literal `eu-west-2` was shown to an operator who has never
    configured AWS, on a stack that is entirely local and free — which is this product's DEFAULT
    shape, not a degraded one (2026-08-14). Its own function so the answer can be asserted
    rather than inferred from where it happens to be assigned."""
    return os.environ.get("AWS_DEFAULT_REGION", "") if _boxes_are_remote() else ""


def _links(board: str | None, temporal: str, console: str, region: str) -> dict:
    """The buttons under the project bar — only the ones this deployment can honour."""
    links: dict[str, str | None] = {"board": board, "temporal": temporal}
    if not _boxes_are_remote():
        return links
    # THE PRODUCT'S OWN PREFIX, not a literal: `sdlc-sandbox` outlived the rename here and
    # pointed at a log group no deployment has carried since (`openfactory/namespace.py` is
    # where that name lives). The deployment's own variables win when it sets them.
    from openfactory.namespace import BRANCH_PREFIX as _PRODUCT

    group = os.environ.get("OPENFACTORY_LOG_GROUP") or f"/ecs/{_PRODUCT}-sandbox"
    cluster = os.environ.get("OPENFACTORY_FARGATE_CLUSTER") or f"{_PRODUCT}-sandbox"
    encoded = group.replace("/", "$252F")
    links["cloudwatch"] = (f"{console}/cloudwatch/home?region={region}"
                           f"#logsV2:log-groups/log-group/{encoded}")
    links["ssm"] = f"{console}/systems-manager/parameters/?region={region}"
    links["ecs"] = f"{console}/ecs/v2/clusters/{cluster}/tasks?region={region}"
    return links


def _board_url(project) -> str:
    """Where a person goes to see this project's board, or `""` — through the board port.

    NEVER RAISES AND NEVER GUESSES. The cockpit is informational: a project with no board, an
    unknown vendor, or a provider that cannot say all resolve to no button, which is honest. A
    link to the wrong host is not — it is a person clicking through to a 404 and concluding the
    platform has lost their board."""
    try:
        from openfactory.adapters.board.factory import build_board

        # NO CREDENTIAL IS RESOLVED HERE, and that is the point: not one of the three `url()`
        # implementations reads a token — they build from coordinates the registry already holds.
        # The first version asked for one anyway, so on an App-authenticated deployment (no PAT in
        # the environment, the documented pilot shape) the panel MINTED a GitHub App installation
        # token on every cockpit load to compose a string, and a mint that failed deleted a link
        # that needs no credential at all. Adversarial review, 2026-08-20.
        made = build_board(project)
        return str(made.url() or "") if made is not None else ""
    except Exception as exc:  # noqa: BLE001 — a missing link never fails a page
        log.warning("panel: could not resolve the board link for %s (%s)",
                    getattr(project, "name", "?"), str(exc)[:120])
        return ""



