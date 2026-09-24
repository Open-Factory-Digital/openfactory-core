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


def _inside(repo_path: Path | None, relative: str) -> Path | None:
    """`repo_path / relative`, or None if that escapes the checkout.

    A profile is an asset and assets are read into the PROMPT. `../../../etc/passwd` as a
    `replace:` target would put whatever it found in front of the model, so the join is contained
    the way `util/scratch.py` contains its own: resolve, then require the result to still be under
    the root. The same class exists on `docs.guidelines` and is not made worse here.
    """
    if repo_path is None:
        return None
    try:
        root = repo_path.resolve()
        candidate = (repo_path / relative).resolve()
    except OSError:
        return None
    if candidate == root or not candidate.is_relative_to(root):
        _log.warning(
            "a profile names %r, which resolves outside the checkout — ignored. Guideline paths "
            "are read into the agent's prompt, so they stay inside the repository.", relative)
        return None
    return candidate


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
    profile: ResolvedProfile | None = None,
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

    guideline_paths = list(manifest.docs.guidelines)
    for comp in manifest.components.values():
        guideline_paths += comp.guidelines
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
    # THE ORDER IS THE WEIGHT (#318): framework baseline first (shaped by the project's class, if
    # it declares one), THEN the operator's own guidelines, THEN the project's own house rules —
    # so a class outranks the framework, the deployment outranks the class, and the project keeps
    # the last word. A profile waives/replaces the operator tier by name exactly as it does the
    # framework's, so its filenames join the known set the unknown-name warning checks against.
    guidelines = _org_defaults(profile, repo_path,
                               {p.name for p in operator.guideline_docs})
    guidelines += _resolve_tier(operator.guideline_docs, profile, repo_path,
                                source="operator's own")
    for g in guideline_paths:
        doc = repo_path / g
        if doc.is_file():
            guidelines.append(doc.read_text()[:_MAX_DOC_CHARS])
        else:
            # Same rule as the two globs above, which had the warning while this list dropped
            # entries in silence (v2 verification pass, 2026-08-10): a guideline the manifest
            # NAMES and the checkout lacks degrades the agent quietly — a rule the team wrote
            # down and nobody is following, with nothing saying so.
            _log.warning(
                "docs.guidelines names %r and no such file exists in the checkout — the agent "
                "runs WITHOUT that guideline; check the path.", g
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
    if operator.dir is not None:
        index_lines += [
            f"{operator_guidelines.reference_label(operator.dir, p)} — {_doc_summary(p)}"
            for p in operator.reference_docs
        ]

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
