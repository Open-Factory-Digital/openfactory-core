"""Reading a preview's shape: the client's compose files, from the BASE branch, through the compose
CLI (ADR-0050 D3; the design on #265, §3.2).

THE ONE READER THAT EXISTS, IN TWO STEPS AND NO MORE.

1. A PRE-SCAN, pure, over the text of each file, for what the compose CLI would otherwise act on
   before anything of ours sees it: an `include:` pulls in files nobody listed, a `provider:` runs
   something outside compose, an `extends.file` can name any file on the machine, and a path that
   is absolute, `~`-rooted or `$`-bearing points at the host rather than at a checkout. It also
   records which sibling repositories the files reach (`../web`), so the layout knows what to
   check out, and which services are gated by a profile.
2. CANONICALISE, by the reference implementation. `docker compose config` merges the files the way
   the spec says, validates them, normalises every short syntax, flattens `extends` and makes every
   relative path absolute — against the FIRST file's directory, the rule the client's own
   `docker compose up` applies (measured on the pinned plugin: an override under `.openfactory/`
   that says `context: ..` means the directory ABOVE the repository, not the repository). The core
   reimplements no merge; a file the CLI refuses is refused with the CLI's own sentence.

Admission (`admit.py`) then judges the one merged document, key by key.

WHY THE BASE, AND ONLY THE BASE. The agent edits the repository the change is in, so the change's
own compose file is what an agent wrote. `shape()` reads the files from `<workdir>/base/<dir>` and
nowhere else; a change that edits them is previewed with the base's version and says so
(`assemble.topology_changed`).
"""

from __future__ import annotations

import json
import os
import posixpath
import subprocess
from collections.abc import Callable, Iterable, Sequence

import yaml
from pydantic import BaseModel, ConfigDict

from openfactory.contracts.manifest import PreviewConfig
from openfactory.preview.plan import Layout, Refused

#: The only variables the compose CLI is run with. `--env-file /dev/null` keeps the project's
#: `.env` out of interpolation, and a reduced environment keeps the worker's own out: a
#: `${ANTHROPIC_API_KEY}` in a compose file must resolve to nothing, not to the factory's key.
_KEPT_ENV = ("PATH", "HOME", "DOCKER_HOST", "DOCKER_CONFIG")


class _ComposeLoader(yaml.SafeLoader):
    """`yaml.safe_load` plus the two tags the compose spec defines.

    `!reset` and `!override` REMOVE or REPLACE a key while the CLI merges files; neither can add
    anything, and admission judges the merged result — so here they are read as the value they
    carry. Every other tag is refused by the safe loader, which is the point of using it."""


def _as_is(loader: yaml.SafeLoader, node: yaml.Node):
    if isinstance(node, yaml.MappingNode):
        return loader.construct_mapping(node, deep=True)
    if isinstance(node, yaml.SequenceNode):
        return loader.construct_sequence(node, deep=True)
    return loader.construct_scalar(node)


_ComposeLoader.add_constructor("!reset", _as_is)
_ComposeLoader.add_constructor("!override", _as_is)


class Prescan(BaseModel):
    """What the pre-scan found. `dirs` and `extends` are LAYOUT-relative: the first segment is the
    repository's directory under `<workdir>/base/`."""

    model_config = ConfigDict(frozen=True)

    refused: tuple[str, ...] = ()
    #: services gated by `profiles:` — a preview runs none of them
    profiled: tuple[str, ...] = ()
    #: the repository directories the files reach, their own included
    dirs: tuple[str, ...] = ()
    #: every file an `extends:` names, as a layout-relative path
    extends: tuple[str, ...] = ()

    def __add__(self, other: Prescan) -> Prescan:
        return Prescan(refused=self.refused + other.refused,
                       profiled=tuple(dict.fromkeys(self.profiled + other.profiled)),
                       dirs=tuple(sorted(set(self.dirs) | set(other.dirs))),
                       extends=tuple(dict.fromkeys(self.extends + other.extends)))


class Shape(BaseModel):
    """The base's compose document, canonicalised, and what the pre-scan found on the way."""

    model_config = ConfigDict(frozen=True)

    doc: dict
    prescan: Prescan
    #: the files read, layout-relative, in the order they were merged
    files: tuple[str, ...]


def _path_values(svc: dict) -> list[tuple[str, str]]:
    """(what, value) for every host path one service names: its build context, the sources of its
    mounts and its env files. A named volume is not a path. (The Dockerfile is relative to the
    context, not to the file, and is checked on its own in `prescan`.)"""
    out: list[tuple[str, str]] = []
    build = svc.get("build")
    if isinstance(build, str):
        out.append(("builds from", build))
    elif isinstance(build, dict) and isinstance(build.get("context"), str):
        out.append(("builds from", build["context"]))
    for vol in svc.get("volumes") or []:
        if isinstance(vol, str):
            source = vol.split(":", 1)[0] if ":" in vol else ""
            if source and (source[0] in "./~" or "/" in source or "$" in source):
                out.append(("mounts", source))
        elif isinstance(vol, dict):
            source = vol.get("source")
            if isinstance(source, str) and (vol.get("type") == "bind" or source[:1] in "./~"
                                            or "/" in source or "$" in source):
                out.append(("mounts", source))
    env_file = svc.get("env_file")
    for item in [env_file] if isinstance(env_file, str | dict) else env_file or []:
        path = item.get("path") if isinstance(item, dict) else item
        if isinstance(path, str):
            out.append(("reads", path))
    return out


def _outside(value: str) -> str:
    """Why a path value points at the host rather than at a checkout, or ""."""
    if "$" in value:
        return "names a variable in a path, which a preview does not resolve"
    if value.startswith("/"):
        return "is absolute — a preview builds and mounts from its own checkouts only"
    if value.startswith("~"):
        return "is under a home directory — a preview builds and mounts from its own checkouts only"
    return ""


def _resolve(relative_to: str, value: str) -> str:
    """`value` resolved against a layout-relative directory: `app` + `../web/src` → `web/src`.
    Starts with `..` (or is `.`) when it leaves every repository."""
    return posixpath.normpath(posixpath.join(relative_to, value))


#: What a `../<dir>` naming no repository of the preview is told. A PRODUCT's layout says it in
#: terms of the file that decides it (`PRODUCT_REMEDY`), because there a directory is a
#: repository of `sources:` and `dirs:` is how one is named differently.
REMEDY = "rename the directory or declare which repository it is"
PRODUCT_REMEDY = ("rename it, or declare `dirs: {{{dir}: <owner/name>}}` in "
                  "`.openfactory/product.yaml`")


def prescan(texts: dict[str, str], *, layout_dirs: Iterable[str] | None = None,
            relative_to: str | None = None, of: str = "this preview",
            remedy: str = REMEDY) -> Prescan:
    """Read each file's text for what must be refused before the compose CLI acts on it.

    `texts` maps LAYOUT-relative paths (`app/docker-compose.yml`) to their text, in merge order.
    Relative paths inside them resolve against `relative_to` — by default the FIRST file's
    directory, which is the rule the CLI applies to every file it is given with `-f`; a file an
    `extends:` names resolves against its own directory, and is scanned with that directory.
    `layout_dirs`, when given, are the repositories the preview may use: a `../<dir>` that names
    any other is refused by name rather than checked out on a guess — said as not a repository
    `of` this preview (or product), with `remedy` (`{dir}` is the directory it named)."""
    known = set(layout_dirs) if layout_dirs is not None else None
    first = next(iter(texts), "")
    base_dir = relative_to if relative_to is not None else posixpath.dirname(first)
    refused: list[str] = []
    profiled: list[str] = []
    dirs: set[str] = set()
    extends: list[str] = []

    def where(what: str, name: str, value: str, owner: str) -> None:
        why = _outside(value)
        if why:
            refused.append(f"`{name}` in {owner} {what} `{value}`, which {why}.")
            return
        resolved = _resolve(base_dir, value)
        if resolved == "." or resolved.startswith("../") or resolved == "..":
            refused.append(f"`{name}` in {owner} {what} `{value}`, which is outside every "
                           f"repository of this preview.")
            return
        top = resolved.split("/", 1)[0]
        if known is not None and top not in known:
            refused.append(f"`{name}` in {owner} {what} `{value}`, and `{top}` is not a "
                           f"repository of {of} ({', '.join(sorted(known)) or 'none'}) — "
                           f"{remedy.format(dir=top)}.")
            return
        dirs.add(top)

    for path, text in texts.items():
        owner = f"`{path.split('/', 1)[-1]}`"
        try:
            doc = yaml.load(text, Loader=_ComposeLoader)  # a SafeLoader, plus two identity tags
        except yaml.YAMLError as exc:
            problem = getattr(exc, "problem", None) or str(exc).splitlines()[0]
            refused.append(f"{owner} could not be read as a compose file: {problem}.")
            continue
        if doc is None:
            continue
        if not isinstance(doc, dict):
            refused.append(f"{owner} is not a compose file: its top level is not a mapping.")
            continue
        if "include" in doc:
            refused.append(f"{owner} includes other files (`include:`), which a preview does not "
                           f"follow — list every file in `preview.compose` instead.")
        services = doc.get("services") or {}
        if not isinstance(services, dict):
            continue
        for name, svc in services.items():
            if not isinstance(svc, dict):
                continue
            if "provider" in svc:
                refused.append(f"`{name}` in {owner} is run by a provider (`provider:`), outside "
                               f"compose — a preview cannot run it; exclude it with "
                               f"`preview.exclude`.")
            if svc.get("profiles"):
                profiled.append(str(name))
            ext = svc.get("extends")
            if isinstance(ext, dict) and "file" in ext:
                file = ext.get("file")
                if not isinstance(file, str) or not file.strip():
                    refused.append(f"`{name}` in {owner} extends a file it does not name.")
                else:
                    before = len(refused)
                    where("extends", str(name), file, owner)
                    if len(refused) == before:
                        extends.append(_resolve(base_dir, file))
            for what, value in _path_values(svc):
                where(what, str(name), value, owner)
            build = svc.get("build")
            dockerfile = build.get("dockerfile") if isinstance(build, dict) else None
            if isinstance(dockerfile, str) and _outside(dockerfile):
                refused.append(f"`{name}` in {owner} builds with `{dockerfile}`, which "
                               f"{_outside(dockerfile)}.")
    return Prescan(refused=tuple(refused), profiled=tuple(dict.fromkeys(profiled)),
                   dirs=tuple(sorted(dirs)), extends=tuple(dict.fromkeys(extends)))


def reduced_env() -> dict[str, str]:
    """The environment the compose CLI runs in: enough to find itself and the daemon, nothing a
    compose file could read a credential from. The pull-credential directory the operator named
    for previews wins over the worker's own (`OPENFACTORY_PREVIEW_DOCKER_CONFIG`)."""
    env = {k: os.environ[k] for k in _KEPT_ENV if os.environ.get(k)}
    own = (os.environ.get("OPENFACTORY_PREVIEW_DOCKER_CONFIG") or "").strip()
    if own:
        env["DOCKER_CONFIG"] = own
    return env


def canonicalise(base_root: str, files: Sequence[str], *,
                 run: Callable[..., subprocess.CompletedProcess] = subprocess.run
                 ) -> dict | Refused:
    """The compose document the files make, as the compose CLI writes it.

    `docker compose -f <base>/<a> [-f <base>/<b> …] --project-directory <dir of a>
    --env-file /dev/null config --no-interpolate --format json`, under `reduced_env()`. It contacts
    no daemon. `--no-interpolate` leaves every `${NAME}` for admission to judge — admission, not
    the CLI, decides which names a preview may read.

    NOT `--no-env-resolution`, which the design named: the pinned plugin (v2.32.4, the one
    `docker/cli.Dockerfile` copies) refuses it as an unknown flag, and measured on both 2.32.4 and
    2.40 the output without it reads no env file into `environment` and resolves no bare name
    either — a bare build argument is dropped, a bare environment entry stays bare.

    `run` is a seam: the tests hand it recorded output of the pinned plugin, and nothing else in
    the preview's pure core runs a process."""
    if not files:
        return Refused(reasons=("`preview.compose` names no file.",))
    paths = [posixpath.join(base_root, f) for f in files]
    argv = ["docker", "compose"]
    for p in paths:
        argv += ["-f", p]
    argv += ["--project-directory", posixpath.dirname(paths[0]), "--env-file", os.devnull,
             "config", "--no-interpolate", "--format", "json"]
    named = ", ".join(f"`{f}`" for f in files)
    try:
        proc = run(argv, capture_output=True, text=True, env=reduced_env(), timeout=120,
                   check=False)
    except (OSError, subprocess.SubprocessError) as exc:
        return Refused(reasons=(f"the compose CLI could not be run to read {named} ({exc}) — "
                                f"`openfactory doctor` on the worker says what is missing.",))
    if proc.returncode != 0:
        lines = [ln.strip() for ln in (proc.stderr or "").splitlines() if ln.strip()]
        said = lines[-1] if lines else f"it exited {proc.returncode} and said nothing"
        return Refused(reasons=(f"the compose CLI refused {named}: {said}",))
    try:
        doc = json.loads(proc.stdout or "")
    except ValueError:
        return Refused(reasons=(f"the compose CLI read {named} and wrote something that is not "
                                f"JSON — is the plugin on the worker the pinned one?",))
    if not isinstance(doc, dict):
        return Refused(reasons=(f"the compose CLI read {named} and wrote no document.",))
    return doc


def _read_inside(root: str, path: str) -> str | None:
    """The text of `path` when it is a file INSIDE `root` once every link is followed; None
    otherwise. A compose file that is a link out of the checkout is not the checkout's file."""
    real_root = os.path.realpath(root)
    real = os.path.realpath(path)
    if not (real == real_root or real.startswith(real_root + os.sep)) or not os.path.isfile(real):
        return None
    with open(real, encoding="utf-8") as fh:
        return fh.read()


def shape(layout: Layout, cfg: PreviewConfig, *, tree: str,
          run: Callable[..., subprocess.CompletedProcess] = subprocess.run,
          of: str = "this preview", remedy: str = REMEDY) -> Shape | Refused:
    """The preview's shape: `cfg.compose`, read from the BASE checkout of `tree`, pre-scanned,
    then canonicalised by the compose CLI — or every reason it will not be.

    The base, never the change: see the module's docstring. Files an `extends:` names are read from
    the base too, and scanned with their own directory, the way the CLI resolves them. A path into
    a directory that is not a tree of the layout is refused as not a repository `of` it, with
    `remedy` (a product's names `dirs:`)."""
    base = layout.root(tree, "base")
    base_all = posixpath.join(layout.workdir, "base")
    texts: dict[str, str] = {}
    missing: list[str] = []
    repo = layout.trees[tree].repo if tree in layout.trees else tree
    for f in cfg.compose:
        text = _read_inside(base, posixpath.join(base, f))
        if text is None:
            missing.append(f)
        else:
            texts[posixpath.normpath(posixpath.join(tree, f))] = text
    if missing:
        return Refused(reasons=tuple(
            f"`{f}` is not a file of `{repo}`'s base branch — `preview.compose` names it, and a "
            f"preview reads the base branch's files only." for f in missing))
    found = prescan(texts, layout_dirs=layout.trees, of=of, remedy=remedy)
    seen = set(texts)
    queue = [p for p in found.extends if p not in seen]
    while queue:
        rel = queue.pop(0)
        seen.add(rel)
        text = _read_inside(base_all, posixpath.join(base_all, rel))
        if text is None:
            found = found + Prescan(refused=(
                f"`{rel.split('/', 1)[-1]}` is named by an `extends:` and is not a file of the "
                f"base branch.",))
            continue
        more = prescan({rel: text}, layout_dirs=layout.trees, relative_to=posixpath.dirname(rel),
                       of=of, remedy=remedy)
        found = found + more
        queue += [p for p in more.extends if p not in seen and p not in queue]
    if found.refused:
        return Refused(reasons=found.refused)
    doc = canonicalise(base, cfg.compose, run=run)
    if isinstance(doc, Refused):
        return doc
    return Shape(doc=doc, prescan=found, files=tuple(texts))
