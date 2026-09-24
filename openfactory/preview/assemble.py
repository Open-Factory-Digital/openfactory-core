"""Assembling a preview: which service is built from the change, which tree each path is read
from, and what the operator's policy sets (ADR-0050 D2, D4, D8; the design on #265, §5.3).

Pure apart from reading the unit's own checkouts, which admission must see on disk. No docker, no
git, no engine: the canonical document comes in (`read.shape`), a `PreviewPlan` or a `Refused`
goes out, and a runtime row runs the plan.

FROM THE CHANGE, OR FROM BASE — DERIVED, NEVER DECLARED (D2). A service is made of its build
context and the sources of its bind mounts: its INPUTS. It is from the change exactly when the
change's own diff (merge base to head) touches one of them. A single-Dockerfile repository has one
service whose input is `.`, so any change rebuilds it and nobody declares a component; a
monorepo's `web/` and `api/` contexts partition the diff on their own. Then:

- a service from the change is re-rooted into `<workdir>/change/<dir>`, and when it builds, it
  loses its `image:` — compose tags the build `<compose_project>-<svc>`, removed with the stack,
  and never the client's `ghcr.io/acme/api:latest`, which would otherwise be retagged on a shared
  daemon and served as "base" to the next preview;
- a service not from the change that names an image loses its `build:` and pulls `always`, so the
  base is what the client's CI publishes today, not what was pulled the first day.

A CHANGE THE PREVIEW WOULD NOT SHOW IS REFUSED, NOT SHOWN. When the diff touches no service's
inputs — every service runs a published image and mounts nothing, or the change is in files no
service is made from — the plan is refused with the paths and the services named: a preview that
looks exactly like production and says "this change" is the worst answer it could give.

WHAT THE OPERATOR SETS, NOT THE FILE. Limits, capabilities, `no-new-privileges`, `restart: "no"`
(a daemon-driven restart re-resolves bind sources from a tree a container may have rewritten since
admission — supervision is the workflow's), the platform's labels, the networks, the volume names,
and the NAMES a service may receive: a registry name reaches a container as `${WORKER_NAME}` and
never as a value, and reaches a BUILD only when the operator listed it under `build_args` — an
unmerged Dockerfile with internet access can read a build argument, and it lands in the image's
history.
"""

from __future__ import annotations

import copy
import hashlib
import os
import posixpath
import re
from collections.abc import Iterable
from typing import Literal

from openfactory import preview
from openfactory.contracts.manifest import PreviewConfig
from openfactory.contracts.project import PreviewPolicy
from openfactory.preview.admit import admit, as_map
from openfactory.preview.plan import Layout, PreviewPlan, Refused, TreePath, Unit

#: The factory's own shape files, whatever the manifest names: a change to any of them changes
#: what a preview WOULD run, and the preview runs the base's.
SHAPE_FILES = (".openfactory/preview.compose.yml", ".openfactory/product.yaml")
SHAPE_DIR = ".openfactory/preview/"

#: Hosts an environment value may name without leaving the preview.
_LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1", "0.0.0.0", "::1", "[::1]"})
_URL_HOST = re.compile(r"(?i)\b[a-z][a-z0-9+.-]*://(?:[^@/\s]*@)?(\[[^\]]+\]|[^:/\s?#,;@]+)")
_REF = re.compile(r"\$\{[^{}]*\}")
_SIZE = re.compile(r"(?i)^\s*(\d+(?:\.\d+)?)\s*([kmgt]?)i?b?\s*$")
_UNITS = {"": 1, "k": 1024, "m": 1024 ** 2, "g": 1024 ** 3, "t": 1024 ** 4}


def url_var(service: str) -> str:
    """The suffix a service's preview URL variables carry: `web-app` → `WEB_APP`."""
    return re.sub(r"[^A-Za-z0-9]", "_", service).upper()


def _under(path: str, rel: str) -> bool:
    return rel in ("", ".") or path == rel or path.startswith(rel.rstrip("/") + "/")


def locate(path: str, layout: Layout) -> TreePath | None:
    """An absolute path as (tree, side, rel), or None when it is in no checkout of the unit."""
    if not isinstance(path, str) or not path.startswith("/"):
        return None
    p = posixpath.normpath(path)
    for d in layout.trees:
        for side in ("base", "change"):
            root = layout.root(d, side)
            if p == root:
                return TreePath(tree=d, side=side, rel=".")
            if p.startswith(root + "/"):
                return TreePath(tree=d, side=side, rel=p[len(root) + 1:])
    return None


def _build(service: dict) -> dict | None:
    build = service.get("build")
    if isinstance(build, str):
        return {"context": build}
    return build if isinstance(build, dict) else None


def inputs(service: dict, layout: Layout) -> tuple[TreePath, ...]:
    """What a service is MADE FROM: its build context and the sources of its bind mounts (plus its
    Dockerfile when that lies outside the context), each as (tree, side, rel).

    A service with no inputs — an image, mounting nothing of the repository — is never from the
    change, whatever the change does. `.dockerignore` is not consulted (a later slice)."""
    out: list[TreePath] = []
    build = _build(service)
    if build and isinstance(build.get("context"), str):
        context = build["context"]
        found = locate(context, layout)
        if found:
            out.append(found)
        dockerfile = build.get("dockerfile")
        if isinstance(dockerfile, str) and "dockerfile_inline" not in build:
            full = posixpath.normpath(posixpath.join(context, dockerfile))
            if not full.startswith(posixpath.normpath(context) + "/"):
                found = locate(full, layout)
                if found:
                    out.append(found)
    for mount in service.get("volumes") or []:
        if isinstance(mount, dict) and mount.get("type") == "bind":
            found = locate(mount.get("source"), layout)
            if found:
                out.append(found)
    return tuple(dict.fromkeys(out))


def is_from_change(service: dict, layout: Layout) -> bool:
    """Whether the change's own diff touches what `service` is made from."""
    for tp in inputs(service, layout):
        tree = layout.trees.get(tp.tree)
        if tree and tree.has_change and any(_under(p, tp.rel) for p in tree.diff_paths):
            return True
    return False


def _reroot(service: dict, layout: Layout) -> dict:
    """`service` with every path it carries moved to the CHANGE side of its repository — where
    that repository has a change; a repository without a pull request in the unit stays base."""

    def moved(path):
        tp = locate(path, layout)
        if tp is None or tp.side != "base" or not layout.trees[tp.tree].has_change:
            return path
        root = layout.root(tp.tree, "change")
        return root if tp.rel == "." else posixpath.join(root, tp.rel)

    svc = copy.deepcopy(service)
    build = svc.get("build")
    if isinstance(build, dict):
        if isinstance(build.get("context"), str):
            build["context"] = moved(build["context"])
        if isinstance(build.get("dockerfile"), str) and build["dockerfile"].startswith("/"):
            build["dockerfile"] = moved(build["dockerfile"])
    elif isinstance(build, str):
        svc["build"] = moved(build)
    for mount in svc.get("volumes") or []:
        if isinstance(mount, dict) and mount.get("type") == "bind":
            mount["source"] = moved(mount.get("source"))
    env_file = svc.get("env_file")
    if isinstance(env_file, list):
        svc["env_file"] = [{**e, "path": moved(e.get("path"))} if isinstance(e, dict) else moved(e)
                           for e in env_file]
    elif isinstance(env_file, str):
        svc["env_file"] = moved(env_file)
    return svc


def shape_edits(diff_paths: Iterable[str], cfg: PreviewConfig | None,
                manifest_path: str = ".openfactory/project.yaml") -> list[str]:
    """The paths of a diff that change what a preview WOULD run: a `preview.compose` file, the
    factory's own shape files, or the manifest the block lives in."""
    compose = {posixpath.normpath(p) for p in (cfg.compose if cfg else [])}
    fixed = {posixpath.normpath(manifest_path), *SHAPE_FILES}
    return [p for p in diff_paths
            if posixpath.normpath(p) in compose | fixed or p.startswith(SHAPE_DIR)]


def topology_changed(diff_paths: Iterable[str], cfg: PreviewConfig | None,
                     manifest_path: str = ".openfactory/project.yaml") -> bool:
    """Whether the change edits the preview's shape. It is then previewed with the base's shape —
    the change's compose file is never opened — and the card says so (S10)."""
    return bool(shape_edits(diff_paths, cfg, manifest_path))


def size_bytes(text: str) -> int | None:
    """`2g` → bytes, the way compose reads a memory size; None when it is not one."""
    m = _SIZE.match(str(text or ""))
    if not m:
        return None
    return int(float(m.group(1)) * _UNITS[m.group(2).lower()])


def _made_of(service: dict, layout: Layout) -> str:
    """What a service is made from, in words, for the refusal that says the change is in none."""
    parts = []
    for tp in inputs(service, layout):
        parts.append(f"`{tp.rel if tp.rel != '.' else tp.tree + '/'}`")
    if parts:
        return "made from " + ", ".join(parts)
    image = service.get("image")
    return f"runs the image `{image}`" if image else "is made from nothing in the repository"


def _env_values(service: dict) -> list[tuple[str, str]]:
    """(name, value) for every literal a service's environment carries, its committed env files
    included — read to find the hosts it will try to reach, never to say a value."""
    out = [(str(k), str(v)) for k, v in as_map(service.get("environment")).items()
           if isinstance(v, str)]
    for item in service.get("env_file") or []:
        path = item.get("path") if isinstance(item, dict) else item
        if not isinstance(path, str) or not os.path.isfile(path):
            continue
        try:
            with open(path, encoding="utf-8", errors="replace") as fh:
                lines = fh.read().splitlines()
        except OSError:
            continue
        for line in lines:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.removeprefix("export ").partition("=")
                out.append((k.strip(), v.strip().strip("'\"")))
    return out


def _external_hosts(service: dict, known: set[str]) -> list[str]:
    hosts: list[str] = []
    for key, value in _env_values(service):
        literal = _REF.sub("", value)
        found = [m.group(1).lower() for m in _URL_HOST.finditer(literal)]
        if not found and key.upper().endswith("HOST") and re.fullmatch(r"[A-Za-z0-9.-]+", literal):
            found = [literal.lower()]
        hosts += [h for h in found if h and h not in known and h not in _LOCAL_HOSTS]
    return list(dict.fromkeys(hosts))


def _carried(service: dict) -> list[str]:
    """Every host path the admitted document carries for one service."""
    out = []
    build = _build(service)
    if build and isinstance(build.get("context"), str):
        out.append(build["context"])
    for mount in service.get("volumes") or []:
        if isinstance(mount, dict) and mount.get("type") == "bind":
            out.append(mount.get("source"))
    for item in service.get("env_file") or []:
        out.append(item.get("path") if isinstance(item, dict) else item)
    return [p for p in out if isinstance(p, str)]


def assemble(doc: dict, *, cfg: PreviewConfig, unit: Unit, layout: Layout,
             policy: PreviewPolicy | None = None, shape_tree: str = "",
             manifest_path: str = ".openfactory/project.yaml", domain: str = "",
             scheme: str = "https", public_port: int | None = None,
             reach: Literal["network", "loopback"] = "network",
             loopback_range: tuple[int, int] | None = None, expires_at: int = 0,
             prove: bool = False) -> PreviewPlan | Refused:
    """The plan for one unit's preview, from the BASE's canonical compose document — or every
    reason there is none.

    `shape_tree` is the repository the compose file and the block live in (default: the first
    tree). `domain`, `scheme` and `public_port` make the browser-facing URLs. `prove` assembles a
    unit with no change at all — the base product only, for `openfactory preview propose --prove`;
    every other preview of a unit with nothing open is refused."""
    policy = policy or PreviewPolicy()
    project, token = unit.project, unit.token
    compose_project = preview.compose_project(project, token)
    edge = preview.edge_network(project, token)
    shape_tree = shape_tree or next(iter(layout.trees), "")
    refused: list[str] = []
    notes: list[str] = []

    services_in = {str(n): dict(s or {}) for n, s in (doc.get("services") or {}).items()}
    running = [n for n, s in services_in.items()
               if n not in cfg.exclude and not s.get("profiles")]
    for field, names in (("preview.expose", cfg.expose), ("preview.data", cfg.data)):
        for n in names:
            if n not in services_in:
                refused.append(f"`{field}` names `{n}`, which the compose file does not declare "
                               f"(it declares {', '.join(f'`{s}`' for s in sorted(services_in))}).")
            elif n not in running:
                refused.append(f"`{field}` names `{n}`, which a preview does not run — it is "
                               f"excluded, or runs only under a profile.")
    for n in cfg.exclude:
        if n not in services_in:
            notes.append(f"`preview.exclude` names `{n}`, which the compose file does not "
                         f"declare.")

    # which service is from the change — judged on the BASE document, before anything moves
    from_change = {n: is_from_change(services_in[n], layout) for n in running}
    moved = {**doc, "services": {n: (_reroot(s, layout) if from_change.get(n) else s)
                                 for n, s in services_in.items()}}

    labels = {s: preview.host_label(project, token, s) for s in cfg.expose}
    urls = {s: (preview.url_for(labels[s], scheme=scheme, preview_domain=domain, port=public_port)
                if domain else "") for s in cfg.expose}
    internal_urls = {s: f"http://{s}:{port}" for s, port in cfg.expose.items()}
    url_names = {f"OPENFACTORY_PREVIEW_URL_{url_var(s)}": "" for s in cfg.expose}
    internal_names = {f"OPENFACTORY_PREVIEW_INTERNAL_URL_{url_var(s)}": "" for s in cfg.expose}
    ours = {v: v for v in (*url_names, *internal_names)}
    public = {v: v for v in url_names}
    allow = {n: {**ours, **policy.names_for(n)} for n in running}
    build_allow = {n: {**public, **policy.names_for(n, build=True)} for n in running}

    roots = [layout.root(d, "base") for d in layout.trees]
    roots += [layout.root(d, "change") for d, t in layout.trees.items() if t.has_change]
    admission = admit(moved, allow_names=allow, build_names=build_allow, trees=roots,
                      exclude=cfg.exclude, project=project, tmpfs_size=policy.tmpfs_size)
    refused += admission.refused
    notes = [*admission.notes, *notes]
    out = admission.doc
    services: dict = out.get("services") or {}

    # the change must be in the preview
    changed = {d: t for d, t in layout.trees.items() if t.has_change}
    if not changed and not prove:
        refused.append("this unit has no open pull request — a preview shows a change, and there "
                       "is none to show yet.")
    elif changed and not prove and not any(from_change.values()):
        touched = [p if len(layout.trees) == 1 else f"{d}/{p}"
                   for d, t in changed.items() for p in t.diff_paths]
        shown = ", ".join(f"`{p}`" for p in touched[:5]) + (
            f" and {len(touched) - 5} more" if len(touched) > 5 else "")
        made = "; ".join(f"`{n}` {_made_of(services_in[n], layout)}" for n in running)
        refused.append(f"the change is in no service's inputs: it touches {shown or 'nothing'}, "
                       f"and no service is built or mounted from any of it ({made}) — a preview "
                       f"would not show it. Add a `build:` for the service this repository builds, "
                       f"in a file `preview.compose` lists.")

    edits = shape_edits(layout.trees[shape_tree].diff_paths, cfg, manifest_path) \
        if shape_tree in layout.trees else []
    if edits:
        notes.append(f"this change edits {', '.join(f'`{p}`' for p in edits)}; the preview runs "
                     f"the base branch's version, never the change's — merge, and the next "
                     f"preview runs the new shape.")

    # what the operator sets
    ports: dict[str, int] = {}
    for name, svc in services.items():
        if from_change.get(name) and "build" in svc:
            svc.pop("image", None)
        elif not from_change.get(name) and "image" in svc:
            svc.pop("build", None)
        svc["pull_policy"] = "build" if "build" in svc else "always"
        env = dict(svc.get("environment") or {})
        for var in ours:
            env[var] = "${" + var + "}"
        for container, worker in policy.names_for(name).items():
            env[container] = "${" + worker + "}"
        svc["environment"] = env
        if "build" in svc:
            args = dict(svc["build"].get("args") or {})
            for var in public:
                args[var] = "${" + var + "}"
            for container, worker in policy.names_for(name, build=True).items():
                args[container] = "${" + worker + "}"
            svc["build"]["args"] = args
        svc.update({
            "cpus": policy.cpus, "mem_limit": policy.memory, "pids_limit": policy.pids_limit,
            "security_opt": ["no-new-privileges:true"], "cap_drop": ["ALL"],
            "cap_add": list(policy.caps), "restart": "no",
        })
        svc["labels"] = {
            preview.LABEL: compose_project, preview.LABEL_PROJECT: project,
            preview.LABEL_UNIT: token, preview.LABEL_KIND: unit.kind,
            preview.LABEL_EXPIRES: str(int(expires_at)), preview.LABEL_WORKDIR: layout.workdir,
            preview.LABEL_EXPOSED: "1" if name in cfg.expose else "",
        }
        nets: dict = {"default": {}}
        if name in cfg.expose:
            nets["edge"] = {"aliases": [labels[name]]}
        if policy.network:
            nets["egress"] = {}
        svc["networks"] = nets
        if reach == "loopback" and name in cfg.expose and loopback_range:
            lo, hi = loopback_range
            port = lo + int(hashlib.sha256(labels[name].encode()).hexdigest(), 16) % (hi - lo + 1)
            clash = next((s for s, p in ports.items() if p == port), None)
            if clash:
                refused.append(f"`{name}` and `{clash}` derive the same loopback port {port} — "
                               f"widen `OPENFACTORY_PREVIEW_PORTS`.")
            ports[name] = port
            svc["ports"] = [{"target": cfg.expose[name], "published": str(port),
                             "host_ip": "127.0.0.1", "protocol": "tcp"}]

    out["volumes"] = {v: {**(spec or {}), "name": f"{compose_project}_{v}"}
                      for v, spec in (out.get("volumes") or {}).items()}
    networks: dict = {"default": {"internal": True}}
    if cfg.expose:
        networks["edge"] = {"name": edge, "external": True}
    if policy.network:
        networks["egress"] = {"name": policy.network, "external": True}
    out["networks"] = networks

    # Hosts a service is configured to reach that a preview cannot (S9). Said at plan time, so a
    # service that connects lazily — and fails no healthcheck — still says it on a live card.
    known = set(services) | {f"{label}.{domain}" for label in labels.values() if domain}
    known |= {str(s.get("hostname")) for s in services.values() if s.get("hostname")}
    for name, svc in services.items():
        hosts = [f"`{h}`" for h in _external_hosts(svc, known)]
        if not hosts:
            continue
        where = hosts[0] if len(hosts) == 1 else f"{', '.join(hosts[:-1])} and {hosts[-1]}"
        if policy.network:
            notes.append(f"`{name}` is configured to reach {where}, outside the preview — only "
                         f"through the operator's network `{policy.network}`, if at all.")
        else:
            notes.append(f"`{name}` is configured to reach {where}, which a preview cannot: it "
                         f"reaches nothing outside itself. Add a service that stands in for it, "
                         f"or name a non-production value with `openfactory project set-preview "
                         f"{project} --env {name}=NAME=WORKER_NAME --network <network>`.")

    # the budget
    count = len(services)
    if count > policy.max_services:
        refused.append(f"this preview would run {count} services, more than the "
                       f"{policy.max_services} the operator allows for one — leave some out with "
                       f"`preview.exclude` in the manifest.")
    each, total = size_bytes(policy.memory), size_bytes(policy.memory_total)
    if each and total and count * each > total:
        refused.append(f"this preview would reserve {count} × {policy.memory} of memory, more than "
                       f"the {policy.memory_total} the operator allows for one — leave services "
                       f"out with `preview.exclude`, or lower the limit per service with "
                       f"`openfactory project set-preview {project} --memory <size>`.")

    if refused:
        return Refused(reasons=tuple(refused), notes=tuple(notes))

    paths = {n: [tp for p in _carried(s) if (tp := locate(p, layout))]
             for n, s in services.items()}
    commits = {}
    for d, tree in layout.trees.items():
        built_from_change = any(tp.tree == d and tp.side == "change"
                                for tps in paths.values() for tp in tps)
        commits[tree.repo] = tree.change_commit if built_from_change else tree.base_commit
    return PreviewPlan(
        unit=unit, project=project, compose_project=compose_project, workdir=layout.workdir,
        layout=layout, doc=out, paths=paths, expose=dict(cfg.expose),
        data=tuple((s, c) for s, c in cfg.data.items()),
        from_change={n: from_change.get(n, False) for n in services},
        commits=commits,
        env_names={n: policy.names_for(n) for n in services},
        build_arg_names={n: policy.names_for(n, build=True) for n, s in services.items()
                         if "build" in s},
        urls=urls, internal_urls=internal_urls, reach=reach, edge_network=edge,
        loopback_ports=ports,
        limits={"cpus": policy.cpus, "memory": policy.memory,
                "memory_total": policy.memory_total, "pids_limit": str(policy.pids_limit),
                "max_services": str(policy.max_services), "tmpfs_size": policy.tmpfs_size},
        egress_network=policy.network, expires_at=int(expires_at),
        pr_urls=tuple(t.pr_url for t in layout.trees.values() if t.pr_url),
        notes=tuple(notes),
    )
