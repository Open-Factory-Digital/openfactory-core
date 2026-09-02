"""#33 slice 1 (SSO is a row the core ships): every door the id_token passes through is a cut.

Each row removes ONE check — the algorithm allowlist, the audience, the issuer, the expiry, the
nonce, the state, the flight's signature and its age, the refetch floor, the discovery issuer,
the group map, the registry's refusal, the 401's hint, the page's redirect, the readiness
report's SSO arm — and the guard file must go red for each, or that door was never there.
"""

TEST = "tests/test_sso_is_a_row_the_core_ships.py"
OIDC = "openfactory/identity/oidc.py"
REGISTRY = "openfactory/identity/registry.py"
APP = "openfactory/api/app.py"
PANEL = "openfactory/api/panel.html"
READINESS = "openfactory/onboarding/readiness.py"

MUTATIONS = [
    # ── verification ──
    ("HS256 and `none` are no longer refused at the header — the issuer is asked about them",
     OIDC,
     "        if alg not in ALGORITHMS:\n",
     "        if alg not in ALGORITHMS and alg not in (\"HS256\", \"none\"):\n"),

    ("the audience is not checked — a token minted for the expenses app opens the panel", OIDC,
     '                options={"require": ["exp", "iat", "sub"]},\n',
     '                options={"require": ["exp", "iat", "sub"], "verify_aud": False},\n'),

    ("the issuer is not checked — anybody's directory will do", OIDC,
     "                issuer=self.settings.issuer, leeway=LEEWAY_SECONDS,\n",
     "                issuer=None, leeway=LEEWAY_SECONDS,\n"),

    ("expiry is tolerated for thirty years", OIDC,
     "leeway=LEEWAY_SECONDS,", "leeway=10 ** 9,"),

    ("the signature key is not looked up by kid — rotation never arrives", OIDC,
     "        for force in (False, True):\n",
     "        for force in (False,):\n"),

    ("an unknown kid refetches the keys on every request", OIDC,
     "            if force and now - self._asked.get(url, -REFETCH_FLOOR_SECONDS) "
     "< REFETCH_FLOOR_SECONDS:\n",
     "            if False:\n"),

    ("the discovery document may name any issuer it likes", OIDC,
     "        if published != self.settings.issuer:\n",
     "        if False:\n"),

    ("the person's id is the opaque `sub`, whatever the deployment asked for", OIDC,
     '        ident = str(claims.get(self.settings.id_claim) or claims.get("sub") or "").strip()\n',
     '        ident = str(claims.get("sub") or "").strip()\n'),

    ("the provider's groups are not mapped to the platform's", OIDC,
     "            mapped = self.settings.group_map.get(name, name)\n",
     "            mapped = name\n"),

    ("an SSO deployment is open to everyone", OIDC,
     "        return False\n\n    def identify",
     "        return True\n\n    def identify"),

    # ── the login flight ──
    ("the nonce is not compared — a token from another login is accepted", OIDC,
     '        if nonce is not None and not hmac.compare_digest(str(claims.get("nonce", "")), nonce):\n',
     "        if False:\n"),

    ("the state is not compared — any browser's callback lands on this one's flight", OIDC,
     '        if not state or not hmac.compare_digest(state, flight["s"]):\n',
     "        if not state:\n"),

    ("the flight cookie's signature is not checked", OIDC,
     "        if not hmac.compare_digest(mac, expected):\n            return None\n",
     "        if False:\n            return None\n"),

    ("a flight never expires", OIDC,
     '        if time.time() - float(flight["t"]) > FLIGHT_TTL_SECONDS:\n',
     "        if False:\n"),

    ("no PKCE challenge leaves with the login", OIDC,
     '            "code_challenge_method": "S256",\n', ""),

    ("the PKCE verifier is not sent with the code", OIDC,
     '                "client_id": self.settings.client_id, "code_verifier": flight["v"]}\n',
     '                "client_id": self.settings.client_id}\n'),

    ("`next` may leave the origin", OIDC,
     r'    if not path.startswith("/") or path.startswith("//") or "\\" in path or scheme_like:'
     "\n",
     '    if not path.startswith("/"):\n'),

    # ── the registry ──
    ("a row named but not configured is built anyway", REGISTRY,
     "    if why:\n        raise ValueError(why)\n",
     "    if why and False:\n        raise ValueError(why)\n"),

    ("the row is gone from the registry", REGISTRY,
     '    "oidc": _oidc,\n', ""),

    # ── the panel ──
    ("the 401 no longer names the login page", APP,
     '    return {"detail": "unauthorized", "login": login} if login else {"detail": "unauthorized"}\n',
     '    return {"detail": "unauthorized"}\n'),

    ("logout leaves the localStorage half behind", APP,
     "\"<script>try{localStorage.removeItem('openfactory_token')}catch(e){}\"",
     '"<script>"'),

    ("a misconfigured row answers 'no login page' instead of naming the variable", APP,
     '    except (ValueError, TypeError) as exc:\n'
     '        return PlainTextResponse(f"login unavailable: {exc}", status_code=503)\n',
     "    except (ValueError, TypeError):\n        pass\n"),

    ("the page prompts for a token instead of going to the login", PANEL,
     'if(d&&d.login){localStorage.removeItem("openfactory_token");',
     'if(false){localStorage.removeItem("openfactory_token");'),

    # ── the readiness report ──
    ("the readiness report asks the token rows of an SSO deployment", READINESS,
     "    has_product = (oidc.product_group_is_mapped(env) if sso\n",
     "    has_product = (False if sso\n"),

    ("an SSO deployment's door is reported open", READINESS,
     "    door_is_closed = sso or has_product or _set(PEOPLE_ENV, SHARED_ENV)\n",
     "    door_is_closed = has_product or _set(PEOPLE_ENV, SHARED_ENV)\n"),
]
