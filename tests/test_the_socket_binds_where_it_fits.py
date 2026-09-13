"""The installer's fake Docker socket binds on a path `sun_path` will actually accept (#121).

WHAT WENT WRONG. `tests/test_the_installer_builds_the_commands_it_says_it_does.py` binds a real
`AF_UNIX` socket so the installer's own `[ -S … ]` check passes for the right reason, and it bound
it under pytest's `tmp_path` in two places. A Unix socket path is capped by `sun_path` at **104
bytes on macOS**, 108 on Linux; macOS pytest temps live under
`/private/var/folders/<xx>/<32 chars>/T/pytest-of-<user>/pytest-<N>/`, ~90 bytes before the test's
own directory is appended. The two binds measured 105 and 128 bytes, `bind()` raised
`OSError: AF_UNIX path too long`, and because the fixture holding the first one is module-scoped it
took every test that takes it down with it — **15 tests**, reported on 2026-09-13 and reproduced
here on Linux with `--basetemp=<146 bytes>`:

    before  5 failed, 5 passed, 14 errors   (15 × `OSError: AF_UNIX path too long`)
    after   5 failed, 19 passed             (identical to the same file under a short base temp)

Green on `ubuntu-latest`, where `tmp_path` is `/tmp/pytest-of-runner/…` and fits. So CI could never
see it and a macOS maintainer could never miss it.

WHAT IS PROVEN HERE, by CALLING `_a_bound_docker_socket` rather than reading it:

  · it still binds when the machine's `$TMPDIR` is far past the cap — the macOS arrangement,
    stood up on Linux;
  · it refuses BY NAME, naming `sun_path` and the byte count, when its base cannot hold a socket,
    instead of the bare `OSError` that started this;
  · the socket's group is still a supplementary group, which is the 2026-08-31 property the move
    could silently have dropped;

and, PARSED rather than grepped, that no third bind site drifts back under `tmp_path` next year.
Parsed because this file's own prose — and the helper's docstring — quote `tmp_path` repeatedly: a
grep for it is satisfied by the explanation of the very thing it forbids.
"""

from __future__ import annotations

import ast
import os
import pathlib
import tempfile

import pytest
import test_the_installer_builds_the_commands_it_says_it_does as installer_tests

#: The one function allowed to bind. Read off the module rather than typed twice, so a rename is a
#: red test here rather than a guard that quietly stops finding anything.
HELPER = installer_tests._a_bound_docker_socket.__name__

#: The two sites the helper exists for. Named, because "some function uses it" is satisfied by a
#: fixture that still binds its own socket under `tmp_path` beside a helper nobody calls.
CALLERS = {"install_run", "test_a_forced_reinstall_states_the_runtime_too"}

SOURCE = pathlib.Path(installer_tests.__file__).read_text(encoding="utf-8")
TREE = ast.parse(SOURCE)


def _a_path_past_the_cap(under: pathlib.Path) -> pathlib.Path:
    """A real directory whose name alone is longer than any `sun_path` will take.

    STANDS macOS UP ON LINUX. `/private/var/folders/<xx>/<32 chars>/T/pytest-of-<user>/pytest-<N>/`
    is ~90 bytes of base temp before anything of ours is appended; three 40-byte segments reproduce
    that shape past both caps without needing the machine it came from."""
    deep = under / ("a" * 40) / ("b" * 40) / ("c" * 40)
    deep.mkdir(parents=True, exist_ok=True)
    assert len(str(deep).encode()) > 108, f"{deep} is not past even the Linux cap"
    return deep


# ── executed: the property itself ───────────────────────────────────────────────────────────────

def test_the_socket_binds_even_when_the_machines_temp_is_far_past_the_cap(tmp_path, monkeypatch):
    """THE DEFECT, in one assertion. With the machine's temp directory where macOS puts it, the
    old code raised `OSError: AF_UNIX path too long` here and 15 tests never ran."""
    far = _a_path_past_the_cap(tmp_path)
    # BOTH, AND THE SECOND ONE IS THE ONE THAT BITES. `tempfile.gettempdir()` caches its answer in
    # `tempfile.tempdir` on first use (measured 2026-09-13: setting `$TMPDIR` after any earlier
    # call left `gettempdir()` reporting the old value), so setting the variable alone would leave
    # this test passing over a base temp that was never long — a guard that cannot fail.
    monkeypatch.setenv("TMPDIR", str(far))
    monkeypatch.setattr(tempfile, "tempdir", str(far))

    with installer_tests._a_bound_docker_socket() as (sock, path):
        bound = pathlib.Path(sock.getsockname())

        assert path.is_socket(), f"{path} is not a bound socket"
        assert bound == path, f"the helper yields {path} and bound {bound}"
        assert path.is_absolute(), (
            f"{path} is relative — `FAKE_SOCKET` reaches the installer's "
            f"`-v <socket>:/var/run/docker.sock` mount and its `stat`, both of which need a real "
            f"absolute path")
        assert len(str(path).encode()) < installer_tests._SUN_PATH_MAX, (
            f"{path} is {len(str(path).encode())} bytes, and `sun_path` caps a Unix socket path "
            f"at {installer_tests._SUN_PATH_MAX} on macOS — this binds on Linux and not on the "
            f"machine the report came from")


def test_the_socket_directory_is_released_when_the_run_ends():
    """A helper that leaks a directory per run is a helper somebody will replace with `tmp_path`
    again. `finally`, so a failing installer run releases it too."""
    with installer_tests._a_bound_docker_socket() as (_sock, path):
        home = path.parent
        assert home.is_dir()

    assert not home.exists(), f"{home} outlived the run that made it"


# ── executed: the refusal ───────────────────────────────────────────────────────────────────────

def test_a_base_that_cannot_hold_a_socket_is_refused_BY_NAME(tmp_path, monkeypatch):
    """`OSError: AF_UNIX path too long` names no remedy, and that is how this cost 15 tests and a
    review round. The house bar is one sentence naming the cause and what to do — so the helper
    measures the path before it binds and says so."""
    monkeypatch.setattr(installer_tests, "_SHORT_TMP", str(_a_path_past_the_cap(tmp_path)))

    with pytest.raises(AssertionError) as refused:
        with installer_tests._a_bound_docker_socket():
            pytest.fail("a base past the cap bound a socket, so this machine is not macOS and the "
                        "guard below is measuring nothing")
    said = str(refused.value)

    assert "sun_path" in said, f"the refusal does not name what refused it: {said}"
    assert str(installer_tests._SUN_PATH_MAX) in said, (
        f"the refusal does not say what the cap IS, so the reader cannot tell how far over they "
        f"are: {said}")
    assert "shorter" in said, f"the refusal names no remedy: {said}"


# ── executed: the group the move could have dropped ─────────────────────────────────────────────

def test_the_socket_still_belongs_to_a_supplementary_group(monkeypatch):
    """The 2026-08-31 property, carried through the move. With the socket's gid equal to `id -g`,
    `--group-add "$(id -g)"` and `--group-add <socket gid>` are the same string and
    `test_the_socket_and_its_group_reach_docker_run` cannot tell a correct installer from one that
    passes its own group — a mutation proved exactly that."""
    mine = os.getgid()
    if not [g for g in os.getgroups() if g != mine]:
        # THIS CONTAINER IS THE AWKWARD CASE: root, `os.getgroups() == []` (measured 2026-09-13),
        # which is the one arrangement in which the property is invisible. Root may chown to any
        # gid, so stand a supplementary group up rather than skip — a guard that skips on the
        # machine CI runs is a guard nobody has ever seen fail.
        if os.getuid() != 0:
            pytest.skip("this user has no supplementary group and cannot chown to one")
        monkeypatch.setattr(os, "getgroups", lambda: [mine, mine + 1])

    with installer_tests._a_bound_docker_socket() as (_sock, path):
        owner = path.stat().st_gid

    assert owner != mine, (
        f"the socket is owned by this process's own group ({mine}), so `--group-add <socket gid>` "
        f"and `--group-add $(id -g)` are the same string and the installer's guard proves nothing")
    assert owner in os.getgroups(), (
        f"the socket was chowned to {owner}, which is not a group this process is in — the "
        f"installer would hand the container a gid it cannot use")


# ── parsed: nothing drifts back under tmp_path ──────────────────────────────────────────────────

def _functions_that_bind() -> dict[str, str]:
    """Every function in the installer's test module containing a `.bind(` call, with the call."""
    found: dict[str, str] = {}
    for node in ast.walk(TREE):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for inner in ast.walk(node):
            if (isinstance(inner, ast.Call) and isinstance(inner.func, ast.Attribute)
                    and inner.func.attr == "bind"):
                found[node.name] = ast.get_source_segment(SOURCE, inner) or "<unreadable>"
    return found


def _functions_that_call_the_helper() -> set[str]:
    names = set()
    for node in ast.walk(TREE):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) or node.name == HELPER:
            continue
        for inner in ast.walk(node):
            if isinstance(inner, ast.Call) and getattr(inner.func, "id", None) == HELPER:
                names.add(node.name)
    return names


def test_every_bind_in_the_installers_tests_goes_through_the_one_helper():
    """The drift guard, and the reason it is PARSED. A third bind added under `tmp_path` next year
    is the same defect again, and it would be green in CI again."""
    binding = _functions_that_bind()

    assert HELPER in binding, (
        f"`{HELPER}` binds nothing, so every assertion in this file is about an empty room")
    strays = {name: call for name, call in binding.items() if name != HELPER}
    assert not strays, (
        f"{sorted(strays)} bind an AF_UNIX socket themselves instead of going through "
        f"`{HELPER}` — pytest's base temp on macOS is already ~90 bytes before the test directory "
        f"is appended, and `sun_path` caps the path at {installer_tests._SUN_PATH_MAX} there: "
        f"{strays}")


def test_both_sites_the_helper_exists_for_actually_call_it():
    """The other half: a helper nobody calls is satisfied by the assertion above and fixes nothing.
    Named sites, because the module fixture is the one whose failure costs 15 tests."""
    callers = _functions_that_call_the_helper()

    assert CALLERS <= callers, (
        f"{sorted(CALLERS - callers)} no longer take their socket from `{HELPER}`, so the path "
        f"they bind on is unmeasured again")


def test_the_short_base_is_explicit_and_not_the_machines_TMPDIR():
    """`mkdtemp()` with no `dir=` lands in `$TMPDIR`, which on macOS IS the long
    `/var/folders/…/T/` path — the fix that is not one. Read off the module's own value rather
    than its text."""
    assert installer_tests._SHORT_TMP, (
        "the helper has no explicit base, so it falls back to $TMPDIR — the long path on macOS")
    base = pathlib.Path(installer_tests._SHORT_TMP)

    assert base.is_absolute() and base.is_dir(), f"{base} is not a directory to bind under"
    assert len(str(base).encode()) < 16, (
        f"{base} is {len(str(base).encode())} bytes of base before a socket name is appended — "
        f"that is not a short base")
    assert installer_tests._SUN_PATH_MAX == 104, (
        "the cap held here is not macOS's 104, so this file measures the machine it runs on "
        "rather than the one it is for")
