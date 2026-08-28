"""One HTTP client for every Azure DevOps axis (C-20).

Four adapters — work items, boards, repos, pipelines — all speak to the same host with the same
credential and the same failure modes, so the client is shared and the adapters carry only their
own vocabulary. That is also what keeps the axes independent: a deployment may run Azure Boards
with GitHub repos, and nothing here assumes otherwise.

TWO CREDENTIAL SHAPES, ON PURPOSE.

    PAT      what a client provisions: `Basic base64(":" + pat)` — Azure DevOps's own convention
    Bearer   a JWT from `az account get-access-token --resource 499b84ac-…`

The second is not a convenience: it is what makes this provable on a laptop with no secret
created, which is the OSS distribution's whole story. Detected from the token's shape rather than
configured, because a deployment that had to declare WHICH KIND of token it pasted would get it
wrong exactly once and see 401 with no explanation.

THE ORG AND PROJECT ARE COORDINATES, not configuration to guess. Azure DevOps nests
`organization / project / repository`, one level deeper than GitHub's `owner/name`, and every
route needs both — so they are read from the provider's `options` and validated at construction.
A missing one fails when the adapter is built, not on the first call inside a job.
"""

from __future__ import annotations

import base64
import json
import logging
import os
import subprocess
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

log = logging.getLogger("openfactory.azure_devops")

#: The Azure DevOps resource id, for `az account get-access-token --resource …`. A constant of the
#: platform, not of a deployment — every tenant uses the same one.
ADO_RESOURCE = "499b84ac-1321-427f-aa17-267ca6975798"

#: Default env var naming the credential. The registry may override with `token_env`, the pattern
#: every other axis already uses (Slack's `bot_token_env`, the tracker's `token_env`).
DEFAULT_TOKEN_ENV = "AZURE_DEVOPS_PAT"

#: The API version every route here is written against. Pinned, because Azure DevOps changes
#: response shapes between versions and an unpinned call is a silent break on their release day.
API_VERSION = "7.1"


class AzureDevOpsError(RuntimeError):
    """An ADO call that failed, carrying enough to act on: the route and what the server said."""


def coordinates(project, *, ref) -> tuple[str, str]:
    """`(organization, ado_project)` for one axis — the ONLY place that spelling lives.

    FOUR REGISTRIES HAD FOUR COPIES OF THIS, and each carried a comment promising *"if any of the
    four spellings moves, all four move together"* — a promise no comment can keep, and one that
    had already been broken twice before this was written. `tracker/registry.py` documented `org`
    as an alias for `organization` and a fallback to the tracker's `repo`; the board's copy raised
    ValueError on a row written exactly the way the tracker documents, and the environment's copy
    raised at `factory.py`'s PromotionRunner construction, before a pipeline was ever read.

    Both failures share a shape worth naming: the axes did not merely disagree about whether a row
    was valid — they could disagree about WHICH PROJECT it named, and a board reporting on work
    items the tracker never writes to is a factory that looks like it is running.

    `ref` is the axis's own `ProviderRef` (the tracker's for tracker and board, the forge's for
    forge and pipelines), because a deployment may name different coordinates per axis. The
    tracker's `repo` is the fallback for the ADO project, and ONLY when the tracker is Azure
    DevOps: a Jira tracker's `repo` is a Jira key, and inheriting it would aim an adapter at a
    project that does not exist while looking configured — a 404 blamed on the pipeline."""
    options = dict(getattr(ref, "options", None) or {})
    organization = str(options.get("organization") or options.get("org") or "").strip()
    declared = str(options.get("project") or "").strip()
    if declared:
        return organization, declared

    tracker = getattr(project, "tracker", None)
    if (getattr(tracker, "kind", "") or "").strip().lower() != "azure_devops":
        return organization, ""
    # THE ADO PROJECT, NOT A REPOSITORY. Azure DevOps nests many git repos inside one project, so
    # this fallback is only sound because an ADO *tracker* names the project in `repo` — which is
    # why the forge must not reach for `repo_of()` here: that resolves to a git repository, and
    # this deployment really does contain a repo whose name matches its project.
    return organization, (getattr(tracker, "repo", None) or "").strip()


#: Seconds before an `az` JWT's stated expiry at which a fresh one is minted rather than reused.
#: The credential is read at the START of a call whose round trip is bounded by `urlopen(timeout=60)`
#: below, so a margin under a minute can hand out a token that expires while the request is in
#: flight — a 401 on the last station of a job that had already done all of its work. Five minutes
#: also absorbs a clock a few minutes out of step with Azure's, which is ordinary on a laptop that
#: has been asleep.
_AZ_REFRESH_MARGIN_SECONDS = 300

#: The minted JWT and the epoch second it expires, or None. PROCESS-WIDE because the credential is
#: the machine's and not a project's: every ADO axis of every project this deployment drives mints
#: the same token from the same `az` login, and one subprocess an hour instead of one per HTTP call
#: is the entire point of holding it.
_az_cached: tuple[str, float] | None = None

#: HELD ACROSS THE MINT, not just across the read. The poller runs projects in threads
#: (`asyncio.to_thread`), so an expiry reached under load is N threads arriving at once; releasing
#: the lock before the subprocess would spawn one `az` per thread to obtain N copies of the same
#: machine-wide token. The wait is bounded by `_az_mint`'s own 30-second timeout.
_az_lock = threading.Lock()


def _az_mint() -> tuple[str, float] | None:
    """One `az account get-access-token` call → (token, epoch expiry), or None on anything else.

    THE SEAM THE TEST SUITE CLOSES. A developer's `az` login is a live credential, and
    `tests/conftest.py` strips those from the environment — which a subprocess escapes. Everything
    that reaches the CLI is behind this one function so the suite has a single thing to neutralise.
    """
    try:
        done = subprocess.run(
            ["az", "account", "get-access-token", "--resource", ADO_RESOURCE, "-o", "json"],
            capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        # NO `az` IS AN ORDINARY STATE, NOT AN ERROR — and it is the NORMAL state of a deployed
        # factory. The container a worker runs in has no Azure CLI and needs none: it holds a
        # service user's PAT precisely so that it depends on no human being logged in anywhere.
        # Anything above debug here would print an alarming line on every healthy production call.
        return None
    if done.returncode != 0:
        log.debug("`az account get-access-token` exited %s", done.returncode)
        return None
    try:
        got = json.loads(done.stdout or "{}")
        token = str(got.get("accessToken") or "").strip()
        # `expires_on` IS THE ONE TO READ. `az` answers both, and its sibling `expiresOn` is LOCAL
        # WALL TIME carrying no zone — a different instant on any machine whose timezone is not the
        # one the CLI formatted it in, which is how a token gets treated as an hour fresher or an
        # hour staler than it is. This one is epoch seconds and unambiguous everywhere.
        expires = float(got.get("expires_on") or 0)
    except (ValueError, TypeError):
        log.debug("`az account get-access-token` did not answer the JSON its contract documents")
        return None
    if not token:
        return None
    # An answer carrying no usable expiry is still a usable token: assume the documented hour so it
    # is refreshed on schedule rather than trusted forever.
    return token, expires or (time.time() + 3600)


def az_token() -> str | None:
    """A JWT minted by THIS MACHINE's `az` login, or None — never raises, never logs the value.

    THE FALLBACK, NEVER THE PREFERENCE. `token_for` reaches this only when the variable a project
    names holds nothing, so a deployment running on a service user's PAT never spawns a subprocess
    on its hot path and never depends on the Azure CLI being installed at all.

    It exists because the opposite deployment is equally real: a laptop inside an enterprise tenant
    where a person cannot create a PAT, and `az account get-access-token` is the only credential
    they have. That JWT lasts about an hour. Resolved once at worker start it makes every job after
    the first hour fail — measured, and the only cure was restarting the worker.

    Shaped like `forge/github.py::discover_token` — a vendor's CLI, captured, timed out, None on
    anything unexpected. Unlike that one it is consulted at each USE rather than once at onboarding,
    which is what lets a job that outlives one token still push and still open its pull request.
    """
    global _az_cached
    with _az_lock:
        cached = _az_cached
        if cached is not None and time.time() < cached[1] - _AZ_REFRESH_MARGIN_SECONDS:
            return cached[0]
        minted = _az_mint()
        if minted is not None:
            _az_cached = minted
            return minted[0]
        # A FAILED REFRESH DOES NOT EVICT A CREDENTIAL THAT IS STILL VALID. `az` fails for reasons
        # that pass on their own — a laptop off the VPN for a minute, a throttled tenant — and
        # dropping a token still good for fifty minutes because one attempt timed out would turn a
        # blip into exactly the mid-job auth failure this function exists to prevent.
        if cached is not None and time.time() < cached[1]:
            return cached[0]
        return None


def token_for(options: dict | None = None) -> str | None:
    """The credential this deployment holds for Azure DevOps, or None.

    The registry NAMES the variable and the environment holds the value — never the other way
    round, so a token cannot reach a manifest, a log or a proof file.

    THE PAT WINS, ALWAYS, AND WITHOUT SPAWNING ANYTHING. A deployment that set the variable has
    already said what its credential is, and a hosted factory's is a service user's PAT — chosen
    so that the platform depends on nobody being logged in. `az` is consulted only when that
    variable is empty, which on a server it never is.
    """
    name = ((options or {}).get("token_env") or DEFAULT_TOKEN_ENV).strip()
    pat = (os.environ.get(name) or "").strip()
    if pat:
        return pat
    return az_token()


def _auth_header(token: str) -> str:
    """`Bearer` for a JWT, `Basic` for a PAT — decided from the token, not from configuration.

    A JWT has three dot-separated base64url segments and starts with `ey` (`{"` encoded). A PAT is
    an opaque 52-character string. Asking a deployment to declare which one it pasted is asking it
    to be wrong once and read a bare 401.
    """
    if token.startswith("ey") and token.count(".") == 2:
        return f"Bearer {token}"
    return "Basic " + base64.b64encode(f":{token}".encode()).decode()


class AzureDevOpsClient:
    """Requests against one organisation/project pair."""

    def __init__(self, *, organization: str, project: str, token: str | None = None,
                 options: dict | None = None) -> None:
        org = (organization or "").strip().rstrip("/")
        # accept either the bare name or the full URL a client copies out of their browser
        if "://" in org:
            org = org.rstrip("/").rsplit("/", 1)[-1]
        if not org or not (project or "").strip():
            raise ValueError(
                "Azure DevOps needs both an organization and a project — its routes nest "
                f"organization/project/resource. Got organization={organization!r}, "
                f"project={project!r}; declare them under the provider's `options`."
            )
        self.organization = org
        self.project = project.strip()
        self._static_token = token
        self._options = dict(options or {})
        self.base = f"https://dev.azure.com/{self.organization}"

    @property
    def token(self) -> str | None:
        """Resolved at each use, never frozen at construction.

        The forge and the board already did this on their own adapters, each with a comment saying
        why; the TRACKER could not, because it builds one client in `__init__` and keeps it for the
        whole job. That is the object that moves a card to Done and posts the closing comment — the
        LAST things a job does — so a credential captured when the job started is precisely the one
        that has expired by the time it is needed. The same defect one level down, and resolving it
        here settles it for every axis that shares this client at once.
        """
        return self._static_token or token_for(self._options)

    # ---- the one request path -------------------------------------------------------------

    def call(self, method: str, path: str, *, body: dict | list | None = None,
             params: dict | None = None, project_scoped: bool = True,
             content_type: str = "application/json", api_version: str | None = None) -> dict:
        """One ADO request. Returns the parsed body ({} when the server sends none).

        RAISES on failure rather than returning a sentinel: every caller here is deciding
        something about a client's work — which column a card sits in, whether a PR merged — and a
        falsy answer that means "the call failed" is indistinguishable from one that means "no".
        That ambiguity is what `items_in_status` returning `[]` on an unreadable board would cost:
        the poller would read an empty queue and report a quiet factory.
        """
        if not self.token:
            raise AzureDevOpsError(
                "no Azure DevOps credential: set the variable this project names in "
                f"`options.token_env` (default {DEFAULT_TOKEN_ENV}). A PAT or an `az account "
                f"get-access-token --resource {ADO_RESOURCE}` token both work."
            )
        scope = f"{self.base}/{urllib.parse.quote(self.project)}" if project_scoped else self.base
        query = dict(params or {})
        query.setdefault("api-version", api_version or API_VERSION)
        url = f"{scope}/_apis/{path.lstrip('/')}?{urllib.parse.urlencode(query)}"

        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(url, data=data, method=method.upper())
        req.add_header("Authorization", _auth_header(self.token))
        req.add_header("Accept", "application/json")
        if data is not None:
            req.add_header("Content-Type", content_type)

        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                raw = resp.read().decode() or ""
        except urllib.error.HTTPError as exc:
            detail = ""
            try:
                detail = (exc.read() or b"").decode()[:600]
            except Exception as read_failed:  # noqa: BLE001 — the status is still the finding
                # BEST-EFFORT IS THE REASON TO LOG, NOT THE REASON NOT TO. The body carries ADO's
                # own sentence ("TF401019: the repository does not exist"), which is the difference
                # between a fixable error and a bare 404; losing it silently means the next person
                # debugging a permission problem never learns the server had already explained it.
                log.debug("could not read the error body of %s %s: %s", method, path, read_failed)
            # THE ROUTE IS IN THE MESSAGE. One deployment drives N projects and half these calls
            # differ only by a path segment; "403 Forbidden" without it sends somebody reading
            # every adapter to find which permission is missing.
            raise AzureDevOpsError(
                f"{method.upper()} {path} → {exc.code} {exc.reason}"
                + (f": {_readable(detail)}" if detail else "")
            ) from exc
        except urllib.error.URLError as exc:
            raise AzureDevOpsError(f"{method.upper()} {path} could not be reached: {exc}") from exc

        if not raw.strip():
            return {}
        try:
            parsed = json.loads(raw)
        except ValueError:
            # ADO answers HTML when a route is wrong or the token lacks scope — a 200 with a
            # sign-in page. Parsing that as "no results" is how a silent zero gets believed.
            raise AzureDevOpsError(
                f"{method.upper()} {path} returned {len(raw)} bytes that are not JSON — usually a "
                "sign-in redirect, meaning the credential is missing a scope rather than being "
                "wrong"
            ) from None
        return parsed if isinstance(parsed, dict) else {"value": parsed}

    def values(self, path: str, **kw) -> list:
        """The `value` array ADO wraps every collection in."""
        got = self.call("GET", path, **kw)
        out = got.get("value")
        return out if isinstance(out, list) else []


def _readable(detail: str) -> str:
    """ADO's error body is JSON with the sentence under `message`; anything else passes through."""
    try:
        got = json.loads(detail)
    except ValueError:
        return detail.strip()
    return str(got.get("message") or detail).strip()
