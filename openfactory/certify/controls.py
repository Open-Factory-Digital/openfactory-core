"""What a deployment pack checks, which profile requires it, and what each control answers (#356).

EVERY ANSWER IS READ, NEVER ASSUMED. A control is computed from what the deployment says about
itself — its environment, its files, its registry, its manifests, its proofs, its doctor — and
nothing else. Where the fact a control is about could not be read, the control says `unknown`
and why, and `unknown` is never a pass. Three controls read the FORGE (#356, slice 3): the
branch's protection (C-BRANCH), what the credential is granted (C-WORKFLOWS) and the platform's
published releases (C-VERSION), each through an optional capability of the project's forge row
(`adapters/forge/base.py`) whose `None` — no such capability, a credential without the scope to
ask, no network — is `unknown` here. A certificate that inferred them would certify something
nobody looked at.

THE PROFILE TABLE IS IN ONE PLACE (`PROFILES`). The partners page states the security controls and
the thresholds every pack must meet; it does not publish a per-profile column. So the table below
is DERIVED from it and says so: the security row (panel not open, secrets file 0600, a credential
without `workflows`, `box.env` as an allow list) and the two thresholds that apply to every pack
(box proofs current, platform version current) are required on every profile; `standard` and
`enterprise` require every control. A profile that is not required reads `n/a`, with the reason.

THE PURE HALF. `evaluate` takes a `Reading` — what `pack.gather` read off the deployment — and
returns one `Control` per entry in `CONTROLS`. Nothing here touches the machine, so every branch is
reachable in a test with no registry, no Docker and no network, the reason `doctor.Probes` exists.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field

from openfactory.adapters.forge.base import BranchProtection

PASS, FAIL, NA, UNKNOWN, INFO = "pass", "fail", "n/a", "unknown", "info"

#: What a control may answer. `info` is C-CONCURRENCY's above 1 — recorded, never a failure.
RESULTS = (PASS, FAIL, NA, UNKNOWN, INFO)

#: Where a control's evidence is read.
SOURCES = ("environment", "filesystem", "registry", "manifests", "policy", "proofs", "doctor",
           "forge", "releases")


@dataclass(frozen=True)
class Spec:
    id: str
    title: str
    source: str


#: Every control a deployment pack carries, in the order the issue lists them.
CONTROLS: tuple[Spec, ...] = (
    Spec("C-PANEL", "the panel is not open: a sign-in token is set, or the identity is OIDC",
         "environment"),
    Spec("C-ENVFILE", "the deployment's env file exists, is mode 0600 and is not tracked by git",
         "filesystem"),
    Spec("C-FORGE-CRED", "the forge credential is minted per use, or the vendor's own where it "
                         "mints none — never the deployment's generic token or a person's login",
         "environment"),
    Spec("C-WORKFLOWS", "the forge credential cannot write workflows", "forge"),
    Spec("C-BOX-ENV", "every project declares box.env as an explicit allow list, and jobs run in "
                      "the container box", "registry"),
    Spec("C-TEST", "every repository declares a test gate", "manifests"),
    Spec("C-SECURITY", "every repository has a security gate, declared or inherited", "manifests"),
    Spec("C-MERGE", "merge_policy and review_mode are recorded for every repository", "manifests"),
    Spec("C-RISK", "where components are declared, at least one declares risk: high",
         "manifests"),
    Spec("C-PROTECT", "the floor's protected paths include .openfactory/**", "policy"),
    Spec("C-BRANCH", "the default branch is protected", "forge"),
    Spec("C-CONCURRENCY", "OPENFACTORY_MAX_CONCURRENT_JOBS is recorded: 1 passes, more is "
                          "information", "environment"),
    Spec("C-RETENTION", "the engine keeps at least 30 days of history", "environment"),
    Spec("C-POSTMERGE", "what happens after a merge is declared, and the doctor's post_merge line "
                        "is green", "manifests"),
    Spec("C-APPROVERS", "a promotion chain that gates production has approvers who can sign",
         "manifests"),
    Spec("C-PROOF", "every repository's box proof is current", "proofs"),
    Spec("C-VERSION", "the running version is the latest release or the one before", "releases"),
    Spec("C-DOCTOR", "the doctor is green on every project", "doctor"),
)

CONTROL_IDS = tuple(c.id for c in CONTROLS)

# ── THE PROFILE TABLE, in one place ─────────────────────────────────────────────────────────────

#: The partners page's "Security controls" threshold, control by control: panel not open; secrets
#: file mode 0600; forge credential without `workflows`; `box.env` is an explicit allow list.
SECURITY_CONTROLS = ("C-PANEL", "C-ENVFILE", "C-WORKFLOWS", "C-BOX-ENV")

#: The thresholds the page sets for EVERY pack, whatever profile it claims: box proofs current for
#: every repository, and the platform version the current release or the one before it.
EVERY_PACK = ("C-PROOF", "C-VERSION")

#: Which controls each profile requires. DERIVED from the partners page, which publishes the
#: security controls and the per-pack thresholds but no per-profile column: `light` requires those;
#: `standard` and `enterprise` require every control. Changing a profile is an edit here, and only
#: here — `summary.md`, `pack.json` and the schema's enum all read this table.
PROFILES: dict[str, frozenset[str]] = {
    "light": frozenset(SECURITY_CONTROLS + EVERY_PACK),
    "standard": frozenset(CONTROL_IDS),
    "enterprise": frozenset(CONTROL_IDS),
}

#: The engine history the partners page asks a deployment to keep.
RETENTION_FLOOR_DAYS = 30

#: Where the pack keeps each diagnostic — one name, read by the controls that point at a file and
#: by the assembly that writes it.
PREFLIGHT_FILE = "diagnostics/preflight.json"


def doctor_file(project: str) -> str:
    return f"diagnostics/doctor-{project}.json"


def box_file(repository: str) -> str:
    return f"diagnostics/box-status-{repository}.txt"


# ── what `pack.gather` read ─────────────────────────────────────────────────────────────────────

@dataclass
class RepositoryReading:
    """One (project, repository): its manifest and its box proof, as the platform reads them."""

    project: str
    #: Who this repository IS, for its pseudonym: the forge coordinate, or `<project>#default`
    #: for a project that names none.
    identity: str
    default: bool
    #: Where its proof is recorded (`card_repo._checkout_key`) — a name its text report prints.
    key: str
    manifest: object | None = None
    manifest_error: str = ""
    #: `box_prove.BoxStatus.as_document()` and its text lines, or why they could not be read.
    box: dict | None = None
    box_lines: list[str] = field(default_factory=list)
    box_error: str = ""
    #: What protects the branch the platform merges into (the manifest's `base_branch`), as the
    #: forge row read it — None when it could not be read, or the branch is not known.
    protection: BranchProtection | None = None


@dataclass
class ProjectReading:
    name: str
    #: What the forge credential a job holds IS — never its value — as the platform resolves it
    #: (`credentials.forge_credential_source`): `minted` (the deployment mints it per use),
    #: `identity` (the machine's own), `stored` (a secret in a variable), `generic` (the
    #: deployment's generic token), `login` (a person's CLI login), `none`, or `unread`.
    forge_credential: str
    #: Whether the forge's vendor offers a credential this deployment can MINT — its credential
    #: row's `mint`. Where it does, a stored token is the weaker choice; where it does not, the
    #: vendor's own stored secret is the documented one.
    forge_mints: bool
    #: Whether the registry declares `box.env` — the allow list — at all, and how many names.
    box_env_declared: bool
    box_env_names: int
    repositories: list[RepositoryReading] = field(default_factory=list)
    doctor: dict | None = None
    doctor_error: str = ""
    #: What that credential is GRANTED, in the vendor's own words, as the forge row read it — None
    #: when it could not be (`forge/base.py::credential_permissions_of`).
    permissions: frozenset[str] | None = None
    #: The grants the row says reach the CI definitions (`ci_write_permissions_of`) — empty when
    #: the row cannot say, which is never read as "none of them does".
    ci_permissions: frozenset[str] = frozenset()


@dataclass
class EnvFileReading:
    """The deployment's secrets file, as seen from where certify ran. `name` is `""` when none is
    visible here — inside the worker the host's `.env.compose` is not on disk."""

    name: str
    exists: bool
    mode: int | None = None
    #: True/False, or None when git could not be asked.
    tracked: bool | None = None


@dataclass
class Reading:
    version: str
    build: tuple[str, str]
    #: The environment certify reads (the process's, over the env file's rows) — values are read
    #: for the few non-secret settings below and for PRESENCE only everywhere else.
    env: dict[str, str]
    env_file: EnvFileReading
    sandbox: str
    identity: str
    providers: dict[str, list[str]]
    projects: list[ProjectReading]
    #: `protected.floor_protected_paths()` — None when the floor cannot be read.
    floor_protected: tuple[str, ...] | None
    #: The approver store's logins — None when the store cannot be read.
    approvers: list[str] | None
    preflight: dict | None = None
    preflight_error: str = ""
    #: The platform's published releases (tags), read through a forge row — None when no row this
    #: deployment uses could list them, or the network did not answer.
    releases: list[str] | None = None
    #: What the redactor must hide, collected while reading: `{category: {identity: aliases}}`
    #: (`redact.Redactor`), the values of every credential-shaped variable, and the NAMES of the
    #: variables the registry declares that are not the platform's own — `ACME_ADO_PAT` names its
    #: customer. No control reads any of them; they travel here so the pack is scrubbed with what
    #: was actually read.
    identifiers: dict[str, dict[str, set[str]]] = field(default_factory=dict)
    secrets: set[str] = field(default_factory=set)
    variables: set[str] = field(default_factory=set)


# ── the answers ─────────────────────────────────────────────────────────────────────────────────

@dataclass
class Control:
    id: str
    title: str
    required: bool
    result: str
    source: str
    detail: str
    pointers: list[str] = field(default_factory=list)

    def as_entry(self) -> dict:
        return {"id": self.id, "title": self.title, "required": self.required,
                "result": self.result,
                "evidence": {"source": self.source, "detail": self.detail,
                             "pointers": list(self.pointers)}}


class Pseudonyms:
    """How a control names a project or a repository in its evidence: by pseudonym, always."""

    def project(self, name: str) -> str:  # pragma: no cover — the redactor implements it
        raise NotImplementedError

    def repository(self, identity: str) -> str:  # pragma: no cover
        raise NotImplementedError


def combined(results: Iterable[str]) -> str:
    """Many answers as one: any failure fails, then any unknown is unknown — NEVER a pass over
    something unread — then any pass passes; nothing at all is `n/a`."""
    seen = list(results)
    for result in (FAIL, UNKNOWN, PASS, INFO):
        if result in seen:
            return result
    return NA


def evaluate(reading: Reading, profile: str, names: Pseudonyms) -> list[Control]:
    """One `Control` per entry in `CONTROLS`, for the claimed profile."""
    required = PROFILES[profile]
    out: list[Control] = []
    for spec in CONTROLS:
        if spec.id not in required:
            out.append(Control(spec.id, spec.title, False, NA, spec.source,
                               f"not required by the {profile} profile"))
            continue
        result, detail, pointers = _READERS[spec.id](reading, names)
        out.append(Control(spec.id, spec.title, True, result, spec.source, detail, pointers))
    return out


Answer = tuple[str, str, list[str]]


def _panel(r: Reading, _n: Pseudonyms) -> Answer:
    identity = (r.env.get("OPENFACTORY_IDENTITY") or "").strip().lower()
    if identity == "oidc":
        return PASS, "OPENFACTORY_IDENTITY=oidc — people sign in through the provider", []
    for name in ("OPENFACTORY_PANEL_TOKENS", "OPENFACTORY_PANEL_TOKEN"):
        if (r.env.get(name) or "").strip():
            return PASS, f"{name} is set — the panel asks for a sign-in", []
    return FAIL, ("neither OPENFACTORY_PANEL_TOKENS nor OPENFACTORY_PANEL_TOKEN is set and the "
                  "identity is not OIDC — the panel answers anybody who can reach it"), []


def _envfile(r: Reading, _n: Pseudonyms) -> Answer:
    f = r.env_file
    if not f.name or not f.exists:
        return UNKNOWN, ("no .env.compose is visible where certify ran, and no one-machine env "
                         "file (~/.openfactory/env) — run it where the deployment's secrets file "
                         "is (beside docker-compose.yml)"), []
    problems = []
    if f.mode is None or f.mode & 0o077:
        problems.append(f"it is mode {f.mode:04o}" if f.mode is not None
                        else "its mode could not be read")
    if f.tracked:
        problems.append("it is tracked by git")
    if problems:
        return FAIL, f"{f.name}: " + " and ".join(problems), [f"filesystem:{f.name}"]
    if f.tracked is None:
        return UNKNOWN, (f"{f.name} is mode {f.mode:04o}, and git could not be asked whether it "
                         f"is tracked"), [f"filesystem:{f.name}"]
    return PASS, f"{f.name} is mode {f.mode:04o} and not tracked by git", [f"filesystem:{f.name}"]


#: What each credential source answers, in words that name no vendor: the rule is the same for
#: every forge, and the vendor's own row says whether it mints (`ProjectReading.forge_mints`).
_CREDENTIALS = {
    "minted": (PASS, "a credential this deployment mints per use"),
    "identity": (PASS, "the machine's own identity — nothing stored"),
    "generic": (FAIL, "the deployment's generic token (OPENFACTORY_BOT_TOKEN or "
                      "OPENFACTORY_FORGE_TOKEN)"),
    "login": (FAIL, "a person's CLI login on this machine"),
    "none": (FAIL, "no forge credential resolves"),
}


def _forge_cred(r: Reading, n: Pseudonyms) -> Answer:
    if not r.projects:
        return UNKNOWN, "no project is registered here, so no forge credential is in use", []
    said, results = [], []
    for p in r.projects:
        who = n.project(p.name)
        if p.forge_credential == "stored":
            result, what = ((FAIL, "a stored token, where the vendor offers a minted credential")
                            if p.forge_mints else
                            (PASS, "the vendor's own stored credential — it offers nothing to "
                                   "mint"))
        else:
            result, what = _CREDENTIALS.get(
                p.forge_credential, (UNKNOWN, "the credential's source could not be read"))
        results.append(result)
        said.append(f"{who}: {what}")
    return combined(results), "; ".join(said), []


def _box_env(r: Reading, n: Pseudonyms) -> Answer:
    if not r.projects:
        return UNKNOWN, "no project is registered here", []
    lacking = [n.project(p.name) for p in r.projects if not p.box_env_declared]
    declared = len(r.projects) - len(lacking)
    said = [f"box.env is declared on {declared} of {len(r.projects)} project(s)"
            + (f" (not on {', '.join(lacking)})" if lacking else "")]
    container = r.sandbox == "container"
    said.append(f"jobs run in the `{r.sandbox}` box"
                + ("" if container else " — the allow list is the container box's; this box "
                                        "scrubs by deny list instead"))
    return (PASS if not lacking and container else FAIL), "; ".join(said), []


def _per_repository(r: Reading, n: Pseudonyms,
                    judge: Callable[[object], tuple[str, str]]) -> Answer:
    """Judge every repository's manifest; an unread manifest is `unknown`, never a pass."""
    if not any(p.repositories for p in r.projects):
        return UNKNOWN, "no repository is registered here", []
    results, said = [], []
    for p in r.projects:
        for repo in p.repositories:
            who = n.repository(repo.identity)
            if repo.manifest is None:
                results.append(UNKNOWN)
                said.append(f"{who}: the manifest could not be read")
                continue
            result, words = judge(repo.manifest)
            results.append(result)
            said.append(f"{who}: {words}")
    return combined(results), "; ".join(said), []


def _roles(manifest) -> set[str]:
    from openfactory.policy.conformance import _effective_validation

    return _effective_validation(manifest)


def _test(r: Reading, n: Pseudonyms) -> Answer:
    def judge(m):
        return (PASS, "declares `test`") if "test" in _roles(m) else \
            (FAIL, "declares no `test` gate")
    return _per_repository(r, n, judge)


def _security(r: Reading, n: Pseudonyms) -> Answer:
    from openfactory.policy.conformance import inherited_floor_roles

    def judge(m):
        if "security" not in _roles(m):
            return FAIL, "has no `security` gate"
        how = "inherited from the deployment's floor" if "security" in \
            inherited_floor_roles(m) else "declared"
        return PASS, f"`security` gate {how}"
    return _per_repository(r, n, judge)


def _merge(r: Reading, n: Pseudonyms) -> Answer:
    def judge(m):
        return PASS, (f"merge_policy={getattr(m, 'merge_policy', '?')}, "
                      f"review_mode={getattr(m, 'review_mode', '?')}")
    return _per_repository(r, n, judge)


def _risk(r: Reading, n: Pseudonyms) -> Answer:
    def judge(m):
        components = getattr(m, "components", {}) or {}
        if not components:
            return NA, "declares no components"
        high = [c for c in components.values()
                if str(getattr(getattr(c, "risk", ""), "value", getattr(c, "risk", ""))) == "high"]
        if high:
            return PASS, f"{len(high)} of {len(components)} component(s) declare risk: high"
        return FAIL, f"{len(components)} component(s), none declares risk: high"
    return _per_repository(r, n, judge)


def _protect(r: Reading, _n: Pseudonyms) -> Answer:
    from openfactory import namespace

    wanted = f"{namespace.DIR}/**"
    if r.floor_protected is None:
        return FAIL, ("the deployment's floor (org_defaults/floor.yaml) cannot be read, so no "
                      "path is protected"), ["policy:protected_paths"]
    if wanted in r.floor_protected:
        return PASS, f"the floor protects {wanted}", ["policy:protected_paths"]
    return FAIL, f"the floor's protected paths do not include {wanted}", ["policy:protected_paths"]


def _concurrency(r: Reading, _n: Pseudonyms) -> Answer:
    raw = (r.env.get("OPENFACTORY_MAX_CONCURRENT_JOBS") or "").strip()
    try:
        value = max(0, int(raw)) if raw else 1
    except ValueError:
        value = 1
    said = (f"OPENFACTORY_MAX_CONCURRENT_JOBS={raw}" if raw else
            "OPENFACTORY_MAX_CONCURRENT_JOBS is not set — the default is 1")
    if raw and str(value) != raw:
        said += f", read as {value}"
    if value == 1:
        return PASS, said + ": one job at a time", ["environment:OPENFACTORY_MAX_CONCURRENT_JOBS"]
    what = "pickup is paused" if value == 0 else f"{value} jobs may run at once"
    return INFO, f"{said}: {what}", ["environment:OPENFACTORY_MAX_CONCURRENT_JOBS"]


def _retention(r: Reading, _n: Pseudonyms) -> Answer:
    raw = (r.env.get("OPENFACTORY_ENGINE_RETENTION_DAYS") or "").strip()
    pointer = ["environment:OPENFACTORY_ENGINE_RETENTION_DAYS"]
    try:
        days = int(raw) if raw else RETENTION_FLOOR_DAYS
    except ValueError:
        return UNKNOWN, f"OPENFACTORY_ENGINE_RETENTION_DAYS={raw!r} is not a number of days", \
            pointer
    said = (f"the deployment declares {days} days" if raw else
            f"nothing is declared, so the platform's default of {days} days applies")
    said += " (the declaration `ensure_retention` raises the engine to; the engine is not asked)"
    return (PASS if days >= RETENTION_FLOOR_DAYS else FAIL), said, pointer


def _check_of(doc: dict | None, check: str) -> str | None:
    """A doctor document's result for one check, or None when it is not there."""
    for c in (doc or {}).get("checks") or []:
        if c.get("id") == check:
            return c.get("result")
    return None


def _postmerge(r: Reading, n: Pseudonyms) -> Answer:
    if not any(p.repositories for p in r.projects):
        return UNKNOWN, "no repository is registered here", []
    results, said, pointers = [], [], []
    for p in r.projects:
        for repo in p.repositories:
            who = n.repository(repo.identity)
            m = repo.manifest
            if m is None:
                results.append(UNKNOWN)
                said.append(f"{who}: the manifest could not be read")
                continue
            declared = getattr(m, "post_merge_deploy", None) is not None or \
                bool(getattr(m, "environments", None))
            if not declared:
                results.append(FAIL)
                said.append(f"{who}: declares neither post_merge_deploy nor environments")
                continue
            if not repo.default:
                results.append(PASS)
                said.append(f"{who}: declared (the doctor reads the default repository only)")
                continue
            line = _check_of(p.doctor, "post_merge")
            pointers.append(doctor_file(n.project(p.name)) + "#post_merge")
            if line is None:
                results.append(UNKNOWN)
                said.append(f"{who}: declared, and the doctor's post_merge line could not be read")
            else:
                results.append(PASS if line == "ok" else FAIL)
                said.append(f"{who}: declared, and the doctor's post_merge line is {line}")
    return combined(results), "; ".join(said), pointers


def _approvers(r: Reading, n: Pseudonyms) -> Answer:
    results, said = [], []
    for p in r.projects:
        for repo in p.repositories:
            m = repo.manifest
            who = n.repository(repo.identity)
            if m is None:
                results.append(UNKNOWN)
                said.append(f"{who}: the manifest could not be read")
                continue
            gated = bool(getattr(m, "promote", None)) or "prod" in (getattr(m, "environments",
                                                                            None) or {})
            if not gated:
                continue
            named = list(getattr(m, "prod_approvers", None) or [])
            if not named:
                results.append(FAIL)
                said.append(f"{who}: a chain gates production and names no approver")
            elif r.approvers is None:
                results.append(UNKNOWN)
                said.append(f"{who}: {len(named)} approver(s) named; the approver store could "
                            f"not be read")
            else:
                able = [a for a in named if a in r.approvers]
                results.append(PASS if able else FAIL)
                said.append(f"{who}: {len(able)} of {len(named)} named approver(s) can sign")
    if not results:
        return NA, "no repository declares a promotion chain that gates production", []
    return combined(results), "; ".join(said), ["approver store", "manifests:prod_approvers"]


def _proof(r: Reading, n: Pseudonyms) -> Answer:
    if not any(p.repositories for p in r.projects):
        return UNKNOWN, "no repository is registered here", []
    results, said, pointers = [], [], []
    for p in r.projects:
        for repo in p.repositories:
            who = n.repository(repo.identity)
            pointers.append(box_file(who))
            if repo.box is None:
                results.append(UNKNOWN)
                said.append(f"{who}: the proof could not be read")
                continue
            state = repo.box.get("state", "")
            results.append(PASS if repo.box.get("valid") is True else FAIL)
            said.append(f"{who}: {state}")
    return combined(results), "; ".join(said), pointers


def _doctor(r: Reading, n: Pseudonyms) -> Answer:
    if not r.projects:
        return UNKNOWN, "no project is registered here", []
    results, said, pointers = [], [], []
    for p in r.projects:
        who = n.project(p.name)
        if p.doctor is None:
            results.append(UNKNOWN)
            said.append(f"{who}: the doctor could not run")
            continue
        pointers.append(doctor_file(who))
        red = [c.get("id") for c in p.doctor.get("checks") or [] if c.get("result") != "ok"]
        results.append(PASS if p.doctor.get("ok") is True and not red else FAIL)
        said.append(f"{who}: " + ("green" if not red else f"red on {', '.join(map(str, red))}"))
    return combined(results), "; ".join(said), pointers


def _workflows(r: Reading, n: Pseudonyms) -> Answer:
    """The credential a job holds may not write the CI definitions: none of what it is granted is
    among the grants its forge row names as reaching them. A grant nobody could read, or a row
    that cannot say which of its grants reach them, is `unknown`."""
    if not r.projects:
        return UNKNOWN, "no project is registered here, so no forge credential is in use", []
    results, said = [], []
    for p in r.projects:
        who = n.project(p.name)
        if p.permissions is None:
            results.append(UNKNOWN)
            said.append(f"{who}: what the credential is granted could not be read — a "
                        f"credential without the scope to ask, or a forge that does not publish "
                        f"it to the credential")
            continue
        granted = ", ".join(f"`{g}`" for g in sorted(p.permissions)) or "nothing"
        if not p.ci_permissions:
            results.append(UNKNOWN)
            said.append(f"{who}: granted {granted}, and the forge does not say which grants "
                        f"reach the CI definitions")
            continue
        reach = sorted(p.permissions & p.ci_permissions)
        if reach:
            results.append(FAIL)
            said.append(f"{who}: granted {', '.join(f'`{g}`' for g in reach)}, which can write "
                        f"the CI definitions")
        else:
            results.append(PASS)
            said.append(f"{who}: granted {granted}; none of it writes the CI definitions")
    return combined(results), "; ".join(said), []


#: The four facts C-BRANCH requires of a protected branch, each with how the evidence says it.
_PROTECTION = (("pr_required", "a pull request is required"),
               ("linear_history", "history is linear"),
               ("force_push_blocked", "force pushes are blocked"),
               ("auto_merge_enabled", "auto-merge is enabled"))


def _branch(r: Reading, n: Pseudonyms) -> Answer:
    """Every repository's base branch requires a pull request, keeps history linear, blocks force
    pushes and allows auto-merge. A fact read as off fails; a fact nobody could read is
    `unknown`, and so is a branch whose protection could not be read at all.

    THE BRANCH IS NEVER NAMED in the evidence: a branch is named by its team, sometimes after
    the customer, and the manifest's `base_branch` is what it is."""
    if not any(p.repositories for p in r.projects):
        return UNKNOWN, "no repository is registered here", []
    results, said = [], []
    for p in r.projects:
        for repo in p.repositories:
            who = n.repository(repo.identity)
            if repo.manifest is None:
                results.append(UNKNOWN)
                said.append(f"{who}: the manifest could not be read, so the branch it merges "
                            f"into is not known")
                continue
            got = repo.protection
            if got is None:
                results.append(UNKNOWN)
                said.append(f"{who}: the protection of its base branch could not be read")
                continue
            off = [words for fact, words in _PROTECTION if getattr(got, fact) is False]
            unread = [words for fact, words in _PROTECTION if getattr(got, fact) is None]
            results.append(FAIL if off else UNKNOWN if unread else PASS)
            words = [f"not: {', '.join(off)}"] if off else []
            words += [f"not read: {', '.join(unread)}"] if unread else []
            said.append(f"{who}: " + ("; ".join(words) if words else
                                      "its base branch requires a pull request, keeps history "
                                      "linear, blocks force pushes and allows auto-merge"))
    return combined(results), "; ".join(said), []


#: A RELEASE is `x.y.z` (three numbers), with or without the `v` a tag carries. A candidate (`0.6.0rc1`,
#: `v0.6.0-rc.1`) and a development build (`0.6.0.dev0`) are not one.
_RELEASE = re.compile(r"v?(\d+)\.(\d+)\.(\d+)")


def _release(text: str) -> tuple[int, int, int] | None:
    m = _RELEASE.fullmatch((text or "").strip())
    return (int(m[1]), int(m[2]), int(m[3])) if m else None


def _version(r: Reading, _n: Pseudonyms) -> Answer:
    """The running version is the latest published release or the one before it, by version
    order — never the order a forge happens to list them in. Unread releases are `unknown`, and so
    is a list that holds no release: there is nothing to measure against."""
    pointer = ["platform.version"]
    if r.releases is None:
        return UNKNOWN, (f"the platform's published releases could not be read — no forge this "
                         f"deployment uses could list them, or the network did not answer; "
                         f"the running version, {r.version}, is recorded in `platform.version`"), \
            pointer
    published = sorted({v for v in map(_release, r.releases) if v}, reverse=True)
    if not published:
        return UNKNOWN, "the releases were read and none of them is a published release", pointer

    def name(v: tuple[int, int, int]) -> str:
        return ".".join(map(str, v))

    running = _release(r.version)
    latest = name(published[0])
    if running is None:
        return FAIL, (f"the running version, {r.version}, is not a release (the latest is "
                      f"{latest})"), pointer
    if running == published[0]:
        return PASS, f"the running version, {r.version}, is the latest release", pointer
    if len(published) > 1 and running == published[1]:
        return PASS, (f"the running version, {r.version}, is the release before the latest "
                      f"({latest})"), pointer
    if running not in published:
        return FAIL, (f"the running version, {r.version}, is not among the published releases "
                      f"(the latest is {latest})"), pointer
    return FAIL, (f"the running version, {r.version}, is older than the release before the "
                  f"latest ({latest})"), pointer


_READERS: dict[str, Callable[[Reading, Pseudonyms], Answer]] = {
    "C-PANEL": _panel,
    "C-ENVFILE": _envfile,
    "C-FORGE-CRED": _forge_cred,
    "C-WORKFLOWS": _workflows,
    "C-BOX-ENV": _box_env,
    "C-TEST": _test,
    "C-SECURITY": _security,
    "C-MERGE": _merge,
    "C-RISK": _risk,
    "C-PROTECT": _protect,
    "C-BRANCH": _branch,
    "C-CONCURRENCY": _concurrency,
    "C-RETENTION": _retention,
    "C-POSTMERGE": _postmerge,
    "C-APPROVERS": _approvers,
    "C-PROOF": _proof,
    "C-VERSION": _version,
    "C-DOCTOR": _doctor,
}
