"""Assemble the AgentContext — the "manual" the worker wears (ADR-0001 D-2/D-9/D-10).

- constraints (ADRs): loaded in full, always (the constitution).
- guidelines: the small house rules the agent can't guess (e.g. "100% coverage is
  enforced" — the thing that makes the difference between a passing and a failing run).
- doc_index: a *derived* table-of-contents of the large architecture docs (glob +
  each doc's front-matter summary / first heading), which the agent pulls from on
  demand — never a hand-maintained index (D-10).
"""

from __future__ import annotations

import logging
from pathlib import Path

import yaml

from openfactory.adapters.agent.base import AgentContext
from openfactory.contracts import Manifest, Ticket
from openfactory.knowledge import load_agent_knowledge
from openfactory.orchestrator import operator_guidelines
from openfactory.policy.profiles import ResolvedProfile

_log = logging.getLogger("openfactory.orchestrator.context")
_DEFAULT_TOOLS = ["Read", "Edit", "Write", "Bash", "Grep", "Glob"]
_MAX_DOC_CHARS = 8000


def _md_files(repo: Path, glob: str | None) -> list[Path]:
    if not glob:
        return []
    # A trailing "**" means "everything under here, recursively" — but pathlib matches a
    # bare trailing "**" inconsistently across Python versions (3.11 yields the files under
    # it; 3.12+ yields only directories, so the files silently vanish and constraints load
    # empty — this once turned CI red on 3.12 while green on 3.11). Normalize it to the
    # explicit "**/*", which reliably yields files (incl. those directly in the dir) on both.
    if glob.endswith("/**") or glob == "**":
        glob += "/*"
    return sorted(p for p in repo.glob(glob) if p.is_file() and p.suffix == ".md")


ORG_DEFAULTS_DIR = Path(__file__).resolve().parent.parent / "org_defaults"

#: Why `resolve_inside` refuses an entry. The job's warning branches on them and the doctor's
#: `guidelines` line says them, so the two surfaces cannot drift into two vocabularies (#350).
OUTSIDE = "outside the repository"
ITSELF = "the repository itself, not a file"


def resolve_inside(repo_path: Path, relative: str) -> tuple[Path, str]:
    """Where `relative` resolves in the checkout, and why the job refuses it — `""` if it does not.

    THE RULE WITHOUT ITS VOICE (#350). `_inside` is the job's door and says each refusal in its
    log; `openfactory doctor` asks this same function of the project's checkout before the first
    job and says the answer in its `guidelines` line. The doctor used to read the manifest's text
    alone, so a guideline committed as a link out of the repository passed there while every job
    refused it here and the agent ran without it — the shape of a deployment that symlinks its
    central standards into each repository, the workaround #318 was filed about. One function
    decides for both, so they cannot disagree again.

    The resolved path comes back even when refused, so a refusal can say where a link leads.
    Raises `OSError` when the join cannot be resolved; `_inside` reads that as a refusal."""
    root = repo_path.resolve()
    candidate = (repo_path / relative).resolve()
    if candidate == root:
        # THE ROOT IS NOT OUTSIDE, and saying so would send somebody looking for an escape that
        # is not there (review of #346): `.`, `docs/..` or an empty entry names the repository
        # itself, which is no file to read
        return candidate, ITSELF
    if not candidate.is_relative_to(root):
        return candidate, OUTSIDE
    return candidate, ""


def _inside(repo_path: Path | None, relative: str, *, named_by: str = "a profile") -> Path | None:
    """`repo_path / relative`, or None if that escapes the checkout.

    A profile is an asset and assets are read into the PROMPT. `../../../etc/passwd` as a
    `replace:` target would put whatever it found in front of the model, so the join is contained
    the way `util/scratch.py` contains its own: resolve, then require the result to still be under
    the root (`resolve_inside`). Resolving is what also refuses a link committed inside the
    repository that points out of it.

    `docs.guidelines` goes through the same door (#329). It is the repository's own content — the
    manifest lives in the tree the agent edits — so an absolute entry, or one that climbs out,
    named any readable file on the worker and had it inlined into the prompt. Refusing it is LOUD,
    never a quiet absence: the job's log names the entry and where central guidelines belong, and
    `openfactory doctor` fails the project before the first job (`doctor._guidelines`).
    """
    if repo_path is None:
        return None
    try:
        candidate, refused = resolve_inside(repo_path, relative)
    except OSError:
        return None
    if refused == ITSELF:
        _log.warning(
            "%s names %r, which is the repository itself, not a file — REFUSED, and the agent "
            "runs WITHOUT it; name the guideline's file.", named_by, relative)
        return None
    if refused == OUTSIDE:
        _log.warning(
            "%s names %r, which resolves outside the checkout — REFUSED, and the agent runs "
            "WITHOUT it. Guideline paths are read into the agent's prompt, so they stay inside "
            "the repository; an organisation's central guidelines belong in %s, which the "
            "operator sets.", named_by, relative, operator_guidelines.ENV_VAR)
        return None
    return candidate


def declared_guidelines(manifest) -> list[tuple[str, str]]:
    """Every guideline path the manifest names, with the key that names it — `docs.guidelines`
    first, then each component's — for the job that reads them and the doctor that checks them."""
    named = [("docs.guidelines", g) for g in manifest.docs.guidelines]
    for name, comp in manifest.components.items():
        named += [(f"components.{name}.guidelines", g) for g in comp.guidelines]
    return named


def _resolve_tier(docs: list[Path], profile: ResolvedProfile | None,
                  repo_path: Path | None, *, source: str) -> list[str]:
    """Read an ordered list of NAMED guideline files, applying the profile's waive/replace.

    ONE MECHANISM, TWO TIERS. The framework baseline (`org_defaults/*.md`) and the operator's own
    guidelines are both addressed by filename, and a profile waives or replaces either the same
    way (#318). `source` names where a KEPT file comes from — "framework's own", "operator's own" —
    for the one warning that mentions it: a replacement that is not in the checkout must not
    subtract the standard it was meant to replace.

    Does NOT warn about a waive/replace naming a file no tier has: that is decided ONCE, across
    both tiers together, by `_unknown_names` — a name unknown here may be known there."""
    if profile is None:
        return [p.read_text()[:_MAX_DOC_CHARS] for p in docs]
    waived = set(profile.waived_guidelines())
    replaced = profile.replaced_guidelines()
    out: list[str] = []
    for p in docs:
        if p.name in waived:
            continue
        substitute = replaced.get(p.name)
        if substitute is not None:
            doc = _inside(repo_path, substitute)
            if doc is not None and doc.is_file():
                out.append(doc.read_text()[:_MAX_DOC_CHARS])
                continue
            # THE ORIGINAL FILE STAYS. A replacement that is not there must not subtract: the
            # project asked for a different rule, not for no rule, and honouring half of that
            # would silently drop a standard on a bad path.
            _log.warning(
                "profile %s replaces %r with %r and no such file exists in the checkout — the "
                "%s %s is used instead; check the path.",
                " → ".join(profile.names), p.name, substitute, source, p.name)
        out.append(p.read_text()[:_MAX_DOC_CHARS])
    return out


def _unknown_names(profile: ResolvedProfile, known: set[str]) -> None:
    """Warn for every waived/replaced name no waivable tier actually has.

    A profile that waives or replaces a file no tier defines is a declaration written against a
    platform that has moved — the file was renamed, or the name was a guess. It reads as though a
    rule was dropped when the rule is still being injected, which is the most expensive shape of
    silence here: the operator believes the class is looser than it is. Decided across BOTH the
    framework baseline and the operator tier, so waiving an operator guideline by name is not
    mistaken for a typo."""
    named = set(profile.waived_guidelines()) | set(profile.replaced_guidelines())
    for name in sorted(named - known):
        # THE WHOLE CHAIN, NOT THE LEAF. These entries accumulate from every profile in the
        # `extends` chain, so naming only the profile the manifest wrote sends an operator to grep
        # the one file that does not contain the line.
        _log.warning(
            "profile %s names %r and no such framework or operator guideline exists — the "
            "deployment ships %s. That line of the profile changes NOTHING; check the name.",
            " → ".join(profile.names), name, ", ".join(sorted(known)) or "none")


def _org_defaults(profile: ResolvedProfile | None = None,
                  repo_path: Path | None = None,
                  extra_known: set[str] | None = None) -> list[str]:
    """Framework-owned baseline guidelines (openfactory/org_defaults/*.md).

    THIS USED TO SAY "injected into EVERY job regardless of project", and that sentence was the
    measurement of what the platform could not express. A throwaway proof-of-concept and a
    regulated bank's legacy monolith received the same twelve engineering rules and the same TDD
    mandate, because the platform had no word for what a project IS. The profile is that word, and
    this is the first place it changes anything.

    WITH NO PROFILE NOTHING MOVES. `None` returns exactly what this function always returned, so a
    project that declares no class is unaffected — most will not declare one, and a dimension that
    quietly re-rules existing projects would be a migration disguised as a feature.

    THE DIRECTION A PROFILE MAY MOVE THESE. Guidelines are prose — the weak form of a rule by this
    platform's own thesis — so a class may drop and substitute them; that is the declaration doing
    its job rather than bureaucracy. Gates are the strong form and a profile cannot reach them: the
    floor stays unconditional, and removing a floor gate is an exception, which is a waiver with a
    name and an expiry on it.

    `extra_known` names the OPERATOR tier's filenames, so a profile waiving one of them is not
    warned about here as though the name were a typo — the unknown-name warning spans both
    waivable tiers.
    """
    baseline = [p for p in sorted(ORG_DEFAULTS_DIR.glob("*.md")) if p.is_file()]
    if profile is None:
        return [p.read_text()[:_MAX_DOC_CHARS] for p in baseline]

    known = {p.name for p in baseline} | (extra_known or set())
    _unknown_names(profile, known)
    out = _resolve_tier(baseline, profile, repo_path, source="framework's own")

    for extra in profile.extra_guidelines():
        doc = _inside(repo_path, extra)
        if doc is not None and doc.is_file():
            out.append(doc.read_text()[:_MAX_DOC_CHARS])
        else:
            _log.warning(
                "profile %s extends the guidelines with %r and no such file exists in the "
                "checkout — the agent runs WITHOUT it; check the path.",
                " → ".join(profile.names), extra)
    return out


def _warn_if_a_name_lives_in_both_tiers(profile: ResolvedProfile | None,
                                        operator: operator_guidelines.OperatorTier) -> None:
    """Say so when a profile addresses a filename that BOTH tiers carry (review of #328).

    Guidelines are addressed by bare filename, and `_resolve_tier` runs the same profile against
    the framework baseline and the operator tier. So an organisation that ships its own `tdd.md` —
    a name `org_defaults/` already uses — finds that one `waive: [tdd.md]` drops BOTH files, and
    one `replace:` injects the substitute twice. The profile is written for one of them and
    silently acts on two, which is the ambiguity this names.

    A WARNING RATHER THAN A RULE, deliberately: which of the two the author meant cannot be read
    off the file, and guessing would be worse than saying so. Namespacing the operator's names
    (`operator:tdd.md`) would remove the ambiguity instead of reporting it, and that is a contract
    change with a migration behind it, not a line in this function."""
    if profile is None or not operator.guideline_docs:
        return
    addressed = set(profile.waived_guidelines()) | set(profile.replaced_guidelines())
    if not addressed:
        return
    baseline = {p.name for p in ORG_DEFAULTS_DIR.glob("*.md") if p.is_file()}
    both = sorted(({p.name for p in operator.guideline_docs} & baseline) & addressed)
    if both:
        _log.warning(
            "profile %s names %s, and %s carries a file with that name as well as the framework "
            "baseline — a guideline is addressed by bare filename, so the profile acts on BOTH "
            "copies. Rename one of them if only one was meant.",
            " → ".join(profile.names), ", ".join(repr(n) for n in both),
            operator_guidelines.ENV_VAR)


def _doc_summary(path: Path) -> str:
    text = path.read_text()
    if text.startswith("---"):
        parts = text.split("---", 2)
        if len(parts) == 3:
            fm = yaml.safe_load(parts[1]) or {}
            if isinstance(fm, dict) and fm.get("summary"):
                return str(fm["summary"])
    for line in text.splitlines():
        if line.startswith("#"):
            return line.lstrip("# ").strip()
    return path.stem


def build_context(
    manifest: Manifest, repo_path: Path, ticket: Ticket, *, knowledge_map: str | None = None,
    knowledge_path: Path | None = None, knowledge_bundle_dir: Path | None = None,
    profile: ResolvedProfile | None = None, reference_root: str | None = None,
) -> AgentContext:
    constraints = [
        p.read_text()[:_MAX_DOC_CHARS] for p in _md_files(repo_path, manifest.docs.constraints)
    ]
    # A declared doc-role that resolves to zero files is almost always a bug (bad glob or
    # missing docs), and it degrades the agent SILENTLY — it just runs with less project
    # knowledge. Surface it (→ stdout → CloudWatch) instead of swallowing it. (This is how
    # a Python-3.12 glob change once dropped every project's constraints unnoticed.)
    if manifest.docs.constraints and not constraints:
        _log.warning(
            "docs.constraints %r matched no .md files — the agent runs WITHOUT the "
            "project's constraints (ADRs); check the path/glob.", manifest.docs.constraints
        )

    guideline_paths = declared_guidelines(manifest)
    # The DEPLOYMENT's own guidelines (#318) — an organisation's central standards, contained.
    # A missing or empty directory WARNS the way `docs.constraints` does above: a setting nobody
    # honours degrades the agent silently otherwise.
    operator = operator_guidelines.gather()
    if operator.missing:
        _log.warning(
            "%s names %s and no such directory exists — every job runs WITHOUT the operator's "
            "central guidelines; check the path.", operator_guidelines.ENV_VAR, operator.dir)
    elif operator.empty:
        _log.warning(
            "%s names %s and it holds no .md guidelines — every job runs WITHOUT the operator's "
            "central guidelines; check the directory.", operator_guidelines.ENV_VAR, operator.dir)
    _warn_if_a_name_lives_in_both_tiers(profile, operator)
    # THE ORDER IS THE WEIGHT (#318): framework baseline first (shaped by the project's class, if
    # it declares one), THEN the operator's own guidelines, THEN the project's own house rules —
    # so a class outranks the framework, the deployment outranks the class, and the project keeps
    # the last word. A profile waives/replaces the operator tier by name exactly as it does the
    # framework's, so its filenames join the known set the unknown-name warning checks against.
    guidelines = _org_defaults(profile, repo_path,
                               {p.name for p in operator.guideline_docs})
    guidelines += _resolve_tier(operator.guideline_docs, profile, repo_path,
                                source="operator's own")
    for named_by, g in guideline_paths:
        # CONTAINED (#329): the manifest is the repository's, so what it names is read from it
        doc = _inside(repo_path, g, named_by=named_by)
        if doc is None:
            continue
        if doc.is_file():
            guidelines.append(doc.read_text()[:_MAX_DOC_CHARS])
        else:
            # Same rule as the two globs above, which had the warning while this list dropped
            # entries in silence (v2 verification pass, 2026-08-10): a guideline the manifest
            # NAMES and the checkout lacks degrades the agent quietly — a rule the team wrote
            # down and nobody is following, with nothing saying so.
            _log.warning(
                "%s names %r and no such file exists in the checkout — the agent runs WITHOUT "
                "that guideline; check the path.", named_by, g
            )

    index_lines = [
        f"{p.relative_to(repo_path)} — {_doc_summary(p)}"
        for p in _md_files(repo_path, manifest.docs.architecture)
    ]
    if manifest.docs.architecture and not index_lines:
        _log.warning(
            "docs.architecture %r matched no .md files — the agent gets no architecture "
            "index; check the path/glob.", manifest.docs.architecture
        )
    # The operator's `reference/` documents feed the SAME index, on the same terms (#318): a long
    # central standard is INDEXED (title + summary) and read on demand, never inlined on every job.
    #
    # AND THE PATH IS THE ONE THE AGENT CAN OPEN, which is the box's answer and not ours (review
    # of #328). These entries used to be labelled relative to the operator directory, like
    # `docs.architecture`'s repo-relative ones — and the agent works from the checkout: on a
    # container box the directory is not mounted at all, and on a worktree box `reference/big.md`
    # resolves INSIDE the repository, where it finds nothing or, worse, a different file with the
    # same name. `reference_root` is where this box can open them; without it they are not
    # indexed, because an entry the agent cannot open costs a tool call and reads as a document
    # somebody deleted.
    if operator.dir is not None and operator.reference_docs:
        if reference_root:
            index_lines += [
                f"{reference_root.rstrip('/')}/"
                f"{operator_guidelines.reference_label(operator.dir, p)} — {_doc_summary(p)}"
                for p in operator.reference_docs
            ]
        else:
            _log.warning(
                "%s holds %d reference document(s) and this box cannot reach %s, so they are NOT "
                "indexed — the agent is told about no document it cannot open. A container box "
                "needs that directory mounted; see `guidelines` in the box knobs.",
                operator_guidelines.ENV_VAR, len(operator.reference_docs), operator.dir)

    # Knowledge Layer, Phase 1 (opt-in via manifest.knowledge_map). Fail-safe: a missing,
    # stale, or orphaned bundle yields "" and the agent just searches the code as before —
    # we never inject knowingly-stale knowledge (§12). Freshness is checksum-based here
    # (git-free, deterministic), so this stays cheap and side-effect-free per job.
    #
    # WHICH TREE we judge matters. The bundle must be read from the JOB'S OWN CHECKOUT
    # (`knowledge_path` — the sandbox workspace), not from `repo_path`: repo_path is the shared,
    # long-lived base-branch clone, whose tree can differ from the commit this job actually runs
    # on (and, locally, can be dirty for reasons that have nothing to do with this ticket). The
    # map an agent is told to verify against must describe the code the agent is looking at.
    # None → fall back to repo_path (callers with no workspace, e.g. the sizer).
    #
    # And WHEN we judge it matters: only the CLEAN checkout is a valid verdict. A caller passes
    # `knowledge_map` to REUSE the value decided at the initial (pre-edit) pass — otherwise a
    # repair/recovery context, built after the agent already edited the workspace, would compare
    # the bundle against the agent's OWN uncommitted changes and spuriously flag it stale (a
    # false positive). None → compute now (the clean initial pass); a passed value (incl. "")
    # → reuse verbatim.
    if knowledge_map is None:
        knowledge_map = load_agent_knowledge(
            knowledge_path or repo_path, enabled=manifest.knowledge_map,
            bundle_dir=knowledge_bundle_dir,
        )

    return AgentContext(
        ticket=ticket,
        constraints=constraints,
        guidelines=guidelines,
        doc_index="\n".join(index_lines),
        knowledge_map=knowledge_map,
        allowed_tools=_DEFAULT_TOOLS,
    )


def _inlined_bytes(texts: list[str]) -> int:
    """How many BYTES these already-truncated documents cost in the prompt.

    BYTES, NOT CHARACTERS, and the two differ on this repository's own prose: `_MAX_DOC_CHARS`
    truncates to 8,000 CHARACTERS, and an ADR that spends any of them on `→`, `—` or an accented
    name runs longer once encoded (its README ADRs measure 8,066 bytes for 8,000 characters). The
    argv ceiling the total has to clear is a byte limit (`MAX_ARG_STRLEN`), so the count reported
    is the byte count the box will actually carry."""
    return sum(len(t.encode("utf-8")) for t in texts)


def inlined_document_bytes(manifest: Manifest, repo_path: Path, *,
                           profile: ResolvedProfile | None = None) -> dict[str, int]:
    """The BYTES each declared document role would inline into every agent pass, AFTER the same
    `_MAX_DOC_CHARS` truncation `build_context` applies — because that is what actually reaches the
    prompt (#7). One entry per role, always present (0 when the role names nothing), so a per-role
    line can point at the setting that changes it and the split cannot collapse into one number.

    NO BOUND IS INVENTED HERE. This reports what IS — #364 decides whether the platform should cap
    the sum, and PR #359 (a summed cap) was closed as superseded. The reads mirror `build_context`
    exactly, role by role, so the number is the one the job will pay and not a second estimate.

    THAT CLAIM IS CONDITIONAL ON `profile`, AND THE CALLER OWES IT (review of #370). A profile
    waives, replaces or extends the framework baseline and the operator tier (`_org_defaults`,
    `_resolve_tier`), so sizing a profiled project with `profile=None` measures a corpus no pass
    will ever inline. It fails in both directions: a profile that waives a baseline doc makes this
    OVER-report — the false-alarm direction `inlined_document_overflow`'s exemption exists to
    prevent — and one that adds guidelines makes it UNDER-report, staying silent on a real
    overflow. Resolve it as the executor does (`resolve_profile(manifest.profile,
    project_dir=root)`, `machine.py:906`) and hand it here."""
    repo = Path(repo_path)
    constraints = [
        p.read_text()[:_MAX_DOC_CHARS] for p in _md_files(repo, manifest.docs.constraints)
    ]
    operator = operator_guidelines.gather()
    framework = _org_defaults(profile, repo, {p.name for p in operator.guideline_docs})
    operator_tier = _resolve_tier(operator.guideline_docs, profile, repo, source="operator's own")
    project_docs: list[str] = []
    for named_by, g in declared_guidelines(manifest):
        doc = _inside(repo, g, named_by=named_by)
        if doc is not None and doc.is_file():
            project_docs.append(doc.read_text()[:_MAX_DOC_CHARS])
    return {
        "docs.constraints": _inlined_bytes(constraints),
        "framework baseline": _inlined_bytes(framework),
        "operator guidelines": _inlined_bytes(operator_tier),
        "docs.guidelines": _inlined_bytes(project_docs),
    }


def inlined_document_summary(per_role: dict[str, int]) -> str:
    """The one line both `doctor` and `box prove` print — the total, then the per-role split, so the
    two surfaces say the same sentence and neither can drift from the other."""
    total = sum(per_role.values())
    parts = "; ".join(f"{role}: {n:,} B" for role, n in per_role.items())
    return (f"{total:,} bytes of declared documents would inline into every pass, after "
            f"{_MAX_DOC_CHARS:,}-char truncation ({parts})")


def inlined_document_overflow(total: int, *, stages_input: bool, harness: str) -> str:
    """The note to add when `total` bytes would NOT fit a box that cannot hand the prompt over off
    the command line — the byte count, the per-argument limit, and the harnesses that cannot read a
    staged prompt. `""` when there is nothing to say: the documents fit `MAX_ARG_STRLEN`, OR this
    box stages input AND this harness can read it there (a staging box with a stdin-capable harness
    is unaffected and must not be told it has a problem, #7).

    A NOTE, NEVER A REFUSAL, and NO BOUND INVENTED. #360 already refuses an undeliverable prompt BY
    NAME at the moment a pass would start; this only makes the size knowable BEFORE then, from the
    manifest and the checkout alone. It reports what is; #364 decides whether a bound should exist.
    """
    from openfactory.adapters.agent.base import HARNESSES_WITHOUT_STAGED_PROMPT, MAX_ARG_STRLEN

    if total <= MAX_ARG_STRLEN:
        return ""
    reads_staged = harness not in HARNESSES_WITHOUT_STAGED_PROMPT
    if stages_input and reads_staged:
        return ""
    cannot = ", ".join(f"`{h}`" for h in sorted(HARNESSES_WITHOUT_STAGED_PROMPT))
    why = ("this box offers no staging channel" if not stages_input
           else f"the {harness!r} harness cannot read a staged prompt")
    return (
        f"the declared documents alone inline {total:,} bytes, past Linux's "
        f"{MAX_ARG_STRLEN:,}-byte per-argument limit (`MAX_ARG_STRLEN`) — and {why}, so a pass "
        f"would refuse the prompt BY NAME rather than deliver it. A box that stages input off argv "
        f"(the worktree and container boxes do) with a harness whose CLI can read it there is "
        f"unaffected; {cannot}-based harnesses cannot read a staged prompt. Nothing is capped here "
        f"— this is the size before a ticket spends anything."
    )
