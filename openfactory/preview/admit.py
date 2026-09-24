"""Admission: the canonical compose document, judged KEY BY KEY (ADR-0050 D3; the design on #265,
§2.1).

A WHITELIST, BECAUSE THE BLACKLIST LET KEYS THROUGH UNEXAMINED. The first assembler refused a list
of keys it knew to be dangerous and passed everything else, so every key the compose spec gained,
and every key nobody thought of, reached the daemon by default. Here every key has one of four
outcomes, and a key in no set is refused by name:

  pass    handed to the compose CLI verbatim — what the client's developers run, the preview runs
  set     written by the assembler from the operator's policy; the client's value is dropped, said
  drop    dropped, said in a note
  refuse  the whole preview, with a sentence saying why and what to do

The sets below are the ONLY place compose-spec drift is paid for, one line per key.

Beyond the sets, admission (all of it on the document the runtime will receive, so AFTER the
assembler has put each service on the side of the unit it runs from):

- ENVIRONMENT, normalised. The CLI writes `environment` as a list of `KEY=VALUE` under
  `--no-interpolate`; it becomes a map before anything reads it, and so does `build.args`.
- INTERPOLATION, resolved here and not by the environment the CLI happens to run in. A `${NAME}`
  whose name the operator listed for this service stays a reference — rewritten to the WORKER's
  name for it — and every other becomes its default or nothing, said. `${X:?}` on a name nobody
  listed is a refusal with the remedy, because compose would otherwise abort the stack after the
  build. So `${DOCKER_HOST}` or `${ANTHROPIC_API_KEY}` in a merged compose file resolve to nothing.
- PATHS, on disk. Every build context, Dockerfile, bind source and env file must be, once every
  link is followed, inside one of the unit's checkouts: a git-tracked `data -> /var/run/docker.sock`
  in a mounted directory is refused here, not mounted.
- VOLUMES. Declared, un-named, and only three mount types. A top-level `name:` is refused because
  compose emits it UN-prefixed: `name: openfactory_openfactory_state` would mount the factory's own
  state into agent-written code.
"""

from __future__ import annotations

import copy
import os
import re
from collections.abc import Iterable

from pydantic import BaseModel, ConfigDict

PASS_SERVICE = frozenset({
    "image", "build", "command", "entrypoint", "environment", "env_file", "working_dir", "user",
    "depends_on", "healthcheck", "volumes", "tmpfs", "read_only", "expose", "stop_grace_period",
    "stop_signal", "init", "tty", "stdin_open", "hostname", "shm_size", "ulimits", "platform",
    "attach",
})
# Written by the assembler from PreviewPolicy / the plan; a client value is dropped with a note.
SET_SERVICE = frozenset({
    "restart", "pull_policy", "cpus", "mem_limit", "pids_limit", "security_opt", "cap_drop",
    "cap_add", "labels", "networks",
})
DROP_SERVICE = frozenset({
    "ports", "container_name", "links", "external_links", "profiles", "deploy", "develop",
    "logging", "dns", "dns_search", "dns_opt", "mac_address", "domainname", "scale", "annotations",
    "oom_kill_disable", "oom_score_adj", "blkio_config", "cpu_shares", "cpu_count", "cpu_percent",
    "cpu_quota", "cpu_period", "cpuset", "mem_reservation", "mem_swappiness", "memswap_limit",
    "extra_hosts",          # writes /etc/hosts only; a preview has no route to the host anyway
})
REFUSE_SERVICE = frozenset({
    "privileged", "devices", "device_cgroup_rules", "group_add", "ipc", "pid", "uts", "cgroup",
    "cgroup_parent", "network_mode", "userns_mode", "sysctls", "runtime", "volumes_from", "gpus",
    "post_start", "pre_stop", "storage_opt", "isolation", "credential_spec", "secrets", "configs",
    "provider", "volume_driver",
})
PASS_BUILD   = frozenset({"context", "dockerfile", "dockerfile_inline", "args", "target",
                          "no_cache", "pull"})
DROP_BUILD   = frozenset({"labels", "tags", "cache_from", "cache_to", "platforms"})
REFUSE_BUILD = frozenset({"ssh", "secrets", "privileged", "network", "extra_hosts",
                          "additional_contexts", "isolation", "ulimits"})
PASS_TOP   = frozenset({"services", "volumes"})
DROP_TOP   = frozenset({"name", "version", "networks"})       # plus every `x-` key
REFUSE_TOP = frozenset({"include", "secrets", "configs", "models"})
PASS_VOLUME   = frozenset({"labels"})                          # top-level volumes
REFUSE_VOLUME = frozenset({"external", "driver", "driver_opts", "name"})   # plus every `x-` key

#: The keys one mount may carry, and the sub-keys of each mount type. `create_host_path` is not
#: here: it is STRIPPED — the tree exists, and a path the daemon creates at start is a path nobody
#: admitted.
_MOUNT_KEYS = frozenset({"type", "source", "target", "read_only", "consistency", "bind", "volume",
                         "tmpfs"})
_BIND_KEYS = frozenset({"selinux"})
_VOLUME_KEYS = frozenset({"nocopy", "subpath"})
_TMPFS_KEYS = frozenset({"size", "mode"})

#: Why a dropped key is not used, said once per key on the card.
_DROPPED_BECAUSE = {
    "ports": "a preview is reached through a host of its own, never a published port",
    "container_name": "a preview names its containers, so two previews never collide",
    "extra_hosts": "it only writes /etc/hosts, and a preview has no route to the host",
    "links": "every service of a preview already reaches the others by name",
    "external_links": "a preview reaches nothing outside itself",
    "deploy": "a preview's limits are the operator's",
    "logging": "a preview's logs are kept by the factory",
}
_TOP_REFUSED_BECAUSE = {
    "include": "list every file in `preview.compose` instead",
    "secrets": "a secret is read from a file on the host; a preview's values come from the "
               "registry's `preview.env`",
    "configs": "a config is read from a file on the host; commit it and mount it from the "
               "repository instead",
    "models": "a preview runs no model runner",
}
_SET_BECAUSE = {
    "restart": "the factory supervises a preview, and the daemon never restarts one",
    "labels": "a preview's containers carry only the platform's labels, so a routing or "
              "automation label never acts on one",
    "networks": "a preview is on its own networks",
    "pull_policy": "a preview pulls what it runs from base every time",
}

_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_OPS = (":-", ":?", ":+", "-", "?", "+")


class Admission(BaseModel):
    """The admitted document, every refusal and every note — each a sentence a person can act
    on. `refused` non-empty means the preview is not run, whatever `doc` holds."""

    model_config = ConfigDict(frozen=True)

    doc: dict
    refused: list[str]
    notes: list[str]


def _closing(s: str, i: int) -> int:
    """The index of the `}` closing the `${` whose body starts at `i`; -1 when there is none."""
    depth = 1
    while i < len(s):
        if s.startswith("$$", i):
            i += 2
            continue
        if s.startswith("${", i):
            depth += 1
            i += 2
            continue
        if s[i] == "}":
            depth -= 1
            if depth == 0:
                return i
        i += 1
    return -1


def rewrite(text: str, allowed: dict[str, str]) -> tuple[str, list[str], list[str]]:
    """`text` with every interpolation resolved the way a preview resolves it.

    Returns (the rewritten text, the unlisted names it read, the unlisted names it REQUIRED).
    A listed name stays a reference, renamed to the worker's variable that holds it; an unlisted
    one becomes its default (`${X:-d}`, `${X-d}`) or nothing; `$$` stays the literal it is."""
    out: list[str] = []
    unlisted: list[str] = []
    required: list[str] = []
    i, n = 0, len(text)
    while i < n:
        c = text[i]
        if c != "$":
            out.append(c)
            i += 1
            continue
        if text.startswith("$$", i):
            out.append("$$")
            i += 2
            continue
        if text.startswith("${", i):
            end = _closing(text, i + 2)
            m = _NAME.match(text, i + 2) if end > 0 else None
            if not m:
                # Not an interpolation compose would accept either; it stays, and the path and
                # key checks judge what it is part of.
                out.append(text[i:] if end < 0 else text[i:end + 1])
                i = n if end < 0 else end + 1
                continue
            name, rest = m.group(0), text[m.end():end]
            op = next((o for o in _OPS if rest.startswith(o)), "")
            arg, more, needs = rewrite(rest[len(op):], allowed) if op else ("", [], [])
            unlisted += more
            required += needs
            if name in allowed:
                out.append("${" + allowed[name] + op + arg + "}")
            else:
                unlisted.append(name)
                if op in (":?", "?"):
                    required.append(name)
                elif op in (":-", "-"):
                    out.append(arg)
            i = end + 1
            continue
        m = _NAME.match(text, i + 1)
        if m:
            name = m.group(0)
            if name in allowed:
                out.append("${" + allowed[name] + "}")
            else:
                unlisted.append(name)
            i = m.end()
            continue
        out.append("$")
        i += 1
    return "".join(out), unlisted, required


def _walk(value, fn):
    """`value` with `fn` applied to every string in it, keys excepted."""
    if isinstance(value, str):
        return fn(value)
    if isinstance(value, dict):
        return {k: _walk(v, fn) for k, v in value.items()}
    if isinstance(value, list):
        return [_walk(v, fn) for v in value]
    return value


def as_map(value) -> dict:
    """`environment` / `build.args` as a map, from either form. A bare `NAME` (no `=`) maps to
    None: compose would read it from ITS OWN environment, which admission decides instead."""
    if isinstance(value, dict):
        return {str(k): v for k, v in value.items()}
    out: dict = {}
    for item in value or []:
        k, eq, v = str(item).partition("=")
        out[k] = v if eq else None
    return out


def _inside(path: str, roots: list[str]) -> str:
    """The root `path` lies in once every link is followed, or ""."""
    real = os.path.realpath(path)
    for root in roots:
        if real == root or real.startswith(root + os.sep):
            return root
    return ""


class _Said:
    """Notes grouped by what they say, so the card says `ports:` once for five services."""

    def __init__(self) -> None:
        self.by_key: dict[tuple[str, str], list[str]] = {}

    def add(self, kind: str, key: str, service: str) -> None:
        self.by_key.setdefault((kind, key), [])
        if service not in self.by_key[(kind, key)]:
            self.by_key[(kind, key)].append(service)

    def sentences(self) -> list[str]:
        out = []
        for (kind, key), services in self.by_key.items():
            who = ", ".join(f"`{s}`" for s in sorted(services))
            if kind == "set":
                why = _SET_BECAUSE.get(key, "the preview sets it from the operator's policy")
                out.append(f"`{key}:` of {who} is not used — {why}.")
            elif kind == "build":
                out.append(f"`build.{key}:` of {who} is not used in a preview's build.")
            elif kind == "x":
                out.append(f"`{key}` of {who} (an extension field) is not read by a preview.")
            else:
                why = _DROPPED_BECAUSE.get(key, "a preview does not use it")
                out.append(f"`{key}:` of {who} is not used in a preview — {why}.")
        return out


def admit(doc: dict, *, allow_names: dict[str, dict[str, str]], trees: Iterable[str],
          build_names: dict[str, dict[str, str]] | None = None, exclude: Iterable[str] = (),
          project: str = "", tmpfs_size: str = "256m") -> Admission:
    """Judge a canonical compose document for a preview.

    `allow_names` — per service (`"*"` = every service): {name the file may read: the worker
    variable that holds it}; the preview URLs belong here. `build_names` — the same for what a
    service's BUILD may read (default: none). `trees` — the checkouts every path must lie in.
    `exclude` — the services `preview.exclude` names. `project` only makes the remedies runnable."""
    doc = copy.deepcopy(doc or {})
    refused: list[str] = []
    notes: list[str] = []
    said = _Said()
    roots = [os.path.realpath(r) for r in trees]
    excluded = set(exclude)
    who = project or "<project>"

    # ── the top level ──
    out: dict = {}
    for key, value in doc.items():
        if key.startswith("x-"):
            notes.append(f"`{key}` (an extension field) is not read by a preview — what it was "
                         f"merged into is.")
        elif key in PASS_TOP:
            out[key] = value
        elif key in DROP_TOP:
            # `name` and `version` are compose's own bookkeeping, and the CLI writes a `default`
            # network into every document: only a network the client declared is worth a line.
            own = sorted(set(value or {}) - {"default"}) if key == "networks" else []
            if own:
                notes.append(f"the file's own networks ({', '.join(f'`{n}`' for n in own)}) are "
                             f"not used — a preview is on its own networks.")
        elif key in REFUSE_TOP:
            refused.append(f"`{key}:` at the top of the compose file is not something a preview "
                           f"reads — {_TOP_REFUSED_BECAUSE[key]}.")
        else:
            refused.append(f"`{key}` is not a key a preview reads.")

    # ── top-level volumes ──
    project_name = str(doc.get("name") or "")
    declared: set[str] = set()
    volumes: dict = {}
    for vol, spec in (out.get("volumes") or {}).items():
        spec = dict(spec or {})
        kept: dict = {}
        for key, value in spec.items():
            if key in PASS_VOLUME:
                kept[key] = value
            elif key == "name" and value == f"{project_name}_{vol}":
                pass  # compose's own name for an un-named volume; the assembler writes the real one
            elif key == "external" and not value:
                pass
            elif key == "name":
                refused.append(f"volume `{vol}` is named `{value}` — a preview's volumes are its "
                               f"own and named by the preview; remove `name:` from the compose "
                               f"file.")
            elif key == "external":
                refused.append(f"volume `{vol}` is external — somebody's real data; a preview "
                               f"starts from fresh volumes only.")
            elif key in REFUSE_VOLUME or key.startswith("x-"):
                refused.append(f"volume `{vol}` sets `{key}:`, which a preview does not use — its "
                               f"volumes are plain local volumes of its own.")
            else:
                refused.append(f"`{key}` on volume `{vol}` is not a key a preview reads.")
        volumes[vol] = _walk(kept, lambda s: rewrite(s, {})[0])
        declared.add(str(vol))
    if "volumes" in out:
        out["volumes"] = volumes

    # ── services ──
    services_in = dict(out.get("services") or {})
    profiled = {n for n, s in services_in.items() if isinstance(s, dict) and s.get("profiles")}
    for name in sorted(profiled):
        profiles = ", ".join(f"`{p}`" for p in services_in[name].get("profiles") or [])
        notes.append(f"`{name}` runs only under a profile ({profiles}); a preview runs none.")
    services: dict = {}
    for name, svc in services_in.items():
        if name in profiled or name in excluded:
            continue
        svc = dict(svc or {})
        kept: dict = {}
        for key, value in svc.items():
            if key.startswith("x-"):
                said.add("x", key, name)
            elif key in PASS_SERVICE:
                kept[key] = value
            elif key in SET_SERVICE:
                if not (key == "networks" and set(value or {}) <= {"default"}):
                    said.add("set", key, name)
            elif key in DROP_SERVICE:
                said.add("drop", key, name)
            elif key in REFUSE_SERVICE:
                refused.append(f"`{name}` asks for `{key}:`, which a preview never grants — it "
                               f"hands a container something of the host's.")
            else:
                refused.append(f"`{key}` is not a key a preview reads (service `{name}`).")
        svc = kept

        # build: normalised, then judged key by key
        if "build" in svc:
            build = svc["build"]
            build = {"context": build} if isinstance(build, str) else dict(build or {})
            judged: dict = {}
            for key, value in build.items():
                if key in PASS_BUILD:
                    judged[key] = value
                elif key in DROP_BUILD:
                    said.add("build", key, name)
                elif key in REFUSE_BUILD:
                    refused.append(f"`{name}` builds with `{key}:`, which a preview's build never "
                                   f"gets — it hands the build something of the host's.")
                else:
                    refused.append(f"`build.{key}` is not a key a preview reads (service "
                                   f"`{name}`).")
            if "args" in judged:
                judged["args"] = as_map(judged["args"])
            svc["build"] = judged
        if "environment" in svc:
            svc["environment"] = as_map(svc["environment"])

        # interpolation: the build reads the build list, everything else the run-time list
        run_names = {**allow_names.get("*", {}), **allow_names.get(name, {})}
        build_list = {**(build_names or {}).get("*", {}), **(build_names or {}).get(name, {})}
        unlisted: list[str] = []
        needed: list[str] = []

        def by(allowed: dict[str, str], unlisted=unlisted, needed=needed):
            def fn(s: str) -> str:
                text, more, needs = rewrite(s, allowed)
                unlisted.extend(more)
                needed.extend(needs)
                return text
            return fn

        # A path is judged BEFORE any value is rewritten: a `${NAME}` in a path is a path an
        # environment chooses at `up`, and rewriting it away would admit a path nobody wrote.
        for what, path in _path_fields(svc):
            if isinstance(path, str) and "$" in path:
                refused.append(f"`{name}` {what} `{path}`, which names a variable — a preview's "
                               f"paths are its checkouts', never an environment's.")

        # Values are rewritten BEFORE bare names are answered: a bare name becomes a reference to
        # the worker's variable, and read again it would be a name nobody listed.
        for key in list(svc):
            if key == "build":
                build = _walk(svc["build"], by(build_list))
                if "args" in build:
                    build["args"] = _bare(build["args"], build_list, unlisted)
                svc["build"] = build
            elif key == "environment":
                svc[key] = _bare(_walk(svc[key], by(run_names)), run_names, unlisted)
            else:
                svc[key] = _walk(svc[key], by(run_names))
        for var in dict.fromkeys(needed):
            refused.append(f"`{name}` requires `{var}` (`${{{var}:?…}}`), which the registry does "
                           f"not name for its previews — name it with `openfactory project "
                           f"set-preview {who} --env {name}={var}`, or give it a default in the "
                           f"compose file.")
        quiet = [v for v in dict.fromkeys(unlisted) if v not in needed]
        if quiet:
            names = ", ".join(f"`{v}`" for v in quiet)
            notes.append(f"`{name}` reads {names}, which the registry does not name for its "
                         f"previews — defaults or nothing here; `openfactory project set-preview "
                         f"{who} --env {name}=NAME` names one.")

        # dependencies: never pruned in silence
        deps = svc.get("depends_on")
        if isinstance(deps, list):
            deps = {d: {"condition": "service_started"} for d in deps}
            svc["depends_on"] = deps
        for dep in deps or {}:
            if dep in excluded:
                refused.append(f"`{name}` depends on `{dep}`, which `preview.exclude` leaves out "
                               f"— run both, or neither.")
            elif dep in profiled:
                refused.append(f"`{name}` depends on `{dep}`, which runs only under a profile a "
                               f"preview does not run — drop the profile from `{dep}`, or exclude "
                               f"`{name}` too.")

        _paths(name, svc, roots=roots, declared=declared, tmpfs_size=tmpfs_size,
               refused=refused, notes=notes)
        services[name] = svc
    out["services"] = services
    return Admission(doc=out, refused=refused, notes=[*said.sentences(), *notes])


def _path_fields(svc: dict) -> list[tuple[str, object]]:
    """(what, value) for every host path a service's document carries."""
    out: list[tuple[str, object]] = []
    build = svc.get("build")
    if isinstance(build, dict):
        out += [("builds from", build.get("context")), ("builds with", build.get("dockerfile"))]
    for mount in svc.get("volumes") or []:
        if isinstance(mount, dict) and mount.get("type") == "bind":
            out.append(("mounts", mount.get("source")))
    env_file = svc.get("env_file")
    for item in [env_file] if isinstance(env_file, str | dict) else env_file or []:
        out.append(("reads", item.get("path") if isinstance(item, dict) else item))
    return out


def _bare(env: dict, allowed: dict[str, str], unlisted: list[str]) -> dict:
    """A bare `NAME` means "whatever the compose process holds" — so it is the registry's to
    answer: a listed name becomes a reference to the worker's variable, any other is removed."""
    out: dict = {}
    for k, v in (env or {}).items():
        if v is not None:
            out[k] = v
        elif k in allowed:
            out[k] = "${" + allowed[k] + "}"
        else:
            unlisted.append(k)
    return out


def _shown(path: str, roots: list[str]) -> str:
    """`path` as a person reads it: relative to the checkout it lies in."""
    real = os.path.realpath(path)
    for root in roots:
        if real.startswith(root + os.sep):
            return real[len(root) + 1:]
    return path


def _paths(name: str, svc: dict, *, roots: list[str], declared: set[str], tmpfs_size: str,
           refused: list[str], notes: list[str]) -> None:
    """Every host path of one service, judged ON DISK, in place."""

    def outside(what: str, path) -> bool:
        if not isinstance(path, str) or not path.startswith("/") or "$" in path:
            refused.append(f"`{name}` {what} `{path}`, which is not a directory of this "
                           f"preview's checkouts.")
            return True
        if not _inside(path, roots):
            refused.append(f"`{name}` {what} `{path}`, which leads outside this preview's "
                           f"checkouts once its links are followed.")
            return True
        return False

    build = svc.get("build")
    if isinstance(build, dict):
        context = build.get("context")
        if not outside("builds from", context) and "dockerfile_inline" not in build:
            dockerfile = os.path.join(context, str(build.get("dockerfile") or "Dockerfile"))
            if not outside("builds with", dockerfile) and not os.path.isfile(dockerfile):
                refused.append(f"`{name}` builds with `{_shown(dockerfile, roots)}`, which is not "
                               f"in the checkout it builds from.")

    kept = []
    for mount in svc.get("volumes") or []:
        if not isinstance(mount, dict):
            refused.append(f"`{name}` mounts `{mount}`, which is not in the form the compose CLI "
                           f"writes — the document was not canonicalised.")
            continue
        mount = dict(mount)
        for key in set(mount) - _MOUNT_KEYS:
            refused.append(f"`{name}` mounts with `{key}:`, which a preview does not use.")
        kind = mount.get("type")
        if kind == "bind":
            source = mount.get("source")
            if outside("mounts", source):
                continue
            bind = {k: v for k, v in (mount.get("bind") or {}).items() if k != "create_host_path"}
            for key in set(bind) - _BIND_KEYS:
                refused.append(f"`{name}` mounts `{_shown(source, roots)}` with `bind.{key}:`, "
                               f"which a preview does not use.")
            if bind:
                mount["bind"] = bind
            else:
                mount.pop("bind", None)
            if not os.path.exists(source):
                notes.append(f"`{name}` mounts `{_shown(source, roots)}`, which is not in the "
                             f"repository — not mounted; the service starts with what its image "
                             f"holds.")
                continue
        elif kind == "volume":
            source = mount.get("source")
            if source and source not in declared:
                refused.append(f"`{name}` mounts the volume `{source}`, which the compose file "
                               f"does not declare — a preview mounts only its own volumes.")
            for key in set(mount.get("volume") or {}) - _VOLUME_KEYS:
                refused.append(f"`{name}` mounts the volume `{source}` with `volume.{key}:`, "
                               f"which a preview does not use.")
        elif kind == "tmpfs":
            tmpfs = dict(mount.get("tmpfs") or {})
            for key in set(tmpfs) - _TMPFS_KEYS:
                refused.append(f"`{name}` mounts a tmpfs with `tmpfs.{key}:`, which a preview does "
                               f"not use.")
            tmpfs.setdefault("size", tmpfs_size)
            mount["tmpfs"] = tmpfs
        else:
            refused.append(f"`{name}` asks for a `{kind}` mount — a preview mounts only its "
                           f"checkouts (bind), its own volumes and tmpfs.")
            continue
        kept.append(mount)
    if "volumes" in svc:
        svc["volumes"] = kept

    if "tmpfs" in svc:
        entries = [svc["tmpfs"]] if isinstance(svc["tmpfs"], str) else list(svc["tmpfs"] or [])
        sized = []
        for entry in entries:
            entry = str(entry)
            if "size=" not in entry:
                entry += f",size={tmpfs_size}" if ":" in entry else f":size={tmpfs_size}"
            sized.append(entry)
        svc["tmpfs"] = sized

    if "env_file" in svc:
        items = svc["env_file"]
        items = [items] if isinstance(items, str | dict) else list(items or [])
        files = []
        for item in items:
            item = dict(item) if isinstance(item, dict) else {"path": item, "required": True}
            path = item.get("path")
            if outside("reads", path):
                continue
            if not os.path.exists(path):
                item["required"] = False
                notes.append(f"`{name}` reads `{_shown(path, roots)}`, which is not in the "
                             f"repository; its names come only from the registry's "
                             f"`preview.env`.")
            files.append(item)
        svc["env_file"] = files
