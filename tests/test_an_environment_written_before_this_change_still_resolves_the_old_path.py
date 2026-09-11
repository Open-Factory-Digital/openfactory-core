"""A stack that is already running does not move its workspaces because we shipped a better default.

THE CLAIM THIS FILE EXISTS TO STOP BEING A PROMISE. On 2026-08-30 the job workspace moved out of
`/var/lib/openfactory-work` — a path that needed `sudo` to create — to a directory under the
invoking user's own `$HOME`, written into `.env.compose` by `openfactory init`. The compatibility
argument made at the time was:

    the `:-` default means an existing `.env.compose` with no OPENFACTORY_WORK_DIR row keeps
    resolving to /var/lib/openfactory-work, byte for byte. Only a NEW install, whose `init`
    writes the row, moves.

That is a true sentence about a file, and a sentence about a file is exactly the kind of thing that
stops being true when somebody edits the file. It is also the sentence with the worst failure mode
in this change: a running deployment whose work directory silently moved has jobs IN FLIGHT whose
workspaces are on the old path, and the box that was preparing them would mount an empty directory
at the new one — the "box saw 0 entries" defect (`container.py`, 2026-08-03), arriving on a machine
nobody touched, from an upgrade nobody thought was risky.

So the claim is asserted rather than believed. `${VAR:-default}` and `${VAR-default}` differ by one
character and only the first treats an EMPTY row as absent, which is the state
`.env.compose.example` ships; both are tested, because a change from one form to the other is
invisible in review and would break the empty-row case alone.

NOTHING TO MIGRATE EITHER WAY, and that is worth writing down beside the guard: the directory holds
`mkdtemp` clones, which are scratch. The reason this matters is not the data, it is that a job
running right now must keep finding the workspace it was given.
"""

from __future__ import annotations

import pathlib
import re

import pytest
import yaml

ROOT = pathlib.Path(__file__).resolve().parents[1]

#: The path every install written before 2026-08-30 resolves to, and must keep resolving to.
LEGACY_PATH = "/var/lib/openfactory-work"

_INTERPOLATION = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?::?-([^}]*))?\}")


def _resolve(text: str, env: dict[str, str]) -> str:
    """Compose's interpolation, including the difference the colon makes."""
    def one(match: re.Match[str]) -> str:
        name, default = match.group(1), match.group(2)
        value = env.get(name)
        if match.group(0).startswith(f"${{{name}:-"):
            return value if value else (default or "")
        return default or "" if value is None else value
    return _INTERPOLATION.sub(one, text)


def _worker() -> dict:
    return yaml.safe_load((ROOT / "docker-compose.yml").read_text())["services"]["worker"]


def _work_dir_bind() -> str:
    binds = [v for v in _worker()["volumes"]
             if "openfactory-work" in v or "OPENFACTORY_WORK_DIR" in v]
    assert len(binds) == 1, f"the work directory is bound {len(binds)} times: {binds}"
    return binds[0]


def test_the_reader_can_tell_the_two_default_forms_apart():
    """Verify the verifier, on the one-character difference the whole file turns on. A resolver
    that treated `${A-d}` like `${A:-d}` would report the empty-row case as compatible when it is
    the case that breaks."""
    assert _resolve("${A:-d}", {}) == "d"
    assert _resolve("${A:-d}", {"A": ""}) == "d"
    assert _resolve("${A:-d}", {"A": "x"}) == "x"
    assert _resolve("${A-d}", {}) == "d"
    assert _resolve("${A-d}", {"A": ""}) == "", "the colon-less form keeps an empty value"


@pytest.mark.parametrize("env, why", [
    pytest.param({}, "an .env.compose written before the row existed", id="no-row"),
    pytest.param({"OPENFACTORY_WORK_DIR": ""}, "the row present and left empty", id="empty-row"),
])
def test_an_environment_with_no_work_directory_row_still_gets_the_old_path(env, why):
    """THE compatibility claim, on both halves of "no answer". An operator upgrading a running
    stack changes nothing and gets what they had."""
    configured = _resolve(_worker()["environment"]["OPENFACTORY_WORK_DIR"], env)
    source, _, target = _resolve(_work_dir_bind(), env).partition(":")

    assert configured == LEGACY_PATH, (
        f"with {why} the worker would be told {configured!r} instead of {LEGACY_PATH!r} — a "
        f"deployment that was running before this change moved its job workspaces without asking")
    assert source == target == LEGACY_PATH, (
        f"with {why} the bind resolves {source!r}:{target!r} — a job in flight would find its "
        f"workspace mounted empty")


def test_an_environment_that_names_a_directory_gets_that_one():
    """The other half of the same guarantee: the default may only apply when nobody answered. A
    default that won over a stated value would be worse than no default at all."""
    chosen = "/home/ana/.local/share/openfactory/work"
    env = {"OPENFACTORY_WORK_DIR": chosen}

    configured = _resolve(_worker()["environment"]["OPENFACTORY_WORK_DIR"], env)
    source, _, target = _resolve(_work_dir_bind(), env).partition(":")

    assert configured == source == target == chosen


def test_the_compatibility_rests_on_a_DEFAULT_and_not_on_a_rewrite():
    """WHY the mechanism is the property and not an implementation detail. The alternative
    considered was migrating existing files — rewriting `.env.compose` to add the row. That cannot
    be safe: the file is read at container creation, a running worker holds jobs whose workspaces
    are on the old path, and a rewrite moves them mid-flight. Defaulting is what makes "nothing
    moves under a running stack" true by construction rather than by timing."""
    declared = _worker()["environment"]["OPENFACTORY_WORK_DIR"]

    assert declared.startswith("${OPENFACTORY_WORK_DIR:-"), (
        f"{declared!r} does not default an ABSENT-OR-EMPTY value — an install written before this "
        f"change would resolve to something else")
    assert declared.endswith(f"{LEGACY_PATH}}}"), (
        f"{declared!r} does not fall back to {LEGACY_PATH!r}")
