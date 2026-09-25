"""What a repository says it RUNS: compose services, Kubernetes workloads, Terraform resources.

A deployment names the components and — through the addresses it hands each one — which talks to
which. `ORDERS_URL: http://orders:8080` in billing's environment is the declaration that billing
calls orders; `DATABASE_URL` pointing at `orders-db` says who uses that database.

A VALUE IS READ ONLY TO BE COMPARED, AND IT NEVER LEAVES THIS MODULE. Each variable is turned, on
the spot, into its NAME and — when its value is an address — the address's scheme and HOST
(`HostRef`); the value itself is dropped. A host is later compared with the names of declared
components, and only a match, or a single-label service name nobody declares, reaches the map. A
password in a connection string, a key in an environment block, a token in a URL's user part: none
survive the first line that reads them. A Kubernetes Secret's `data` and `stringData` are never
read at all, and a compose `env_file` is never opened — each is said, by name, as not read.

TEXT ONLY. Compose files are read with the safe loader and merged by nobody: `include:` and an
`extends:` that names another file are named as not followed, never fetched, because following them
is what the compose CLI does and this layer runs no CLI. A Helm chart is a program that renders
YAML; it is named, and its templates are not read. Terraform is read as blocks and literal
attributes: a module from elsewhere is never fetched, a variable is never evaluated, a provisioner
is never run.
"""

from __future__ import annotations

import posixpath
import re
from dataclasses import dataclass, field
from urllib.parse import urlsplit

import yaml

from openfactory.knowledge.system.contracts import (
    AT_RUN_TIME,
    NOT_FOLLOWED,
    NOT_READ,
    PARSE_ERROR,
    TOO_LARGE,
    NotDerived,
)
from openfactory.knowledge.system.text import (
    Lines,
    blank_comments,
    clip,
    documents,
    load_yaml,
    pairs,
)
from openfactory.knowledge.system.text import bodies as _bodies

# ── addresses ───────────────────────────────────────────────────────────────────────────────────

#: A variable whose NAME says it holds an address. Only these are worth saying when their value
#: cannot be read (a secret, `${…}`): a `LOG_LEVEL` from a secret is not a blind spot on the map.
_ADDRESS_NAME = re.compile(r"(^|_)(URL|URI|DSN|HOST|HOSTNAME|ADDR|ADDRESS|ENDPOINT|SERVER|SERVERS|"
                           r"BROKERS?|BOOTSTRAP_SERVERS)($|_)", re.IGNORECASE)
#: A variable whose name says its value is a bare host (`ORDERS_HOST=orders`) — stricter than
#: `_ADDRESS_NAME`, because a bare word is read as a host only where the name leaves no doubt.
_HOST_NAME = re.compile(r"(^|_)(HOST|HOSTNAME|ADDR|ADDRESS|SERVER|SERVICE|SERVICE_NAME)$",
                        re.IGNORECASE)
_BARE_HOST = re.compile(r"[a-z0-9][a-z0-9.-]{0,252}")
_NOT_HOSTS = frozenset({"true", "false", "yes", "no", "on", "off", "none", "null", "nil"})
_HOST_PORT = re.compile(r"(?P<host>[A-Za-z0-9][A-Za-z0-9.-]*):\d{1,5}(?:/.*)?")
#: Hosts that are the component itself, the machine, or nowhere — never another component.
_SELF_HOSTS = frozenset({"localhost", "127.0.0.1", "0.0.0.0", "::1", "host.docker.internal"})


def address_name(name: str) -> bool:
    return bool(_ADDRESS_NAME.search(name or ""))


@dataclass(frozen=True)
class HostRef:
    """What an address in a variable points at — the variable's NAME, the scheme and the HOST, and
    nothing else of the value."""

    name: str
    scheme: str
    host: str


def host_ref(name: str, value: object) -> HostRef | None:
    """The host `value` addresses, for the variable `name` — None when it addresses none.

    `http://orders:8080`, `postgres://u:p@orders-db:5432/orders`, `jdbc:postgresql://db/x`,
    `kafka:9092` and, for a variable named like a host, `orders` — each becomes a `HostRef`; the
    user part, the port, the path and the query are dropped by the parse and never kept."""
    if not isinstance(value, str | int | float) or isinstance(value, bool):
        return None
    text = str(value).strip()
    if not text or is_interpolated(text):
        return None
    if text.lower().startswith("jdbc:"):
        text = text[5:]
    first = re.split(r"[,\s]", text, maxsplit=1)[0]        # a broker list: the first address
    scheme, host = "", ""
    if "://" in first:
        try:
            parts = urlsplit(first)
            scheme, host = parts.scheme.lower(), (parts.hostname or "")
        except ValueError:
            return None
    elif m := _HOST_PORT.fullmatch(first):
        host = m.group("host")
    elif _HOST_NAME.search(name or "") and _BARE_HOST.fullmatch(first.lower()) \
            and not first.isdigit() and first.lower() not in _NOT_HOSTS:
        host = first
    host = host.lower().strip(".")
    if not host or host in _SELF_HOSTS or "$" in host:
        return None
    return HostRef(name=name, scheme=scheme, host=host)


def is_interpolated(value: object) -> bool:
    """Whether a value is supplied wholly by the environment a service is started in (`${X}`)."""
    return isinstance(value, str) and bool(re.fullmatch(r"\s*\$\{[^}]+\}\s*|\s*\$[A-Za-z_]\w*\s*",
                                                        value))


# ── what a component's image says it is ─────────────────────────────────────────────────────────

#: A word in an image's name, and the kind of component it makes. Matched against the words of the
#: whole reference (`bitnami/kafka:3.6` → bitnami, kafka), so a vendor's packaging does not hide
#: the engine. A built service, or an image with none of these words, is a `service`.
_IMAGE_WORDS: tuple[tuple[str, frozenset[str]], ...] = (
    ("database", frozenset({"postgres", "postgresql", "postgis", "mysql", "mariadb", "mongo",
                            "mongodb", "mssql", "sqlserver", "cockroach", "cockroachdb",
                            "cassandra", "scylla", "couchdb", "oracle", "timescaledb",
                            "clickhouse", "neo4j", "influxdb", "dynamodb", "cosmosdb"})),
    ("broker", frozenset({"kafka", "rabbitmq", "nats", "activemq", "artemis", "pulsar",
                          "redpanda", "mosquitto", "emqx", "elasticmq", "zookeeper"})),
    ("cache", frozenset({"redis", "memcached", "valkey", "keydb", "dragonfly"})),
    ("search", frozenset({"elasticsearch", "opensearch", "solr", "meilisearch", "typesense"})),
)


def image_kind(image: str) -> tuple[str, str]:
    """`(kind, engine)` an image names: `postgres:16-alpine` → `("database", "postgres")`."""
    ref = (image or "").lower().split("@", 1)[0]
    path = ref.rsplit(":", 1)[0] if ref.count(":") and "/" not in ref.rsplit(":", 1)[1] else ref
    words = set(re.split(r"[/_.\-:]", path))
    for kind, names in _IMAGE_WORDS:
        hit = sorted(words & names)
        if hit:
            return kind, hit[0]
    return "service", ""


def image_repository(image: str) -> str:
    """The last path segment of an image's repository: `ghcr.io/acme/orders:1.2` → `orders`."""
    ref = (image or "").split("@", 1)[0]
    last = ref.rsplit("/", 1)[-1]
    return last.split(":", 1)[0].lower()


# ── compose ─────────────────────────────────────────────────────────────────────────────────────

@dataclass
class Deployed:
    """One component as one deployment file declares it."""

    name: str
    line: int = 0
    image: str = ""
    #: `(repository-relative directory, None)` when the build context is inside this repository;
    #: `(path under a sibling, sibling name)` when it climbs out into a sibling directory
    build: tuple[str, str | None] | None = None
    depends_on: list[str] = field(default_factory=list)
    env: list[str] = field(default_factory=list)
    refs: list[HostRef] = field(default_factory=list)
    #: address-named variables whose value this layer did not or could not read, with why
    unresolved: list[tuple[str, str]] = field(default_factory=list)
    #: Kubernetes: the labels its pods carry, for a Service's selector
    labels: dict[str, str] = field(default_factory=dict)


def _env_items(env: object) -> list[tuple[str, object]]:
    """A compose `environment:` as `(name, value)` pairs, from its mapping or its list form."""
    if isinstance(env, dict):
        return [(str(k), v) for k, v in env.items()]
    out = []
    for item in env if isinstance(env, list) else []:
        if isinstance(item, str):
            name, _, value = item.partition("=")
            out.append((name.strip(), value if "=" in item else None))
    return out


def _take_env(target: Deployed, items: list[tuple[str, object]]) -> None:
    """Names kept, values turned into host references and dropped, on the spot."""
    for name, value in items:
        if not name:
            continue
        target.env.append(name)
        if (ref := host_ref(name, value)) is not None:
            target.refs.append(ref)
        elif address_name(name) and (value is None or "$" in str(value)):
            target.unresolved.append((name, "at-run-time"))


def read_compose(text: str, *, rel: str, repo: str) -> tuple[list[Deployed], list[NotDerived]]:
    """A compose file's services — image, build context, start order, environment by name."""
    notes: list[NotDerived] = []
    doc = load_yaml(text)
    if doc is None:
        return [], notes
    if not isinstance(doc, dict):
        return [], [NotDerived(kind=PARSE_ERROR, repo=repo, path=rel,
                               detail="is not a compose file: its top level is not a mapping")]
    if "include" in doc:
        notes.append(NotDerived(kind=NOT_FOLLOWED, repo=repo, path=rel,
                                detail="includes other compose files (`include:`), which are not "
                                       "followed; list them where the map can read them"))
    services = doc.get("services")
    if not isinstance(services, dict):
        return [], notes
    lines = _service_lines(text)
    here = posixpath.dirname(rel)
    out = []
    for name, svc in services.items():
        if not isinstance(svc, dict):
            continue
        name = str(name)
        line = lines.get(name, 0)
        d = Deployed(name=name, line=line, image=clip(svc.get("image"), 200)
                     if isinstance(svc.get("image"), str) else "")
        build = svc.get("build")
        context = build if isinstance(build, str) else (
            build.get("context") if isinstance(build, dict) else None)
        if isinstance(context, str) and context.strip():
            d.build = _context(here, context.strip())
            if d.build is None:
                notes.append(NotDerived(kind=NOT_FOLLOWED, repo=repo, path=rel,
                                        detail=f"`{name}` builds from a context that is absolute, "
                                               f"a URL or a variable; where its code lives is "
                                               f"not derived"))
        deps = svc.get("depends_on")
        d.depends_on = sorted(x for x in (deps.keys() if isinstance(deps, dict)
                                          else deps if isinstance(deps, list) else [])
                              if isinstance(x, str))
        _take_env(d, _env_items(svc.get("environment")))
        env_file = svc.get("env_file")
        if env_file:
            notes.append(NotDerived(kind=NOT_READ, repo=repo, path=rel,
                                    detail=f"`{name}` takes part of its environment from an env "
                                           f"file, which this layer never opens (it is where "
                                           f"secrets live); the addresses in it are not derived"))
        extends = svc.get("extends")
        if isinstance(extends, dict) and extends.get("file"):
            notes.append(NotDerived(kind=NOT_FOLLOWED, repo=repo, path=rel,
                                    detail=f"`{name}` extends a service of another file, which is "
                                           f"not followed"))
        out.append(d)
    return out, notes


_KEY = re.compile(r"""^([ \t]+)['"]?([^'":#\s][^'":#]*?)['"]?[ \t]*:""")


def _service_lines(text: str) -> dict[str, int]:
    """Each service's line: the keys directly under `services:`, at the indentation of the first
    one — one pass, so a nested key that happens to share a service's name is never taken for it."""
    out: dict[str, int] = {}
    inside, indent = False, None
    for number, line in enumerate(text.splitlines(), start=1):
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if not line[0].isspace():
            inside = bool(re.match(r"services[ \t]*:", line))
            continue
        if not inside:
            continue
        m = _KEY.match(line)
        if m is None:
            continue
        if indent is None:
            indent = m.group(1)
        if m.group(1) == indent:
            out.setdefault(m.group(2), number)
    return out


def _context(here: str, context: str) -> tuple[str, str | None] | None:
    """A build context resolved against the compose file's directory: inside this repository, or
    under a sibling directory the context climbs into (`../orders` → `("", "orders")`)."""
    if context.startswith(("/", "~", "git@")) or "://" in context or "$" in context:
        return None
    joined = posixpath.normpath(posixpath.join(here or ".", context))
    if joined == ".." or joined.startswith("../"):
        rest = joined[3:] if joined.startswith("../") else ""
        if not rest or rest.startswith("../"):
            return None
        sibling, _, inner = rest.partition("/")
        return (inner or ".", sibling)
    return (joined or ".", None)


# ── Kubernetes ──────────────────────────────────────────────────────────────────────────────────

_WORKLOADS = frozenset({"Deployment", "StatefulSet", "DaemonSet", "ReplicaSet", "Job", "CronJob",
                        "Pod", "Rollout"})


@dataclass
class K8sService:
    name: str
    selector: dict[str, str]
    line: int = 0


@dataclass
class K8sRead:
    workloads: list[Deployed] = field(default_factory=list)
    services: list[K8sService] = field(default_factory=list)
    #: ConfigMap name → the host references its data holds, keyed by the data key
    config_maps: dict[str, dict[str, HostRef | None]] = field(default_factory=dict)
    #: `(workload, variable, config map, key or "")` — resolved once every file is read
    from_config: list[tuple[str, str, str, str]] = field(default_factory=list)


def _list(value: object) -> list:
    """`value` when a manifest wrote a list there, else nothing — a manifest is somebody else's
    input, and a number where a list belongs is a malformed file, not a reason to stop reading."""
    return value if isinstance(value, list) else []


def _pod_spec(kind: str, spec: dict, meta: dict) -> tuple[dict, dict]:
    """`(pod spec, pod labels)` of a workload, wherever its kind keeps them — a bare Pod's own
    metadata, everything else's pod template."""
    if kind == "Pod":
        labels = meta.get("labels") if isinstance(meta.get("labels"), dict) else {}
        return spec, labels
    if kind == "CronJob":
        job = spec.get("jobTemplate") if isinstance(spec.get("jobTemplate"), dict) else {}
        spec = job.get("spec") if isinstance(job.get("spec"), dict) else {}
    template = spec.get("template") if isinstance(spec.get("template"), dict) else {}
    meta = template.get("metadata") if isinstance(template.get("metadata"), dict) else {}
    labels = meta.get("labels") if isinstance(meta.get("labels"), dict) else {}
    pod = template.get("spec") if isinstance(template.get("spec"), dict) else {}
    return pod, labels


def read_kubernetes(text: str, *, rel: str, repo: str, into: K8sRead) -> list[NotDerived]:
    """Every document of a Kubernetes file: workloads, Services, ConfigMaps. A Secret is skipped
    whole — its values are never read, and a variable taken from one is said as not read."""
    notes: list[NotDerived] = []
    for line, chunk in documents(text):
        try:
            doc = load_yaml(chunk)
        except (yaml.YAMLError, ValueError, TypeError, RecursionError) as exc:
            notes.append(NotDerived(kind=PARSE_ERROR, repo=repo, path=rel,
                                    detail=f"the document at line {line} did not parse "
                                           f"({clip(getattr(exc, 'problem', None) or exc, 120)})"))
            continue
        if not isinstance(doc, dict) or not isinstance(doc.get("kind"), str):
            continue
        kind = doc["kind"]
        meta = doc.get("metadata") if isinstance(doc.get("metadata"), dict) else {}
        name = meta.get("name") if isinstance(meta.get("name"), str) else ""
        spec = doc.get("spec") if isinstance(doc.get("spec"), dict) else {}
        if kind == "Service" and name:
            selector = spec.get("selector") if isinstance(spec.get("selector"), dict) else {}
            into.services.append(K8sService(name=name, line=line,
                                            selector={str(k): str(v)
                                                      for k, v in selector.items()}))
        elif kind == "ConfigMap" and name:
            data = doc.get("data") if isinstance(doc.get("data"), dict) else {}
            into.config_maps[name] = {str(k): host_ref(str(k), v) for k, v in data.items()}
        elif kind in _WORKLOADS and name:
            pod, labels = _pod_spec(kind, spec, meta)
            d = Deployed(name=name, line=line,
                         labels={str(k): str(v) for k, v in labels.items()})
            for container in _list(pod.get("containers")) + _list(pod.get("initContainers")):
                if not isinstance(container, dict):
                    continue
                if isinstance(container.get("image"), str) and not d.image:
                    d.image = clip(container["image"], 200)
                for var in _list(container.get("env")):
                    if not isinstance(var, dict) or not var.get("name"):
                        continue
                    vname = str(var["name"])
                    source = var.get("valueFrom") if isinstance(var.get("valueFrom"), dict) else {}
                    if "value" in var:
                        _take_env(d, [(vname, var.get("value"))])
                    elif isinstance(source.get("configMapKeyRef"), dict):
                        d.env.append(vname)
                        ref = source["configMapKeyRef"]
                        into.from_config.append((name, vname, str(ref.get("name") or ""),
                                                 str(ref.get("key") or "")))
                    elif isinstance(source.get("secretKeyRef"), dict):
                        d.env.append(vname)
                        if address_name(vname):
                            d.unresolved.append((vname, "secret"))
                    else:
                        d.env.append(vname)
                for env_from in _list(container.get("envFrom")):
                    if not isinstance(env_from, dict):
                        continue
                    cm = env_from.get("configMapRef")
                    if isinstance(cm, dict) and cm.get("name"):
                        into.from_config.append((name, "", str(cm["name"]), ""))
                    secret = env_from.get("secretRef")
                    if isinstance(secret, dict):
                        d.unresolved.append((str(secret.get("name") or "?"), "secret-all"))
            into.workloads.append(d)
    return notes


# ── Terraform ───────────────────────────────────────────────────────────────────────────────────

#: Resource types the map knows, and what each is. A TABLE OF THE FORMAT'S OWN VOCABULARY: the
#: resource types are how a Terraform file says "a queue" or "a database", and the core talks to
#: none of these providers. A type not listed here is not a component or a queue of the map, and is
#: not listed as missing either — most of a Terraform tree is networking and permissions.
TF_KINDS: dict[str, str] = {
    **dict.fromkeys(("aws_db_instance", "aws_rds_cluster", "aws_dynamodb_table",
                     "aws_docdb_cluster", "aws_neptune_cluster", "google_sql_database_instance",
                     "google_spanner_instance", "google_firestore_database",
                     "google_bigtable_instance", "azurerm_postgresql_server",
                     "azurerm_postgresql_flexible_server", "azurerm_mysql_server",
                     "azurerm_mysql_flexible_server", "azurerm_mssql_server",
                     "azurerm_mssql_database", "azurerm_cosmosdb_account"), "database"),
    **dict.fromkeys(("aws_elasticache_cluster", "aws_elasticache_replication_group",
                     "google_redis_instance", "azurerm_redis_cache"), "cache"),
    **dict.fromkeys(("aws_msk_cluster", "aws_mq_broker", "azurerm_servicebus_namespace",
                     "azurerm_eventhub_namespace", "confluent_kafka_cluster"), "broker"),
    **dict.fromkeys(("aws_ecs_service", "aws_lambda_function", "aws_apprunner_service",
                     "google_cloud_run_service", "google_cloud_run_v2_service",
                     "google_cloudfunctions_function", "google_cloudfunctions2_function",
                     "azurerm_container_app", "azurerm_linux_web_app", "azurerm_windows_web_app",
                     "azurerm_function_app", "azurerm_linux_function_app",
                     "kubernetes_deployment", "kubernetes_deployment_v1"), "compute"),
    "aws_sqs_queue": "queue",
    "aws_sns_topic": "topic",
    "aws_kinesis_stream": "stream",
    "google_pubsub_topic": "topic",
    "google_pubsub_subscription": "subscription",
    "azurerm_servicebus_queue": "queue",
    "azurerm_servicebus_topic": "topic",
    "azurerm_eventhub": "stream",
    "azurerm_storage_queue": "queue",
    "confluent_kafka_topic": "topic",
    "kafka_topic": "topic",
}
#: The kinds that are queues and topics — the map's `queues` rather than its infrastructure.
TF_QUEUE_KINDS = frozenset({"queue", "topic", "stream", "subscription"})
#: The attributes read, and only these: a name and an engine. A `password`, a `connection_string`,
#: a `master_password` — every other attribute — is never read.
_TF_NAME_KEYS = ("name", "identifier", "cluster_identifier", "function_name", "cluster_name",
                 "broker_name", "replication_group_id", "cluster_id", "topic_name", "queue_name")
_TF_ENGINE_KEYS = ("engine", "database_version", "engine_type", "kind")
_TF_BLOCK = re.compile(r'^[ \t]*(resource|data|module)[ \t]+"([^"\n]+)"(?:[ \t]+"([^"\n]+)")?'
                       r'[ \t]*\{', re.MULTILINE)
_TF_SOURCE = re.compile(r'^[ \t]*source[ \t]*=[ \t]*"([^"\n]*)"', re.MULTILINE)
_HEREDOC = re.compile(r"<<-?[ \t]*([A-Za-z_]\w*)[ \t]*\n")
#: Blocks one Terraform file may contribute; past it the file is generated, or hostile.
MAX_TF_BLOCKS = 5000


@dataclass
class TfResource:
    type: str
    label: str
    kind: str
    line: int
    name: str = ""
    engine: str = ""


def _blank_heredocs(text: str) -> str:
    """Heredoc bodies (`<<EOF … EOF`) replaced by spaces, newlines kept: their text is a value,
    and a quote or a brace inside one must not be read as HCL. One pass: each body is found from
    where the last one ended, and a `<<` inside a body is part of that body."""
    out: list[str] = []
    pos = 0
    for m in _HEREDOC.finditer(text):
        if m.start() < pos:
            continue
        close = re.compile(rf"^[ \t]*{re.escape(m.group(1))}[ \t]*$", re.MULTILINE)
        end = close.search(text, m.end())
        stop = end.start() if end else len(text)
        out.append(text[pos:m.end()])
        out.append(re.sub(r"[^\n]", " ", text[m.end():stop]))
        pos = stop
    out.append(text[pos:])
    return "".join(out)


def _tf_literal(body: str, keys: tuple[str, ...]) -> str:
    """The first of `keys` assigned a plain string literal at the top level of a block body."""
    depth = 0
    for line in body.splitlines():
        if depth == 0:
            m = re.match(r'\s*([A-Za-z_][\w-]*)\s*=\s*"([^"$]*)"\s*$', line)
            if m and m.group(1) in keys:
                return clip(m.group(2), 120)
        depth += line.count("{") - line.count("}")
    return ""


def read_terraform(text: str, *, rel: str, repo: str) -> tuple[list[TfResource], list[NotDerived]]:
    """The resources of a `.tf` file whose type the map knows, and the modules it does not
    follow. Blocks are found by brace matching over the text with comments and heredocs blanked."""
    notes: list[NotDerived] = []
    code = blank_comments(_blank_heredocs(text), line=("#", "//"), block=("/*", "*/"), quotes='"')
    closes, lines = pairs(code, quotes='"'), Lines(code)
    found = list(_TF_BLOCK.finditer(code))
    if len(found) > MAX_TF_BLOCKS:
        notes.append(NotDerived(kind=TOO_LARGE, repo=repo, path=rel,
                                detail=f"declares more than {MAX_TF_BLOCKS} blocks; the rest were "
                                       f"not read"))
    out = []
    for m, end in _bodies(code, found[:MAX_TF_BLOCKS + 1], closes)[:MAX_TF_BLOCKS]:
        block, first, second = m.group(1), m.group(2), m.group(3)
        body = code[m.end(): end]
        line = lines.at(m.start())
        if block == "module":
            source = _TF_SOURCE.search(body)
            local = source and source.group(1).startswith(("./", "../"))
            if not local:
                notes.append(NotDerived(kind=NOT_FOLLOWED, repo=repo, path=rel,
                                        detail=f"module `{first}` (line {line}) comes from "
                                               f"outside this repository and is not fetched; "
                                               f"what it declares is not derived"))
            continue
        if block != "resource" or not second or first not in TF_KINDS:
            continue
        out.append(TfResource(type=first, label=second, kind=TF_KINDS[first], line=line,
                              name=_tf_literal(body, _TF_NAME_KEYS),
                              engine=_tf_literal(body, _TF_ENGINE_KEYS)))
    return out, notes


def read_terraform_json(doc: object, *, rel: str, repo: str) -> list[TfResource]:
    """The same, from `.tf.json`: `{"resource": {"<type>": {"<label>": {...}}}}`."""
    out: list[TfResource] = []
    resources = doc.get("resource") if isinstance(doc, dict) else None
    blocks = resources if isinstance(resources, list) else [resources]
    for block in blocks:
        if not isinstance(block, dict):
            continue
        for rtype, labelled in block.items():
            if rtype not in TF_KINDS or not isinstance(labelled, dict):
                continue
            for label, attrs in labelled.items():
                attrs = attrs[0] if isinstance(attrs, list) and attrs else attrs
                attrs = attrs if isinstance(attrs, dict) else {}

                def literal(keys: tuple[str, ...], attrs=attrs) -> str:
                    for k in keys:
                        v = attrs.get(k)
                        if isinstance(v, str) and "$" not in v:
                            return clip(v, 120)
                    return ""

                out.append(TfResource(type=rtype, label=str(label), kind=TF_KINDS[rtype], line=0,
                                      name=literal(_TF_NAME_KEYS),
                                      engine=literal(_TF_ENGINE_KEYS)))
    return out


__all__ = ["AT_RUN_TIME", "TF_KINDS", "TF_QUEUE_KINDS", "Deployed", "HostRef", "K8sRead",
           "K8sService", "TfResource", "address_name", "host_ref", "image_kind",
           "image_repository", "is_interpolated", "read_compose", "read_kubernetes",
           "read_terraform", "read_terraform_json"]
