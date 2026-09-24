"""Read a repository and DRAFT how a preview of it would run — the fifth field `infer` attempts
(ADR-0050 D12; the design on #265, §4.1).

A preview is the client's own compose file, read from the base branch and admitted key by key. Most
repositories a factory meets have none: a Dockerfile, or two, or nothing but `manage.py`. This
module reads what IS there and says, in the three tiers `infer.py` already speaks, what a preview
would be made of — so the person merging it is reviewing a restatement of their own files, never a
guess dressed as one.

THE SAME CONTRACT AS `infer.py`, AND FOR THE SAME REASON
---------------------------------------------------------
It reads files. It runs nothing — not `docker build`, not `docker compose config`, not the
client's install step: a Dockerfile's `RUN` line is agent-influenced text that executes with
network access, and this module runs on whatever machine asked, the operator's laptop included.
It touches no network. It writes nothing: it returns an object, and `preview_propose.py` is the
only thing that turns the object into files — in a clone that becomes a pull request a person
merges. Same repository state → same draft, byte for byte; every list is sorted with an explicit
key.

THREE SHAPES A REPOSITORY ARRIVES IN
------------------------------------
(a) A COMPOSE FILE, under one of the spec's four names at the root. Proposed: only the BLOCK that
    says what the file does not — which services a person opens (`expose`, inferred from what they
    publish), how data is seeded (asked). Plus an OVERRIDE when the file cannot show a change: a
    service that only names a published image while a Dockerfile here builds it (S2), or a service
    configured to reach a database outside the preview, with a fresh one drafted in its place (S9).
(b) DOCKERFILES and no compose (S3, S4, S8). One service per directory, at the root or one level
    deep — a Dockerfile deeper than that (`tools/loadtest/`, `vendor/x/`) is asked about, never
    drafted, and two in one directory are asked about too: which one runs is the team's to say.
(c) NEITHER (S5). A Dockerfile is drafted only when the start command is ANCHORED to a file that
    was actually read — a `Procfile`'s `web:`, `package.json`'s `start`, a Makefile target, or
    `manage.py`. Nothing anchored, nothing drafted: only the questions.

A data store a service needs is drafted from a dependency MARKER actually read (`psycopg` in a
requirements file → `postgres:16`), always with the image's own healthcheck and the application's
`depends_on: {condition: service_healthy}` — without them the first boot races the database and a
live preview shows a dead service.

WHAT A DRAFT NEVER CARRIES
--------------------------
A secret's value. A literal that looks like a credential — a password inside a URL, a name that
says SECRET, KEY, TOKEN or PASSWORD — is FLAGGED where it was read, by name and `file:line` only,
and a name the application reads for a secret is listed for the REGISTRY (`preview.env`), which
is where a preview's values come from. The excerpt of such a line is never kept, because an
excerpt travels into a pull request body, and a body on a client's forge cannot be un-published.
"""

from __future__ import annotations

import json
import posixpath
import re
import tomllib
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field

from openfactory import namespace
from openfactory.onboarding.infer import (
    INFERRED,
    OBSERVED,
    UNKNOWN,
    Evidence,
    Proposal,
    _LineLoader,
    _read,
    _Tree,
    _tree,
)

# ONE RULE FOR "A HOST A PREVIEW CANNOT REACH", borrowed from the plan's own note rather than
# copied: the draft asks exactly what a live card would later say, and a second copy would be the
# first thing to drift when either learns a new shape of address.
from openfactory.preview.assemble import _LOCAL_HOSTS, _REF, _URL_HOST, url_var

#: The compose spec's own file names, in the order it looks them up.
COMPOSE_NAMES = ("compose.yaml", "compose.yml", "docker-compose.yaml", "docker-compose.yml")
#: Where every file the factory drafts lives: under `.openfactory/`, so it never collides with a
#: file of the client's, and on the deployment floor, so it is never auto-merged.
DRAFT_COMPOSE = ".openfactory/preview.compose.yml"
DRAFT_DIR = ".openfactory/preview"
#: Example environment files a team commits beside the real one it ignores.
ENV_EXAMPLES = (".env.example", ".env.sample")

#: Written by a person with `--set`, outranking any tier.
ANSWERED = "answered"
_RANK = {UNKNOWN: 0, INFERRED: 1, OBSERVED: 2, ANSWERED: 3}


def weakest(*tiers: str) -> str:
    """The tier a thing made of several claims carries: its weakest one."""
    return min(tiers, key=lambda t: _RANK.get(t, 0)) if tiers else UNKNOWN


# ── the data stores a marker implies ────────────────────────────────────────────────────────────


class Store(BaseModel):
    """A data store drafted as a service of its own: an official image, its healthcheck, a named
    volume, and the address a service reaches it at."""

    kind: str
    image: str
    port: int
    #: the variable an application conventionally reads its address from
    var: str
    #: URL schemes that name this store (`postgresql://` is `postgres://`)
    schemes: tuple[str, ...]
    #: the image's own variables; throwaway values of a fresh store only its preview can reach
    env: dict[str, str] = Field(default_factory=dict)
    healthcheck: list[str]
    data: str
    #: `{host}` is the drafted service's name
    url: str
    #: what the service is called when the name is free
    service: str

    def address(self, host: str) -> str:
        return self.url.format(host=host)


STORES: dict[str, Store] = {
    "postgres": Store(
        kind="postgres", image="postgres:16", port=5432, var="DATABASE_URL",
        schemes=("postgres", "postgresql"),
        env={"POSTGRES_USER": "app", "POSTGRES_PASSWORD": "app", "POSTGRES_DB": "app"},
        healthcheck=["CMD-SHELL", "pg_isready -U app -d app"], data="/var/lib/postgresql/data",
        url="postgres://app:app@{host}:5432/app", service="db"),
    "mysql": Store(
        kind="mysql", image="mysql:8", port=3306, var="DATABASE_URL", schemes=("mysql", "mariadb"),
        env={"MYSQL_DATABASE": "app", "MYSQL_USER": "app", "MYSQL_PASSWORD": "app",
             "MYSQL_ROOT_PASSWORD": "app"},
        healthcheck=["CMD", "mysqladmin", "ping", "-h", "127.0.0.1"], data="/var/lib/mysql",
        url="mysql://app:app@{host}:3306/app", service="db"),
    "redis": Store(
        kind="redis", image="redis:7", port=6379, var="REDIS_URL", schemes=("redis", "rediss"),
        healthcheck=["CMD", "redis-cli", "ping"], data="/data", url="redis://{host}:6379/0",
        service="redis"),
    "mongo": Store(
        kind="mongo", image="mongo:7", port=27017, var="MONGODB_URI",
        schemes=("mongodb", "mongodb+srv"),
        healthcheck=["CMD", "mongosh", "--quiet", "--eval", "db.runCommand({ping:1})"],
        data="/data/db", url="mongodb://{host}:27017/app", service="mongo"),
    "rabbitmq": Store(
        kind="rabbitmq", image="rabbitmq:3", port=5672, var="AMQP_URL", schemes=("amqp", "amqps"),
        env={"RABBITMQ_DEFAULT_USER": "app", "RABBITMQ_DEFAULT_PASS": "app"},
        healthcheck=["CMD", "rabbitmq-diagnostics", "-q", "ping"], data="/var/lib/rabbitmq",
        url="amqp://app:app@{host}:5672/", service="rabbitmq"),
}

#: A dependency NAME, read in a service's own directory, and the store it means. Names only: a
#: word in a README is not a dependency, and a guess from the stack ("Django, so Postgres") is not
#: a marker.
_MARKERS: dict[str, str] = {
    "psycopg": "postgres", "psycopg2": "postgres", "psycopg2-binary": "postgres",
    "psycopg-binary": "postgres", "asyncpg": "postgres", "pg": "postgres",
    "github.com/jackc/pgx": "postgres", "github.com/lib/pq": "postgres",
    "mysql2": "mysql", "pymysql": "mysql", "mysqlclient": "mysql",
    "github.com/go-sql-driver/mysql": "mysql",
    "redis": "redis", "ioredis": "redis", "github.com/redis/go-redis": "redis",
    "pymongo": "mongo", "mongoose": "mongo", "mongodb": "mongo", "motor": "mongo",
    "go.mongodb.org/mongo-driver": "mongo",
    "amqp": "rabbitmq", "amqplib": "rabbitmq", "pika": "rabbitmq", "aio-pika": "rabbitmq",
    "github.com/rabbitmq/amqp091-go": "rabbitmq",
}

#: Images that are a data store, by their repository's last segment. Such a service is never
#: proposed for `expose`: a person opens screens and APIs, not a database's port.
_STORE_IMAGES = frozenset({"postgres", "postgis", "mysql", "mariadb", "redis", "valkey", "mongo",
                           "rabbitmq", "memcached", "elasticsearch", "opensearch", "minio",
                           "mailhog", "mailpit", "localstack"})


# ── the reading, as data ────────────────────────────────────────────────────────────────────────


class Env(BaseModel):
    """One `environment:` line the draft writes, and how much of it was made up."""

    name: str
    value: str
    tier: str
    evidence: list[Evidence] = Field(default_factory=list)
    note: str = ""
    #: also a build argument, so a bundler that bakes it at build time receives it
    build_arg: bool = False
    #: the drafted services this line points at — written only when they are
    needs: list[str] = Field(default_factory=list)


class Service(BaseModel):
    """One service the draft writes: built from a Dockerfile here, built from a Dockerfile the
    factory drafted, a data store, or a patch to a service the client's compose file declares."""

    name: str
    #: "build" · "draft" · "store" · "patch"
    kind: str
    tier: str
    evidence: list[Evidence] = Field(default_factory=list)
    #: the build context as the compose CLI resolves it — against the FIRST compose file's
    #: directory, measured on the pinned plugin (v2.32.4)
    context: str = ""
    #: relative to the context
    dockerfile: str = ""
    image: str = ""
    environment: list[Env] = Field(default_factory=list)
    #: stores this service waits for, healthy
    depends_on: list[str] = Field(default_factory=list)
    healthcheck: list[str] = Field(default_factory=list)
    #: `<volume>:<path>` for a store's data
    volume: str = ""
    store: str = ""
    #: the Dockerfile's FROM lines and the command it runs, quoted in the pull request's body
    quoted: list[Evidence] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class DockerfileDraft(BaseModel):
    """A Dockerfile the factory drafts for a repository that has none — only when the command it
    starts is anchored to a file that was read."""

    service: str
    path: str
    ignore: str
    base: str
    base_evidence: Evidence
    #: the repository's own roots — never `COPY . .`, so nothing the survey did not name is baked
    copy_files: list[str] = Field(default_factory=list)
    copy_dirs: list[str] = Field(default_factory=list)
    install: list[str] = Field(default_factory=list)
    install_tier: str = UNKNOWN
    install_evidence: list[Evidence] = Field(default_factory=list)
    #: a shell string (a Procfile's or a Makefile's line) or an argument list
    command: str | list[str]
    command_tier: str
    command_evidence: Evidence
    port: int | None = None
    port_tier: str = UNKNOWN
    port_evidence: Evidence | None = None
    #: the command reads `$PORT`, so the image sets it
    reads_port: bool = False

    @property
    def tier(self) -> str:
        return weakest(INFERRED, self.install_tier, self.command_tier)


class Flag(BaseModel):
    """A literal that looks like a credential, where it was read. NEVER its value."""

    path: str
    line: int | None = None
    service: str
    name: str
    why: str

    @property
    def locator(self) -> str:
        return f"{self.path}:{self.line}" if self.line else self.path


class RegistryName(BaseModel):
    """A name the application reads whose value belongs in the registry's `preview.env`, never in
    a file: a secret, or a variable from an env file the repository does not commit."""

    service: str
    name: str
    path: str
    line: int | None = None
    why: str

    @property
    def locator(self) -> str:
        return f"{self.path}:{self.line}" if self.line else self.path


class Existing(BaseModel):
    """A service the client's compose file already declares, as the pull request's body shows it:
    what merging the block lets the factory run is THEIR file, so it is named service by service."""

    name: str
    line: int | None = None
    image: str = ""
    #: the build context and Dockerfile as the file names them, relative to the repository
    context: str = ""
    dockerfile: str = ""
    quoted: list[Evidence] = Field(default_factory=list)
    #: host paths it mounts, as written
    binds: list[str] = Field(default_factory=list)
    store: bool = False


class PreviewProposal(BaseModel):
    """What one read of one repository can say about how a preview of it would run."""

    repo: str
    #: the repository's short name — a root Dockerfile's service is named after it
    name: str
    #: "declared" (the manifest already has `preview:`) · "compose" · "dockerfiles" · "draft" ·
    #: "nothing"
    case: str
    #: `preview.compose`: the files the block names, in merge order
    compose: Proposal
    #: the client's compose files the draft overrides (S2, S9); empty when the draft IS the file
    overrides: list[str] = Field(default_factory=list)
    #: the services the client's compose file declares, when there is one
    existing: list[Existing] = Field(default_factory=list)
    services: list[Service] = Field(default_factory=list)
    dockerfiles: list[DockerfileDraft] = Field(default_factory=list)
    expose: dict[str, Proposal] = Field(default_factory=dict)
    data: dict[str, Proposal] = Field(default_factory=dict)
    questions: list[str] = Field(default_factory=list)
    flags: list[Flag] = Field(default_factory=list)
    registry: list[RegistryName] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
    #: the files the draft was read from, sorted — what the card says it could be drafted from
    read: list[str] = Field(default_factory=list)
    #: the block the manifest already declares, when it does
    declared: dict[str, Any] | None = None
    #: a web framework whose host check a named preview domain must pass (Django, Rails)
    host_check: str = ""

    def rows(self) -> list[Proposal]:
        """The reading as `env read` shows it: one row per claim, with its tier and its source."""
        out: list[Proposal] = []
        if self.case == "declared":
            out.append(self.compose)
            return out
        if self.compose.value or self.compose.note:
            out.append(self.compose)
        for svc in self.services:
            out.append(Proposal(field=f"preview.service.{svc.name}", value=_describe(svc),
                                confidence=svc.tier, evidence=svc.evidence,
                                note=" ".join(svc.notes)))
            # a store's own variables are the image's convention, said once on the store's row
            for env in [] if svc.kind == "store" else svc.environment:
                out.append(Proposal(field=f"preview.service.{svc.name}.environment.{env.name}",
                                    value=env.value, confidence=env.tier,
                                    evidence=env.evidence, note=env.note))
        for draft in self.dockerfiles:
            out.append(Proposal(field=f"preview.dockerfile.{draft.service}", value=draft.path,
                                confidence=draft.tier,
                                evidence=[draft.command_evidence, draft.base_evidence],
                                note=f"starts `{_shown_command(draft.command)}`"))
        out += [self.expose[k] for k in sorted(self.expose)]
        out += [self.data[k] for k in sorted(self.data)]
        for name in self.registry:
            out.append(Proposal(
                field=f"preview.env.{name.service}.{name.name}", value=None, confidence=UNKNOWN,
                evidence=[Evidence(path=name.path, line=name.line)],
                note=f"{name.why} — the operator names it for previews in the registry "
                     f"(`preview.env`), never in a file"))
        return out

    def said(self) -> str:
        """What the repository says a preview could be drafted from, in a few words: the card's
        sentence names it (`Dockerfile, EXPOSE 8000`), and "" means nothing at all."""
        if self.case == "compose":
            return self.compose.evidence[0].path if self.compose.evidence else ""
        if self.case == "dockerfiles":
            parts = []
            for svc in self.services:
                if svc.kind != "build":
                    continue
                port = self.expose.get(svc.name)
                where = posixpath.join(svc.context.removeprefix("..").lstrip("/"),
                                       svc.dockerfile)
                parts.append(where + (f", EXPOSE {port.value}"
                                      if port is not None and port.confidence == OBSERVED else ""))
            return "; ".join(parts)
        if self.case in ("draft", "nothing"):
            return _and(self.read)
        return ""


def _and(names: list[str], word: str = "and") -> str:
    shown = [f"`{n}`" for n in names]
    if len(shown) <= 1:
        return "".join(shown)
    return f"{', '.join(shown[:-1])} {word} {shown[-1]}"


def _describe(svc: Service) -> str:
    if svc.kind == "store":
        return f"{svc.image} (healthchecked), a fresh volume every time"
    if svc.kind == "patch":
        what = []
        if svc.dockerfile:
            what.append(f"built from `{svc.context}` with `{svc.dockerfile}`")
        if svc.environment:
            what.append(", ".join(f"`{e.name}`" for e in svc.environment) + " re-pointed")
        return "; ".join(what) or "patched"
    return f"built from `{svc.context}` with `{svc.dockerfile}`"


def _shown_command(command: str | list[str]) -> str:
    return command if isinstance(command, str) else " ".join(command)


# ── small readers ───────────────────────────────────────────────────────────────────────────────


def _is_dockerfile(name: str) -> bool:
    """All three spellings `onboarding/context.py` reads: `Dockerfile`, `Dockerfile.dev`,
    `api.Dockerfile`."""
    return name == "Dockerfile" or name.startswith("Dockerfile.") or name.endswith(".Dockerfile")


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")


def _lines(text: str) -> list[str]:
    return text.splitlines()


_FROM = re.compile(r"^\s*FROM\s+(\S+)", re.IGNORECASE)
_EXPOSE = re.compile(r"^\s*EXPOSE\s+(\S+)", re.IGNORECASE)
_START = re.compile(r"^\s*(CMD|ENTRYPOINT)\s+(.+)$", re.IGNORECASE)


class _Dockerfile(BaseModel):
    path: str
    froms: list[Evidence] = Field(default_factory=list)
    expose: int | None = None
    expose_evidence: Evidence | None = None
    start: Evidence | None = None


def _read_in(root: Path, rel: str) -> str | None:
    """`rel`'s text, READ ONLY INSIDE `root` — None when it is missing, unreadable, or not there.

    A PATH THAT LEAVES THE TREE IS NOT READ. What this module reads is quoted: on a card, in a
    pull request's body, in `preview draft`. And a tree can be one an agent wrote — the card's job
    hands its own checkout to `offer_facts` — so a `Dockerfile` that is a symlink to a file of the
    worker's would put that file's lines where a person reads them. The real location is asked of
    the filesystem, and anything whose real path is not under the tree's own is treated as absent,
    the same answer a file that is not there gets."""
    try:
        base = root.resolve(strict=True)
        real = (root / rel).resolve(strict=True)
    except (OSError, RuntimeError):
        return None
    if base not in real.parents:
        return None
    return _read(real)


def _read_dockerfile(root: Path, rel: str) -> _Dockerfile | None:
    text = _read_in(root, rel)
    if text is None:
        return None
    out = _Dockerfile(path=rel)
    for number, raw in enumerate(_lines(text), start=1):
        # QUOTED IN A PULL REQUEST'S BODY, so a line holding a secret is named, never copied
        line = quoted(raw.strip())
        if _FROM.match(raw):
            out.froms.append(Evidence(path=rel, line=number, excerpt=line))
        m = _EXPOSE.match(raw)
        if m and out.expose is None:
            port = m.group(1).split("/", 1)[0]
            if port.isdigit() and 1 <= int(port) <= 65535:
                out.expose = int(port)
                out.expose_evidence = Evidence(path=rel, line=number, excerpt=line)
        if _START.match(raw):
            out.start = Evidence(path=rel, line=number, excerpt=line)
    return out


def _dependencies(root: Path, tree: _Tree, directory: str) -> list[tuple[str, Evidence]]:
    """(store kind, where its marker was read) for every dependency marker in ONE directory —
    the service's own, never a sibling's. Sorted, and one entry per store kind."""
    found: dict[str, Evidence] = {}
    prefix = f"{directory}/" if directory else ""

    def mark(name: str, rel: str, line: int | None, excerpt: str) -> None:
        key = name.strip().lower().replace("_", "-")
        key = re.sub(r"/v\d+$", "", key)
        kind = _MARKERS.get(key)
        if kind is None:
            kind = next((k for m, k in _MARKERS.items() if "/" in m and key.startswith(m)), None)
        if kind and kind not in found:
            found[kind] = Evidence(path=rel, line=line, excerpt=excerpt)

    for rel in tree.files:
        if not rel.startswith(prefix) or "/" in rel[len(prefix):]:
            continue
        name = Path(rel).name
        text = _read_in(root, rel)
        if text is None:
            continue
        if re.match(r"^requirements.*\.txt$", name):
            for number, raw in enumerate(_lines(text), start=1):
                line = raw.strip()
                if not line or line.startswith(("#", "-")):
                    continue
                mark(re.split(r"[\s<>=!~;\[@]", line, maxsplit=1)[0], rel, number, line)
        elif name == "pyproject.toml":
            try:
                doc = tomllib.loads(text)
            except (tomllib.TOMLDecodeError, ValueError):
                continue
            project = doc.get("project") if isinstance(doc, dict) else None
            deps = list((project or {}).get("dependencies") or [])
            poetry = (((doc.get("tool") or {}).get("poetry") or {}).get("dependencies") or {})
            deps += list(poetry) if isinstance(poetry, dict) else []
            for dep in deps:
                if isinstance(dep, str):
                    bare = re.split(r"[\s<>=!~;\[@]", dep, maxsplit=1)[0]
                    number = next((i for i, raw in enumerate(_lines(text), start=1)
                                   if bare and bare in raw), None)
                    mark(bare, rel, number, _lines(text)[number - 1].strip() if number else dep)
        elif name == "package.json":
            try:
                doc = json.loads(text)
            except ValueError:
                continue
            deps = doc.get("dependencies") if isinstance(doc, dict) else None
            for dep in sorted(deps or {}) if isinstance(deps, dict) else []:
                number = next((i for i, raw in enumerate(_lines(text), start=1)
                               if f'"{dep}"' in raw), None)
                mark(dep, rel, number, _lines(text)[number - 1].strip() if number else dep)
        elif name == "go.mod":
            for number, raw in enumerate(_lines(text), start=1):
                m = re.match(r"^\s*(?:require\s+)?([a-z0-9.-]+\.[a-z]+/\S+)\s+v\S+", raw)
                if m:
                    mark(m.group(1), rel, number, raw.strip())
        elif name == "Gemfile":
            for number, raw in enumerate(_lines(text), start=1):
                m = re.match(r"""^\s*gem\s+['"]([^'"]+)['"]""", raw)
                if m:
                    mark(m.group(1), rel, number, raw.strip())
    return sorted(found.items())


class _EnvEntry(BaseModel):
    name: str
    value: str
    path: str
    line: int


_ENV_LINE = re.compile(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*?)\s*$")


def _env_example(root: Path, directory: str) -> list[_EnvEntry]:
    """The names (and example values) of the example env file in one directory."""
    for name in ENV_EXAMPLES:
        rel = posixpath.join(directory, name) if directory else name
        text = _read_in(root, rel)
        if text is None:
            continue
        out = []
        for number, raw in enumerate(_lines(text), start=1):
            if raw.strip().startswith("#"):
                continue
            m = _ENV_LINE.match(raw)
            if not m:
                continue
            value = m.group(2)
            if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
                value = value[1:-1]
            out.append(_EnvEntry(name=m.group(1), value=value, path=rel, line=number))
        return out
    return []


# ── what looks like a credential ────────────────────────────────────────────────────────────────

#: Words in a variable's NAME that say its value is a secret. Matched as whole words of the name
#: (`JWT_SECRET`, `SECRET_KEY_BASE`, `POSTGRES_PASSWORD`), so `KEYBOARD_LAYOUT` is not one.
_SECRET_WORDS = frozenset({"SECRET", "PASSWORD", "PASSWD", "PASS", "TOKEN", "KEY", "APIKEY",
                           "CREDENTIAL", "CREDENTIALS", "PRIVATE"})
_USERINFO = re.compile(r"(?i)^[a-z][a-z0-9+.-]*://[^/@\s:]*:([^/@\s]+)@")


#: A LINE that carries a secret inline — `--password=…`, `API_TOKEN=… node server.js`, a password
#: inside an address. A line is what an excerpt quotes and what a drafted `CMD` copies, so such a
#: line is neither quoted nor copied: it is said to be there, by `file:line`.
_INLINE_SECRET = re.compile(
    r"(?i)(?:^|[\s\"'\[,-])[A-Z0-9_-]*(?:SECRET|PASSWORD|PASSWD|TOKEN|API_?KEY|PRIVATE_?KEY)"
    r"[A-Z0-9_-]*\s*[=:]\s*[^\s$\"'\],]")
_INLINE_USERINFO = re.compile(r"(?i)[a-z][a-z0-9+.-]*://[^/@\s:]*:[^/@\s$]+@")


def carries_credential(line: str) -> bool:
    """Whether a line of the client's (a Dockerfile's, a Procfile's) holds a literal secret."""
    return bool(_INLINE_SECRET.search(line or "") or _INLINE_USERINFO.search(line or ""))


#: What an excerpt says in place of a line that holds a secret.
NOT_QUOTED = "(not quoted: it carries what looks like a credential)"


def quoted(line: str) -> str:
    """A line as an excerpt may quote it — never with a secret in it."""
    return NOT_QUOTED if carries_credential(line) else line


def credential(name: str, value: str) -> str:
    """Why a LITERAL looks like a credential, or "" when it does not. A reference (`${X}`) is not
    a literal: its value lives wherever the name is resolved, never in this file."""
    literal = str(value or "")
    if not literal.strip() or "${" in literal:
        return ""
    m = _USERINFO.match(literal)
    if m and "$" not in m.group(1):
        return "a password inside the address"
    words = {w for w in re.split(r"[^A-Za-z0-9]+", name.upper()) if w}
    if words & _SECRET_WORDS:
        return "its name says it holds a secret"
    return ""


# ── (a) a compose file ──────────────────────────────────────────────────────────────────────────


class _ComposeLoader(_LineLoader):
    """`infer.py`'s line-keeping loader plus the two tags the compose spec defines. `!reset` and
    `!override` only remove or replace keys while the CLI merges files, so they are read as the
    value they carry; every other tag is refused by the safe loader underneath."""


def _as_is(loader: yaml.SafeLoader, node: yaml.Node):
    if isinstance(node, yaml.MappingNode):
        return loader.construct_mapping(node, deep=True)
    if isinstance(node, yaml.SequenceNode):
        return loader.construct_sequence(node, deep=True)
    return loader.construct_scalar(node)


_ComposeLoader.add_constructor("!reset", _as_is)
_ComposeLoader.add_constructor("!override", _as_is)


def _line(value: Any) -> int | None:
    return getattr(value, "line", None) or None


def _env_items(env: Any) -> list[tuple[str, str, int | None]]:
    """(name, value, line) of a service's `environment:`, map or list form."""
    out: list[tuple[str, str, int | None]] = []
    if isinstance(env, dict):
        for k, v in env.items():
            out.append((str(k), "" if v is None else str(v), _line(v) or _line(k)))
    elif isinstance(env, list):
        for item in env:
            if isinstance(item, str) and "=" in item:
                k, _, v = item.partition("=")
                out.append((k, v, _line(item)))
    return out


def _container_port(entry: Any) -> tuple[int | None, int | None]:
    """The CONTAINER side of one `ports:` entry, and its line: `"8000:8000"` → 8000,
    `"127.0.0.1:5432:5432"` → 5432, `3000` → 3000, `{target: 80}` → 80."""
    if isinstance(entry, dict):
        target = entry.get("target")
        return (int(target) if str(target).isdigit() else None), _line(entry.get("target"))
    text = str(entry).split("/", 1)[0]
    last = text.rsplit(":", 1)[-1]
    port = last.split("-", 1)[0]
    return (int(port) if port.isdigit() else None), _line(entry)


def _image_name(image: str) -> str:
    """`ghcr.io/acme/api:latest` → `api`; `postgres:16` → `postgres`."""
    bare = image.split("@", 1)[0]
    last = bare.rsplit("/", 1)[-1]
    return last.split(":", 1)[0].lower()


_ONE_SHOT = re.compile(r"(?i)\b(migrate|seed|loaddata|db:migrate|db:seed|db:prepare|"
                       r"upgrade\s+head|alembic)\b")


def _hosts(value: str, key: str) -> list[tuple[str, str]]:
    """(host, scheme) for every address one literal names — the plan's rule, with the scheme
    kept, because the scheme is what says which store could stand in for it."""
    literal = _REF.sub("", value)
    out = []
    for m in _URL_HOST.finditer(literal):
        scheme = m.group(0).split("://", 1)[0].lower()
        out.append((m.group(1).lower(), scheme))
    if not out and key.upper().endswith("HOST") and re.fullmatch(r"[A-Za-z0-9.-]+", literal):
        out.append((literal.lower(), ""))
    return out


def _free(name: str, taken: set[str]) -> str:
    if name not in taken:
        return name
    n = 2
    while f"{name}{n}" in taken:
        n += 1
    return f"{name}{n}"


def _store_service(store: Store, *, taken: set[str], evidence: list[Evidence]) -> Service:
    """A store, drafted: always INFERRED — a dependency marker implies it, nothing states it —
    under a name no other service has, with its healthcheck and a volume of its own."""
    name = _free(store.service, taken)
    taken.add(name)
    return Service(
        name=name, kind="store", tier=INFERRED, evidence=evidence, image=store.image,
        environment=[Env(name=k, value=v, tier=INFERRED, evidence=evidence) for k, v in
                     store.env.items()],
        healthcheck=list(store.healthcheck), volume=f"{name}-data:{store.data}", store=store.kind)


def _from_compose(root: Path, tree: _Tree, found: list[str], out: PreviewProposal,
                  dockerfiles: dict[str, _Dockerfile]) -> None:
    if len(found) > 1:
        out.compose = Proposal(
            field="preview.compose", value=None, confidence=UNKNOWN,
            evidence=[Evidence(path=f) for f in found],
            note=f"which of {_and(found)} describes the product? A preview reads the one "
                 f"`preview.compose` names — answer with `--set preview.compose=<file>`.")
        out.questions.append(out.compose.note)
        return
    rel = found[0]
    text = _read_in(root, rel) or ""
    try:
        doc = yaml.load(text, Loader=_ComposeLoader)  # noqa: S506 - a SafeLoader subclass
    except yaml.YAMLError as exc:
        problem = getattr(exc, "problem", None) or str(exc).splitlines()[0]
        out.compose = Proposal(field="preview.compose", value=None, confidence=UNKNOWN,
                               evidence=[Evidence(path=rel)],
                               note=f"`{rel}` could not be read as a compose file ({problem}) — "
                                    f"fix it, and propose again.")
        out.questions.append(out.compose.note)
        return
    services = (doc or {}).get("services") if isinstance(doc, dict) else None
    services = services if isinstance(services, dict) else {}
    out.read.append(rel)
    names = {str(n) for n in services}
    taken = set(names)
    stores = {str(n) for n, s in services.items()
              if isinstance(s, dict) and isinstance(s.get("image"), str)
              and _image_name(s["image"]) in _STORE_IMAGES}
    candidates: list[str] = []
    published: dict[str, int] = {}
    patches: dict[str, Service] = {}
    substitutes: dict[str, Service] = {}
    compose_dir = posixpath.dirname(rel)
    for raw_name, svc in services.items():
        name = str(raw_name)
        if not isinstance(svc, dict):
            continue
        line = _line(raw_name)
        out.existing.append(_existing(name, line, svc, compose_dir, dockerfiles,
                                      store=name in stores))
        # `expose`: the container side of what the service publishes, never a store's
        for entry in svc.get("ports") or []:
            port, at = _container_port(entry)
            if port and name not in stores and name not in out.expose:
                published[name] = port
                out.expose[name] = Proposal(
                    field=f"preview.expose.{name}", value=port, confidence=INFERRED,
                    evidence=[Evidence(path=rel, line=at or line,
                                       excerpt=f"{name} publishes {port}")],
                    note=f"`{name}` publishes container port {port}; a preview opens it on a "
                         f"host of its own instead of a published port")
        if "build" not in svc and isinstance(svc.get("image"), str) and name not in stores:
            candidates.append(name)
        command = svc.get("command")
        shown = " ".join(map(str, command)) if isinstance(command, list) else str(command or "")
        if _ONE_SHOT.search(shown):
            out.notes.append(f"`{name}` looks like it runs once and finishes ({rel}:"
                             f"{_line(command) or line}) — a preview runs it, and reads its "
                             f"exit 0 as done, not as a failure.")
        env = _env_items(svc.get("environment"))
        for key, value, at in env:
            why = credential(key, value)
            if why:
                out.flags.append(Flag(path=rel, line=at, service=name, name=key, why=why))
        for arg, value, at in _env_items((svc.get("build") or {}).get("args")
                                         if isinstance(svc.get("build"), dict) else None):
            why = credential(arg, value)
            if why:
                out.flags.append(Flag(path=rel, line=at, service=name, name=arg, why=why))
        # an env file the repository does not commit: its names are the registry's
        env_file = svc.get("env_file")
        for item in [env_file] if isinstance(env_file, str | dict) else (env_file or []):
            path = item.get("path") if isinstance(item, dict) else item
            if not isinstance(path, str):
                continue
            target = posixpath.normpath(posixpath.join(posixpath.dirname(rel), path))
            if (root / target).is_file():
                continue
            example = _env_example(root, posixpath.dirname(target))
            for entry in example:
                out.registry.append(RegistryName(
                    service=name, name=entry.name, path=entry.path, line=entry.line,
                    why=f"`{name}` reads `{path}`, which the repository does not commit"))
            if not example:
                out.notes.append(f"`{name}` reads `{path}` ({rel}:{_line(path) or line}), which "
                                 f"the repository does not commit and no `.env.example` "
                                 f"describes — its names come only from the registry's "
                                 f"`preview.env`.")
        # an address a preview cannot reach (S9)
        for key, value, at in env:
            for host, scheme in _hosts(value, key):
                if host in names or host in _LOCAL_HOSTS:
                    continue
                store = next((s for s in STORES.values() if scheme in s.schemes), None)
                where = f"{rel}:{at}" if at else rel
                if store is None:
                    out.questions.append(
                        f"which service stands in for `{host}` ({where}, `{name}`'s `{key}`)? A "
                        f"preview reaches nothing outside itself — add one to "
                        f"`{DRAFT_COMPOSE}`, or have the operator name a non-production value "
                        f"and open egress: `openfactory project set-preview <project> --env "
                        f"{name}={key}=<WORKER_NAME> --network <network>`.")
                    continue
                sub = substitutes.get(store.kind)
                if sub is None:
                    ev = [Evidence(path=rel, line=at, excerpt=f"{key} names {scheme}://{host}")]
                    sub = _store_service(store, taken=taken, evidence=ev)
                    substitutes[store.kind] = sub
                patch = patches.setdefault(name, Service(
                    name=name, kind="patch", tier=INFERRED,
                    evidence=[Evidence(path=rel, line=line, excerpt=f"{name}:")]))
                patch.environment.append(Env(
                    name=key, value=store.address(sub.name), tier=INFERRED,
                    evidence=[Evidence(path=rel, line=at, excerpt=f"{key} names {scheme}://{host}")],
                    note=f"re-pointed from `{host}` at the drafted `{sub.name}`", needs=[sub.name]))
                if sub.name not in patch.depends_on:
                    patch.depends_on.append(sub.name)
                out.notes.append(
                    f"`{name}` reaches `{host}` ({where}), which a preview cannot: it reaches "
                    f"nothing outside itself. Drafted here: a fresh `{sub.name}` ({store.image}) "
                    f"with `{key}` pointed at it. The other way is the operator's: name a "
                    f"NON-PRODUCTION value and open egress — `openfactory project set-preview "
                    f"<project> --env {name}={key}=<WORKER_NAME> --network <network>`.")

    # S2: a service that only names a published image, and a Dockerfile here that builds it
    built = _match_images(candidates, published, dockerfiles, services, rel, out)
    for name, svc in sorted(built.items()):
        patch = patches.setdefault(name, Service(name=name, kind="patch", tier=svc.tier,
                                                 evidence=[]))
        patch.context, patch.dockerfile = svc.context, svc.dockerfile
        patch.tier = weakest(patch.tier, svc.tier) if patch.environment else svc.tier
        patch.evidence = svc.evidence + patch.evidence
        patch.quoted = svc.quoted
        patch.notes = svc.notes + patch.notes
    out.services = [patches[n] for n in sorted(patches)] + \
        [substitutes[k] for k in sorted(substitutes)]
    files = [rel]
    tier = OBSERVED
    if out.services:
        files.append(DRAFT_COMPOSE)
        out.overrides = [rel]
        tier = weakest(*(s.tier for s in out.services))
    out.compose = Proposal(field="preview.compose", value=files, confidence=OBSERVED,
                           evidence=[Evidence(path=rel)],
                           note=(f"the team's own `{rel}`" + (
                               f", then `{DRAFT_COMPOSE}` ({tier}): relative paths in it "
                               f"resolve against `{rel}`'s directory, as the compose CLI "
                               f"resolves every file it merges" if out.services else "")))
    # the data a store holds is migrated and seeded somehow; nothing in a compose file says how
    for name, svc in services.items():
        name = str(name)
        if name in stores or not isinstance(svc, dict):
            continue
        deps = svc.get("depends_on")
        deps = list(deps) if isinstance(deps, dict | list) else []
        deps += list(patches.get(name, Service(name=name, kind="patch", tier=UNKNOWN)).depends_on)
        if any(str(d) in stores or str(d) in {s.name for s in substitutes.values()}
               for d in deps):
            _ask_data(out, name, [Evidence(path=rel, line=_line(_key(services, name)),
                                           excerpt=f"{name}:")])


def _existing(name: str, line: int | None, svc: dict, compose_dir: str,
              dockerfiles: dict[str, _Dockerfile], *, store: bool) -> Existing:
    build = svc.get("build")
    context = build if isinstance(build, str) else (
        build.get("context") if isinstance(build, dict) else None)
    out = Existing(name=name, line=line, store=store,
                   image=str(svc.get("image")) if isinstance(svc.get("image"), str) else "")
    if isinstance(context, str):
        named = (build.get("dockerfile") if isinstance(build, dict) else None) or "Dockerfile"
        out.context = posixpath.normpath(posixpath.join(compose_dir or ".", context))
        out.dockerfile = str(named)
        df = dockerfiles.get(posixpath.normpath(posixpath.join(out.context, str(named))))
        if df is not None:
            out.quoted = [*df.froms, *([df.start] if df.start else [])]
    for vol in svc.get("volumes") or []:
        source = vol.split(":", 1)[0] if isinstance(vol, str) and ":" in vol else (
            vol.get("source") if isinstance(vol, dict) and vol.get("type") == "bind" else "")
        if isinstance(source, str) and source[:1] in "./~":
            out.binds.append(str(vol) if isinstance(vol, str) else f"{source}:{vol.get('target')}")
    return out


def _key(services: dict, name: str) -> Any:
    """The mapping key a service was read under — it carries the line the name is on."""
    return next((k for k in services if str(k) == name), name)


def _match_images(candidates: list[str], published: dict[str, int],
                  dockerfiles: dict[str, _Dockerfile], services: dict, rel: str,
                  out: PreviewProposal) -> dict[str, Service]:
    """Which image-only service each Dockerfile here builds — by the port it EXPOSEs matching the
    one the service publishes, or the image's own name matching the Dockerfile's directory. One
    match is inferred; anything else is asked, never picked."""
    compose_dir = posixpath.dirname(rel) or "."
    # A DOCKERFILE A SERVICE ALREADY BUILDS IS NOT A CANDIDATE: S9's `api: build: .` owns the root
    # Dockerfile, and "one Dockerfile, one image-only service" would otherwise hand it to `web`.
    owned = set()
    for svc in services.values():
        build = svc.get("build") if isinstance(svc, dict) else None
        context = build if isinstance(build, str) else (
            build.get("context") if isinstance(build, dict) else None)
        if isinstance(context, str):
            named = (build.get("dockerfile") if isinstance(build, dict) else None) or "Dockerfile"
            owned.add(posixpath.normpath(posixpath.join(compose_dir, context, str(named))))
    usable = {path: df for path, df in dockerfiles.items()
              if path.count("/") <= 1 and posixpath.normpath(path) not in owned}
    if not candidates or not usable:
        if candidates and not any("build" in (s or {}) for s in services.values()
                                  if isinstance(s, dict)):
            out.questions.append(
                f"every service in `{rel}` runs a published image and none is built from this "
                f"repository, so a change here would not be in a preview — which service does "
                f"this repository build, and from which Dockerfile?")
        return {}
    built: dict[str, Service] = {}
    for path, df in sorted(usable.items()):
        directory = posixpath.dirname(path)
        slug = _slug(directory) if directory else _slug(out.name)
        by_port = [c for c in candidates if df.expose and published.get(c) == df.expose]
        by_name = [c for c in candidates
                   if _slug(_image_name(str(services[_key(services, c)].get("image")))) == slug]
        match = by_port if len(by_port) == 1 else by_name if len(by_name) == 1 else []
        if len(usable) == 1 and len(candidates) == 1:
            match = candidates
        if len(match) != 1:
            out.questions.append(
                f"which service does `{path}` build: {_and(candidates, 'or')}? Nothing here "
                f"ties it to one — add `build: {{context: {_ctx(compose_dir, directory)}, "
                f"dockerfile: "
                f"{Path(path).name}}}` to that service in `{DRAFT_COMPOSE}`.")
            continue
        name = match[0]
        why = []
        ev = [Evidence(path=path, line=df.froms[0].line if df.froms else None,
                       excerpt=df.froms[0].excerpt if df.froms else "")]
        if df.expose and published.get(name) == df.expose and df.expose_evidence:
            ev.append(df.expose_evidence)
            why.append(f"`{path}` exposes {df.expose}, the port `{name}` publishes")
        elif len(by_name) == 1:
            why.append(f"`{name}`'s image is named like `{directory or out.name}`")
        image = services[_key(services, name)].get("image")
        ev.append(Evidence(path=rel, line=_line(image), excerpt=f"{name} runs {image}"))
        built[name] = Service(
            name=name, kind="patch", tier=INFERRED, evidence=ev,
            context=_ctx(compose_dir, directory), dockerfile=Path(path).name,
            quoted=[*df.froms, *([df.start] if df.start else [])],
            notes=[(("; ".join(why) + " — ") if why else "") + "so a change here is in the "
                   "preview, built from the change instead of pulled"])
    return built


def _ctx(compose_dir: str, directory: str) -> str:
    """A directory of the repository as the compose CLI resolves it from the FIRST file's
    directory (measured on v2.32.4: an override's paths do NOT resolve against its own)."""
    return posixpath.relpath(directory or ".", compose_dir or ".")


def _ask_data(out: PreviewProposal, name: str, evidence: list[Evidence]) -> None:
    if name in out.data:
        return
    out.data[name] = Proposal(
        field=f"preview.data.{name}", value=None, confidence=UNKNOWN, evidence=evidence,
        note=f"how is `{name}`'s data migrated and seeded? A preview starts every store empty. "
             f"Answer with `--set preview.data.{name}=\"<command>\"` (a command run inside "
             f"`{name}` once it is up).")


# ── (b) Dockerfiles ─────────────────────────────────────────────────────────────────────────────

#: Prefixes a front-end bundler exposes to the BROWSER; such a variable is baked at build time.
_PUBLIC = ("NEXT_PUBLIC_", "VITE_", "REACT_APP_", "NUXT_PUBLIC_", "PUBLIC_", "EXPO_PUBLIC_",
           "GATSBY_")
_SSR_FILES = ("next.config.js", "next.config.mjs", "next.config.ts", "nuxt.config.js",
              "nuxt.config.ts")


def _ssr_marker(root: Path, tree: _Tree, directory: str) -> Evidence | None:
    """A file saying the service RENDERS ON ITS SERVER, so it calls other services from inside
    the preview as well as from the browser."""
    prefix = f"{directory}/" if directory else ""
    for name in _SSR_FILES:
        if f"{prefix}{name}" in tree.files:
            return Evidence(path=f"{prefix}{name}")
    if f"{prefix}manage.py" in tree.files and any(
            f.startswith(f"{prefix}") and "/templates/" in f"/{f[len(prefix):]}" for f in
            tree.files):
        return Evidence(path=f"{prefix}manage.py")
    return None


def _local_port(value: str) -> tuple[bool, int | None, str]:
    """Whether a value points at THIS machine, the port it names, and its scheme."""
    m = re.match(r"(?i)^([a-z][a-z0-9+.-]*)://(?:[^@/]*@)?([^:/?#]+)(?::(\d+))?", value)
    if not m:
        return False, None, ""
    host = m.group(2).lower()
    return host in _LOCAL_HOSTS, (int(m.group(3)) if m.group(3) else None), m.group(1).lower()


def _wire(out: PreviewProposal, svc: Service, entries: list[_EnvEntry],
          stores: dict[str, Service], ports: dict[str, int], ssr: Evidence | None) -> None:
    """The service's `environment:` from its `.env.example`: names read there, values that are
    safe to write, wiring to the other drafted services, and every secret left for the registry.

    `stores` is store kind → the drafted store service; `ports` the other drafted services'
    EXPOSE."""
    provided: set[str] = set()
    for entry in entries:
        where = Evidence(path=entry.path, line=entry.line, excerpt=f"{entry.name}=…")
        local, port, scheme = _local_port(entry.value)
        store = next((STORES[k] for k in stores if scheme in STORES[k].schemes), None)
        if store is not None and local:
            host = stores[store.kind].name
            svc.environment.append(Env(
                name=entry.name, value=store.address(host), tier=INFERRED, evidence=[where],
                note=f"named at {entry.path}:{entry.line}; points at the drafted `{host}`",
                needs=[host]))
            provided.add(store.kind)
            continue
        why = credential(entry.name, entry.value)
        if why:
            out.registry.append(RegistryName(service=svc.name, name=entry.name, path=entry.path,
                                             line=entry.line,
                                             why=f"`{entry.name}` looks like a secret ({why})"))
            continue
        if local:
            targets = sorted(n for n, p in ports.items() if port is not None and p == port)
            if len(targets) != 1:
                out.questions.append(
                    f"`{svc.name}` reads `{entry.name}` ({entry.path}:{entry.line}), which "
                    f"points at this machine — in a preview nothing listens there. Which service "
                    f"should it reach? Add it to `{DRAFT_COMPOSE}`.")
                continue
            target = targets[0]
            if entry.name.upper().startswith(_PUBLIC):
                svc.environment.append(Env(
                    name=entry.name, value="${OPENFACTORY_PREVIEW_URL_" + url_var(target) + "}",
                    tier=INFERRED, evidence=[where], build_arg=True, needs=[target],
                    note=f"the browser's address of `{target}` (port {port} matches its EXPOSE), "
                         f"also a build argument so a bundler bakes it"))
            elif ssr is not None:
                svc.environment.append(Env(
                    name=entry.name,
                    value="${OPENFACTORY_PREVIEW_INTERNAL_URL_" + url_var(target) + "}",
                    tier=INFERRED, evidence=[where, ssr], needs=[target],
                    note=f"`{target}`'s address inside the preview — `{ssr.path}` says "
                         f"`{svc.name}` renders on its server"))
            else:
                out.questions.append(
                    f"does `{svc.name}` call `{target}` at `{entry.name}` ({entry.path}:"
                    f"{entry.line}) from the browser or from its server? Nothing read says — "
                    f"from the browser it is `${{OPENFACTORY_PREVIEW_URL_{url_var(target)}}}`, "
                    f"from the server `${{OPENFACTORY_PREVIEW_INTERNAL_URL_{url_var(target)}}}`.")
            continue
        if not entry.value:
            out.registry.append(RegistryName(service=svc.name, name=entry.name, path=entry.path,
                                             line=entry.line,
                                             why=f"`{entry.name}` has no example value"))
            continue
        svc.environment.append(Env(name=entry.name, value=entry.value, tier=OBSERVED,
                                   evidence=[Evidence(path=entry.path, line=entry.line,
                                                      excerpt=f"{entry.name}={entry.value}")]))
    for kind, drafted in sorted(stores.items()):
        if kind in provided:
            continue
        store = STORES[kind]
        svc.environment.append(Env(
            name=store.var, value=store.address(drafted.name), tier=INFERRED,
            evidence=list(drafted.evidence), note="confirm your application reads this name",
            needs=[drafted.name]))
    svc.depends_on = sorted({s.name for s in stores.values()})


def _from_dockerfiles(root: Path, tree: _Tree, out: PreviewProposal,
                      dockerfiles: dict[str, _Dockerfile]) -> None:
    by_dir: dict[str, list[str]] = {}
    for path in sorted(dockerfiles):
        depth = path.count("/")
        if depth > 1:
            out.questions.append(
                f"`{path}` is deeper than one directory, so it is not drafted as a service — is "
                f"it part of the product a person opens, or tooling? If it is the product, add it "
                f"to `{DRAFT_COMPOSE}`.")
            continue
        by_dir.setdefault(posixpath.dirname(path), []).append(path)
    subdirs = sorted(d for d in by_dir if d)
    taken: set[str] = set()
    drafted: list[tuple[str, str, _Dockerfile]] = []
    for directory in sorted(by_dir):
        files = by_dir[directory]
        if len(files) > 1:
            name = _slug(directory) if directory else _slug(out.name)
            out.questions.append(
                f"which Dockerfile runs `{name}` in a preview: {_and(files, "or")}? Two in one "
                f"directory are the team's to choose between — add the one to "
                f"`{DRAFT_COMPOSE}`.")
            continue
        if not directory and subdirs:
            out.questions.append(
                f"does the root `{files[0]}` run a service of its own beside "
                f"{_and([_slug(d) for d in subdirs])}? It is not drafted: a root Dockerfile beside "
                f"per-directory ones is usually a combined image or a tool.")
            continue
        name = _slug(directory) if directory else (_slug(out.name) or "app")
        taken.add(name)
        drafted.append((name, directory, dockerfiles[files[0]]))
    ports = {name: df.expose for name, _, df in drafted if df.expose}
    stores_of: dict[str, dict[str, Service]] = {}
    store_services: dict[str, Service] = {}
    for name, directory, df in drafted:
        out.read.append(df.path)
        mine: dict[str, Service] = {}
        for kind, ev in _dependencies(root, tree, directory):
            store = store_services.get(kind)
            if store is None:
                store = _store_service(STORES[kind], taken=taken, evidence=[ev])
                store_services[kind] = store
            elif ev.path not in {e.path for e in store.evidence}:
                store.evidence.append(ev)
            mine[kind] = store
            out.read.append(ev.path)
        stores_of[name] = mine
    out.services = []
    for name, directory, df in drafted:
        context = posixpath.join("..", directory) if directory else ".."
        svc = Service(
            name=name, kind="build", tier=OBSERVED,
            evidence=[df.froms[0] if df.froms else Evidence(path=df.path)],
            context=context, dockerfile=Path(df.path).name,
            quoted=[*df.froms, *([df.start] if df.start else [])])
        if not directory:
            svc.notes.append(f"`{name}` builds from the whole repository (context `.`), so any "
                             f"change to it rebuilds `{name}`")
        others = {n: p for n, p in ports.items() if n != name}
        _wire(out, svc, _env_example(root, directory), stores_of[name], others,
              _ssr_marker(root, tree, directory))
        out.services.append(svc)
        if df.expose and df.expose_evidence:
            out.expose[name] = Proposal(field=f"preview.expose.{name}", value=df.expose,
                                        confidence=OBSERVED, evidence=[df.expose_evidence])
        else:
            out.expose[name] = Proposal(
                field=f"preview.expose.{name}", value=None, confidence=UNKNOWN,
                evidence=[Evidence(path=df.path)],
                note=f"which port does `{name}` listen on inside its container? `{df.path}` has "
                     f"no `EXPOSE`. Answer with `--set preview.expose.{name}=<port>`.")
        if stores_of[name]:
            _ask_data(out, name, [s.evidence[0] for s in stores_of[name].values()])
    out.services += [store_services[k] for k in sorted(store_services)]
    if out.services:
        out.compose = Proposal(
            field="preview.compose", value=[DRAFT_COMPOSE],
            confidence=weakest(*(s.tier for s in out.services if s.kind == "build")),
            evidence=[s.evidence[0] for s in out.services if s.kind == "build"],
            note=f"drafted from {_and(sorted(df.path for _, _, df in drafted))}; relative paths "
                 f"in it resolve against `.openfactory/`, so the repository root is `..`")


# ── (c) nothing to build from: a Dockerfile, only when its start is anchored ────────────────────

_CONVENTION_PORTS = (
    (re.compile(r"\brunserver\b"), 8000), (re.compile(r"\bgunicorn\b"), 8000),
    (re.compile(r"\buvicorn\b"), 8000), (re.compile(r"\bflask\s+run\b"), 5000),
    (re.compile(r"\b(?:rails\s+s(?:erver)?|puma)\b"), 3000),
    (re.compile(r"\b(?:next\s+start|npm\s+start|node)\b"), 3000),
)
_LITERAL_PORT = re.compile(r"(?:--port[= ]|-p\s+|--bind[= ]\S*?:|:)(\d{2,5})\b")


_NODE_HEADS = frozenset({"node", "npm", "yarn", "pnpm", "npx", "next", "nuxt"})
_PYTHON_HEADS = frozenset({"python", "python3", "gunicorn", "uvicorn", "flask", "celery",
                           "daphne", "hypercorn", "waitress-serve"})


def _stack_of(tree: _Tree, command: str) -> str:
    """Which runtime a start command needs: its head when that says, else the one marker at the
    root — and "" when neither does, so no base image is guessed."""
    head = (command.split() or [""])[0]
    if head in _NODE_HEADS:
        return "node"
    if head in _PYTHON_HEADS:
        return "python"
    python = any(f in tree.files for f in ("manage.py", "pyproject.toml", "requirements.txt"))
    node = "package.json" in tree.files
    return "python" if python and not node else "node" if node and not python else ""


def _start(root: Path, tree: _Tree) -> tuple[str | list[str], str, Evidence, str] | None:
    """(command, tier, evidence, stack) for the one start command a file here ANCHORS — or None,
    and then nothing is drafted."""
    text = _read_in(root, "Procfile") if "Procfile" in tree.files else None
    for number, raw in enumerate(_lines(text or ""), start=1):
        m = re.match(r"^\s*web\s*:\s*(.+?)\s*$", raw)
        if m:
            command = m.group(1)
            return command, OBSERVED, Evidence(path="Procfile", line=number,
                                               excerpt=quoted(raw.strip())), \
                _stack_of(tree, command)
    if "package.json" in tree.files:
        text = _read_in(root, "package.json") or ""
        try:
            doc = json.loads(text)
        except ValueError:
            doc = {}
        scripts = doc.get("scripts") if isinstance(doc, dict) else None
        if isinstance(scripts, dict) and isinstance(scripts.get("start"), str):
            number = next((i for i, raw in enumerate(_lines(text), start=1) if '"start"' in raw),
                          None)
            return ["npm", "start"], OBSERVED, Evidence(
                path="package.json", line=number,
                excerpt=quoted(_lines(text)[number - 1].strip()) if number else ""), "node"
    for name in ("Makefile", "justfile"):
        if name not in tree.files:
            continue
        lines = _lines(_read_in(root, name) or "")
        for number, raw in enumerate(lines, start=1):
            m = re.match(r"^(run|serve|start)\s*:(?!=)", raw)
            if not m:
                continue
            recipe = []
            for follow in lines[number:]:
                if not follow.startswith(("\t", "    ")) or not follow.strip():
                    break
                recipe.append(follow.strip().lstrip("@-+").strip())
            if recipe:
                command = " && ".join(recipe)
                return command, OBSERVED, Evidence(path=name, line=number,
                                                   excerpt=quoted(raw.strip())), \
                    _stack_of(tree, command)
    if "manage.py" in tree.files:
        return (["python", "manage.py", "runserver", "0.0.0.0:8000"], INFERRED,
                Evidence(path="manage.py", excerpt="manage.py"), "python")
    return None


def _base_image(root: Path, tree: _Tree, stack: str) -> tuple[str, Evidence] | None:
    """The official image for the version a marker names — or None, and then nothing is drafted:
    a guessed runtime version is the kind of line that builds and then misbehaves."""
    if stack == "python":
        text = _read_in(root, ".python-version") if ".python-version" in tree.files else None
        if text:
            m = re.match(r"\s*(?:python-)?(\d+\.\d+)", text)
            if m:
                return f"python:{m.group(1)}-slim", Evidence(path=".python-version", line=1,
                                                             excerpt=text.splitlines()[0].strip())
        text = _read_in(root, "pyproject.toml") if "pyproject.toml" in tree.files else None
        for number, raw in enumerate(_lines(text or ""), start=1):
            m = re.match(r"""^\s*requires-python\s*=\s*["'][^0-9]*(\d+\.\d+)""", raw)
            if m:
                return f"python:{m.group(1)}-slim", Evidence(path="pyproject.toml", line=number,
                                                             excerpt=raw.strip())
        text = _read_in(root, "runtime.txt") if "runtime.txt" in tree.files else None
        if text:
            m = re.match(r"\s*python-(\d+\.\d+)", text)
            if m:
                return f"python:{m.group(1)}-slim", Evidence(path="runtime.txt", line=1,
                                                             excerpt=text.splitlines()[0].strip())
    if stack == "node":
        text = _read_in(root, ".nvmrc") if ".nvmrc" in tree.files else None
        if text:
            m = re.match(r"\s*v?(\d+)", text)
            if m:
                return f"node:{m.group(1)}-slim", Evidence(path=".nvmrc", line=1,
                                                           excerpt=text.splitlines()[0].strip())
        text = _read_in(root, "package.json") if "package.json" in tree.files else ""
        try:
            engines = (json.loads(text or "{}").get("engines") or {})
        except (ValueError, AttributeError):
            engines = {}
        node = engines.get("node") if isinstance(engines, dict) else None
        m = re.search(r"(\d+)", str(node or ""))
        if m:
            number = next((i for i, raw in enumerate(_lines(text or ""), start=1)
                           if '"node"' in raw), None)
            return f"node:{m.group(1)}-slim", Evidence(
                path="package.json", line=number,
                excerpt=_lines(text)[number - 1].strip() if number else "")
    return None


def _manifest_setup(root: Path) -> tuple[list[str], list[Evidence]] | None:
    """The `setup:` the manifest already declares — the client's own install step, cited."""
    rel = namespace.MANIFEST
    text = _read_in(root, rel)
    if text is None:
        return None
    try:
        doc = yaml.safe_load(text)
    except yaml.YAMLError:
        return None
    setup = doc.get("setup") if isinstance(doc, dict) else None
    if not isinstance(setup, list) or not setup or not all(isinstance(s, str) for s in setup):
        return None
    number = next((i for i, raw in enumerate(_lines(text), start=1)
                   if re.match(r"^setup\s*:", raw)), None)
    return list(setup), [Evidence(path=rel, line=number, excerpt="setup:")]


def _roots(tree: _Tree) -> tuple[list[str], list[str]]:
    """The repository's own top-level files and directories — what the drafted image copies,
    instead of `COPY . .`. Anything whose name starts with a dot (`.git`, `.env`, `.openfactory`)
    is never one of them."""
    files, dirs = set(), set()
    for rel in tree.files:
        first, _, rest = rel.partition("/")
        if first.startswith("."):
            continue
        (dirs if rest else files).add(first)
    return sorted(files), sorted(dirs)


def _from_nothing(root: Path, tree: _Tree, out: PreviewProposal,
                  setup: Proposal | None) -> None:
    name = _slug(out.name) or "app"
    started = _start(root, tree)
    if started is None:
        markers = [m for m in ("requirements.txt", "pyproject.toml", "package.json", "go.mod",
                               "Gemfile") if m in tree.files]
        out.read += markers
        out.questions.append(
            f"how does `{name}` start? Nothing here says: no compose file, no Dockerfile, and no "
            f"`Procfile` `web:` line, `package.json` `start` script, Makefile `run`/`serve`/"
            f"`start` target or `manage.py` to anchor a drafted one to — so nothing is drafted. "
            f"`--as-card` files this as a card the factory works like any other.")
        return
    command, command_tier, command_ev, stack = started
    out.read.append(command_ev.path)
    if carries_credential(_shown_command(command)):
        # A DRAFTED `CMD` IS A COPY: a secret inline in the line it copies would be baked into a
        # file on a pull request, and into the image's history after that.
        out.questions.append(
            f"the start command at {command_ev.locator} carries what looks like a credential, so "
            f"it is not copied into a drafted Dockerfile — move the value out of the line (the "
            f"operator names it for previews with `openfactory project set-preview`), and propose "
            f"again.")
        return
    base = _base_image(root, tree, stack)
    declared = _manifest_setup(root)
    if declared is not None:
        install, install_tier, install_ev = declared[0], OBSERVED, declared[1]
    elif setup is not None and setup.known and setup.value:
        install, install_tier, install_ev = list(setup.value), setup.confidence, setup.evidence
    else:
        install, install_tier, install_ev = [], UNKNOWN, []
    missing = []
    if base is None:
        missing.append(f"which {stack or 'runtime'} version `{name}` runs on (no "
                       f"`.python-version`, `requires-python`, `.nvmrc` or `engines.node` names "
                       f"one)")
    if not install:
        missing.append(f"how `{name}`'s dependencies are installed (the manifest declares no "
                       f"`setup:`)")
    if base is None or not install:
        out.questions.append(f"a Dockerfile for `{name}` could be drafted from "
                             f"`{command_ev.path}`, but not without knowing "
                             + " and ".join(missing) + ".")
        return
    image, base_ev = base
    out.read.append(base_ev.path)
    shown = _shown_command(command)
    literal = _LITERAL_PORT.search(shown)
    port: int | None = None
    port_tier, port_ev = UNKNOWN, None
    if literal:
        port, port_tier, port_ev = int(literal.group(1)), command_tier, command_ev
    else:
        conv = next((p for pattern, p in _CONVENTION_PORTS if pattern.search(shown)), None)
        if conv:
            port, port_tier, port_ev = conv, INFERRED, command_ev
    files, dirs = _roots(tree)
    draft = DockerfileDraft(
        service=name, path=f"{DRAFT_DIR}/{name}.Dockerfile",
        ignore=f"{DRAFT_DIR}/{name}.Dockerfile.dockerignore", base=image, base_evidence=base_ev,
        copy_files=files, copy_dirs=dirs, install=install, install_tier=install_tier,
        install_evidence=install_ev, command=command, command_tier=command_tier,
        command_evidence=command_ev, port=port, port_tier=port_tier, port_evidence=port_ev,
        reads_port=bool(re.search(r"\$\{?PORT\b", shown)))
    out.dockerfiles.append(draft)
    taken = {name}
    svc = Service(name=name, kind="draft", tier=draft.tier, evidence=[command_ev, base_ev],
                  context="..", dockerfile=draft.path,
                  notes=[f"`{name}` builds from the whole repository (context `.`), so any "
                         f"change to it rebuilds `{name}`"])
    mine: dict[str, Service] = {}
    for kind, ev in _dependencies(root, tree, ""):
        mine[kind] = _store_service(STORES[kind], taken=taken, evidence=[ev])
        out.read.append(ev.path)
    out.services = [svc, *(mine[k] for k in sorted(mine))]
    _wire(out, svc, _env_example(root, ""), mine, {}, _ssr_marker(root, tree, ""))
    if port is not None and port_ev is not None:
        out.expose[name] = Proposal(field=f"preview.expose.{name}", value=port,
                                    confidence=weakest(port_tier, draft.tier),
                                    evidence=[port_ev])
    else:
        out.expose[name] = Proposal(
            field=f"preview.expose.{name}", value=None, confidence=UNKNOWN,
            evidence=[command_ev],
            note=f"which port does `{name}` listen on? `{shown}` names none. Answer with "
                 f"`--set preview.expose.{name}=<port>`.")
    if "manage.py" in tree.files:
        out.data[name] = Proposal(
            field=f"preview.data.{name}", value="python manage.py migrate", confidence=INFERRED,
            evidence=[Evidence(path="manage.py", excerpt="manage.py")],
            note="Django's own migrations; a seed is still yours to add (`&& python manage.py "
                 "loaddata <fixture>`)")
        out.questions.append(f"how is `{name}` seeded with data a person can look at? "
                             f"`python manage.py migrate` makes the tables and leaves them "
                             f"empty.")
    elif mine:
        _ask_data(out, name, [s.evidence[0] for s in mine.values()])
    out.compose = Proposal(field="preview.compose", value=[DRAFT_COMPOSE],
                           confidence=draft.tier, evidence=[command_ev, base_ev],
                           note=f"drafted with `{draft.path}`, from {_and(out.read)}")


# ── the entry point ─────────────────────────────────────────────────────────────────────────────


def _declared(root: Path) -> tuple[dict | None, int | None]:
    text = _read_in(root, namespace.MANIFEST)
    if text is None:
        return None, None
    try:
        doc = yaml.safe_load(text)
    except yaml.YAMLError:
        return None, None
    block = doc.get("preview") if isinstance(doc, dict) else None
    if not isinstance(block, dict):
        return None, None
    number = next((i for i, raw in enumerate(_lines(text), start=1)
                   if re.match(r"^preview\s*:", raw)), None)
    return block, number


def _host_check(root: Path, tree: _Tree) -> str:
    """The framework whose host check a named preview domain must pass, when one is read."""
    if "manage.py" in tree.files:
        return "Django (`ALLOWED_HOSTS`)"
    gemfile = _read_in(root, "Gemfile") if "Gemfile" in tree.files else ""
    if gemfile and re.search(r"""^\s*gem\s+['"]rails['"]""", gemfile, re.M):
        return "Rails (`config.hosts`)"
    return ""


def infer_preview(repo: str | Path, *, tree: _Tree | None = None, setup: Proposal | None = None,
                  name: str = "", max_files: int = 20_000) -> PreviewProposal:
    """Read `repo` and draft how a preview of it would run. Reads files; runs nothing; writes
    nothing; the same repository gives the same object.

    `tree` is `infer`'s own walk when it calls this, so the repository is walked once. `setup` is
    the install step `infer` proposed, used only when the manifest declares none. `name` is the
    repository's short name (`acme/api` → `api`); a root Dockerfile's service is named after it,
    and it defaults to the directory's name."""
    root = Path(repo).expanduser()
    if not root.is_dir():
        raise NotADirectoryError(f"cannot read a repository at {root}: it is not a directory.")
    tree = tree or _tree(root, max_files)
    short = _slug(name or root.resolve().name) or "app"
    out = PreviewProposal(repo=str(root.resolve()), name=short, case="nothing",
                          compose=Proposal(field="preview.compose"),
                          host_check=_host_check(root, tree))
    block, line = _declared(root)
    if block is not None:
        out.case = "declared"
        out.declared = block
        out.compose = Proposal(field="preview", value=block, confidence=OBSERVED,
                               evidence=[Evidence(path=namespace.MANIFEST, line=line,
                                                  excerpt="preview:")],
                               note="the manifest already declares how this repository is "
                                    "previewed — edit it in the repository")
        return out
    dockerfiles = {rel: df for rel in tree.files
                   if _is_dockerfile(Path(rel).name) and not rel.startswith(".openfactory/")
                   and (df := _read_dockerfile(root, rel)) is not None}
    found = [n for n in COMPOSE_NAMES if n in tree.files]
    if found:
        out.case = "compose"
        _from_compose(root, tree, found, out, dockerfiles)
    elif dockerfiles:
        out.case = "dockerfiles"
        _from_dockerfiles(root, tree, out, dockerfiles)
    else:
        _from_nothing(root, tree, out, setup)
        out.case = "draft" if out.dockerfiles else "nothing"
    charts = sorted({posixpath.dirname(f) for f in tree.files
                     if Path(f).name == "Chart.yaml"})
    if charts:
        out.notes.append(f"{_and([c + '/' for c in charts])} "
                         f"{'exists' if len(charts) == 1 else 'exist'}; the core reads no chart "
                         f"— this draft is a development shape for the deployment's own daemon.")
    out.read = sorted(set(out.read))
    out.notes = list(dict.fromkeys(out.notes))
    # A PORT NOBODY STATED COMES FIRST: without it the block cannot be written at all, so it is
    # the question the pull request's first line asks.
    ports = [p.note for _, p in sorted(out.expose.items()) if p.confidence == UNKNOWN and p.note]
    data = [p.note for _, p in sorted(out.data.items()) if p.confidence == UNKNOWN and p.note]
    out.questions = list(dict.fromkeys(q for q in (*ports, *out.questions, *data) if q))
    return out
