"""#162 (factory.py): a credential only goes to the host that issued it.

The reverses are the ones that matter here, because "no token appears" is also true of a URL
nobody authenticated — a clone that fails for everybody would pass a one-directional guard.
"""

TEST = "tests/test_a_credential_only_goes_to_its_own_host.py"
FACTORY = "openfactory/factory.py"
BASE = "openfactory/adapters/forge/base.py"
GH = "openfactory/adapters/forge/github.py"
ADO = "openfactory/adapters/forge/azure_devops.py"
CONF = "tests/conftest.py"

MUTATIONS = [
    # ── the weld comes back ─────────────────────────────────────────────────────────────────────
    ("the neutral path injects one vendor's spelling into any https URL again", FACTORY,
     "        return build_forge(project, token=token).authenticated_url(url)",
     '        return url.replace("https://", f"https://x-access-token:{token}@", 1)'),

    ("a forge nobody implements falls back to injecting anyway", FACTORY,
     '        log.warning("no forge to authenticate %s with for %s (%s) — cloning without a '
     'credential",\n                    url.split("://", 1)[-1].split("/")[0], '
     'getattr(project, "name", "?"),\n                    str(exc)[:120])\n        return url',
     '        return url.replace("https://", f"https://x-access-token:{token}@", 1)'),

    ("…and the reverse: it refuses in silence, so the clone fails for no stated reason", FACTORY,
     '        log.warning("no forge to authenticate %s with for %s (%s) — cloning without a '
     'credential",\n                    url.split("://", 1)[-1].split("/")[0], '
     'getattr(project, "name", "?"),\n                    str(exc)[:120])\n', ""),

    # ── whose host is it ────────────────────────────────────────────────────────────────────────
    ("GitHub stops checking the host — the App token goes wherever the URL points", GH,
     "        if not token or carries_credentials(url) or host_of(url) != self._host():",
     "        if not token or carries_credentials(url):"),

    ("…and the reverse: it never matches, so no GitHub clone is ever authenticated", GH,
     "        if not token or carries_credentials(url) or host_of(url) != self._host():",
     "        if not token or carries_credentials(url) or True:"),

    ("an Enterprise deployment's host stops being read — github.com again", GH,
     '        return (os.environ.get("GH_HOST") or os.environ.get("GITHUB_HOST")\n'
     '                or "github.com").strip().lower()',
     '        return "github.com"'),

    ("Azure stops checking the host", ADO,
     '        if not token or carries_credentials(url) or host_of(url) != "dev.azure.com":',
     "        if not token or carries_credentials(url):"),

    ("…and the reverse: an Azure URL is never authenticated at all", ADO,
     '        if not token or carries_credentials(url) or host_of(url) != "dev.azure.com":',
     "        if True:"),

    ("a URL that already carries its own credential is rewritten", BASE,
     "    return bool(urllib.parse.urlsplit(url).username or urllib.parse.urlsplit(url).password)",
     "    return False"),

    ("an ssh remote is treated as an https one", BASE,
     '    if not url.lower().startswith("https://"):\n        return ""',
     "    pass"),

    # ── whose credential is it ──────────────────────────────────────────────────────────────────
    ("the CALLER's token wins over the adapter's — the wrong axis's secret, wrapped", ADO,
     '        token = self.token\n        if not token or carries_credentials(url) or '
     'host_of(url) != "dev.azure.com":',
     '        token = self.token or "ghs_the_callers_github_token"\n'
     '        if not token or carries_credentials(url) or host_of(url) != "dev.azure.com":'),

    # ── the deployment's mint, by axis ──────────────────────────────────────────────────────────
    ("the repo fetch mints a GitHub credential for any vendor again", FACTORY,
     "        token = forge_token_for(project) or deployment_forge_token(project)",
     "        token = forge_token_for(project) or github_app_token_from_env()"),

    ("the promotion runner does too", FACTORY,
     "    app_tok = deployment_forge_token(project)  # observer takes a static token (short op)",
     "    app_tok = github_app_token_from_env()  # observer takes a static token (short op)"),

    # ── the stripper the guard rests on ─────────────────────────────────────────────────────────
    ("the prose stripper eats the CODE as well as the docstring", CONF,
     '    kept = [("" if n in drop else re.sub(r"(^|\\s)#.*$", "", line))\n'
     "            for n, line in enumerate(source.splitlines(), start=1)]",
     '    kept = ["" for _ in source.splitlines()]'),

    ("…and the reverse: it stops stripping docstrings, so the guard reads its own explanation",
     CONF, "            drop.update(range(first.lineno, (first.end_lineno or first.lineno) + 1))",
     "            pass"),
]
