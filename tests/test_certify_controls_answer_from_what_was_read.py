"""Each certify control answers from what the deployment says about itself, and an answer nothing
could read is `unknown` — never `pass` (#356).

`controls.evaluate` is pure: it takes a `Reading` and returns one answer per control. So every
branch is exercised here with no registry, no Docker and no network — pass, fail, `unknown` and
`n/a` for each control, and the profile table that decides which are required. The three controls
that read the forge have their own file, `test_certify_reads_the_forge.py`.
"""

from __future__ import annotations

import pytest

from openfactory.adapters.forge.base import BranchProtection
from openfactory.certify import controls as c
from openfactory.contracts import Manifest

#: A branch every fact of C-BRANCH holds for, as a forge row reads one.
PROTECTED = BranchProtection(pr_required=True, linear_history=True, force_push_blocked=True,
                             auto_merge_enabled=True)


class Names(c.Pseudonyms):
    def project(self, name: str) -> str:
        return f"P({name})"

    def repository(self, identity: str) -> str:
        return f"R({identity})"


def _manifest(**over) -> Manifest:
    data = {"version": 1, "validate": {"test": "pytest -q"},
            "post_merge_deploy": {"workflow": "deploy.yml"}}
    data.update(over)
    return Manifest(**data)


def _repo(manifest=None, **over) -> c.RepositoryReading:
    base = dict(project="p", identity="o/r", default=True, key="p",
                manifest=manifest if manifest is not None else _manifest(),
                box={"valid": True, "state": "valid"}, protection=PROTECTED)
    base.update(over)
    return c.RepositoryReading(**base)


def _doctor(*red: str) -> dict:
    checks = [{"id": i, "result": "fail" if i in red else "ok"}
              for i in ("docker", "post_merge", "forge_access")]
    return {"ok": not red, "checks": checks}


def _project(*repos, **over) -> c.ProjectReading:
    base = dict(name="p", forge_credential="minted", forge_mints=True, box_env_declared=True,
                box_env_names=1, repositories=list(repos) or [_repo()], doctor=_doctor(),
                permissions=frozenset({"contents:write"}),
                ci_permissions=frozenset({"workflows:write"}))
    base.update(over)
    return c.ProjectReading(**base)


def _reading(**over) -> c.Reading:
    base = dict(version="0.6.0", build=("", ""), env={"OPENFACTORY_PANEL_TOKEN": "t"},
                env_file=c.EnvFileReading(".env.compose", True, 0o600, False),
                sandbox="container", identity="local", providers={}, projects=[_project()],
                floor_protected=(".openfactory/**",), approvers=["ana"],
                releases=["v0.6.0", "v0.5.1"])
    base.update(over)
    return c.Reading(**base)


def _answer(control: str, reading: c.Reading, profile: str = "standard") -> c.Control:
    return {x.id: x for x in c.evaluate(reading, profile, Names())}[control]


# ── the profile table ───────────────────────────────────────────────────────────────────────────

def test_every_profile_requires_the_security_controls_and_the_per_pack_thresholds():
    for profile, required in c.PROFILES.items():
        assert set(c.SECURITY_CONTROLS) | set(c.EVERY_PACK) <= required, profile


def test_light_requires_only_those_and_the_others_require_every_control():
    assert c.PROFILES["light"] == set(c.SECURITY_CONTROLS) | set(c.EVERY_PACK)
    assert c.PROFILES["standard"] == c.PROFILES["enterprise"] == set(c.CONTROL_IDS)


def test_a_control_the_profile_does_not_require_reads_n_a_and_says_why():
    answers = {x.id: x for x in c.evaluate(_reading(), "light", Names())}

    assert answers["C-TEST"].result == "n/a" and answers["C-TEST"].required is False
    assert "light" in answers["C-TEST"].detail
    assert answers["C-PANEL"].required is True
    assert [x.id for x in c.evaluate(_reading(), "light", Names())] == list(c.CONTROL_IDS)


def test_a_healthy_reading_passes_every_control():
    answers = {x.id: x.result for x in c.evaluate(_reading(), "standard", Names())}

    assert answers == {**{k: "pass" for k in c.CONTROL_IDS}, "C-RISK": "n/a",
                       "C-APPROVERS": "n/a"}


@pytest.mark.parametrize("profile", sorted(c.PROFILES))
def test_a_forge_read_nobody_could_make_never_passes(profile):
    """The forge's protection, the credential's grants and the releases list, each unread: the
    controls built on them say `unknown` (or `n/a` where the profile does not ask), never `pass`."""
    unread = _reading(projects=[_project(_repo(protection=None), permissions=None)],
                      releases=None)

    for control in ("C-WORKFLOWS", "C-BRANCH", "C-VERSION"):
        assert _answer(control, unread, profile).result in ("unknown", "n/a"), control


def test_many_answers_never_combine_into_a_pass_over_something_unread():
    assert c.combined(["pass", "unknown", "pass"]) == "unknown"
    assert c.combined(["pass", "unknown", "fail"]) == "fail"
    assert c.combined(["n/a", "pass"]) == "pass"
    assert c.combined([]) == "n/a"


# ── one control at a time ───────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("env,result", [
    ({"OPENFACTORY_IDENTITY": "oidc"}, "pass"),
    ({"OPENFACTORY_PANEL_TOKENS": "a:b:c"}, "pass"),
    ({"OPENFACTORY_PANEL_TOKEN": "   "}, "fail"),
    ({}, "fail"),
])
def test_the_panel(env, result):
    assert _answer("C-PANEL", _reading(env=env)).result == result


@pytest.mark.parametrize("env_file,result", [
    (c.EnvFileReading(".env.compose", True, 0o600, False), "pass"),
    (c.EnvFileReading(".env.compose", True, 0o644, False), "fail"),
    (c.EnvFileReading(".env.compose", True, 0o600, True), "fail"),
    (c.EnvFileReading(".env.compose", True, 0o600, None), "unknown"),
    (c.EnvFileReading("", False), "unknown"),
])
def test_the_secrets_file(env_file, result):
    assert _answer("C-ENVFILE", _reading(env_file=env_file)).result == result


@pytest.mark.parametrize("credential,mints,result", [
    ("minted", True, "pass"), ("identity", True, "pass"), ("generic", True, "fail"),
    ("login", False, "fail"), ("none", True, "fail"),
    ("stored", True, "fail"), ("stored", False, "pass"), ("unread", False, "unknown"),
])
def test_the_forge_credential(credential, mints, result):
    """ONE RULE FOR EVERY FORGE: minted per use passes; a stored secret passes only where the
    vendor offers nothing to mint (a PAT on a vendor with no App); the deployment's generic token
    and a person's login fail; an unread source is `unknown`."""
    reading = _reading(projects=[_project(forge_credential=credential, forge_mints=mints)])

    assert _answer("C-FORGE-CRED", reading).result == result


def test_the_box_allow_list():
    assert _answer("C-BOX-ENV", _reading(projects=[_project(box_env_declared=False)])).result \
        == "fail"
    assert _answer("C-BOX-ENV", _reading(sandbox="worktree")).result == "fail"


def test_an_unread_manifest_is_unknown_for_every_control_that_reads_one():
    reading = _reading(projects=[_project(_repo(manifest=None))])
    reading.projects[0].repositories[0].manifest = None

    for control in ("C-TEST", "C-SECURITY", "C-MERGE", "C-RISK", "C-POSTMERGE", "C-APPROVERS"):
        assert _answer(control, reading).result == "unknown", control


def test_the_test_gate():
    reading = _reading(projects=[_project(_repo(_manifest(validate={"lint": "ruff check ."})))])

    assert _answer("C-TEST", reading).result == "fail"
    assert _answer("C-SECURITY", reading).result == "pass", "the floor's gate is inherited"


def test_risk():
    high = _manifest(components={"pay": {"path": "pay/**", "stack": "python", "risk": "high"}})
    plain = _manifest(components={"web": {"path": "web/**", "stack": "node"}})

    assert _answer("C-RISK", _reading(projects=[_project(_repo(high))])).result == "pass"
    assert _answer("C-RISK", _reading(projects=[_project(_repo(plain))])).result == "fail"
    assert _answer("C-RISK", _reading()).result == "n/a"


def test_the_protected_paths():
    assert _answer("C-PROTECT", _reading(floor_protected=None)).result == "fail"
    assert _answer("C-PROTECT", _reading(floor_protected=("compose.yaml",))).result == "fail"


@pytest.mark.parametrize("value,result", [("", "pass"), ("1", "pass"), ("3", "info"),
                                          ("0", "info")])
def test_concurrency(value, result):
    env = {"OPENFACTORY_PANEL_TOKEN": "t", "OPENFACTORY_MAX_CONCURRENT_JOBS": value}

    assert _answer("C-CONCURRENCY", _reading(env=env)).result == result


@pytest.mark.parametrize("value,result", [("", "pass"), ("30", "pass"), ("90", "pass"),
                                          ("7", "fail"), ("thirty", "unknown")])
def test_retention(value, result):
    env = {"OPENFACTORY_PANEL_TOKEN": "t", "OPENFACTORY_ENGINE_RETENTION_DAYS": value}

    assert _answer("C-RETENTION", _reading(env=env)).result == result


def test_post_merge():
    undeclared = _reading(projects=[_project(_repo(_manifest(post_merge_deploy=None)))])
    red = _reading(projects=[_project(doctor=_doctor("post_merge"))])
    unread = _reading(projects=[_project(doctor=None)])

    assert _answer("C-POSTMERGE", undeclared).result == "fail"
    assert _answer("C-POSTMERGE", red).result == "fail"
    assert _answer("C-POSTMERGE", unread).result == "unknown"


def test_approvers():
    gated = _manifest(environments={"prod": {"health_url": "https://h"}}, promote=["prod"],
                      prod_approvers=["ana"])
    nobody = _manifest(environments={"prod": {"health_url": "https://h"}}, promote=["prod"])

    assert _answer("C-APPROVERS", _reading(projects=[_project(_repo(gated))])).result == "pass"
    assert _answer("C-APPROVERS", _reading(projects=[_project(_repo(nobody))])).result == "fail"
    assert _answer("C-APPROVERS", _reading(projects=[_project(_repo(gated))],
                                           approvers=["bia"])).result == "fail"
    assert _answer("C-APPROVERS", _reading(projects=[_project(_repo(gated))],
                                           approvers=None)).result == "unknown"


def test_proofs():
    expired = _reading(projects=[_project(_repo(box={"valid": False, "state": "expired"}))])
    unread = _reading(projects=[_project(_repo(box=None))])

    assert _answer("C-PROOF", expired).result == "fail"
    assert _answer("C-PROOF", unread).result == "unknown"


def test_the_doctor():
    assert _answer("C-DOCTOR", _reading(projects=[_project(doctor=_doctor("docker"))])).result \
        == "fail"
    assert _answer("C-DOCTOR", _reading(projects=[_project(doctor=None)])).result == "unknown"


def test_nothing_registered_is_unknown_never_a_pass():
    empty = _reading(projects=[])

    for control in ("C-FORGE-CRED", "C-BOX-ENV", "C-TEST", "C-PROOF", "C-DOCTOR"):
        assert _answer(control, empty).result == "unknown", control


# ── the credential's class comes from the platform's own resolution ─────────────────────────────

_APP = {"OPENFACTORY_GH_APP_ID": "1", "OPENFACTORY_GH_APP_INSTALLATION_ID": "2",
        "OPENFACTORY_GH_APP_KEY_CONTENT": "k"}


@pytest.mark.parametrize("kind,repo,env,expected", [
    ("github", "o/r", {}, ("none", True)),
    ("github", "o/r", _APP, ("minted", True)),
    ("github", "o/r", {**_APP, "OPENFACTORY_BOT_TOKEN": "t"}, ("generic", True)),
    ("azure_devops", "Proj/r", {"AZURE_DEVOPS_PAT": "p"}, ("stored", False)),
], ids=["nothing", "an-app", "an-app-and-the-generic-token", "a-pat-where-nothing-mints"])
def test_the_credential_is_what_a_job_would_be_handed(monkeypatch, kind, repo, env, expected):
    """ASKED OF `credentials.forge_credential_source`, the resolution the doctor and the jobs use
    — so where the generic token and a minted credential are both set, the pack reports the one a
    job is actually handed (the generic token comes first), not the better one beside it."""
    from openfactory.certify import pack
    from openfactory.contracts.project import Project, ProviderRef

    for name in (*_APP, "OPENFACTORY_BOT_TOKEN", "OPENFACTORY_FORGE_TOKEN", "AZURE_DEVOPS_PAT"):
        monkeypatch.delenv(name, raising=False)
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    row = Project(name="p", repo_path="/x",
                  tracker=ProviderRef(kind=kind, repo=repo, options={"organization": "org"}))

    assert pack._forge_credential(row) == expected
