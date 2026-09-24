"""The system map as files: `system.yaml`, `api.yaml`, `schema.yaml`, `adr-index.yaml`, `index.md`.

WHERE THEY LIVE: `.okf/system/` in the product's CONTEXT repository — beside `.okf/repos/`, the
per-source bundles, because the system belongs to no one source (ADR-0052 D17). `okf.py` already
reserves the `.okf/` root for what crosses repositories, and one directory under it keeps the five
files together and out of the way of `index.md`, the front door onboarding writes at the root.

    system.yaml      the sources read, the components, the links between them, the queues, the
                     infrastructure, and everything that could not be derived
    api.yaml         the interfaces: HTTP APIs with their operations, gRPC services, events with
                     their producers and consumers
    schema.yaml      the databases: each schema, its owners and its users
    adr-index.yaml   the decision records of every source
    index.md         the door, for a person and for the product role — what could NOT be derived
                     comes first, before anything the map does say (the order `okf.render_index`
                     keeps, for its reason)

DETERMINISTIC, AND IT CONVERGES. The files are written with sorted keys from pre-sorted lists, so
one state of the sources is one set of bytes. `derived_key` hashes the map with every commit and
the clock blanked: a commit that changed nothing the layer reads leaves the key where it was, and
the refresh publishes nothing (`knowledge-layer.md` §22 D-5, one artefact along) — one commit in
the context repository per real change to the system, never one per merge.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import yaml

from openfactory.knowledge.system.contracts import SystemMap

SYSTEM_DIRNAME = "system"
SYSTEM_FILE = "system.yaml"
API_FILE = "api.yaml"
SCHEMA_FILE = "schema.yaml"
ADR_INDEX_FILE = "adr-index.yaml"
INDEX_FILE = "index.md"
FILES = (SYSTEM_FILE, API_FILE, SCHEMA_FILE, ADR_INDEX_FILE, INDEX_FILE)

#: The sentence that stops a reader taking the map for the system. Written into `system.yaml` and
#: at the top of `index.md`.
SCOPE_LIMIT = (
    "Derived without a model from what the product's repositories declare — OpenAPI, AsyncAPI, "
    "proto, migrations, compose, Kubernetes and Terraform — read as text; nothing in them was "
    "run. Every entry cites the file and the commit it came from. What a repository does not "
    "declare (an address chosen at run time, a call made through code no description names) is "
    "not here, and what could not be derived is listed. Test, example, vendored and build "
    "directories are not read. It says where to look; the code says what is true.")


class _NoAliases(yaml.SafeDumper):
    """A dumper that writes every repeated value out again rather than as an anchor and an
    alias: the files are read by people and by roles that grep them, and `*id001` is neither."""

    def ignore_aliases(self, data):
        return True


def _dump(data: object) -> str:
    """Deterministic YAML — the contract `okf._dump` states: sorted keys, block style, no
    aliases, unicode kept."""
    return yaml.dump(data, Dumper=_NoAliases, sort_keys=True, default_flow_style=False,
                     allow_unicode=True, width=100)


def _plain(model) -> object:
    return model.model_dump(by_alias=True, mode="json")


def derived_key(system: SystemMap) -> str:
    """The map's identity with every provenance stamp blanked — the commit on each citation, the
    commit of each source, and the clock. Equal keys: the refresh has nothing to publish."""
    data = _plain(system)
    data["generated_at"] = ""

    def blank(node: object) -> object:
        if isinstance(node, dict):
            return {k: ("" if k == "commit" else blank(v)) for k, v in node.items()}
        if isinstance(node, list):
            return [blank(v) for v in node]
        return node

    raw = json.dumps(blank(data), sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def render(system: SystemMap) -> dict[str, str]:
    """`{file name: text}` for the five files."""
    data = _plain(system)
    head = {"version": data["version"], "derived_key": derived_key(system)}
    if data["generated_at"]:
        head["generated_at"] = data["generated_at"]
    return {
        SYSTEM_FILE: _dump({**head, "scope_limit": SCOPE_LIMIT, "sources": data["sources"],
                            "components": data["components"], "links": data["links"],
                            "queues": data["queues"], "infrastructure": data["infrastructure"],
                            "not_derived": data["not_derived"]}),
        API_FILE: _dump({**head, "http": data["http"], "grpc": data["grpc"],
                         "events": data["events"]}),
        SCHEMA_FILE: _dump({**head, "databases": data["databases"]}),
        ADR_INDEX_FILE: _dump({**head, "adrs": data["adrs"]}),
        INDEX_FILE: render_index(system),
    }


def write_system(system: SystemMap, into: str | Path) -> list[Path]:
    """The five files, written INTO `into` (the caller chooses the directory, as `write_okf`'s
    caller does). Returns the paths written, sorted."""
    out = Path(into)
    out.mkdir(parents=True, exist_ok=True)
    written = []
    for name, text in render(system).items():
        (out / name).write_text(text, encoding="utf-8")
        written.append(out / name)
    return sorted(written)


def read_derived_key(root: str | Path, rel: str) -> str:
    """The `derived_key` the `system.yaml` at `rel` under `root` carries — "" when there is none to
    read. Read through `tree.read_text`, like every file of a checkout: a `system.yaml` somebody
    replaced with a link out of the context repository is not followed."""
    from openfactory.knowledge.system.tree import read_text

    got = read_text(root, rel)
    if got.text is None:
        return ""
    try:
        data = yaml.safe_load(got.text)
    except (yaml.YAMLError, ValueError, RecursionError):
        return ""
    return str(data.get("derived_key") or "") if isinstance(data, dict) else ""


def _where(cite) -> str:
    line = f":{cite.line}" if cite.line else ""
    return f"`{cite.repo}` `{cite.path}{line}`"


def render_index(system: SystemMap) -> str:
    """The door: what could not be derived, then the components and how they talk."""
    lines = ["# The system, across the product's sources", "", "> " + SCOPE_LIMIT, ""]
    lines += ["## What this map could not derive", ""]
    if system.not_derived:
        for n in system.not_derived:
            where = f"`{n.repo}`" + (f" `{n.path}`" if n.path else "") if n.repo else ""
            lines.append(f"- **{n.kind}** — {where + ': ' if where else ''}{n.detail}")
    else:
        lines.append("- Nothing was recorded as not derived by the pass that wrote this.")
    lines += ["", "## Sources", ""]
    for s in system.sources:
        if s.missing:
            lines.append(f"- `{s.repo}` — NOT READ: {s.missing}")
        else:
            lines.append(f"- `{s.repo}` @ `{s.commit[:12] or '(no commit)'}` — {s.files} "
                         f"declaration file(s) read"
                         + (f"; not checked out, holding only pictures, fonts or binaries: "
                            f"{', '.join(f'`{d}`' for d in s.left_out)}" if s.left_out else ""))
    lines += ["", "## Components", ""]
    if not system.components:
        lines.append("- None was declared.")
    for c in system.components:
        code = f" — code in `{c.repo}` `{c.code}`" if c.repo else ""
        lines.append(f"- **{c.name}** ({c.kind}){code}")
        for link in [lk for lk in system.links if lk.from_ == c.name]:
            lines.append(f"  - talks to **{link.to}** ({link.kind}, {link.via})")
    for heading, file_name, count in (
            ("Interfaces", API_FILE, len(system.http) + len(system.grpc) + len(system.events)),
            ("Databases", SCHEMA_FILE, len(system.databases)),
            ("Decision records", ADR_INDEX_FILE, len(system.adrs))):
        lines += ["", f"## {heading}", "", f"{count} in [`{file_name}`]({file_name})."]
    if system.http:
        lines.append("")
        for a in system.http:
            lines.append(f"- HTTP API of **{a.component}** — {len(a.operations)} operation(s), "
                         f"{_where(a.source)}")
    if system.events:
        lines.append("")
        for e in system.events:
            senders = ", ".join(sorted({p.component for p in e.producers})) or "nobody declared"
            receivers = ", ".join(sorted({c.component for c in e.consumers})) or "nobody declared"
            lines.append(f"- event `{e.channel}` — sent by {senders}; received by {receivers}")
    if system.databases:
        lines.append("")
        for d in system.databases:
            owners = ", ".join(d.owners) or "no migrations"
            users = f"; also used by {', '.join(d.users)}" if d.users else ""
            lines.append(f"- database **{d.name}** — {len(d.tables)} table(s), owned by "
                         f"{owners}{users}")
    return "\n".join(lines).rstrip() + "\n"


__all__ = ["ADR_INDEX_FILE", "API_FILE", "FILES", "INDEX_FILE", "SCHEMA_FILE", "SCOPE_LIMIT",
           "SYSTEM_DIRNAME", "SYSTEM_FILE", "derived_key", "read_derived_key", "render",
           "render_index", "write_system"]
