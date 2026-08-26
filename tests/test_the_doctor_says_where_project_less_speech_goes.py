"""`openfactory doctor` prints where project-less speech goes — one line, derived, vendor-neutral.

THE SILENT REGRESSION (review of the chat cut, 2026-08-26). The deployment-wide fallback notifier
stopped switching itself on from a fallback row's own two variables and became a DECLARATION
(`OPENFACTORY_NOTIFIER_FALLBACK=<kind>`). Correct — the core no longer reads a vendor's variables
to decide a vendor was wanted — and, measured: a deployment that set the old switch and nothing
else now gets `NullNotifier` from `build_notifier(None)` while the `openfactory.notify` logger
emits ZERO lines. Two variables present and unread, and nothing anywhere says so, because from
the registry's point of view nothing is wrong.

So the deployment gets read out where the deployment IS read — `openfactory doctor` — as one line
that says what the fallback is, and, when a notifier kind is installed and not declared, the
exact line to add. The doctor asks the notifier registry and the plugin loader what is installed;
it imports no package and names no vendor. Four states, each asserted on the state the registry
answers AND on the sentence the doctor prints, plus the CLI reaching it.
"""

from __future__ import annotations

import ast
import pathlib

import add_ons
import pytest
import stranger_addon
from typer.testing import CliRunner
from vendor_addons import Point, install

from openfactory import doctor, plugins
from openfactory.adapters.notify.registry import (
    FALLBACK_ENV,
    CannotPost,
    FallbackState,
    build_notifier,
    fallback_state,
)
from openfactory.doctor import notifier_fallback_line

ROOT = pathlib.Path(__file__).resolve().parents[1]


@pytest.fixture
def stranger(tmp_path, monkeypatch):
    """A real distribution on `sys.path` declaring `notifier.acme` — nothing of ours patched."""
    return stranger_addon.installed(tmp_path, monkeypatch)


@pytest.fixture
def panel_only(monkeypatch):
    """The public core as shipped: no add-on row on any axis."""
    install(monkeypatch, declared_rows=False)


class _Silent:
    """A row that answers `CannotPost` naming the ONE variable it lacks — and declares that
    variable as what it reads, so a deployment could fill it: a candidate."""

    def load(self):
        def build(project):
            return CannotPost(missing=("the ACME_PAGER_KEY environment variable",))
        build.environment = ("ACME_PAGER_KEY",)
        return build

    name = "notifier.pager"


class _ProjectBound:
    """A row whose project-less answer names a PROJECT field beside its variable — the shape of
    a per-project chat row: no variable a deployment sets makes it post for nobody's project."""

    def load(self):
        def build(project):
            return CannotPost(missing=("the ACME_ROUTE_KEY environment variable",
                                       "the project's route"))
        build.environment = ("ACME_ROUTE_KEY",)
        return build

    name = "notifier.route"


class _Undeclared:
    """A row that answers `CannotPost` and declares nothing about what it reads."""

    def load(self):
        return lambda project: CannotPost(missing=("ACME_X_KEY",))

    name = "notifier.mute"


# ── the state, as the registry answers it ───────────────────────────────────────────────────────

def test_declared_and_installed_is_implemented_and_can_post(stranger, monkeypatch):
    monkeypatch.setenv(FALLBACK_ENV, "acme")
    assert fallback_state() == FallbackState("acme", True, "", ("acme",))


def test_installed_and_not_declared_is_a_candidate(stranger, monkeypatch):
    """THE regression's shape: a row is installed, nothing declares it, the project-less caller
    gets nothing — and the state says which kind is standing there unused."""
    monkeypatch.delenv(FALLBACK_ENV, raising=False)
    assert fallback_state() == FallbackState("", False, "", ("acme",))
    assert type(build_notifier(None)).__name__ == "NullNotifier"


def test_the_panel_only_core_has_no_candidate(panel_only, monkeypatch):
    monkeypatch.delenv(FALLBACK_ENV, raising=False)
    assert fallback_state() == FallbackState("", False, "", ())


def test_declared_but_uninstalled_is_not_implemented(panel_only, monkeypatch):
    monkeypatch.setenv(FALLBACK_ENV, "telegram")
    assert fallback_state() == FallbackState("telegram", False, "", ())


def test_a_declared_row_that_cannot_post_says_what_it_lacked(monkeypatch):
    install(monkeypatch, declared_rows=False, extra=(_Silent(),))
    monkeypatch.setenv(FALLBACK_ENV, "pager")
    assert fallback_state() == FallbackState(
        "pager", True, "the ACME_PAGER_KEY environment variable", ("pager",))


# ── offered only when a project-less caller could use it ────────────────────────────────────────

def test_a_row_lacking_only_its_own_variables_is_offered(monkeypatch):
    install(monkeypatch, declared_rows=False, extra=(_Silent(),))
    monkeypatch.delenv(FALLBACK_ENV, raising=False)
    assert fallback_state() == FallbackState("", False, "", ("pager",), ())


def test_a_row_a_project_less_caller_can_never_use_is_held_back_with_what_it_needs(monkeypatch):
    """THE REVIEWER'S PROBE (2026-08-26): with the chat package installed and nothing declared,
    the doctor offered `<one of slack, telegram>` — and the per-project row answers "the
    project's channel_id" to a project-less caller, so declaring it can never post. An offered
    option must be executable: the row is held back, and what it would still need is said."""
    install(monkeypatch, declared_rows=False, extra=(_ProjectBound(), _Silent()))
    monkeypatch.delenv(FALLBACK_ENV, raising=False)
    state = fallback_state()
    assert state.installed == ("pager",)
    assert state.unserviceable == (("route", "the project's route"),)
    monkeypatch.setenv(FALLBACK_ENV, "route")
    assert "the project's route" in fallback_state().cannot_post


def test_a_row_that_declares_nothing_is_held_back_with_everything_it_lacked(monkeypatch):
    install(monkeypatch, declared_rows=False, extra=(_Undeclared(),))
    monkeypatch.delenv(FALLBACK_ENV, raising=False)
    assert fallback_state() == FallbackState("", False, "", (), (("mute", "ACME_X_KEY"),))


# ── the line, on a case table ───────────────────────────────────────────────────────────────────

CASES = [
    (FallbackState("acme", True, "", ("acme",)),
     ["notifier fallback: acme", "project-less"], ["declare ", "nowhere"]),
    (FallbackState("acme", True, "ACME_PAGER_KEY", ("acme",)),
     ["notifier fallback: acme is declared but cannot post", "ACME_PAGER_KEY", "go nowhere"],
     ["declare "]),
    (FallbackState("telegram", False, "", ()),
     ["notifier fallback: telegram is declared and no notifier row implements it",
      "known: panel", plugins.install_hint("notifier", "telegram"), "go nowhere"], ["declare "]),
    (FallbackState("", False, "", ()),
     ["notifier fallback: none declared", "project-less notifications go nowhere"],
     ["declare ", FALLBACK_ENV, "installed"]),
    (FallbackState("", False, "", ("acme",)),
     ["notifier fallback: none declared", "go nowhere",
      "acme is installed and is not the fallback",
      f"declare {FALLBACK_ENV}=acme to route project-less notifications there"], []),
    (FallbackState("", False, "", ("acme", "pager")),
     ["acme, pager are installed and none is the fallback",
      f"declare {FALLBACK_ENV}=<one of acme, pager>"], []),
    (FallbackState("", False, "", (), (("route", "the project's route"),)),
     ["notifier fallback: none declared", "go nowhere",
      "route is installed, and a project-less caller cannot use it", "the project's route"],
     ["declare "]),
    (FallbackState("", False, "", ("acme",), (("route", "the project's route"),)),
     [f"declare {FALLBACK_ENV}=acme",
      "route is installed, and a project-less caller cannot use it — it would still need "
      "the project's route"],
     ["<one of"]),
]


@pytest.mark.parametrize("state, present, absent", CASES, ids=[str(i) for i in range(len(CASES))])
def test_the_line_says_the_state_and_the_remedy_only_when_there_is_one(state, present, absent):
    line = notifier_fallback_line(state)
    assert line.startswith("notifier fallback: ")
    for words in present:
        assert words in line, f"{words!r} not in {line!r}"
    for words in absent:
        assert words not in line, f"{words!r} in {line!r}"


def test_without_a_state_the_line_reads_the_deployment(stranger, monkeypatch):
    """The default argument is the registry's answer — the line and the state cannot disagree."""
    monkeypatch.delenv(FALLBACK_ENV, raising=False)
    assert notifier_fallback_line() == notifier_fallback_line(fallback_state())
    assert f"declare {FALLBACK_ENV}=acme" in notifier_fallback_line()


def test_the_doctor_names_no_vendor_and_no_package_variable():
    """Vendor-neutral BY CONSTRUCTION: the doctor's own text holds no product name and no
    variable of any package — the package name in the uninstalled case arrives through
    `plugins.install_hint`, the core's own table of which package carries which row."""
    tree = ast.parse((ROOT / "openfactory" / "doctor.py").read_text())
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.FunctionDef) and n.name == "notifier_fallback_line")
    text = " ".join(n.value for n in ast.walk(fn)
                    if isinstance(n, ast.Constant) and isinstance(n.value, str)).lower()
    for word in ("slack", "telegram", "teams", "discord", "openfactory-"):
        assert word not in text, f"the doctor's fallback line spells {word!r} itself"


# ── the CLI reaches it ──────────────────────────────────────────────────────────────────────────

def _doctor_output(monkeypatch) -> str:
    from openfactory import cli

    monkeypatch.setattr(doctor, "diagnose", lambda *_a, **_kw: doctor.Report())
    monkeypatch.setattr(doctor, "probes_for", lambda _p: None)
    monkeypatch.setattr(cli.ProjectRegistry, "get", lambda self, n: object())
    monkeypatch.setattr(cli, "_load_environment", lambda: None)
    result = CliRunner().invoke(cli.app, ["doctor", "demo"])
    assert result.exit_code == 0, result.output
    return result.output


def test_the_cli_prints_the_remedy_for_an_installed_undeclared_notifier(stranger, monkeypatch):
    monkeypatch.delenv(FALLBACK_ENV, raising=False)
    out = _doctor_output(monkeypatch)
    assert "notifier fallback: none declared" in out
    assert f"declare {FALLBACK_ENV}=acme" in out


def test_the_cli_prints_the_declared_kind(stranger, monkeypatch):
    monkeypatch.setenv(FALLBACK_ENV, "acme")
    assert "notifier fallback: acme —" in _doctor_output(monkeypatch)


def test_the_cli_does_not_offer_a_row_a_project_less_caller_cannot_use(monkeypatch):
    install(monkeypatch, declared_rows=False, extra=(_ProjectBound(),))
    monkeypatch.delenv(FALLBACK_ENV, raising=False)
    out = _doctor_output(monkeypatch)
    line = next(ln for ln in out.splitlines() if "notifier fallback:" in ln)
    assert "route is installed, and a project-less caller cannot use it" in line
    assert "declare " not in line


def test_the_panel_only_cli_prints_none_declared_without_a_remedy(panel_only, monkeypatch):
    monkeypatch.delenv(FALLBACK_ENV, raising=False)
    out = _doctor_output(monkeypatch)
    line = next(ln for ln in out.splitlines() if "notifier fallback:" in ln)
    assert "none declared" in line and "go nowhere" in line
    assert "declare " not in line and FALLBACK_ENV not in line


# ── the behaviour change is written where a reader checks it ────────────────────────────────────

def test_the_status_page_records_the_behaviour_change_by_the_variable_to_declare():
    """A deployment that set the old switch must learn from STATUS what to declare now."""
    text = add_ons.STATUS.read_text()
    assert "Behaviour change (2026-08-26)" in text
    paragraph = text[text.index("Behaviour change (2026-08-26)"):].split("\n\n", 1)[0]
    assert FALLBACK_ENV in paragraph and "doctor" in paragraph


# ── the stranger's row is served the way `pip install` serves it (verify the verifier) ──────────

def test_the_strangers_row_is_a_real_entry_point(stranger):
    assert Point("notifier.acme", "acme_addons:build_notifier").load() is stranger.build_notifier
