"""Load a project's manifest from its repo (the `.openfactory/project.yaml` plug)."""

from __future__ import annotations

import logging
from pathlib import Path

import yaml
from pydantic import ValidationError

from openfactory import namespace
from openfactory.contracts import Manifest
from openfactory.contracts.project import Project

log = logging.getLogger("openfactory.loader")


def load_manifest_base_branch(project: Project, *, default: str = "main") -> str:
    """The base branch to fetch, WITHOUT reading the manifest — which lives inside the checkout we
    are about to make. Chicken and egg: the registry's `tracker.options` may name it, otherwise
    `default`.

    `default=""` MEANS "NOBODY SAID, LET THE CLONE LAND WHERE THE REPOSITORY POINTS", and it is
    what every caller that can pass it on should ask for. The old fixed `"main"` was not a wrong
    guess costing one extra fetch, as this docstring used to claim — it was `git clone --branch
    main` naming a branch that does not exist on a `master`, `develop` or `trunk` repository, so
    the clone FAILED and the caller degraded with a message about reachability."""
    named = (getattr(project, "tracker", None)
             and (project.tracker.options or {}).get("base_branch"))
    return named or default


def load_manifest(project: Project, *, repo_root: Path | None = None) -> Manifest:
    """The project's manifest, from its checkout.

    `repo_root` overrides where to look, for callers that have already resolved it — everything on
    the job path has, and re-resolving would fetch twice. Unset, it resolves the same way, which is
    what makes a URL-registered project readable at all: this used to do
    `Path(project.repo_path)` and produced `https:/github.com/o/n.git/.sdlc/project.yaml` in an
    error message a client would read as their own mistake (#65).
    """
    if repo_root is None:
        from openfactory.factory import resolve_repo_path

        repo_root = resolve_repo_path(project)
    # A REPOSITORY STILL ON THE DIRECTORY'S RETIRED NAME IS REFUSED HERE, BY NAME: `resolve` raises
    # a `FileNotFoundError` whose sentence says what to rename, and it travels the same road as a
    # missing manifest — the doctor's finding, the job's park reason, the CLI's refusal. A reader
    # that merely did not look there would report "no manifest" to somebody looking at one. When
    # nothing is there at all the error names the path we use, so a client is told what to create.
    manifest_file = namespace.resolve(repo_root, project.manifest_path, project=project.name)
    if not manifest_file.exists():
        # THE REMEDY HAS TO MATCH HOW THIS PROJECT IS REGISTERED. `project init` scaffolds into a
        # LOCAL checkout; for a project registered by clone URL — the shape the compose worker
        # uses — it writes nothing and says so, so naming it here sent the pilot operator to a
        # command that could not help (2026-08-13). The environment session is the answer either
        # way, and `--pr` is the answer when there is no checkout anywhere.
        raw = str(getattr(project, "repo_path", "") or "")
        by_url = "://" in raw or raw.startswith("git@")
        how = (f"`openfactory env apply {project.name} --yes --pr` proposes it as a pull request "
               f"on the repository (no checkout needed anywhere), or run "
               f"`openfactory env read <your-checkout>` and `env apply <your-checkout> --yes` "
               f"where the repository is"
               if by_url else
               f"`openfactory env read {raw or '<your-checkout>'}` proposes it and "
               f"`openfactory env apply {raw or '<your-checkout>'} --yes` writes it")
        raise FileNotFoundError(
            f"project {project.name!r} has no manifest at {manifest_file}. {how}."
        )
    try:
        data = yaml.safe_load(manifest_file.read_text()) or {}
    except yaml.YAMLError as exc:
        raise ValueError(f"{manifest_file} is not valid YAML: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError(
            f"{manifest_file} must be a YAML mapping, not {type(data).__name__} — a manifest that "
            "parses to a list or a bare string would fail later as a missing field."
        )
    try:
        manifest = Manifest(**data)
        _say_what_is_inert(project, data)
        return manifest
    except ValidationError as exc:
        # One deployment hosts N projects. "manifest version 42 is not supported" is true and
        # useless without the path: the operator has to know WHICH client's repository to open.
        raise ValueError(f"{manifest_file} (project {project.name!r}) is invalid: {exc}") from exc


#: Manifest keys the schema still ACCEPTS and nothing reads. Kept loadable so an existing
#: project.yaml does not break, which is right — but silence let a client set a blast-radius
#: ceiling, load cleanly, and run with none.
_INERT: dict[str, str] = {
    "max_plan_files": "sizing is INVEST-only since ADR-0013 — use `max_cost_usd` for a real "
                      "ceiling",
    "max_plan_steps": "sizing is INVEST-only since ADR-0013 — use `max_cost_usd` for a real "
                      "ceiling",
    # A SECURITY-SHAPED PROMISE, which is the worst kind to leave inert: manifest.py:209 calls it
    # "project-level tightening of permissions (never loosening)", and a client's security
    # reviewer reads that and writes it into their onboarding document. Nothing reads the field.
    "permissions": "no call site reads it — per-project permission tightening is not implemented; "
                   "the box's isolation and `box.env` are what actually bound a run",
}


#: The environment names the promotion tail actually observes. `PromotionRunner` asks for these
#: two BY NAME (`promotion.py`), so an environment called anything else is declared, validated and
#: read by nothing.
#:
#: The DERIVED default — what the tail walks when no `promote:` is declared. It stopped being a
#: transcription of two `.get()` literals the day the tail learned the declared chain (#109):
#: `Manifest.promotion_chain()` is the one answer now, this tuple mirrors its no-chain branch,
#: and the guard checks the two agree BEHAVIOURALLY (a three-environment manifest, both modes)
#: instead of reading the runner's source.
OBSERVED_ENVIRONMENTS = ("staging", "prod")


def _say_what_is_inert(project, data: dict) -> None:
    """Name every declared key that has no effect. A setting that loads cleanly and does nothing
    is worse than one that is rejected: the operator believes the guard is in place."""
    for key, why in _INERT.items():
        if data.get(key) is not None:
            log.warning(
                "OPENFACTORY_MANIFEST_INERT %s declares `%s` — it is accepted for "
                "compatibility and "
                ""
                "READ "
                "BY NOTHING, so it bounds nothing (%s)",
                getattr(project, "name", "?"), key, why)

    # AN ENVIRONMENT IS A KEY INSIDE A KEY, which is why the table above could not see it.
    # `environments` IS read, so the loop above passes it; the tail then asks for exactly
    # `staging` and `prod` by name and everything else is silently never observed.
    #
    # THREE ENVIRONMENTS IS THE CORPORATE NORM, not an edge case — dev/qa/prod, or
    # dev/homologação/produção, and in a regulated shop having the three separate with an approval
    # before the last is a change-management requirement written into a policy somebody audits. A
    # client declares them, the tail observes two, and the third produces no line anywhere: the
    # deployment believes it is being watched and it is not.
    #
    # A WARNING, NOT A REFUSAL, and the asymmetry is deliberate: the manifest is otherwise valid
    # and the work still merges. What is unacceptable is silence.
    declared = data.get("environments")
    if isinstance(declared, dict):
        chain = data.get("promote")
        observed = tuple(chain) if isinstance(chain, list) and chain else OBSERVED_ENVIRONMENTS
        unobserved = [name for name in declared if name not in observed]
        if unobserved:
            log.warning(
                "OPENFACTORY_MANIFEST_INERT %s declares environment(s) %s — the promotion tail "
                "walks only %s, so nothing watches these and nothing will say they are red. "
                "Add them to `promote:` (the chain the tail follows, in order, human gate before "
                "the last) — or remove them, so the manifest stops promising a watch that does "
                "not exist.",
                getattr(project, "name", "?"),
                ", ".join(f"`{n}`" for n in unobserved),
                ", ".join(f"`{n}`" for n in observed))
