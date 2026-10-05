"""The backup before a candidate covers everything the stack writes, and nothing it never writes.

THE REVIEW OF #530 FOUND THE PAGE WRONG. docs/RELEASING.md said "an installation is two files and
five Docker volumes", and its backup loop covered those. `docker-compose.yml` also mounts two
directories of the host the stack WRITES (`OPENFACTORY_WORK_DIR` for the worker,
`OPENFACTORY_REPOS_DIR` for the worker and the panel), so "going back" left them in the
candidate's state under a database restored to the previous one. And nothing held the list to the
compose file: the next mount added there would have falsified the page again, silently.

So the list is read from `docker-compose.yml` here, the way `installer_docs_do_not_drift` reads the
installer, and the section is held to it in both directions:

  every named volume       in both loops of the section, the backup's and the restore's, exactly
  every writable host dir  read, archived and restored by both blocks
  every read-only one      named as needing no backup
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
COMPOSE = yaml.safe_load((ROOT / "docker-compose.yml").read_text())
PAGE = (ROOT / "docs" / "RELEASING.md").read_text()

#: A mount whose source is a setting of `.env.compose`: `${NAME:-default}:<target>[:ro]`
_HOST_DIR = re.compile(r"^\$\{(OPENFACTORY_[A-Z_]+)(?::-[^}]*(?:\}[^}]*)?)?\}:.*?(:ro)?$")


def _section() -> str:
    start = PAGE.index("#### Backing up an installation before a candidate")
    return PAGE[start:PAGE.index("\n### ", start)]


def _blocks() -> tuple[str, str]:
    backup, restore = re.findall(r"```bash\n(.*?)```", _section(), re.S)
    return backup, restore


def _host_dirs() -> dict[str, bool]:
    """Every host directory a service mounts from a setting, and whether the stack writes it."""
    writes: dict[str, bool] = {}
    for service in COMPOSE["services"].values():
        for mount in service.get("volumes") or []:
            hit = _HOST_DIR.match(str(mount))
            if hit:
                name, read_only = hit.group(1), bool(hit.group(2))
                writes[name] = writes.get(name, False) or not read_only
    return writes


def test_the_compose_file_still_has_what_this_reads():
    """The guard has a subject: if these vanish, it would pass while checking nothing."""
    assert len(COMPOSE["volumes"]) >= 5, COMPOSE["volumes"]
    dirs = _host_dirs()
    assert {"OPENFACTORY_WORK_DIR", "OPENFACTORY_REPOS_DIR"} <= {n for n, w in dirs.items() if w}
    assert dirs.get("OPENFACTORY_GUIDELINES_DIR") is False, dirs


@pytest.mark.parametrize("which", ["backup", "restore"])
def test_both_loops_name_every_volume_and_only_those(which):
    block = dict(zip(("backup", "restore"), _blocks(), strict=True))[which]
    [loop] = re.findall(r"^for v in (.+); do$", block, re.M)
    assert set(loop.split()) == set(COMPOSE["volumes"]), (
        f"the {which} loop names {sorted(loop.split())}; docker-compose.yml declares "
        f"{sorted(COMPOSE['volumes'])}")


@pytest.mark.parametrize("name", sorted(n for n, writes in _host_dirs().items() if writes))
def test_every_directory_the_stack_writes_is_backed_up_and_restored(name):
    backup, restore = _blocks()
    for which, block in (("backup", backup), ("restore", restore)):
        [var] = re.findall(rf"^(\w+)=\$\(setting {name} ", block, re.M) or [None]
        assert var, f"the {which} block never reads {name} from .env.compose"
        verb = "tar czf" if which == "backup" else "tar xzf"
        assert re.search(rf'^.*{verb} \S+ -C "\${var}"', block, re.M), (
            f"the {which} block reads {name} into ${var} and never archives it")
    assert f"`{name}`" in _section(), f"the section never says what {name} is"


@pytest.mark.parametrize("name", sorted(n for n, writes in _host_dirs().items() if not writes))
def test_a_directory_mounted_read_only_is_said_to_need_no_backup(name):
    section = _section()
    assert f"`{name}` is mounted read-only" in section, (
        f"{name} is mounted read-only and the section does not say why it is left out")
    assert name not in "".join(_blocks()), f"{name} is backed up, though the stack never writes it"


def test_every_other_mount_is_one_this_guard_reads_or_the_docker_socket():
    """A host path written into `docker-compose.yml` itself, rather than through a setting, would be
    a mount neither this guard nor the section can name."""
    unread = []
    for service in COMPOSE["services"].values():
        for mount in service.get("volumes") or []:
            source = str(mount).split(":", 1)[0]
            if source in COMPOSE["volumes"] or _HOST_DIR.match(str(mount)):
                continue
            if source == "/var/run/docker.sock":      # the daemon, not the installation's data
                continue
            unread.append(str(mount))
    assert not unread, f"mounts the backup section cannot know about: {unread}"


def test_the_section_states_no_count_a_new_mount_would_falsify():
    """"Two files and five Docker volumes" was the sentence that went stale."""
    prose = re.sub(r"```.*?```", "", _section(), flags=re.S)
    assert not re.search(r"\b(?:four|five|six|seven|\d+) (?:Docker )?volumes\b", prose), prose
