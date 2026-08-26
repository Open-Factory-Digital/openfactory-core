"""One vendor's name was the last resort of every credential resolution (#162, `doctor.py:832`).

The card names the doctor's board probe. The class is eighteen live sites across both axes, all
spelling the same thing in modules that name no vendor anywhere else:

    tracker_token_for(project) or github_app_token_from_env()
    forge_token_for(project)   or github_app_token_from_env()

`deployment_forge_token` was written for exactly this and its own docstring says the rest is "a
separate, mechanical sweep". This is that sweep, plus its missing twin on the tracker axis.

WHY THE TRACKER AXIS IS THE WORSE ONE. A forge handed the wrong system's token answers 401 —
wrong, but legible. Azure DevOps answers a GitHub token with HTTP 200 AND A SIGN-IN PAGE, so the
board reads as configured-but-unreadable; Jira answers an empty search, so a board with work in
TO-DO produces a pickup queue of `[]` and nothing says why. Both were found by running against a
real deployment, not by reading.

And one site was asking the wrong axis outright: the tech-lead's board read resolved through
`forge_token_for` and handed the result to `read_board`, whose own `_credential` docstring says in
writing that a board is a tracker object and that this is "the wrong axis for asking a tracker
anything".
"""

from __future__ import annotations

import ast
import inspect
import types
from pathlib import Path

import pytest

from openfactory.credentials import deployment_forge_token, deployment_tracker_token


def _project(*, tracker="github", forge="github"):
    return types.SimpleNamespace(
        name="p",
        tracker=types.SimpleNamespace(kind=tracker, options={}, repo="o/r"),
        forge=types.SimpleNamespace(kind=forge, options={}, repo="o/r"))


# ── 1. the deployment mints only for the vendor it has ──────────────────────────────────────────

@pytest.mark.parametrize("vendor", ["azure_devops", "jira", "gitlab"])
def test_no_github_credential_is_offered_to_another_vendors_TRACKER(vendor, monkeypatch):
    monkeypatch.setattr("openfactory.factory.github_app_token_from_env", lambda: "ghs_minted")

    assert deployment_tracker_token(_project(tracker=vendor)) is None


@pytest.mark.parametrize("vendor", ["azure_devops", "gitlab"])
def test_nor_to_another_vendors_FORGE(vendor, monkeypatch):
    monkeypatch.setattr("openfactory.factory.github_app_token_from_env", lambda: "ghs_minted")

    assert deployment_forge_token(_project(forge=vendor)) is None


def test_and_a_GITHUB_project_still_gets_the_mint(monkeypatch):
    """The positive twin. "Nothing is offered" is also true of a resolver that returns None to
    everybody, which would break every deployment that exists."""
    monkeypatch.setattr("openfactory.factory.github_app_token_from_env", lambda: "ghs_minted")

    assert deployment_tracker_token(_project()) == "ghs_minted"
    assert deployment_forge_token(_project()) == "ghs_minted"


def test_a_project_that_names_NO_vendor_is_still_served(monkeypatch):
    """A registry row with no `kind` at all predates the seam. Refusing it would turn a legacy
    row into a dead deployment, and this fallback is what those rows have always had."""
    monkeypatch.setattr("openfactory.factory.github_app_token_from_env", lambda: "ghs_minted")
    blank = types.SimpleNamespace(tracker=types.SimpleNamespace(kind=""), forge=None)

    assert deployment_tracker_token(blank) == "ghs_minted"
    assert deployment_forge_token(blank) == "ghs_minted"


def test_the_two_axes_are_read_SEPARATELY(monkeypatch):
    """A Jira-tracker / GitHub-forge project is the ordinary case the contract exists for, and a
    resolver reading the wrong field would answer for the wrong system on exactly that shape."""
    monkeypatch.setattr("openfactory.factory.github_app_token_from_env", lambda: "ghs_minted")
    mixed = _project(tracker="jira", forge="github")

    assert deployment_tracker_token(mixed) is None
    assert deployment_forge_token(mixed) is not None


# ── 2. the site the card named, and its neighbours ──────────────────────────────────────────────

def test_the_doctors_board_probe_offers_an_azure_board_NOTHING(monkeypatch):
    """`openfactory doctor` on a laptop whose `.env` carries `OPENFACTORY_GH_APP_*` minted a
    token, presented it to dev.azure.com, got HTTP 200 and a sign-in page, and reported "the board
    is configured but could not be read"."""
    from openfactory.doctor import _board_credential

    monkeypatch.setattr("openfactory.factory.github_app_token_from_env", lambda: "ghs_minted")
    monkeypatch.setattr("openfactory.credentials.tracker_token_for", lambda p: None)

    assert _board_credential(_project(tracker="azure_devops"))() is None


def test_and_a_github_board_still_resolves(monkeypatch):
    from openfactory.doctor import _board_credential

    monkeypatch.setattr("openfactory.factory.github_app_token_from_env", lambda: "ghs_minted")
    monkeypatch.setattr("openfactory.credentials.tracker_token_for", lambda p: None)

    assert _board_credential(_project())() == "ghs_minted"


def _jira(**options):
    from openfactory.contracts.project import Project, ProviderRef

    return Project(name="fx-jira", repo_path="/nowhere",
                   tracker=ProviderRef(kind="jira", repo="FX",
                                       options={"site": "acme.atlassian.net",
                                                "project_key": "FX", "email": "a@b.c", **options}),
                   forge=ProviderRef(kind="github", repo="acme/fx"))


def _no_ambient(monkeypatch):
    for name in ("JIRA_API_TOKEN", "AZURE_DEVOPS_PAT", "OPENFACTORY_TRACKER_TOKEN",
                 "OPENFACTORY_BOT_TOKEN", "OPENFACTORY_FORGE_TOKEN"):
        monkeypatch.delenv(name, raising=False)


def test_a_JIRA_tracker_is_not_handed_the_mint_through_the_PROVIDER_door(monkeypatch):
    """THE FINDING THAT MADE THIS SWEEP NEARLY COSMETIC. Every caller with no explicit token passes
    `token_provider=factory._bot_token_provider` — the GitHub App minter — and the Jira and Azure
    rows CALLED it and used the result as their static token. So resolving `None` at the call site
    changed which door the same `ghs_…` came in by, and nothing else. Measured before the fix: a
    Jira project with no `JIRA_API_TOKEN` built a tracker whose token was the minted one."""
    from openfactory.adapters.tracker.registry import build_tracker

    _no_ambient(monkeypatch)

    built = build_tracker(_jira(), token=None, token_provider=lambda: "ghs_MINTED")

    assert getattr(built, "token", None) != "ghs_MINTED", (
        "the GitHub App mint reached a Jira tracker through `token_provider`")
    assert not getattr(built, "token", None)


def test_and_JIRAS_OWN_credential_still_arrives(monkeypatch):
    """The positive twin — refusing everything would break every Jira deployment."""
    from openfactory.adapters.tracker.registry import build_tracker

    _no_ambient(monkeypatch)
    monkeypatch.setenv("JIRA_API_TOKEN", "jira_real")

    assert build_tracker(_jira(), token=None,
                         token_provider=lambda: "ghs_MINTED").token == "jira_real"


def _ado_token(built):
    """Where the Azure tracker keeps its credential — inside its client, not on itself.

    Asserted through a named helper because reading `built.token` answers `None` for this adapter
    whatever the credential is, and a probe that always answers None passes every leak test."""
    client = getattr(built, "ado", None)
    return getattr(client, "token", None) or getattr(client, "_token", None)


def _ado():
    from openfactory.contracts.project import Project, ProviderRef

    ref = ProviderRef(kind="azure_devops", repo="fx",
                      options={"organization": "c", "project": "P"})
    return Project(name="fx-ado", repo_path="/nowhere", tracker=ref, forge=ref)


def test_an_AZURE_board_is_not_handed_the_mint_either(monkeypatch):
    from openfactory.adapters.tracker.registry import build_tracker

    _no_ambient(monkeypatch)

    assert _ado_token(build_tracker(_ado(), token=None,
                                    token_provider=lambda: "ghs_MINTED")) is None


def test_and_the_AZURE_PAT_still_arrives(monkeypatch):
    """It arrives from the CLIENT, which reads the variable this project names on its own — the
    registry row adds nothing to the value and deliberately does not pretend to."""
    from openfactory.adapters.tracker.registry import build_tracker

    _no_ambient(monkeypatch)
    monkeypatch.setenv("AZURE_DEVOPS_PAT", "pat_real")

    assert _ado_token(build_tracker(_ado(), token=None,
                                    token_provider=lambda: "ghs_MINTED")) == "pat_real"


def test_an_EXPLICIT_azure_token_still_wins(monkeypatch):
    """The one thing the client cannot know about is a token the caller is holding — an onboarding
    flow that has just been handed a PAT, say. Dropping it would silently authenticate as somebody
    else's session."""
    from openfactory.adapters.tracker.registry import build_tracker

    _no_ambient(monkeypatch)
    monkeypatch.setenv("AZURE_DEVOPS_PAT", "the_ambient_one")

    assert _ado_token(build_tracker(_ado(), token="the_callers_own")) == "the_callers_own"


async def test_the_prod_release_hands_the_TRACKER_its_own_credential(monkeypatch):
    """The highest-authority action there is, and it resolved ONE token from the GitHub App and
    handed it to the tracker AND the observer — overriding a project's own PAT, because an
    explicit `token=` wins over everything a registry row resolves for itself.

    DRIVEN, not read. The first version of this guard asserted that the names `tracker_token_for`
    and `deployment_tracker_token` appear in the function — and stayed green when the resolved
    value was computed and then not used, which is precisely the mutation that had to go red."""
    from openfactory.actions import catalog
    from openfactory.actions.base import Actor

    _no_ambient(monkeypatch)
    monkeypatch.setenv("JIRA_API_TOKEN", "jira_real")
    seen: dict = {}
    manifest = types.SimpleNamespace(prod_approvers=["ana"], staging=None, production=None)
    monkeypatch.setattr(catalog, "_forge_and_manifest",
                        lambda name: (_jira(), manifest, object()))
    monkeypatch.setattr("openfactory.approvals.verify_approver", lambda *a, **k: True)
    # The observer's credential is the FORGE axis's now (`forge_token_for or
    # deployment_forge_token`), and the deployment mint for a GitHub forge is the App trio
    # reached through the composition root — so that is the seam to drive.
    monkeypatch.setattr("openfactory.factory.github_app_token_from_env", lambda: "ghs_MINTED")
    monkeypatch.setattr("openfactory.adapters.tracker.registry.build_tracker",
                        lambda p, **kw: seen.update(tracker=kw.get("token")))
    monkeypatch.setattr("openfactory.adapters.environment.registry.build_observer",
                        lambda p, **kw: seen.update(observer=kw.get("token")))
    monkeypatch.setattr("openfactory.observability.registry.journal_for", lambda *a, **k: None)
    monkeypatch.setattr("openfactory.orchestrator.promotion.PromotionRunner",
                        lambda **kw: types.SimpleNamespace(
                            release_prod=lambda *a, **k: types.SimpleNamespace(
                                note="released", state=types.SimpleNamespace(value="done"))))

    await catalog._promote(project="fx-jira", issue="7", version="1.0", approver="ana",
                           password="p", by=Actor(id="a", display="a", admin=True))

    assert seen.get("tracker") == "jira_real", (
        f"the release built the tracker with {seen.get('tracker')!r} — not this project's own")
    assert seen.get("observer") == "ghs_MINTED", (
        "the observer lost the credential it does take — the CI it watches is GitHub Actions")


def test_the_helper_that_reads_the_azure_credential_can_SEE_one():
    """Verify the verifier: `_ado_token` returning None for every input would pass both guards
    above, and `AzureBoardsTracker` has no `.token` attribute at all."""
    from openfactory.adapters.tracker.azure_devops import AzureBoardsTracker

    assert _ado_token(AzureBoardsTracker(organization="c", project="P", token="T")) == "T"


def test_the_board_read_resolves_a_TRACKER_credential(monkeypatch):
    """BEHAVIOUR, where a source-text assertion stood. It walked the AST for the name
    `tracker_token_for` — which stays green on a conversion that resolves the right axis and then
    hands the tracker the wrong credential anyway, which is exactly what was happening."""
    from openfactory.runtime.temporal import activities

    _no_ambient(monkeypatch)
    monkeypatch.setenv("JIRA_API_TOKEN", "jira_real")
    seen: dict = {}
    monkeypatch.setattr("openfactory.product.board.read_board",
                        lambda project, token=None: (seen.update(token=token), ([], ""))[1])
    monkeypatch.setattr("openfactory.product.queue.readiness",
                        lambda *a, **k: types.SimpleNamespace(todo=[]))

    activities._queued_tickets(_jira())

    assert seen.get("token") == "jira_real", (
        f"the board was read with {seen.get('token')!r} — not this project's tracker credential")


# ── 3. the box can finally ask its own question ─────────────────────────────────────────────────

def test_the_box_resolves_the_forge_credential_the_PROJECT_names(monkeypatch):
    """The comment here said this could not be done because `BoxConfig` carried no `token_env`.
    #162 made the box carry each axis's options WHOLE, and `token_env` lives in them."""
    from openfactory.credentials import forge_token_for
    from openfactory.runtime.boxed_job import BoxConfig, _project_for

    monkeypatch.setenv("ACME_ADO_PAT", "pat_from_the_named_variable")
    cfg = BoxConfig(project="p", issue="1", repo="fx-ado", forge_kind="azure_devops",
                    forge_options={"organization": "c", "project": "P",
                                   "token_env": "ACME_ADO_PAT"})

    assert forge_token_for(_project_for(cfg, repo_dir=None)) == "pat_from_the_named_variable"


def test_and_the_box_actually_CALLS_it():
    """Reachability. The guard above proves the resolution is possible; nothing proved the box
    performs it, and 'possible' is what the old comment already conceded."""
    from openfactory.runtime import boxed_job

    src = inspect.getsource(boxed_job.main)
    called = {getattr(n.func, "id", "") for n in ast.walk(ast.parse(inspect.cleandoc("\n" + src)))
              if isinstance(n, ast.Call)}

    assert "forge_token_for" in called, "the box still resolves its credential process-wide"


# ── 4. the ratchet ─────────────────────────────────────────────────────────────────────────────

#: A site may keep the mint by SAYING SO ON THE LINE, with a reason. The exemption lives at the
#: call rather than in a list here: a list in a test file drifts from the code it describes, and
#: the reason — the only part that matters — ends up somewhere the next reader will not look.
MARKER = "github-only:"


def _is_the_mint(func: ast.AST) -> bool:
    """Whether this call is the GitHub App mint, under ANY spelling.

    NAME, ALIAS AND ATTRIBUTE. Matching the bare name only was a bypass with a live example: for
    months `cli.py` carried `_github_app_token_from_env`, a one-line wrapper, and one word of
    difference made a nineteenth site invisible to this walk. `factory.github_app_token_from_env()`
    is the same hole facing the other way. Found by adversarial review, 2026-08-20."""
    name = getattr(func, "id", None) or getattr(func, "attr", None) or ""
    return name.lstrip("_") == "github_app_token_from_env"


def _last_resorts(root: Path) -> list[str]:
    """`<something> or github_app_token_from_env()` — the FALLBACK shape, not a bare call.

    ONE WALK, DRIVEN BY BOTH GUARDS BELOW. The first version of the neighbouring ratchet had a
    walk per guard and its verifier re-implemented the predicate inline, so the walk could be
    neutered entirely and stay green — adversarial review caught that, and this is the same shape.
    """
    out: list[str] = []
    for path in sorted(root.rglob("*.py")):
        text = path.read_text()
        lines = text.splitlines()
        for node in ast.walk(ast.parse(text)):
            if not (isinstance(node, ast.BoolOp) and isinstance(node.op, ast.Or)):
                continue
            for value in node.values[1:]:
                if not (isinstance(value, ast.Call) and _is_the_mint(value.func)):
                    continue
                # SIX LINES, because the reason is a sentence and the call it explains is often
                # wrapped: three was not enough for the first real exemption written against it.
                near = "\n".join(lines[max(0, value.lineno - 7):value.lineno])
                if MARKER in near:
                    continue
                out.append(f"{path.name}:{value.lineno}")
    return out


def test_no_neutral_module_makes_ONE_VENDOR_the_last_resort():
    """The ratchet. This class was spelled at eighteen sites; a nineteenth must fail the suite
    rather than wait for somebody to run `doctor` against a real deployment again.

    Read by AST from the CALL, so the paragraphs above explaining the rule cannot satisfy it."""
    package = Path(inspect.getfile(deployment_forge_token)).parent

    offenders = _last_resorts(package)

    assert not offenders, (
        "one vendor's mint is the last resort on a neutral path — ask the axis instead "
        "(`deployment_forge_token` / `deployment_tracker_token`), or say `# github-only: <why>` "
        f"on the line if this really is a GitHub-only capability: {offenders}")


def test_and_the_ratchet_can_SEE_one(tmp_path):
    """Verify the verifier, through `_last_resorts` ITSELF — the walk the guard above depends on,
    not a re-implementation of its predicate."""
    (tmp_path / "offender.py").write_text(
        "a = tracker_token_for(p) or github_app_token_from_env()\n"
        "b = github_app_token_from_env()\n"
        # FIRST in an `or` is the PRIMARY resolution, not a last resort standing in for another
        # system — flagging it would flag `github_app_token_from_env() or None`, which asks for
        # exactly what it says.
        "e = github_app_token_from_env() or None\n"
        "# github-only: this capability exists on one vendor\n"
        "c = tracker_token() or github_app_token_from_env()\n"
        "# github-only: and the reason may be a paragraph, so the window is generous\n"
        "#   (a wrapped call pushes the marker further from the name)\n"
        "d = tracker_token() or (\n    github_app_token_from_env())\n")

    found = _last_resorts(tmp_path)

    assert found == ["offender.py:1"], (
        f"line 1 is a last resort, line 2 is a bare call and line 4 says why: {found}")


@pytest.mark.parametrize("spelling", [
    "github_app_token_from_env()",
    "_github_app_token_from_env()",              # cli.py carried exactly this wrapper
    "factory.github_app_token_from_env()",
])
def test_the_ratchet_sees_the_mint_under_ANY_spelling(tmp_path, spelling):
    """One word of difference used to make a site invisible, and the wrapper that proves it was
    live in the tree until this change removed it."""
    (tmp_path / "bypass.py").write_text(f"a = tracker_token_for(p) or {spelling}\n")

    assert _last_resorts(tmp_path) == ["bypass.py:1"]


@pytest.mark.parametrize("innocent", [
    "mock_github_app_token_from_env()",       # a test double, not the mint
    "cached_github_app_token_from_env_value", # not even a call to it
])
def test_and_it_does_NOT_match_a_name_that_merely_CONTAINS_the_words(tmp_path, innocent):
    """A substring match would flag a double or a cache and send somebody to fix working code —
    the asymmetry that makes a false positive cost more than a miss."""
    (tmp_path / "innocent.py").write_text(f"a = tracker_token_for(p) or {innocent}\n")

    assert _last_resorts(tmp_path) == []


def test_and_the_wrapper_that_made_it_possible_is_GONE():
    """It had one caller, this sweep converted it, and ruff does not flag an unused module-level
    function — so a dead alias sat in the tree being a working bypass."""
    from openfactory import cli

    assert not hasattr(cli, "_github_app_token_from_env")


def test_the_ratchet_walks_a_package_that_still_exists():
    package = Path(inspect.getfile(deployment_forge_token)).parent
    seen = sum(1 for path in package.rglob("*.py")
               if "deployment_forge_token" in path.read_text()
               or "deployment_tracker_token" in path.read_text())

    assert seen >= 8, f"only {seen} modules ask an axis — the sweep did not land"


def _crossed(root: Path) -> list[str]:
    """Sites pairing one axis's `*_token_for` with the OTHER axis's `deployment_*` resolver.

    READ BY AST, NOT BY REGEX. The regex this replaces used `[^)]*` for the argument, which cannot
    cross a nested `)` — so it was blind to `forge_token_for(_project_for(cfg, repo_dir=None)) or
    deployment_forge_token(...)`, which is the literal shape the newest converted site introduced.
    A checker blind to the code it was written for is worse than none.
    """
    out: list[str] = []
    for path in sorted(root.rglob("*.py")):
        for node in ast.walk(ast.parse(path.read_text())):
            if not (isinstance(node, ast.BoolOp) and isinstance(node.op, ast.Or)):
                continue
            axes = [getattr(v.func, "id", "") for v in node.values if isinstance(v, ast.Call)]
            asked = {a.split("_token_for")[0] for a in axes if a.endswith("_token_for")}
            fell_back = {a.split("deployment_")[1].split("_token")[0]
                         for a in axes if a.startswith("deployment_")}
            if asked and fell_back and asked != fell_back:
                out.append(f"{path.name}:{node.lineno}")
    return out


def test_every_converted_site_asks_the_axis_that_MATCHES_its_resolver():
    """The mechanical risk of a sweep this wide: pairing `tracker_token_for` with
    `deployment_forge_token`, which reads as asking and answers for the other system."""
    crossed = _crossed(Path(inspect.getfile(deployment_forge_token)).parent)

    assert not crossed, f"an axis falls back to the OTHER axis's resolver: {crossed}"


def test_and_THAT_check_can_see_one_too(tmp_path):
    (tmp_path / "crossed.py").write_text(
        "a = tracker_token_for(p) or deployment_forge_token(p)\n"
        "b = forge_token_for(p) or deployment_forge_token(p)\n"
        # A NESTED CALL IN THE ARGUMENT — the shape the regex this replaced could not see, and the
        # literal shape `boxed_job` introduced.
        "c = forge_token_for(_project_for(cfg, repo_dir=None)) or deployment_tracker_token(p)\n")

    assert _crossed(tmp_path) == ["crossed.py:1", "crossed.py:3"]
