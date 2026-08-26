"""The context repository is checked outside the product role (C-17).

ADR-0019 makes the context repository the product entity: it owns the board, the specification
and the list of source repositories. Both directions of the mapping already exist —
`ProductDocs.sources` in `.openfactory/product.yaml`, `Manifest.docs_repo` in each source repo — and
`resolve_product_link` already reconciles them with exactly the right discipline: a disagreement
turns the module OFF rather than redirecting it, because anyone with write access to a source repo
could otherwise point it at any repository at all.

**What was missing is who asks.** That verdict was reached only by the product role, at sweep time.
So a context repository that is misconfigured — not listed as a member, describing a different
product, unreadable — is discovered hours later by an agent going quiet, which is the silent stall
this platform exists to make impossible. `sdlc doctor` asks the same question at setup.

The four verdicts need four different people, and flattening them is why a misconfiguration
survives:

    off        nobody enabled it — not a problem, and must not read as one
    config     enabled but unusable — the operator's
    conflict   the two declarations disagree — whoever edited one of the two files
    ok         they agree
"""

from __future__ import annotations

import pytest

from openfactory.doctor import Finding, diagnose


def _findings(report) -> dict[str, Finding]:
    return {f.check: f for f in report.findings}


def _link(**kw):
    from openfactory.product.config import ProductLink

    return ProductLink(**kw)


def test_the_check_runs(healthy):
    assert "product_link" in _findings(diagnose(healthy))


def test_a_project_with_no_product_module_is_not_a_problem(healthy):
    """`off` means nobody enabled it. Reporting that as a failure would train people to ignore
    doctor — most projects have no product module and are entirely correct."""
    f = _findings(diagnose(healthy))["product_link"]
    assert f.ok


def test_a_healthy_link_says_which_repository_it_agreed_on(product_ok):
    f = _findings(diagnose(product_ok))["product_link"]
    assert f.ok and "acme/docs" in f.message


def test_a_conflict_is_reported_with_its_reason(product_conflict):
    """The reason is the whole value. `resolve_product_link` already writes a precise one — doctor
    must carry it through rather than replace it with 'product link problem'."""
    f = _findings(diagnose(product_conflict))["product_link"]
    assert not f.ok
    assert "not listed in `sources:`" in f.message


def test_a_conflict_names_whose_problem_it_is(product_conflict):
    """`conflict` and `config` need different people. A remedy that says 'check the configuration'
    to both is a remedy for neither."""
    f = _findings(diagnose(product_conflict))["product_link"]
    assert "product.yaml" in f.remedy or "sources" in f.remedy


def test_an_unusable_config_is_reported_separately(product_config_broken):
    f = _findings(diagnose(product_config_broken))["product_link"]
    assert not f.ok and "docs repo" in f.message.lower()


def test_a_warning_is_surfaced_without_failing(product_warned):
    """The module runs, and something is still worth fixing. Swallowing it would lose the one
    signal that says a check could not be made."""
    f = _findings(diagnose(product_warned))["product_link"]
    assert f.ok
    assert "membership could not be checked" in f.message


def test_a_probe_that_raises_is_a_finding_not_a_traceback(product_explodes):
    report = diagnose(product_explodes)
    assert not _findings(report)["product_link"].ok


# ── fixtures ────────────────────────────────────────────────────────────────────────────────────

from openfactory.doctor import Probes  # noqa: E402


def _manifest_obj():
    """A real manifest that satisfies the floor — this file is about the product link, and a stub
    that failed the manifest or floor check would fail every fixture here for an unrelated reason
    and hide the thing under test."""
    from openfactory.contracts import Manifest

    return Manifest(version=1, base_branch="main",
                    validate={"test": "pytest -q",
                              "security": {"command": "semgrep --config=auto .",
                                           "advisory": True}})


def _probes(**over) -> Probes:
    base = dict(
        docker_running=lambda: (True, ""),
        harness_on_path=lambda kind: True,
        manifest=_manifest_obj,
        forge_reachable=lambda: (True, ""),
        board_columns=lambda: ["TO-DO"],
        pickup_column=lambda: "TO-DO",
        requires_review=lambda: False,
        floor_enforced=lambda: False,
        harness_kind=lambda: "claude_code",
        product_link=lambda: _link(active=False, kind="off", reason="no product module"),
    )
    base.update(over)
    return Probes(**base)


@pytest.fixture
def healthy():
    return _probes()


@pytest.fixture
def product_ok():
    return _probes(product_link=lambda: _link(
        active=True, kind="ok", docs_repo="acme/docs",
        reason="registry, source repo and documentation repo agree"))


@pytest.fixture
def product_conflict():
    return _probes(product_link=lambda: _link(
        active=False, kind="conflict",
        reason="acme/api is not listed in `sources:` of acme/docs's `.openfactory/product.yaml`"))


@pytest.fixture
def product_config_broken():
    return _probes(product_link=lambda: _link(
        active=False, kind="config", reason="the docs repo could not be read"))


@pytest.fixture
def product_warned():
    return _probes(product_link=lambda: _link(
        active=True, kind="ok", docs_repo="acme/docs", reason="agree",
        warnings=["this project declares no source repo, so membership could not be checked"]))


@pytest.fixture
def product_explodes():
    def _boom():
        raise OSError("docs repo unreachable")

    return _probes(product_link=_boom)


def test_a_green_verdict_still_says_the_CLIENT_half_is_off():
    """The operator, reading "OK — 'podbeam' can run a ticket" on a project whose context
    repository does not exist (2026-08-14): *"o doctor não pode falar para seguir com ticket sem
    o contexto, não concorda?"*

    Half-right, and the half that is right needed fixing. A ticket genuinely runs without one —
    the coding agents read the SOURCE repo's own `docs:`, and making this a FAIL would tell
    every deployment that never wanted the product role that it is broken. What was wrong is
    that a bare pass reads as "nothing to see" while what is off is the CLIENT's entire half:
    the requirements corpus, the product role, the "ready to try" message, and the yes that
    releases production."""
    from openfactory.doctor import Finding, diagnose

    class _Off:
        kind = "off"
        active = False
        reason = ""
        warnings: list[str] = []

    findings = {f.check: f for f in diagnose(_probes(product_link=lambda: _Off())).findings}
    product = findings["product_link"]

    assert product.ok, "a legitimate opt-out was turned into a failure"
    assert isinstance(product, Finding)
    for owed in ("requirements", "product role", "ready to try"):
        assert owed in product.message.lower(), (
            f"the pass does not say what is switched off ({owed!r} missing): {product.message}")
    assert product.note and "onboard" in product.note, (
        "the pass carries no way to turn the client-facing half on")
