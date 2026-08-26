"""`TF401019` is an Azure DevOps error code, not an HTTP status — and it broke the doctor.

The forge probe decided "the credential was refused" with `"401" in str(exc)`. Azure DevOps answers
a missing pull request with

    GET git/pullrequests/1 → 404 Not Found: TF401019: The Git repository with name or identifier
    21200617-… does not exist or you do not have permissions for the operation you are attempting.

so a HEALTHY Azure deployment was told its forge had refused the credential, with a remedy about
granting a GitHub App permissions it neither has nor needs. Found by running `sdlc doctor` against a
real client project that was, in fact, fine — the check that exists to reassure somebody was the
only thing failing.

THIRD TIME THIS SHAPE HAS BILLED THIS CODEBASE. `_RATE_RE` matched `429` inside generated session
ids and parked healthy jobs as rate-limited across three adapters. A substring guard tripped on the
prose explaining its own rule. Now an error code. **A bare number inside a message is not a
status** — and the reason it keeps happening is that the naive check works perfectly until a vendor
whose diagnostics carry digits shows up.
"""

from __future__ import annotations

import pytest

from openfactory.contracts.project import Project, ProviderRef

PROJECT = Project(
    name="fx-dsk", repo_path="/tmp/fx-dsk",
    tracker=ProviderRef(kind="azure_devops", repo="Deskline",
                        options={"organization": "acme-ai"}),
    forge=ProviderRef(kind="azure_devops", repo="fx-dsk-flows",
                      options={"organization": "acme-ai"}),
)

#: Verbatim from the live run (acme-ai/Deskline, 2026-08-06).
REAL_404 = (
    "GET git/pullrequests/1 → 404 Not Found: TF401019: The Git repository with name or identifier "
    "21200617-5ca5-4819-a6e0-68bbec2c964c does not exist or you do not have permissions for the "
    "operation you are attempting."
)


def _probe(monkeypatch, message: str):
    """The REAL forge probe, with only the network replaced.

    A credential is SET, deliberately: the probe refuses by PRESENCE before it ever asks the
    vendor (pre-pilot review, 2026-08-09), and this file's whole subject is how the vendor's
    ANSWER is read — which only happens once a credential exists to ask with."""
    import openfactory.adapters.forge.registry as forge_registry
    from openfactory.doctor import probes_for

    class _Forge:
        def pr_status(self, *, pr):
            raise RuntimeError(message)

    monkeypatch.setenv("OPENFACTORY_BOT_TOKEN", "tok-vendor-code-test")
    monkeypatch.setattr(forge_registry, "build_forge", lambda *a, **k: _Forge())
    return probes_for(PROJECT).forge_reachable()


def test_a_vendor_error_code_that_contains_401_is_not_a_refusal(monkeypatch):
    ok, detail = _probe(monkeypatch, REAL_404)
    assert ok, f"a vendor error code was read as a refused credential: {detail}"


@pytest.mark.parametrize("message", [
    "GET git/pullrequests/1 → 401 Unauthorized: bad or expired token",
    "GET git/pullrequests/1 → 403 Forbidden: the token lacks Code (read)",
    "repository not accessible with the configured credentials",
])
def test_a_REAL_refusal_is_still_caught(monkeypatch, message):
    """The positive twin, and it matters more than the fix.

    A change that stopped noticing 401 would be worse than the bug it cured: this probe exists to
    catch a credential the deployment cannot use, and a silent pass there is a client discovering
    it on their first ticket instead of on `doctor`.
    """
    ok, _ = _probe(monkeypatch, message)
    assert not ok, f"a genuine refusal was reported as healthy: {message!r}"


def test_a_404_means_we_were_ALLOWED_to_ask(monkeypatch):
    """The probe's actual question is permission, not existence. "There is no PR #1 in this
    project" is a fine answer to it — every fresh client repository gives that answer."""
    ok, _ = _probe(monkeypatch, "GET git/pullrequests/1 → 404 Not Found: no such pull request")
    assert ok
