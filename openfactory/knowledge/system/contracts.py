"""The system layer's shape: components, the interfaces between them, and what was not derived.

ADR-0052 D17, #268 slice 2. The per-source bundles say what one repository's code does; nothing
said which components the product has, which calls which, which events flow or which database is
shared. This is that record, derived WITHOUT A MODEL from what the repositories declare (OpenAPI,
AsyncAPI, proto, migrations, compose, Kubernetes, Terraform) and published beside the per-source
bundles in the context repository (`knowledge-layer.md` §9's `api.yaml`, `schema.yaml` and
`adr-index.yaml`, finally built — across the sources rather than inside one).

EVERY ENTRY CITES WHERE IT CAME FROM (`Cite`: repository, path, commit, and a line where the
format has one), as every fact in the knowledge layer does (§7): the map says where to look, and a
reader confirms in the file. And WHAT COULD NOT BE DERIVED IS DATA (`NotDerived`), never silence:
a map that omits what it could not read is indistinguishable from one that found nothing there,
which is the failure this whole layer is built against (D21).

NO VALUE OF A VARIABLE IS EVER HELD HERE. A component carries the NAMES of the variables it is
given; a link says which variable declares it and which declared component it points at. The
value was read only to be compared with the names of declared components — a password inside a
connection string, a key in an environment block, a secret's data never reach any field below.

Plain pydantic models, `extra="ignore"` like the rest of the bundle (`knowledge/contracts.py`): a
newer deriver may add a field, and an older reader must degrade rather than crash.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

_MODEL = ConfigDict(extra="ignore", populate_by_name=True)

#: The layer's format version. It numbers what `system.yaml` and its three siblings look like; the
#: module map and the concept bundle number their own.
SYSTEM_VERSION = "1"

# ── what could not be derived: a closed vocabulary, because a reader acts on each differently ────

#: A declared source could not be checked out, so nothing in it was read.
SOURCE_UNREADABLE = "source-unreadable"
#: A file this layer recognises as a declaration and does not read (RAML, a Helm template, a
#: migration written in a programming language, infrastructure declared in code).
UNKNOWN_FORMAT = "unknown-format"
#: A file of a format this layer reads, which did not parse.
PARSE_ERROR = "parse-error"
#: An interface referenced and declared nowhere: a host no source declares, an event received and
#: never sent, a service called over HTTP that describes no API.
NOT_DECLARED = "not-declared"
#: Something that points elsewhere and was not followed: an `include:`, a remote module, a `$ref`
#: to another place, a link out of the repository's tree.
NOT_FOLLOWED = "not-followed"
#: A value this layer never reads, on purpose: a secret's, or an environment file's.
NOT_READ = "not-read"
#: What only running the code would tell: an address the environment supplies when it starts
#: (`${ORDERS_URL}`), SQL a migration builds as it runs, a table named by a variable. The blind
#: spot ADR-0052 names — "reflection, runtime configuration" — said where it is met.
AT_RUN_TIME = "at-run-time"
#: A file bigger than the layer reads.
TOO_LARGE = "too-large"
#: Two declarations answer one question differently, and the map does not choose.
AMBIGUOUS = "ambiguous"
#: The walk of a repository stopped at its ceiling; what lies beyond it was not seen.
TRUNCATED = "truncated"

NOT_DERIVED_KINDS = (SOURCE_UNREADABLE, UNKNOWN_FORMAT, PARSE_ERROR, NOT_DECLARED, NOT_FOLLOWED,
                     NOT_READ, AT_RUN_TIME, TOO_LARGE, AMBIGUOUS, TRUNCATED)


class Cite(BaseModel):
    """Where an entry came from: the repository, the path inside it, the commit it was read at.

    `line` is 1-based where the format has a statement to point at (a `CREATE TABLE`, an `rpc`, a
    Terraform block, a Kubernetes document); 0 means the file as a whole.

    THE COMMIT IS THE ONE THE MAP WAS DERIVED AT. A later commit that changed nothing this layer
    reads does not republish the map (`render.derived_key`), so a cited commit may be older than the
    repository's head — and the file at that commit says what the entry says, which is what a
    citation promises."""

    model_config = _MODEL

    repo: str
    path: str
    commit: str = ""
    line: int = 0


class NotDerived(BaseModel):
    """One thing the layer could not establish, with why. `kind` is one of `NOT_DERIVED_KINDS`."""

    model_config = _MODEL

    kind: str
    detail: str
    repo: str = ""
    path: str = ""


class SourceRead(BaseModel):
    """One declared source, and what became of it: read at a commit, or not read, with why."""

    model_config = _MODEL

    repo: str
    commit: str = ""
    #: how many declaration files of this source were read — the denominator of what it says
    files: int = 0
    #: directories its checkout did not bring: each holds nothing but weight (pictures, fonts,
    #: archives, binaries), which no declaration is — said so the reader knows what was not walked
    left_out: list[str] = Field(default_factory=list)
    #: why it could not be read; "" when it was
    missing: str = ""


class Component(BaseModel):
    """One part of the product that runs: a service, a database, a broker, a cache.

    NAMED WHERE IT IS DEPLOYED — a compose service, a Kubernetes workload — and failing any
    deployment, by the repository that declares its interfaces (`kind: repository`, which says
    exactly that: nothing in the product's sources deploys it). One name is one component: what
    compose and Kubernetes each declare under the same name is cited by both.

    `repo` and `code` say where its code lives, when a declaration says so (`code_by`): a build
    context that resolves into a source, or an image named like one. "" when nothing does."""

    model_config = _MODEL

    name: str
    #: service | database | broker | cache | search | repository
    kind: str
    repo: str = ""
    code: str = ""
    #: `build-context` | `image` | "" — how `repo`/`code` were established
    code_by: str = ""
    #: the image's name as declared; an image reference carries no credential
    image: str = ""
    #: the start order the deployment declares — not an interface, and kept apart from `links`
    depends_on: list[str] = Field(default_factory=list)
    #: the NAMES of the variables it is given. Never a value (see the module's docstring).
    env: list[str] = Field(default_factory=list)
    declared_by: list[Cite] = Field(default_factory=list)


class Link(BaseModel):
    """One declared interface between two components: `from` talks to `to`.

    `kind` is `http`, `grpc`, `event`, `database`, `broker`, `cache`, `search` or `network` (an
    address with nothing saying what is spoken over it). `via` is the declaration that says so, by
    NAME: `env ORDERS_URL`, `channel order.placed`."""

    model_config = _MODEL

    from_: str = Field(alias="from")
    to: str
    kind: str
    via: str
    sources: list[Cite] = Field(default_factory=list)


class Operation(BaseModel):
    """One HTTP operation an API describes."""

    model_config = _MODEL

    method: str
    path: str
    operation_id: str = ""
    summary: str = ""


class HttpApi(BaseModel):
    """An OpenAPI (or Swagger) description, the component it belongs to, and who calls it.

    `owner_by` is the rule that placed it (`derive.owner_of`): `servers` (its servers name the
    component), `code` (it sits in the component's build context or image source), `directory`
    (a directory of its path is named like the component), `repository-name` (the component is
    named like its repository) or `repository` (nothing else did — the repository is the
    component)."""

    model_config = _MODEL

    component: str
    owner_by: str = ""
    title: str = ""
    version: str = ""
    operations: list[Operation] = Field(default_factory=list)
    #: components declared to call it (`Link`s of kind `http` into `component`)
    callers: list[str] = Field(default_factory=list)
    source: Cite


class Rpc(BaseModel):
    """One `rpc` of a proto service. `request`/`response` carry `stream ` when declared so."""

    model_config = _MODEL

    name: str
    request: str = ""
    response: str = ""
    line: int = 0


class GrpcService(BaseModel):
    """One `service` of a `.proto` file, and the component it belongs to."""

    model_config = _MODEL

    component: str
    owner_by: str = ""
    package: str = ""
    service: str
    rpcs: list[Rpc] = Field(default_factory=list)
    callers: list[str] = Field(default_factory=list)
    source: Cite


class EventEnd(BaseModel):
    """One side of an event: the component that sends or receives it, and where that is said."""

    model_config = _MODEL

    component: str
    owner_by: str = ""
    message: str = ""
    source: Cite


class Event(BaseModel):
    """A channel (a topic, a subject, a routing key) and who sends and receives on it.

    A channel received and sent by nobody is listed in `not_derived` as well: the map cannot say
    where those events come from."""

    model_config = _MODEL

    channel: str
    protocol: str = ""
    #: the declared component the AsyncAPI servers point at, when they point at one
    broker: str = ""
    producers: list[EventEnd] = Field(default_factory=list)
    consumers: list[EventEnd] = Field(default_factory=list)


class Column(BaseModel):
    model_config = _MODEL

    name: str
    type: str = ""


class Table(BaseModel):
    """One table as the migrations leave it, after every later migration was applied."""

    model_config = _MODEL

    name: str
    columns: list[Column] = Field(default_factory=list)
    #: the tables it declares a foreign key to
    references: list[str] = Field(default_factory=list)
    #: the statement that created it
    source: Cite
    #: every later migration that changed it, in the order they apply
    altered_in: list[Cite] = Field(default_factory=list)


class Database(BaseModel):
    """A database: the schema its migrations leave, who owns it and who else is declared to use it.

    `name` is the deployed component it runs on, when the owner's declared address points at one;
    otherwise the owner's name, and `not_derived` says no source declares the instance.

    OWNERS AND USERS ARE DIFFERENT FACTS. An owner is a component whose migrations define the
    schema; a user is any other component declared to connect to it. A database with users beyond
    its owners is SHARED, which is the thing an owner most needs to see on a map."""

    model_config = _MODEL

    name: str
    engine: str = ""
    owners: list[str] = Field(default_factory=list)
    users: list[str] = Field(default_factory=list)
    #: sql | flyway | golang-migrate | dbmate | alembic | django | prisma — "" when none was read
    tool: str = ""
    tables: list[Table] = Field(default_factory=list)
    #: every migration file read, in the order it applies
    migrations: list[Cite] = Field(default_factory=list)
    #: the deployment that declares the instance, when one does
    declared_by: list[Cite] = Field(default_factory=list)


class Queue(BaseModel):
    """A named queue or topic declared as infrastructure: by Terraform, or an AsyncAPI binding."""

    model_config = _MODEL

    name: str
    kind: str
    producers: list[str] = Field(default_factory=list)
    consumers: list[str] = Field(default_factory=list)
    source: Cite


class Infrastructure(BaseModel):
    """One Terraform resource of a kind the map knows (a database, a cache, a broker, compute).

    NOT MERGED INTO THE COMPONENTS, on purpose: Terraform names cloud resources, compose and
    Kubernetes name the services' network names, and which cloud resource a compose service becomes
    is exactly what a repository does not declare. Listed beside them, cited, and left unjoined."""

    model_config = _MODEL

    address: str
    kind: str
    name: str = ""
    engine: str = ""
    source: Cite


class Adr(BaseModel):
    """One architecture decision record in one source, and the component its directory sits in."""

    model_config = _MODEL

    repo: str
    number: str = ""
    title: str = ""
    status: str = ""
    date: str = ""
    component: str = ""
    source: Cite


class SystemMap(BaseModel):
    """The whole derivation: every source read, what it declares, and what it could not say."""

    model_config = _MODEL

    version: str = SYSTEM_VERSION
    #: ISO-8601, passed in — never read from the clock here
    generated_at: str = ""
    sources: list[SourceRead] = Field(default_factory=list)
    components: list[Component] = Field(default_factory=list)
    links: list[Link] = Field(default_factory=list)
    http: list[HttpApi] = Field(default_factory=list)
    grpc: list[GrpcService] = Field(default_factory=list)
    events: list[Event] = Field(default_factory=list)
    databases: list[Database] = Field(default_factory=list)
    queues: list[Queue] = Field(default_factory=list)
    infrastructure: list[Infrastructure] = Field(default_factory=list)
    adrs: list[Adr] = Field(default_factory=list)
    not_derived: list[NotDerived] = Field(default_factory=list)

    def component(self, name: str) -> Component | None:
        return next((c for c in self.components if c.name == name), None)


__all__ = [
    "AMBIGUOUS",
    "AT_RUN_TIME",
    "NOT_DECLARED",
    "NOT_DERIVED_KINDS",
    "NOT_FOLLOWED",
    "NOT_READ",
    "PARSE_ERROR",
    "SOURCE_UNREADABLE",
    "SYSTEM_VERSION",
    "TOO_LARGE",
    "TRUNCATED",
    "UNKNOWN_FORMAT",
    "Adr",
    "Cite",
    "Column",
    "Component",
    "Database",
    "Event",
    "EventEnd",
    "GrpcService",
    "HttpApi",
    "Infrastructure",
    "Link",
    "NotDerived",
    "Operation",
    "Queue",
    "Rpc",
    "SourceRead",
    "SystemMap",
    "Table",
]
