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


def _org_defaults() -> list[str]:
    """Framework-owned baseline guidelines (openfactory/org_defaults/*.md), injected into
    EVERY job regardless of project — the standards the agent can never skip."""
    d = Path(__file__).resolve().parent.parent / "org_defaults"
    return [p.read_text()[:_MAX_DOC_CHARS] for p in sorted(d.glob("*.md")) if p.is_file()]


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
    # framework baseline first (always), then the project's own house rules
    guidelines = _org_defaults()
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
