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
import time
from html import escape as _h
from pathlib import Path
from urllib.parse import parse_qsl, quote

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, Header, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import (
    HTMLResponse,
    JSONResponse,
    PlainTextResponse,
    RedirectResponse,
    StreamingResponse,
)
from pydantic import BaseModel

from openfactory import actions
from openfactory.contracts.project import Project, ProviderRef
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
    if request.url.path.startswith("/api/"):
        from openfactory.identity import build_identity

        try:
            provider = build_identity()
        except ValueError as exc:
            # a deployment naming a provider this build lacks — or one it did not finish
            # configuring (#33: an `oidc` row with no issuer) — must fail CLOSED: "I cannot
            # check credentials" is not "let everyone in" (same rule as require_auth). The
            # sentence is the provider's own, so the log names the variable and not a guess.
            log.error("OPENFACTORY_IDENTITY_UNKNOWN the configured identity provider cannot be "
                      "built — refusing every request rather than falling back to open: %s", exc)
            return JSONResponse({"detail": "identity provider unavailable"}, status_code=503)
        if not getattr(provider, "open_to_everyone", lambda: False)():
            auth = request.headers.get("authorization", "")
            supplied = (
                auth[7:] if auth.startswith("Bearer ")
                else (request.cookies.get("openfactory_token")
                      or request.query_params.get("token") or "")
            )
            subject = provider.identify(credential=supplied, via="panel")
            if subject is None:
                return JSONResponse(_unauthorized(provider), status_code=401)
            scopes = _scopes_of(subject)
            wanted = _scope_of_path(request.url.path)
            if scopes is not None and wanted is not None and wanted not in scopes:
                log.warning("DENIED_SCOPE_READ %s (%s) for a credential scoped to %s",
                            request.url.path, wanted, ", ".join(sorted(scopes)) or "nothing")
                return JSONResponse(
                    {"detail": f"this credential is scoped to "
                               f"{', '.join(sorted(scopes)) or 'nothing'} and that is part of the "
                               f"{wanted}."},
                    status_code=403)
    return await call_next(request)


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


def _scope_of_path(path: str) -> str | None:
    """Which area a request belongs to, or None when every credential may read it."""
    if path in _UNSCOPED_ROUTES:
        return None
    if path.startswith(_PRODUCT_ROUTES):
        return actions.PRODUCT
    return actions.FLOOR


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
    from openfactory.identity import build_identity

    try:
        provider = build_identity()
    except ValueError as exc:
        # A deployment that NAMES a provider this build does not have — or has not configured —
        # is misconfigured, and the safe reading of "I cannot check credentials" is not "let
        # everyone in".
        log.error("OPENFACTORY_IDENTITY_UNKNOWN the configured identity provider cannot be built "
                  "— refusing every request rather than falling back to open: %s", exc)
        raise HTTPException(status_code=503, detail="identity provider unavailable") from None

    if getattr(provider, "open_to_everyone", lambda: False)():
        return
    token = authorization.removeprefix("Bearer ").strip()
    if provider.identify(credential=token, via="panel") is None:
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
                         via="panel", admin=True, scopes=scopes)


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
    """
    from openfactory.runtime.temporal.view import ATTENTION_STATES
    from openfactory.runtime.temporal.workflow import merge_wait_note

    return {
        "alarm": sorted(ATTENTION_STATES),
        "merge_wait": {"auto": merge_wait_note(True), "human": merge_wait_note(False)},
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
    provider: str = "github"
    repo: str | None = None
    board_owner: str | None = None
    board_number: str | None = None


@app.post("/api/projects", dependencies=_AUTH)
def add_project(body: NewProject) -> dict:
    options: dict[str, str] = {}
    if body.board_owner and body.board_number:
        options = {"board_owner": body.board_owner, "board_number": body.board_number}
    try:
        ProjectRegistry().add(
            Project(
                name=body.name, repo_path=body.repo_path,
                tracker=ProviderRef(kind=body.provider, repo=body.repo, options=options),
            )
        )
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
            cost = next(
                ((e.get("data") or {}).get("cost_usd") for e in reversed(evs)
                 if (e.get("data") or {}).get("cost_usd")),
                None,
            )
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
    from openfactory.runtime.temporal.view import ATTENTION_STATES

    return [j for j in list_jobs() if j.get("state") in ATTENTION_STATES]


async def _verdict_of(client, job: dict) -> dict:
    """This platform's own reading of the change a person is being asked about (#149).

    UNREADABLE IS A VALUE, NOT AN ABSENCE. A workflow that will not answer the query is usually one
    whose worker is gone; rendering that as "no review" would tell somebody at a merge gate that
    nothing checked their diff, which is a different and much worse claim than "I could not look".
    """
    from openfactory.review import verdict as verdict_read
    from openfactory.runtime.temporal.workflow import JobWorkflow

    wf_id = job.get("workflow_id")
    if not wf_id:
        return verdict_read.headline(None)
    try:
        handle = client.get_workflow_handle(wf_id, run_id=job.get("run_id") or None)
        raw = await handle.query(JobWorkflow.verdict)
    except Exception as exc:  # noqa: BLE001 — the gate degrades, never 500s
        log.info("could not read %s's review verdict (%s)", wf_id, str(exc)[:120])
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
    for j in await tv.list_jobs(client, ns):
        state, act = j.get("state"), (j.get("action") or {})
        # WHAT THIS PLATFORM'S OWN REVIEWER FOUND, on the one screen where somebody is deciding
        # (#149). It was computed at the REVIEW station, published by a query, and shown nowhere
        # near the gate — so a pull request the review REJECTED and one it approved produced
        # byte-identical cards, and the pilot found out only by asking the tech-lead in words.
        # Read HERE rather than in `list_jobs`: it is one query RPC per item and the inbox is, by
        # construction, only the jobs that need a person.
        review = await _verdict_of(client, j)
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
        from openfactory.registry import ProjectRegistry

        try:
            proj = ProjectRegistry().get(project)
        except KeyError:
            raise HTTPException(status_code=404,
                                detail=f"no project called {project!r} here") from None
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
    from openfactory.identity import build_identity

    try:
        provider = build_identity()
    except ValueError as exc:
        log.error("OPENFACTORY_IDENTITY_UNKNOWN — refusing the stream rather than falling back to "
                  "open: %s", exc)
        await ws.close(code=1011, reason="identity provider unavailable")
        return

    if not getattr(provider, "open_to_everyone", lambda: False)():
        supplied = (ws.query_params.get("token")
                    or ws.cookies.get("openfactory_token") or "")
        who = provider.identify(credential=supplied, via="panel")
        if who is None:
            # 1008 = policy violation. The browser can tell this apart from a network drop, which
            # is what stops it retrying forever against a credential that will never work.
            await ws.close(code=1008, reason="unauthorized")
            return
        # …AND THE SCOPE, WHICH THIS DID NOT CHECK (#145). Identity alone was the whole test, so a
        # PRODUCT-scoped credential — refused with a 403 on every HTTP read of the floor, by the
        # middleware three lines up in the same file — was accepted here and handed the project
        # list and any project's conversation. The gate the middleware cannot see is the gate
        # somebody has to write by hand, and the hand-written one checked half of what it copied.
        scopes = _scopes_of(who)
        if scopes is not None and actions.FLOOR not in scopes:
            await ws.close(code=1008, reason="this credential does not open the floor")
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

    reader = asyncio.create_task(_resubscribe())
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
    try:
        ProjectRegistry().get(project)
    except KeyError:
        raise HTTPException(404, f"no project named {project!r} in this deployment") from None
    return _events(project, issue)


@app.get("/api/jobs/{project}/{issue}/stream")
async def job_stream(project: str, issue: str, request: Request) -> StreamingResponse:
    try:  # a de-registered project is a 404, not a 500 — see `job_events`
        path = events_file(ProjectRegistry().get(project), issue)
    except KeyError:
        raise HTTPException(404, f"no project named {project!r} in this deployment") from None
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

    return StreamingResponse(gen(), media_type="text/event-stream")


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
        p = ProjectRegistry().get(project)
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
        raise RuntimeError("runtime extra not installed (pip install -e '.[runtime]')") from exc
    addr, ns = tv.temporal_config()
    return tv, addr, ns


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
            "connected": True, "address": addr, "ui_base": tv.ui_base(), "build": build,
            "jobs": await tv.list_jobs(client, ns),
            # WHETHER WORK IS PICKED UP AT ALL — a different fact from `connected`, which only
            # says the engine answers. See `tv.intake`: a paused poller under a live engine
            # rendered as a healthy factory, beneath a line promising that TO-DO cards start on
            # their own. Carried on the SAME payload the header already reads, so nothing has to
            # remember to fetch it.
            "intake": await tv.intake(client),
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
#: the job list. The stream ticks every 2s; these describe 3-5 Temporal schedules and read a file,
#: so they ride a longer clock. Ten seconds is far inside the poller's own 3-minute tick.
_STREAM_SLOW_S = 10.0


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

    THE SCHEDULE READS ARE CACHED, deliberately. `tv.intake` describes 3-5 Temporal schedules;
    doing that every 2 seconds for every connected browser turns a status line into load. Ten
    seconds is far inside the poller's own 3-minute tick, so nothing observable lags."""

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
                    slow = {"intake": await tv.intake(client), "build": _build_report()}
                    slow_at = now
                frame = {"connected": True, "address": addr, "ui_base": tv.ui_base(),
                         "jobs": await tv.list_jobs(client, ns), **slow}
            except Exception as exc:  # engine blip — emit a disconnected frame, retry
                logging.getLogger("openfactory.panel").warning("temporal_stream: %r", exc)
                client = None
                slow, slow_at = {}, 0.0   # never carry an intake read from before the blip
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

    return StreamingResponse(gen(), media_type="text/event-stream")


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
            if (_login_provider() is not None or _form_login() is not None) else None}


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


_NO_CACHE = {"Cache-Control": "no-store"}  # the panel HTML changes on every deploy —
# a browser must never serve a stale copy (else "I don't see the change" confusion).


@app.get("/")
def index() -> HTMLResponse:
    return HTMLResponse(_read_panel(), headers=_NO_CACHE)


@app.get("/p/{project}")
def project_page(project: str) -> HTMLResponse:
    # same single-page app; the client reads the path to focus one project's floor.
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
    nobody has registered yet: a form nobody can fill in is a dead end, not a door."""
    from openfactory.identity import build_identity
    from openfactory.identity.local import LocalIdentity

    try:
        provider = build_identity()
    except (ValueError, TypeError):
        return None
    if isinstance(provider, LocalIdentity) and provider.login_path:
        return provider
    return None


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
    provider = _login_provider()
    if provider is None:
        local = _form_login()
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
    response.set_cookie(_sso.TOKEN_COOKIE, login.id_token,
                        max_age=max(1, login.expires_at - int(time.time())),
                        samesite="lax", secure=request.url.scheme == "https", path="/")
    return response


@app.post(_sso.LOGIN_PATH)
async def auth_login_form(request: Request):
    """The local row's login: a registered person, their password, a session (#33)."""
    local = _form_login()
    if local is None:
        return _no_login_page()
    fields = await _form_fields(request)
    next_path = _sso.safe_next(fields.get("next", "/"))
    token = local.people().login(fields.get("id", ""), fields.get("password", ""))
    if not token:
        log.info("OPENFACTORY_LOGIN_REFUSED a sign-in for %r was refused", fields.get("id", "")[:80])
        return _auth_page("Sign in", _login_form(next_path, why="that is not a registered person, "
                                                 "or not their password"), status=401)
    return _session_response(next_path, token)


def _session_response(next_path: str, token: str) -> RedirectResponse:
    """A session token in the cookie the panel reads, then `next`. Not HttpOnly, for the reason
    the OIDC callback gives on its own copy of this line."""
    from openfactory.identity.people import SESSION_TTL_SECONDS

    response = RedirectResponse(next_path, status_code=303, headers=_NO_CACHE)
    response.set_cookie(_sso.TOKEN_COOKIE, token, max_age=SESSION_TTL_SECONDS, samesite="lax",
                        path="/")
    return response


@app.get(_REGISTER_PATH)
def auth_register(request: Request, invite: str = ""):
    """The one-time link's landing: choose a name and a credential. 404 for a link this
    deployment did not issue, already used or expired — one sentence for all three, on purpose."""
    local = _local_provider()
    invitation = local.people().invitation_for(invite) if local is not None else None
    if invitation is None:
        return _no_invitation()
    return _auth_page("Register", _register_form(invite, invitation.display))


@app.post(_REGISTER_PATH)
async def auth_register_form(request: Request):
    local = _local_provider()
    if local is None:
        return _no_invitation()
    fields = await _form_fields(request)
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
    return _session_response("/", session)


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
    local = _local_provider()
    if local is not None:
        auth = request.headers.get("authorization", "")
        held = (auth[7:] if auth.startswith("Bearer ")
                else request.cookies.get(_sso.TOKEN_COOKIE, ""))
        if held and local.people().revoke(held):
            log.info("OPENFACTORY_LOGOUT a registered person's session was revoked")
    response = HTMLResponse(
        "<!doctype html><meta charset=utf-8><title>signed out</title>"
        "<script>try{localStorage.removeItem('openfactory_token')}catch(e){}"
        "location.replace('/')</script>signed out.", headers=_NO_CACHE)
    response.delete_cookie(_sso.TOKEN_COOKIE, path="/")
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

    temporal_base, namespace = "https://cloud.temporal.io", ""
    try:
        from openfactory.runtime.temporal.view import temporal_config, ui_base

        temporal_base, (_, namespace) = ui_base(), temporal_config()
    except Exception as exc:  # noqa: BLE001 — the panel renders without the engine links
        log.warning("panel: no Temporal coordinates, engine links hidden (%s)", str(exc)[:120])
    if namespace:
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
        # LINKS TO PLACES THIS DEPLOYMENT ACTUALLY HAS. Three of these five addressed an AWS
        # account a compose install does not own — CloudWatch, SSM, ECS — and one of them named
        # a log group from the product's OLD name (`sdlc-sandbox`), so the operator's panel
        # offered four buttons and three led to somebody else's console (2026-08-14). A local
        # deployment keeps the two that are real; the cloud ones appear when there IS a cloud.
        "links": _links(board, temporal, console, region),
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



