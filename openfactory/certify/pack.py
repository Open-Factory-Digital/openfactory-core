"""Reading the deployment, assembling the pack, and the tarball (#356).

THREE STEPS, AND ONLY THE FIRST TOUCHES THE MACHINE. `gather` reads what the platform already knows
about itself — the registry, the manifests it reads to run a job, the box proofs, the doctor, the
preflight, the environment and the secrets file's mode — into a `controls.Reading`. `assemble` turns
a reading into the pack's files with every identifier replaced and every credential, address and
path dropped, and refuses to hand back a pack in which anything survived. `write` puts the files in
a tarball. A test drives the second and third with no registry, no Docker and no network.

WHAT IS NEVER READ: ticket titles and bodies, pull request bodies, commit messages, diffs, and any
file inside a customer repository other than the manifest the platform already loads. The box
proof's advisory messages, which can quote a gate's output, are left out of the pack by name.
"""

from __future__ import annotations

import hashlib
import io
import json
import logging
import os
import secrets as _secrets
import subprocess
import tarfile
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path

from openfactory.certify import controls as c
from openfactory.certify.redact import CATEGORIES, Redactor, holds_a_credential
from openfactory.certify.schema import PACK_SCHEMA, validate

log = logging.getLogger("openfactory.certify")

#: The window the outcome aggregates will cover, when they are measured.
DEFAULT_WINDOW_DAYS = 90

#: Why `pack.json` says `"signature": null`, in the pack's own words.
UNSIGNED_BECAUSE = ("minisign signing is not built yet: this pack carries no pack.sig, so nothing "
                    "in it is attested by the partner's key")

#: Why `outcomes` says `not_measured` — never zeros, which would read as a deployment that did
#: nothing.
OUTCOMES_REASON = ("the outcome aggregates over the window (jobs run, merged, parked by class, "
                   "medians for cost and time to pull request, the oldest Needs Action age) come "
                   "from the metrics sink and the journals, and that read is not built yet")

#: What a reader must not look for in this pack, said in the pack.
NOT_YET = (
    "a signature: minisign signing is not built yet, so there is no pack.sig",
    "the forge-read controls: C-WORKFLOWS and C-BRANCH read `unknown`",
    "the releases read: C-VERSION reads `unknown`",
    "the outcome aggregates: `outcomes` is `not_measured`",
    "the env check and conformance diagnostics",
)

#: Registry option keys whose values name an organisation, a repository or a person.
_ORGANISATION_OPTIONS = ("board_owner", "organization", "org", "project", "team")
_REPOSITORY_OPTIONS = ("project_key",)
_PERSON_OPTIONS = ("email",)


class Unsafe(RuntimeError):
    """The pack would carry something it must not — a defect in certify, never a deployment's
    fault. Nothing is written."""


# ── 1. reading the deployment ───────────────────────────────────────────────────────────────────

def gather(*, cwd: Path | None = None) -> c.Reading:
    """Everything the controls and the redactor need, read once, from where certify runs.

    The environment is the process's over the env file's rows (`preflight`'s reading): on the
    compose host the deployment's settings live in `.env.compose`, inside the worker they are its
    environment, and on the one-machine deployment the CLI has already loaded
    `~/.openfactory/env`."""
    from openfactory import __version__, approvals, namespace, preflight
    from openfactory.identity.registry import identity_kind
    from openfactory.policy import protected
    from openfactory.registry import ProjectRegistry
    from openfactory.runtime.temporal.io import DEFAULT_SANDBOX

    here = cwd or Path.cwd()
    env = {**preflight._env_file_rows(str(here / ".env.compose")), **os.environ}
    build = namespace.build_stamp()
    rows = [p for p in ProjectRegistry().list() if p.enabled]
    sandbox = (env.get("OPENFACTORY_SANDBOX") or "").strip().lower() or DEFAULT_SANDBOX

    quieted = logging.getLogger("openfactory")
    was = quieted.level
    quieted.setLevel(logging.ERROR)
    try:
        projects = [_project(p, build) for p in rows]
        try:
            before = preflight.check(preflight.probes_for_this_machine()).as_document()
            before_error = ""
        except Exception as exc:  # noqa: BLE001 — a diagnostic that could not run is stated
            before, before_error = None, str(exc)
    finally:
        quieted.setLevel(was)
    try:
        approvers: list[str] | None = approvals.list_approvers()
    except Exception as exc:  # noqa: BLE001 — an unreadable store is `unknown`, never empty
        log.info("the approver store could not be read (%s)", str(exc)[:160])
        approvers = None

    reading = c.Reading(
        version=__version__, build=build, env=env, env_file=_env_file(here), sandbox=sandbox,
        identity=identity_kind(env), providers=_providers(rows, env, sandbox), projects=projects,
        floor_protected=protected.floor_protected_paths(), approvers=approvers,
        preflight=before, preflight_error=before_error)
    reading.identifiers = _identifiers(rows, projects, approvers or [], env)
    reading.secrets = _secret_values(rows, env)
    reading.variables = _variable_names(rows)
    return reading


def _project(project, build: tuple[str, str]) -> c.ProjectReading:
    from openfactory import box_prove, doctor

    box = getattr(project, "box", None)
    credential, mints = _forge_credential(project)
    reading = c.ProjectReading(
        name=project.name, forge_credential=credential, forge_mints=mints,
        box_env_declared=box is not None and "env" in box.model_fields_set,
        box_env_names=len(box.env) if box is not None else 0)
    reading.repositories.append(_repository(project, "", default=True))
    for repo in _foreign_repositories(project, box_prove._proof_dir()):
        reading.repositories.append(_repository(project, repo, default=False))
    try:
        report = doctor.diagnose(doctor.probes_for(project))
        reading.doctor = doctor.as_document(report, project=project.name, build=build)
    except Exception as exc:  # noqa: BLE001 — a doctor that could not run is `unknown`
        reading.doctor_error = str(exc)
    return reading


#: `credentials.forge_credential_source`'s identities, as the classes C-FORGE-CRED judges.
_SOURCES = {"deployment": "minted", "identity": "identity", "env": "stored",
            "generic": "generic", "login": "login", "": "none"}


def _forge_credential(project) -> tuple[str, bool]:
    """WHAT the forge credential a job of `project` holds is — never its value — asked of the one
    resolution the doctor and the jobs use, and whether the vendor offers a credential to MINT.

    THE PLATFORM'S OWN ANSWER, not a reading of which variables are set: where the generic token
    and a minted credential are both configured, the generic token is what a job is handed (the
    value path comes first), so that is what this reports."""
    from openfactory import credentials

    row = credentials.forge_credential_row(project)
    mints = row is not None and getattr(row, "mint", None) is not None
    try:
        source = credentials.forge_credential_source(project)
    except Exception as exc:  # noqa: BLE001 — an unread source is `unknown`, never a pass
        log.info("the forge credential of %s could not be resolved (%s)", project.name,
                 str(exc)[:160])
        return "unread", mints
    return _SOURCES.get(source.partition(":")[0], "unread"), mints


def _coordinate(project) -> str:
    forge = getattr(project, "forge", None)
    return ((forge.repo if forge else None) or project.tracker.repo or "").strip()


def _foreign_repositories(project, root: Path) -> list[str]:
    """The project's OTHER repositories this deployment knows about: the ones with a proof
    recorded (`<project>--<owner>--<repo>.json`, `card_repo._checkout_key`'s shape). The registry
    names one repository per project; a product's others travel on its cards, and their proofs are
    where the deployment wrote them down."""
    prefix = f"{project.name}--"
    try:
        keys = sorted(p.stem for p in root.glob(f"{prefix}*.json"))
    except OSError:
        return []
    return [k[len(prefix):].replace("--", "/") for k in keys]


def _repository(project, repo: str, *, default: bool) -> c.RepositoryReading:
    from openfactory import box_prove
    from openfactory.loader import load_manifest
    from openfactory.runtime.card_repo import _checkout_key

    identity = repo or _coordinate(project) or f"{project.name}#default"
    key = project.name if default else _checkout_key(project, repo)
    out = c.RepositoryReading(project=project.name, identity=identity, default=default, key=key)
    try:
        if default:
            out.manifest = load_manifest(project)
        else:
            from openfactory.factory import resolve_repo_path
            from openfactory.runtime.card_repo import _runner_view

            view, _ = _runner_view(project, f"{repo}#0")
            out.manifest = load_manifest(view, repo_root=resolve_repo_path(view, cache_key=key))
    except Exception as exc:  # noqa: BLE001 — an unread manifest is `unknown`, never a pass
        out.manifest_error = str(exc)
    try:
        st = box_prove.status(project, repo=repo)
        out.box = st.as_document()
        out.box_lines = _withheld(st).lines()
    except Exception as exc:  # noqa: BLE001 — an unread proof is `unknown`
        out.box_error = str(exc)
    return out


#: What stands in for an advisory finding's message in the pack.
WITHHELD = "(message withheld from the pack: a gate's output can quote the repository)"


def _withheld(st):
    """The status with every advisory MESSAGE replaced — a gate's output can quote a file path or
    a line of the customer's code, and a pack carries neither."""
    import copy

    if st.proof is None or not st.proof.findings:
        return st
    out = copy.deepcopy(st)
    for finding in out.proof.findings:
        finding.message = WITHHELD
    return out


def _env_file(here: Path) -> c.EnvFileReading:
    """The deployment's secrets file as seen from here: `.env.compose` beside the compose file, or
    the one-machine deployment's `~/.openfactory/env`. Only its NAME travels, never its path."""
    for name, path in ((".env.compose", here / ".env.compose"),
                       ("~/.openfactory/env", Path("~/.openfactory/env").expanduser())):
        if path.is_file():
            try:
                mode = path.stat().st_mode & 0o777
            except OSError:
                mode = None
            return c.EnvFileReading(name, True, mode, _tracked(path))
    return c.EnvFileReading("", False)


def _tracked(path: Path) -> bool | None:
    """Whether git tracks this file — None when git cannot be asked at all."""
    try:
        done = subprocess.run(["git", "-C", str(path.parent), "ls-files", "--error-unmatch",
                               path.name], capture_output=True, text=True, timeout=20)
    except (OSError, subprocess.SubprocessError):
        return None
    if done.returncode == 0:
        return True
    said = (done.stderr or "").lower()
    if "did not match" in said or "not a git repository" in said:
        return False
    return None


def _providers(rows, env: dict[str, str], sandbox: str) -> dict[str, list[str]]:
    """Which KIND serves each axis — kind names only."""
    from openfactory.adapters.agent.registry import harness_kind
    from openfactory.identity.registry import identity_kind

    def kinds(values) -> list[str]:
        return sorted({str(v) for v in values if v})

    return {
        "tracker": kinds(p.tracker.kind for p in rows),
        "forge": kinds(p.forge.kind for p in rows if p.forge),
        "ci": kinds(p.ci.kind for p in rows if p.ci),
        "channel": kinds((p.channel or "panel") for p in rows),
        "harness": kinds(harness_kind(p, "executor") for p in rows),
        "box": [sandbox],
        "identity": [identity_kind(env)],
        "metrics": [(env.get("OPENFACTORY_METRICS_SINK") or "default").strip().lower()],
        "preview": [(env.get("OPENFACTORY_PREVIEW_RUNTIME") or "none").strip().lower()],
    }


def _identifiers(rows, projects: list[c.ProjectReading], approvers: list[str],
                 env: dict[str, str]) -> dict[str, dict[str, set[str]]]:
    """Every name the deployment carries that a pack must not, by category, with its aliases."""
    ids: dict[str, dict[str, set[str]]] = {k: defaultdict(set) for k in CATEGORIES}

    def coordinate(value, *aliases: str) -> None:
        value = str(value or "").strip()
        if not value:
            return
        ids["repository"][value].update(a for a in aliases if a)
        if "/" in value:
            ids["repository"][value].add(value.rsplit("/", 1)[-1])
            ids["organisation"].setdefault(value.split("/", 1)[0], set())

    def person(*names) -> None:
        for name in names:
            if str(name or "").strip():
                ids["person"].setdefault(str(name).strip(), set())

    for p in rows:
        ids["project"].setdefault(p.name, set())
        for axis in (p.tracker, p.forge, p.ci):
            if axis is None:
                continue
            coordinate(axis.repo)
            options = axis.options or {}
            for key in _ORGANISATION_OPTIONS:
                if options.get(key):
                    ids["organisation"].setdefault(str(options[key]), set())
            for key in _REPOSITORY_OPTIONS:
                coordinate(options.get(key))
            person(*(options.get(k) for k in _PERSON_OPTIONS))
        board = getattr(p, "factory_board", None)
        if board is not None:
            if board.tracker is not None:
                coordinate(board.tracker.repo)
            person(board.supervisor)
        if p.product is not None:
            coordinate(p.product.docs_repo)
            person(*p.product.admins)
        for login, channel_id in (p.people or {}).items():
            ids["person"][login].add(str(channel_id))
        person(*p.admins)
        for key, value in (p.channel_options or {}).items():
            if not key.endswith("_env") and str(value or "").strip():
                ids["organisation"].setdefault(str(value), set())
    for project in projects:
        for repo in project.repositories:
            coordinate(repo.identity, *(() if repo.default else (repo.key,)))
            m = repo.manifest
            if m is not None:
                person(*(getattr(m, "reviewers", None) or []),
                       *(getattr(m, "prod_approvers", None) or []))
                coordinate(getattr(m, "docs_repo", None))
    person(*approvers, env.get("OPENFACTORY_BOT_LOGIN"), env.get("OPENFACTORY_BOT_NAME"))
    return {k: dict(v) for k, v in ids.items()}


def _secret_values(rows, env: dict[str, str]) -> set[str]:
    """The VALUE of every credential-shaped variable, and of every variable the registry names as
    a credential (`token_env`, a channel's `*_env`) — whatever it is called."""
    named = {k for k, v in env.items() if holds_a_credential(k)}
    for p in rows:
        for axis in (p.tracker, p.forge, p.ci):
            if axis is not None and (axis.options or {}).get("token_env"):
                named.add(str(axis.options["token_env"]))
        named.update(str(v) for k, v in (p.channel_options or {}).items() if k.endswith("_env"))
    return {env[n].strip() for n in named if (env.get(n) or "").strip()}


def _variable_names(rows) -> set[str]:
    """The NAMES of the variables the registry declares — `token_env`, `box.env`, a channel's
    `*_env`, a preview's — that are not the platform's own. A name a customer chose for their
    credential (`CASTELLO_ADO_PAT`) names the customer, and the doctor quotes it."""
    from openfactory.certify.redact import credential_names

    names: set[str] = set()
    for p in rows:
        for axis in (p.tracker, p.forge, p.ci):
            if axis is not None and (axis.options or {}).get("token_env"):
                names.add(str(axis.options["token_env"]))
        if p.box is not None:
            names.update(p.box.env)
        names.update(str(v) for k, v in (p.channel_options or {}).items() if k.endswith("_env"))
        if p.preview is not None:
            for mapping in (*p.preview.env.values(), *p.preview.build_args.values()):
                names.update(mapping)
                names.update(mapping.values())
    platform = credential_names()
    return {n.strip() for n in names if n and n.strip()
            and not n.startswith("OPENFACTORY_") and n not in platform}


# ── 2. assembling the pack ──────────────────────────────────────────────────────────────────────

@dataclass
class Pack:
    files: dict[str, str]
    document: dict
    controls: list[c.Control]
    salt_id: str
    when: datetime
    notes: list[str] = field(default_factory=list)

    @property
    def default_name(self) -> str:
        return f"openfactory-evidence-{self.salt_id}-{self.when:%Y-%m-%d}.tgz"


def parse_consent(consent: str) -> tuple[str, str, str] | None:
    """`"name, role, date"` as its three parts, or None when it is not that shape."""
    parts = [p.strip() for p in (consent or "").split(",")]
    if len(parts) < 3 or not parts[0] or not parts[-1]:
        return None
    return parts[0], ", ".join(parts[1:-1]), parts[-1]


def _iso(when: datetime) -> str:
    return when.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _dumps(document) -> str:
    return json.dumps(document, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def assemble(reading: c.Reading, *, profile: str, partner: str, practitioner: str,
             window_days: int = DEFAULT_WINDOW_DAYS, consent: str = "",
             when: datetime | None = None, salt: bytes | None = None) -> Pack:
    """The pack's files, anonymised, validated, and checked for survivors before anything else
    sees them. Raises `Unsafe` rather than return a pack that carries what it must not."""
    when = when or datetime.now(UTC)
    consented = parse_consent(consent) if consent else None
    identifiers = {k: {i: set(a) for i, a in v.items()}
                   for k, v in (reading.identifiers or {}).items()}
    if consented:
        identifiers.setdefault("person", {}).setdefault(consented[0], set())
    redactor = Redactor(salt=salt or _secrets.token_bytes(32), identifiers=identifiers,
                        secrets=reading.secrets, variables=reading.variables, keep=practitioner)
    files: dict[str, str] = {}
    notes: list[str] = []

    # THE DIAGNOSTICS, each scrubbed under its own file name so redactions.json can say where.
    if reading.preflight is not None:
        files[c.PREFLIGHT_FILE] = _dumps(
            redactor.scrub_document(reading.preflight, where=c.PREFLIGHT_FILE))
    else:
        notes.append("preflight could not run here: "
                     + redactor.scrub(reading.preflight_error, where="summary.md"))
    proofs = []
    for p in reading.projects:
        who = redactor.project(p.name)
        if p.doctor is not None:
            where = c.doctor_file(who)
            doc = dict(p.doctor, project=who)
            files[where] = _dumps(redactor.scrub_document(doc, where=where))
        else:
            notes.append(f"the doctor could not run on {who}: "
                         + redactor.scrub(p.doctor_error, where="summary.md"))
        for repo in p.repositories:
            name = redactor.repository(repo.identity)
            where = c.box_file(name)
            if repo.box is not None:
                files[where] = "\n".join(redactor.scrub(line, where=where)
                                         for line in repo.box_lines) + "\n"
                if repo.box.get("advisories"):
                    redactor.drop_field(where=where, field="advisories[].message",
                                        why="a gate's output can quote the repository")
            else:
                files[where] = ("the proof could not be read: "
                                + redactor.scrub(repo.box_error, where=where) + "\n")
            proofs.append({"project": who, "repository": name,
                           "status": (repo.box or {}).get("state") or "unknown"})

    results = c.evaluate(reading, profile, redactor)
    for control in results:
        control.detail = redactor.scrub(control.detail, where="pack.json")

    code, built = reading.build
    document = {
        "schema": PACK_SCHEMA,
        "generated_at": _iso(when),
        "platform": {"version": reading.version,
                     "build": {"code": code, "built": built} if code else None},
        "partner": partner,
        "profile": profile,
        "practitioner": practitioner,
        "window": {"days": window_days, "since": _iso(when - timedelta(days=window_days)),
                   "until": _iso(when)},
        "providers": redactor.scrub_document(reading.providers, where="pack.json"),
        "controls": [r.as_entry() for r in results],
        "outcomes": {"status": "not_measured", "reason": OUTCOMES_REASON},
        "proofs": proofs,
        "consent": ({"by": redactor.person(consented[0]),
                     "role": redactor.scrub(consented[1], where="pack.json"),
                     "date": redactor.scrub(consented[2], where="pack.json")}
                    if consented else None),
        "salt_id": redactor.salt_id,
        "signature": None,
        "unsigned_because": UNSIGNED_BECAUSE,
        "not_in_this_pack": list(NOT_YET),
        "checksums": {},
    }
    files["summary.md"] = render_summary(document, notes=notes,
                                         pseudonyms=redactor.pseudonyms)
    files["redactions.json"] = _dumps(redactor.log())
    document["checksums"] = {path: "sha256:" + hashlib.sha256(text.encode()).hexdigest()
                             for path, text in sorted(files.items())}
    ordered = {"pack.json": _dumps(document), "summary.md": files.pop("summary.md"),
               "redactions.json": files.pop("redactions.json"), **dict(sorted(files.items()))}

    errors = validate(document)
    if errors:
        raise Unsafe("pack.json does not match its published schema (pack.schema.json): "
                     + "; ".join(errors))
    leaked = _survivors(redactor, ordered)
    if leaked:
        raise Unsafe("the pack would carry what it must not — " + "; ".join(leaked))
    return Pack(files=ordered, document=document, controls=results, salt_id=redactor.salt_id,
                when=when, notes=notes)


def _survivors(redactor: Redactor, files: dict[str, str]) -> list[str]:
    """Every file asked, the way it was scrubbed: a JSON file string by string (its keys too), a
    text file whole. Answers WHAT survived and where — never the value."""
    out: list[str] = []

    def strings(node):
        if isinstance(node, dict):
            for k, v in node.items():
                yield str(k)
                yield from strings(v)
        elif isinstance(node, list):
            for v in node:
                yield from strings(v)
        elif isinstance(node, str):
            yield node

    for path, text in files.items():
        found = sorted({kind for s in (strings(json.loads(text)) if path.endswith(".json")
                                       else [text]) for kind in redactor.survivors(s)})
        if found:
            out.append(f"{path}: {', '.join(found)}")
    return out


def render_summary(document: dict, *, notes: list[str], pseudonyms: dict[str, str]) -> str:
    """`summary.md` — the pack, for a person. What it does NOT contain comes before what it does."""
    def cell(text: str) -> str:
        return str(text).replace("|", "\\|").replace("\n", " ")

    platform = document["platform"]
    build = platform["build"]
    lines = [
        "# OpenFactory deployment evidence pack",
        "",
        f"- Partner: `{document['partner']}`",
        f"- Profile claimed: **{document['profile']}**",
        f"- Responsible practitioner: {document['practitioner']}",
        f"- Platform: {platform['version']}"
        + (f" (build {build['code']}, built {build['built']})" if build else
           " (not a built image)"),
        f"- Generated: {document['generated_at']}",
        f"- Window: {document['window']['days']} days, {document['window']['since']} to "
        f"{document['window']['until']}",
        f"- Salt id: `{document['salt_id']}` (the salt itself is never written)",
        "",
        "## What this pack does not contain yet",
        "",
        "This pack is not signed, and some of what the partner program asks for is not read yet. "
        "Every gap is stated here and in `pack.json`; none of it is filled with a guess.",
        "",
        *[f"- {item}" for item in document["not_in_this_pack"]],
        "",
        f"Signature: none. {UNSIGNED_BECAUSE}.",
        "",
        f"Outcomes: {document['outcomes']['status']}. {document['outcomes']['reason']}.",
        "",
        "## Controls",
        "",
        "| Control | Required | Result | Evidence |",
        "|---|---|---|---|",
    ]
    for control in document["controls"]:
        lines.append(f"| {control['id']} | {'yes' if control['required'] else 'no'} | "
                     f"{control['result']} | {cell(control['evidence']['detail'])} |")
    required = [x for x in document["controls"] if x["required"]]
    tally = defaultdict(int)
    for x in required:
        tally[x["result"]] += 1
    lines += ["", f"{len(required)} control(s) required by the {document['profile']} profile: "
              + ", ".join(f"{n} {result}" for result, n in sorted(tally.items())) + "."]
    lines += ["", "## Box proofs", ""]
    if document["proofs"]:
        lines += ["| Project | Repository | Status |", "|---|---|---|"]
        lines += [f"| {p['project']} | {p['repository']} | {p['status']} |"
                  for p in document["proofs"]]
    else:
        lines.append("No repository is registered on this deployment.")
    lines += ["", "## Provider kinds", ""]
    lines += [f"- {axis}: {', '.join(kinds) or 'none'}"
              for axis, kinds in sorted(document["providers"].items())]
    lines += ["", "## Consent", ""]
    consent = document["consent"]
    lines.append(f"Recorded: {consent['by']}, {consent['role']}, {consent['date']}." if consent
                 else "No consent was recorded (`--consent`).")
    lines += ["", "## Redactions", ""]
    by_category = defaultdict(int)
    for category in pseudonyms.values():
        by_category[category] += 1
    lines.append("Pseudonyms: " + (", ".join(f"{n} {k}" for k, n in sorted(by_category.items()))
                                   or "none") + ". The full log, with every count of what was "
                 "replaced and dropped, is `redactions.json`; it never holds an original.")
    if notes:
        lines += ["", "## Notes", "", *[f"- {cell(n)}" for n in notes]]
    return "\n".join(lines) + "\n"


# ── 3. the tarball ──────────────────────────────────────────────────────────────────────────────

def write(pack: Pack, out: Path) -> Path:
    """The pack as a gzipped tarball at `out`. Never replaces a file that is already there."""
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as tar:
        for path, text in pack.files.items():
            data = text.encode("utf-8")
            info = tarfile.TarInfo(path)
            info.size = len(data)
            info.mtime = int(pack.when.timestamp())
            info.mode = 0o644
            tar.addfile(info, io.BytesIO(data))
    with open(out, "xb") as fh:
        fh.write(buffer.getvalue())
    return out
