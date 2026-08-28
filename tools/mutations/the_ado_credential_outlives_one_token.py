"""The Azure DevOps credential, on both deployments it has to serve at once.

A hosted factory runs on a SERVICE USER's PAT — long-lived, dependent on nobody being logged in,
in a container with no Azure CLI. A laptop inside an enterprise tenant cannot create a PAT at all
and has only `az account get-access-token`, which lasts about an hour.

The defect this closes: `token_for` re-read `os.environ` at each use, which LOOKS like a refresh
and is not — a process's environment does not renew itself, so a worker started with a JWT re-read
the same expired one until somebody restarted it. Measured on a real Azure DevOps deployment.

THE FIRST TWO ROWS ARE THE PRODUCTION REGRESSION, not the original defect: a fallback that outranks
the PAT would prefer a human's identity to the service user's and would spawn a subprocess per call
in a container that has no `az` to spawn. That is a worse failure than the one being fixed, and it
is invisible to anyone testing on a laptop where both credentials happen to work.

THE LAST TWO ARE THE SECOND MOUTH of the same defect, one level down: the shared client froze its
credential in `__init__`, and the TRACKER keeps one client for the life of the job — so the card is
moved to Done, hours later, on the token the job started with.
"""

TEST = "tests/test_the_ado_credential_outlives_one_token.py"

MUTATIONS = [
    # ── the hosted deployment must not change ───────────────────────────────────────────────────
    ("the mint outranks the PAT, so a service user's credential is ignored in favour of whichever "
     "human happens to be logged in — and every call spawns a subprocess",
     "openfactory/adapters/azure_devops.py",
     "    pat = (os.environ.get(name) or \"\").strip()\n    if pat:\n        return pat\n    return az_token()",
     "    pat = (os.environ.get(name) or \"\").strip()\n    return az_token() or pat"),

    ("no fallback at all — the defect exactly as it shipped: the variable is re-read forever and "
     "a worker that started with a JWT needs restarting once an hour",
     "openfactory/adapters/azure_devops.py",
     "    if pat:\n        return pat\n    return az_token()",
     "    if pat:\n        return pat\n    return None"),

    # ── the laptop: a job that outlives one token ───────────────────────────────────────────────
    ("no refresh margin, so a token with seconds left is handed to a request whose round trip is "
     "bounded at 60 — a 401 on the last station of a job that had done all its work",
     "openfactory/adapters/azure_devops.py",
     "        if cached is not None and time.time() < cached[1] - _AZ_REFRESH_MARGIN_SECONDS:",
     "        if cached is not None and time.time() < cached[1]:"),

    ("the margin is zero by another route — same failure, spelled in the constant",
     "openfactory/adapters/azure_devops.py",
     "_AZ_REFRESH_MARGIN_SECONDS = 300",
     "_AZ_REFRESH_MARGIN_SECONDS = 0"),

    ("nothing is ever cached, so every HTTP call the platform makes spawns `az` — and "
     "`push_remote()` alone is called at ten sites in the orchestrator",
     "openfactory/adapters/azure_devops.py",
     "            _az_cached = minted\n            return minted[0]",
     "            return minted[0]"),

    ("a token is cached once and never refreshed, which is the original defect with an extra step",
     "openfactory/adapters/azure_devops.py",
     "        minted = _az_mint()\n        if minted is not None:",
     "        minted = None if cached is not None else _az_mint()\n        if minted is not None:"),

    ("a failed refresh evicts a credential still valid for fifty minutes, turning a laptop off the "
     "VPN for one minute into the mid-job auth failure this path exists to prevent",
     "openfactory/adapters/azure_devops.py",
     "        if cached is not None and time.time() < cached[1]:\n            return cached[0]\n        return None",
     "        return None"),

    ("a failed refresh hands back an EXPIRED token, so the 401 blames the credential instead of "
     "the refresh that failed",
     "openfactory/adapters/azure_devops.py",
     "        if cached is not None and time.time() < cached[1]:\n            return cached[0]\n        return None",
     "        if cached is not None:\n            return cached[0]\n        return None"),

    # ── what the CLI actually answers ───────────────────────────────────────────────────────────
    ("the expiry is read from `expiresOn` — LOCAL WALL TIME with no zone — so the token's life is "
     "off by the machine's UTC offset, and in the stale direction that is a dead credential "
     "handed out as live",
     "openfactory/adapters/azure_devops.py",
     '        expires = float(got.get("expires_on") or 0)',
     '        expires = float(got.get("expiresOn") or 0)'),

    ("a nonzero exit is read as success, so `az` printing an error to a machine that is not logged "
     "in yields an empty credential that reaches `_auth_header` and is sent as a real one",
     "openfactory/adapters/azure_devops.py",
     "    if done.returncode != 0:\n        log.debug(\"`az account get-access-token` exited %s\", done.returncode)\n        return None",
     "    if done.returncode != 0:\n        log.debug(\"`az account get-access-token` exited %s\", done.returncode)"),

    ("a missing `az` binary raises out of a credential lookup — which is the NORMAL state of the "
     "deployed container, so a healthy production worker dies on a stack trace",
     "openfactory/adapters/azure_devops.py",
     "    except (OSError, subprocess.SubprocessError):",
     "    except _NeverRaised:"),

    ("an answer with no expiry is trusted forever",
     "openfactory/adapters/azure_devops.py",
     "    return token, expires or (time.time() + 3600)",
     "    return token, expires or float(\"inf\")"),

    # ── the shared client every Azure axis reaches through ──────────────────────────────────────
    ("the client freezes its credential in `__init__` again — the tracker keeps one for the whole "
     "job, so the card is moved to Done on the token the job started with",
     "openfactory/adapters/azure_devops.py",
     "        return self._static_token or token_for(self._options)",
     "        return self._static_token or self._frozen_at_construction"),

    ("the caller's explicit token is discarded, so the forge's own per-use resolution is thrown "
     "away and an Azure adapter re-derives a credential the caller had already chosen",
     "openfactory/adapters/azure_devops.py",
     "        return self._static_token or token_for(self._options)",
     "        return token_for(self._options)"),
]
