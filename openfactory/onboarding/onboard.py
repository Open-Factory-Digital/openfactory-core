"""`openfactory onboard` — the first-time setup, done where the factory lives (2026-08-13).

THE OPERATOR'S TWO OBSERVATIONS, the day the pilot reached §3, are the whole design:

    *"why is the first-time setup not done in a BOX, the way everything else is? A box over the
    source to produce the manifest, the module map, the app's own tests running — and a box over
    the context repository, creating it where there is none, where the prose backfill happens."*
    And: *"the reality at an enterprise client is multi-repo — a front end and a back end."*

He was pointing at an incoherence the platform half-knew: it already runs everything that
matters inside the box — `box prove` runs the client's own gates there, every ticket's agent
runs there — while the SETUP that produces those declarations was the one thing done by static
reading on somebody's machine. And the journey was single-repo-shaped while the runtime
(C-18) already routes every card to its own repository.

WHAT THIS MODULE DOES, per source repository of a product:

    clone (the factory's own machinery — right host, right credential)
      → infer the manifest from the repository        (zero tokens)
      → PROVE the proposal in the real box            (the client's own setup:/validate:,
                                                       streamed — the PR arrives MEASURED)
      → generate the module map                       (deterministic parse, zero tokens)
      → ONE pull request: manifest + knowledge/, its body carrying the proof verdict and the
        questions only a human can answer.

A repository that already declares its manifest is not re-declared: its existing manifest is
proven as-is, and the pull request carries only what is genuinely new (the map, typically) —
or nothing, which is said rather than performed.

PROVING FAILURE DOES NOT BLOCK THE PROPOSAL, deliberately. The point of proving is that the
reviewer sees a measurement instead of a guess — and "your proposed test command exited 2, here
is the tail" is a MORE useful pull request than silence, not a reason to withhold it. The proof
is also SAVED under the repo's own key: if the reviewer merges the manifest unchanged, the
pickup gate finds a valid proof; if they edit it, the commands hash moves and the gate says
"re-prove" — exactly the freshness contract every proof already has.

Every write to the client's repository is a pull request, through the same arms `env apply
--pr` earned in review: idempotency asked through the port, the orphan branch finished rather
than re-pushed, "could not ask" never read as "there is none".
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from openfactory import namespace

log = logging.getLogger("openfactory.onboarding.onboard")

#: What the caller sees per stage: ("start"|"line"|"done", text). The CLI streams it; a test
#: collects it. Same shape `box prove` already uses.
StageFn = Callable[[str, str], None]


@dataclass
class RepoOutcome:
    """One source repository's onboarding, in the terms a person acts on."""

    repo: str
    ok: bool = False
    #: the pull request URL when one was opened (or found already open)
    pr: str = ""
    existed: bool = False
    #: whether the repository already declared its manifest (nothing re-proposed)
    manifest_already_there: bool = False
    #: the box proof's verdict — "proven" / "failed" / "skipped: <why>"
    proof: str = ""
    #: proof findings that failed, one line each, for the summary table
    proof_failures: list[str] = field(default_factory=list)
    #: advisory findings that failed non-blockingly, for the PR body
    proof_advisories: list[str] = field(default_factory=list)
    #: module count in the generated map; -1 = not generated
    modules: int = -1
    #: the questions only a human can answer (unknown manifest fields)
    questions: list[str] = field(default_factory=list)
    #: one sentence when not ok
    detail: str = ""


def _say(stream: StageFn | None, kind: str, text: str) -> None:
    if stream is not None:
        try:
            stream(kind, text)
        except Exception:  # noqa: BLE001 — a broken reporter must not fail the onboarding
            log.warning("the onboard stream callback raised — continuing silently",
                        exc_info=True)


def onboard_source_repo(project, repo: str, *, sandbox: str = "container",
                        stream: StageFn | None = None) -> RepoOutcome:
    """One repository: clone → infer → prove → map → pull request."""
    import yaml as yaml_mod

    from openfactory.adapters.forge.registry import build_forge, clone_url_for
    from openfactory.contracts.manifest import Manifest
    from openfactory.credentials import deployment_forge_token, forge_token_for
    from openfactory.loader import load_manifest
    from openfactory.onboarding.infer import infer, to_manifest_dict
    from openfactory.onboarding.live_ci import ask_the_forge, demote_disabled
    from openfactory.onboarding.propose_manifest import (
        already_proposed,
        clone_for_proposal,
        default_branch,
        propose,
    )
    from openfactory.runtime.card_repo import _checkout_key, _runner_view

    out = RepoOutcome(repo=repo)
    view, _ = _runner_view(project, f"{repo}#0")
    key = _checkout_key(project, repo)
    # The deployment's own credential as the last resort: an App-only GitHub deployment holds
    # no static token at all (docs/setup/github.md says to leave OPENFACTORY_BOT_TOKEN empty),
    # so without it this whole verb dies at the first private clone. Vendor-aware by
    # construction — it offers nothing to a forge that is not GitHub's.
    token = forge_token_for(view) or deployment_forge_token(view)
    forge = build_forge(view, token=token)

    _say(stream, "start", f"{repo}: cloning")
    url = clone_url_for(view, repo, token=token)
    checkout, why = clone_for_proposal(clone_url=url)
    if checkout is None:
        out.detail = f"could not clone {repo}: {why}"
        return out
    try:
        base = default_branch(checkout)

        manifest_rel = str(getattr(project, "manifest_path", namespace.MANIFEST))
        manifest_file = checkout / manifest_rel
        manifest = None
        try:
            # THE LOADER decides whether the repository declares its manifest. `is_file()` on the
            # default path alone once read a repository that declared it elsewhere as undeclared
            # and proposed a SECOND manifest that, once merged, silently shadowed the one the
            # client already obeyed (adversarial review, 2026-08-13).
            manifest = load_manifest(view, repo_root=checkout)
            out.manifest_already_there = True
        except namespace.RetiredNamespace as exc:
            # A REPOSITORY STILL ON THE DIRECTORY'S RETIRED NAME IS REFUSED HERE, BY NAME — before
            # anything is inferred or written. The refusal is a `FileNotFoundError`, and the arm
            # below would read it as "undeclared": infer a manifest, write it under the current
            # name and open a pull request that never mentions the one the repository has — the
            # second-manifest defect above, back on the first door a new client walks through
            # (review, 2026-08-25). The sentence says what to rename; this verb does nothing else.
            out.detail = str(exc)
            return out
        except FileNotFoundError:
            out.manifest_already_there = False
        except Exception as exc:  # noqa: BLE001 — a broken declaration is the client's to fix
            out.detail = (f"{repo} carries a manifest that does not load "
                          f"({str(exc)[:200]}) — fix or remove it; nothing was proposed")
            return out
        if out.manifest_already_there:
            _say(stream, "line", f"{repo}: already declares its manifest — proving it as-is")
        else:
            _say(stream, "start", f"{repo}: reading the repository")
            proposal = infer(checkout)
            # WHAT THE FILES CANNOT SAY, ASKED OF THE FORGE (#117). `infer` is offline and
            # vendor-neutral by design, and on disk a retired workflow is byte-identical to a
            # living one — so the pilot's proposal carried a `bandit` command read verbatim from a
            # `ci.yml` that had been disabled for months, cited as "observed", and the box proof
            # then failed on a gate the client had deliberately switched off. The inference cannot
            # know; this function has a forge.
            dead = ask_the_forge(forge, repo)
            if dead:
                _say(stream, "line",
                     f"{repo}: {len(dead)} CI definition(s) are switched off in the forge — "
                     f"anything read only from them becomes a question")
            demote_disabled(proposal, dead)
            document = to_manifest_dict(proposal)
            manifest = Manifest.model_validate(document)
            out.questions = list(proposal.questions)
            for unknown in proposal.unknowns():
                if unknown.note:
                    out.questions.append(unknown.note)
            # an unknown field's note often IS one of the proposal's questions — the reviewer
            # reads each once
            out.questions = list(dict.fromkeys(out.questions))
            manifest_file.parent.mkdir(parents=True, exist_ok=True)
            manifest_file.write_text(
                yaml_mod.safe_dump(document, sort_keys=False, allow_unicode=True,
                                   default_flow_style=False), encoding="utf-8")

        _say(stream, "start", f"{repo}: proving the box on its own manifest")
        out.proof, out.proof_failures, out.proof_advisories = _prove_in_box(
            view, key, checkout, manifest, sandbox=sandbox, stream=stream)

        _say(stream, "start", f"{repo}: generating the module map")
        out.modules = _build_map(checkout)

        wanted: list[str] = []
        if not out.manifest_already_there:
            wanted.append(manifest_rel)
        if out.modules >= 0 and _dirty(checkout, "knowledge"):
            # only when the map is NEW OR CHANGED — a committed, current map staged again
            # produces "nothing to commit" two steps later, a misleading refusal about work
            # that was simply already done
            wanted.append("knowledge")
        if not wanted:
            out.ok = True
            out.detail = (f"{repo} already declares everything — nothing to propose "
                          f"(proof: {out.proof})")
            return out

        _say(stream, "start", f"{repo}: opening the pull request")
        first, extras = wanted[0], wanted[1:]
        # `env apply --pr` proposes the manifest on its own branch; two open reviews declaring
        # the same file is a reviewer trap, so the older one is NAMED rather than silently raced
        sibling = already_proposed(forge, repo) if not out.manifest_already_there else ""
        note = (f"\n\nNote: an earlier manifest proposal from `env apply --pr` is open at "
                f"{sibling} — this pull request supersedes it; close that one when merging "
                f"this." if sibling else "")
        result = propose(
            checkout=checkout, manifest_path=first, repo=repo, clone_url=url, base=base,
            forge=forge, project_name=getattr(project, "name", repo),
            branch="openfactory/onboard", extra_paths=extras,
            title=f"OpenFactory onboarding: {repo}",
            body=_pr_body(repo, out, manifest_proposed=not out.manifest_already_there) + note)
        out.ok = result.ok
        out.pr, out.existed, out.detail = result.url, result.existed, result.detail
        return out
    finally:
        import shutil

        shutil.rmtree(checkout, ignore_errors=True)


def _prove_in_box(view, key: str, checkout: Path, manifest, *, sandbox: str,
                  stream: StageFn | None) -> tuple[str, list[str], list[str]]:
    """The proposal, measured — never a guess, and never a blocker.

    Failure shapes: a box that cannot even be built (no docker, no image) is `skipped:` with
    the why; gates that ran and failed are `failed`, each finding a line the PR body carries.
    The proof is SAVED under the repo's own key either way it completes — see the module
    docstring for why a saved failing proof is correct (the gate holds pickup and says so)."""
    from openfactory.box_prove import box_probes, prove, save
    from openfactory.factory import resolve_box_image
    from openfactory.onboarding.propose_manifest import scrub

    try:
        image = resolve_box_image(view, explicit=None, sandbox=sandbox)
        with box_probes(view, image, repo_path=checkout, manifest=manifest, key=key) as probes:
            proof = prove(key, image, probes,
                          on_stage=(lambda kind, text: _say(stream, kind, f"    {text}"))
                          if stream else None)
        save(proof)
        advisories = []
        for a in proof.advisories():
            line = scrub(f"{a.check}: {a.message}")
            if a.remedy:
                line += f"\n  → {scrub(a.remedy)}"
            advisories.append(line)
        if proof.ok:
            return "proven", [], advisories
        # scrub(): these lines carry captured command output and they land in a PULL REQUEST
        # BODY on the client's forge — the one place a leaked credential cannot be un-published.
        # THE REMEDY RIDES ALONG: "sh: 1: uv: not found" without the box.image sentence is the
        # reviewer blocked in a shell's vocabulary (the pilot, 2026-08-13)
        failures = []
        for f in proof.failures():
            line = scrub(f"{f.check}: {f.message}")
            if f.remedy:
                line += f"\n  → {scrub(f.remedy)}"
            failures.append(line)
        return "failed", failures, advisories
    except Exception as exc:  # noqa: BLE001 — an unprovable environment must not hide the PR
        log.warning("could not prove %s's box during onboarding", key, exc_info=True)
        return f"skipped: {scrub(str(exc))[:160]}", [], []



def _dirty(checkout: Path, path: str) -> bool:
    """Whether `path` differs from what the clone came with — new counts, unchanged does not."""
    import subprocess

    status = subprocess.run(["git", "-C", str(checkout), "status", "--porcelain", "--", path],
                            capture_output=True, text=True, timeout=30, check=False)
    return bool((status.stdout or "").strip())


def _build_map(checkout: Path) -> int:
    """The module map, into the checkout — deterministic, zero tokens, best-effort."""
    import subprocess
    from datetime import UTC, datetime

    from openfactory.knowledge import build_bundle, read_bundle, write_bundle

    try:
        if (checkout / "knowledge").exists() and read_bundle(checkout) is None:
            # `knowledge/` is a generic name. A directory that exists but is NOT an OpenFactory
            # bundle is the client's own content — proposing its replacement in a PR is exactly
            # the overwrite a reviewer should never have to catch.
            log.info("the repository carries its own knowledge/ (not an OpenFactory bundle) — "
                     "leaving it untouched")
            return -1
        head = subprocess.run(["git", "-C", str(checkout), "rev-parse", "HEAD"],
                              capture_output=True, text=True, timeout=30, check=False)
        commit = (head.stdout or "").strip() if head.returncode == 0 else ""
        bundle = build_bundle(checkout, commit=commit,
                              generated_at=datetime.now(UTC).isoformat())
        write_bundle(bundle, checkout)
        return len(bundle.module_map.modules)
    except Exception:  # noqa: BLE001 — a navigation aid is never worth failing onboarding for
        log.warning("could not build the module map during onboarding", exc_info=True)
        return -1


def _pr_body(repo: str, out: RepoOutcome, *, manifest_proposed: bool) -> str:
    lines: list[str] = []
    if manifest_proposed:
        lines += [
            f"`{repo}`'s manifest, **read from the repository and then MEASURED**: the box ran "
            f"the proposed `setup:` and `validate:` before this pull request was opened.",
            "",
        ]
    else:
        lines += [f"`{repo}` already declares its manifest; this proposes what was missing.",
                  ""]
    if out.proof == "proven":
        lines.append("**Box proof: PASSED** — the commands below ran green inside the real box.")
        if out.proof_advisories:
            lines.append("")
            lines.append("**Advisory warnings (non-blocking tech debt):**")
            lines += [f"- {a}" for a in out.proof_advisories]
    elif out.proof.startswith("skipped"):
        lines.append(f"**Box proof: not taken** ({out.proof}) — "
                     f"run `openfactory box prove <project> --repo {repo}` after merging.")
    else:
        lines.append("**Box proof: FAILED** — merge only after reading these, they are "
                     "measurements, not lint:")
        lines += [f"- {f}" for f in out.proof_failures]
        if out.proof_advisories:
            lines.append("")
            lines.append("**Advisory warnings:**")
            lines += [f"- {a}" for a in out.proof_advisories]
    lines.append("")
    if out.modules >= 0:
        lines.append(f"`knowledge/` is the module map ({out.modules} modules) — parsed from "
                     f"the code, zero tokens, refreshed automatically after every merge. It is "
                     f"what lets an agent jump to the right file instead of searching for it.")
        lines.append("")
    if out.questions:
        lines.append("**Only your team can answer these — before merging:**")
        lines += [f"- {q}" for q in out.questions]
        lines.append("")
    lines.append("Correct anything wrong and merge. Until then the factory has no declaration "
                 "to obey for this repository.")
    return "\n".join(lines)


@dataclass
class ContextOutcome:
    """The product's context repository, onboarded — created or reused, backfilled, proposed."""

    docs_repo: str = ""
    created: bool = False
    ok: bool = False
    pr: str = ""
    #: how the backfill ran — "semantic" (one agent pass, citation-checked) or "deterministic"
    #: with the why (no harness credential, typically)
    backfill: str = ""
    #: documents written into the proposal (paths relative to the context repo)
    documents: list[str] = field(default_factory=list)
    #: the wiring only a human can commit (each source repo's `docs_repo:` line)
    todo: list[str] = field(default_factory=list)
    detail: str = ""


def onboard_product_context(project, *, sources: list[str],
                            stream: StageFn | None = None) -> ContextOutcome:
    """The context box: create-or-use the repository, backfill it, propose it — one PR.

    BOTH SHAPES, because a deployment has both at once — an enterprise organisation keeps a
    documentation repository on some projects and none on others: a `product.docs_repo` already
    in the registry is
    USED — cloned, read, merged into — and only a project with none gets a repository created
    in its own organisation (GitHub and Azure Repos both implement the capability; a forge
    without it refuses by name).

    THE BACKFILL RUNS WHERE THE FACTORY LIVES. The survey is deterministic; the one agent pass
    (citation-checked — a sentence whose `file:line` does not resolve is demoted into a
    question) runs only when the harness CLI *and* its credential are both present on this
    machine, and says which mode it took. No laptop anywhere.
    """
    import shutil as _shutil
    import subprocess

    from openfactory.onboarding.propose_manifest import (
        _git,
        already_proposed,
        last_error_was_rate_limit,
        open_review_request,
        scrub,
    )
    from openfactory.product.onboard import (
        PRODUCT_YAML,
        context_clone_url,
        context_forge,
        create_context_repository,
        plan,
        proposal_branch,
    )

    out = ContextOutcome()
    docs_repo = (getattr(getattr(project, "product", None), "docs_repo", "") or "").strip()
    if not docs_repo:
        _say(stream, "start", "context: no repository declared — creating one")
        try:
            docs_repo, out.created = create_context_repository(
                project, getattr(project, "name", "product"))
        except (ValueError, RuntimeError) as exc:
            out.detail = f"could not create the context repository: {exc}"
            return out
        # RE-READ WHAT WAS JUST RECORDED — the stale-object defect, third sighting prevented
        from openfactory.registry import ProjectRegistry

        try:
            project = ProjectRegistry().get(getattr(project, "name", ""))
        except KeyError:
            pass  # a doubled registry in a test may not answer; the record itself happened
    out.docs_repo = docs_repo

    _say(stream, "start", f"context: cloning {docs_repo}")
    url = context_clone_url(project, docs_repo)
    import tempfile

    root = Path(tempfile.mkdtemp(prefix="openfactory-context-"))
    try:
        rc, log_out = _git(["clone", url, str(root / "docs")])
        if rc != 0:
            out.detail = f"could not clone {docs_repo}: {scrub(log_out)[-200:]}"
            return out
        docs_clone = root / "docs"
        head = subprocess.run(["git", "-C", str(docs_clone), "rev-parse", "--abbrev-ref",
                               "HEAD"], capture_output=True, text=True, timeout=60,
                              check=False)
        named = (head.stdout or "").strip()
        born_empty = not (head.returncode == 0 and named and named != "HEAD")
        if born_empty:
            # A REPOSITORY BORN EMPTY HAS NO BRANCH — one checkout gives it a base every later
            # step assumes exists (the product-init precedent, incident and all).
            _git(["-C", str(docs_clone), "checkout", "-B", "main"])
            base = "main"
        else:
            # A repository WITH history keeps ITS default branch — `checkout -B main` here
            # rewrote a master/develop repo's base and the pull request then targeted a branch
            # the remote does not have (adversarial review, 2026-08-13).
            base = named

        result = plan(project, docs_clone, sources=sources)
        if result.refusal:
            out.detail = result.refusal
            return out
        out.todo = list(result.todo)

        _say(stream, "start", "context: the backfill — reading the source repository")
        out.backfill, written = _backfill(project, docs_clone, stream=stream)
        out.documents = written

        if result.already_correct and not written:
            out.ok = True
            out.detail = f"{docs_repo} already declares this product and the backfill found " \
                         f"nothing new to write"
            return out

        if not result.already_correct:
            target = docs_clone / PRODUCT_YAML
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(result.product_yaml, encoding="utf-8")

        _say(stream, "start", "context: opening the pull request")
        branch = proposal_branch(getattr(project, "name", "product"))
        forge = context_forge(project)
        # THROUGH THE PORT BEFORE ANY PUSH — the same discipline propose() earned in review. A
        # `--force` onto a branch with an OPEN review destroys whatever commits the client's
        # reviewer added to it; an open proposal is FOUND, not overwritten. Merged/closed reads
        # as "propose again" (already_proposed's state arm), and "could not ask" refuses.
        pushed_already = already_proposed(forge, docs_repo, branch)
        if pushed_already is None:
            out.detail = (f"could not ask {docs_repo} whether this context was already "
                          f"proposed, so nothing was pushed — asking again in a moment is "
                          f"safer than force-pushing over an open review")
            return out
        if pushed_already.strip():
            out.ok = True
            out.pr = pushed_already.strip()
            out.detail = f"the context was already proposed on {branch}"
            return out
        if born_empty:
            # No PR is possible against a base that has no commits — the forge refuses it. The
            # repository is empty (typically just created), so the declaration IS its first
            # content: pushed to the base itself, plainly (never --force — if somebody pushed
            # in the meantime, failing is the correct answer), and said in those words.
            for args in (["-C", str(docs_clone), "add", "-A"],
                         ["-C", str(docs_clone), "commit", "-m",
                          f"{getattr(project, 'name', 'product')}: declare this product and "
                          f"its backfilled context"],
                         ["-C", str(docs_clone), "push", "-u", url, base]):
                rc, log_out = _git(args)
                if rc != 0:
                    out.detail = f"git {args[2]} failed: {scrub(log_out)[-200:]}"
                    return out
            out.ok = True
            out.detail = (f"{docs_repo} was born empty — the declaration and backfill are its "
                          f"first commit on {base}; review them there")
            return out
        for args in (["-C", str(docs_clone), "checkout", "-b", branch],
                     ["-C", str(docs_clone), "add", "-A"],
                     ["-C", str(docs_clone), "commit", "-m",
                      f"{getattr(project, 'name', 'product')}: declare this product and its "
                      f"backfilled context"],
                     # the bot's OWN onboarding branch — a retry after a partial failure must
                     # replace, not dead-lock on a non-fast-forward (product init's rule); safe
                     # only BECAUSE the port said no open review exists on it
                     ["-C", str(docs_clone), "push", "--force", "-u", url, branch]):
            rc, log_out = _git(args)
            if rc != 0:
                out.detail = f"git {args[2]} failed: {scrub(log_out)[-200:]}"
                return out
        out.pr = open_review_request(
            forge, repo=docs_repo, head=branch, base=base,
            title=f"OpenFactory: {getattr(project, 'name', 'product')}'s context — declaration "
                  f"and backfill",
            body="\n".join([
                f"`{PRODUCT_YAML}` declares the product and which repositories implement it; "
                f"the documents are the BACKFILL — what the code says the product is today, "
                f"written to be corrected by the people who know it.",
                "",
                f"Backfill mode: {out.backfill}.",
                "",
                *(f"- still yours to commit: {t}" for t in out.todo),
            ]))
        out.ok = True
        # THE BRANCH IS THE WORK; the pull request is the ceremony. When the ceremony is only
        # WAITING on an API budget, saying "open it by hand" sends somebody to do work that
        # will do itself — so the two endings are different sentences (pilot, 2026-08-14: the
        # backfill landed complete and the operator was told to go open a PR).
        if out.pr:
            out.detail = f"proposed on {branch} — {out.pr}"
        elif last_error_was_rate_limit():
            out.detail = (f"proposed on {branch} — everything is pushed; the review request is "
                          f"waiting on this deployment's API budget, which refills within the "
                          f"hour. Re-run this command then and it opens the pull request; "
                          f"nothing is re-proposed")
        else:
            out.detail = (f"proposed on {branch} — the review request did not open; open it "
                          f"by hand")
        return out
    finally:
        _shutil.rmtree(root, ignore_errors=True)


def _carry_questions(project, proposal, *, surveyed: bool) -> None:
    """Carry the survey's questions in the ledger: close what a later look resolved, open what is
    newly asked. Best-effort — a memory write must never cost the backfill its documents.

    `surveyed` IS PASSED AND NOT INFERRED FROM THE QUESTION LIST. An empty list means "this survey
    earned nothing", and a survey that could not run earns nothing either; reading the second as
    the first would close every open question about a repository the platform can no longer see.
    The caller knows which happened, and only the caller does."""
    from openfactory.adapters.forge.registry import repo_of
    from openfactory.memory import store as loop_store
    from openfactory.onboarding.questions import carry

    try:
        repo = repo_of(project)
        rows = carry(repo, ledger=loop_store.read(project.name),
                     fresh=list(proposal.tracked), surveyed=surveyed,
                     ts=datetime.now(UTC).isoformat(timespec="seconds"))
        if rows:
            loop_store.write(project.name, rows)
    except Exception:  # noqa: BLE001 — telemetry of a kind; never derail the backfill
        log.warning("could not carry the backfill's questions in the ledger for %s — the "
                    "documents are unaffected and the questions stay as they were",
                    getattr(project, "name", "?"), exc_info=True)


def semantic_pass_for(project, source: Path) -> tuple[object | None, str]:
    """Can the backfill's one agent pass run on THIS machine, and the sentence saying why not.

    Returns `(ask_fn, mode)`. `ask_fn` is None whenever the deterministic half is all that can run;
    `mode` is what the outcome and the pull request body report, so it is written for a person
    deciding what to do next rather than for a log.

    EXTRACTED FROM `_backfill` so the decision can be tested without standing up a clone, a forge
    and a sandbox. It was four lines inside sixty, and the four were wrong.

    THE DEFECT THIS FIXES. The BINARY came from `harness_kind(project, "techlead")` — `codex`,
    `kimi`, `opencode` or `claude_code` — while the CREDENTIAL was two hardcoded Anthropic variable
    names:

        has_credential = bool(os.environ.get("CLAUDE_CODE_OAUTH_TOKEN")
                              or os.environ.get("ANTHROPIC_API_KEY"))

    So every deployment running any other harness took the else-branch on every onboarding,
    whatever it had configured, and was told *"no harness credential on this machine"* — false,
    naming no variable that would fix it, and pointing a reader at a token they do not need.
    `routes.resolve_route` already holds that knowledge for every harness; a second copy here is
    how two answers drift apart.

    A ROUTE THAT DECLARES NO REQUIREMENT MEANS THE PLATFORM CANNOT TELL, NOT THAT NOTHING IS
    NEEDED. `codex` and `kimi` reach the generic route with empty `requires`, because nobody here
    has verified which variable either reads — and inventing one would refuse a working deployment
    by name, which is the more expensive mistake. So an unknown route is ATTEMPTED, and
    `propose_context`'s own arms turn a harness that cannot authenticate into the deterministic
    pass with the real reason attached. Trying and being told why beats refusing and being told
    something untrue.

    AND A MISSING BINARY IS ITS OWN SENTENCE. One branch served both, so a machine that had simply
    not installed the harness was sent looking for a credential it already had.
    """
    import os

    from openfactory.onboarding import context as ctx

    try:
        import shutil as which_mod

        from openfactory.adapters.agent import build_asker
        from openfactory.adapters.agent.registry import harness_binary, harness_kind
        from openfactory.adapters.agent.routes import resolve_route
        from openfactory.adapters.sandbox.base import Workspace
        from openfactory.adapters.sandbox.registry import judging_worktree

        kind = harness_kind(project, "techlead")
        binary = harness_binary(kind)
        route = resolve_route(project, role="techlead")
        missing = route.missing(dict(os.environ))

        if not which_mod.which(binary):
            return None, (f"deterministic (the {kind} binary `{binary}` is not on this machine's "
                          f"PATH — the survey still reads the repository; run "
                          f"`env context --ask` later for the prose pass)")
        if missing:
            return None, (f"deterministic (no harness credential on this machine for the "
                          f"{route.name} route — it needs {' and '.join(missing)}; the survey "
                          f"still reads the repository; run `env context --ask` later for the "
                          f"prose pass)")
        ask_fn = ctx.agent_ask(
            build_asker(project),
            sandbox=judging_worktree(project, root=source),
            workspace=Workspace(path=str(source), branch="main", base_branch="main"))
        return ask_fn, "semantic (one agent pass, every claim citation-checked)"
    except Exception:  # noqa: BLE001 — the deterministic half must survive a broken harness
        log.warning("could not build the backfill's agent pass — deterministic only",
                    exc_info=True)
        return None, "deterministic (the agent pass could not be built)"


def _concept_budget(project, source: Path) -> int:
    """How many concepts this project asked for. A manifest that cannot be read means the DEFAULT,
    never zero: a repository whose manifest is missing or malformed is the exact shape that most
    needs describing, and reading "no manifest" as "no concepts wanted" would silently switch the
    feature off precisely there."""
    from openfactory.contracts.manifest import Manifest
    from openfactory.loader import load_manifest

    try:
        manifest = load_manifest(project, repo_root=source)
    except Exception as exc:  # noqa: BLE001 — an unreadable manifest is a default, not a crash
        log.info("the concept budget falls back to the default (%s)", str(exc)[:160])
        return Manifest().okf_concept_budget
    return int(getattr(manifest, "okf_concept_budget", Manifest().okf_concept_budget))


def _coverage(survey, concepts, *, budget: int) -> list:
    """What was described, what was not, and — when the answer is "not" — WHY.

    THE DENOMINATOR IS THE POINT. `concepts: 5` alone is a number a reader must interpret; `5 of
    412 modules, because a budget of 5 was declared and these were the most-changed, widest-reach,
    least-understood ones` is a decision somebody can disagree with. A bundle that omits the
    denominator implies a completeness it does not have, which is the failure this whole artifact
    exists to make impossible.

    ONE ROW PER CONCEPT TYPE, PLUS THE MODULE ROW, because the two answer different questions: the
    module row says how much of the repository was looked at, and a type row says what kind of
    knowledge came back. A client whose bundle is fourteen `configuration` concepts and no
    `policy` learns something from that shape that no total can tell them.
    """
    from openfactory.knowledge.contracts import CoverageRow

    described = len(concepts)
    total = len(survey.modules)
    rows = [CoverageRow(
        kind="module", inventoried=total, concepts=described,
        reason=("" if described >= total else
                f"a budget of {budget} was declared; the {described} module(s) with the most "
                f"change, the widest reach and the least known purpose were described first — "
                f"the other {total - described} are inventoried and undescribed"))]
    by_type: dict[str, int] = {}
    for concept in concepts:
        by_type[concept.type] = by_type.get(concept.type, 0) + 1
    rows += [CoverageRow(kind=kind, inventoried=count, concepts=count)
             for kind, count in sorted(by_type.items())]
    return rows


def _write_concepts(project, survey, source: Path, docs_clone: Path, *,
                    ask_fn, commit: str) -> list[str]:
    """Author the budgeted concepts and write them into the CONTEXT repository's `.okf/`.

    INTO THE CONTEXT REPO, NEVER THE CLIENT'S SOURCE — D-2, and the reasons are the ones that
    produced the orphan branch this platform has already retired: writing to a client's `main`
    fires their deploy, puts every open PR behind, and needs push rights on a protected branch.

    BEST-EFFORT, AND LOUD WHEN IT FAILS. The five documents above are the backfill's contract; the
    concepts are the richer half and must never cost a client the part that already worked. A
    failure here is logged with its reason and returns nothing written — the caller still reports
    the documents it did write."""
    from openfactory.knowledge.bundle import compute_checksums
    from openfactory.knowledge.contracts import OkfManifest
    from openfactory.knowledge.okf import OKF_DIRNAME, OKF_INDEX_FILE, render_index, write_okf
    from openfactory.onboarding.concepts import propose_concepts

    budget = _concept_budget(project, source)
    if budget <= 0:
        log.info("concepts: this project declares a budget of 0 — none authored")
        return []
    try:
        fingerprints = {c.file: c.sha256 for c in compute_checksums(source)}
        concepts, gaps = propose_concepts(
            survey, ask=ask_fn, budget=budget, commit=commit,
            generated_at=_now_iso(),
            language=getattr(project, "language", None),
            fingerprints=fingerprints)
        manifest = OkfManifest(
            bundle_kind="source-repo", generated_at=_now_iso(), source_commit=commit,
            coverage=_coverage(survey, concepts, budget=budget),
            gaps=gaps,
            scope_limit=(
                "Machine-generated from the code and verified only by citation: every business "
                "rule here resolves to a line that existed at the commit above. That makes it "
                "checkable, not authoritative — it is a reading of what the system DOES, never a "
                "specification of what it SHOULD do, and it authorises no change on its own."))
        written = write_okf(docs_clone, manifest=manifest, concepts=concepts)
        index = Path(docs_clone) / OKF_DIRNAME / OKF_INDEX_FILE
        index.write_text(render_index(manifest, concepts), encoding="utf-8")
        written.append(index)
        return [str(p.relative_to(docs_clone)) for p in sorted(written)]
    except Exception as exc:  # noqa: BLE001 — never lose the five documents to the richer half
        log.warning("concepts: not written (%s)", str(exc)[:240])
        return []


def _now_iso() -> str:
    from datetime import UTC, datetime

    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _backfill(project, docs_clone: Path, *, stream: StageFn | None) -> tuple[str, list[str]]:
    """Survey + the repository's own history + (when possible) one citation-checked agent pass."""
    import shutil as _shutil

    from openfactory.adapters.forge.registry import clone_url_for, repo_of
    from openfactory.credentials import deployment_forge_token, forge_token_for
    from openfactory.onboarding import context as ctx
    from openfactory.onboarding.history import read_history
    from openfactory.onboarding.propose_manifest import clone_for_proposal

    # the same last-resort as the source half — without it the backfill silently degrades to
    # "skipped: could not clone" on the App-only credential shape
    source_url = clone_url_for(project, repo_of(project),
                               token=forge_token_for(project) or deployment_forge_token(project))
    # HISTORY, WHICH IS WHY THIS ONE CLONE DIFFERS FROM THE SOURCE HALF'S. `--depth 1` carries one
    # commit, and on a legacy repository the log is the input that says WHERE to spend this pass —
    # a module nobody has touched since 2019 does not need a concept before the factory can start.
    # The request degrades to the shallow clone by itself, and `read_history` then names the
    # shallow checkout rather than reporting a repository that never changes.
    source, why = clone_for_proposal(clone_url=source_url, history=True)
    if source is None:
        return f"skipped: could not clone the source repository ({why})", []
    try:
        ask_fn, mode = semantic_pass_for(project, source)

        # The impure half of the survey, done by the caller on purpose: `ctx.survey` promises no
        # subprocess, and reading a log runs `git`. Never raises — a repository whose history
        # cannot be read still gets the whole deterministic survey, with the reason stated.
        history = read_history(source)
        if not history.usable:
            log.info("the backfill is reading %s without its history: %s",
                     repo_of(project), history.unavailable)
        survey = ctx.survey(str(source), history=history)
        # THE PROJECT'S OWN LANGUAGE, like every other voice this platform has. The backfill
        # was the one that never asked: `propose_context` fell back to the module default, so a
        # deployment registered `--language en` still received documents in the default's
        # language — right by accident wherever the two agreed, and wrong in silence everywhere
        # else (the operator, reading a Portuguese backfill, 2026-08-14). The registry carries
        # the decision; this reads it.
        proposal = ctx.propose_context(
            survey, ask=ask_fn, docs_root=docs_clone,
            language=getattr(project, "language", None) or ctx.DEFAULT_LANGUAGE)
        _carry_questions(project, proposal, surveyed=True)
        if not proposal.ok:
            return f"skipped: {proposal.refusal}", []
        outcome = ctx.write_documents(proposal, docs_clone, consent=True)
        wrote = list(outcome.wrote)
        wrote += _write_concepts(project, survey, source, docs_clone,
                                 ask_fn=ask_fn, commit=history.head)
        return mode, wrote
    finally:
        _shutil.rmtree(source, ignore_errors=True)
