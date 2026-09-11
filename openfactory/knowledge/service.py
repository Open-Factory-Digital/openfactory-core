"""The orchestrator-facing entrypoint: get injectable knowledge, safely.

`load_agent_knowledge` is the ONE call `build_context` makes. It is opt-in (a manifest flag),
fail-safe (a missing/stale/orphaned/corrupt bundle yields ""), and never raises — exactly the
posture §12 demands: serve the map only when we can trust it, otherwise the agent degrades to
searching the code directly.
"""

from __future__ import annotations

import logging
from pathlib import Path

from openfactory.knowledge.bundle import read_bundle, read_bundle_dir
from openfactory.knowledge.render import render_module_map
from openfactory.knowledge.staleness import is_trustworthy

_log = logging.getLogger("openfactory.knowledge.service")


def load_agent_knowledge(
    repo_path: Path, *, enabled: bool, bundle_dir: Path | None = None
) -> str:
    """Injectable module-map text for the coding agent, or "" to inject nothing.

    `repo_path` must be the checkout the AGENT will work in (the job's workspace), not a shared
    base clone — the map is a claim about the code the agent is about to read, and it is only
    honest if it was verified against that exact tree.

    `bundle_dir` is where the bundle itself was read from, when that is NOT inside `repo_path`.
    Phase 2 publishes the bundle into the project's context repository (see
    `pipeline.okf_subpath`, D-2/D-3) and hands the job a temp checkout of it: the two are
    deliberately separate, because a bundle planted inside the workspace would be swept into the
    ticket's commit by `git add -A` and every PR would carry a copy of the map. Verification still
    happens against `repo_path` — the checksums must match the tree the agent will actually edit,
    wherever the YAML came from.

    Returns "" when: the feature is off (`enabled=False`); no bundle exists; or the bundle is
    stale / has orphan links / is unreadable (`is_trustworthy` fails). Best-effort — any
    unexpected error degrades to "" rather than failing the job."""
    if not enabled:
        return ""
    try:
        bundle = read_bundle_dir(bundle_dir) if bundle_dir else read_bundle(repo_path)
        if not is_trustworthy(bundle, repo_path):
            if bundle is not None:
                _log.info("knowledge: bundle present but not trustworthy — not injecting")
            return ""
        assert bundle is not None  # is_trustworthy(None) is False, so this holds
        return render_module_map(bundle)
    except Exception as exc:  # noqa: BLE001 — knowledge is a bonus; never crash the caller
        _log.warning("knowledge: load failed (%s) — running without the map", exc)
        return ""
