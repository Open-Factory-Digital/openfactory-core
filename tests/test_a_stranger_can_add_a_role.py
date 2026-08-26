"""A stranger adds a ROLE without editing a file of ours — the role axis is an axis.

The doctrine (2026-08-24): the public repository is the core, and agents around it — the
consultancy's QA agent is the owner's own example — must be addable without editing core. Measured
before this file existed: `harness_kind`, `model_for` and `build_asker(project, role="qa")` all
raised `unknown role 'qa'` from a dict literal; `set-model --role qa` refused; the panel cockpit
iterated the literal; `role_prompt("qa")` returned "" and warned that the INSTALLATION was broken.
The harness axis in the same file was plug-in-able and the role axis beside it was not.

THE TEST IS THE CLAIM, in the style of `test_a_stranger_can_add_an_adapter.py`: every assertion
drives the REAL resolvers, the REAL project registry and the REAL panel function with a `role.qa`
entry point that exists only for the duration of the test. No file of ours edited.

What the axis deliberately does NOT do is also pinned here: an unregistered name still raises and
names what is installed; a shipped role wins a collision and the attempt is logged; a spec that is
partly wrong resolves nowhere rather than partly.

The second round (2026-08-25, after review) pins the fact the first left unmodelled — a verdict
CODE parses gets no language directive, shipped or add-on — and closes what the review's probes
opened: `default` and a shipped phase's name as a role, one variable claimed by two add-ons, and
the platform's namespace claimed by one.

The third round (2026-08-26, after the second review) replaces the one hand table left — the
foreign names the platform reads — with a derivation from the code's own reads, and proves the
derivation is LIVE by planting a read in a scratch tree and watching the reservation grow; the
second review's own survivor (the model slot of the cross-spec clash) is pinned.
"""

from __future__ import annotations

import add_ons
import pytest

from openfactory import environ, plugins
from openfactory.adapters.agent import registry as harnesses
from openfactory.adapters.agent import roles
from openfactory.adapters.agent.roles import RoleSpec
from openfactory.contracts.project import Project

QA_PROMPT = "# Role: QA\n\nRead the diff and the acceptance criteria; say what is not covered."


def qa_spec(**overrides) -> RoleSpec:
    base = dict(name="qa", prompt=QA_PROMPT, harness_env="ACME_QA_HARNESS",
                model_env="ACME_QA_MODEL", human_facing=True)
    return RoleSpec(**{**base, **overrides})


class _Point:
    """One entry point, as `importlib.metadata` hands them over."""

    def __init__(self, name, value):
        self.name, self._value = name, value

    def load(self):
        if isinstance(self._value, Exception):
            raise self._value
        return self._value


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    """The env overrides outrank the registry by design, so a leaked variable would make an
    assertion pass for the wrong reason; and the once-per-role log caches would let a refusal
    logged by an earlier test satisfy a later one."""
    for var in (*harnesses.ROLES.values(), *harnesses.ROLE_MODELS.values(),
                "ACME_QA_HARNESS", "ACME_QA_MODEL", "ACME_TL_HARNESS", "ACME_TL_MODEL",
                "ACME_SEC_HARNESS", "ACME_SEC_MODEL"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setattr(harnesses, "_REFUSED_SAID", set())
    monkeypatch.setattr(roles, "_MISSING_SAID", set())


@pytest.fixture
def installs(monkeypatch):
    """Install add-ons for the duration of one test, the way a `pip install` would — patched at
    `importlib.metadata.entry_points`, because the claim is about the packaging mechanism."""
    def _install(*points):
        plugins.reset_cache()
        monkeypatch.setattr("importlib.metadata.entry_points",
                            lambda group=None: list(points) if group == plugins.GROUP else [])
        plugins.reset_cache()
    yield _install
    plugins.reset_cache()


def _project(**kw) -> Project:
    return Project(name="p", repo_path="/tmp/p", **kw)


# ── the claim: the role resolves like a shipped one ─────────────────────────────────────────────

def test_a_stranger_s_role_RESOLVES_its_harness_its_model_and_its_prompt(installs):
    installs(_Point("role.qa", qa_spec))
    assert "qa" not in harnesses.ROLES, "the fixture collided with a real row"
    p = _project(harness={"qa": "codex", "executor": "claude_code"}, model={"qa": "qa-large"})

    assert "qa" in harnesses.known_roles()
    assert harnesses.harness_kind(p, "qa") == "codex"
    assert harnesses.model_for(p, "qa") == "qa-large"
    assert roles.role_prompt("qa") == QA_PROMPT
    # and the shipped roles are untouched by the add-on's presence
    assert harnesses.harness_kind(p, "executor") == "claude_code"
    assert harnesses.model_for(p, "executor") is None


def test_the_add_on_s_OWN_env_names_override_like_a_shipped_role_s(installs, monkeypatch):
    """Explicit names, declared by the add-on — never `OPENFACTORY_HARNESS_<ROLE>` derived from the
    role name, which would land on `OPENFACTORY_HARNESS_ENDPOINT` for a role called `endpoint`."""
    installs(_Point("role.qa", qa_spec))
    p = _project(harness={"qa": "codex"}, model={"qa": "qa-large"})

    monkeypatch.setenv("ACME_QA_HARNESS", "kimi")
    monkeypatch.setenv("ACME_QA_MODEL", "qa-cheap")
    assert harnesses.harness_kind(p, "qa") == "kimi"
    assert harnesses.model_for(p, "qa") == "qa-cheap"


def test_the_add_on_s_default_harness_is_honoured_when_nothing_names_one(installs):
    installs(_Point("role.qa", lambda: qa_spec(harness="opencode")))
    p = _project()

    assert harnesses.harness_kind(p, "qa") == "opencode"
    assert harnesses.harness_kind(p, "executor") == harnesses.DEFAULT_KIND
    # `harness: <one string>` still covers every role, add-on included
    assert harnesses.harness_kind(_project(harness="codex"), "qa") == "codex"


def test_build_asker_BUILDS_the_add_on_role_on_the_harness_the_project_names(installs):
    """The whole path, through the real `_judging`: the add-on that ships the role is the thing
    that calls `build_asker(project, role="qa")`, so this is the seam it depends on. Proven with a
    plugin HARNESS too, so the sentence "zero core edits" covers both axes at once."""
    built = {}

    class _QaEngine:
        def __init__(self, **kw):
            built.update(kw)

        def ask(self, **kw):
            return "answer"

    installs(_Point("role.qa", qa_spec),
             _Point("harness.qa_engine", lambda **kw: _QaEngine(**kw)))
    p = _project(harness={"qa": "qa_engine"}, model={"qa": "qa-large"}, language="pt-BR")

    agent = harnesses.build_asker(p, role="qa")

    assert isinstance(agent, _QaEngine)
    assert built["model"] == "qa-large", "the add-on role's model never reached its harness"
    assert built["role"] == "qa"
    assert built["language"] == "pt-BR"


def test_the_add_on_prompt_is_not_reported_as_a_broken_installation(installs, caplog):
    """`role_prompt` warns that an empty prompt means an incomplete install. For an add-on that
    sentence would be a lie — and the add-on's prompt is not empty, it is in the spec."""
    installs(_Point("role.qa", qa_spec))

    with caplog.at_level("WARNING"):
        assert roles.role_prompt("qa") == QA_PROMPT

    assert "OPENFACTORY_ROLE_PROMPT_MISSING" not in caplog.text


# ── the two surfaces the first draft would have left unreached ──────────────────────────────────

def test_set_model_ACCEPTS_the_add_on_role_and_a_typo_is_refused_NAMING_it(installs, tmp_path):
    """`registry.py:393` was the CLI path's refusal against dict keys nothing reads; an add-on
    role is a key something reads, so it must pass — and the refusal must list it, or a stranger
    reads "not a role" about the row they just installed."""
    import yaml

    from openfactory.registry import ProjectRegistry

    installs(_Point("role.qa", qa_spec))
    path = tmp_path / "registry.yaml"
    path.write_text(yaml.safe_dump({"projects": {"acme": {"name": "acme",
                                                          "repo_path": "/tmp/acme"}}}))
    reg = ProjectRegistry(path=path)

    reg.set_model("acme", "qa-large", role="qa")
    assert reg.get("acme").model == {"qa": "qa-large"}
    assert harnesses.model_for(reg.get("acme"), "qa") == "qa-large"

    with pytest.raises(ValueError, match=r"'qaa' is not a role.*\bqa\b"):
        reg.set_model("acme", "x", role="qaa")


def test_set_model_still_refuses_a_role_nobody_installed(tmp_path, installs):
    import yaml

    from openfactory.registry import ProjectRegistry

    installs()
    path = tmp_path / "registry.yaml"
    path.write_text(yaml.safe_dump({"projects": {"acme": {"name": "acme",
                                                          "repo_path": "/tmp/acme"}}}))
    with pytest.raises(ValueError, match="'qa' is not a role"):
        ProjectRegistry(path=path).set_model("acme", "x", role="qa")


def test_the_panel_cockpit_LISTS_the_add_on_role_s_axes(installs, monkeypatch):
    """`api/app.py` iterated the shipped table, so the one surface ADR-0038 calls the reference
    would have shown a deployment four roles while its registry configured five."""
    from openfactory.api.app import _axes

    installs(_Point("role.qa", qa_spec))
    project = _project(harness={"qa": "codex"}, model={"qa": "qa-large", "executor": "big-1"})
    monkeypatch.setattr("openfactory.registry.ProjectRegistry.get", lambda self, name: project)

    label, models, _route = _axes("p")

    assert models["qa"] == "qa-large"
    assert models["executor"] == "big-1"
    assert set(models) == set(harnesses.known_roles())
    assert "qa:" in label, "a mixed deployment names each role's harness, the add-on's included"


# ── what stays closed ───────────────────────────────────────────────────────────────────────────

def test_an_UNREGISTERED_role_still_raises_and_the_refusal_names_what_is_installed(installs):
    """The house rule, unchanged: a typo must never resolve silently. And the list it names has
    to carry the stranger's own row, or the error says the platform does not support what they
    just installed."""
    installs(_Point("role.qa", qa_spec))
    p = _project(harness={"qaa": "codex"})

    for resolve in (harnesses.harness_kind, harnesses.model_for):
        with pytest.raises(ValueError, match=r"unknown role 'qaa'.*\bqa\b"):
            resolve(p, "qaa")
    with pytest.raises(ValueError, match=r"unknown role 'qaa'.*\bqa\b"):
        harnesses.build_asker(p, role="qaa")


def test_with_nothing_installed_the_four_shipped_roles_are_the_whole_list(installs):
    installs()
    assert harnesses.known_roles() == sorted(harnesses.ROLES)
    with pytest.raises(ValueError, match="unknown role 'qa'"):
        harnesses.harness_kind(_project(), "qa")
    assert harnesses.addon_role("qa") is None


def test_a_shipped_role_WINS_a_collision_and_the_attempt_is_logged(installs, monkeypatch, caplog):
    """An add-on that could hand `techlead` a different prompt, or point it at its own env var,
    would change what the tech-lead means for every project on the deployment — from a package
    somebody installed for something else. Asserted on WHICH CODE ANSWERS, not on a flag."""
    installs(_Point("role.techlead", lambda: qa_spec(
        name="techlead", prompt="HIJACKED", harness_env="ACME_TL_HARNESS",
        model_env="ACME_TL_MODEL")))
    monkeypatch.setenv("ACME_TL_HARNESS", "kimi")

    with caplog.at_level("WARNING"):
        assert "HIJACKED" not in roles.role_prompt("techlead")
        assert roles.role_prompt("techlead").strip(), "the shipped prompt itself vanished"
        assert harnesses.harness_kind(_project(), "techlead") == harnesses.DEFAULT_KIND
        assert harnesses.addon_role("techlead") is None

    assert any("techlead" in r.getMessage() and "built-ins win" in r.getMessage()
               for r in caplog.records), caplog.text


def test_a_shipped_PROMPT_name_is_refused_too(installs, caplog):
    """`sizer`, `planner`, `coordinator`, `recovery` are prompt files rather than config rows, so
    the generic collision check does not see them — but `role_prompt` reads the file first, and
    an add-on `role.sizer` would resolve a harness while its own prompt was silently ignored."""
    installs(_Point("role.sizer", lambda: qa_spec(name="sizer")))

    with caplog.at_level("WARNING"):
        with pytest.raises(ValueError, match="unknown role 'sizer'"):
            harnesses.harness_kind(_project(), "sizer")

    assert any("sizer" in r.getMessage() and "built-ins win" in r.getMessage()
               for r in caplog.records), caplog.text


@pytest.mark.parametrize(("label", "name", "builder", "reason"), [
    ("not a RoleSpec", "qa", lambda: {"name": "qa"}, "not a RoleSpec"),
    ("names itself differently", "qa", lambda: qa_spec(name="tester"), "the spec says 'tester'"),
    ("claims a shipped harness override", "qa",
     lambda: qa_spec(harness_env="OPENFACTORY_HARNESS_EXECUTOR"), "own configuration namespace"),
    ("claims a shipped model override", "qa",
     lambda: qa_spec(model_env="OPENFACTORY_TECHLEAD_MODEL"), "own configuration namespace"),
    ("claims the auth-route override", "qa",
     lambda: qa_spec(harness_env="OPENFACTORY_HARNESS_ENDPOINT"), "own configuration namespace"),
    ("claims the planner model every adapter reads", "qa",
     lambda: qa_spec(model_env="OPENFACTORY_PLANNER_MODEL"), "own configuration namespace"),
    # the review's probe (2026-08-25): a variable of OURS that no module reads TODAY was accepted
    # and `model_for` handed its value to the harness — the namespace is reserved, not a list
    ("claims a variable of ours nobody reads yet", "qa",
     lambda: qa_spec(model_env="OPENFACTORY_HOME"), "own configuration namespace"),
    ("claims the old spelling of our namespace", "qa",
     lambda: qa_spec(model_env="SDLC_QA_MODEL"), "old spelling"),
    ("claims a foreign variable the platform reads", "qa",
     lambda: qa_spec(model_env="ANTHROPIC_API_KEY"), "tool this platform drives"),
    # the second review's probes (2026-08-26): names the platform reads through a route's
    # `requires` table and through a default argument — invisible to a scan of literal reads, so
    # a hand table derived from that scan accepted them and `model_for` returned the SECRET
    ("claims a foreign variable read through a table", "qa",
     lambda: qa_spec(model_env="OPENAI_API_KEY"), "tool this platform drives"),
    # `GH_TOKEN`, read through a default argument by the forge that STAYS in the public tree
    # (it was `SLACK_BOT_TOKEN` until the chat connector left with its package, 2026-08-26 —
    # a name only a leaving module reads is nobody's to reserve in the tree it left)
    ("claims a foreign variable read through a default argument", "qa",
     lambda: qa_spec(harness_env="GH_TOKEN"), "tool this platform drives"),
    ("is named after the per-role fallback key", "default",
     lambda: qa_spec(name="default"), "one line mean two things"),
    ("is named after a shipped phase", "size",
     lambda: qa_spec(name="size"), "'size' is a phase this package passes"),
    ("is named after the stem of a shipped phase", "product",
     lambda: qa_spec(name="product"), "built-ins win"),
    ("its builder raises", "qa", lambda: (_ for _ in ()).throw(RuntimeError("no licence")),
     "RuntimeError"),
])
def test_a_spec_that_is_partly_wrong_resolves_NOWHERE_and_says_why(installs, caplog, label,
                                                                    name, builder, reason):
    """Half-honouring a spec is a role that reads a variable meaning something else, or answers to
    a name nobody listed. It is refused whole, the reason is logged by name, and every other role
    is untouched."""
    installs(_Point(f"role.{name}", builder))

    with caplog.at_level("WARNING"):
        assert name not in harnesses.known_roles() or name in harnesses.ROLES, label
        assert harnesses.addon_role(name) is None, label
        if name not in harnesses.ROLES:
            with pytest.raises(ValueError, match=f"unknown role '{name}'"):
                harnesses.harness_kind(_project(), name)

    said = [r.getMessage() for r in caplog.records if f"add-on role '{name}'" in r.getMessage()]
    assert said and reason in said[0], (label, caplog.text)
    assert harnesses.harness_kind(_project(), "executor") == harnesses.DEFAULT_KIND


def _sec_spec(**overrides) -> RoleSpec:
    base = dict(name="sec", prompt="# Role: security review", harness_env="ACME_SEC_HARNESS",
                model_env="ACME_SEC_MODEL", human_facing=True)
    return RoleSpec(**{**base, **overrides})


def test_two_add_ons_claiming_ONE_variable_the_second_is_refused_by_name(installs, caplog,
                                                                         monkeypatch):
    """`RoleSpec` refuses a spec whose two names are the same; ACROSS specs nothing did. The
    review's probe (2026-08-25): `role.qa` and `role.sec` both with `harness_env="SHARED_H"` were
    both accepted and `SHARED_H=kimi` moved both — one exported variable binding two roles — and
    one add-on's model override being another's harness override was accepted too, a harness name
    handed to a model slot. The first claimant keeps the variable; the second is refused by name,
    naming the variable and the role that has it."""
    installs(_Point("role.qa", qa_spec),
             _Point("role.sec", lambda: _sec_spec(harness_env="ACME_QA_HARNESS")))

    with caplog.at_level("WARNING"):
        assert harnesses.known_roles() == sorted([*harnesses.ROLES, "qa"])

    said = [r.getMessage() for r in caplog.records if "add-on role 'sec'" in r.getMessage()]
    assert said and "ACME_QA_HARNESS" in said[0] and "'qa'" in said[0], caplog.text
    monkeypatch.setenv("ACME_QA_HARNESS", "kimi")
    assert harnesses.harness_kind(_project(), "qa") == "kimi"
    with pytest.raises(ValueError, match="unknown role 'sec'"):
        harnesses.harness_kind(_project(), "sec")

    # crosswise: a model slot reading the variable that is another role's harness override
    monkeypatch.setattr(harnesses, "_REFUSED_SAID", set())
    installs(_Point("role.qa", qa_spec),
             _Point("role.sec", lambda: _sec_spec(model_env="ACME_QA_HARNESS")))
    with caplog.at_level("WARNING"):
        assert "sec" not in harnesses.known_roles()
    assert any("add-on role 'sec'" in r.getMessage() and "ACME_QA_HARNESS" in r.getMessage()
               for r in caplog.records), caplog.text

    # the twin: two add-ons with their own variables both resolve, each on its own override
    installs(_Point("role.qa", qa_spec), _Point("role.sec", _sec_spec))
    monkeypatch.setenv("ACME_SEC_HARNESS", "opencode")
    assert {"qa", "sec"} <= set(harnesses.known_roles())
    assert harnesses.harness_kind(_project(), "qa") == "kimi"
    assert harnesses.harness_kind(_project(), "sec") == "opencode"


def test_two_add_ons_sharing_a_MODEL_override_the_second_is_refused_by_name(installs, caplog,
                                                                            monkeypatch):
    """The second review's survivor (2026-08-26): recording only the HARNESS slot in the claimed
    map kept the file green, because the guard above shares a harness override and crosses a
    model slot INTO a harness one, but never shares a model override and never crosses the other
    way. The code handled both; nothing pinned it. Both directions, by name."""
    installs(_Point("role.qa", qa_spec),
             _Point("role.sec", lambda: _sec_spec(model_env="ACME_QA_MODEL")))

    with caplog.at_level("WARNING"):
        assert harnesses.known_roles() == sorted([*harnesses.ROLES, "qa"])

    said = [r.getMessage() for r in caplog.records if "add-on role 'sec'" in r.getMessage()]
    assert said and "ACME_QA_MODEL" in said[0] and "'qa'" in said[0], caplog.text
    monkeypatch.setenv("ACME_QA_MODEL", "tier-x")
    assert harnesses.model_for(_project(), "qa") == "tier-x"
    with pytest.raises(ValueError, match="unknown role 'sec'"):
        harnesses.model_for(_project(), "sec")

    # crosswise: a harness slot reading the variable that is another role's MODEL override — a
    # model tier handed to a harness slot
    monkeypatch.setattr(harnesses, "_REFUSED_SAID", set())
    installs(_Point("role.qa", qa_spec),
             _Point("role.sec", lambda: _sec_spec(harness_env="ACME_QA_MODEL")))
    with caplog.at_level("WARNING"):
        assert "sec" not in harnesses.known_roles()
    assert any("add-on role 'sec'" in r.getMessage() and "ACME_QA_MODEL" in r.getMessage()
               for r in caplog.records), caplog.text
    assert harnesses.model_for(_project(), "qa") == "tier-x"


def test_a_refusal_is_said_ONCE_not_once_per_resolution(installs, caplog):
    """The registry is consulted on every job; a broken add-on saying the same sentence on every
    `harness_kind` call is noise that teaches people to filter the channel."""
    installs(_Point("role.qa", lambda: {"name": "qa"}))

    with caplog.at_level("WARNING"):
        for _ in range(4):
            harnesses.known_roles()

    assert sum("add-on role 'qa'" in r.getMessage() for r in caplog.records) == 1


@pytest.mark.parametrize(("field", "value", "why"), [
    ("prompt", "", "EMPTY prompt"),
    ("prompt", "   \n", "EMPTY prompt"),
    ("name", "QA", "lowercase identifier"),
    ("name", "qa agent", "lowercase identifier"),
    ("harness_env", "acme qa", "environment variable name"),
    ("model_env", "", "environment variable name"),
    # the second review's note (2026-08-26): `HOME` was accepted and `model_for` returned the home
    # directory — the runtime reads it where no scan of ours can see, so the SHAPE refuses it
    ("model_env", "HOME", "carrying its own prefix"),
    ("harness_env", "PATH", "carrying its own prefix"),
    ("model_env", "ACME_QA_HARNESS", "one value cannot name both"),
    ("harness", "", "never ''"),
])
def test_a_role_spec_refuses_what_would_fail_later_and_silently(field, value, why):
    """The positive twin of the refusals above: the value itself will not hold an empty prompt (the
    shape `role_prompt` warns about as a broken INSTALL — a lie for an add-on) or two facts in
    one env name."""
    with pytest.raises(ValueError, match=why):
        qa_spec(**{field: value})


# ── the registry file: an unknown role key is said by name, and the project still loads ─────────

def _registry(tmp_path, **entry):
    import yaml

    from openfactory.registry import ProjectRegistry

    path = tmp_path / "registry.yaml"
    path.write_text(yaml.safe_dump({"projects": {"acme": {"name": "acme",
                                                          "repo_path": "/tmp/acme", **entry}}}))
    return ProjectRegistry(path=path)


def test_a_role_key_nothing_reads_is_WARNED_by_name_and_the_project_still_loads(tmp_path, caplog,
                                                                                installs):
    """`Project` accepts any key under a dict-shaped `harness:`/`model:`, `_configured` reads only
    the keys it is asked for, and no CLI writes a per-role `harness:` — so a hand-edited
    `reviewr:` was the one path with neither a refusal nor a line. Measured: `model: {executr:
    <a client's own endpoint>}` loaded clean and ran the executor on the default provider.

    A WARNING, never a raise: `Registry.list()` raising for one entry stops the poller for every
    project (`test_the_box_image_resolves_in_one_place.py` records `BoxConfig(extra='forbid')`
    doing exactly that)."""
    installs()
    reg = _registry(tmp_path, harness={"reviewr": "codex", "default": "kimi"},
                    model={"qa": "gpt-5", "executor": "big-1"})

    with caplog.at_level("WARNING"):
        loaded = reg.list()

    assert [p.name for p in loaded] == ["acme"], "the project must still load"
    messages = [r.getMessage() for r in caplog.records]
    assert any("'reviewr'" in m and "`harness:`" in m for m in messages), caplog.text
    assert any("'qa'" in m and "`model:`" in m for m in messages), caplog.text
    assert not any("'default'" in m for m in messages), "`default` is a key `_configured` reads"
    assert not any("'executor'" in m for m in messages)
    # and the keys that ARE read take effect, on the loaded object
    assert harnesses.harness_kind(loaded[0], "executor") == "kimi"
    assert harnesses.model_for(loaded[0], "executor") == "big-1"


def test_an_INSTALLED_role_s_key_is_not_a_typo(tmp_path, caplog, installs):
    """The twin in the other direction: the day the add-on is installed, `qa:` is a key something
    reads, and warning about it would send the operator to delete a line that works."""
    installs(_Point("role.qa", qa_spec))
    reg = _registry(tmp_path, model={"qa": "qa-large", "reviewr": "x"})

    with caplog.at_level("WARNING"):
        loaded = reg.list()

    messages = [r.getMessage() for r in caplog.records]
    assert not any("'qa'" in m for m in messages), caplog.text
    assert any("'reviewr'" in m for m in messages), "the typo beside it is still named"
    assert harnesses.model_for(loaded[0], "qa") == "qa-large"


# ── the registry asks the loader for THIS axis ──────────────────────────────────────────────────

def test_the_harness_registry_ASKS_the_loader_for_the_role_axis():
    """Mirrors `test_every_axis_CONSULTS_the_loader`: the axis name is what joins an entry point
    to a registry, and a typo there is silent. Read off the call, not off a substring."""
    import ast
    import pathlib

    src = pathlib.Path(harnesses.__file__).read_text()
    calls = [n for n in ast.walk(ast.parse(src))
             if isinstance(n, ast.Call) and getattr(n.func, "attr", "") == "builder"
             and getattr(n.func.value, "id", "") == "plugins"]
    axes_asked = {a.value for c in calls for a in c.args if isinstance(a, ast.Constant)}

    assert "role" in axes_asked, (
        f"adapters/agent/registry.py asks the loader for {sorted(axes_asked)}, not `role`")


# ── language: ONE rule for four harnesses — not the coding path, not a verdict code parses, ─────
# ── everything else, an unknown phase included ─────────────────────────────────────────────────

def _adapters(language="pt-BR"):
    """Every shipped harness, built through the registry's own builders — parametrised over the
    table rather than hand-listed, so a fifth harness cannot join with an allowlist of its own."""
    return {kind: build(language=language) for kind, build in harnesses.HARNESSES.items()}


class _Box:
    """A sandbox double: the harness is on the PATH by its bare name, every command exits 0
    with no output — enough for `ask()` to run to its end without a CLI."""

    def harness_path(self, name: str) -> str:
        return name

    def run(self, *, workspace, command: str, timeout: int):  # noqa: ARG002
        return 0, ""


def _prompt_the_harness_receives(adapter, phase: str) -> str:
    """Drive the REAL `ask()` and read the prompt at the CLI seam. Every adapter turns the prompt
    it has localised (or not) into a command through `_cli(prompt, …)` one call before
    `sandbox.run`, so what arrives there is what the harness would have been handed — asserting
    on `_localised` alone would prove the helper and say nothing about whether `ask()` uses it."""
    seen: list[str] = []

    def _cli(prompt, *args, **kwargs):  # noqa: ARG001 — the flags differ per harness
        seen.append(prompt)
        return "true"

    adapter._cli = _cli
    adapter.ask(sandbox=_Box(), workspace=None, prompt="PROMPT", phase=phase)
    assert len(seen) == 1, f"ask({phase!r}) reached the CLI seam {len(seen)} times, not once"
    return seen[0]


@pytest.mark.parametrize("kind", sorted(harnesses.HARNESSES))
def test_a_phase_this_tree_has_never_seen_is_LOCALISED_on_every_harness(kind):
    """Before: `HUMAN_PHASES` was an allowlist, so a QA verdict a person reads on the card
    (`qa_verdict`) shipped in English regardless of `project.language` — on all four adapters,
    measured. And the phase is also the metering label, so a role wanting its own telemetry row
    had to invent one and thereby lose its language. Inverted: the CODING set is closed."""
    from openfactory.adapters.agent.roles import CODING_PHASES, language_directive

    adapter = _adapters()[kind]
    for phase in ("qa_verdict", "qa", "something_nobody_listed"):
        assert phase not in CODING_PHASES and phase not in roles.HUMAN_PHASES
        out = adapter._localised("PROMPT", phase)
        assert out.startswith(language_directive("pt-BR")), (kind, phase)
        assert out.endswith("PROMPT")


@pytest.mark.parametrize("kind", sorted(harnesses.HARNESSES))
def test_the_coding_path_is_byte_identical(kind):
    """The production coding path must not move: an executor's prompt language is a different
    question, and this is the pin that keeps the inversion from changing it."""
    from openfactory.adapters.agent.roles import CODING_PHASES

    adapter = _adapters()[kind]
    for phase in CODING_PHASES:
        assert adapter._localised("PROMPT", phase) == "PROMPT", (kind, phase)


@pytest.mark.parametrize("kind", sorted(harnesses.HARNESSES))
def test_every_catalogued_human_phase_is_still_localised(kind):
    """The positive twin: inverting the set must keep every phase the allowlist used to carry."""
    from openfactory.adapters.agent.roles import language_directive

    adapter = _adapters()[kind]
    for phase in roles.HUMAN_PHASES:
        assert adapter._localised("PROMPT", phase).startswith(language_directive("pt-BR")), (
            kind, phase)


def test_the_coding_set_is_the_phases_the_adapters_really_pass():
    """`CODING_PHASES` is a closed set, and closed sets drift: codex labels its coding runs
    `planner`/`executor` where the others say `plan`/`execute`, and a set that forgot one would
    localise an executor's prompt on one harness only. Read off the adapters' own calls."""
    import ast
    import pathlib

    from openfactory.adapters.agent.roles import CODING_PHASES

    passed: set[str] = set()
    for module in ("claude_code", "codex", "kimi", "opencode"):
        path = pathlib.Path(harnesses.__file__).with_name(f"{module}.py")
        for node in ast.walk(ast.parse(path.read_text())):
            if not (isinstance(node, ast.Call)
                    and getattr(node.func, "attr", "") in ("_invoke", "_run")):
                continue
            for arg in node.args:  # the positional phase/role label
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                    passed.add(arg.value)
            for kw in node.keywords:
                if kw.arg == "phase" and isinstance(kw.value, ast.Constant):
                    passed.add(kw.value.value)
    coding_passed = passed - roles.HUMAN_PHASES
    assert coding_passed, "the scan found no literal phases — the pattern is wrong, not the code"
    assert coding_passed <= CODING_PHASES, (
        f"phases an adapter passes on its coding path that would now be localised: "
        f"{sorted(coding_passed - CODING_PHASES)}")
    assert roles.HUMAN_PHASES.isdisjoint(CODING_PHASES), (
        "a phase in both sets is two facts in one value")


@pytest.mark.parametrize("kind", sorted(harnesses.HARNESSES))
def test_a_verdict_CODE_parses_gets_NO_directive_and_the_answer_a_person_reads_does(kind):
    """The review's blocker (2026-08-25). `product_confirm` (approve / reject / neither) and
    `product_accept` (worked / did-not-work / neither) are one-word verdicts `_verdict_token`
    parses, marked `audience="team"` — never shown to a person. On main they sat outside the
    allowlist; after the inversion they sat in NEITHER set, and all four adapters prepended
    "write in pt-BR" to a prompt demanding an English token: a translated token parses as
    `neither`, so the proposal stays pending and the acceptance stays open, silently, at the
    sign-off gate the product sells. Through the REAL `ask()`, captured at the CLI seam."""
    from openfactory.adapters.agent.roles import MACHINE_PHASES, language_directive

    assert {"product_confirm", "product_accept"} <= MACHINE_PHASES
    adapter = _adapters()[kind]
    directive = language_directive("pt-BR")
    for phase in MACHINE_PHASES:
        received = _prompt_the_harness_receives(adapter, phase)
        # ends with, not equals: a harness may prepend its own read-only sentence (kimi does)
        assert directive not in received and received.endswith("PROMPT"), (kind, phase, received)
    # the twin: the same role's answer a PERSON reads, on the same path, still gets the directive
    received = _prompt_the_harness_receives(adapter, "product_answer")
    assert received.startswith(directive) and received.endswith("PROMPT"), kind


@pytest.mark.parametrize("kind", sorted(harnesses.HARNESSES))
def test_an_add_on_whose_answers_CODE_parses_gets_no_directive_and_one_a_person_reads_does(
        kind, installs):
    """`RoleSpec.human_facing` was a required field nothing in core read — and its natural
    reading is exactly what an add-on with a one-word verdict needs: the closed sets live in
    core, so a stranger's QA verdict had no way to stay un-localised (the blocker, exported).
    Now the flag is read where the directive is decided: a role's phases are its name and
    `<name>_*`, the shipped product role's own convention; any other spelling is nobody's and
    localised, because that is the direction that costs a person nothing."""
    from openfactory.adapters.agent.roles import language_directive, needs_language_directive

    installs(_Point("role.qa", lambda: qa_spec(human_facing=False)))
    adapter = _adapters()[kind]
    directive = language_directive("pt-BR")
    for phase in ("qa", "qa_verdict"):
        assert not needs_language_directive(phase), phase
        received = _prompt_the_harness_receives(adapter, phase)
        assert directive not in received and received.endswith("PROMPT"), (kind, phase, received)
    assert _prompt_the_harness_receives(adapter, "qaverdict").startswith(directive), (
        "a phase not spelled after the role is nobody's")

    installs(_Point("role.qa", lambda: qa_spec(human_facing=True)))
    for phase in ("qa", "qa_verdict"):
        assert needs_language_directive(phase), phase
        assert _prompt_the_harness_receives(adapter, phase).startswith(directive), (kind, phase)


def test_every_phase_the_tree_passes_sits_in_EXACTLY_one_set():
    """The measurement behind the blocker: the guard above walks the four adapter files'
    `_invoke`/`_run` calls and cannot see `product/role.py`, where the two verdict phases are
    passed POSITIONALLY to `_ask`; the older guard in `test_agent_harness.py` regexes the keyword
    form `phase="product_…"`. Both missed them, and a mutation moving them into the closed set
    survived. This walks the WHOLE package — every `phase=` keyword literal on any call, the
    fourth positional of `_ask`/`_invoke`/`_run` (the `(sandbox, workspace, prompt, phase)`
    shape), and a `phase` parameter's default — and requires each literal to sit in exactly one
    of the three sets, so a phase can be neither forgotten nor two things."""
    import ast
    import pathlib

    from openfactory.adapters.agent.roles import CODING_PHASES, HUMAN_PHASES, MACHINE_PHASES

    root = pathlib.Path(harnesses.__file__).parents[2]  # openfactory/
    passed: dict[str, set[str]] = {}

    def _note(lit, path):
        # an empty default (`phase: str = ""` on a command builder) is "no label", not a phase
        if isinstance(lit, ast.Constant) and isinstance(lit.value, str) and lit.value:
            passed.setdefault(lit.value, set()).add(str(path.relative_to(root)))

    for path in sorted(root.rglob("*.py")):
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.Call):
                for kw in node.keywords:
                    if kw.arg == "phase":
                        _note(kw.value, path)
                fn = getattr(node.func, "attr", None) or getattr(node.func, "id", None)
                if fn in ("_ask", "_invoke", "_run") and len(node.args) > 3:
                    _note(node.args[3], path)
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                a = node.args
                # defaults align with the LAST positional parameters, hence reversed and lenient
                positional = list(zip(reversed(a.args), reversed(a.defaults), strict=False))
                keyword_only = [(p, d) for p, d in zip(a.kwonlyargs, a.kw_defaults, strict=True)
                                if d]
                for param, default in (*positional, *keyword_only):
                    if param.arg == "phase":
                        _note(default, path)

    assert len(passed) >= 20, f"the scan found {len(passed)} phases — the pattern is wrong"
    sets = {"CODING_PHASES": CODING_PHASES, "HUMAN_PHASES": HUMAN_PHASES,
            "MACHINE_PHASES": MACHINE_PHASES}
    for phase, where in sorted(passed.items()):
        homes = [name for name, members in sets.items() if phase in members]
        assert len(homes) == 1, (
            f"phase {phase!r} (passed in {sorted(where)}) sits in {homes or 'NO set'}; a phase "
            f"in no set is localised by accident and one in two sets is two facts in one value")
    # what neither older guard could see: the positional verdict phases in product/role.py
    assert {"product_confirm", "product_accept"} <= set(passed), "the positional form is unseen"
    assert "product/role.py" in passed["product_confirm"]


# ── the platform's variables are reserved by NAMESPACE, and the foreign ones are DERIVED ───────

FOREIGN = "tool this platform drives"


@pytest.mark.parametrize(("shape", "name", "source"), [
    ("a literal at the read", "ACME_TOOL_LITERAL_KEY",
     'import os\nKEY = os.environ.get("ACME_TOOL_LITERAL_KEY")\n'),
    ("a subscript at the read", "ACME_TOOL_SUBSCRIPT_KEY",
     'import os\nKEY = os.environ["ACME_TOOL_SUBSCRIPT_KEY"]\n'),
    ("os.getenv", "ACME_TOOL_GETENV_KEY",
     'import os\nKEY = os.getenv("ACME_TOOL_GETENV_KEY")\n'),
    ("an alias of the environment", "ACME_TOOL_ALIAS_KEY",
     'import os\n\ndef read(env=None):\n    e = os.environ if env is None else env\n'
     '    return e.get("ACME_TOOL_ALIAS_KEY")\n'),
    # the second review's first blind spot: a route's `requires` table, read in a loop
    ("a names table a loop reads", "ACME_TOOL_TABLE_KEY",
     'REQUIRES = (("ACME_TOOL_TABLE_KEY", "ACME_TOOL_TABLE_TWIN"),)\n\n'
     'def missing(env):\n    return [g for g in REQUIRES if not any(env.get(n) for n in g)]\n'),
    ("a dict of names", "ACME_TOOL_DICT_KEY",
     'VENDOR_DEFAULT = {"acme": "ACME_TOOL_DICT_KEY"}\n'),
    # the second review's second blind spot: a default handed to the function that reads it
    ("a default handed to a function reading its parameter", "ACME_TOOL_DEFAULT_KEY",
     'import os\n\ndef _resolve(env_name, default):\n'
     '    return os.environ.get(env_name or default)\n\n'
     'TOKEN = _resolve(None, "ACME_TOOL_DEFAULT_KEY")\n'),
    ("a module constant a read names", "ACME_TOOL_CONSTANT_KEY",
     'import os\nTOOL_VAR = "ACME_TOOL_CONSTANT_KEY"\nVALUE = os.environ.get(TOOL_VAR)\n'),
])
def test_the_reservation_GROWS_the_day_a_module_reads_a_new_foreign_name(tmp_path, shape, name,
                                                                         source):
    """The second review's measurement (2026-08-26): the hand table of foreign names was EXACTLY
    the set an AST scan of literal reads could see — so the guard that "kept it complete" could
    never fail, and the six names read through a route's table or a default argument were open
    to an add-on, which handed `OPENAI_API_KEY`'s value to a harness as a model. The reservation
    is now derived from the code (`environ.names_read`), and this is the proof it is live: a
    scratch tree with ONE new read, in each shape a read takes, reserves the name it reads. The
    same name is free in the real package — nobody reads it — which is the twin."""
    assert environ.reserved(name) is None, f"{name} is read by the real package; pick another"
    (tmp_path / "planted.py").write_text(source)

    why = environ.reserved(name, root=tmp_path)

    assert why and FOREIGN in why, (shape, why)
    assert name in environ.names_read(tmp_path), shape


def test_a_name_nobody_reads_is_FREE_and_an_export_list_is_not_a_read(tmp_path):
    """The twin of the growth above, in the same scratch tree: a name the tree never reads stays
    an add-on's to take, and `__all__` — a list of upper-case names that reads nothing — reserves
    nothing, while the one real read beside it does."""
    (tmp_path / "planted.py").write_text(
        '__all__ = ["ACME_EXPORTED_NAME", "ACME_OTHER_EXPORT"]\n'
        'import os\nVALUE = os.environ.get("ACME_REAL_READ")\n')

    assert environ.reserved("ACME_QA_MODEL", root=tmp_path) is None
    assert environ.reserved("ACME_EXPORTED_NAME", root=tmp_path) is None
    assert FOREIGN in (environ.reserved("ACME_REAL_READ", root=tmp_path) or "")
    assert environ.reserved("ACME_QA_MODEL") is None, "the real package reads the fixture's name"


def test_the_names_only_the_chat_package_reads_are_reserved_where_it_is():
    """`SLACK_BOT_TOKEN` and `SLACK_APP_TOKEN` are read by the chat listener alone, which leaves
    the public tree with `openfactory-slack` (2026-08-26): reserved here, where its modules are,
    and nobody's in the tree it left — so this runs where the module is and skips by name where
    it is not, instead of asserting a reservation the public tree cannot make."""
    add_ons.source("openfactory/runtime/slack/bot.py")
    for name in ("SLACK_BOT_TOKEN", "SLACK_APP_TOKEN"):
        assert FOREIGN in (environ.reserved(name) or ""), name


def test_the_names_the_hand_table_could_not_see_are_reserved_in_THIS_tree():
    """The derivation against the real package: the six the second review probed (each read
    through a table or a default argument), a sample of the old table so nothing fell out with
    it, and the platform's own names by prefix — plus a floor on the count, so a scan that finds
    a handful is a broken scan and not a platform that reads little."""
    for name in ("OPENAI_API_KEY", "AZURE_API_KEY", "AZURE_RESOURCE_NAME", "ANTHROPIC_AUTH_TOKEN",
                 "ANTHROPIC_API_KEY", "TEMPORAL_ADDRESS", "AWS_REGION", "GH_TOKEN",
                 "JIRA_API_TOKEN", "AZURE_DEVOPS_PAT"):
        assert FOREIGN in (environ.reserved(name) or ""), name
    for name, why in (("OPENFACTORY_HOME", "own configuration namespace"),
                      ("SDLC_QA_MODEL", "old spelling")):
        assert why in (environ.reserved(name) or ""), name
    read = environ.names_read()
    assert len(read) > 100, f"the scan found {len(read)} names — the shapes, not the code, are wrong"


def test_an_installation_with_NO_sources_REFUSES_rather_than_reserving_nothing(tmp_path, installs,
                                                                               caplog, monkeypatch):
    """A derivation has a failure mode a table does not: nothing to derive from. An install that
    ships no readable sources would reserve no foreign name at all, which reads as "every name is
    free" — absence as compliance. It says so instead, and the registry refuses the add-on for
    that reason by name; every shipped role still resolves from its tables."""
    empty = tmp_path / "empty"
    empty.mkdir()
    why = environ.reserved("ACME_QA_MODEL", root=empty)
    assert why and "no readable sources" in why

    monkeypatch.setattr(environ, "names_read", lambda root=None: frozenset())
    installs(_Point("role.qa", qa_spec))
    with caplog.at_level("WARNING"):
        assert "qa" not in harnesses.known_roles()
    assert any("add-on role 'qa'" in r.getMessage() and "no readable sources" in r.getMessage()
               for r in caplog.records), caplog.text
    assert harnesses.harness_kind(_project(), "executor") == harnesses.DEFAULT_KIND
