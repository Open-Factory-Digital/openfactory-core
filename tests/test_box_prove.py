"""`sdlc box prove` — the box is proven before any agent runs (ADR-0037 D3).

The product owner asked whether a box should be pre-configured per client before pulling from
TO-DO. It
should be something stronger: **configuration is a declaration, a proof is a fact.**

The box is the one part of the platform that must satisfy the CLIENT's stack and the FRAMEWORK's
harness at once, and it was the only part of onboarding with no step of its own — it first appeared
at the first ticket, which is the worst moment to discover it is wrong, because by then an agent is
running and money is being spent on an environment that cannot work.

WHAT THE PROOF IS. Pull the image and resolve its tag to a digest; check the image contract item by
item; check that the toolbox can even execute in that image; run the client's own `setup:` and then
`validate:` against untouched `main`. Green means *your tests passed inside the factory* — the first
time a client sees their own work succeed in our machine, and it costs **zero harness tokens**.

WHY EACH CHECK IS SEPARATE, with its own remedy. `doctor`'s standing bar: one cause, one actionable
line. "The box does not work" is as useless as silence when there are seven ways for it not to.

THE VARIANT CHECK IS THE ONE THAT PAYS. The harness binaries are glibc-linked (measured: `ldd` on
the shipped `claude.exe` shows `ld-linux-<arch>.so.1`). An Alpine or musl client image cannot
execute them, and the failure is the dynamic loader's *no such file or directory* — which names the
wrong thing entirely and sends somebody looking for a file that is sitting right there. Catching
that here turns an afternoon into a sentence.

A TAG IS NOT AN IMAGE, which is why the digest is recorded rather than the tag: `docker run` passes
no `--pull`, so a tag proven on Monday can be repointed on Tuesday and the job launches something
nobody proved.
"""

from __future__ import annotations

import pytest

from openfactory.box_prove import Probes, prove


def _probes(**overrides) -> Probes:
    """A box that satisfies everything. Each test breaks exactly one thing."""
    base = dict(
        resolve_digest=lambda image: "sha256:" + "a" * 64,
        image_platform=lambda image: ("linux", "arm64", "glibc"),
        toolbox_stamp=lambda: {"variant": "linux-arm64-glibc",
                               "harnesses": ["claude", "codex", "kimi"]},
        contract=lambda image: {},          # {requirement: what is wrong} — empty is satisfied
        run_in_box=lambda cmd: (0, ""),     # setup / validate / harness smoke
        harness_reachable=lambda: (True, ""),
        setup_commands=lambda: ["pip install -q pytest"],
        validate_commands=lambda: {"test": "pytest -q"},
        harness_name=lambda: "claude",
    )
    base.update(overrides)
    return Probes(**base)


# ── the happy path is the product moment ────────────────────────────────────────────────────────

def test_a_good_box_proves(monkeypatch):
    proof = prove("acme", "mycorp/ci:1", _probes())

    assert proof.ok, [f.message for f in proof.findings if not f.ok]


def test_the_proof_records_the_digest_not_the_tag():
    """A tag can be repointed between the proof and the job. `docker run` passes no `--pull`, so
    what was proven and what runs would differ with nobody able to tell."""
    proof = prove("acme", "mycorp/ci:1", _probes())

    assert proof.digest.startswith("sha256:"), proof.digest
    assert proof.image == "mycorp/ci:1"


def test_the_proof_records_what_it_was_proven_against():
    """D5 gates pickup on a proof still being VALID, which means knowing the three things that can
    change underneath it: the image, the toolbox, and the client's commands."""
    proof = prove("acme", "mycorp/ci:1", _probes())

    assert proof.toolbox == "linux-arm64-glibc"
    assert proof.commands_hash, proof


def test_the_commands_hash_changes_when_setup_changes():
    """A client editing `setup:` invalidates the proof — the environment it proved is not the one
    the next job builds."""
    a = prove("acme", "img", _probes())
    b = prove("acme", "img", _probes(setup_commands=lambda: ["pip install -q pytest", "npm ci"]))

    assert a.commands_hash != b.commands_hash


# ── each failure gets its own line ──────────────────────────────────────────────────────────────

def test_an_unpullable_image_says_so_and_stops():
    """Everything after this would fail for the same reason and report it seven different ways."""
    proof = prove("acme", "mycorp/ci:1", _probes(resolve_digest=lambda image: None))

    assert not proof.ok
    failed = [f for f in proof.findings if not f.ok]
    assert len(failed) == 1, [f.check for f in failed]
    assert failed[0].check == "image"
    assert "mycorp/ci:1" in failed[0].message
    assert "registry" in failed[0].remedy.lower() or "pull" in failed[0].remedy.lower()


def test_a_musl_image_is_refused_by_name():
    """THE check that pays for the feature. The alternative is a dynamic-loader ENOENT at the first
    ticket, naming a file that is right there."""
    proof = prove("acme", "alpine-ci:1",
                  _probes(image_platform=lambda image: ("linux", "arm64", "musl")))

    assert not proof.ok
    finding = next(f for f in proof.findings if f.check == "toolbox")
    assert not finding.ok
    assert "musl" in finding.message and "glibc" in finding.message
    assert finding.remedy


def test_an_architecture_mismatch_is_refused():
    proof = prove("acme", "amd-only:1",
                  _probes(image_platform=lambda image: ("linux", "amd64", "glibc")))

    finding = next(f for f in proof.findings if f.check == "toolbox")
    assert not finding.ok
    assert "amd64" in finding.message


def test_a_matching_variant_passes():
    proof = prove("acme", "img", _probes())
    assert next(f for f in proof.findings if f.check == "toolbox").ok


def test_a_missing_toolbox_is_named_rather_than_assumed():
    """A worker built without the toolbox stage. The box would come up and the harness would not
    be there — reported here rather than as 'claude: not found' inside an agent pass."""
    proof = prove("acme", "img", _probes(toolbox_stamp=lambda: {}))

    finding = next(f for f in proof.findings if f.check == "toolbox")
    assert not finding.ok
    assert "toolbox" in finding.message.lower()


@pytest.mark.parametrize("missing,expect", [
    ("sh", "shell"),
    ("git", "git"),
    ("workspace-writable", "writ"),
])
def test_each_contract_item_fails_by_name(missing, expect):
    """"any image your CI uses" is false, and the contract is what makes the falseness checkable.
    A distroless image has neither a shell nor a keep-alive."""
    proof = prove("acme", "img",
                  _probes(contract=lambda image: {missing: f"{missing} is not usable"}))

    finding = next(f for f in proof.findings if f.check == "contract")
    assert not finding.ok
    assert missing in finding.message
    assert expect in (finding.message + finding.remedy).lower()


def test_a_failing_setup_names_the_command_and_its_output():
    """The most common failure for a client whose stack is not the box's, and the one whose exit
    code the job path used to discard entirely."""
    def _run(cmd):
        return (1, "error NU1301: Unable to load the service index") if "restore" in cmd else (0, "")

    proof = prove("acme", "img", _probes(
        setup_commands=lambda: ["dotnet restore"], run_in_box=_run))

    finding = next(f for f in proof.findings if f.check == "setup")
    assert not finding.ok
    assert "dotnet restore" in finding.message
    assert "NU1301" in finding.message


def test_setup_stops_before_validate():
    """Validating against an environment that failed to build produces a second, misleading error
    stacked on the real one."""
    ran: list[str] = []

    def _run(cmd):
        ran.append(cmd)
        return (1, "boom") if "install" in cmd else (0, "")

    prove("acme", "img", _probes(
        setup_commands=lambda: ["pip install -q pytest"],
        validate_commands=lambda: {"test": "pytest -q"},
        run_in_box=_run))

    assert "pytest -q" not in ran, ran


def test_a_failing_validation_names_which_one():
    # No setup command here: the default one is `pip install -q pytest`, which CONTAINS "pytest"
    # and would trip a naive matcher — setup would fail and validate would never run. My first
    # version of this test did exactly that.
    def _run(cmd):
        return (1, "3 failed") if cmd.startswith("pytest") else (0, "")

    proof = prove("acme", "img", _probes(
        setup_commands=lambda: [],
        validate_commands=lambda: {"test": "pytest -q", "lint": "ruff check ."},
        run_in_box=_run))

    finding = next(f for f in proof.findings if f.check == "validate")
    assert not finding.ok
    assert "test" in finding.message and "3 failed" in finding.message


def test_an_unreachable_harness_endpoint_is_caught_here():
    """`--version` opens no TLS connection, so a corporate proxy, an intercepting CA or an egress
    policy all pass a smoke test and kill the first real agent call. Still zero tokens."""
    proof = prove("acme", "img",
                  _probes(harness_reachable=lambda: (False, "TLS handshake failed: unknown CA")))

    finding = next(f for f in proof.findings if f.check == "network")
    assert not finding.ok
    assert "unknown CA" in finding.message
    assert "proxy" in finding.remedy.lower() or "ca" in finding.remedy.lower()


# ── the promise: no harness tokens are spent ────────────────────────────────────────────────────

def test_proving_never_invokes_the_agent():
    """The whole point of proving before the first ticket. A proof that costs an agent pass is a
    ticket with extra steps."""
    ran: list[str] = []

    prove("acme", "img", _probes(run_in_box=lambda cmd: (ran.append(cmd), (0, ""))[1]))

    for cmd in ran:
        assert "-p " not in cmd, f"the harness was asked to DO something: {cmd}"
        assert "--permission-mode" not in cmd, cmd


# ── validity: the proof expires when the ground moves (D5's input) ──────────────────────────────

def test_a_proof_is_valid_for_what_it_was_taken_against():
    from openfactory.box_prove import is_valid

    proof = prove("acme", "img", _probes())

    assert is_valid(proof, digest=proof.digest, toolbox=proof.toolbox,
                    commands_hash=proof.commands_hash)


@pytest.mark.parametrize("field", ["digest", "toolbox", "commands_hash"])
def test_any_of_the_three_changing_expires_it(field):
    """Configuration is a declaration; a proof is a fact — and a fact about a world that can move.
    A checkbox ages silently, which is the difference this makes."""
    from openfactory.box_prove import is_valid

    proof = prove("acme", "img", _probes())
    args = {"digest": proof.digest, "toolbox": proof.toolbox,
            "commands_hash": proof.commands_hash}
    args[field] = "something-else"

    assert not is_valid(proof, **args)


def test_a_failed_proof_is_never_valid():
    from openfactory.box_prove import is_valid

    proof = prove("acme", "img", _probes(resolve_digest=lambda image: None))

    assert not is_valid(proof, digest=proof.digest, toolbox=proof.toolbox,
                        commands_hash=proof.commands_hash)


# ── the box failing to start is its own cause ───────────────────────────────────────────────────

def test_a_box_that_does_not_start_is_not_reported_as_a_setup_failure():
    """Found on the first real run, twice over. A leftover container from a crashed proof made the
    next `prepare` refuse — correctly, that guard shipped this morning — and the proof then blamed
    the CLIENT's `setup:`, with a remedy about private package feeds. One cause, one actionable
    line, and the line has to be the true one."""
    proof = prove("acme", "img", _probes(
        run_in_box=lambda cmd: (1, "the box could not be started: name is already in use")))

    finding = next(f for f in proof.findings if f.check == "box")
    assert not finding.ok
    assert "already in use" in finding.message
    assert "docker ps" in finding.remedy
    assert not any(f.check == "setup" for f in proof.findings), (
        "the client's commands were blamed for a container that never started"
    )


def test_the_box_check_comes_before_the_client_s_commands():
    """Ordering is the whole of it: asking `true` first costs nothing and separates 'your image is
    wrong' from 'our container did not start'."""
    order = [f.check for f in prove("acme", "img", _probes()).findings]

    assert order.index("box") < order.index("setup"), order


# ── C-35 (#76): the proof must cover the gates a DIFF reaches, not just untouched main ──────────
#
# FOUND LIVE (fx-mono#1, 2026-08-04). The proof ran `applicable_validations([])` — the repo-wide
# gates only, because untouched main touches no component. But `stack: python` opts a component
# into the preset's lint/security/type gates, which fire the moment a diff reaches it. Those tools
# were never proven to exist: the job ran, the agent worked 47 turns, and then `ruff: not found`
# (exit 127) failed the gates at full agent price, looking like an incompetent executor rather
# than a box missing a tool the project had declared all along.

def _manifest_with_components():
    from openfactory.contracts import Component, Manifest

    return Manifest(
        setup=["pip install -q pytest"],
        validate={"test": "pytest -q"},
        components={
            "functions": Component(path="functions/**", stack="python"),
            "api": Component(path="services/api/**", stack="python",
                             validate={"test": "pytest -q services/api"}),
        },
    )


def test_the_union_includes_the_presets_gates_the_repo_wide_list_cannot_see():
    """Every preset gate the repo-wide list does not already carry — `lint` and `security` are the
    two that failed with exit 127 on fx-mono#1, invisible to a proof that only knew `test`."""
    from openfactory.box_prove import component_gates
    from openfactory.policy import load_preset

    gates = component_gates(_manifest_with_components())

    # a preset gate the repo-wide list does not NAME at all: for one it does name, precedence
    # makes the repo-wide command the effective one, and that was already proven
    repo_wide = {"test": "pytest -q"}
    unseen = {g for g in load_preset("python").get("validate", {}) if g not in repo_wide}
    assert unseen, "the python preset declares no gate beyond the repo-wide one — check the preset"
    for gate in unseen:
        assert f"functions:{gate}" in gates, f"the preset's {gate!r} gate is invisible to the proof"


def test_a_repo_wide_gate_is_not_proven_twice():
    """`test: pytest -q` already ran in the repo-wide pass — repeating it per component costs a
    full test run each and proves nothing new."""
    from openfactory.box_prove import component_gates

    gates = component_gates(_manifest_with_components())

    assert "functions:test" not in gates, "the repo-wide command was queued again per component"
    assert gates["api:test"] == "pytest -q services/api", "the component's OWN override must run"


def test_two_components_declaring_the_same_gate_NAME_both_survive():
    """Keyed by origin, never by gate name: a dict keyed `test` would prove one and silently drop
    the other — the same collapse two same-numbered cards forced out of `columns()`."""
    from openfactory.box_prove import component_gates
    from openfactory.contracts import Component, Manifest

    gates = component_gates(Manifest(components={
        "a": Component(path="a/**", stack="python", validate={"test": "pytest a"}),
        "b": Component(path="b/**", stack="python", validate={"test": "pytest b"}),
    }))

    assert sorted(c for k, c in gates.items() if k.endswith(":test")) == ["pytest a", "pytest b"]


def test_a_component_gate_the_box_CANNOT_RUN_fails_the_proof():
    """THE fx-mono failure, caught before pickup instead of 47 turns into a paid pass."""
    from openfactory.box_prove import prove

    ran: list[str] = []

    def _run(cmd: str) -> tuple[int, str]:
        ran.append(cmd)
        if "ruff" in cmd:
            return 127, "sh: 1: ruff: not found"
        return 0, ""

    proof = prove("p", "img", _probes(run_in_box=_run,
                                      component_gate_commands=lambda: {"functions:lint":
                                                                       "ruff check ."}))

    assert not proof.ok
    bad = [f for f in proof.findings if not f.ok]
    assert bad and bad[0].check == "component gates"
    assert "ruff" in bad[0].message and "setup:" in bad[0].remedy


def test_a_component_gate_that_RUNS_and_fails_does_not_block_pickup():
    """The asymmetry that keeps this safe to ship: `pytest -q services/api` exits 5 when that
    component has no tests yet, and this proof is a PRECONDITION OF PICKUP — demanding green here
    would stop a working deployment from picking up any work at all."""
    from openfactory.box_prove import prove

    def _run(cmd: str) -> tuple[int, str]:
        if "services/api" in cmd:
            return 5, "no tests ran"
        return 0, ""

    proof = prove("p", "img", _probes(run_in_box=_run,
                                      component_gate_commands=lambda: {
                                          "api:test": "pytest -q services/api"}))

    assert proof.ok, [f.message for f in proof.findings if not f.ok]


def test_the_proof_expires_when_a_COMPONENT_gate_changes():
    """Covering the gates without covering them in the hash would leave a client free to declare a
    component needing a tool the box has never seen, with a proof that still reads valid."""
    from openfactory.box_prove import _hash_commands

    base = _hash_commands(["setup"], {"test": "pytest"}, {"a:lint": "ruff check ."})
    changed = _hash_commands(["setup"], {"test": "pytest"}, {"a:lint": "ruff check . --fix"})
    added = _hash_commands(["setup"], {"test": "pytest"},
                           {"a:lint": "ruff check .", "a:type": "mypy ."})

    assert base != changed and base != added


def test_a_project_with_no_components_is_unchanged():
    from openfactory.box_prove import component_gates
    from openfactory.contracts import Manifest

    assert component_gates(Manifest(validate={"test": "pytest -q"})) == {}


def test_only_a_gate_that_did_not_RUN_counts_as_missing():
    from openfactory.box_prove import _cannot_run

    assert _cannot_run(127, "sh: 1: ruff: not found")
    assert _cannot_run(1, "/bin/sh: mypy: command not found")
    assert not _cannot_run(0, "")
    assert not _cannot_run(5, "no tests ran")
    assert not _cannot_run(1, "2 files would be reformatted")


def test_the_harness_smoke_test_goes_THROUGH_the_boxs_own_seam():
    """FOUND LIVE (fx-jira on `node:22`, 2026-08-05). `harness_path` (ADR-0037 D2a) exists
    because `PATH` cannot be relied on inside a CLIENT's image — and this proof asked for the
    BARE name, so it smoke-tested a command the real run never issues. On the framework's own
    image both happen to work; on a genuine client image the bare name is `claude: not found`,
    and the gate then refuses a box that would have run perfectly.

    A false negative here is not cosmetic: the proof is a PRECONDITION OF PICKUP, so it stops
    the project from being worked at all."""
    import inspect

    from openfactory import box_prove

    src = inspect.getsource(box_prove.probes_for) if hasattr(box_prove, "probes_for") \
        else inspect.getsource(box_prove)
    assert "box.harness_path(" in src, (
        "the proof resolves the harness by bare name again — it is no longer smoke-testing what "
        "the executor actually invokes")


def test_the_smoke_test_runs_whatever_harness_name_returns():
    """The seam only helps if the command is built from it."""
    from openfactory.box_prove import prove

    ran: list[str] = []
    proof = prove("p", "img", _probes(
        run_in_box=lambda cmd: (ran.append(cmd), (0, "claude 2.1.0"))[1],
        harness_name=lambda: "/opt/openfactory-toolbox/claude"))

    assert proof.ok, [f.message for f in proof.findings if not f.ok]
    assert any(c.startswith("/opt/openfactory-toolbox/claude --version") for c in ran), ran


# ── the stack the platform cannot know (pilot, 2026-08-13) ──────────────────────────────────────

def test_a_missing_binary_names_the_stack_choice_not_the_shells_words():
    """The first real pilot proof died with `sh: 1: uv: not found` — a shell's vocabulary, no
    remedy, the user blocked at the very start. The platform cannot know the stack, so the
    remedy must name the one choice that works for ANY stack: box.image, or change the command."""
    proof = prove("acme", "openfactory-python:sandbox", _probes(
        setup_commands=lambda: ["uv sync --all-extras"],
        run_in_box=lambda cmd: (127, "sh: 1: uv: not found") if cmd.startswith("uv")
        else (0, "")))

    setup = next(f for f in proof.findings if f.check == "setup")
    assert not setup.ok
    assert "`uv` does not exist in this image" in setup.remedy
    assert "box.image" in setup.remedy
    assert "openfactory-python:sandbox" in setup.remedy


def test_a_command_that_runs_and_fails_keeps_the_build_remedy():
    """Ran-and-failed is the client's build; only could-not-run is the image's business."""
    proof = prove("acme", "img", _probes(
        run_in_box=lambda cmd: (2, "3 tests failed") if cmd.startswith("pytest")
        else (0, "")))

    validate = next(f for f in proof.findings if f.check == "validate")
    assert not validate.ok
    assert "box.image" not in validate.remedy


def test_a_validate_gate_with_a_missing_binary_gets_the_image_remedy():
    proof = prove("acme", "img", _probes(
        validate_commands=lambda: {"test": "dotnet test --nologo"},
        run_in_box=lambda cmd: (127, "dotnet: not found") if cmd.startswith("dotnet")
        else (0, "")))

    validate = next(f for f in proof.findings if f.check == "validate")
    assert not validate.ok
    assert "`dotnet` does not exist in this image" in validate.remedy
