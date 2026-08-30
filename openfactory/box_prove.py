"""`openfactory box prove` — the box is proven before any agent runs (ADR-0037 D3).

The product owner asked whether there should be a per-client box pre-configuration before pulling
from TO-DO. There should be something stronger: **configuration is a declaration, a proof is a
fact.**

The box must satisfy the CLIENT's stack and the FRAMEWORK's harness at once, and it was the only
part of onboarding with no step of its own — it first appeared at the first ticket, which is the
worst moment to find it wrong, because by then an agent is running and money is being spent inside
an environment that cannot work.

WHAT A PROOF IS. Resolve the image's tag to a digest; check the image contract item by item; check
that the toolbox can even execute in that image; run the client's own `setup:` and then `validate:`
against untouched `main`; check the harness endpoint is reachable through whatever network the box
has. Green means *your tests passed inside the factory* — and it costs **zero harness tokens**,
because nothing here asks an agent to do anything.

ORDER MATTERS AND STOPPING MATTERS. An unpullable image would make the next six checks fail for the
same reason and report it six different ways; a `setup:` that fails makes `validate:` a second,
misleading error stacked on the real one. So the sequence stops at the first fault whose successors
depend on it, and every finding carries its own remedy — `doctor`'s standing bar: one cause, one
actionable line.

THE VARIANT CHECK IS THE ONE THAT PAYS FOR THE FEATURE. Measured on the shipped binary: `ldd
claude.exe` gives `ld-linux-<arch>.so.1`, i.e. glibc. An Alpine or musl-based client image cannot
execute it, and the failure is the dynamic loader's *no such file or directory* — which names the
wrong thing and sends somebody hunting a file that is sitting in front of them. Catching it here
turns an afternoon into a sentence.

PROBES ARE INJECTED, exactly as in `doctor.py`, so every branch is reachable in a test without
Docker, a network or a client repository. A prover that could only be exercised against a healthy
box is a prover nobody can show reports illness.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import shlex
from collections.abc import Callable
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path

from openfactory import namespace
from openfactory.orchestrator.validation import advisory_gates, gate_commands

log = logging.getLogger("openfactory.box_prove")

#: Where proofs are kept. Beside the registry, because a proof is deployment state with exactly the
#: same lifetime: it outlives the image and belongs to the installation, not to the client's repo.
PROOF_DIR = Path(os.environ.get("OPENFACTORY_PROOFS") or "/var/lib/openfactory/proofs")


@dataclass
class Finding:
    check: str
    ok: bool
    message: str
    #: Required whenever `ok` is False. A finding with no remedy is a symptom handed to the one
    #: person who does not yet know the system.
    remedy: str = ""
    #: A gate the PROJECT declared advisory. Not-ok and not a failure: recorded, rendered and
    #: reported, and deliberately unable to hold a pickup. See `Proof.failures`.
    advisory: bool = False

    @property
    def mark(self) -> str:
        """The three-state label every renderer uses, spelled once.

        Three renderers printed `ok if f.ok else FAIL`, and a fourth state added in one of them
        would have been three states in one place and two in the others — with `warn` rendered as
        `FAIL` on the surface a client actually reads."""
        return "ok" if self.ok else ("warn" if self.advisory else "FAIL")


@dataclass
class Proof:
    """What was proven, and what it was proven AGAINST.

    The three `against` fields are the whole of D5: a proof is a fact about a world that can move,
    so it has to carry enough to notice when it has. A checkbox ages silently; this expires."""

    project: str
    image: str
    ok: bool = False
    digest: str = ""
    toolbox: str = ""
    commands_hash: str = ""
    #: WHAT THE BOX OFFERED THE CLIENT'S COMMANDS — the image's own `/etc/openfactory-toolchain`
    #: line (python, node, git, gh, uv, the OS). It exists because a compose deployment BUILDS
    #: its image, so the digest above moves on every `--build` even when nothing a client's
    #: `setup:` depends on has changed. Empty = the image does not carry one (a client's own
    #: toolbox image), and then the digest is the only thing there is to compare.
    toolchain: str = ""
    findings: list[Finding] = field(default_factory=list)
    at: str = ""

    def failures(self) -> list[Finding]:
        """What makes this proof not ok — and therefore what holds a pickup.

        ADVISORY FINDINGS ARE NOT IN HERE, AND THAT IS #11's SECOND HALF. `advisory` meant "the
        merge gate never consults it" and nothing else: `box prove` demanded rc==0 from every
        repo-wide gate, `proof.ok` went False, and `gate_reason` held every card on the project. A
        gate the client declared advisory had a decidedly non-advisory effect.

        The station twenty lines below this one already draws exactly this line for per-component
        gates — *"a per-component gate can be legitimately non-green on untouched main … and this
        proof is a PRECONDITION OF PICKUP, so demanding green here would stop a working deployment
        from picking up any work at all"*. An advisory gate is legitimately non-green by the
        project's own declaration. This is that principle, one station up.

        The proof does not IGNORE them: they are in `findings`, they render as `warn`, and
        `advisories()` returns them. Proving is a measurement; holding a pickup is an
        authorisation, and this codebase separates the two everywhere else."""
        return [f for f in self.findings if not f.ok and not f.advisory]

    def advisories(self) -> list[Finding]:
        """Gates that failed and were declared advisory. Reported, never blocking — a proof that
        hid a red gate would prove less, which is the objection this answers rather than dodges."""
        return [f for f in self.findings if not f.ok and f.advisory]


@dataclass
class Probes:
    """Everything `prove` needs to know about the world, as callables it can be handed."""

    #: The image's `sha256:` digest, or None when it cannot be pulled at all.
    resolve_digest: Callable[[str], str | None]
    #: `(os, arch, libc)` of the image — what has to EXECUTE the toolbox, which is not the worker.
    image_platform: Callable[[str], tuple[str, str, str]]
    #: The live toolbox's stamp: `{variant, harnesses}`, or `{}` when there is none.
    toolbox_stamp: Callable[[], dict]
    #: `{requirement: what is wrong}` for the image contract. Empty means satisfied.
    contract: Callable[[str], dict]
    #: Run one command inside the box: `(exit_code, output)`.
    run_in_box: Callable[[str], tuple[int, str]]
    #: `(reachable, detail)` for the harness endpoint, FROM INSIDE the box.
    harness_reachable: Callable[[], tuple[bool, str]]
    setup_commands: Callable[[], list[str]]
    validate_commands: Callable[[], dict[str, str]]
    harness_name: Callable[[], str]
    #: The route the configured harness will actually take — Anthropic direct, a client's own
    #: Bedrock account, a gateway fronting Foundry. Defaults to the Anthropic-direct route so an
    #: older `Probes` still builds.
    auth_route: Callable[[], object] = lambda: _default_route()
    #: `{name: value}` for the given names AS SEEN INSIDE THE BOX. Values never leave the box —
    #: only presence is ever read (see `AuthRoute.missing`), and only names are ever printed.
    #:
    #: None means "this Probes cannot see inside the box", which is NOT the same as "the variables
    #: are absent". Defaulting to `{}` would read every route as missing every credential and
    #: refuse pickup for deployments that are configured correctly.
    env_in_box: Callable[[tuple[str, ...]], dict[str, str] | None] = lambda _names: None
    #: The same, streaming each line to a callback as it arrives. `None` = this probe set cannot
    #: stream, which is the honest answer for every test double and the reason `prove` falls back
    #: explicitly instead of catching a signature error.
    #:
    #: Both live sandboxes already stream (`worktree.py`/`container.py` take `on_output`, and
    #: `test_the_box_transmits_while_it_runs.py` asserts it) — `box_prove` was simply the one
    #: caller that never passed the callback, so the one command that IS the factory coming alive
    #: was the one command that showed nothing while it ran.
    run_streaming: Callable[[str, Callable[[str], None]], tuple[int, str]] | None = None
    #: EVERY gate that could ever run, `{where it comes from: command}` — the per-component ones
    #: the repo-wide list cannot see (C-35). Defaults to nothing so an older Probes still builds.
    component_gate_commands: Callable[[], dict[str, str]] = dict
    #: Which repo-wide gates the project declared advisory. Defaults to none so an older `Probes`
    #: still builds — and so a caller that does not know about the flag proves exactly what it
    #: proved before rather than silently loosening.
    advisory_gates: Callable[[], frozenset[str]] = frozenset
    #: The image's own toolchain line (`/etc/openfactory-toolchain`), or "" when it carries none.
    #: Defaulted, like every probe below the required ones: an older `Probes` still builds, and a
    #: box that does not answer falls back to comparing digests.
    toolchain_stamp: Callable[[str], str] = lambda _img: ""


def component_gates(manifest) -> dict[str, str]:
    """`{label: command}` for every gate a diff could ever trigger BEYOND the repo-wide ones.

    WHY THIS EXISTS (C-35, #76 — found live on fx-mono#1, 2026-08-04). The proof ran
    `applicable_validations([])`: the repo-wide gates only, because untouched `main` touches no
    component. But `stack: python` opts a component into the platform's preset, whose lint /
    security / type gates fire the moment a diff reaches that component — and those tools were
    never proven to EXIST. The job ran, the agent worked, and 47 turns later `ruff: not found`
    (exit 127) failed the gates, at full agent price, looking exactly like an incompetent
    executor rather than a box missing a tool the project had declared all along.

    Keyed by ORIGIN rather than by gate name, deliberately: two components can both declare
    `test:` with different commands, and a dict keyed by `test` would prove one and silently drop
    the other — the same collapse `columns()` had to stop doing for two same-numbered cards."""
    from openfactory.policy import load_preset

    repo_wide = dict(getattr(manifest, "validation", {}) or {})
    out: dict[str, str] = {}
    for comp_name, comp in (getattr(manifest, "components", {}) or {}).items():
        preset = load_preset(getattr(comp, "stack", "") or "").get("validate", {}) or {}
        # the same precedence `applicable_validations` applies for a real diff: a repo-wide value
        # overrides its preset, and the component's own overrides both. Proving a command the
        # ticket would never run is a false failure.
        effective = {**preset, **repo_wide, **(getattr(comp, "validation", {}) or {})}
        for gate, cmd in effective.items():
            if repo_wide.get(gate) == cmd:
                continue  # already proven by the repo-wide pass
            out[f"{comp_name}:{gate}"] = cmd
    return out


def _hash_commands(setup: list[str], validate: dict[str, str],
                   components: dict[str, str] | None = None) -> str:
    """A stable fingerprint of what the client asked to be run.

    Sorted, because a reordered `validate:` mapping is the same environment — and an unstable hash
    would expire every proof on every read, which is the same as having none.

    THE HASH COVERS EXACTLY WHAT THE PROOF COVERS. Adding the component gates to the proof without
    adding them here would leave a client free to declare a component needing a tool the box has
    never seen, with a proof that still reads valid — the very hole C-35 closes, reopened one
    level up."""
    payload = json.dumps({"setup": list(setup), "validate": dict(sorted(validate.items())),
                          "components": dict(sorted((components or {}).items()))},
                         sort_keys=True)
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


def _now() -> str:
    from datetime import UTC, datetime

    return datetime.now(UTC).isoformat()


#: What a shell says when the binary is not there. `sh` and `bash` both exit 127 for it, but the
#: message is read too: a wrapper (`make lint`, `npm run lint`) exits with ITS own code while the
#: missing tool is only named in the output.
_NOT_FOUND_MARKERS = ("command not found", "not found", "no such file or directory",
                      "is not recognized as an internal or external command")


def _cannot_run(rc: int, out: str) -> bool:
    """Whether this gate did not RUN, as opposed to running and failing.

    The distinction is the whole point of the component-gate check: a red test suite on untouched
    main is the project's business, while a missing binary is the box's — and only the second may
    hold up pickup."""
    if rc == 127:
        return True
    text = (out or "").lower()
    return rc != 0 and any(m in text for m in _NOT_FOUND_MARKERS)


def _missing_tool_remedy(cmd: str, image: str) -> str:
    """The stack-agnostic sentence for a command whose binary the image does not carry.

    The platform CANNOT know the stack (the operator, pilot 2026-08-13: "there is no way
    for us to know what each client's stack will be") — so a bare `sh: 1: uv: not found` is the
    user blocked at the very start with a shell's vocabulary. The two remedies below are the only
    two that exist for ANY stack, and both are the client's to choose."""
    head = (cmd.split() or ["?"])[0]
    return (f"`{head}` does not exist in this image ({image}). The platform cannot know your "
            f"stack — name it: declare an image that carries your toolchain (`box.image` in "
            f"the registry, then re-run the proof), or change this command to one the image "
            f"can run")


def _variant_remedy(variant: str, image: tuple[str, str, str]) -> str:
    """Which of os / arch / libc actually differs, and what to do about that one."""
    have = variant.split("-")
    want_os, want_arch, want_libc = image
    if len(have) != 3:
        return f"rebuild the worker's toolbox for {want_os}-{want_arch}-{want_libc}"
    have_os, have_arch, have_libc = have
    if have_libc != want_libc:
        # The example has to match the libc that is NEEDED, or the remedy sends somebody to the
        # wrong base image — which the first two versions of this message both managed to do.
        family = {"glibc": "debian, ubuntu", "musl": "alpine"}.get(have_libc, have_libc)
        return (
            f"a {want_libc} image cannot execute {have_libc}-linked binaries — the dynamic loader "
            "fails with 'no such file or directory', naming the wrong thing entirely. Use a "
            f"{have_libc} base image ({family}), or build the toolbox for {want_libc}"
        )
    if have_arch != want_arch:
        return (
            f"the toolbox is {have_arch} and the image is {want_arch}. Build the worker for "
            f"{want_arch} (`docker build --platform linux/{want_arch}`), or use a {have_arch} "
            "image — emulation would run, slowly, and only if qemu is installed"
        )
    return (
        f"the toolbox was built on {have_os} and the box runs {want_os}. Build the worker image "
        f"on {want_os} — a toolbox assembled on a developer's machine cannot be mounted into a "
        "Linux container"
    )


def prove(project: str, image: str, p: Probes, *,
          on_stage: Callable[[str, str], None] | None = None) -> Proof:
    """Prove this box can build and test this project. No agent is invoked.

    `on_stage(kind, text)` REPORTS WHILE IT HAPPENS, and it is not decoration. This command pulls
    an image, installs a client's dependencies and runs their whole test suite — up to 1800s per
    command — and until this existed it printed NOTHING until every station had finished. The
    scene it is built for is a room of the client's developers watching their factory come up for
    the first time; a terminal that sits blank for four minutes is indistinguishable from one that
    has hung, and somebody reaches for Ctrl-C. `_in_box` streams the command's own output through
    the same callback, so what the room sees is their build, live, not a spinner.

    `None` keeps the old behaviour exactly, so every existing caller and every test is unchanged.

      kind      meaning
      ────────  ──────────────────────────────────────────────────────────────────────────
      `start`   a station has begun; `text` names it
      `line`    one line of output from inside the box
      `done`    a station finished; `text` is its one-line result
    """
    def _say(kind: str, text: str) -> None:
        """Never let the reporting break the proof — a screen is not a result."""
        if on_stage is None:
            return
        try:
            on_stage(kind, text)
        except Exception:  # noqa: BLE001 — a broken renderer must not fail a good box
            log.debug("the box-prove reporter raised on %s", kind, exc_info=True)

    setup, validate = p.setup_commands(), p.validate_commands()
    per_component = p.component_gate_commands()
    proof = Proof(project=project, image=image, at=_now(),
                  commands_hash=_hash_commands(setup, validate, per_component))

    # EVERY STATION REPORTS, AND NOBODY HAS TO REMEMBER TO MAKE IT. Instrumenting the fourteen
    # `findings.append` sites by hand would have worked today and rotted at the fifteenth: a new
    # station would land silent, and silence is the failure this whole change is about. The list
    # itself announces, so a station cannot be added without being visible.
    class _Reporting(list):
        def append(self, finding):  # type: ignore[override]
            super().append(finding)
            mark = getattr(finding, "mark", "ok" if getattr(finding, "ok", False) else "FAIL")
            _say("done", f"{mark}  {getattr(finding, 'check', '?')}  "
                         f"{getattr(finding, 'message', '')}")

    proof.findings = _Reporting(proof.findings)

    def _run(command: str, *, label: str) -> tuple[int, str]:
        """One command inside the box, streamed when there is somebody watching.

        The fallback is EXPLICIT rather than a `TypeError` handler around a wider call: a probe
        set that cannot stream is an ordinary, correct thing (every test double is one), and
        catching the exception a wrong signature would raise is how a real defect gets to look
        like a supported configuration."""
        _say("start", label)
        if on_stage is not None and p.run_streaming is not None:
            return p.run_streaming(command, lambda line: _say("line", line))
        return p.run_in_box(command)

    # ── the image ───────────────────────────────────────────────────────────────────────────────
    _say("start", f"pulling {image}")
    digest = p.resolve_digest(image)
    if not digest:
        proof.findings.append(Finding(
            "image", False,
            f"the image {image!r} could not be pulled, so nothing below could be checked",
            "check the reference and whether this deployment can authenticate to that registry — "
            "the pull happens on the WORKER's daemon, not on your machine, so a `docker login` you "
            "did locally does not carry",
        ))
        return proof  # everything after this would fail for one reason and say it six ways
    proof.digest = digest
    # Recorded beside the digest, never instead of it: this is what makes a REBUILD of the same
    # image distinguishable from a CHANGE to it (see `Proof.toolchain` and `gate_reason`).
    try:
        proof.toolchain = (p.toolchain_stamp(image) or "").strip()
    except Exception as exc:  # noqa: BLE001 — a stamp is an optimisation, never a reason to fail
        log.info("could not read %s's toolchain line (%s) — the proof pins its digest alone",
                 image, str(exc)[:120])
    proof.findings.append(Finding("image", True, f"{image} → {digest[:19]}…"))

    # ── can the toolbox even run in it ──────────────────────────────────────────────────────────
    stamp = p.toolbox_stamp()
    variant = stamp.get("variant") or ""
    proof.toolbox = variant
    img_os, img_arch, img_libc = p.image_platform(image)
    wanted = f"{img_os}-{img_arch}-{img_libc}"
    if not variant:
        proof.findings.append(Finding(
            "toolbox", False,
            "this worker has no harness toolbox, so the box would start with no agent CLI in it",
            "the toolbox is baked by the worker image's `toolbox` build stage and copied to its "
            "volume on boot — rebuild the worker, or check the boot log for why populate() found "
            "nothing",
        ))
    elif variant != wanted:
        # NAME THE DIMENSION THAT DIFFERS. The first version of this templated the libc sentence
        # onto every mismatch and produced "a glibc image cannot run glibc-linked binaries",
        # which is nonsense and exactly the kind of remedy that sends somebody the wrong way.
        proof.findings.append(Finding(
            "toolbox", False,
            f"the toolbox is built for {variant} and this image is {wanted} — the harness "
            "binaries cannot execute in it",
            _variant_remedy(variant, (img_os, img_arch, img_libc)),
        ))
    else:
        harnesses = ", ".join(stamp.get("harnesses") or []) or "nothing"
        proof.findings.append(Finding("toolbox", True, f"{variant} — {harnesses}"))

    # ── the image contract ──────────────────────────────────────────────────────────────────────
    broken = p.contract(image)
    if broken:
        proof.findings.append(Finding(
            "contract", False,
            "the image cannot host a box: "
            + "; ".join(f"{k} ({v})" for k, v in sorted(broken.items())),
            "a box needs a POSIX shell at /bin/sh, a keep-alive, git, a writable HOME and a "
            "writable /workspace. A distroless or scratch image has neither a shell nor a "
            "keep-alive and cannot be used; for the rest, install the missing tool in your image",
        ))
    else:
        proof.findings.append(Finding("contract", True, "shell, git and a writable workspace"))

    if proof.failures():
        return proof  # running commands in a box that cannot host one proves nothing

    # ── does the box actually START ─────────────────────────────────────────────────────────────
    # Asked before anything is blamed on the client's commands. A leftover container from a crashed
    # run reported itself as a failing `setup:`, with a remedy about private package feeds.
    rc, out = p.run_in_box("true")
    if rc != 0:
        proof.findings.append(Finding(
            "box", False, _tail(out) or "the box did not start",
            "this is the container itself, before any of your commands ran — a name collision "
            "with a leftover container, an image that cannot keep alive, or a daemon that refused "
            "the run. `docker ps -a` and remove anything named openfactory-<project>-*",
        ))
        return proof
    proof.findings.append(Finding("box", True, "the box starts and runs commands"))

    # ── the client's own setup, then their own gates ────────────────────────────────────────────
    for cmd in setup:
        rc, out = _run(cmd, label=f"setup: {cmd}")
        if rc != 0:
            # A MISSING BINARY IS THE BOX'S BUSINESS, and its remedy is different in kind from
            # a command that ran and failed: the second is the client's build, the first is a
            # stack the image does not speak — and the platform cannot know the stack, so the
            # remedy has to name the choice instead of leaking the shell's "not found"
            # ONE CAUSE WAS ASSERTED WHERE THREE ARE COMMON. This read "a private feed needing
            # credentials is the usual cause" for EVERY setup failure — and the pilot's failure
            # was a command that runs in a subdirectory of the client's own repository, whose
            # output says so in the tool's own words. A remedy that names the wrong cause with
            # confidence is worse than one that names the candidates (2026-08-14).
            remedy = (_missing_tool_remedy(cmd, image) if _cannot_run(rc, out) else
                      "this is your `setup:` running in your image, from the repository ROOT. "
                      "Three usual causes, and the output above says which: a command that "
                      "expects a different working directory (your CI may `cd` first — give it "
                      "the path, or declare that directory as a component); a file it needs "
                      "that is not in the repository; or a private feed needing credentials, "
                      "whose environment variables go in the registry's `box.env`")
            proof.findings.append(Finding(
                "setup", False, f"`{cmd}` exited {rc}\n{_tail(out)}", remedy))
            return proof  # validating a broken environment stacks a second, misleading error
    proof.findings.append(Finding("setup", True, f"{len(setup)} command(s)"))

    advisory = p.advisory_gates()
    failed_gates: list[str] = []
    advisory_gates_failed: list[str] = []
    cannot_run: list[str] = []
    for name, cmd in sorted(validate.items()):
        rc, out = _run(cmd, label=f"{name}: {cmd}")
        if rc == 0:
            continue
        line = f"{name}: `{cmd}` exited {rc}\n{_tail(out)}"
        # A COMMAND THE BOX CANNOT EXECUTE IS NOT ADVISORY, whatever the project declared. The
        # flag says "a finding here should not stop the work"; it cannot say "this image has the
        # tool" when the shell just said it does not. That is the same asymmetry the per-component
        # station below draws, and it is what keeps `advisory: true` from becoming a way to prove
        # a box that cannot run its own gates.
        if name in advisory and not _cannot_run(rc, out):
            advisory_gates_failed.append(line)
            continue
        failed_gates.append(line)
        if _cannot_run(rc, out):
            cannot_run.append(cmd)
    if advisory_gates_failed:
        # RECORDED BEFORE THE BLOCKING ONES, so a proof that stops below still carries it. This is
        # the half of #11 that answers "a proof that ignores a red gate proves less": it is not
        # ignored, it is reported — it simply does not authorise a halt.
        proof.findings.append(Finding(
            "validate", False, "\n".join(advisory_gates_failed),
            "declared `advisory: true`, so this does NOT hold pickup and does NOT block a merge — "
            "it is debt this project has chosen to carry visibly. Fix it or drop the gate; leaving "
            "it is a decision, not an oversight",
            advisory=True))
    if failed_gates:
        remedy = ("these are YOUR gates, on untouched `main`, inside the box. Failing here "
                  "means the box cannot reproduce your build — fix that before a ticket does "
                  "it for you")
        if cannot_run:
            remedy = _missing_tool_remedy(cannot_run[0], image)
        proof.findings.append(Finding(
            "validate", False, "\n".join(failed_gates), remedy))
        return proof
    # THE COUNT SAYS WHAT WAS ACTUALLY GREEN, never the total. Reporting "12 gate(s) green" when
    # one of them failed advisorily is the sentence a reader trusts and should not.
    green = len(validate) - len(advisory_gates_failed)
    proof.findings.append(Finding(
        "validate", True, f"{green} gate(s) green on untouched main"
        + (f"; {len(advisory_gates_failed)} advisory gate(s) failed and did not hold it"
           if advisory_gates_failed else "")))

    # ── the gates a DIFF would reach, which untouched main never does (C-35) ────────────────────
    #
    # EXECUTABILITY ONLY, and the asymmetry is deliberate. A per-component gate can be legitimately
    # non-green on untouched main — `pytest -q services/api` exits 5 when that component has no
    # tests yet — and this proof is a PRECONDITION OF PICKUP, so demanding green here would stop a
    # working deployment from picking up any work at all. What is never legitimate is a command the
    # box cannot execute: that is a tool the project declared and the image does not have, and it
    # is the exact failure this check was written for.
    missing = []
    for label, cmd in sorted(per_component.items()):
        rc, out = _run(cmd, label=f"{label}: {cmd}")
        if _cannot_run(rc, out):
            missing.append(f"{label}: `{cmd}` exited {rc}\n{_tail(out)}")
    if missing:
        proof.findings.append(Finding(
            "component gates", False, "\n".join(missing),
            "these gates run the moment a diff reaches that component — they never run on "
            "untouched main, so nothing had ever checked the tools existed. Install them in "
            "`setup:` (a `stack:` opts the component into that stack's preset gates, tools "
            "included) or drop the gate from the component",
        ))
        return proof
    proof.findings.append(Finding(
        "component gates", True,
        f"{len(per_component)} per-component gate(s) can run in this box"
        if per_component else "none declared beyond the repo-wide gates"))

    # ── the harness: present, and reachable ─────────────────────────────────────────────────────
    name = p.harness_name()
    rc, out = p.run_in_box(f"{name} --version")
    if rc != 0:
        proof.findings.append(Finding(
            "harness", False, f"`{name} --version` exited {rc} inside the box\n{_tail(out)}",
            "the toolbox is mounted read-only at /opt/openfactory-toolbox; check the box's mount "
            "and "
            "that the entry is executable",
        ))
    else:
        proof.findings.append(Finding("harness", True, f"{name} {out.strip()[:40]}"))

    # ── the auth route: does the harness's credential actually ARRIVE inside the box ─────────────
    #
    # A worker that holds `ANTHROPIC_BASE_URL` while `box.env` does not carry it is invisible from
    # the worker's own environment — the route looks configured and the box runs without it. This
    # is the only place that difference can be seen, and it costs nothing to look.
    route = p.auth_route()
    present = p.env_in_box(_route_names(route))
    missing = route.missing(present) if present is not None else []
    if present is None:
        proof.findings.append(Finding(
            "harness auth", True, f"the {route.name} route was not checked inside this box"))
    elif missing:
        proof.findings.append(Finding(
            "harness auth", False,
            f"the {route.name} route is missing {', '.join(missing)} INSIDE the box",
            route.remedy or "name the variable in the project's `box.env` — the registry names "
                            "variables, the worker holds their values",
        ))
    else:
        proof.findings.append(Finding("harness auth", True, f"the {route.name} route is complete"))

    # ── and can the box REACH it ─────────────────────────────────────────────────────────────────
    if not route.endpoint:
        # An honest gap, said out loud rather than probed against a guessed host: a wrong guess
        # here REFUSES pickup for a deployment that works, which is the same damage as the bug
        # this replaced, wearing a helmet.
        proof.findings.append(Finding(
            "network", True,
            f"not proven — no endpoint known for the {route.name} route"
            + (f" ({', '.join(route.unresolved)} is unset)" if route.unresolved else ""),
        ))
    else:
        reachable, detail = p.harness_reachable()
        if not reachable:
            proof.findings.append(Finding(
                "network", False,
                f"the {route.name} endpoint {route.endpoint} is not reachable from inside the "
                f"box: {detail}",
                "`--version` opens no connection, so a proxy, an intercepting CA or an egress "
                "policy passes a smoke test and kills the first real agent call. Set the box's "
                "network (`box.network`) and make sure your image trusts your CA",
            ))
        else:
            proof.findings.append(
                Finding("network", True, f"{route.endpoint} answers ({route.name})"))

    proof.ok = not proof.failures()
    return proof


def _default_route():
    """The route for a `Probes` that did not supply one — resolved from the environment exactly
    as the real probe does, so an older caller keeps the behaviour it had."""
    from openfactory.adapters.agent.routes import resolve_route

    return resolve_route(None)


def presence_script(names: tuple[str, ...]) -> str:
    """A shell line that echoes the NAME of each variable that is set, and never its value.

    The proof is written to a file, logged, and rendered in the panel. A probe that echoed `$VAR`
    instead of `VAR` would put a live credential in all three, from the one component whose whole
    purpose is to be safe to run before anything else does."""
    return "; ".join(f'[ -n "${n}" ] && echo {n}' for n in names) + "; true"


def _route_names(route) -> tuple[str, ...]:
    """Every variable name the route would accept — asked about by NAME, answered by presence."""
    return tuple(dict.fromkeys(name for group in route.requires for name in group))


def _tail(out: str, lines: int = 20) -> str:
    return "\n".join((out or "").splitlines()[-lines:])


def is_valid(proof: Proof, *, digest: str, toolbox: str, commands_hash: str) -> bool:
    """Whether a recorded proof still describes the world (ADR-0037 D5).

    Three things can move underneath it: the client republishes their image, we pin a new harness,
    they edit `setup:` or `validate:`. Any of them and the proof is about a box that no longer
    exists. That expiry is what separates an invariant from an onboarding checkbox."""
    return bool(
        proof.ok
        and proof.digest == digest
        and proof.toolbox == toolbox
        and proof.commands_hash == commands_hash
    )


def save(proof: Proof, *, root: Path | None = None) -> Path | None:
    """Record a proof where the poller can find it. `None` when it could not be written.

    NEVER RAISES, AND NOW NEVER LIES EITHER. An unwritable proof directory must not fail a proof
    that succeeded — that reasoning was right and stays. What was wrong is that it returned the
    path REGARDLESS, so the caller printed *"PROVEN — … (recorded at "
                                            "/var/lib/openfactory/proofs/p.json)"*
    about a file that does not exist. The `log.warning` below is invisible from the CLI, which
    configures no logging at all.

    THAT ONE LINE EXPLAINS A DISAGREEMENT THAT LOOKED LIKE THREE SEPARATE BUGS. An audit measured
    `openfactory doctor` saying *"OK — can run a "
                                 "ticket"*, `box_prove.gate_reason` saying *"the box has
    never been proven"*, and the poller holding pickup — all at the same instant on the same
    project. The proof HAD succeeded and nothing was recorded, so the gate was right and the
    operator had been told otherwise.

    And it is the exact scene this platform is sold into: the OpenFactory tech-lead running this
    beside the client's developers, reading PROVEN, and the first ticket then sitting still."""
    path = (root or PROOF_DIR) / f"{proof.project}.json"
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({
            "project": proof.project, "image": proof.image, "ok": proof.ok,
            "digest": proof.digest, "toolbox": proof.toolbox,
            "commands_hash": proof.commands_hash, "at": proof.at,
            "toolchain": proof.toolchain,
        }, indent=2, sort_keys=True))
    except OSError as exc:
        log.warning("could not record the proof for %s at %s (%s)", proof.project, path, exc)
        return None
    return path


def load(project: str, *, root: Path | None = None) -> Proof | None:
    """The recorded proof, or None. A malformed record is no proof — never a crash."""
    path = (root or PROOF_DIR) / f"{project}.json"
    try:
        data = json.loads(path.read_text())
    except FileNotFoundError:
        return None
    except (OSError, ValueError) as exc:
        log.warning("the proof for %s at %s is unreadable (%s) — treating it as absent",
                    project, path, exc)
        return None
    if not isinstance(data, dict):
        return None
    return Proof(project=data.get("project", project), image=data.get("image", ""),
                 ok=bool(data.get("ok")), digest=data.get("digest", ""),
                 toolbox=data.get("toolbox", ""),
                 commands_hash=data.get("commands_hash", ""), at=data.get("at", ""),
                 toolchain=data.get("toolchain", ""))


# ── the real probes ─────────────────────────────────────────────────────────────────────────────

@contextmanager
def box_probes(project, image: str, *, repo_path: Path | None = None, manifest=None,
               key: str | None = None):
    """The live probes, over a REAL box — the same `ContainerSandbox` a job gets.

    ONE CONTAINER FOR THE WHOLE PROOF, and the first real run is why this is stated. The first
    version issued a separate `docker run --rm` per command, so `pip install pytest` installed into
    a container that then exited and `pytest` ran in a fresh one without it: setup was useless by
    construction and the proof failed for a reason it had itself created.

    Reusing `ContainerSandbox` rather than approximating it is the stronger form of the same point.
    A proof taken in a lookalike proves the lookalike — this way the mounts, the network, the
    limits, the container naming and the toolbox mount are the ones the job will have, because
    they are produced by the same code.

    `repo_path` / `manifest` / `key` exist for C-18: one product, N repositories, and each
    repository's box must be provable on ITS OWN manifest against ITS OWN checkout (a proof
    taken on the API repo says nothing about the web repo's toolchain). Absent, all three derive
    exactly as they always did — the single-repo path is byte-for-byte unchanged. `key` also
    names the proof container, so two repos' proofs cannot collide on one docker name.
    """
    import subprocess

    from openfactory.adapters.sandbox.registry import build_sandbox
    from openfactory.factory import resolve_repo_path
    from openfactory.loader import load_manifest
    from openfactory.runtime import toolbox as tb

    def _sh(args: list[str], timeout: int = 300) -> tuple[int, str]:
        try:
            p = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
            return p.returncode, (p.stdout or "") + (p.stderr or "")
        except FileNotFoundError:
            return 127, "docker is not installed in this environment"
        except subprocess.SubprocessError as exc:
            return 1, str(exc)

    def _resolve_digest(img: str) -> str | None:
        """What this deployment would actually run, pinned.

        PULL FIRST, because `docker run` passes no `--pull` and proving a tag without pinning what
        it pointed at proves nothing about what runs later. But a failed pull is NOT the answer:
        the first real run of this command failed on `openfactory-python:latest`, an image built
        locally
        by our own compose file and therefore in no registry at all — which is also every adopter
        who builds their own. The question is "can this deployment obtain the image", and already
        having it is a yes."""
        pulled = _sh(["docker", "pull", "--quiet", img], timeout=900)[0] == 0
        if not pulled and _sh(["docker", "image", "inspect", img])[0] != 0:
            return None
        rc, out = _sh(["docker", "image", "inspect", "--format",
                       "{{index .RepoDigests 0}}", img])
        if rc == 0 and "@sha256:" in out:
            return out.strip().split("@", 1)[1]
        # A locally-built image has no RepoDigest. Its content id still pins WHAT was proven.
        rc, out = _sh(["docker", "image", "inspect", "--format", "{{.Id}}", img])
        return out.strip() if rc == 0 and out.strip().startswith("sha256:") else None

    def _platform(img: str) -> tuple[str, str, str]:
        rc, out = _sh(["docker", "image", "inspect", "--format", "{{.Os}}/{{.Architecture}}", img])
        os_, _, arch = (out.strip() if rc == 0 else "linux/unknown").partition("/")
        # libc is a property of the FILESYSTEM, not of the manifest, so it has to be looked at.
        rc, _ = _sh(["docker", "run", "--rm", "--entrypoint", "sh", img, "-c",
                     "ls /lib/ld-musl-* >/dev/null 2>&1"])
        return os_ or "linux", arch or "unknown", ("musl" if rc == 0 else "glibc")

    def _contract(img: str) -> dict:
        """Each requirement asked separately, so the answer names which one is missing."""
        checks = {
            "sh": "command -v sh",
            "git": "command -v git",
            "keep-alive": "command -v sleep || command -v tail",
            "workspace-writable":
                "mkdir -p /workspace && touch /workspace/.p && rm -f /workspace/.p",
            "home-writable":
                "touch ${HOME:-/root}/.p && rm -f ${HOME:-/root}/.p",
        }
        broken: dict[str, str] = {}
        for name, probe in checks.items():
            rc, out = _sh(["docker", "run", "--rm", "--entrypoint", "sh", img, "-c", probe])
            if rc != 0:
                broken[name] = (out.strip().splitlines() or ["not available"])[-1][:120]
        return broken

    # RESOLVED, exactly as `build_runner` does — a proof taken against a path the job would not
    # use proves nothing. This was left as the raw `repo_path` when #65 landed, so on the compose
    # worker it was still a URL: the clone failed silently and the proof ran against an empty
    # workspace, reporting the client's own gates as broken.
    #
    # `cache_key=key`: a `--repo` proof resolves into ITS OWN cache slot. Without it the foreign
    # repository synced into the DEFAULT repo's shared checkout — the tree a live worker may be
    # reading — which is the exact cross-repo contamination `_checkout_key` exists to prevent
    # (adversarial review, 2026-08-13). `key=None` keeps the default slot, byte for byte.
    repo = repo_path if repo_path is not None else resolve_repo_path(project, cache_key=key)
    manifest = manifest if manifest is not None else load_manifest(project, repo_root=repo)
    start_error = ""
    # THE REGISTRY'S `box:` KNOBS ARE FORWARDED, mirroring `build_runner` (factory.py) — this
    # call passed none of them, so the proof box had the default network, no cache volume, no
    # `box.env`, while the docstring above promised "the mounts, the network, the limits … are
    # the ones the job will have". The harness-auth station probed a box that lacked exactly
    # the `box.env` names the job's box receives (measured by the onboard fact-finding pass,
    # 2026-08-13). Only keys the operator set are passed; an absent block changes nothing.
    declared = getattr(project, "box", None)
    knobs = {
        k: v for k in ("network", "cache_volume", "cpus", "memory")
        if (v := getattr(declared, k, None)) is not None
    }
    if declared_env := tuple(getattr(declared, "env", None) or ()):
        knobs["extra_env"] = declared_env
    box = build_sandbox("container", image=image, project=f"{key or project.name}-prove",
                        toolbox=(os.environ.get("OPENFACTORY_TOOLBOX_VOLUME") or "").strip()
                                or None, **knobs)
    workspace = None

    def _in_box(command: str, on_line: Callable[[str], None] | None = None) -> tuple[int, str]:
        if workspace is None:
            # SAY WHY. This used to return a bare "the box was never started", which `prove`
            # reported as a SETUP failure with a remedy about private package feeds — while the
            # real cause was a leftover container from a crashed run. One cause, one actionable
            # line, and the line has to be the true one.
            return 1, f"the box could not be started: {start_error or 'unknown reason'}"
        # `on_output` IS WHAT THE ROOM SEES. Both sandboxes have taken it since C-39 and this
        # caller passed None, so `openfactory box prove` — a command that installs a client's
        # dependencies and runs their whole suite, up to 1800s per command — printed nothing
        # until each station had already finished.
        return box.run(workspace=workspace, command=command, timeout=1800, on_output=on_line)

    def _reachable() -> tuple[bool, str]:
        """A TLS HANDSHAKE from inside the box, and still zero tokens. `--version` opens no
        connection at all, so a proxy, an intercepting CA or an egress policy passes a smoke test
        and then kills the first real agent call.

        THE HOST IS THE ROUTE'S, not Anthropic's. It was hardcoded here, which meant a client
        running the harness against their own Bedrock account was proven against a host their
        box never contacts — refused pickup when that host is blocked, waved through when their
        real endpoint is."""
        url = _route().endpoint
        if not url:
            return True, "no endpoint to probe"
        rc, out = _in_box(
            f"curl -sS --max-time 20 -o /dev/null -w '%{{http_code}}' {shlex.quote(url)} || true"
        )
        if rc != 0:
            return False, _tail(out, 5) or "the probe could not run"
        code = (out or "").strip().splitlines()[-1] if out.strip() else ""
        # Any HTTP status means TLS completed and something answered — 401 is a fine answer here,
        # because we deliberately send no credential.
        return (bool(code and code.isdigit()),
                f"no HTTP response ({_tail(out, 3)})" if not code.isdigit() else code)

    def _route():
        from openfactory.adapters.agent.routes import resolve_route

        return resolve_route(project)

    def _env_in_box(names: tuple[str, ...]) -> dict[str, str] | None:
        """Which of these names are SET inside the box. Presence only — the probe prints the name
        of every variable it found non-empty and never its value, so a credential cannot reach a
        log, a proof file or the panel through this path."""
        if not names:
            return {}
        rc, out = _in_box(f"sh -lc {shlex.quote(presence_script(names))}")
        if rc != 0:
            return None  # the box could not answer — not the same as "nothing is set"
        found = {line.strip() for line in (out or "").splitlines() if line.strip() in names}
        return {n: "1" for n in found}

    try:
        # A throwaway branch in a throwaway clone: `prepare` always makes one, nothing is pushed,
        # and the working tree is `main` untouched because no commit happens.
        workspace = box.prepare(repo_path=repo, base_branch=manifest.base_branch,
                                branch=f"{namespace.BRANCH_PREFIX}/box-prove")
    except Exception as exc:  # noqa: BLE001 — an unstartable box IS the finding, not a crash
        start_error = str(exc)[:300]
        log.info("the box could not be started for the proof (%s)", start_error)

    try:
        yield Probes(
            resolve_digest=_resolve_digest,
            image_platform=_platform,
            toolbox_stamp=lambda: tb.read_stamp(),
            contract=_contract,
            run_in_box=_in_box,
            toolchain_stamp=_toolchain_of,
            # The SAME closure, bound to a line sink. Two entries rather than one widened field
            # so `prove` never has to guess whether the probe set it was handed can stream.
            run_streaming=lambda cmd, on_line: _in_box(cmd, on_line),
            harness_reachable=_reachable,
            setup_commands=lambda: list(manifest.setup),
            validate_commands=lambda: gate_commands(manifest.validation),
            advisory_gates=lambda: advisory_gates(manifest.validation),
            component_gate_commands=lambda: component_gates(manifest),
            # THROUGH THE BOX'S OWN SEAM, exactly as the executor does. `harness_path` (ADR-0037
            # D2a) exists because `PATH` cannot be relied on inside a CLIENT's image, and this
            # proof asked for the bare name instead — so it smoke-tested a command the real run
            # never issues. On the framework's own image both happen to work; on `node:22` the
            # bare name is `claude: not found` (found live on fx-jira, 2026-08-05) and the gate
            # refused a box that would have run perfectly. A false negative here BLOCKS PICKUP.
            harness_name=lambda: (box.harness_path(_harness_binary(project))
                                  if box is not None else _harness_binary(project)),
            auth_route=_route,
            env_in_box=_env_in_box,
        )
    finally:
        try:
            if workspace is not None:
                box.cleanup(workspace=workspace)
        except Exception as exc:  # noqa: BLE001 — a leaked container is a warning, not a failure
            log.warning("the proof's box could not be cleaned up (%s)", str(exc)[:160])


def _harness_binary(project) -> str:
    """The CLI the executor role will actually invoke, so the smoke test smokes the right one."""
    from openfactory.adapters.agent.registry import harness_binary, harness_kind

    return harness_binary(harness_kind(project, "executor"))


# ── the gate (ADR-0037 D5) ──────────────────────────────────────────────────────────────────────

def _current_digest(image: str) -> str:
    """The digest the box would run RIGHT NOW, for comparison against the proof.

    A local read only — this is on the poller's tick, so it must not pull. An image that has
    changed in the registry without being pulled still reads as unchanged here, and that is
    correct: the box would launch the cached one too."""
    import subprocess

    for fmt in ("{{index .RepoDigests 0}}", "{{.Id}}"):
        try:
            p = subprocess.run(["docker", "image", "inspect", "--format", fmt, image],
                               capture_output=True, text=True, timeout=60)
        except (OSError, subprocess.SubprocessError):
            return ""
        out = (p.stdout or "").strip()
        if p.returncode == 0 and out:
            return out.split("@", 1)[1] if "@sha256:" in out else out
    return ""


#: Where the box image writes what it offers a client's commands (see `docker/sandbox.Dockerfile`).
TOOLCHAIN_FILE = "/etc/openfactory-toolchain"


def _toolchain_of(image: str) -> str:
    """What that image offers the client's commands, or "" when it does not say.

    ONE `docker run`, AND ONLY WHEN THE DIGEST HAS ALREADY MOVED — so on a steady deployment this
    never executes, and after an update it runs once per project instead of holding the floor.
    An image without the file (a client's own toolbox) answers "", which is not a verdict: the
    caller falls back to comparing digests, which is what it did before this existed."""
    import subprocess

    try:
        p = subprocess.run(
            ["docker", "run", "--rm", "--entrypoint", "sh", image, "-c", f"cat {TOOLCHAIN_FILE}"],
            capture_output=True, text=True, timeout=120)
    except (OSError, subprocess.SubprocessError) as exc:
        log.info("could not ask %s what toolchain it carries (%s)", image, str(exc)[:120])
        return ""
    return (p.stdout or "").strip() if p.returncode == 0 else ""


def _freshness_reason(proof: Proof, *, digest: str, variant: str, commands: str,
                      run_it: str) -> str | None:
    """Whether the recorded proof still describes the world, and which fact moved if not.

    ITS OWN FUNCTION because it is the whole of D5 and every branch is a judgement somebody has
    to be able to exercise without a docker daemon, a toolbox volume and a client checkout.
    """
    if variant and proof.toolbox != variant:
        return (f"the harness toolbox changed ({proof.toolbox or 'none'} → {variant}), "
                f"so the box is no longer the one that was proven — {run_it}")
    if not variant and proof.toolbox:
        # I CANNOT READ MY OWN TOOLBOX ≠ THE TOOLBOX CHANGED. The three-state rule this codebase
        # keeps paying for, one seam further in. The PANEL runs without the toolbox volume
        # mounted — it starts no boxes, so it has no reason to carry one — and read an empty
        # stamp as `none`, then announced the floor as HELD with a remedy to run: the operator
        # saw "podbeam is held — the toolbox changed (linux-arm64-glibc → none)" while the
        # WORKER, the process that actually picks cards up, read the stamp correctly and would
        # have held nothing (pilot, 2026-08-14).
        #
        # An unreadable stamp says nothing about the box. Every other freshness check above
        # still applies, so a genuinely stale proof is still caught — by the facts this process
        # CAN measure.
        log.info("the toolbox stamp is unreadable here (proof recorded %r) — not judging the "
                 "toolbox from a measurement this process cannot make", proof.toolbox)
    if proof.commands_hash != commands:
        return (f"this project's `setup:` or `validate:` changed since the box was proven — "
                f"{run_it}")
    if proof.digest != digest:
        # A REBUILD IS NOT A CHANGE, and on the free deployment it is the common case. A compose
        # install BUILDS its box image, so it has no registry digest and this compares the content
        # id — which moves on every `--build`, including the ones that carry only a new version of
        # our own package. The pilot updated eight times in three days and got eight "the image
        # changed — run box prove" alarms, with his tickets held between each (2026-08-15).
        #
        # What a client's `setup:` and `validate:` depend on is the TOOLCHAIN, and the image
        # writes it down (`/etc/openfactory-toolchain`). Same toolchain → the proof still
        # describes the world, and the digest it was pinned to is refreshed so the question is
        # asked once rather than every tick. Different, or unreadable on either side → today's
        # answer, because then this process genuinely cannot say the box is the one that was
        # proven.
        now = ""
        try:
            now = (_toolchain_of(proof.image) or "").strip()
        except Exception as exc:  # noqa: BLE001 — an unreadable stamp is not a verdict
            log.info("could not read %s's toolchain line (%s)", proof.image, str(exc)[:120])
        if now and proof.toolchain and now == proof.toolchain:
            log.info("%s was rebuilt (%s… → %s…) with the same toolchain — the proof stands",
                     proof.image, proof.digest[:19], digest[:19])
            proof.digest = digest
            save(proof)
            return None
        return (f"the image {proof.image} changed ({proof.digest[:19]}… → {digest[:19]}…) — "
                f"{run_it}")
    return None


def foreign_proofs_recorded(project: str, *, root: Path | None = None) -> bool:
    """Does any FOREIGN repository of this project have a proof on disk (C-18)?

    THE POLLER'S SECOND QUESTION, and it lives here because two callers now ask it. With the
    default repo's gate holding, `activities.py::scan_todo` still READS THE BOARD when some
    other repo of the project is proven — a proven foreign repo must not wait on the default's
    paperwork — and skips the read entirely when none is. `doctor` asks the same thing to decide
    whether an unreadable API budget is a safety net anybody needs yet, and one condition written
    in two places is a disagreement waiting to happen — this module has already watched the
    doctor say "OK — can run a ticket" while the gate said "never proven" and the poller held
    pickup, on one project, at one instant (`save`).

    THE NAME SHAPE IS `card_repo.py::_checkout_key`'s: a foreign repo is recorded as
    `<project>--<owner>--<repo>.json`, while the default repo keeps `<project>.json` — so the
    default's own proof never matches this glob, which is the whole point of asking.

    NEVER RAISES: it runs on the poller's tick, and an unreadable proof directory must answer
    "none recorded" rather than stop the tick for every other project.
    """
    try:
        return any((root or PROOF_DIR).glob(f"{project}--*.json"))
    except OSError as exc:
        log.warning("could not list the proof directory for %s (%s)", project, exc)
        return False


def gate_reason(project, *, sandbox: str, repo: str = "") -> str | None:
    """Why this project may NOT be picked up, or None when it may (ADR-0037 D5).

    Configuration is a declaration; a proof is a fact — and a fact about a world that moves. Three
    things can move underneath it, and each gets named rather than collapsed into "expired": a
    reason with no cause is a wall, and somebody has to know whether to re-prove, rebuild the
    worker, or look at what they just edited.

    ONLY WHERE THERE IS SOMETHING TO PROVE. A `worktree` box has no image and no toolbox; a
    `fargate` job runs inside a task whose image is baked into the task definition. Gating either
    would block a deployment on a proof it cannot take — and both live deployments are fargate, so
    this is what keeps them untouched by D5.

    NEVER RAISES. It runs on the poller's tick; an unreadable proof directory must degrade to
    "unproven", which is a stated reason, rather than stopping the tick for every other project.

    `repo` IS C-18'S HALF (2026-08-13). One product may span N repositories, and a proof taken
    against the API repo says nothing about the web repo's toolchain — yet the gate consulted
    ONE proof, keyed by project name, for every card. A qualified card was admitted on the
    strength of a proof about a different codebase, which is the gate looking closed while
    standing open. The key is `_checkout_key(project, repo)` — the default repo keeps today's
    filename byte for byte, so no existing deployment re-proves anything.
    """
    from openfactory.adapters.sandbox.registry import box_traits
    from openfactory.runtime import toolbox as tb

    try:
        if not box_traits((sandbox or "").strip().lower()).honours_image:
            return None
    except ValueError:
        return None  # an unknown box is the registry's error to report, not a silent pickup halt

    from openfactory.runtime.card_repo import _checkout_key, _runner_view

    name = getattr(project, "name", "?")
    key = _checkout_key(project, repo) if repo else name
    run_it = (f"run `openfactory box prove {name} --repo {repo}`" if repo and key != name
              else f"run `openfactory box prove {name}`")
    proof = load(key)
    if proof is None:
        subject = f"the box for {repo}" if repo and key != name else "the box"
        return f"{subject} has never been proven — {run_it}"
    if not proof.ok:
        return f"the last box proof FAILED — {run_it}"

    try:
        from openfactory.loader import load_manifest

        if repo and key != name:
            # THE FOREIGN REPO'S OWN MANIFEST — its setup:/validate: are what the proof hashed,
            # and hashing the default repo's here would expire the wrong proof (or worse, keep
            # a stale one fresh). `_runner_view` swaps the axes to the card's repo; the resolve
            # syncs the same cache the job will use.
            from openfactory.factory import resolve_repo_path

            view, view_key = _runner_view(project, f"{repo}#0")
            manifest = load_manifest(
                view, repo_root=resolve_repo_path(view, cache_key=view_key))
        else:
            manifest = load_manifest(project)
        commands = _hash_commands(list(manifest.setup), gate_commands(manifest.validation),
                                  component_gates(manifest))
    except namespace.RetiredNamespace as exc:
        # A REPOSITORY STILL ON THE DIRECTORY'S RETIRED NAME. The arm below REWRITES the
        # message — "not on the base branch yet" — and for this repository that is a false
        # cause: the manifest IS on the base branch, under a directory the platform does not
        # read, and the sentence saying what to rename was the one thing dropped (review,
        # 2026-08-25). The gate holds, and it holds with the rename in the reason.
        return str(exc)
    except FileNotFoundError:
        # NOT a question we cannot ask — the ANSWER: the manifest is not on the base branch.
        # Onboarding deliberately mints this state (proof saved while the manifest rides an
        # un-merged PR), and degrading to the proof's own hash admitted the card into a job
        # whose first act is to fail loading this exact file (adversarial review, 2026-08-13).
        subject = f"{repo}'s manifest" if repo and key != name else "the manifest"
        return (f"{subject} is not on the base branch yet — the box is proven, and pickup "
                f"starts when the pull request declaring it merges")
    except Exception as exc:  # noqa: BLE001 — an unreadable manifest is its own doctor finding
        log.info("could not hash %s's commands for the box gate (%s)", key, str(exc)[:160])
        commands = proof.commands_hash  # do not block on a question we cannot ask
    variant = (tb.read_stamp() or {}).get("variant", "")
    digest = _current_digest(proof.image) or proof.digest
    return _freshness_reason(proof, digest=digest, variant=variant, commands=commands,
                             run_it=run_it)
    return None


def _announced_file(project: str, root: Path | None = None) -> Path:
    return (root or PROOF_DIR) / f"{project}.gate"


def _hold_key(reason: str) -> str:
    """The KIND of hold, so the same one is announced once rather than once per rebuild.

    "Say it once" was already the rule, and it compared the whole sentence — which carries the
    detail that changed: `the image … changed (sha256:a… → sha256:b…)`. Every `docker compose up
    --build` produced a new sentence, so the pilot's tech-lead channel collected eight identical
    alarms in three days, each one a fresh interruption for a client to read (2026-08-15).

    The detail belongs IN the message — an operator needs to know which digest moved — and not in
    the question "have I already said this?". So the parenthetical is dropped from the key and
    kept in the text."""
    import re as _re

    return _re.sub(r"\s+", " ", _re.sub(r"\([^)]*\)", "", reason)).strip()


def announce_gate(project: str, reason: str, *, root: Path | None = None,
                  registry_name: str = "") -> bool:
    """Say why pickup is held, ONCE per reason. Returns whether it spoke.

    A gate that blocks and does not speak is the platform's headline failure wearing new clothes:
    the card sits in TO-DO looking merely unstarted, which is indistinguishable from a quiet
    factory (ADR-0038 D2 — a wait is a question, never a state).

    Once, though. The poller ticks every few minutes, and an alarm on every tick is an alarm
    somebody learns to filter — the same cost a false alarm has anywhere else here.

    `registry_name` is the PROJECT the notifier belongs to, when `project` is a per-repo
    checkout key (`dsk--acme--web`): the registry cannot resolve a composite key, so without
    the split every foreign-repo hold KeyError'd into the catch-all and the channel was never
    told — the gate's own headline failure, one level down (adversarial review, 2026-08-13)."""
    path = _announced_file(project, root)
    key = _hold_key(reason)
    try:
        if path.read_text() == key:
            return False
    except OSError:
        pass

    log.warning("%s: pickup is held — %s", project, reason)
    try:
        from openfactory.factory import notifier_for_project
        from openfactory.registry import ProjectRegistry

        # `notify`, NOT `send`. This read `.send(...)` from the day it shipped, and NO notifier
        # has ever had that method — `Notifier` is a Protocol with exactly one member
        # (`adapters/notify/base.py:17`). Every call raised `AttributeError` into the catch-all
        # below and was logged at DEBUG, so the commit that introduced this gate claimed "the gate
        # speaks" while the channel half had never once run: the 18th instance of this
        # repository's signature defect, in the change whose entire point was that a wait must be
        # a question rather than a state.
        from openfactory.techlead import voice as tl_voice

        row = ProjectRegistry().get(registry_name or project)
        notifier_for_project(row).notify(
            message=tl_voice.say(tl_voice.NARRATION, "gate.pickup-held",
                                 str(getattr(row, "language", "") or ""),
                                 project=project, reason=reason),
            level="warning")
    except Exception as exc:  # noqa: BLE001 — a channel is an ADD-ON; the log is the record
        # WARNING, not DEBUG. A channel push is best-effort and must never hold the gate, but
        # "best-effort" is the reason to log it, not the reason to hide it — DEBUG is what let a
        # method that does not exist go unnoticed through two deployments.
        log.warning("could not push the box gate for %s to a channel (%s) — the log line above is "
                    "the only record", project, str(exc)[:120])
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        # THE KEY, NOT THE SENTENCE — the same thing the read above compares. Writing the full
        # reason here while reading the key meant the marker never matched, so the dedup this
        # function exists for was off for every hold whose detail moves.
        path.write_text(key)
    except OSError as exc:
        # Not fatal, but say it: without the marker every tick announces again.
        log.warning("could not record the gate announcement for %s (%s) — it will repeat",
                    project, exc)
    return True


def clear_gate_announcement(project: str, *, root: Path | None = None) -> None:
    """Forget what was said, so the NEXT breakage speaks rather than staying quiet because
    something similar was announced once."""
    _announced_file(project, root).unlink(missing_ok=True)


# ── the box, as a HUMAN-READABLE verdict ──────────────────────────────────────────────────────
#
# MOVED OUT OF `api/app.py` (#144). It was a private helper of the web layer, and the floor's
# ladder, the CLI and any channel need the same answer — a second copy is how two surfaces come
# to disagree about whether a factory will take a card. The web layer keeps a thin alias.
def health(project) -> dict:
    """Whether this project's box is proven, and — when it is not — the sentence and the remedy.

    THE BOX WAS INVISIBLE, and that is the whole reason this exists. `box prove` writes a proof,
    `gate_reason` reads it and silently returns `[]` from the poller, and NO human surface showed
    either: measured on `panel.html`, all 41 occurrences of "box" were CSS (`box-shadow`,
    `border-box`). So the state that decides whether a factory picks up work at all had a file, a
    gate and no window — which for a product built on unattended runs is the one thing a client
    wants to see. The product owner: *"without the BOXes showing a healthy, visible status, this
    is not good."*

    NEVER RAISES AND NEVER GUESSES. This is rendered next to every project on a page an operator
    opens when something is already wrong; an unreadable proof directory must degrade to
    "unknown", which is a stated answer, rather than taking the whole list down. `unknown` is not
    `unproven`: one is a fact about the client's box, the other about our ability to read it.
    """
    from openfactory.runtime.temporal.io import default_sandbox

    try:
        sandbox = default_sandbox()
        held = gate_reason(project, sandbox=sandbox)
        proof = load(project.name)
    except Exception as exc:  # noqa: BLE001 — one bad project must not empty the whole page
        log.warning("could not read the box health of %s (%s)", project.name, str(exc)[:160])
        return {"state": "unknown", "detail": "the proof could not be read from here",
                "gate": "", "image": "", "at": ""}

    return {
        # `held` is what the POLLER acts on, so it is what decides the badge — not the proof's own
        # `ok`. A proof that succeeded against an image that has since moved is `ok` and expired,
        # and showing green there would be the panel disagreeing with the factory.
        "state": "proven" if not held else ("unproven" if proof is None else "expired"),
        "gate": held or "",
        "sandbox": sandbox,
        "image": getattr(proof, "image", "") if proof else "",
        "at": getattr(proof, "at", "") if proof else "",
        "detail": "" if not held else held,
    }
