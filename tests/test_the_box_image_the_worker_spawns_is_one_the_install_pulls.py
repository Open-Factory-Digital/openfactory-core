"""The box image is named in four places, and all four have to agree.

THE FAILURE THIS PREVENTS IS INVISIBLE AT INSTALL TIME AND ARRIVES AT THE FIRST TICKET. The worker
is told `OPENFACTORY_SANDBOX_IMAGE` and `docker run`s it against the **host's** daemon — it is a
sibling container, not a nested one, which is the whole docker-out-of-docker design. Nothing else
fetches that image:

  · `docker compose up -d` does not, because `sandbox-image` sits behind the `build` profile so the
    installer does not build a multi-gigabyte image it could pull;
  · `docker compose --profile build up -d --build` builds it, which is the CONTRIBUTOR's path;
  · the worker never builds anything.

So on the pull path there is exactly one thing that puts the box image on the daemon: the explicit
`docker pull` in `install.sh`. Remove it and the install is flawless — every container healthy, the
panel up, `preflight` green — and the first job dies on `image not found`, one layer away from its
cause and hours after the command that caused it. That is the same shape the `sandbox-image` compose
service was added to prevent in 2026-08, when the worker referred to an image nothing produced.

THE FOUR PLACES, and why a guard rather than care: `docker-compose.yml` tags it (what a build
produces), the worker's environment launches it, `install.sh` pulls it, and `release.yml` publishes
it. Four files, four different reasons to edit them, no two edited together.

`preflight` IS THE FIFTH AND IT IS DIFFERENT IN KIND. It does not name the image — it reads it from
the compose file and asks the daemon whether it is there, with `docker pull …` as the remedy. That
is what makes a missing box image a named finding at install time instead of a dead job later, and
it is the guarantee that replaced `worker.depends_on: sandbox-image` when the profile made that row
illegal (ADR-0043).
"""

from __future__ import annotations

import pathlib
import re

import installer_script
import yaml

ROOT = pathlib.Path(__file__).resolve().parent.parent
COMPOSE = yaml.safe_load((ROOT / "docker-compose.yml").read_text())
WORKFLOW = yaml.safe_load((ROOT / ".github" / "workflows" / "release.yml").read_text())
SCRIPT = installer_script.SCRIPT

#: `${NAME:-default}` as compose resolves it on a machine that has set nothing.
_INTERPOLATION = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?::?-([^}]*))?\}")


def _resolved(text: str) -> str:
    return _INTERPOLATION.sub(lambda m: m.group(2) or "", text)


def _launched() -> str:
    """The image the worker will `docker run` on the host daemon."""
    return COMPOSE["services"]["worker"]["environment"]["OPENFACTORY_SANDBOX_IMAGE"]


def _tagged() -> str:
    """The image `--profile build up --build` produces."""
    return COMPOSE["services"]["sandbox-image"]["image"]


def _repository(reference: str) -> str:
    """`ghcr.io/org/name:tag` → `name`. The tag is a version and moves; the name must not."""
    return _resolved(reference).rsplit(":", 1)[0].rsplit("/", 1)[-1]


def test_the_worker_launches_what_the_build_tags():
    """Connected by nothing but agreement, and a disagreement is invisible until a job runs."""
    assert _launched() == _tagged(), (
        f"the worker launches {_launched()!r} and the build tags {_tagged()!r}")


def test_the_installer_pulls_the_image_the_worker_will_launch():
    """THE line the whole file is about. `up -d` will not fetch this image and the worker will not
    build it, so if `install.sh` does not pull it, nothing does."""
    repository = _repository(_launched())
    pulls = [installer_script.expand(line) for line in installer_script.code_lines()
             if "docker pull" in line or "would pull" in line]

    assert any(repository in line for line in pulls), (
        f"install.sh never pulls {repository} — the install completes, every container is healthy, "
        f"and the first ticket dies on `image not found` against an image the compose file names, "
        f"the release publishes, and this machine has never seen. Pulls found: {pulls}")


def test_the_release_publishes_the_image_the_installer_pulls():
    """A pull of something nothing publishes is a `manifest unknown` at the first ticket rather
    than at `up` — later, and harder to attribute."""
    published = {row["image"] for row in WORKFLOW["jobs"]["images"]["strategy"]["matrix"]["include"]}

    assert _repository(_launched()) in published, (
        f"release.yml publishes {sorted(published)} and the worker launches "
        f"{_repository(_launched())!r}")


def test_the_pull_is_pinned_to_the_same_version_as_everything_else():
    """A box image at a different tag from the worker running beside it is a mismatched pair that
    nothing reports: the toolbox contract, the glibc/musl expectations and the platform baked into
    each are versioned together and are only tested together."""
    assert "${OPENFACTORY_VERSION" in _launched(), (
        f"the box image is not pinned to the deployment's version: {_launched()!r}")

    pulls = [line for line in installer_script.code_lines()
             if "docker pull" in line and "sandbox" in line]
    assert pulls, "install.sh does not pull the box image at all"
    for line in pulls:
        assert "${VERSION}" in line, (
            f"the box image is pulled at a tag other than the resolved version: {line.strip()}")


def test_preflight_is_what_names_the_missing_image_at_install_time():
    """The guarantee that replaced `worker.depends_on: sandbox-image` (ADR-0043). The compose row
    could only ever protect somebody who typed `--build`; this covers the pull path, which is the
    path almost everybody now takes — and it is the reason a missing box image is a sentence with a
    remedy rather than a dead job."""
    from openfactory import preflight

    probes = preflight.Probes(
        compose=lambda: (True, "v2.29.1"), daemon=lambda: (True, "linux/arm64"),
        host_arch=lambda: "arm64", port_free=lambda port: True,
        free_disk=lambda: 200 * 1024 ** 3, work_dir=lambda: "/home/ana/work",
        writable_without_root=lambda where: (True, "ok"),
        image_present=lambda image: False,
        sandbox_image=lambda: _resolved(_launched()),
        env_file=lambda: (True, 0o600),
        agent_credential=lambda: (True, "set"),
        ports=lambda: (("panel", 8787),))
    finding = next(f for f in preflight.check(probes).findings if f.check == "box_image")

    assert not finding.ok, "a box image absent from the daemon is reported as fine"
    assert "docker pull" in finding.remedy, (
        f"the remedy does not tell somebody how to get the image: {finding.remedy!r}")
    assert _repository(_launched()) in finding.remedy, (
        "the remedy does not name the image the worker will actually launch")


def test_the_compose_file_does_not_quietly_start_fetching_it_again():
    """VERIFY THE PREMISE. Every claim above rests on `sandbox-image` being behind the build
    profile — that is WHY the explicit pull exists. If the profile were removed, `up -d` would
    fetch the image and this file would be guarding a line nobody needs, while the real hazard
    (Compose refusing the project, because `worker` may not depend on a profiled service) moved
    somewhere else entirely."""
    assert "build" in (COMPOSE["services"]["sandbox-image"].get("profiles") or []), (
        "sandbox-image is no longer behind the build profile — re-read ADR-0043 before deciding "
        "whether install.sh should still pull it by hand")
