"""What a repository says it SERVES: OpenAPI, AsyncAPI and proto, read as data.

Each reader turns one parsed document into a declaration — operations, channel ends, rpcs — and a
list of what it could not follow. Which COMPONENT a declaration belongs to is not decided here: a
file does not know that, and `derive.owner_of` decides it once, the same way for all three.

THE TWO DIRECTIONS OF ASYNCAPI 2 ARE THE SPECIFICATION'S, NOT THE ENGLISH. In AsyncAPI 2.x a
channel's `subscribe` operation describes messages the application SENDS (others subscribe to
them) and `publish` describes messages it RECEIVES (others publish them to it) — the inversion
AsyncAPI 3 removed by writing `action: send | receive`. Reading `publish` as "this service
publishes" draws every event arrow backwards, and on a map that is worse than no arrow.

A `$ref` IS FOLLOWED ONLY INTO THE SAME TREE, through `tree.read_text`: a pointer inside the
document, or a relative file of the same repository. A URL is never fetched, a path that climbs out
of the repository is never opened, and each is said, without the reference's text — a URL can
carry a credential in its user part, and nothing of it reaches the map.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field

from openfactory.knowledge.system.contracts import (
    NOT_FOLLOWED,
    PARSE_ERROR,
    TOO_LARGE,
    NotDerived,
    Operation,
    Rpc,
)
from openfactory.knowledge.system.text import Lines, blank_comments, bodies, clip, pairs
from openfactory.knowledge.system.tree import resolve

_METHODS = ("get", "put", "post", "delete", "options", "head", "patch", "trace")
#: Operations one description may contribute. Past it the rest are counted and not listed: a
#: description that large is generated, and the map points at its file either way.
MAX_OPERATIONS = 2000
#: How many `$ref` hops a path item may take before the reader stops following.
MAX_REF_HOPS = 3
#: Services one `.proto` file may contribute; a file with more is generated, or hostile.
MAX_SERVICES = 500

#: `load(rel) -> (document | None, why)` — the caller's reader of another file of the same source.
Load = Callable[[str], tuple[object, str]]


@dataclass
class OpenApiDecl:
    title: str = ""
    version: str = ""
    operations: list[Operation] = field(default_factory=list)
    #: the hosts its `servers` (or Swagger 2's `host`) name — compared with component names, then
    #: dropped; never written to the map as they are
    hosts: list[str] = field(default_factory=list)


@dataclass
class ChannelEnd:
    channel: str
    #: `send` or `receive`, from the declaring application's side
    action: str
    message: str = ""


@dataclass
class AsyncApiDecl:
    title: str = ""
    protocol: str = ""
    hosts: list[str] = field(default_factory=list)
    ends: list[ChannelEnd] = field(default_factory=list)
    #: `(queue name, kind, channel)` from a binding that names a queue
    queues: list[tuple[str, str, str]] = field(default_factory=list)


@dataclass
class ProtoService:
    name: str
    line: int
    rpcs: list[Rpc] = field(default_factory=list)


@dataclass
class ProtoDecl:
    package: str = ""
    services: list[ProtoService] = field(default_factory=list)
    imports: list[str] = field(default_factory=list)


def _host(url: str) -> str:
    """The host of a server URL, lowercase — "" when it has none a component could be named by."""
    text = str(url or "").strip()
    if "://" in text:
        text = text.split("://", 1)[1]
    text = text.rsplit("@", 1)[-1]           # a userinfo part is dropped before anything is kept
    host = re.split(r"[:/?#]", text, maxsplit=1)[0].strip().lower()
    return host if re.fullmatch(r"[a-z0-9][a-z0-9._-]*", host or "") else ""


def _pointer(doc: object, fragment: str) -> object:
    """A JSON pointer (`/paths/~1orders`) into `doc`; None when it names nothing."""
    node = doc
    for raw in [p for p in fragment.split("/") if p != ""]:
        key = raw.replace("~1", "/").replace("~0", "~")
        if isinstance(node, dict):
            node = node.get(key)
        elif isinstance(node, list) and key.isdigit() and int(key) < len(node):
            node = node[int(key)]
        else:
            return None
    return node


def _deref(item: object, *, doc: object, rel: str, load: Load, what: str,
           notes: list[NotDerived], repo: str) -> object:
    """`item`, with a `$ref` followed where it may be — or None, with the reason noted."""
    hops, where, base = 0, rel, doc
    while isinstance(item, dict) and isinstance(item.get("$ref"), str):
        hops += 1
        if hops > MAX_REF_HOPS:
            notes.append(NotDerived(kind=NOT_FOLLOWED, repo=repo, path=rel,
                                    detail=f"{what} is a chain of more than {MAX_REF_HOPS} "
                                           f"references; the rest was not followed"))
            return None
        ref = item["$ref"]
        file_part, _, fragment = ref.partition("#")
        if file_part:
            target = resolve(where, file_part)
            if target is None:
                notes.append(NotDerived(kind=NOT_FOLLOWED, repo=repo, path=rel,
                                        detail=f"{what} is described in a document outside this "
                                               f"repository (a URL or a path out of its tree), "
                                               f"which this layer never opens"))
                return None
            loaded, why = load(target)
            if loaded is None:
                notes.append(NotDerived(kind=NOT_FOLLOWED, repo=repo, path=rel,
                                        detail=f"{what} is described in `{target}`, which {why}"))
                return None
            base, where = loaded, target
        item = _pointer(base, fragment)
        if item is None:
            notes.append(NotDerived(kind=NOT_FOLLOWED, repo=repo, path=rel,
                                    detail=f"{what} points at `#{fragment}`, which names nothing"))
            return None
    return item


def read_openapi(doc: dict, *, rel: str, repo: str, load: Load
                 ) -> tuple[OpenApiDecl, list[NotDerived]]:
    """An OpenAPI 3 or Swagger 2 document: its operations, its title, the hosts it is served on."""
    notes: list[NotDerived] = []
    info = doc.get("info") if isinstance(doc.get("info"), dict) else {}
    out = OpenApiDecl(title=clip(info.get("title"), 120), version=clip(info.get("version"), 40))
    servers = doc.get("servers")
    for server in servers if isinstance(servers, list) else []:
        if isinstance(server, dict) and (host := _host(server.get("url"))):
            out.hosts.append(host)
    if isinstance(doc.get("host"), str) and (host := _host(doc["host"])):
        out.hosts.append(host)
    paths = doc.get("paths")
    if paths is not None and not isinstance(paths, dict):
        notes.append(NotDerived(kind=PARSE_ERROR, repo=repo, path=rel,
                                detail="its `paths` is not a mapping; no operation was read"))
        paths = {}
    skipped = 0
    for path, item in (paths or {}).items():
        item = _deref(item, doc=doc, rel=rel, load=load, what=f"the path `{clip(path, 80)}`",
                      notes=notes, repo=repo)
        if not isinstance(item, dict):
            continue
        for method in _METHODS:
            op = item.get(method)
            if not isinstance(op, dict):
                continue
            if len(out.operations) >= MAX_OPERATIONS:
                skipped += 1
                continue
            out.operations.append(Operation(
                method=method.upper(), path=clip(path, 200),
                operation_id=clip(op.get("operationId"), 120),
                summary=clip(op.get("summary"), 160)))
    if skipped:
        notes.append(NotDerived(kind=TOO_LARGE, repo=repo, path=rel,
                                detail=f"describes {skipped} more operations than the "
                                       f"{MAX_OPERATIONS} the map lists; open the file for them"))
    out.hosts = sorted(set(out.hosts))
    return out, notes


def _message_name(message: object) -> str:
    """The name a message goes by: its `name`, `messageId` or `title`, the last segment of its
    `$ref`, or each of a `oneOf`'s, joined."""
    if isinstance(message, list):
        return " | ".join(n for n in (_message_name(m) for m in message) if n)
    if not isinstance(message, dict):
        return ""
    if isinstance(message.get("oneOf"), list):
        return _message_name(message["oneOf"])
    for key in ("name", "messageId", "title"):
        if isinstance(message.get(key), str) and message[key].strip():
            return clip(message[key], 80)
    ref = message.get("$ref")
    if isinstance(ref, str) and "/" in ref:
        return clip(ref.rsplit("/", 1)[-1], 80)
    return ""


def _binding_queues(bindings: object, channel: str) -> list[tuple[str, str, str]]:
    """The queues a channel's bindings name: an AMQP queue, an SQS queue."""
    out: list[tuple[str, str, str]] = []
    if not isinstance(bindings, dict):
        return out
    amqp = bindings.get("amqp")
    if isinstance(amqp, dict) and isinstance(amqp.get("queue"), dict):
        name = amqp["queue"].get("name")
        if isinstance(name, str) and name.strip():
            out.append((clip(name, 120), "amqp-queue", channel))
    sqs = bindings.get("sqs")
    if isinstance(sqs, dict):
        more = sqs.get("queues")
        queues = [sqs.get("queue")] + (list(more) if isinstance(more, list) else [])
        for q in queues:
            if isinstance(q, dict) and isinstance(q.get("name"), str) and q["name"].strip():
                out.append((clip(q["name"], 120), "sqs-queue", channel))
    return out


def read_asyncapi(doc: dict, *, rel: str, repo: str) -> tuple[AsyncApiDecl, list[NotDerived]]:
    """An AsyncAPI 2 or 3 document: which channels the application sends to and receives from."""
    notes: list[NotDerived] = []
    info = doc.get("info") if isinstance(doc.get("info"), dict) else {}
    out = AsyncApiDecl(title=clip(info.get("title"), 120))
    protocols: set[str] = set()
    servers = doc.get("servers") if isinstance(doc.get("servers"), dict) else {}
    for server in servers.values():
        if not isinstance(server, dict):
            continue
        if isinstance(server.get("protocol"), str):
            protocols.add(server["protocol"].strip().lower())
        host = _host(server.get("host") or server.get("url") or "")
        if host:
            out.hosts.append(host)
    out.protocol = ",".join(sorted(protocols))
    out.hosts = sorted(set(out.hosts))
    major = str(doc.get("asyncapi") or "").strip().split(".", 1)[0]
    channels = doc.get("channels") if isinstance(doc.get("channels"), dict) else {}
    if major == "3":
        address: dict[str, str] = {}
        for key, ch in channels.items():
            where = ch.get("address") if isinstance(ch, dict) else None
            address[str(key)] = clip(where if isinstance(where, str) and where else key, 200)
            if isinstance(ch, dict):
                out.queues += _binding_queues(ch.get("bindings"), address[str(key)])
        operations = doc.get("operations") if isinstance(doc.get("operations"), dict) else {}
        for op_id, op in operations.items():
            if not isinstance(op, dict):
                continue
            action = str(op.get("action") or "").strip().lower()
            ref = (op.get("channel") or {}).get("$ref") if isinstance(op.get("channel"),
                                                                      dict) else None
            key = ref.rsplit("/", 1)[-1].replace("~1", "/").replace("~0", "~") \
                if isinstance(ref, str) and ref.startswith("#/channels/") else ""
            if action not in ("send", "receive") or key not in address:
                notes.append(NotDerived(kind=PARSE_ERROR, repo=repo, path=rel,
                                        detail=f"operation `{clip(op_id, 80)}` names no action "
                                               f"(send or receive) or no channel of this "
                                               f"document; it was not read"))
                continue
            out.ends.append(ChannelEnd(address[key], action, _message_name(op.get("messages"))))
        return out, notes
    if major != "2":
        notes.append(NotDerived(kind=PARSE_ERROR, repo=repo, path=rel,
                                detail=f"declares AsyncAPI version "
                                       f"`{clip(doc.get('asyncapi'), 20)}`, which this layer "
                                       f"does not read (2.x and 3.x only)"))
        return out, notes
    for name, item in channels.items():
        if not isinstance(item, dict):
            continue
        channel = clip(name, 200)
        # THE INVERSION, stated where it is applied: see the module's docstring
        for key, action in (("subscribe", "send"), ("publish", "receive")):
            op = item.get(key)
            if isinstance(op, dict):
                out.ends.append(ChannelEnd(channel, action, _message_name(op.get("message"))))
        out.queues += _binding_queues(item.get("bindings"), channel)
    return out, notes


_PACKAGE = re.compile(r"\bpackage\s+([A-Za-z_][\w.]*)\s*;")
_IMPORT = re.compile(r"\bimport\s+(?:public\s+|weak\s+)?\"([^\"\n]+)\"\s*;")
_SERVICE = re.compile(r"\bservice\s+([A-Za-z_]\w*)\s*\{")
_RPC = re.compile(r"\brpc\s+([A-Za-z_]\w*)\s*\(\s*(stream\s+)?([A-Za-z_.][\w.]*)\s*\)\s*"
                  r"returns\s*\(\s*(stream\s+)?([A-Za-z_.][\w.]*)\s*\)")


def read_proto(text: str) -> ProtoDecl:
    """A `.proto` file: its package, its services and their rpcs, each with the line it is on.
    Comments are blanked first, so a commented-out `rpc` is not an rpc."""
    code = blank_comments(text, line=("//",), block=("/*", "*/"), quotes="\"'")
    closes, lines = pairs(code), Lines(code)
    out = ProtoDecl()
    if m := _PACKAGE.search(code):
        out.package = m.group(1)
    out.imports = sorted({m.group(1) for m in _IMPORT.finditer(code)})
    for m, body_end in bodies(code, list(_SERVICE.finditer(code))[:MAX_SERVICES], closes):
        service = ProtoService(name=m.group(1), line=lines.at(m.start()))
        for r in _RPC.finditer(code, m.end(), body_end):
            service.rpcs.append(Rpc(
                name=r.group(1),
                request=("stream " if r.group(2) else "") + r.group(3),
                response=("stream " if r.group(4) else "") + r.group(5),
                line=lines.at(r.start())))
        out.services.append(service)
    return out


__all__ = ["MAX_OPERATIONS", "AsyncApiDecl", "ChannelEnd", "OpenApiDecl", "ProtoDecl",
           "ProtoService", "read_asyncapi", "read_openapi", "read_proto"]
