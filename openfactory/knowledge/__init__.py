"""Knowledge Layer (Phase 1) — the deterministic module map.

`docs/knowledge-layer.md` is the design. Phase 1 ships the cheap, exact, LLM-free slice:
a generated `knowledge/` bundle (`modules.yaml` + `manifest.yaml`) per project that gives
the coding agent a map of "where things live + why", so it locates code faster instead of
rediscovering the repo on every ticket — then verifies against the real files (the code is
ground truth, §7).

Public surface:
- `build_bundle` / `write_bundle` / `read_bundle` — assemble, persist, and load the bundle.
- `build_module_map`                              — the deterministic generator (no LLM).
- `is_stale` / `orphan_links` / `is_trustworthy`  — the §12 staleness/consistency guards.
- `render_module_map`                             — the prompt-injection payload.
- `load_agent_knowledge`                          — the one call the orchestrator uses to get
                                                    injectable text (opt-in, fail-safe).
"""

from __future__ import annotations

from openfactory.knowledge.bundle import (
    build_bundle,
    compute_checksums,
    derived_key,
    read_bundle,
    read_bundle_dir,
    write_bundle,
)
from openfactory.knowledge.check import CheckReport, ConceptCheck, check_concepts, stale_bundle_gap
from openfactory.knowledge.contracts import (
    BundleManifest,
    KnowledgeBundle,
    Module,
    ModuleMap,
    SourceChecksum,
    SourceLink,
    UnreadExtension,
)
from openfactory.knowledge.gate import GateReport, judge
from openfactory.knowledge.generator import (
    build_module_map,
    canonical_source_files,
    survey_extensions,
)
from openfactory.knowledge.render import render_module_map
from openfactory.knowledge.service import load_agent_knowledge
from openfactory.knowledge.staleness import is_stale, is_trustworthy, orphan_links

__all__ = [
    "BundleManifest",
    "CheckReport",
    "GateReport",
    "ConceptCheck",
    "KnowledgeBundle",
    "Module",
    "ModuleMap",
    "SourceChecksum",
    "SourceLink",
    "UnreadExtension",
    "build_bundle",
    "build_module_map",
    "canonical_source_files",
    "check_concepts",
    "compute_checksums",
    "judge",
    "derived_key",
    "is_stale",
    "is_trustworthy",
    "load_agent_knowledge",
    "orphan_links",
    "read_bundle",
    "read_bundle_dir",
    "render_module_map",
    "stale_bundle_gap",
    "survey_extensions",
    "write_bundle",
]
