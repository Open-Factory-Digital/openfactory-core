"""SSO is a row the core ships, not a socket somebody else fills (#33, slice 1).

`registry.py` said OIDC was an add-on registered as `identity.oidc`; `docs/configuration.md` said
the same; nothing anywhere implemented it. "Ready for SSO" meant there was somewhere to plug one
in, not that one plugged in — and a platform sold to enterprises must log in through the buyer's
own provider without anybody installing anything, the way it already speaks GitHub and Azure
DevOps. OIDC is a standard, so it is a built-in row beside `local`; what stays outside the core is
each deployment's configuration.

THE ID TOKEN IS THE CREDENTIAL. The port says `identify` receives a bearer token or a signed
assertion; an OpenID `id_token` is the second. So the gate, the SSE cookie and the socket stay
what they are, and what the login flow adds is a way to put an id_token where the shared password
used to be. Each check below is a door on its own — signature, issuer, audience, expiry, nonce,
state, the flight's signature and age — and each has a mutation row that removes it.
"""

from __future__ import annotations

import base64
import collections
import hashlib
import hmac
import json
import time
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient

from openfactory.identity import oidc
from openfactory.identity.base import IdentityProvider
from openfactory.identity.oidc import OidcIdentity
from openfactory.identity.registry import build_identity

ROOT = Path(__file__).resolve().parent.parent
ISSUER = "https://issuer.example/realms/acme"
CLIENT = "openfactory-panel"


class Issuer:
    """A provider in memory: key pairs, a discovery document, a JWKS, a token endpoint — and a
    count of every read, because "fetched once" is one of the properties under test."""

    def __init__(self, issuer: str = ISSUER) -> None:
        self.issuer = issuer
        self.published_issuer = issuer
        self.keys: dict[str, rsa.RSAPrivateKey] = {}
        self.current = ""
        self.rotate("k1")
        self.fetched: collections.Counter[str] = collections.Counter()
        self.posted: list[tuple[str, dict, tuple | None]] = []
        self.answer: dict = {}

    def rotate(self, kid: str) -> None:
        self.keys[kid] = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        self.current = kid

    def jwks(self) -> dict:
        keys = []
        for kid, key in self.keys.items():
            jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(key.public_key()))
            keys.append({**jwk, "kid": kid, "use": "sig", "alg": "RS256"})
        return {"keys": keys}

    def discovery(self) -> dict:
        return {"issuer": self.published_issuer,
                "authorization_endpoint": f"{self.issuer}/authorize",
                "token_endpoint": f"{self.issuer}/token",
                "jwks_uri": f"{self.issuer}/keys"}

    def fetch(self, url: str) -> dict:
        self.fetched[url] += 1
        if url == f"{self.issuer}/.well-known/openid-configuration":
            return self.discovery()
        if url == f"{self.issuer}/keys":
            return self.jwks()
        raise RuntimeError(f"unexpected read of {url}")

    def post(self, url: str, data: dict, auth: tuple | None) -> dict:
        self.posted.append((url, data, auth))
        return self.answer

    def token(self, *, kid: str = "", alg: str = "RS256", key=None, **claims) -> str:
        now = int(time.time())
        body = {"iss": self.issuer, "aud": CLIENT, "sub": "sub-7f3a", "email": "ana@acme.example",
                "name": "Ana Lima", "iat": now, "exp": now + 3600}
        body.update(claims)
        kid = kid or self.current
        return jwt.encode(body, key if key is not None else self.keys[kid], algorithm=alg,
                          headers={"kid": kid})


def provider(issuer: Issuer, **env) -> OidcIdentity:
    full = {oidc.ISSUER_ENV: issuer.issuer, oidc.CLIENT_ID_ENV: CLIENT, **env}
    return OidcIdentity(env=full, fetch=issuer.fetch, post=issuer.post)


@pytest.fixture(autouse=True)
def _fresh_cache():
    """The cache is module-wide on purpose (the provider is rebuilt per request); a test's issuer
    must not answer the next test's."""
    oidc.reset_cache()
    yield
    oidc.reset_cache()


@pytest.fixture
def issuer() -> Issuer:
    return Issuer()


@pytest.fixture
def sso(issuer, monkeypatch):
    """The panel as an SSO deployment: the row named, the coordinates set, the network replaced
    by the in-memory issuer. No client secret — a public client, the harder registration."""
    monkeypatch.setenv("OPENFACTORY_IDENTITY", "oidc")
    monkeypatch.setenv(oidc.ISSUER_ENV, issuer.issuer)
    monkeypatch.setenv(oidc.CLIENT_ID_ENV, CLIENT)
    for name in (oidc.CLIENT_SECRET_ENV, oidc.REDIRECT_ENV, oidc.GROUPS_ENV,
                 "OPENFACTORY_PANEL_TOKEN", "OPENFACTORY_PANEL_TOKENS"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(oidc, "_http_json", issuer.fetch)
    monkeypatch.setattr(oidc, "_http_post_form", issuer.post)
    return issuer


def flight_of(client: TestClient) -> dict:
    """What the browser is carrying between the redirect out and the callback in."""
    body = client.cookies[oidc.FLIGHT_COOKIE].split(".")[0]
    return json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)))


# ── the row ─────────────────────────────────────────────────────────────────────────────────────

def test_the_row_satisfies_the_port_by_SHAPE_and_is_built_from_config(issuer, monkeypatch):
    assert isinstance(provider(issuer), IdentityProvider)

    monkeypatch.setenv(oidc.ISSUER_ENV, issuer.issuer)
    monkeypatch.setenv(oidc.CLIENT_ID_ENV, CLIENT)
    assert isinstance(build_identity({"OPENFACTORY_IDENTITY": "oidc"}), OidcIdentity)


def test_a_row_named_but_not_configured_is_refused_at_startup_by_variable_name(monkeypatch):
    """Closed for a reason nothing said is the shape this platform refuses everywhere: a
    provider with no issuer would answer "nobody" to every credential, and the operator would
    read a wall of 401s instead of the one variable they forgot."""
    for name in (oidc.ISSUER_ENV, oidc.CLIENT_ID_ENV):
        monkeypatch.delenv(name, raising=False)

    with pytest.raises(ValueError, match=oidc.ISSUER_ENV) as e:
        build_identity({"OPENFACTORY_IDENTITY": "oidc"})
    assert oidc.CLIENT_ID_ENV in str(e.value)

    assert oidc.ISSUER_ENV in OidcIdentity(env={oidc.CLIENT_ID_ENV: CLIENT}).misconfiguration()
    assert "https://" in OidcIdentity(env={oidc.ISSUER_ENV: "http://issuer.example",
                                           oidc.CLIENT_ID_ENV: CLIENT}).misconfiguration()
    assert OidcIdentity(env={oidc.ISSUER_ENV: "http://localhost:8180/realms/dev",
                             oidc.CLIENT_ID_ENV: CLIENT}).misconfiguration() == "", \
        "a provider on this machine may be plain http"


def test_an_sso_deployment_is_never_open(issuer):
    """`local` opens the door when nothing is configured — its development posture. This row
    must not inherit it through a missing method: the gate reads `open_to_everyone` by getattr."""
    assert provider(issuer).open_to_everyone() is False


def test_the_conformance_suite_passes_the_row_configured_or_not(issuer):
    from openfactory.conformance.adapters import check_identity

    assert check_identity(OidcIdentity(env={})) == []
    assert check_identity(provider(issuer)) == []

    def unreachable(url):
        raise ConnectionError("no route to host")

    assert check_identity(OidcIdentity(env={oidc.ISSUER_ENV: ISSUER, oidc.CLIENT_ID_ENV: CLIENT},
                                       fetch=unreachable)) == []


# ── a credential is somebody only when every door is open ───────────────────────────────────────

def test_a_token_the_issuer_signed_for_this_client_is_that_person(issuer):
    who = provider(issuer).identify(credential=issuer.token(), via="panel")

    assert who is not None and who.known
    assert (who.id, who.display, who.via) == ("ana@acme.example", "Ana Lima", "oidc")


def test_the_id_is_the_readable_claim_and_a_deployment_may_name_another(issuer):
    """`sub` is stable and opaque on most providers; an allowlist of opaque ids is one nobody can
    audit. So `email` by default, the provider's `sub` when the claim is absent, and the claim
    the deployment names when it says so."""
    assert provider(issuer).identify(credential=issuer.token(email=None)).id == "sub-7f3a"

    named = provider(issuer, **{oidc.ID_CLAIM_ENV: "preferred_username"})
    who = named.identify(credential=issuer.token(preferred_username="ana.lima"))
    assert who.id == "ana.lima"


def test_a_token_signed_by_somebody_else_is_nobody(issuer):
    stranger = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    forged = issuer.token(key=stranger)                       # right kid, wrong key

    assert provider(issuer).identify(credential=forged) is None


def test_an_expired_token_is_nobody(issuer):
    stale = issuer.token(exp=int(time.time()) - 2 * oidc.LEEWAY_SECONDS)

    assert provider(issuer).identify(credential=stale) is None


def test_a_token_for_another_client_is_nobody(issuer):
    """The same provider issues tokens for every application in the company. One minted for the
    expenses app must not open this panel."""
    assert provider(issuer).identify(credential=issuer.token(aud="expenses-app")) is None


def test_a_token_from_another_issuer_is_nobody(issuer):
    assert provider(issuer).identify(credential=issuer.token(iss="https://other.example")) is None


def test_a_symmetric_or_none_algorithm_is_refused_before_any_key_is_read(issuer):
    """The classic confusion: sign with HS256 using the issuer's PUBLIC key as the secret, and a
    verifier that accepts HS256 accepts the forgery. Refused at the header — the issuer is not
    even asked, which is the property the fetch count measures."""
    pem = issuer.keys["k1"].public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
    now = int(time.time())
    body = {"iss": issuer.issuer, "aud": CLIENT, "sub": "x", "iat": now, "exp": now + 60}

    def b64(raw: bytes) -> str:
        return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()

    # by hand, because PyJWT itself refuses to MINT this one — the attacker's tooling does not
    signing_input = (b64(json.dumps({"alg": "HS256", "typ": "JWT", "kid": "k1"}).encode()) + "."
                     + b64(json.dumps(body).encode()))
    forged_hs = signing_input + "." + b64(hmac.new(pem, signing_input.encode(), hashlib.sha256).digest())
    forged_none = (b64(json.dumps({"alg": "none", "typ": "JWT", "kid": "k1"}).encode()) + "."
                   + b64(json.dumps(body).encode()) + ".")

    p = provider(issuer)
    assert p.identify(credential=forged_hs) is None
    assert p.identify(credential=forged_none) is None
    assert sum(issuer.fetched.values()) == 0, "refused at the header, before discovery or keys"


def test_the_discovery_document_must_name_the_configured_issuer(issuer):
    """The spec's own check, and the one that catches a tenant typo on Entra: a wrong tenant's
    document names a different issuer, and every token it verifies is somebody else's directory."""
    issuer.published_issuer = "https://issuer.example/realms/other"

    assert provider(issuer).identify(credential=issuer.token()) is None


def test_garbage_and_an_unreachable_issuer_are_nobody_and_never_raise(issuer):
    p = provider(issuer)
    assert p.identify(credential="") is None
    assert p.identify(credential="not.a.jwt") is None
    assert p.identify(credential="x" * 5000) is None

    def unreachable(url):
        raise ConnectionError("no route to host")

    cold = OidcIdentity(env={oidc.ISSUER_ENV: issuer.issuer, oidc.CLIENT_ID_ENV: CLIENT},
                        fetch=unreachable)
    assert cold.identify(credential=issuer.token()) is None


# ── the issuer is read once, and rotation arrives without a restart ────────────────────────────

def test_a_rotated_key_is_fetched_once_and_an_unknown_kid_is_not_fetched_in_a_loop(issuer):
    p = provider(issuer)
    assert p.identify(credential=issuer.token()) is not None
    assert issuer.fetched[f"{issuer.issuer}/keys"] == 1

    for _ in range(5):                                          # a warm cache costs no reads
        p.identify(credential=issuer.token())
    assert issuer.fetched[f"{issuer.issuer}/keys"] == 1

    issuer.rotate("k2")                                          # rotation: one refetch, then served
    assert p.identify(credential=issuer.token(kid="k2")) is not None
    assert issuer.fetched[f"{issuer.issuer}/keys"] == 2

    reads = issuer.fetched[f"{issuer.issuer}/keys"]
    for _ in range(5):                                          # random kids: floored to one refetch
        assert p.identify(credential=issuer.token(kid="nope", key=issuer.keys["k2"])) is None
    assert issuer.fetched[f"{issuer.issuer}/keys"] == reads, \
        "an unknown kid within the floor is answered from the cache, not the network"


# ── groups: the provider's word, the platform's meaning ─────────────────────────────────────────

def test_the_providers_groups_are_mapped_to_the_platforms_and_the_rest_pass_through(issuer):
    """`OF-BA=product` makes a business analyst a product credential (#98) without a token row;
    `Everyone` is not the platform's business and passes through so a project's allowlist may
    name it. The map is the whole customisation — the code knows no vendor's group names."""
    p = provider(issuer, **{oidc.GROUPS_ENV: "OF-BA=product, OF-Ops=floor"})
    who = p.identify(credential=issuer.token(groups=["OF-BA", "Everyone", "OF-BA"]))

    assert who.groups == ("product", "Everyone")

    from openfactory.api.app import _scopes_of
    assert _scopes_of(who) == frozenset({"product"})

    unmapped = provider(issuer).identify(credential=issuer.token(groups=["Everyone"]))
    assert _scopes_of(unmapped) is None, "no platform group → unscoped, exactly as a panel token"
    assert provider(issuer).identify(credential=issuer.token(groups="OF-BA")).groups == ("OF-BA",)

    assert oidc.product_group_is_mapped({oidc.GROUPS_ENV: "OF-BA=product"})
    assert not oidc.product_group_is_mapped({oidc.GROUPS_ENV: "OF-BA=floor, broken"})


# ── the login flow ──────────────────────────────────────────────────────────────────────────────

def test_the_login_sends_the_browser_to_the_issuer_with_pkce_state_and_nonce(sso):
    from openfactory.api.app import app

    client = TestClient(app)
    r = client.get("/auth/login?next=/p/demo", follow_redirects=False)

    assert r.status_code == 302, r.text
    url = r.headers["location"]
    assert url.startswith(f"{ISSUER}/authorize?")
    q = parse_qs(urlparse(url).query)
    assert q["response_type"] == ["code"] and q["client_id"] == [CLIENT]
    assert q["code_challenge_method"] == ["S256"] and q["code_challenge"][0]
    assert "openid" in q["scope"][0].split()
    assert q["redirect_uri"] == ["http://testserver/auth/callback"], "derived from the request"
    flight = flight_of(client)
    assert q["state"] == [flight["s"]] and q["nonce"] == [flight["n"]]
    assert flight["next"] == "/p/demo" and flight["v"]


def test_the_callback_exchanges_the_code_and_hands_the_browser_the_id_token(sso):
    """The whole flow, end to end, with the only network the panel makes replaced by the issuer
    in memory: leave, come back with a code, exchange it with the PKCE verifier, verify the
    id_token against the nonce this browser started with, land on `next` holding it."""
    from openfactory.api.app import app

    client = TestClient(app)
    client.get("/auth/login?next=/p/demo", follow_redirects=False)
    flight = flight_of(client)
    sso.answer = {"id_token": sso.token(nonce=flight["n"])}

    r = client.get(f"/auth/callback?code=c0de&state={flight['s']}", follow_redirects=False)

    assert r.status_code == 302, r.text
    assert r.headers["location"] == "/p/demo"
    assert client.cookies[oidc.TOKEN_COOKIE] == sso.answer["id_token"]
    assert oidc.FLIGHT_COOKIE not in client.cookies, "the flight is over"

    url, data, auth = sso.posted[-1]
    assert url == f"{ISSUER}/token" and auth is None, "a public client: PKCE, no secret"
    assert data["grant_type"] == "authorization_code" and data["code"] == "c0de"
    assert data["code_verifier"] == flight["v"]
    assert data["redirect_uri"] == "http://testserver/auth/callback"

    # …and the credential it left is the one every route already understands
    me = client.get("/api/whoami",
                    headers={"authorization": f"Bearer {sso.answer['id_token']}"}).json()
    assert me["known"] and me["id"] == "ana@acme.example" and me["logout"] == "/auth/logout"


def test_a_confidential_client_sends_its_secret_the_way_the_spec_requires(sso, monkeypatch):
    monkeypatch.setenv(oidc.CLIENT_SECRET_ENV, "s3cret")
    monkeypatch.setenv(oidc.REDIRECT_ENV, "https://panel.acme.example/auth/callback")
    from openfactory.api.app import app

    client = TestClient(app)
    r = client.get("/auth/login", follow_redirects=False)
    assert parse_qs(urlparse(r.headers["location"]).query)["redirect_uri"] == \
        ["https://panel.acme.example/auth/callback"], "configured wins over derived"
    flight = flight_of(client)
    sso.answer = {"id_token": sso.token(nonce=flight["n"])}

    r = client.get(f"/auth/callback?code=c0de&state={flight['s']}", follow_redirects=False)

    assert r.status_code == 302, r.text
    _, data, auth = sso.posted[-1]
    assert auth == (CLIENT, "s3cret"), "client_secret_basic — the method every provider must support"
    assert data["redirect_uri"] == "https://panel.acme.example/auth/callback"


def test_a_callback_whose_state_is_not_this_browsers_is_refused(sso):
    from openfactory.api.app import app

    client = TestClient(app)
    client.get("/auth/login", follow_redirects=False)
    flight = flight_of(client)
    sso.answer = {"id_token": sso.token(nonce=flight["n"])}

    r = client.get("/auth/callback?code=c0de&state=somebody-elses", follow_redirects=False)

    assert r.status_code == 401 and "state" in r.text
    assert oidc.TOKEN_COOKIE not in client.cookies and not sso.posted, "no exchange was attempted"


def test_a_callback_with_a_forged_or_stale_flight_is_refused(sso, monkeypatch):
    from openfactory.api.app import app

    client = TestClient(app)
    client.get("/auth/login", follow_redirects=False)
    flight = flight_of(client)
    body, mac = client.cookies[oidc.FLIGHT_COOKIE].split(".")
    client.cookies.set(oidc.FLIGHT_COOKIE, f"{body}.{'0' * len(mac)}", path="/auth/")

    r = client.get(f"/auth/callback?code=c0de&state={flight['s']}", follow_redirects=False)
    assert r.status_code == 401 and "not started here" in r.text

    # a real flight, signed with the deployment's own key, that took too long
    monkeypatch.setenv(oidc.CLIENT_SECRET_ENV, "s3cret")
    old = dict(flight, t=int(time.time()) - oidc.FLIGHT_TTL_SECONDS - 5)
    client.cookies.set(oidc.FLIGHT_COOKIE, OidcIdentity()._sign(old), path="/auth/")

    r = client.get(f"/auth/callback?code=c0de&state={flight['s']}", follow_redirects=False)
    assert r.status_code == 401 and "minutes" in r.text
    assert not sso.posted


def test_a_callback_whose_token_carries_another_nonce_is_refused(sso):
    """A code exchanged correctly for a token minted for a DIFFERENT login is a replay, and the
    nonce is the only thing that ties the token to this browser's flight."""
    from openfactory.api.app import app

    client = TestClient(app)
    client.get("/auth/login", follow_redirects=False)
    flight = flight_of(client)
    sso.answer = {"id_token": sso.token(nonce="another-browsers")}

    r = client.get(f"/auth/callback?code=c0de&state={flight['s']}", follow_redirects=False)

    assert r.status_code == 401 and "nonce" in r.text
    assert oidc.TOKEN_COOKIE not in client.cookies


def test_a_provider_that_refuses_the_login_is_quoted_not_paraphrased(sso):
    from openfactory.api.app import app

    client = TestClient(app)
    client.get("/auth/login", follow_redirects=False)

    r = client.get("/auth/callback?error=access_denied&error_description=not+assigned",
                   follow_redirects=False)

    assert r.status_code == 401 and "access_denied" in r.text and "not assigned" in r.text


def test_next_cannot_leave_this_origin():
    for evil in ("//evil.example/", "https://evil.example", "/\\evil.example", "javascript:x", ""):
        assert oidc.safe_next(evil) == "/", evil
    assert oidc.safe_next("/p/demo?x=1") == "/p/demo?x=1"


def test_a_token_deployment_has_no_login_page_and_says_so(monkeypatch):
    monkeypatch.delenv("OPENFACTORY_IDENTITY", raising=False)
    from openfactory.api.app import app

    r = TestClient(app).get("/auth/login", follow_redirects=False)

    assert r.status_code == 404
    assert "local" in r.text and "no login page" in r.text and "OPENFACTORY_IDENTITY=oidc" in r.text


def test_the_401_names_the_login_page_so_the_page_can_go_there(sso, monkeypatch):
    from openfactory.api.app import app

    r = TestClient(app).get("/api/projects")
    assert r.status_code == 401
    assert r.json()["login"] == "/auth/login"

    # …and on a token deployment the body is exactly what it was: no door is drawn
    monkeypatch.delenv("OPENFACTORY_IDENTITY", raising=False)
    monkeypatch.setenv("OPENFACTORY_PANEL_TOKEN", "s3cret")
    r = TestClient(app).get("/api/projects")
    assert r.status_code == 401 and "login" not in r.json()
    assert TestClient(app).get("/api/whoami", headers={"authorization": "Bearer s3cret"}) \
        .json()["logout"] is None


def test_the_page_goes_to_the_login_instead_of_prompting_and_adopts_the_cookie():
    """The page's half of the flow, pinned by text: a 401 that names a login page is followed,
    not answered with a prompt for a token no such deployment issues; and at boot the cookie the
    server set wins over a localStorage copy, so the credential a login left reaches every fetch."""
    html = (ROOT / "openfactory/api/panel.html").read_text()

    assert 'if(d&&d.login){localStorage.removeItem("openfactory_token");' in html
    assert 'location.assign(d.login+"?next="' in html
    assert 'cookieToken()||localStorage.getItem("openfactory_token")' in html


def test_logout_clears_both_halves_of_the_credential(sso):
    from openfactory.api.app import app

    r = TestClient(app).get("/auth/logout", follow_redirects=False)

    assert r.status_code == 200
    assert "localStorage.removeItem('openfactory_token')" in r.text
    gone = r.headers["set-cookie"]
    assert gone.startswith(f'{oidc.TOKEN_COOKIE}=""') and "Max-Age=0" in gone, gone


def test_a_misconfigured_row_closes_the_door_naming_the_variable(monkeypatch, caplog):
    monkeypatch.setenv("OPENFACTORY_IDENTITY", "oidc")
    monkeypatch.delenv(oidc.ISSUER_ENV, raising=False)
    monkeypatch.delenv(oidc.CLIENT_ID_ENV, raising=False)
    from openfactory.api.app import app

    with caplog.at_level("ERROR", logger="openfactory.panel"):
        r = TestClient(app).get("/api/projects")

    assert r.status_code == 503
    assert oidc.ISSUER_ENV in caplog.text, "the log names the variable, not 'does not exist'"
    login = TestClient(app).get("/auth/login")
    assert login.status_code == 503 and oidc.ISSUER_ENV in login.text, \
        "the login page says which variable, not 'no login page'"


# ── the readiness report reads the row's own map ───────────────────────────────────────────────

def test_the_readiness_report_asks_the_sso_map_not_the_token_rows():
    """`product_role` decided "is a product credential issued" from the token variables. On an
    SSO deployment there are none: the door is closed by definition, and the credential is a
    provider group mapped to `product` — asked of the module that reads the map."""
    from openfactory.onboarding import readiness as R

    def probes(env):
        return SimpleNamespace(project_name="demo", product_enabled=lambda: True,
                               product_admins=lambda: ["ana@acme.example"], environ=lambda: env)

    sso_env = {"OPENFACTORY_IDENTITY": "oidc", oidc.ISSUER_ENV: ISSUER, oidc.CLIENT_ID_ENV: CLIENT}

    f, _ = R._product_role(probes({**sso_env, oidc.GROUPS_ENV: "OF-BA=product"}), on="worker")
    assert f.ok, f.message
    assert "a product credential is issued" in f.message

    f, _ = R._product_role(probes(sso_env), on="worker")
    assert not f.ok
    assert "no product credential is issued" in f.message
    assert oidc.GROUPS_ENV in f.remedy and "OPENFACTORY_PRODUCT_TOKENS" not in f.remedy, \
        "the remedy is the SSO one — a token row is not read on this deployment"


# ── the operator's documents name what the row reads ───────────────────────────────────────────

def test_the_operators_documents_name_every_variable_the_row_reads():
    docs = (ROOT / "docs/configuration.md").read_text()
    reference = (ROOT / "docs/reference/configuration.md").read_text()
    example = (ROOT / ".env.compose.example").read_text()

    for name in (oidc.ISSUER_ENV, oidc.CLIENT_ID_ENV, oidc.CLIENT_SECRET_ENV, oidc.REDIRECT_ENV,
                 oidc.GROUPS_ENV):
        assert name in docs and name in reference and name in example, name
    for name in (oidc.ID_CLAIM_ENV, oidc.GROUPS_CLAIM_ENV, oidc.SCOPES_ENV):
        assert name in docs and name in reference, name
    assert "OPENFACTORY_IDENTITY=oidc" in docs and "OPENFACTORY_IDENTITY=oidc" in example
    assert "OIDC/SAML/EntraID are add-ons" not in docs, "the sentence that was false for a week"
