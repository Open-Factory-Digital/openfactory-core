"""OpenID Connect as a row the core ships — SSO out of the box, beside `local` (#33, slice 1).

WHY IN THE CORE AND NOT AN ADD-ON. `registry.py` said for a week that OIDC, SAML and EntraID were
"one module each, joining through the entry-point group", and `docs/configuration.md` said the
same — and none existed anywhere. "Ready for SSO" meant there was somewhere to plug one in, not
that one plugged in. OIDC is a STANDARD, not a vendor: Entra, Okta, Keycloak, Google and Auth0 all
speak it, and a platform sold to enterprises must log in through the buyer's own provider the way
it already speaks GitHub, Azure DevOps and GitLab without anybody installing anything. What stays
outside the core is each deployment's CONFIGURATION — issuer, client id, which of the provider's
groups mean what here — which is not code. SAML stays an add-on. Decided 2026-09-02.

THE ID TOKEN IS THE CREDENTIAL. The port (`base.py`) says `identify` receives *"a bearer token, a
signed assertion, a chat user id"*, and an OpenID `id_token` is exactly the second: a JWT the
issuer signed, naming the person, the audience and an expiry. So the panel's whole authentication
machinery stays what it is — `_panel_gate` reads a Bearer header, a cookie or `?token=` and asks
the deployment's provider — and what the login flow does is put an id_token where the shared
password used to be. No session table, no second store, nothing to replicate across panel
processes: every request is verified against the issuer's published keys, and an expired token is
a 401 that sends the browser back through a login the provider's own session usually answers
without a prompt.

WHAT `identify` CHECKS, AND WHY EACH CHECK IS THERE. A token is somebody only when the header's
algorithm is one of the ASYMMETRIC ones this module lists (`alg: none` and the HS* family are
refused before any key is read — a verifier that accepted HS256 would let anyone forge a token by
signing it with the issuer's PUBLIC key, which is public), the signature verifies against a key
the issuer's JWKS publishes, `iss` is the configured issuer, `aud` contains this client id, and
`exp`/`iat`/`sub` are present with `exp` in the future. Every one of those is a separate mutation
row in the plan that proved this file, because each one is a door on its own.

THE PROVIDER IS BUILT PER REQUEST AND THE NETWORK IS NOT. `build_identity()` is called on every
`/api/*` request, so this class is cheap to construct and the discovery document and the key set
are cached at module level, per issuer, for an hour — with ONE refetch allowed per minute when a
token names a `kid` the cache does not hold, which is how key rotation arrives without a restart
and how an attacker's random `kid` does not become a request-per-request fetch against the
issuer.

NEVER RAISES, like every row of this axis: the gate is a request handler, and a provider that
throws takes the door down instead of closing it. A credential that cannot be verified is nobody,
with one log line saying why at a level that does not page anybody — an expired token is the
normal end of every session, not an incident.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
import secrets
import threading
import time
from dataclasses import dataclass, field
from urllib.parse import urlencode

import jwt

from openfactory.identity.base import Subject
from openfactory.identity.local import PRODUCT_GROUP

log = logging.getLogger("openfactory.identity")

#: The registry row, and the `via` every subject this resolves carries.
KIND = "oidc"

#: The issuer URL — what the provider calls itself, and where `/.well-known/openid-configuration`
#: hangs off. `https://login.microsoftonline.com/<tenant>/v2.0`, `https://accounts.google.com`,
#: `https://<host>/realms/<realm>` (Keycloak), `https://<org>.okta.com`. REQUIRED.
ISSUER_ENV = "OPENFACTORY_OIDC_ISSUER"
#: The client id the provider issued for this deployment. REQUIRED.
CLIENT_ID_ENV = "OPENFACTORY_OIDC_CLIENT_ID"
#: Its secret — optional, because a public client with PKCE is a legitimate registration and
#: this flow always sends a PKCE challenge either way.
CLIENT_SECRET_ENV = "OPENFACTORY_OIDC_CLIENT_SECRET"
#: The callback URL as the provider knows it. Derived from the request when unset, which is
#: right on a laptop and wrong behind a proxy that terminates TLS — set it there.
REDIRECT_ENV = "OPENFACTORY_OIDC_REDIRECT_URL"
#: The scopes the login asks for. `openid` is mandatory and re-added if dropped.
SCOPES_ENV = "OPENFACTORY_OIDC_SCOPES"
#: Which claim is the person's id — the one `project.admins` and `product.admins` will spell.
#: `email` by default because it is the one a person can read in an allowlist; `sub` is stable
#: but opaque on most providers, and an allowlist of opaque ids is one nobody can audit.
ID_CLAIM_ENV = "OPENFACTORY_OIDC_ID_CLAIM"
#: Which claim carries the provider's groups (`groups` on Entra, Okta and Keycloak by default;
#: Google emits none).
GROUPS_CLAIM_ENV = "OPENFACTORY_OIDC_GROUPS_CLAIM"
#: `<provider group>=<platform group>` rows, comma-separated. A provider group named here becomes
#: the platform's word for it — `product` scopes its holder to the product surface (#98) — and a
#: group NOT named here passes through unchanged, so a project's allowlist may name it directly.
GROUPS_ENV = "OPENFACTORY_OIDC_GROUPS"

DEFAULT_SCOPES = "openid profile email"
DEFAULT_ID_CLAIM = "email"
DEFAULT_GROUPS_CLAIM = "groups"

#: The three doors the panel mounts for this row. Constants because the page, the gate's 401 and
#: the routes must agree on the spelling.
LOGIN_PATH = "/auth/login"
CALLBACK_PATH = "/auth/callback"
LOGOUT_PATH = "/auth/logout"

#: The name of the cookie that carries a login in flight (state, nonce, PKCE verifier) between
#: the redirect out and the callback in. Signed, short-lived, HttpOnly, and SameSite=Lax because
#: the callback ARRIVES as a cross-site navigation from the issuer — a Strict cookie is not sent
#: on one, and a login would fail with "no flight" on every provider.
FLIGHT_COOKIE = "openfactory_login"
#: The cookie the panel already reads (`api/app.py::_panel_gate`, the SSE and the socket).
TOKEN_COOKIE = "openfactory_token"

#: Asymmetric only — see the module docstring for what accepting HS256 would mean.
ALGORITHMS = ("RS256", "RS384", "RS512", "PS256", "PS384", "PS512", "ES256", "ES384", "ES512")
#: Clock skew tolerated on `exp`/`iat`/`nbf`. A minute is what the providers themselves use.
LEEWAY_SECONDS = 60
#: How long a login may take between leaving for the issuer and coming back.
FLIGHT_TTL_SECONDS = 600
#: Discovery and keys are re-read this often without being asked.
CACHE_TTL_SECONDS = 3600
#: …and at most this often when asked by an unknown `kid`.
REFETCH_FLOOR_SECONDS = 60
#: Every call to the issuer. Five seconds, because `identify` runs inside a request.
HTTP_TIMEOUT_SECONDS = 5.0


# ── configuration ───────────────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Settings:
    """What a deployment says about its provider. Read once per provider, never per call."""

    issuer: str = ""
    client_id: str = ""
    client_secret: str = ""
    redirect_url: str = ""
    scopes: str = DEFAULT_SCOPES
    id_claim: str = DEFAULT_ID_CLAIM
    groups_claim: str = DEFAULT_GROUPS_CLAIM
    group_map: dict[str, str] = field(default_factory=dict)

    @classmethod
    def from_env(cls, env: dict[str, str]) -> Settings:
        def get(name: str, default: str = "") -> str:
            return str(env.get(name, "") or "").strip() or default

        scopes = get(SCOPES_ENV, DEFAULT_SCOPES).split()
        if "openid" not in scopes:
            scopes.insert(0, "openid")
        return cls(
            issuer=get(ISSUER_ENV).rstrip("/"),
            client_id=get(CLIENT_ID_ENV),
            client_secret=get(CLIENT_SECRET_ENV),
            redirect_url=get(REDIRECT_ENV),
            scopes=" ".join(scopes),
            id_claim=get(ID_CLAIM_ENV, DEFAULT_ID_CLAIM),
            groups_claim=get(GROUPS_CLAIM_ENV, DEFAULT_GROUPS_CLAIM),
            group_map=_group_map(get(GROUPS_ENV)),
        )

    def misconfiguration(self) -> str:
        """One sentence naming what is missing or wrong, or "" when the row can run.

        Refused at STARTUP by the registry, not at the first request: the failure mode of this
        axis is letting the wrong person in, and a provider that cannot verify anything must not
        be one the gate consults and reads "None" from as if it had."""
        pairs = ((ISSUER_ENV, self.issuer), (CLIENT_ID_ENV, self.client_id))
        missing = [name for name, value in pairs if not value]
        if missing:
            return (f"OPENFACTORY_IDENTITY={KIND} needs {' and '.join(missing)} set where the "
                    f"panel runs — the issuer URL and the client id the provider issued for "
                    f"this deployment")
        if not (self.issuer.startswith("https://") or _is_loopback(self.issuer)):
            return (f"{ISSUER_ENV} must be an https:// URL ({self.issuer!r} is not): an issuer "
                    f"reached over plain http can be impersonated by anyone on the path, and its "
                    f"keys are what every login is verified against. http:// is accepted for "
                    f"localhost only, for a provider running on this machine")
        return ""


def _group_map(raw: str) -> dict[str, str]:
    """`a=b,c=d` → mapping. A malformed row is SKIPPED AND LOGGED, never guessed at: a row that
    half-parsed into the wrong platform group would scope somebody to an area by accident."""
    out: dict[str, str] = {}
    for row in str(raw or "").split(","):
        row = row.strip()
        if not row:
            continue
        left, sep, right = row.partition("=")
        if not sep or not left.strip() or not right.strip():
            log.warning("OPENFACTORY_IDENTITY_BAD_ROW ignoring a %s entry that is not "
                        "'<provider group>=<platform group>' — that group maps to nothing",
                        GROUPS_ENV)
            continue
        out[left.strip()] = right.strip()
    return out


def _is_loopback(url: str) -> bool:
    return url.startswith(("http://localhost", "http://127.0.0.1", "http://[::1]"))


def product_group_is_mapped(env: dict[str, str]) -> bool:
    """Whether this deployment's map hands anybody the product surface — the SSO answer to "is a
    product credential issued", which `onboarding/readiness.py` asks of the local token rows."""
    return PRODUCT_GROUP in Settings.from_env(env).group_map.values()


# ── the issuer, cached ──────────────────────────────────────────────────────────────────────────

def _http_json(url: str) -> dict:
    import httpx

    with httpx.Client(timeout=HTTP_TIMEOUT_SECONDS) as client:
        response = client.get(url, headers={"accept": "application/json"})
        response.raise_for_status()
        return response.json()


def _http_post_form(url: str, data: dict[str, str], auth: tuple[str, str] | None) -> dict:
    import httpx

    with httpx.Client(timeout=HTTP_TIMEOUT_SECONDS) as client:
        response = client.post(url, data=data, auth=auth, headers={"accept": "application/json"})
        # NOT `raise_for_status`: a refused exchange answers 400 with `error` and
        # `error_description` in the body, and those words are the ones a person can act on.
        return response.json()


class _Cache:
    """One entry per URL: the document, when it was fetched, and when it was last refetched on
    demand. Module-wide and locked, because the provider is rebuilt per request."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._docs: dict[str, tuple[dict, float]] = {}
        self._asked: dict[str, float] = {}

    def get(self, url: str, fetch, *, force: bool = False) -> dict | None:
        now = time.monotonic()
        with self._lock:
            held = self._docs.get(url)
            fresh = held is not None and now - held[1] < CACHE_TTL_SECONDS
            if held is not None and fresh and not force:
                return held[0]
            if force and now - self._asked.get(url, -REFETCH_FLOOR_SECONDS) < REFETCH_FLOOR_SECONDS:
                # asked for a refetch within the floor: answer from what is held, or nothing
                return held[0] if held is not None else None
            if force:
                self._asked[url] = now
        try:
            doc = fetch(url)
        except Exception as exc:  # noqa: BLE001 — the door closes, it does not fall
            log.warning("OPENFACTORY_OIDC_UNREACHABLE could not read %s (%s)", url, exc)
            return held[0] if held is not None else None
        if not isinstance(doc, dict):
            log.warning("OPENFACTORY_OIDC_UNREACHABLE %s did not answer a JSON object", url)
            return held[0] if held is not None else None
        with self._lock:
            self._docs[url] = (doc, time.monotonic())
        return doc

    def reset(self) -> None:
        with self._lock:
            self._docs.clear()
            self._asked.clear()


_CACHE = _Cache()


def reset_cache() -> None:
    """For a test, and for nothing else: the cache is the point in production."""
    _CACHE.reset()


#: The key a login flight is signed with when the deployment registered a PUBLIC client (no
#: secret to derive one from). Per process: a flight that starts on one panel process and lands
#: on another is refused as "not recognised" and the person logs in again — which a deployment
#: running several panel replicas behind one address avoids by setting a client secret.
_PROCESS_KEY = secrets.token_bytes(32)


# ── the provider ────────────────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Login:
    """What a finished callback hands the route: a credential and where to go, or why not."""

    id_token: str = ""
    subject: Subject | None = None
    expires_at: int = 0
    next_path: str = "/"
    refused: str = ""


class OidcIdentity:
    """The deployment's OpenID Connect provider — any of them, configured, never subclassed."""

    #: Where the panel sends a browser that has no credential (`api/app.py` reads it from the
    #: provider rather than assuming every provider has one — `local` does not).
    login_path = LOGIN_PATH

    def __init__(self, *, env: dict[str, str] | None = None, fetch=None, post=None) -> None:
        self.settings = Settings.from_env(dict(env if env is not None else os.environ))
        self._fetch = fetch or _http_json
        self._post = post or _http_post_form

    # ── the port ──────────────────────────────────────────────────────────────────────────────

    def misconfiguration(self) -> str:
        return self.settings.misconfiguration()

    def open_to_everyone(self) -> bool:
        """Never. A deployment that named a provider has closed its door, whatever else it set —
        the local row's "nothing configured means open" is that row's development posture and
        must not leak into this one through a missing method."""
        return False

    def identify(self, *, credential: str, via: str = "") -> Subject | None:
        try:
            token = str(credential or "").strip()
            if not token or self.settings.misconfiguration():
                return None
            claims = self._claims(token)
            if isinstance(claims, str):
                log.info("OPENFACTORY_OIDC_NOBODY a credential was refused: %s", claims)
                return None
            return self._subject(claims)
        except Exception as exc:  # noqa: BLE001 — an identity provider never takes the door down
            log.warning("the OIDC identity provider could not read a credential (%s)", exc)
            return None

    # ── the login flow, as pure steps the routes call ─────────────────────────────────────────

    def begin_login(self, *, callback_url: str, next_path: str) -> tuple[str, str] | str:
        """`(where to send the browser, the flight cookie's value)`, or a sentence when the
        issuer could not be read. PKCE (S256) on every login, a fresh `state` and `nonce` each."""
        doc = self._discovery()
        if isinstance(doc, str):
            return doc
        verifier = secrets.token_urlsafe(64)
        challenge = _b64url(hashlib.sha256(verifier.encode("ascii")).digest())
        flight = {"s": secrets.token_urlsafe(24), "n": secrets.token_urlsafe(24), "v": verifier,
                  "next": safe_next(next_path), "t": int(time.time())}
        query = {
            "response_type": "code",
            "client_id": self.settings.client_id,
            "redirect_uri": callback_url,
            "scope": self.settings.scopes,
            "state": flight["s"],
            "nonce": flight["n"],
            "code_challenge": challenge,
            "code_challenge_method": "S256",
        }
        return f"{doc['authorization_endpoint']}?{urlencode(query)}", self._sign(flight)

    def finish_login(self, *, callback_url: str, code: str, state: str, flight_cookie: str,
                     error: str = "", error_description: str = "") -> Login:
        """Exchange the code, verify the id_token against the flight, and say who it is."""
        if error:
            return Login(refused=f"the identity provider refused the login: {error}"
                                 f"{' — ' + error_description if error_description else ''}")
        flight = self._verify_flight(flight_cookie)
        if flight is None:
            return Login(refused="this login was not started here, or took longer than "
                                 f"{FLIGHT_TTL_SECONDS // 60} minutes — start it again from the "
                                 "panel")
        if not state or not hmac.compare_digest(state, flight["s"]):
            return Login(refused="the login's state does not match the one this browser started "
                                 "with — start it again from the panel")
        if not code:
            return Login(refused="the identity provider sent no authorization code back")
        doc = self._discovery()
        if isinstance(doc, str):
            return Login(refused=doc)
        data = {"grant_type": "authorization_code", "code": code, "redirect_uri": callback_url,
                "client_id": self.settings.client_id, "code_verifier": flight["v"]}
        auth = ((self.settings.client_id, self.settings.client_secret)
                if self.settings.client_secret else None)
        try:
            answer = self._post(doc["token_endpoint"], data, auth)
        except Exception as exc:  # noqa: BLE001
            return Login(refused="the identity provider's token endpoint could not be reached "
                                 f"({exc})")
        id_token = str((answer or {}).get("id_token") or "")
        if not id_token:
            got = answer or {}
            why = got.get("error_description") or got.get("error") or "no id_token"
            return Login(refused=f"the identity provider did not issue an id_token: {why}")
        claims = self._claims(id_token, nonce=flight["n"])
        if isinstance(claims, str):
            return Login(refused=f"the id_token the provider issued was refused: {claims}")
        subject = self._subject(claims)
        if subject is None:
            return Login(refused=f"the id_token carries no {self.settings.id_claim!r} claim and no "
                                 f"`sub`, so there is nobody to name — set {ID_CLAIM_ENV} to a "
                                 f"claim this provider emits")
        return Login(id_token=id_token, subject=subject, expires_at=int(claims["exp"]),
                     next_path=safe_next(flight.get("next", "/")))

    # ── verification ──────────────────────────────────────────────────────────────────────────

    def _discovery(self) -> dict | str:
        url = f"{self.settings.issuer}/.well-known/openid-configuration"
        doc = _CACHE.get(url, self._fetch)
        if doc is None:
            return f"the identity provider's discovery document could not be read at {url}"
        published = str(doc.get("issuer", "") or "").rstrip("/")
        if published != self.settings.issuer:
            # THE SPEC'S OWN CHECK, and the one that catches a tenant typo on Entra: the document
            # a wrong tenant serves names a different issuer, and every token it would verify
            # belongs to somebody else's directory.
            return (f"the discovery document at {url} names issuer {published!r}, not the "
                    f"configured {self.settings.issuer!r} — {ISSUER_ENV} must be spelled exactly "
                    f"as the provider spells it")
        for name in ("authorization_endpoint", "token_endpoint", "jwks_uri"):
            if not doc.get(name):
                return f"the discovery document at {url} has no {name}"
        return doc

    def _key_for(self, jwks_uri: str, header: dict):
        kid = header.get("kid")
        for force in (False, True):
            keys = _CACHE.get(jwks_uri, self._fetch, force=force)
            found = _pick_key((keys or {}).get("keys") or [], kid)
            if found is not None:
                return found
        return None

    def _claims(self, token: str, *, nonce: str | None = None) -> dict | str:
        try:
            header = jwt.get_unverified_header(token)
        except jwt.PyJWTError as exc:
            return f"not a JWT ({exc})"
        alg = str(header.get("alg", "") or "")
        if alg not in ALGORITHMS:
            return f"algorithm {alg!r} is not one this deployment verifies with a published key"
        doc = self._discovery()
        if isinstance(doc, str):
            return doc
        key = self._key_for(doc["jwks_uri"], header)
        if key is None:
            return f"no published key matches kid {header.get('kid')!r}"
        try:
            claims = jwt.decode(
                token, key=key, algorithms=[alg], audience=self.settings.client_id,
                issuer=self.settings.issuer, leeway=LEEWAY_SECONDS,
                options={"require": ["exp", "iat", "sub"]},
            )
        except jwt.PyJWTError as exc:
            return f"{type(exc).__name__}: {exc}"
        if nonce is not None and not hmac.compare_digest(str(claims.get("nonce", "")), nonce):
            return "the nonce does not match the login this browser started"
        return claims

    def _subject(self, claims: dict) -> Subject | None:
        ident = str(claims.get(self.settings.id_claim) or claims.get("sub") or "").strip()
        if not ident:
            return None
        display = str(claims.get("name") or claims.get("preferred_username") or ident).strip()
        return Subject(id=ident, display=display or ident, via=KIND, groups=self._groups(claims))

    def _groups(self, claims: dict) -> tuple[str, ...]:
        raw = claims.get(self.settings.groups_claim)
        names = [raw] if isinstance(raw, str) else [str(g) for g in (raw or []) if g is not None]
        out: list[str] = []
        for name in names:
            mapped = self.settings.group_map.get(name, name)
            if mapped and mapped not in out:
                out.append(mapped)
        return tuple(out)

    # ── the flight cookie ─────────────────────────────────────────────────────────────────────

    def _flight_key(self) -> bytes:
        if self.settings.client_secret:
            return hmac.new(self.settings.client_secret.encode("utf-8"),
                            b"openfactory-login-flight", hashlib.sha256).digest()
        return _PROCESS_KEY

    def _sign(self, flight: dict) -> str:
        body = _b64url(json.dumps(flight, separators=(",", ":")).encode("utf-8"))
        mac = hmac.new(self._flight_key(), body.encode("ascii"), hashlib.sha256).hexdigest()
        return f"{body}.{mac}"

    def _verify_flight(self, cookie: str) -> dict | None:
        body, _, mac = str(cookie or "").partition(".")
        if not body or not mac:
            return None
        expected = hmac.new(self._flight_key(), body.encode("ascii"), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(mac, expected):
            return None
        try:
            flight = json.loads(_b64url_decode(body))
        except (ValueError, UnicodeDecodeError):
            return None
        if not isinstance(flight, dict) or not all(k in flight for k in ("s", "n", "v", "t")):
            return None
        if time.time() - float(flight["t"]) > FLIGHT_TTL_SECONDS:
            return None
        return flight


def safe_next(path: str) -> str:
    """Where to go after a login — a path on THIS origin, or the root. `//evil.example/` is a
    scheme-relative URL and `\\` is one on browsers that normalise it, so both are the root."""
    path = str(path or "").strip()
    scheme_like = ":" in path.split("?")[0]
    if not path.startswith("/") or path.startswith("//") or "\\" in path or scheme_like:
        return "/"
    return path


def _pick_key(keys: list, kid: str | None):
    """The verification key a token's header names, or the only one published when it names
    none (some providers sign with a single key and omit `kid`)."""
    candidates = [k for k in keys if isinstance(k, dict) and k.get("use", "sig") == "sig"]
    if kid is not None:
        candidates = [k for k in candidates if k.get("kid") == kid]
    elif len(candidates) != 1:
        return None
    for jwk in candidates:
        try:
            return jwt.PyJWK(jwk).key
        except jwt.PyJWTError as exc:
            log.warning("OPENFACTORY_OIDC_BAD_KEY a published key could not be read (%s)", exc)
    return None


def _b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _b64url_decode(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))
