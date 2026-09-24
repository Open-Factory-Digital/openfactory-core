"""The system layer, derived: every declared source read, and one map of the product across them.

`derive(sources)` is a PURE FUNCTION OF THE FILES: no model, no network, no process, no clock. It
walks each source (`tree.walk`), reads the declarations it recognises (`interfaces`, `schemas`,
`deployments`, `adrs`), and joins them into one `SystemMap` — the components, the interfaces
between them, the databases and who owns or uses each, the queues, the ADRs — with every entry
citing the repository, file and commit it came from, and everything it could not establish listed
with why.

THE JOIN IS BY NAME, AND EVERY RULE IS WRITTEN HERE. Nothing is inferred from prose or guessed from
similarity. A component is named where it is deployed; an address is joined to a component when its
host IS that component's name (or a Kubernetes Service that selects it); a declaration belongs to a
component by the first of these that holds (`owner_of`), and the rule that placed it is written on
the entry beside it:

    servers          an OpenAPI description's servers name exactly one component
    code             it sits under a component's code — a build context that resolves into the
                     source, or an image named like the source
    directory        a directory of its path is named like a component
    file-name        its file is named like a component (`orders.openapi.yaml`)
    repository-name  a component is named like its repository
    repository       none of the above: the repository is the component (`kind: repository`)

A weaker rule is not a guess — each is a name matching a name — but a reader deserves to know which
one placed an API, so it is on the entry.
"""

from __future__ import annotations

import ast
import json
import posixpath
import re
from collections.abc import Iterable
from dataclasses import dataclass, field

import yaml

from openfactory.knowledge.system import adrs as adr_reader
from openfactory.knowledge.system import deployments as deploy
from openfactory.knowledge.system import interfaces as api
from openfactory.knowledge.system import schemas
from openfactory.knowledge.system.contracts import (
    AMBIGUOUS,
    AT_RUN_TIME,
    NOT_DECLARED,
    NOT_FOLLOWED,
    NOT_READ,
    PARSE_ERROR,
    SOURCE_UNREADABLE,
    TOO_LARGE,
    TRUNCATED,
    UNKNOWN_FORMAT,
    Adr,
    Cite,
    Component,
    Database,
    Event,
    EventEnd,
    GrpcService,
    HttpApi,
    Infrastructure,
    Link,
    NotDerived,
    Queue,
    SourceRead,
    SystemMap,
)
from openfactory.knowledge.system.text import clip, load_yaml
from openfactory.knowledge.system.tree import MAX_FILES, SourceTree, read_text, walk

_COMPOSE = re.compile(r"^(?:docker-)?compose(?:[.-][\w.-]*)?\.ya?ml$", re.IGNORECASE)
#: Line starts are matched with `[ \t]*`, never `\s*`: under MULTILINE a `\s*` after `^` runs
#: across blank lines, and from every line start of a file of blank lines that is quadratic.
_SPEC_SNIFF = re.compile(r"""^[ \t]*["']?(openapi|swagger|asyncapi)["']?[ \t]*:""", re.MULTILINE)
_K8S_SNIFF = re.compile(r"""^[ \t]*["']?apiVersion["']?[ \t]*:""", re.MULTILINE)
_K8S_KIND = re.compile(r"""^[ \t]*["']?kind["']?[ \t]*:""", re.MULTILINE)
_CLOUDFORMATION = re.compile(r"AWSTemplateFormatVersion|Transform\s*:\s*['\"]?AWS::Serverless")
#: Files whose name alone says they are a declaration this layer does not read, and what it is.
_UNREAD_NAMES = {
    "serverless.yml": "a Serverless Framework service",
    "serverless.yaml": "a Serverless Framework service",
    "pulumi.yaml": "infrastructure declared in code (Pulumi) — known only by running it",
    "cdk.json": "infrastructure declared in code (CDK) — known only by running it",
    "schema.graphql": "a GraphQL schema",
}
_UNREAD_SUFFIXES = {
    ".raml": "a RAML API description", ".apib": "an API Blueprint description",
    ".graphqls": "a GraphQL schema", ".wsdl": "a WSDL service description",
    ".avsc": "an Avro schema", ".avdl": "an Avro IDL", ".thrift": "a Thrift IDL",
    ".smithy": "a Smithy model", ".nomad": "a Nomad job",
}
_LOCKFILES = frozenset({"package-lock.json", "pnpm-lock.yaml", "composer.lock", "yarn.lock"})
#: Proto imports every toolchain ships: not the product's to declare.
_WELL_KNOWN_PROTO = ("google/protobuf/", "google/api/", "google/rpc/", "google/type/",
                     "validate/", "buf/validate/", "gogoproto/")
#: Suffixes a description's file name carries after the component's name (`orders.openapi.yaml`).
_SPEC_STEM_SUFFIXES = (".openapi", ".swagger", ".asyncapi", "-openapi", "-swagger", "-asyncapi",
                       "_openapi", "-api", "_api", ".api")
_SCHEMES = {"postgres": "database", "postgresql": "database", "mysql": "database",
            "mariadb": "database", "mongodb": "database", "mongodb+srv": "database",
            "sqlserver": "database", "redis": "cache", "rediss": "cache", "amqp": "broker",
            "amqps": "broker", "kafka": "broker", "nats": "broker", "mqtt": "broker",
            "http": "http", "https": "http", "ws": "http", "wss": "http", "grpc": "grpc",
            "grpcs": "grpc"}


# ── what one source declares, before the join ───────────────────────────────────────────────────

@dataclass
class _Declared:
    """Everything the readers found in every source, each item with where it was found."""

    compose: list[tuple[Cite, deploy.Deployed]] = field(default_factory=list)
    workloads: list[tuple[Cite, deploy.Deployed]] = field(default_factory=list)
    k8s_services: list[tuple[Cite, deploy.K8sService]] = field(default_factory=list)
    config_maps: dict[str, dict[str, deploy.HostRef | None]] = field(default_factory=dict)
    from_config: list[tuple[Cite, str, str, str, str]] = field(default_factory=list)
    terraform: list[tuple[Cite, deploy.TfResource]] = field(default_factory=list)
    openapi: list[tuple[Cite, api.OpenApiDecl]] = field(default_factory=list)
    asyncapi: list[tuple[Cite, api.AsyncApiDecl]] = field(default_factory=list)
    proto: list[tuple[Cite, api.ProtoDecl]] = field(default_factory=list)
    schemas: list[tuple[Cite, schemas.MigrationSet, schemas.Schema, str]] = field(
        default_factory=list)
    adrs: list[tuple[Cite, adr_reader.AdrDecl]] = field(default_factory=list)
    notes: list[NotDerived] = field(default_factory=list)
    files: dict[str, int] = field(default_factory=dict)
    all_files: dict[str, list[str]] = field(default_factory=dict)


def _parse_structured(text: str, rel: str):
    """A YAML or JSON document, by the file's extension."""
    if rel.lower().endswith(".json"):
        return json.loads(text)
    return load_yaml(text)


_PARSE_ERRORS = (yaml.YAMLError, ValueError, TypeError, RecursionError, SyntaxError)


def _problem(exc: BaseException) -> str:
    """One line of what a parser said, without the file's text."""
    said = getattr(exc, "problem", None) or getattr(exc, "msg", None) or type(exc).__name__
    mark = getattr(exc, "problem_mark", None)
    where = f" at line {mark.line + 1}" if mark is not None else (
        f" at line {exc.lineno}" if getattr(exc, "lineno", None) else "")
    return clip(f"{said}{where}", 160)


def _read_source(tree: SourceTree, into: _Declared) -> None:
    """Every declaration of one source, read into `into`."""
    repo = tree.repo
    walked = walk(tree.root)
    files = walked.files
    into.all_files[repo] = files
    read = 0

    def note(kind: str, rel: str, detail: str) -> None:
        into.notes.append(NotDerived(kind=kind, repo=repo, path=rel, detail=detail))

    def cite(rel: str, line: int = 0) -> Cite:
        return Cite(repo=repo, path=rel, commit=tree.commit, line=line)

    if walked.truncated:
        note(TRUNCATED, "", f"has more than {MAX_FILES} files; the walk stopped there and what "
                            f"lies beyond was not read")
    for rel in walked.links_out:
        note(NOT_FOLLOWED, rel, "is a link out of the repository's tree; it was not followed, "
                                "and nothing it points at was read")
    for rel in walked.unreadable:
        note(NOT_READ, rel, "could not be opened, so nothing under it was read")

    def text_of(rel: str, *, quiet: bool = False) -> str | None:
        got = read_text(tree.root, rel)
        if got.text is None and not quiet:
            note(TOO_LARGE if got.too_large else PARSE_ERROR, rel, f"{got.why}; it was not read")
        return got.text

    loaded: dict[str, tuple[object, str]] = {}

    def load(rel: str) -> tuple[object, str]:
        """Another file of this source, for a `$ref` — parsed, or why not."""
        if rel not in loaded:
            got = read_text(tree.root, rel)
            if got.text is None:
                loaded[rel] = (None, got.why)
            else:
                try:
                    loaded[rel] = (_parse_structured(got.text, rel), "")
                except _PARSE_ERRORS as exc:
                    loaded[rel] = (None, f"did not parse ({_problem(exc)})")
        return loaded[rel]

    charts = {posixpath.dirname(f) for f in files if posixpath.basename(f) == "Chart.yaml"}
    for chart in sorted(charts):
        note(UNKNOWN_FORMAT, f"{chart}/Chart.yaml" if chart else "Chart.yaml",
             "is a Helm chart: its manifests exist only when helm renders the templates, which "
             "runs the chart and is never done here; the services it deploys are not derived")

    def in_chart(rel: str) -> bool:
        """Whether `rel` is inside a chart's directory: any of its ancestors is one."""
        parts = rel.split("/")
        return any("/".join(parts[:i]) in charts for i in range(len(parts)))

    present = set(files)
    alembic_dirs = {posixpath.dirname(f) for f in files
                    if posixpath.basename(posixpath.dirname(f)) == "versions"
                    and (f"{posixpath.dirname(posixpath.dirname(f))}/env.py".lstrip("/")
                         in present or "alembic" in f.split("/"))}
    unread_tools: dict[tuple[str, str], str] = {}

    def one(rel: str) -> int:
        """One file, read if it is a declaration. Returns 1 when it was read, 0 otherwise."""
        name = posixpath.basename(rel)
        low = name.lower()
        if in_chart(rel):
            return 0
        if what := schemas.unread_tool(rel):
            unread_tools.setdefault((what, posixpath.dirname(rel)), rel)
            return 0
        if low in _UNREAD_NAMES:
            note(UNKNOWN_FORMAT, rel, f"is {_UNREAD_NAMES[low]}, a format this layer does not "
                                      f"read; what it declares is not derived")
            return 0
        suffix = posixpath.splitext(low)[1]
        if low.endswith(".nomad.hcl"):
            suffix = ".nomad"
        if suffix in _UNREAD_SUFFIXES:
            note(UNKNOWN_FORMAT, rel, f"is {_UNREAD_SUFFIXES[suffix]}, a format this layer does "
                                      f"not read; what it declares is not derived")
            return 0
        if low in ("kustomization.yaml", "kustomization.yml"):
            note(NOT_FOLLOWED, rel, "is a kustomize overlay: its patches are not applied, and the "
                                    "manifests it lists are read as they are written")
            return 0
        if _COMPOSE.match(name):
            if (text := text_of(rel)) is None:
                return 0
            try:
                services, notes = deploy.read_compose(text, rel=rel, repo=repo)
            except _PARSE_ERRORS as exc:
                note(PARSE_ERROR, rel, f"did not parse as a compose file ({_problem(exc)})")
                return 0
            into.notes.extend(notes)
            into.compose += [(cite(rel, s.line), s) for s in services]
            return 1
        if low.endswith(".proto"):
            if (text := text_of(rel)) is None:
                return 0
            into.proto.append((cite(rel), api.read_proto(text)))
            return 1
        if low.endswith(".tf"):
            if (text := text_of(rel)) is None:
                return 0
            resources, notes = deploy.read_terraform(text, rel=rel, repo=repo)
            into.notes.extend(notes)
            into.terraform += [(cite(rel, r.line), r) for r in resources]
            return 1
        if low.endswith(".tf.json"):
            if (text := text_of(rel)) is None:
                return 0
            try:
                resources = deploy.read_terraform_json(json.loads(text), rel=rel, repo=repo)
            except _PARSE_ERRORS as exc:
                note(PARSE_ERROR, rel, f"did not parse as Terraform JSON ({_problem(exc)})")
                return 0
            into.terraform += [(cite(rel), r) for r in resources]
            return 1
        if adr_reader.is_adr(rel):
            if (text := text_of(rel)) is None:
                return 0
            into.adrs.append((cite(rel), adr_reader.read_adr(text, rel)))
            return 1
        if suffix in (".yaml", ".yml", ".json") and low not in _LOCKFILES:
            hinted = any(w in low for w in ("openapi", "swagger", "asyncapi"))
            if (text := text_of(rel, quiet=not hinted)) is None:
                return 0
            return _read_structured(text, rel, repo=repo, cite=cite, note=note, load=load,
                                    into=into)
        return 0

    # A REPOSITORY IS SOMEBODY ELSE'S INPUT. A file shaped in a way no reader expected costs that
    # file — named, with the kind of failure and nothing of its text — never the map.
    for rel in files:
        try:
            read += one(rel)
        except Exception as exc:  # noqa: BLE001 — one file's surprise must not cost every source
            note(PARSE_ERROR, rel, f"could not be read ({type(exc).__name__}); what it declares "
                                   f"is not derived")

    for (what, directory), rel in sorted(unread_tools.items()):
        note(UNKNOWN_FORMAT, directory or rel,
             f"holds {what}, a migration format this layer does not read (its files are a "
             f"program); the schema they build is not derived")

    for mset in schemas.migration_sets(files, alembic_dirs=alembic_dirs):
        try:
            schema, engine, applied = _apply_set(tree, mset, note)
        except Exception as exc:  # noqa: BLE001 — as above, for one set of migrations
            note(PARSE_ERROR, mset.directory, f"its migrations could not be applied "
                                              f"({type(exc).__name__}); its schema is not derived")
            continue
        if applied:
            done = schemas.MigrationSet(directory=mset.directory, tool=mset.tool, files=applied)
            into.schemas.append((cite(applied[0]), done, schema, engine))
            read += len(applied)

    into.files[repo] = read


def _read_structured(text: str, rel: str, *, repo: str, cite, note, load, into: _Declared
                     ) -> int:
    """One YAML or JSON file: an OpenAPI or AsyncAPI description, Kubernetes manifests, a
    CloudFormation template (named, not read) — or nothing this layer reads, left alone."""
    spec = _SPEC_SNIFF.search(text) or re.search(r'"(openapi|swagger|asyncapi)"\s*:', text)
    if spec is not None:
        try:
            doc = _parse_structured(text, rel)
        except _PARSE_ERRORS as exc:
            note(PARSE_ERROR, rel, f"looks like an API description and did not parse "
                                   f"({_problem(exc)})")
            return 0
        if not isinstance(doc, dict):
            return 0
        if "asyncapi" in doc:
            decl, notes = api.read_asyncapi(doc, rel=rel, repo=repo)
            into.asyncapi.append((cite(rel), decl))
        elif "openapi" in doc or "swagger" in doc:
            decl, notes = api.read_openapi(doc, rel=rel, repo=repo, load=load)
            into.openapi.append((cite(rel), decl))
        else:
            return 0
        into.notes.extend(notes)
        return 1
    if _CLOUDFORMATION.search(text):
        note(UNKNOWN_FORMAT, rel, "is a CloudFormation template, a format this layer does not "
                                  "read; the resources it declares are not derived")
        return 0
    if (_K8S_SNIFF.search(text) and _K8S_KIND.search(text)) or (
            rel.lower().endswith(".json") and '"apiVersion"' in text and '"kind"' in text):
        if "{{" in text:
            note(UNKNOWN_FORMAT, rel, "is a templated manifest (`{{ … }}`): only rendering it "
                                      "would say what it deploys, and nothing is rendered here")
            return 0
        found = deploy.K8sRead()
        into.notes.extend(deploy.read_kubernetes(text, rel=rel, repo=repo, into=found))
        lines = {w.name: w.line for w in found.workloads}
        into.workloads += [(cite(rel, w.line), w) for w in found.workloads]
        into.k8s_services += [(cite(rel, s.line), s) for s in found.services]
        for name, data in found.config_maps.items():
            into.config_maps.setdefault(name, data)
        into.from_config += [(cite(rel, lines.get(f[0], 0)), *f) for f in found.from_config]
        return 1
    return 0


def _apply_set(tree: SourceTree, mset: schemas.MigrationSet, note
               ) -> tuple[schemas.Schema, str, list[str]]:
    """One migration set applied in the order its tool runs it. `(schema, engine, applied)`, where
    `applied` is every file read, in that order — empty when the set changed nothing (a directory
    of queries is not a schema)."""
    schema = schemas.Schema()
    engine = ""
    applied: list[str] = []
    parsed: dict[str, ast.Module] = {}
    changed = 0
    for rel in mset.files:
        got = read_text(tree.root, rel)
        if got.text is None:
            note(TOO_LARGE if got.too_large else PARSE_ERROR, rel, f"{got.why}; it was not read")
            continue
        at = Cite(repo=tree.repo, path=rel, commit=tree.commit)
        if mset.tool in ("alembic", "django"):
            try:
                parsed[rel] = ast.parse(got.text, filename=rel)   # a tree; nothing is executed
            except (SyntaxError, ValueError, RecursionError, MemoryError) as exc:
                note(PARSE_ERROR, rel, f"did not parse as Python ({_problem(exc)})")
            continue
        if mset.tool == "prisma":
            engine = schemas.apply_prisma(got.text, schema, at) or engine
            changed += 1
        else:
            changed += schemas.apply_sql(got.text, schema, at)
        applied.append(rel)
    if mset.tool == "alembic" and parsed:
        order, linear = schemas.alembic_order(parsed)
        if not linear:
            note(AMBIGUOUS, mset.directory, "its Alembic revisions do not form one line (a branch, "
                                            "a merge or a missing revision); they were applied in "
                                            "file-name order, which may not be the order they run")
        for rel in order:
            at = Cite(repo=tree.repo, path=rel, commit=tree.commit)
            for n in schemas.apply_alembic(parsed[rel], schema, at, repo=tree.repo, rel=rel):
                note(n.kind, n.path, n.detail)
            applied.append(rel)
        changed += len(order)
    elif mset.tool == "django" and parsed:
        app = posixpath.basename(posixpath.dirname(mset.directory)) or tree.leaf
        models: dict[str, str] = {}
        for rel in mset.files:
            if rel in parsed:
                schemas.apply_django(parsed[rel], schema, Cite(repo=tree.repo, path=rel,
                                                               commit=tree.commit),
                                     app=app, models=models)
                applied.append(rel)
        changed += len(applied)
    return schema, engine, applied if (changed or schema.tables()) else []


# ── the join ────────────────────────────────────────────────────────────────────────────────────

@dataclass
class _Comp:
    name: str
    kind: str
    engine: str = ""
    repo: str = ""
    code: str = ""
    code_by: str = ""
    image: str = ""
    depends_on: set[str] = field(default_factory=set)
    env: set[str] = field(default_factory=set)
    declared_by: list[Cite] = field(default_factory=list)
    refs: list[tuple[deploy.HostRef, Cite]] = field(default_factory=list)
    unresolved: list[tuple[str, str, Cite]] = field(default_factory=list)
    labels: dict[str, str] = field(default_factory=dict)


class _Join:
    """The components and the rules that join everything else to them."""

    def __init__(self, sources: list[SourceTree], declared: _Declared,
                 missing: Iterable[str] = ()) -> None:
        self.sources = sources
        #: every declared source by its own name — the ones that could not be read included: a
        #: build context into one of them still says where that component's code lives
        self.leaves = {r.strip("/").rsplit("/", 1)[-1].lower(): r for r in missing}
        self.leaves.update({s.leaf.lower(): s.repo for s in sources})
        self.unread = set(missing)
        self.d = declared
        self.comps: dict[str, _Comp] = {}
        self.notes: list[NotDerived] = []
        self.k8s_services: dict[str, list[str]] = {}

    def note(self, kind: str, detail: str, cite: Cite | None = None) -> None:
        self.notes.append(NotDerived(kind=kind, detail=detail, repo=cite.repo if cite else "",
                                     path=cite.path if cite else ""))

    # components ------------------------------------------------------------------------------

    def _code(self, cite: Cite, dep: deploy.Deployed) -> tuple[str, str, str]:
        """`(repo, code, code_by)` of a deployed component — where its code lives, when said."""
        if dep.build is not None:
            inner, sibling = dep.build
            if sibling is None:
                return cite.repo, inner, "build-context"
            repo = self.leaves.get(sibling.lower())
            if repo is not None:
                return repo, inner, "build-context"
            self.note(NOT_DECLARED, f"`{dep.name}` builds from `../{sibling}`, which is not a "
                                    f"source of this product; its code is not in the map", cite)
        if dep.image:
            repo = self.leaves.get(deploy.image_repository(dep.image))
            if repo is not None:
                return repo, ".", "image"
        return "", "", ""

    def add(self, cite: Cite, dep: deploy.Deployed) -> None:
        kind, engine = deploy.image_kind(dep.image) if dep.image and dep.build is None \
            else ("service", "")
        repo, code, code_by = self._code(cite, dep)
        comp = self.comps.get(dep.name)
        if comp is None:
            comp = self.comps[dep.name] = _Comp(name=dep.name, kind=kind, engine=engine)
        elif comp.kind != kind:
            self.note(AMBIGUOUS, f"`{dep.name}` is declared as a {comp.kind} and here as a "
                                 f"{kind}; the map keeps it as a {comp.kind}", cite)
        if code_by and (not comp.code_by or comp.code_by == "image" and code_by != "image"):
            comp.repo, comp.code, comp.code_by = repo, code, code_by
        elif code_by == "build-context" and comp.code_by == "build-context" \
                and (repo, code) != (comp.repo, comp.code):
            self.note(AMBIGUOUS, f"`{dep.name}` is built from `{code}` of {repo} here and from "
                                 f"`{comp.code}` of {comp.repo} elsewhere; the map keeps the first",
                      cite)
        comp.image = comp.image or dep.image
        comp.engine = comp.engine or engine
        comp.depends_on |= set(dep.depends_on)
        comp.env |= set(dep.env)
        comp.declared_by.append(cite)
        comp.refs += [(r, cite) for r in dep.refs]
        comp.unresolved += [(n, why, cite) for n, why in dep.unresolved]
        comp.labels.update(dep.labels)

    def repository_component(self, repo: str, cite: Cite | None) -> str:
        """The repository as a component of its own, cited by the declaration that made it one."""
        leaf = repo.strip("/").rsplit("/", 1)[-1]
        comp = self.comps.get(leaf)
        if comp is None:
            comp = self.comps[leaf] = _Comp(name=leaf, kind="repository", repo=repo, code=".")
        if cite is not None and cite not in comp.declared_by:
            comp.declared_by.append(cite)
        return leaf

    # owners ----------------------------------------------------------------------------------

    def owner_of(self, repo: str, rel: str, *, hosts: Iterable[str] = (), create: bool = True,
                 cite: Cite | None = None) -> tuple[str, str]:
        """`(component, rule)` a declaration at `rel` of `repo` belongs to — see the module's
        docstring for the rules, in the order they are asked. `("", "")` when `create` is False
        and only the last rule would place it."""
        targets = {t for t in (self.target(h) for h in hosts) if t}
        if len(targets) == 1:
            return targets.pop(), "servers"
        under = [(len(c.code), c.name) for c in self.comps.values()
                 if c.repo == repo and c.code and c.kind != "repository"
                 and (c.code == "." or rel == c.code or rel.startswith(c.code + "/"))]
        shared: list[str] = []
        if under:
            depth = max(n for n, _ in under)
            best = sorted(name for n, name in under if n == depth)
            if len(best) == 1:
                return best[0], "code"
            parts = {p.lower() for p in rel.split("/")[:-1]}
            named = [b for b in best if b.lower() in parts]
            if len(named) == 1:
                return named[0], "code"
            shared = best
        dirs = rel.split("/")[:-1]
        for part in reversed(dirs):
            if part in self.comps and self.comps[part].kind != "repository":
                return part, "directory"
        stem = posixpath.basename(rel)
        for ext in (".yaml", ".yml", ".json", ".proto"):
            if stem.lower().endswith(ext):
                stem = stem[: -len(ext)]
                break
        for suffix in _SPEC_STEM_SUFFIXES:
            if stem.lower().endswith(suffix) and len(stem) > len(suffix):
                stem = stem[: -len(suffix)]
                break
        if stem in self.comps and self.comps[stem].kind != "repository":
            return stem, "file-name"
        leaf = repo.strip("/").rsplit("/", 1)[-1]
        if leaf in self.comps and self.comps[leaf].kind != "repository":
            return leaf, "repository-name"
        if not create:
            return "", ""
        if shared:
            # SAID, NOT CHOSEN: two components built from one directory (an API and its worker)
            # and nothing else names which one this file describes
            self.note(AMBIGUOUS, f"sits in the code of {', '.join(f'`{b}`' for b in shared)}, "
                                 f"which are built from one directory, and nothing says which "
                                 f"it describes; the map places it on the repository", cite)
        return self.repository_component(repo, cite), "repository"

    # addresses -------------------------------------------------------------------------------

    def target(self, host: str) -> str:
        """The component an address's host names, or "".

        By name: a component's own (`orders`), a Kubernetes Service's in any of the forms the
        cluster resolves (`orders.shop.svc.cluster.local`, `orders.shop.svc`, and `orders.shop` —
        the last only when `orders` IS a declared Service, since two labels are also how an
        outside host looks)."""
        h = host.lower().strip(".")
        labels = h.split(".")
        if h.endswith(".svc.cluster.local") or h.endswith(".svc"):
            h = labels[0]
        elif len(labels) == 2 and labels[0] in self.k8s_services:
            h = labels[0]
        if h in self.comps:
            return h
        selected = self.k8s_services.get(h) or []
        return selected[0] if len(selected) == 1 else ""


def _select(services: list[tuple[Cite, deploy.K8sService]], comps: dict[str, _Comp]
            ) -> dict[str, list[str]]:
    """Kubernetes Service name → the workloads its selector selects (by their pods' labels)."""
    out: dict[str, list[str]] = {}
    for _, svc in services:
        chosen = sorted(c.name for c in comps.values() if svc.selector and c.labels
                        and all(c.labels.get(k) == v for k, v in svc.selector.items()))
        if not chosen and svc.name in comps:
            chosen = [svc.name]
        out.setdefault(svc.name, [])
        out[svc.name] = sorted(set(out[svc.name]) | set(chosen))
    return out


def _link_kind(target: _Comp, scheme: str, serves_http: bool, serves_grpc: bool) -> str:
    if target.kind in ("database", "broker", "cache", "search"):
        return target.kind
    if scheme in _SCHEMES:
        return _SCHEMES[scheme]
    if not scheme:
        if serves_grpc and not serves_http:
            return "grpc"
        if serves_http:
            return "http"
    return "network"


def _cite_key(c: Cite) -> tuple:
    return (c.repo, c.path, c.line)


def derive(sources: list[SourceTree], *, missing: dict[str, str] | None = None,
           generated_at: str = "") -> SystemMap:
    """The system map of a product whose sources are `sources` — each already checked out, with
    the commit it is at — and `missing`, the sources that could not be, with why."""
    sources = sorted(sources, key=lambda s: s.repo)
    declared = _Declared()
    for tree in sources:
        _read_source(tree, declared)
    j = _Join(sources, declared, missing=(missing or {}).keys())
    notes = list(declared.notes)

    # 1. components, from every deployment, by name
    for cite, dep in declared.compose + declared.workloads:
        j.add(cite, dep)
    j.k8s_services = _select(declared.k8s_services, j.comps)
    for cite, workload, var, cm, key in sorted(declared.from_config, key=lambda x: (
            _cite_key(x[0]), x[1], x[2], x[3], x[4])):
        comp = j.comps.get(workload)
        data = declared.config_maps.get(cm)
        if comp is None:
            continue
        if data is None:
            if not var or deploy.address_name(var):
                j.note(NOT_DECLARED, f"`{workload}` takes {f'`{var}`' if var else 'variables'} "
                                     f"from ConfigMap `{cm}`, which no source declares; where "
                                     f"{'it points' if var else 'they point'} is not derived",
                       cite)
            continue
        items = [(var, data.get(key))] if var else sorted(data.items())
        for name, ref in items:
            comp.env.add(name)
            if ref is not None:
                comp.refs.append((deploy.HostRef(name=name, scheme=ref.scheme, host=ref.host),
                                  cite))

    # 2. what each component serves — asked before the links, whose kind depends on it
    http: list[HttpApi] = []
    for cite, decl in declared.openapi:
        owner, rule = j.owner_of(cite.repo, cite.path, hosts=decl.hosts, cite=cite)
        http.append(HttpApi(component=owner, owner_by=rule, title=decl.title,
                            version=decl.version, operations=decl.operations, source=cite))
    grpc: list[GrpcService] = []
    # every tail of every `.proto` path of every source: `a/b/c.proto`, `b/c.proto`, `c.proto` —
    # an import names a file by a tail of its path, relative to wherever its tool was pointed
    tails = {"/".join(parts[i:]) for files in declared.all_files.values() for f in files
             if f.endswith(".proto") for parts in [f.split("/")] for i in range(len(parts))}
    for cite, decl in declared.proto:
        for imported in decl.imports:
            if imported.startswith(_WELL_KNOWN_PROTO):
                continue
            if imported not in tails:
                j.note(NOT_DECLARED, f"imports `{clip(imported, 120)}`, which is in none of the "
                                     f"product's sources", cite)
        for service in decl.services:
            owner, rule = j.owner_of(cite.repo, cite.path, cite=cite)
            grpc.append(GrpcService(component=owner, owner_by=rule, package=decl.package,
                                    service=service.name, rpcs=service.rpcs,
                                    source=cite.model_copy(update={"line": service.line})))
    serves_http = {a.component for a in http}
    serves_grpc = {g.component for g in grpc}

    # 3. events and the queues their bindings name
    events: dict[str, Event] = {}
    queues: list[Queue] = []
    for cite, decl in declared.asyncapi:
        owner, rule = j.owner_of(cite.repo, cite.path, cite=cite)
        brokers = sorted({t for t in (j.target(h) for h in decl.hosts) if t})
        for end in decl.ends:
            event = events.setdefault(end.channel, Event(channel=end.channel))
            if decl.protocol and decl.protocol not in event.protocol.split(","):
                event.protocol = ",".join(sorted(filter(None, [*event.protocol.split(","),
                                                               decl.protocol])))
            if len(brokers) == 1 and not event.broker:
                event.broker = brokers[0]
            side = event.producers if end.action == "send" else event.consumers
            side.append(EventEnd(component=owner, owner_by=rule, message=end.message,
                                 source=cite))
        for qname, qkind, channel in decl.queues:
            ends = [e for e in decl.ends if e.channel == channel]
            queues.append(Queue(name=qname, kind=qkind, source=cite,
                                producers=[owner] if any(e.action == "send" for e in ends) else [],
                                consumers=[owner] if any(e.action == "receive"
                                                         for e in ends) else []))

    # 4. schemas: a database per migration set, joined to the instance its owner addresses
    migrated: list[tuple[str, schemas.MigrationSet, schemas.Schema, str, Cite]] = []
    for cite, mset, schema, engine in declared.schemas:
        owner, _ = j.owner_of(cite.repo, cite.path, cite=cite)
        migrated.append((owner, mset, schema, engine, cite))

    # 5. the links an address declares
    links: dict[tuple[str, str, str, str], Link] = {}
    for comp in sorted(j.comps.values(), key=lambda c: c.name):
        for ref, cite in comp.refs:
            to = j.target(ref.host)
            if to == comp.name:
                continue
            if to:
                kind = _link_kind(j.comps[to], ref.scheme, to in serves_http, to in serves_grpc)
                key = (comp.name, to, kind, f"env {ref.name}")
                link = links.setdefault(key, Link(**{"from": comp.name}, to=to, kind=kind,
                                                  via=f"env {ref.name}"))
                if cite not in link.sources:
                    link.sources.append(cite)
            elif "." not in ref.host and not re.fullmatch(r"[\d.]+", ref.host):
                j.note(NOT_DECLARED, f"`{comp.name}` names `{ref.host}` in `{ref.name}`, and no "
                                     f"source declares a component `{ref.host}`", cite)
        for name, why, cite in comp.unresolved:
            if why == "secret-all":
                j.note(NOT_READ, f"`{comp.name}` takes every variable of the secret `{name}`; a "
                                 f"secret's value is never read, so the addresses among them are "
                                 f"not derived", cite)
            elif why == "secret":
                j.note(NOT_READ, f"`{comp.name}` takes `{name}` from a secret; a secret's value "
                                 f"is never read, so where it points is not derived", cite)
            else:
                j.note(AT_RUN_TIME, f"`{comp.name}` takes `{name}` from the environment it is "
                                    f"started in; where it points is known only at run time",
                       cite)

    # 6. event links, and what is received from nobody
    for event in events.values():
        for p in event.producers:
            for c in event.consumers:
                if p.component == c.component:
                    continue
                key = (p.component, c.component, "event", f"channel {event.channel}")
                link = links.setdefault(key, Link(**{"from": p.component}, to=c.component,
                                                  kind="event", via=f"channel {event.channel}"))
                for cite in (p.source, c.source):
                    if cite not in link.sources:
                        link.sources.append(cite)
        if event.consumers and not event.producers:
            for c in event.consumers:
                j.note(NOT_DECLARED, f"`{c.component}` receives `{event.channel}`, and no source "
                                     f"declares who sends it", c.source)

    # 7. callers, and calls into a component that describes no interface
    for link in links.values():
        if link.kind == "http":
            for a in http:
                if a.component == link.to and link.from_ not in a.callers:
                    a.callers.append(link.from_)
        if link.kind == "grpc":
            for g in grpc:
                if g.component == link.to and link.from_ not in g.callers:
                    g.callers.append(link.from_)
        described = link.to in serves_http or link.to in serves_grpc
        if link.kind in ("http", "grpc", "network") and not described \
                and j.comps[link.to].kind in ("service", "repository"):
            how = {"http": "over HTTP", "grpc": "over gRPC"}.get(link.kind, "at an address")
            why = (f"its source, `{j.comps[link.to].repo}`, could not be read"
                   if j.comps[link.to].repo in j.unread else f"`{link.to}` describes no API")
            j.note(NOT_DECLARED, f"`{link.from_}` calls `{link.to}` {how} ({link.via}), and "
                                 f"{why}; the operations it calls are not known",
                   link.sources[0] if link.sources else None)

    # 8. databases
    databases: dict[str, Database] = {}
    for owner, mset, schema, engine, cite in migrated:
        instances = sorted({lk.to for lk in links.values()
                            if lk.from_ == owner and lk.kind == "database"})
        if len(instances) == 1:
            name = instances[0]
        else:
            name = owner
            if not instances:
                j.note(NOT_DECLARED, f"`{owner}`'s migrations (`{mset.directory}`) describe a "
                                     f"database, and no source declares the instance it runs on",
                       cite)
            else:
                j.note(AMBIGUOUS, f"`{owner}` connects to {len(instances)} databases "
                                  f"({', '.join(instances)}) and its migrations "
                                  f"(`{mset.directory}`) do not say which they describe", cite)
        db = databases.setdefault(name, Database(name=name))
        if owner not in db.owners:
            db.owners.append(owner)
        db.tool = ",".join(sorted(set(filter(None, [*db.tool.split(","), mset.tool]))))
        db.engine = db.engine or engine or (j.comps[name].engine if name in j.comps else "")
        db.tables += schema.tables()
        db.migrations += [Cite(repo=cite.repo, path=rel, commit=cite.commit)
                          for rel in mset.files]
    for comp in sorted(j.comps.values(), key=lambda c: c.name):
        if comp.kind != "database":
            continue
        db = databases.get(comp.name)
        if db is None:
            db = databases[comp.name] = Database(name=comp.name, engine=comp.engine)
            j.note(NOT_DECLARED, f"`{comp.name}` is a database no source's migrations describe; "
                                 f"its schema is not derived",
                   comp.declared_by[0] if comp.declared_by else None)
        db.declared_by = sorted(comp.declared_by, key=_cite_key)
    for link in links.values():
        if link.kind == "database" and link.to in databases:
            db = databases[link.to]
            if link.from_ not in db.owners and link.from_ not in db.users:
                db.users.append(link.from_)

    # 9. Terraform: queues to the queues, the rest beside the components
    infrastructure: list[Infrastructure] = []
    for cite, res in declared.terraform:
        if res.kind in deploy.TF_QUEUE_KINDS:
            queues.append(Queue(name=res.name or f"{res.type}.{res.label}", kind=res.kind,
                                source=cite))
        else:
            infrastructure.append(Infrastructure(address=f"{res.type}.{res.label}",
                                                 kind=res.kind, name=res.name,
                                                 engine=res.engine, source=cite))

    # 10. ADRs, placed where they sit — never inventing a component for one
    adrs = []
    for cite, decl in declared.adrs:
        owner, _ = j.owner_of(cite.repo, cite.path, create=False)
        adrs.append(Adr(repo=cite.repo, number=decl.number, title=decl.title,
                        status=decl.status, date=decl.date, component=owner, source=cite))

    # 11. the sources themselves
    read_sources = [SourceRead(repo=s.repo, commit=s.commit, files=declared.files.get(s.repo, 0))
                    for s in sources]
    for repo, why in sorted((missing or {}).items()):
        read_sources.append(SourceRead(repo=repo, missing=why))
        notes.append(NotDerived(kind=SOURCE_UNREADABLE, repo=repo,
                                detail=f"could not be read ({why}); nothing it declares is in "
                                       f"the map"))
    notes += j.notes

    return SystemMap(
        generated_at=generated_at,
        sources=sorted(read_sources, key=lambda s: s.repo),
        components=[_component(c) for c in sorted(j.comps.values(), key=lambda c: c.name)],
        links=sorted(links.values(), key=lambda lk: (lk.from_, lk.to, lk.kind, lk.via)),
        http=sorted(_sorted_callers(http), key=lambda a: (a.component, *_cite_key(a.source))),
        grpc=sorted(_sorted_callers(grpc), key=lambda g: (g.component, g.service,
                                                          *_cite_key(g.source))),
        events=[_sorted_event(e) for _, e in sorted(events.items())],
        databases=[_sorted_db(d) for _, d in sorted(databases.items())],
        queues=sorted(queues, key=lambda q: (q.name, q.kind, *_cite_key(q.source))),
        infrastructure=sorted(infrastructure, key=lambda i: (i.address, *_cite_key(i.source))),
        adrs=sorted(adrs, key=lambda a: (a.repo, a.number, a.source.path)),
        not_derived=_unique(notes),
    )


def _component(c: _Comp) -> Component:
    return Component(name=c.name, kind=c.kind, repo=c.repo, code=c.code, code_by=c.code_by,
                     image=c.image, depends_on=sorted(c.depends_on), env=sorted(c.env),
                     declared_by=sorted(c.declared_by, key=_cite_key))


def _sorted_callers(items):
    for item in items:
        item.callers = sorted(set(item.callers))
    return items


def _sorted_event(e: Event) -> Event:
    e.producers.sort(key=lambda x: (x.component, *_cite_key(x.source)))
    e.consumers.sort(key=lambda x: (x.component, *_cite_key(x.source)))
    return e


def _sorted_db(d: Database) -> Database:
    d.owners.sort()
    d.users.sort()
    d.tables.sort(key=lambda t: (t.name.lower(), *_cite_key(t.source)))
    return d


def _unique(notes: list[NotDerived]) -> list[NotDerived]:
    seen, out = set(), []
    for n in sorted(notes, key=lambda n: (n.kind, n.repo, n.path, n.detail)):
        key = (n.kind, n.repo, n.path, n.detail)
        if key not in seen:
            seen.add(key)
            out.append(n)
    return out


__all__ = ["derive"]
