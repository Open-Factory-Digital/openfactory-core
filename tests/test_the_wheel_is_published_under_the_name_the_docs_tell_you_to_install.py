"""If a document says `pip install <name>`, something has to publish `<name>`.

MEASURED 2026-08-30, and it had been true for a while: PyPI `openfactory` was a **404**, while
`docs/writing-an-addon.md` sold an entry-point model that only works once the core is installable
by name. A document pointing at an index that had never heard of this project.

(The `Makefile`'s cloud recipes name the add-on package the same way, and this workflow does NOT
fix those — that package is on no index deliberately. The bare name is not spelled anywhere in
this file, because `test_the_remedy_a_refusal_hands_you_can_be_followed.py` forbids it in any
tracked text file and caught this docstring doing it, on the commit after the one that wrote it:
that guard reads `git ls-files`, so a brand-new file's offence is invisible until it is added.)

The install instruction and the thing that publishes are in different files, edited by different
people for different reasons, and nothing connected them. This is the connection, and it is
deliberately a LOCAL, OFFLINE one: a test that asks PyPI whether a name exists needs the network,
which changes what a fork or a laptop can run, and "your machine is not the reference". What can
be checked here is that the workflow publishes the name `pyproject.toml` declares, that it does so
only on a tag, and that the tag and the declared version are reconciled BEFORE the upload rather
than after.

THE VERSION CHECK IS THE ONE WITH TEETH. A PyPI upload is rejected for a version that already
exists and accepted for one that does not, so a tag/metadata mismatch does not fail — it publishes
the wrong number, permanently, because a version can be yanked and never replaced.

AND SINCE 2026-08-31 THE PUBLISH IS OFF UNTIL A HUMAN TURNS IT ON. The product owner cut v0.1.0 for
the images and the release assets alone: a PyPI trusted publisher has to be registered in a browser
BEFORE the first upload and cannot be created from CI, so an ungated job would have died inside
`pypa/gh-action-pypi-publish` and made the project's first public release run red for a reason no
code caused. The gate is a repository variable — a settings change, not a commit — and it is
guarded here in the shape `openfactory/preflight.py` already uses for a question it cannot answer:
**absence is not failure and it is not a pass**, so a tag produces either a publish or a job that
says, by name and with the three steps to change it, that the wheel was deliberately not published.
"""

from __future__ import annotations

import pathlib
import re
import tomllib

import pytest
import yaml

ROOT = pathlib.Path(__file__).resolve().parent.parent
WORKFLOW = ROOT / ".github" / "workflows" / "release.yml"
PROJECT = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]


def _pypi_job() -> dict:
    workflow = yaml.safe_load(WORKFLOW.read_text())
    assert "pypi" in workflow["jobs"], (
        "release.yml has no job that publishes the wheel — installing the core by name is what "
        "docs/writing-an-addon.md's whole model rests on")
    return workflow["jobs"]["pypi"]


def test_the_release_publishes_the_name_the_package_declares():
    """A publish job pointing at a different project name would upload this code under somebody
    else's name, or fail on a trusted-publisher mismatch after a green build."""
    job = _pypi_job()
    environment = job.get("environment") or {}

    assert PROJECT["name"] == "openfactory", PROJECT["name"]
    # THE LAST SEGMENT, EXACTLY — not a substring. `openfactory` is a prefix of `openfactory-core`,
    # `openfactory-aws` and every add-on package this project publishes, so `name in url` was
    # satisfied by a URL pointing at a DIFFERENT project. A mutation caught it (2026-08-30): the
    # cut aimed at exactly this rot survived a green guard.
    published = str(environment.get("url", "")).rstrip("/").rsplit("/", 1)[-1]
    assert published == PROJECT["name"], (
        f"the publish environment points at project {published!r}, and this package is called "
        f"{PROJECT['name']!r} — a trusted publisher registered for one name cannot upload another")


def test_the_publish_job_actually_uploads_something():
    """FOUND BY A SURVIVING MUTATION (2026-08-30). Every other assertion in this file is about the
    SHAPE of the publish job — its trigger, its permissions, its version check — and a job that
    checks out, builds a wheel and then uploads nothing satisfies all of them while publishing
    nothing at all. The suite went green over a release that would have shipped no package.

    The action name is also what `test_the_remedy_a_refusal_hands_you_can_be_followed.py` scans for
    to decide which of our distributions an index serves, so this is the same fact both files
    depend on, asserted where it is easiest to see."""
    steps = _pypi_job()["steps"]

    assert any("gh-action-pypi-publish" in str(s.get("uses", "")) for s in steps), (
        "the publish job builds a distribution and never uploads it — a release that ships no "
        "package, green")


def test_it_publishes_through_trusted_publishing_and_holds_no_api_token():
    """A long-lived `PYPI_API_TOKEN` is a secret that can publish this package — worth stealing,
    and impossible to scope to one workflow. Trusted publishing mints a short-lived credential
    against this workflow's OIDC identity instead, which is why `id-token: write` is here and why
    nothing else needs to be."""
    job = _pypi_job()

    assert (job.get("permissions") or {}).get("id-token") == "write", (
        "the publish job cannot mint an OIDC token, so trusted publishing cannot work")

    # THE PUBLISH JOB'S OWN TEXT, not the whole workflow. The first cut of this searched the file
    # and failed on `password: ${{ secrets.GITHUB_TOKEN }}` — the GHCR login in the images job,
    # which is exactly the credential that SHOULD be there. A guard that cannot tell the two
    # apart would have to be deleted the first time somebody read it.
    text = yaml.dump(job)
    assert not re.search(r"PYPI_API_TOKEN|pypi[_-]token|password:", text, re.I), (
        "the publish job carries a PyPI password or token — trusted publishing needs neither, and "
        "a secret that can publish this package is one more thing that can be stolen")


def _announcement_job() -> dict:
    """The job that runs when the wheel is deliberately NOT published.

    SELECTED BY NAME, not by "the pypi-ish job that is not `_pypi_job()`" — which was the first
    cut of this and is always true: `_pypi_job()` re-parses the YAML on every call, so the dict it
    returns is never identical to anything, and BOTH jobs matched (2026-08-31)."""
    workflow = yaml.safe_load(WORKFLOW.read_text())
    named = {name: job for name, job in workflow["jobs"].items()
             if name.startswith("pypi") and name != "pypi"}
    assert len(named) == 1, (
        f"expected exactly one job announcing a release that did not publish the wheel, found "
        f"{sorted(named)} — absence would otherwise be a job that is simply not there, which a "
        f"reader has to infer")
    return next(iter(named.values()))


@pytest.mark.parametrize("job", ["pypi", "announcement"])
def test_the_wheel_is_published_only_from_a_tag(job):
    """A version is published ONCE and can never be replaced. A per-push publish is not a faster
    feedback loop, it is a burned version number — and then every later push fails on a version
    that already exists, which reads as a broken workflow rather than a wrong trigger.

    BOTH JOBS, since 2026-08-31. Asking only the publishing one would leave the announcement free
    to fire on every push to `main`, telling everybody on every commit that a wheel they were not
    expecting had not been published."""
    guard = str((_pypi_job() if job == "pypi" else _announcement_job()).get("if", ""))

    assert "refs/tags/v" in guard, (
        f"the {job} job's condition is {guard!r} — it would run on a push to main")


#: The repository variable that turns publishing on. Spelled once, because three assertions and the
#: workflow's own announcement all have to agree about the name a human will type into Settings.
GATE = "PYPI_TRUSTED_PUBLISHER"


def test_enabling_the_publish_is_a_settings_change_and_not_a_commit():
    """THE PRODUCT OWNER'S DECISION (2026-08-31): v0.1.0 publishes the images and the release
    assets; the wheel waits for a later tag, because registering a PyPI trusted publisher is a
    browser step on pypi.org that cannot be done from CI and must happen BEFORE the first upload.

    A REPOSITORY VARIABLE RATHER THAN A COMMENTED-OUT JOB, so turning it on later needs no commit,
    no review and no re-tag — and `vars` rather than `secrets` because this is a switch, not a
    credential: trusted publishing has no credential to hold, and a `secrets` gate would make the
    state invisible to anybody without admin."""
    guard = str(_pypi_job().get("if", ""))

    assert f"vars.{GATE}" in guard, (
        f"the publish job is not gated on the `{GATE}` repository variable: {guard!r}")
    assert "secrets." not in guard, (
        f"the publish is gated on a secret rather than a variable — the state would be invisible "
        f"to everybody without admin, on a switch that is not a credential: {guard!r}")


def test_exactly_one_of_the_two_jobs_runs_on_any_tag():
    """The third state, made structural. `openfactory/preflight.py` renders "could not be answered"
    as its own mark because two values cannot carry three meanings; the same rule here means a tag
    must produce EITHER a publish OR a stated non-publish — never both, and never neither.

    Neither is the dangerous one: it is what a plain `if: … == 'true'` with no twin would give,
    and the release run would then be silent about the wheel in a way indistinguishable from a
    workflow that had forgotten it."""
    publishing = str(_pypi_job().get("if", ""))
    announcing = str(_announcement_job().get("if", ""))

    assert f"vars.{GATE} == 'true'" in publishing, publishing
    assert f"vars.{GATE} != 'true'" in announcing, announcing
    # the same tag condition on both, so the pair is complementary over tags rather than over
    # every event GitHub might deliver
    tag = "startsWith(github.ref, 'refs/tags/v')"
    assert tag in publishing and tag in announcing, (publishing, announcing)


def test_a_release_that_does_not_publish_the_wheel_says_so_by_name():
    """ABSENCE IS NOT FAILURE AND IT IS NOT A PASS. A skipped publish that vanished from the run
    would leave "was the wheel published?" answerable only by somebody who knows which jobs are
    supposed to exist. The announcement is what makes the non-publish a visible fact, and it owes
    the reader the way to change it — the same standard every failing `Finding` in this codebase
    is held to: name the cause AND the remedy."""
    steps = " ".join(str(s.get("run", "")) for s in _announcement_job()["steps"])

    assert "NOT published" in steps, "the announcement does not say the wheel was not published"
    assert GATE in steps, (
        f"the announcement does not name `{GATE}`, so a reader is told the state and not how to "
        f"change it")
    assert "pypi.org" in steps and "pending publisher" in steps, (
        "the announcement does not name the browser step that has to happen first — which is the "
        "one thing nobody can work out from this repository")
    assert "GITHUB_STEP_SUMMARY" in steps, (
        "the announcement is only in the log, where the person cutting the release will not see "
        "it; it belongs in the run summary")


def test_a_deliberately_unpublished_wheel_never_makes_the_release_run_red():
    """The whole point of gating rather than discovering. Left ungated, the job would run on the
    v0.1.0 tag and die inside `pypa/gh-action-pypi-publish` on an OIDC exchange against a publisher
    that does not exist — turning the project's first public release run red for a reason no code
    caused, on the artefact a stranger arriving from Hacker News meets first."""
    announcement = _announcement_job()
    steps = " ".join(str(s.get("run", "")) for s in announcement["steps"])

    assert "exit 1" not in steps, (
        "the announcement fails the run — the wheel was not published on purpose, and a red run "
        "says something untrue about the code")
    assert not any("pypi-publish" in str(s.get("uses", "")) for s in announcement["steps"]), (
        "the announcement job tries to publish, which is the thing it exists to say did not happen")

    # AND NOTHING WAITS ON IT. `release` must not `needs: pypi`, or a skipped publish would take
    # the GitHub Release — the thing install.sh resolves a pinned tag out of — down with it.
    workflow = yaml.safe_load(WORKFLOW.read_text())
    needs = workflow["jobs"]["release"].get("needs")
    needs = [needs] if isinstance(needs, str) else (needs or [])
    assert not any(str(n).startswith("pypi") for n in needs), (
        f"the GitHub Release depends on {needs} — with publishing disabled, a skipped job would "
        f"cancel the release that carries docker-compose.yml and SHA256SUMS")


def test_nothing_in_the_release_claims_a_wheel_that_may_not_exist():
    """The release notes are read by people deciding what they can install. While publishing is
    gated, a line promising PyPI would be a claim the same workflow declines to make true."""
    body = str(yaml.safe_load(WORKFLOW.read_text())["jobs"]["release"]["steps"][-1]["with"]["body"])

    assert "pypi" not in body.lower() and "pip install" not in body.lower(), (
        f"the release body advertises the wheel while the publish is gated:\n{body}")


def test_the_tag_and_the_declared_version_are_reconciled_before_the_upload():
    """THE check with teeth, and the reason it must come before `python -m build` rather than
    after: PyPI accepts any version that does not already exist, so a mismatch between the tag and
    `project.version` does not fail — it publishes the wrong number, and a wrong version can be
    yanked but never replaced."""
    steps = _pypi_job()["steps"]
    reconciles = [i for i, s in enumerate(steps)
                  if "pyproject.toml" in str(s.get("run", ""))
                  and "GITHUB_REF_NAME" in str(s.get("run", ""))]
    assert reconciles, (
        "nothing in the publish job compares the tag with project.version — a mismatch would "
        "publish this code under a version number nobody chose")

    builds = next(i for i, s in enumerate(steps) if "-m build" in str(s.get("run", "")))
    assert reconciles[0] < builds, (
        "the tag/version check runs AFTER the build — it has to refuse before anything is made, "
        "or the failure arrives with artefacts already sitting on disk ready to upload")


def test_the_package_declares_ONE_version():
    """THE GAP THIS CLOSES, found while cutting v0.1.0 (2026-08-31). The version has two homes —
    `pyproject.toml`'s `project.version`, which becomes the wheel's metadata, and
    `openfactory/__init__.py`'s `__version__`, which is what `openfactory.__version__` answers to
    anybody who asks the installed package what it is. **Nothing held them equal.**

    `release.yml` reconciles the TAG against `pyproject.toml` and never looks at `__init__.py`, so
    that second home could drift for ever without a single red run: a wheel would ship, correctly
    labelled 0.1.0 by every packaging tool, and report `0.0.1` when imported. It is the shape #113
    is about — a number a command can measure, typed by hand, in more than one place — and it had
    been true since the file was written, because `__version__` is read by nothing in this tree
    and so nothing ever contradicted it.

    NOT DELETED IN FAVOUR OF `importlib.metadata`, deliberately: that answers from the INSTALLED
    distribution, so it is unavailable to a checkout run from source and would make the attribute
    depend on how the package was obtained. Two homes and one guard is the cheaper honest option."""
    import openfactory

    assert openfactory.__version__ == PROJECT["version"], (
        f"openfactory.__version__ is {openfactory.__version__!r} and pyproject.toml declares "
        f"{PROJECT['version']!r}. The wheel would carry one number in its metadata and answer "
        f"with the other when imported, and release.yml — which only reads pyproject.toml — would "
        f"not notice.")


def test_the_declared_version_is_one_a_tag_could_carry():
    """`v${version}` is how the tag is formed, so a version with a leading `v`, whitespace or a
    local segment produces a tag the workflow's own `${GITHUB_REF_NAME#v}` cannot round-trip."""
    version = PROJECT["version"]

    assert re.fullmatch(r"\d+\.\d+\.\d+([abrc.dev+][0-9A-Za-z.+-]*)?", version), (
        f"project.version is {version!r}, which does not round-trip through a `v<version>` tag")


def test_publishing_the_core_is_not_claimed_to_publish_the_add_on_packages():
    """THE CONFLATION THIS GUARD REFUSES TO INHERIT. The case for publishing was written as "the
    Makefile already tells people to install the cloud add-on and `docs/writing-an-addon.md` sells
    the entry-point model — both currently point at a 404". Only the second half is fixed by this
    workflow. `python -m build` at the repository root produces the CORE distribution; the add-on
    packages are built out of `addons/` by their own script and nothing uploads them, deliberately
    — `openfactory/plugins.py::install_hint` exists to say so, and
    `tests/test_the_remedy_a_refusal_hands_you_can_be_followed.py` holds the line that no remedy
    may hand somebody their bare name.

    So this asserts the boundary rather than assuming it: whatever else changes, this workflow must
    not start publishing a package whose name a refusal is still forbidden to print."""
    from openfactory import plugins

    text = WORKFLOW.read_text()
    for package in sorted(set(plugins.SHIPS_IN.values())):
        assert f"packages-dir: {package}" not in text and f"upload {package}" not in text, (
            f"release.yml has started publishing {package} — `install_hint` and every refusal that "
            f"names it are now saying something false in the other direction")


def test_the_document_that_rests_on_an_installable_core_still_does():
    """Verify the verifier, and keep the subject. This publish job exists because
    `docs/writing-an-addon.md` sells a model that only works once the core resolves by name; if
    that page stops teaching an install, the guard is protecting a claim nobody makes and should
    be re-aimed rather than left passing quietly."""
    text = (ROOT / "docs" / "writing-an-addon.md").read_text()

    assert "pip install" in text, (
        "docs/writing-an-addon.md no longer teaches an install — this job was justified by it, and "
        "a guard whose subject has moved is one nobody re-earns")
