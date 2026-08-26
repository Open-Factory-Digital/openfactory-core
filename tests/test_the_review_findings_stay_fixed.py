"""The pre-commit adversarial review's confirmed findings, each pinned as a property.

Fifty agents reviewed this batch before it reached the pilot operator's terminal — five lenses
(credentials, idempotency, vendor neutrality, blast radius, regression), every finding then
handed to an independent verifier told to REFUTE it. Six blockers and fourteen serious defects
survived, in code I had already tested and was about to ship against a real client repository.

They are pinned here rather than in the file each one lives in, because what they have in
common is the moment they were caught: the last gate before a write to somebody else's
repository. If one of these goes red, the batch is not ready.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from openfactory.contracts.project import Project, ProviderRef
from tests.pinned_probes import a_fully_pinned_probe_set


def _ado(**opts) -> Project:
    ref = ProviderRef(kind="azure_devops", repo="dsk-api",
                      options={"organization": "acme-ai", "project": "Deskline", **opts})
    return Project(name="dsk", repo_path="https://dev.azure.com/acme-ai/Deskline/_git/dsk-api",
                   tracker=ProviderRef(kind="azure_devops", repo="Deskline",
                                       options={"organization": "acme-ai"}),
                   forge=ref)


# ── BLOCKER: a GitHub credential must never reach dev.azure.com ─────────────────────────────────

def test_the_pr_clone_url_never_carries_the_wrong_vendors_secret(monkeypatch):
    """`env apply --pr` called `forge.clone_url(..., token=token)` directly, walking around the
    refusal `build_forge` makes on the Azure row — a live GitHub App token embedded in a
    dev.azure.com URL and presented to Microsoft as HTTP Basic."""
    from openfactory.adapters.forge.registry import clone_url_for, repo_of

    monkeypatch.delenv("AZURE_DEVOPS_PAT", raising=False)
    monkeypatch.delenv("OPENFACTORY_FORGE_TOKEN", raising=False)
    monkeypatch.setenv("OPENFACTORY_BOT_TOKEN", "ghs_LIVE_GITHUB_APP_TOKEN")
    project = _ado()

    url = clone_url_for(project, repo_of(project), token="ghs_LIVE_GITHUB_APP_TOKEN")

    assert "dev.azure.com" in url
    assert "ghs_LIVE_GITHUB_APP_TOKEN" not in url, (
        "a GitHub secret was embedded in an Azure DevOps URL — the exact defect the Azure row's "
        "token refusal exists to prevent")


def test_the_catalog_goes_through_the_wrapper_not_the_adapter(monkeypatch):
    """The reachability half: the property above is only true if the call site uses it."""
    from openfactory.actions import catalog

    code = _code_of(catalog._env_apply_impl)
    assert "clone_url_for(" in code
    assert ".clone_url(" not in code, "the catalog calls the adapter directly again"


def _code_of(fn) -> str:
    """A function's CODE, without its docstring — read through the AST.

    The first version of this guard grepped the source and tripped on the comment that explains
    the very rule it enforces, which this codebase has already paid for once ("a rule that
    forces a worse defect": read via AST so the explanation is not the violation)."""
    import ast
    import inspect
    import textwrap

    tree = ast.parse(textwrap.dedent(inspect.getsource(fn)))
    body = tree.body[0].body
    if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
        body = body[1:]
    return "\n".join(ast.unparse(node) for node in body)


def test_the_context_repo_clone_uses_the_PROJECTS_credential():
    """`product init --write` resolved `forge_token() or github_app_token_from_env()` — always
    GitHub — and handed it to whatever forge the project actually has.

    The seam MOVED TWICE. First to `product.onboard` (the CLI now delegates, so two copies
    cannot drift apart again). Then the fallback itself stopped naming a vendor: neutral code
    asks `deployment_forge_token`, which offers the App mint to a GitHub axis and NOTHING to any
    other, so this module can no longer mention one vendor at all. Raised by the operator while
    reviewing these very changes (2026-08-14): a fix must serve the product, not one
    deployment."""
    from openfactory import cli
    from openfactory.product import onboard as po

    assert "context_clone_url" in _code_of(cli._context_clone_url), (
        "the CLI grew its own resolution again — two drifting copies is how the original "
        "defect shipped")
    code = _code_of(po.context_clone_url) + _code_of(po._context_token)
    assert "clone_url_for(" in code and "forge_token_for(" in code
    assert "github" not in code.lower(), (
        f"a vendor is named in the neutral context path: {code}")
    # the CALLS, not the import line — `from … import deployment_forge_token, forge_token_for`
    # is alphabetical and would decide this assertion instead of the code doing so
    assert code.index("forge_token_for(project)") < code.index("deployment_forge_token(project)"), (
        "the deployment-wide credential is consulted before the project's own")


# ── BLOCKER: a timeout must not publish the token in its argv ───────────────────────────────────

def test_a_git_timeout_never_carries_the_tokened_url(monkeypatch):
    from openfactory.onboarding import propose_manifest as pm

    def _times_out(cmd, **kw):
        raise subprocess.TimeoutExpired(cmd, timeout=1)

    monkeypatch.setattr(pm.subprocess, "run", _times_out)
    rc, out = pm._git(["clone", "https://openfactory:ghp_SECRET@dev.azure.com/o/p/_git/r", "/tmp/x"])

    assert rc != 0
    assert "ghp_SECRET" not in out, "the timeout published the credential"
    assert "timed out" in out


# ── BLOCKER: a merged proposal must not lock the verb for ever ─────────────────────────────────

class _Forge:
    def __init__(self, *, found="", state="active"):
        self.found, self.state = found, state
        self.asked_state = False

    def pr_for_head(self, head, *, repo=""):
        return self.found

    def pr_status(self, *, pr, repo=""):
        self.asked_state = True
        return self.state


@pytest.mark.parametrize("state, still", [
    ("active", True), ("open", True),
    ("merged", False), ("closed", False), ("abandoned", False), ("completed", False),
])
def test_only_an_OPEN_proposal_counts_as_already_proposed(state, still):
    from openfactory.onboarding.propose_manifest import already_proposed

    forge = _Forge(found="https://host/pull/1", state=state)
    answer = already_proposed(forge, "acme/api")

    assert bool(answer) is still, (
        f"a {state} proposal read as {'still open' if answer else 'gone'} — a merged manifest PR "
        f"that counts as 'already proposed' means the manifest can never be corrected")


def test_a_state_that_cannot_be_read_is_treated_as_still_open():
    """Unreadable is not closed: proposing over an open review is the worse mistake."""
    class _Mute(_Forge):
        def pr_status(self, *, pr, repo=""):
            raise RuntimeError("unreachable")

    from openfactory.onboarding.propose_manifest import already_proposed

    assert already_proposed(_Mute(found="https://host/pull/1"), "acme/api") == \
        "https://host/pull/1"


# ── BLOCKER: an unborn HEAD is not a branch name ───────────────────────────────────────────────

def test_the_default_branch_of_an_empty_clone_is_not_the_word_HEAD(tmp_path):
    """`git rev-parse --abbrev-ref HEAD` prints the literal `HEAD` and exits 128 on a repository
    with no commits — read blindly it became the pull request's base."""
    from openfactory.onboarding.propose_manifest import default_branch

    empty = tmp_path / "empty"
    empty.mkdir()
    subprocess.run(["git", "init", "-b", "main", str(empty)], check=True, capture_output=True)

    assert default_branch(empty) == "main"


def test_the_default_branch_is_READ_not_assumed(tmp_path):
    repo = tmp_path / "onmaster"
    repo.mkdir()
    for args in (["init", "-b", "master"], ["config", "user.email", "t@t"],
                 ["config", "user.name", "t"], ["commit", "--allow-empty", "-m", "seed"]):
        subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)

    from openfactory.onboarding.propose_manifest import default_branch

    assert default_branch(repo) == "master", (
        "a `master` repository would get a pull request against a branch that does not exist")


# ── SERIOUS: a flag that cannot act must refuse, never be ignored ──────────────────────────────

def test_pr_on_a_local_checkout_is_REFUSED_not_silently_ignored(tmp_path, monkeypatch):
    from typer.testing import CliRunner

    from openfactory.cli import app

    monkeypatch.setenv("OPENFACTORY_REGISTRY", str(tmp_path / "registry.yaml"))
    checkout = tmp_path / "local"
    checkout.mkdir()
    (checkout / "pyproject.toml").write_text('[project]\nname = "x"\nversion = "0.1.0"\n')
    assert CliRunner().invoke(app, ["project", "add", "demo", str(checkout)]).exit_code == 0

    result = CliRunner().invoke(app, ["env", "apply", "demo", "--yes", "--pr",
                                      "--set", "validate.test=pytest -q"])

    assert result.exit_code != 0
    assert "local checkout" in result.output and "--pr" in result.output
    assert not (checkout / ".openfactory" / "project.yaml").exists(), (
        "it wrote the file while the operator was asking for a pull request")


# ── SERIOUS: a bare name must not resolve as a directory in the process's cwd ──────────────────

def test_a_project_NAME_is_never_read_as_a_path_in_the_working_directory(tmp_path, monkeypatch):
    """On the worker the cwd is the platform's own install; a typo'd name that matched a
    directory there would write a manifest into it."""
    from typer.testing import CliRunner

    from openfactory.cli import app

    monkeypatch.setenv("OPENFACTORY_REGISTRY", str(tmp_path / "registry.yaml"))
    (tmp_path / "openfactory").mkdir()          # a name that is also a directory here
    monkeypatch.chdir(tmp_path)

    result = CliRunner().invoke(app, ["env", "apply", "openfactory", "--yes"])

    assert result.exit_code != 0
    assert "no project called" in result.output
    assert not (tmp_path / "openfactory" / ".openfactory").exists()


# ── SERIOUS: the temporary clone must not survive a FAILED clone ───────────────────────────────

def test_a_failed_clone_leaves_no_directory_behind(monkeypatch):
    from openfactory.onboarding import propose_manifest as pm

    monkeypatch.setattr(pm, "_git", lambda *a, **kw: (128, "fatal: repository not found"))
    made: list[Path] = []
    real_mkdtemp = pm.tempfile.mkdtemp

    def _remember(**kw):
        path = real_mkdtemp(**kw)
        made.append(Path(path))
        return path

    monkeypatch.setattr(pm.tempfile, "mkdtemp", _remember)
    path, why = pm.clone_for_proposal(clone_url="https://host/x.git")

    assert path is None and "not found" in why
    assert made and not made[0].exists(), "a failed clone left its directory in /tmp"


# ── SERIOUS: a cross-project pull request must be LINKED where it lives ────────────────────────

def test_the_pr_page_url_follows_the_project_the_answer_reports():
    from openfactory.adapters.forge.azure_devops import AzureReposForge

    f = AzureReposForge("dsk-api", organization="acme-ai", project="Deskline", token="pat")
    answer = {"pullRequestId": 12,
              "repository": {"name": "product-context", "project": {"name": "SharedDocs"}}}

    url = f._web_url(repo=f"{f._project_of(answer)}/{f._repo_of(answer)}", pr_id=12)

    assert "/SharedDocs/_git/product-context/pullrequest/12" in url
    assert "/Deskline/_git/" not in url


def test_a_same_project_answer_keeps_the_url_it_always_had():
    from openfactory.adapters.forge.azure_devops import AzureReposForge

    f = AzureReposForge("dsk-api", organization="acme-ai", project="Deskline", token="pat")
    answer = {"pullRequestId": 3,
              "repository": {"name": "dsk-api", "project": {"name": "Deskline"}}}

    url = f._web_url(repo=f"{f._project_of(answer)}/{f._repo_of(answer)}", pr_id=3)

    assert "/acme-ai/Deskline/_git/dsk-api/pullrequest/3" in url


def test_a_generic_owner_name_row_does_not_have_its_OWNER_read_as_a_project():
    """A registry that filled the GitHub-shaped `owner/name` field on an Azure row is a
    misconfiguration this adapter tolerates by reducing to the leaf. The qualifier rule must not
    turn that owner into an ADO project and aim every clone somewhere that does not exist."""
    from openfactory.adapters.forge.azure_devops import AzureReposForge

    f = AzureReposForge("acme/dsk-api", organization="acme-ai", project="Deskline",
                        token="pat")

    assert "/Deskline/_git/dsk-api" in f.clone_url("acme/dsk-api", token="pat")


# ── PILOT (2026-08-13): the remedy must fit how the project is REGISTERED ──────────────────────

def test_a_missing_manifest_on_a_URL_project_names_the_command_that_can_write_it(tmp_path):
    """`doctor` told the operator to run `openfactory project init` — which, for a project
    registered by clone URL (the compose worker's own shape), writes nothing and says so. The
    remedy has to name the verb that actually applies: the environment session, or `--pr`."""
    from openfactory.loader import load_manifest

    by_url = Project(name="podbeam", repo_path="https://github.com/solo-dev/podbeam.git",
                     tracker=ProviderRef(kind="github", repo="solo-dev/podbeam"))
    with pytest.raises(FileNotFoundError) as err:
        load_manifest(by_url, repo_root=tmp_path)

    text = str(err.value)
    assert "--pr" in text, "the no-checkout answer is not offered"
    assert "env apply" in text
    assert "project init" not in text, "it still names the command that cannot write this file"


def test_a_missing_manifest_on_a_LOCAL_project_names_the_path_it_would_write(tmp_path):
    from openfactory.loader import load_manifest

    local = Project(name="demo", repo_path=str(tmp_path),
                    tracker=ProviderRef(kind="github", repo="acme/demo"))
    with pytest.raises(FileNotFoundError) as err:
        load_manifest(local, repo_root=tmp_path)

    text = str(err.value)
    assert str(tmp_path) in text and "env apply" in text
    assert "--pr" not in text, "the pull-request form has nothing to do with a checkout here"


# ── PILOT (2026-08-13): "not written yet" is not "broken" ──────────────────────────────────────

def _registered(tmp_path, monkeypatch, repo_path: str):
    from typer.testing import CliRunner

    from openfactory.cli import app

    monkeypatch.setenv("OPENFACTORY_REGISTRY", str(tmp_path / "registry.yaml"))
    assert CliRunner().invoke(app, ["project", "add", "demo", repo_path]).exit_code == 0
    return CliRunner()


def test_doctor_at_registration_time_says_the_red_lines_are_EXPECTED(tmp_path, monkeypatch):
    """The operator followed the document exactly: register (§2), then run the diagnostic the
    same section ends with. It answered "NOT ready — fix the FAIL lines above" about a manifest
    that §3 has not written yet, and he went looking for a defect that was not there
    (2026-08-13). Not-ready and broken are different sentences."""
    from openfactory import doctor as doc
    from openfactory.cli import app

    runner = _registered(tmp_path, monkeypatch, str(tmp_path / "checkout"))

    # THE MANIFEST IS THE ONLY THING THIS TEST MEASURES, so it is the only thing unpinned —
    # every other member of `doctor.Probes` answers green, derived from the dataclass's own
    # fields (tests/pinned_probes.py). The hand-pinned version named seven of the fifteen members
    # there were then and left the rest reading the real machine, which is how a probe added
    # later went green on a laptop and red in a clean environment, twice: `agent_credential`
    # (2026-08-21, a laptop `.env` that `cli.py`'s `_load_environment()` reloads inside the
    # CliRunner call) and `api_budget` (2026-08-24, a laptop where `gh` is logged in). Neither
    # had anything to do with the verdict asserted below.
    monkeypatch.setattr(doc, "probes_for", lambda _project: a_fully_pinned_probe_set(
        manifest=lambda: (_ for _ in ()).throw(FileNotFoundError("no manifest here"))))
    result = runner.invoke(app, ["doctor", "demo"])

    assert result.exit_code == 1, "it must still be non-zero — nothing can run yet"
    assert "EXPECTED" in result.output
    assert "§3" in result.output, "the step that answers it is not named"
    assert "fix the FAIL lines above" not in result.output


def test_a_REAL_failure_still_says_fix_it(tmp_path, monkeypatch):
    """The positive twin: when something IS broken, the softer sentence must not appear."""
    from openfactory import doctor as doc
    from openfactory.cli import app

    runner = _registered(tmp_path, monkeypatch, str(tmp_path / "checkout"))

    # DOCKER IS WHAT THIS TWIN MEASURES, and the manifest is the §2 state it measures it in.
    # Everything else green: with a second unpinned probe red, the harsher sentence would appear
    # for a reason this test never named and it would pass with the docker line deleted
    # (measured on a clean clone, 2026-08-21).
    monkeypatch.setattr(doc, "probes_for", lambda _project: a_fully_pinned_probe_set(
        docker_running=lambda: (False, "the daemon is not answering"),
        manifest=lambda: (_ for _ in ()).throw(FileNotFoundError("no manifest here"))))
    result = runner.invoke(app, ["doctor", "demo"])

    assert result.exit_code == 1
    assert "fix the FAIL lines above" in result.output
    assert "EXPECTED" not in result.output


def test_a_MISSING_AGENT_CREDENTIAL_at_registration_is_never_excused_as_expected(tmp_path,
                                                                                monkeypatch):
    """The other half of the same verdict, and CI demonstrated it by accident before anyone
    asserted it: on a runner with no credential the §2 report read "fix the FAIL lines above",
    which is CORRECT — ONBOARDING §1 puts the agent credential before registration ("what must be
    green at THIS point is … docker, the harness, the agent credential, forge access and the
    board's columns"), so no step ahead answers it. Nothing asserted that, so the day somebody
    adds `agent_credential` to the answered-later set the softer sentence would start hiding the
    one prerequisite that cannot be postponed (2026-08-21)."""
    from openfactory import doctor as doc
    from openfactory.cli import app

    runner = _registered(tmp_path, monkeypatch, str(tmp_path / "checkout"))

    monkeypatch.setattr(doc, "probes_for", lambda _project: a_fully_pinned_probe_set(
        agent_credential=lambda: (False, "no agent credential in this environment"),
        manifest=lambda: (_ for _ in ()).throw(FileNotFoundError("no manifest here"))))
    result = runner.invoke(app, ["doctor", "demo"])

    assert result.exit_code == 1
    assert "no agent credential" in result.output, "the missing prerequisite is not named"
    assert "EXPECTED" not in result.output, (
        "a red line no step ahead answers was labelled as expected at this point")
    assert "fix the FAIL lines above" in result.output


# ── PILOT (2026-08-13): the three artefacts must be told apart ─────────────────────────────────

def test_the_onboarding_distinguishes_manifest_context_and_module_map():
    """The operator asked "é neste momento que ele cria o OKF?" at §3 — a fair question, since
    the document mentioned the module map exactly once, in passing, at the very end. Three
    artefacts, three readers, three homes: the manifest (the platform), the context (the product
    role), the module map (the coding agents). A reader guided only by this document has no
    other way to learn the third exists, or that it is what makes each ticket cheaper."""
    from pathlib import Path as _P

    text = _P("docs/ONBOARDING.md").read_text()
    section = text.split("## 3 ·", 1)[1].split("## 4 ·", 1)[0]

    assert "knowledge/" in section, "the module map is not named where the reader asks about it"
    assert "knowledge build" in section, "no way to generate the first one is offered"
    assert "no model call" in section or "no token cost" in section, (
        "the reader cannot tell whether this costs them money")
    for other in ("the manifest", "the context"):
        assert other in section, f"{other} is not distinguished from the rest"


# ── PILOT (2026-08-14): doctor asked eight questions and not the one that gates pickup ─────────

def test_doctor_asks_the_gates_own_question(tmp_path, monkeypatch):
    """`doctor` is the command the documentation says tells you when a ticket can run, and it
    never checked the box proof — so a deployment whose proof had FAILED (or expired, or never
    run) read "OK — can run a ticket" while every card sat in TO-DO. Found the moment the
    pilot's board went green and the only thing left was a proof taken before the image
    shipped `uv`."""
    from typer.testing import CliRunner

    from openfactory import doctor as doc
    from openfactory.cli import app

    monkeypatch.setenv("OPENFACTORY_REGISTRY", str(tmp_path / "registry.yaml"))
    checkout = tmp_path / "co"
    (checkout / ".openfactory").mkdir(parents=True)
    (checkout / ".openfactory" / "project.yaml").write_text(
        "version: 1\nsetup: []\nvalidate:\n  test: pytest -q\n  security: bandit -q .\n")
    assert CliRunner().invoke(app, ["project", "add", "demo", str(checkout)]).exit_code == 0

    # THE GATE IS THE ONE THING UNPINNED: a healthy machine whose box proof failed.
    monkeypatch.setattr(doc, "probes_for", lambda _project: a_fully_pinned_probe_set(
        box_gate=lambda: "the last box proof FAILED — run `openfactory box prove demo`"))
    result = CliRunner().invoke(app, ["doctor", "demo"])

    assert result.exit_code != 0, "doctor said a project the poller will hold is ready"
    assert "box proof FAILED" in result.output, "the gate's own sentence is not shown"
    assert "box prove demo" in result.output


def test_a_project_that_has_simply_not_been_proven_YET_still_reads_as_expected(tmp_path,
                                                                               monkeypatch):
    """The nuance that must survive the new check: at §2 nothing has been proven BY
    CONSTRUCTION, and 'fix the FAIL lines above' there is the confusion this verdict exists to
    end. Every red line answered by a step still ahead reads as EXPECTED — and the sentence
    names the NEXT step, not a generic one."""
    from typer.testing import CliRunner

    from openfactory import doctor as doc
    from openfactory.cli import app

    monkeypatch.setenv("OPENFACTORY_REGISTRY", str(tmp_path / "registry.yaml"))
    checkout = tmp_path / "co"
    (checkout / ".openfactory").mkdir(parents=True)
    (checkout / ".openfactory" / "project.yaml").write_text(
        "version: 1\nsetup: []\nvalidate:\n  test: pytest -q\n  security: bandit -q .\n")
    assert CliRunner().invoke(app, ["project", "add", "demo", str(checkout)]).exit_code == 0

    monkeypatch.setattr(doc, "probes_for", lambda _project: a_fully_pinned_probe_set(
        box_gate=lambda: "the box has never been proven — run `openfactory box prove demo`"))

    result = CliRunner().invoke(app, ["doctor", "demo"])

    assert "EXPECTED" in result.output, (
        "an operator who has simply not reached §5 yet is told something is broken")
    assert "box prove demo" in result.output, "the next step is not named"


def test_the_real_probes_actually_wire_the_gate(tmp_path, monkeypatch):
    """THE REACHABILITY HALF, and it caught its own absence: with the check added and the probe
    NOT wired in `probes_for`, the test above still passed — it injected the probe itself. A
    guard that supplies the wiring it is meant to verify proves the guard."""
    from openfactory import doctor as doc

    monkeypatch.setenv("OPENFACTORY_REGISTRY", str(tmp_path / "registry.yaml"))
    project = Project(name="demo", repo_path=str(tmp_path),
                      tracker=ProviderRef(kind="github", repo="acme/demo"))
    asked: list[str] = []

    def _gate(p, *, sandbox, repo=""):
        asked.append(getattr(p, "name", "?"))
        return "held for a measured reason"

    monkeypatch.setattr("openfactory.box_prove.gate_reason", _gate)
    probes = doc.probes_for(project)

    assert probes.box_gate is not None, "doctor's own probes do not carry the gate"
    assert probes.box_gate() == "held for a measured reason"
    assert asked == ["demo"], (
        "the probe does not reach `box_prove.gate_reason` — doctor would answer a question the "
        "poller never asked")


# ── PILOT (2026-08-14): "it cannot be true only because you are telling me here" ─────────────────────

def test_doctor_names_the_open_proposal_instead_of_describing_one(tmp_path, monkeypatch):
    """The manual merge is deliberate; being told about it in chat is not. The remedy used to
    read "IF onboard already opened a pull request, this is that PR" — a conditional about a
    fact the platform can look up, with no link, to a reader who cannot tell whether it applies
    to them. It is now LOOKED UP and named."""
    from typer.testing import CliRunner

    from openfactory import doctor as doc
    from openfactory.cli import app

    monkeypatch.setenv("OPENFACTORY_REGISTRY", str(tmp_path / "registry.yaml"))
    assert CliRunner().invoke(
        app, ["project", "add", "demo", "https://github.com/acme/demo.git"]).exit_code == 0

    # THE TWO THINGS THIS TEST MEASURES: a manifest that is missing, and a proposal that is open.
    monkeypatch.setattr(doc, "probes_for", lambda _project: a_fully_pinned_probe_set(
        manifest=lambda: (_ for _ in ()).throw(FileNotFoundError("no manifest")),
        open_proposal=lambda: "https://github.com/acme/demo/pull/86"))

    result = CliRunner().invoke(app, ["doctor", "demo"])

    assert "https://github.com/acme/demo/pull/86" in result.output, (
        "the operator is told a pull request may exist and not which one")
    assert "PROPOSED" in result.output
    assert "merge" in result.output.lower()
    assert "if `openfactory onboard`" not in result.output, "the conditional survived"
    # THE CLOSING VERDICT TOO, and separately: the finding names the PR, and the last line of
    # the command is what an operator acts on. Asserting only "somewhere in the output" let a
    # verdict that had stopped quoting the finding's own next step pass (mutation, 2026-08-14).
    closing = next(line for line in result.output.splitlines() if line.startswith("Next:"))
    assert "https://github.com/acme/demo/pull/86" in closing, (
        f"the last line does not name the step it is asking for: {closing}")
    # AND IT PLACES THE READER IN THE DOCUMENT. Every other remedy cites its section; this one
    # did not, so an operator following ONBOARDING could not tell whether "merge that PR" was a
    # step they had reached or one they had skipped — and asked (pilot, 2026-08-14: "pela
    # documentação agora seria isso aqui, não? … onboard --yes").
    assert "ONBOARDING §3" in result.output, (
        "the merge step is not anchored in the document the operator is following")


def test_with_no_proposal_open_the_session_is_named_instead(tmp_path, monkeypatch):
    """The other half of the same fact: a project nobody has proposed for must not be sent to
    merge a pull request that does not exist."""
    from typer.testing import CliRunner

    from openfactory import doctor as doc
    from openfactory.cli import app

    monkeypatch.setenv("OPENFACTORY_REGISTRY", str(tmp_path / "registry.yaml"))
    assert CliRunner().invoke(
        app, ["project", "add", "demo", "https://github.com/acme/demo.git"]).exit_code == 0

    monkeypatch.setattr(doc, "probes_for", lambda _project: a_fully_pinned_probe_set(
        manifest=lambda: (_ for _ in ()).throw(FileNotFoundError("no manifest")),
        open_proposal=lambda: ""))

    result = CliRunner().invoke(app, ["doctor", "demo"])

    assert "PROPOSED" not in result.output, "a proposal that does not exist was announced"
    assert "onboard" in result.output and "ONBOARDING §3" in result.output


def test_the_lookup_is_wired_and_asks_both_proposal_branches(tmp_path, monkeypatch):
    """Reachability, again by name: the probe must be ON the real Probes and must ask about the
    branches BOTH verbs use — `onboard` rides one, `env apply --pr` the other."""
    from openfactory import doctor as doc

    monkeypatch.setenv("OPENFACTORY_REGISTRY", str(tmp_path / "registry.yaml"))
    project = Project(name="demo", repo_path="https://github.com/acme/demo.git",
                      tracker=ProviderRef(kind="github", repo="acme/demo"),
                      forge=ProviderRef(kind="github", repo="acme/demo"))
    asked: list[str] = []

    monkeypatch.setattr("openfactory.adapters.forge.registry.build_forge",
                        lambda *a, **kw: object())
    monkeypatch.setattr(
        "openfactory.onboarding.propose_manifest.already_proposed",
        lambda forge, repo, branch="": asked.append(branch) or (
            "https://github.com/acme/demo/pull/9" if branch == "openfactory/manifest" else ""))

    probes = doc.probes_for(project)

    assert probes.open_proposal is not None, "doctor's own probes do not carry the lookup"
    assert probes.open_proposal() == "https://github.com/acme/demo/pull/9"
    assert asked == ["openfactory/onboard", "openfactory/manifest"], (
        f"only some proposal branches are asked about: {asked}")


def test_an_unreachable_forge_never_reads_as_no_proposal(tmp_path, monkeypatch):
    """"Could not ask" must not become "there is none" — that is how a second, competing
    proposal gets opened over an open review."""
    from openfactory import doctor as doc

    monkeypatch.setenv("OPENFACTORY_REGISTRY", str(tmp_path / "registry.yaml"))
    project = Project(name="demo", repo_path="https://github.com/acme/demo.git",
                      tracker=ProviderRef(kind="github", repo="acme/demo"),
                      forge=ProviderRef(kind="github", repo="acme/demo"))

    monkeypatch.setattr("openfactory.adapters.forge.registry.build_forge",
                        lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("no credential")))

    assert doc.probes_for(project).open_proposal() == "", (
        "an unreachable forge must degrade to 'no information', not crash the diagnostic")


def test_no_line_says_propose_it_while_another_says_it_is_already_proposed(tmp_path,
                                                                           monkeypatch):
    """A SCREEN, not a string. `_manifest` said "merge it — nothing needs proposing again" and
    four lines below, inside another check's message, the loader's own text said "`env apply
    … --pr` proposes it as a pull request". Both are true sentences and together they are a
    contradiction, in the one output an operator reads when they do not yet know the system
    (pilot, 2026-08-14)."""
    from typer.testing import CliRunner

    from openfactory import doctor as doc
    from openfactory.cli import app

    monkeypatch.setenv("OPENFACTORY_REGISTRY", str(tmp_path / "registry.yaml"))
    assert CliRunner().invoke(
        app, ["project", "add", "demo", "https://github.com/acme/demo.git"]).exit_code == 0

    loader_words = ("project 'demo' has no manifest at /var/lib/openfactory/repos/demo/"
                    ".openfactory/project.yaml. `openfactory env apply demo --yes --pr` "
                    "proposes it as a pull request on the repository")
    monkeypatch.setattr(doc, "probes_for", lambda _project: a_fully_pinned_probe_set(
        manifest=lambda: (_ for _ in ()).throw(FileNotFoundError(loader_words)),
        open_proposal=lambda: "https://github.com/acme/demo/pull/86"))

    output = CliRunner().invoke(app, ["doctor", "demo"]).output

    assert "still PROPOSED" in output, "the fixture no longer reaches the state it tests"
    assert "proposes it as a pull request" not in output, (
        "a check repeats the loader's write-a-manifest instructions while the manifest finding "
        "says one is already proposed and must only be merged")
    assert "env apply" not in output, (
        "the operator is pointed at a second way to propose what is already open")


def test_doctors_screen_belongs_to_doctor_even_when_a_probe_degrades(tmp_path, monkeypatch,
                                                                     capfd):
    """A BEHAVIOURAL guard against the REAL degrade path — and the first version of it was
    decoration: it monkeypatched `RepoCache.sync` with a double that called the logger, so it
    proved the double and passed with the defect restored (mutation, 2026-08-14). The cache
    here genuinely fails — an unresolvable host — and whatever it says on the way down, the
    first thing an operator reads is doctor's own output.

    The shape: the repo cache degraded with a raw `print`, so "clone failed … not found" landed
    ABOVE the table, before the reader knew there was a table, immune to the logger silencing
    that fixed the same defect one layer up the day before."""
    from typer.testing import CliRunner

    from openfactory.cli import app

    monkeypatch.setenv("OPENFACTORY_REGISTRY", str(tmp_path / "registry.yaml"))
    monkeypatch.setenv("OPENFACTORY_REPO_CACHE", str(tmp_path / "cache"))
    monkeypatch.setenv("OPENFACTORY_REPO_CACHE", str(tmp_path / "cache"))
    assert CliRunner().invoke(
        app, ["project", "add", "demo", "https://example.invalid/nope.git"]).exit_code == 0

    capfd.readouterr()  # drop whatever registration said
    result = CliRunner().invoke(app, ["doctor", "demo"])
    leaked = result.output + capfd.readouterr().err + capfd.readouterr().out

    assert "OPENFACTORY_CACHE" not in leaked, (
        "the cache's degrade notice reaches the diagnostic's own screen")
    first = next(line for line in result.output.splitlines() if line.strip())
    assert first.startswith("·") or first.lstrip().startswith(("ok", "FAIL")), (
        f"doctor's output does not begin with doctor: {first!r}")


def test_doctor_runs_its_probes_with_the_libraries_quieted(tmp_path, monkeypatch):
    """The other half of the same screen, and it needs a different instrument: pytest's own
    logging plugin swallows records, so no output capture can observe this leak (a mutation
    removing the silencing passed a capture-based guard, 2026-08-14). What IS observable is the
    level the probes RUN at — measured from inside one."""
    import logging

    from typer.testing import CliRunner

    from openfactory import doctor as doc
    from openfactory.cli import app

    monkeypatch.setenv("OPENFACTORY_REGISTRY", str(tmp_path / "registry.yaml"))
    assert CliRunner().invoke(app, ["project", "add", "demo", str(tmp_path)]).exit_code == 0

    seen: list[int] = []

    def _docker():
        seen.append(logging.getLogger("openfactory").getEffectiveLevel())
        return True, ""

    # ONE PROBE UNPINNED, and it is the instrument itself. This site had the widest exposure of
    # the nine and the narrowest assertion: it named a single member and let the other fourteen
    # answer off this machine, surviving only because it measures a logging level rather than
    # the report (sweep, 2026-08-24).
    monkeypatch.setattr(doc, "probes_for",
                        lambda _project: a_fully_pinned_probe_set(docker_running=_docker))
    before = logging.getLogger("openfactory").level
    CliRunner().invoke(app, ["doctor", "demo"])

    assert seen and seen[0] >= logging.ERROR, (
        "the probes run with library warnings still reaching the operator's screen, above the "
        "table doctor is about to print")
    assert logging.getLogger("openfactory").level == before, (
        "doctor left the logger quieted for the rest of the process — a diagnostic may own its "
        "own screen, never everybody else's")


def test_the_third_declaration_is_documented_with_its_SHAPE():
    """"That line is yours to commit" was the whole documentation of a step the operator had to
    perform (2026-08-14): §9 said WHOSE it was and never what it looked like or where it went,
    and the reference page that carried the shape lives behind a link nobody follows mid-flow.
    He asked the right question — *"where in the documentation is this step, asking me to do it and how?"* — and it was in neither of the two places he would have looked."""
    onboarding = Path(__file__).resolve().parents[1] / "docs" / "ONBOARDING.md"
    text = onboarding.read_text()

    assert "docs_repo: <owner>/<product>-context" in text, (
        "the third declaration is still described without showing the line to write")
    where = text[text.index("docs_repo: <owner>"):][:400]
    assert "top level" in where, "the line is shown without saying where in the file it goes"
    assert "client-isolation breach" in text or "isolation" in where, (
        "the reason it is not written FOR you is unstated, which makes it read as an omission")
