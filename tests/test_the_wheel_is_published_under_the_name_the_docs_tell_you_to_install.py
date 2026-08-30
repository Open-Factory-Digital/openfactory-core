"""If a document says `pip install <name>`, something has to publish `<name>`.

MEASURED 2026-08-30, and it had been true for a while: PyPI `openfactory` was a **404**, while
`Makefile`'s four cloud recipes told a reader `pip install openfactory-aws` and
`docs/writing-an-addon.md` sold an entry-point model that only works once the core is installable
by name. Three surfaces pointing at an index that had never heard of this project.

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
"""

from __future__ import annotations

import pathlib
import re
import tomllib

import yaml

ROOT = pathlib.Path(__file__).resolve().parent.parent
WORKFLOW = ROOT / ".github" / "workflows" / "release.yml"
PROJECT = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]


def _pypi_job() -> dict:
    workflow = yaml.safe_load(WORKFLOW.read_text())
    assert "pypi" in workflow["jobs"], (
        "release.yml has no job that publishes the wheel — `pip install openfactory` is what "
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


def test_the_wheel_is_published_only_from_a_tag():
    """A version is published ONCE and can never be replaced. A per-push publish is not a faster
    feedback loop, it is a burned version number — and then every later push fails on a version
    that already exists, which reads as a broken workflow rather than a wrong trigger."""
    guard = str(_pypi_job().get("if", ""))

    assert "refs/tags/v" in guard, (
        f"the publish job's condition is {guard!r} — a push to main would try to publish, and the "
        f"first one that succeeded would spend this version number")


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
