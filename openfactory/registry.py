"""ProjectRegistry — the set of projects the framework drives.

A YAML file behind a small interface, so a Postgres-backed version drops in later without touching
callers. This is what makes "add another project" a first-class, data-only operation.

WHERE THE FILE LIVES IS THE WHOLE CARD (C-12). Reading was never the problem — `_load_raw` already
reads from disk on every call. The *deployment* was: `docker/worker.Dockerfile` copied the registry
to the very path the worker reads, so onboarding a repository meant `docker build` and a redeploy.
For a downloadable product that is disqualifying, and it is a live hazard on file: a rebuild that
ships without the gitignored `deploy/registry.yaml` produces a project-less worker that raises on
every job.

So the image now carries a SEED and the worker reads a writable path that outlives it:

    /etc/openfactory/registry.seed.yaml   baked, immutable, what this build was shipped knowing
    /var/lib/openfactory/registry.yaml    mounted, writable, what this deployment actually drives

`seed_registry()` copies the first to the second when — and only when — the second holds no
projects. That makes a fresh install never project-less AND makes a redeploy never revert a project
added at runtime. Getting either half wrong is silent: one leaves a board unpolled, the other
reverts it later.

TWO DURABILITY BUGS FIXED HERE, both reachable without anyone rebuilding anything:

    write_text TRUNCATES first  a crash between truncate and write leaves an EMPTY registry, which
                                is the same project-less worker
    no lock on read-modify-write two processes adding at once lose one of the two projects, and a
                                project that silently did not land is a board nobody polls
"""

from __future__ import annotations

import fcntl
import logging
import os
import tempfile
from contextlib import contextmanager
from pathlib import Path

import yaml
from pydantic import ValidationError

from openfactory.contracts.project import BoxConfig, Project

log = logging.getLogger("openfactory.registry")

#: Where a deployed worker keeps the registry it actually drives — writable and mounted, so it
#: survives the image. Overridden by `OPENFACTORY_REGISTRY` like everything else.
LIVE_REGISTRY_PATH = Path("/var/lib/openfactory/registry.yaml")

#: What the image was shipped knowing. Immutable, and only ever read.
SEED_REGISTRY_PATH = Path("/etc/openfactory/registry.seed.yaml")


# ── one process, one GitHub App installation (#64, C-28) ────────────────────────────────────────
#
# THE ASYMMETRY. The CHANNEL credential is per-project: `factory.notifier_for_project` reads the
# env var the registry names, so one deployment hosts N projects across N Slack workspaces, and
# `contracts/project.py` documents that as deliberate. The FORGE credential is not — the App's
# installation id is a process-wide environment variable (`credentials.app_installation_id`), and
# a GitHub App installation belongs to exactly ONE org. So one running process can only ever reach
# one org's repositories, `Project` has no field that could say otherwise, and nothing said so
# anywhere a person onboarding a project would look. The failure it produces is a 404 on a repo
# the operator can see in their browser.
#
# One deployment per organisation is the shape the platform is built for, so the limit is
# defensible — it just has to be TRUE and SAID rather than discovered. This makes it both.


def github_owners(project: Project) -> set[str]:
    """Which GitHub orgs this project's work actually touches. Pure, no I/O.

    ONLY the three provider axes and the board, and only when that axis is GitHub — a Jira
    `repo` is a project key (`CONT`), not an `owner/name`, and reading it as an org would refuse
    a perfectly valid mixed-vendor registry.

    DELIBERATELY EXCLUDED, each for its own reason:

        repo_path            may be a clone URL or a local path; it is where the code is FETCHED
                             from, and `RepoCache` already handles a URL. Not an authorisation fact
        factory_board        ADR-0027 puts the factory's OWN impediments on the factory's OWN board,
                             which is legitimately a different org from the client's — and the
                             shipped template does exactly that. `_warn_foreign_pointers` warns
        product.docs_repo    same shape: a client's requirements repo may live anywhere
    """
    owners: set[str] = set()
    for axis in (project.tracker, project.forge, project.ci):
        if axis is None or (axis.kind or "").strip().lower() != "github":
            continue
        repo = (axis.repo or "").strip()
        if "/" in repo:
            owners.add(repo.split("/", 1)[0])
        board_owner = (axis.options or {}).get("board_owner", "").strip()
        if board_owner:
            owners.add(board_owner)
    return owners


def spanning_installations(projects: list[Project]) -> dict[str, list[str]]:
    """`{owner: [project names]}` when the set spans more than one org — otherwise empty.

    Empty is the answer for the healthy case AND for a registry with no GitHub projects at all,
    so a caller reads "falsy means fine" without a special case."""
    by_owner: dict[str, list[str]] = {}
    for project in projects:
        for owner in github_owners(project):
            by_owner.setdefault(owner, []).append(project.name)
    return by_owner if len(by_owner) > 1 else {}


def _spanning_message(by_owner: dict[str, list[str]]) -> str:
    """The sentence somebody can act on: both orgs, and which projects sit in each."""
    parts = [f"{owner} ({', '.join(sorted(names))})" for owner, names in sorted(by_owner.items())]
    return (
        "this registry spans more than one GitHub organisation — " + " and ".join(parts) + ". "
        "One running process authenticates as ONE GitHub App installation, and an installation "
        "belongs to one org, so the projects outside it would 404 on every forge read. Run one "
        "deployment per organisation, or remove the projects that do not belong to this one."
    )


class ProjectRegistry:
    def __init__(self, path: Path | str | None = None) -> None:
        # env override lets the panel/tests point at an isolated registry
        explicit = path or os.environ.get("OPENFACTORY_REGISTRY")
        # the default is the OPERATOR's home file, resolved in one place (`namespace.operator_path`)
        # so the registry, the approver store and the resume handles share a home; an explicit
        # path (argument, env) is never second-guessed
        from openfactory import namespace as _ns
        self.path = Path(explicit) if explicit else _ns.operator_path("registry.yaml")

    # ── plumbing ────────────────────────────────────────────────────────────────────────────────

    @contextmanager
    def _locked(self):
        """Serialise read-modify-write across processes.

        The panel and the CLI can both register a project, and an unlocked read-modify-write drops
        one of two concurrent adds — silently, leaving a board nobody polls. The lock is on a
        sibling file rather than the registry itself, because the registry is REPLACED on write
        (see `_save_raw`) and a lock held on a replaced inode protects nothing.
        """
        self.path.parent.mkdir(parents=True, exist_ok=True)
        lock = self.path.with_suffix(self.path.suffix + ".lock")
        with open(lock, "w") as fh:
            fcntl.flock(fh, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(fh, fcntl.LOCK_UN)

    def _load_raw(self) -> dict[str, dict]:
        if not self.path.exists():
            return {}
        try:
            data = yaml.safe_load(self.path.read_text()) or {}
        except yaml.YAMLError as exc:
            raise ValueError(f"{self.path} is not valid YAML: {exc}") from exc
        if not isinstance(data, dict):
            raise ValueError(f"{self.path} must be a YAML mapping, not {type(data).__name__}")
        return data.get("projects", {}) or {}

    def _normalised(self, name: str, raw: dict) -> dict:
        """Rewrite one entry under the current field names, keeping anything unrecognised.

        This is what makes the C-08 rename drain away instead of needing a flag day: every write
        migrates every entry, so a registry nobody can see converges on its own.

        UNKNOWN KEYS ARE PRESERVED. `extra="ignore"` means the model would silently drop them, and
        a write that deleted a key somebody deliberately added is a worse failure than the stale
        name it was fixing. An entry that will not parse at all is left verbatim: an unrelated
        `add` must not be the thing that rewrites a broken neighbour.
        """
        try:
            dumped = Project(**raw).model_dump(mode="json")
        except Exception as exc:  # noqa: BLE001 — leave what we cannot read
            log.warning("registry: project %r could not be normalised (%s) — left verbatim, so "
                        "its old field names will not migrate until it parses", name, exc)
            return raw
        unknown = {k: v for k, v in raw.items()
                   if k not in Project.model_fields and k not in self._RENAMED}
        return {**dumped, **unknown}

    def _save_raw(self, projects: dict[str, dict]) -> None:
        """Write atomically: a temp file in the same directory, then `os.replace`.

        `write_text` truncates before it writes, so a crash, a full disk or a SIGTERM in between
        leaves an EMPTY registry — the project-less worker, without anyone rebuilding anything.
        `os.replace` is atomic on the same filesystem: readers see either the old file or the new
        one, never a half-written one.
        """
        projects = {k: self._normalised(k, v) for k, v in projects.items()}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=self.path.parent, prefix=".registry-", suffix=".tmp")
        try:
            with os.fdopen(fd, "w") as fh:
                yaml.safe_dump({"projects": projects}, fh, sort_keys=True)
                fh.flush()
                os.fsync(fh.fileno())  # the bytes are on disk before anything points at them
            os.replace(tmp, self.path)
        except BaseException:
            Path(tmp).unlink(missing_ok=True)  # never leave debris beside the registry
            raise

    # ── reads ───────────────────────────────────────────────────────────────────────────────────

    #: Keys renamed in C-08. Still accepted (see `Project`'s `AliasChoices`) and reported by name,
    #: because `deploy/registry.yaml` is gitignored and baked into the worker image — a migration
    #: requiring an edit nobody can be shown is how a deployment goes mute.
    _RENAMED = {
        "slack_channel": "channel_id",
        "slack_admins": "admins",
        "slack_bot_token_env": "channel_options.bot_token_env",
        "slack_app_token_env": "channel_options.app_token_env",
    }

    def _report_keys(self, name: str, raw: dict) -> None:
        """Name every key that will not do what its author expects.

        `extra="ignore"` is kept deliberately: making an unknown key fatal would turn one stale
        line into an outage the operator could not have reviewed, since the file is invisible to
        every test and reviewer. But silence is worse than either — a typo'd `slack_chanel` is
        dropped, the project goes quiet, and the first report comes from the client.
        """
        known = set(Project.model_fields) | {"slack_channel", "slack_admins",
                                             "slack_bot_token_env", "slack_app_token_env"}
        for key in raw:
            if key in self._RENAMED:
                log.info("registry: project %r still uses %r — renamed to %r (still accepted; "
                         "it migrates on the next write)", name, key, self._RENAMED[key])
            elif key not in known:
                log.warning("registry: project %r has an unknown key %r — it is IGNORED, so "
                            "whatever it was meant to configure is not configured", name, key)
        # NESTED BLOCKS TOO. `box:` is the first sub-model an operator hand-edits, and a typo there
        # is worth exactly as much noise as one at the top level: a dropped `network:` means the
        # egress restriction somebody believed they configured is not configured, and the first
        # report of that comes from an incident.
        box = raw.get("box")
        if isinstance(box, dict):
            for key in set(box) - set(BoxConfig.model_fields):
                log.warning("registry: project %r has an unknown key %r under `box:` — it is "
                            "IGNORED, so whatever it was meant to configure is not configured",
                            name, key)
        # AND THE PER-ROLE SHAPES OF `harness:` / `model:`. `Project` types them `dict[str, str]`
        # with no key validation, `_configured` reads only the keys it is asked for, and the CLI
        # never writes a per-role `harness:` at all — so hand-editing the file is the ONLY path to
        # `harness: {reviewr: codex}`, and it was the one path with neither a refusal nor a line.
        # Measured 2026-08-24: `model: {executr: <a client's own endpoint>}` loaded clean and ran
        # the executor on the deployment's default provider. A WARNING and never a raise: `list()`
        # below turns one invalid entry into every project failing to load, which is the outage
        # the `extra="ignore"` docstring above exists to prevent. The key set is `known_roles()`,
        # so a role installed as an add-on is a legitimate key here the day it is installed.
        from openfactory.adapters.agent.registry import FALLBACK_KEY, known_roles

        for field in ("harness", "model"):
            per_role = raw.get(field)
            if isinstance(per_role, dict):
                for key in sorted(set(per_role) - {*known_roles(), FALLBACK_KEY}):
                    log.warning("registry: project %r has an unknown role %r under `%s:` — it "
                                "is IGNORED, so the %s that role was meant to run on is not "
                                "configured (roles: %s, plus `%s`)", name, key, field,
                                field, ", ".join(known_roles()), FALLBACK_KEY)

    def list(self) -> list[Project]:
        out: list[Project] = []
        for key, raw in self._load_raw().items():
            self._report_keys(key, raw)
            try:
                out.append(Project(**raw))
            except ValidationError as exc:
                # One malformed entry stops ALL projects, because every caller builds the whole
                # list and none of them catch. That is arguably the right failure — but a bare
                # pydantic traceback does not tell the operator which line to open.
                raise ValueError(f"{self.path}: project {key!r} is invalid: {exc}") from exc
        self._warn_if_spanning(out)
        return out

    def _warn_if_spanning(self, projects: list[Project]) -> None:
        """Say it loudly on every load — but do NOT raise (#64).

        WHY THIS WARNS WHERE `add` REFUSES, which is a deliberate split. `add` has a human in
        front of it: the mistake is being made right now, and refusing costs them one message.
        `list` runs on the poller's every tick, inside a worker, against a file that
        `_report_keys` two methods up already describes as "invisible to every test and reviewer"
        because it is gitignored and baked into an image. Raising here would turn ONE stale line
        in an unreviewable file into a total outage for EVERY project — including the ones that
        are perfectly fine — and the failure would arrive as a retried activity error in a log
        nobody is watching. That is a silent stall, the one thing this platform promises not to
        produce, and it is strictly worse than the 404s it would be protecting against.

        The same argument is already written down one method up for `extra="ignore"`. This obeys
        it rather than contradicting it.

        The positive, network-side twin is `doctor`'s `installation_scope` check, which asks the
        App which org it is ACTUALLY installed on and compares — the one place that can tell a
        spanning registry from a correct one without guessing.
        """
        by_owner = spanning_installations(projects)
        if by_owner:
            log.error("OPENFACTORY_REGISTRY_SPANS_INSTALLATIONS: %s", _spanning_message(by_owner))

    def get(self, name: str) -> Project:
        raw = self._load_raw()
        if name not in raw:
            raise KeyError(f"project not registered: {name!r}")
        try:
            return Project(**raw[name])
        except ValidationError as exc:
            raise ValueError(f"{self.path}: project {name!r} is invalid: {exc}") from exc

    # ── writes ──────────────────────────────────────────────────────────────────────────────────

    def add(self, project: Project) -> None:
        with self._locked():
            raw = self._load_raw()
            if project.name in raw:
                raise ValueError(f"project already registered: {project.name!r}")
            # REFUSED HERE BECAUSE HERE IS WHERE THE MISTAKE IS MADE (#64). A human is in front of
            # this — `openfactory project add` or the panel's POST /api/projects, which already
            # renders a
            # ValueError as a 409 carrying the message — so the cost of refusing is one sentence
            # at the moment it can still be acted on, rather than a 404 on a repo they can see in
            # their browser, three layers away, minutes later.
            #
            # ASKED OF THE WHOLE REGISTRY AS IT WOULD BE, through the SAME function `list` warns
            # with — one rule, one implementation. An earlier version compared the incoming
            # project's orgs against the incumbents' and missed the case a test caught: a SINGLE
            # project whose repo is in one org and whose board is in another spans two
            # installations by itself, and no between-project comparison can see that.
            would_be = [Project(**other) for other in raw.values()] + [project]
            spanning = spanning_installations(would_be)
            if spanning:
                raise ValueError(_spanning_message(spanning))
            raw[project.name] = project.model_dump(mode="json")
            self._save_raw(raw)
            self._warn_foreign_pointers(project)

    def _warn_foreign_pointers(self, project: Project) -> None:
        """The two pointers that may legitimately live in another org — warned, never refused.

        `factory_board` is ADR-0027: the factory files its OWN impediments on its OWN board, and
        the shipped `deploy/registry.yaml.example` points it at a fork of this platform. A fork
        operator aiming it at the upstream repo is doing the natural thing. `product.docs_repo` is
        the same shape — a client's requirements repository may live anywhere.

        Refusing either would break a documented design to enforce an undocumented one. But both
        DO need the same installation to read them, and both fail today by degrading quietly (a
        logged impediment that reaches nobody), so the warning is worth its noise."""
        mine = github_owners(project)
        if not mine:
            return
        board = getattr(getattr(project, "factory_board", None), "tracker", None)
        docs = getattr(getattr(project, "product", None), "docs_repo", None)
        for label, repo in (("factory_board", getattr(board, "repo", None)),
                            ("product.docs_repo", docs)):
            owner = (repo or "").split("/", 1)[0].strip()
            if owner and owner not in mine:
                log.warning(
                    "registry: project %r points %s at %r, in a different GitHub organisation "
                    "(%s) from its own (%s). One process holds ONE App installation, so that "
                    "pointer reads only if the App is installed on BOTH orgs — otherwise it "
                    "degrades quietly and reaches nobody.",
                    project.name, label, repo, owner, ", ".join(sorted(mine)))

    def remove(self, name: str) -> None:
        with self._locked():
            raw = self._load_raw()
            raw.pop(name, None)
            self._save_raw(raw)

    def attach_board(self, name: str, *, board_owner: str, board_number: str) -> None:
        """Point a registered project's tracker at a board — `init`'s converge step (C-16).

        Written under the same lock as every other mutation. Layered onto the existing options
        rather than replacing them: a project that already mapped its column names (C-14) must
        not lose the mapping to the act that attaches the board."""
        with self._locked():
            raw = self._load_raw()
            if name not in raw:
                raise KeyError(name)
            tracker = raw[name].setdefault("tracker", {}) or {}
            options = tracker.setdefault("options", {}) or {}
            options.update({"board_owner": board_owner, "board_number": str(board_number)})
            tracker["options"] = options
            raw[name]["tracker"] = tracker
            self._save_raw(raw)

    def set_model(self, name: str, model: str, *, role: str | None = None) -> None:
        """Which model the harness runs for this project — the CLI's way in (funnel review 2).

        The `model:` field has existed since 2026-08-05 in two shapes (one string for every
        role, or per role), and the ONLY way to set it was editing the registry YAML inside the
        worker — for the compose deployment, `docker compose exec worker vi`, which is exactly
        the by-hand step the pilot operator asked where to find and could not. Same lock, same
        layering rule as `attach_board`.

        A single string and a per-role dict do not merge: narrowing `model: x` with
        `--role executor y` would either drop x for every other role or invent an expansion this
        method cannot know is wanted. That case REFUSES with both forms named."""
        if role:
            from openfactory.adapters.agent.registry import known_roles

            known = known_roles()
            if role not in known:
                # a typo here writes a dict key NOTHING ever reads — a model that looks
                # configured and is not, this codebase's signature defect (caught by the
                # measurement pass before it shipped, 2026-08-10). `known_roles()` rather than
                # the shipped table, so a role installed as an add-on is one this command can
                # configure — and the refusal names it, or a stranger reads "not a role" about
                # the row they just installed
                raise ValueError(
                    f"{role!r} is not a role — one of: {', '.join(known)}")
        with self._locked():
            raw = self._load_raw()
            if name not in raw:
                raise KeyError(name)
            if role:
                current = raw[name].get("model")
                if isinstance(current, str) and current:
                    raise ValueError(
                        f"{name} sets model: {current!r} for EVERY role; a per-role value would "
                        f"silently drop it for the others. Set the whole shape explicitly — "
                        f"either `set-model {name} <model>` (every role) or one "
                        f"`set-model {name} <model> --role <r>` per role after clearing it")
                merged = dict(current) if isinstance(current, dict) else {}
                merged[role] = model
                raw[name]["model"] = merged
            else:
                raw[name]["model"] = model
            self._save_raw(raw)

    def set_docs_repo(self, name: str, docs_repo: str) -> None:
        """Record which repository holds this project's requirements.

        WITHOUT THIS THE CREATION IS THEATRE (#99 slice 2b). `product init --create-context` makes
        the repository in the client's organisation, and the product module stays OFF until the
        registry names it — `ProductConfig.docs_repo` is required, and its own contract says a
        module with nowhere to write requirements *"is not a configuration, it is a mistake"*. So
        an onboarding that created the repository and did not write it down would leave the client
        with a new empty repository and a product role that still refuses to speak.

        The whole `product:` block is created when absent, because a project registered before
        this feature existed has none — and demanding an operator hand-edit YAML first is exactly
        the "four files by hand" this slice exists to remove.
        """
        with self._locked():
            raw = self._load_raw()
            if name not in raw:
                raise KeyError(name)
            product = dict(raw[name].get("product") or {})
            product["docs_repo"] = docs_repo
            raw[name]["product"] = product
            self._save_raw(raw)

    def set_language(self, name: str, language: str) -> None:
        """Which language this project's UNPROMPTED messages are written in (#124).

        THE FIELD HAS EXISTED SINCE THE PRODUCT ROLE AND HAD NO WAY IN. `--language` is offered by
        `project add` and `project init` — at registration, once — and after that the only way to
        change it was editing the registry YAML *inside the worker image* and rebuilding, which is
        the same "edit a file by hand" that `set_model` and `set_docs_repo` exist to remove. An
        operator who onboarded in Portuguese and later wants English had no command at all.

        NOT VALIDATED AGAINST A LIST, deliberately, and for the reason `set_model` gives about
        model strings: the phrasebooks carry `en` and `pt-BR` today and fall back to English for
        anything they have not been translated for (`product/voice.py::_pick`), while the AGENTS
        take the value verbatim as an instruction — so a language nobody has written a catalogue
        for still produces sensible agent output and understandable canned text. Refusing it here
        would block the only half that already works.
        """
        wanted = str(language or "").strip()
        if not wanted:
            raise ValueError("a language with no name in it is not a setting — pass one, e.g. "
                             "`en` or `pt-BR`")
        with self._locked():
            raw = self._load_raw()
            if name not in raw:
                raise KeyError(name)
            raw[name]["language"] = wanted
            self._save_raw(raw)

    def set_enabled(self, name: str, enabled: bool) -> None:
        """Turn the framework on/off for a project's board — so it only starts picking up TODO
        tickets once the board has been prioritized."""
        with self._locked():
            raw = self._load_raw()
            if name not in raw:
                raise KeyError(name)
            raw[name]["enabled"] = enabled
            self._save_raw(raw)


def seed_registry(*, seed: Path | str | None = None, live: Path | str | None = None) -> bool:
    """Populate the live registry from the image's seed, once. Returns whether it did.

    Called at worker start. Two properties, and both halves are silent when wrong:

        it seeds an EMPTY live registry     a freshly mounted volume is an empty file, not a
                                            decision; treating "the file exists" as "somebody
                                            configured this" leaves that deployment project-less
        it NEVER overwrites real projects   otherwise every deploy reverts every project added at
                                            runtime, and the operator finds out when a board stops
                                            being polled

    Never raises. A worker that will not boot because a seed file is malformed has turned a
    configuration mistake into an outage; it starts project-less and says so.
    """
    seed_path = Path(seed or os.environ.get("OPENFACTORY_REGISTRY_SEED") or SEED_REGISTRY_PATH)
    live_path = Path(live or os.environ.get("OPENFACTORY_REGISTRY") or LIVE_REGISTRY_PATH)
    try:
        if not seed_path.exists():
            return False
        existing = ProjectRegistry(live_path)._load_raw()
        if existing:
            return False
        projects = (yaml.safe_load(seed_path.read_text()) or {}).get("projects") or {}
        if not projects:
            return False
        ProjectRegistry(live_path)._save_raw(projects)
        log.info("seeded %s from %s with %d project(s): %s", live_path, seed_path,
                 len(projects), ", ".join(sorted(projects)))
        return True
    except Exception as exc:  # noqa: BLE001 — a bad seed must not stop the worker booting
        log.warning("could not seed the registry from %s (%s) — starting with whatever %s holds",
                    seed_path, exc, live_path)
        return False
