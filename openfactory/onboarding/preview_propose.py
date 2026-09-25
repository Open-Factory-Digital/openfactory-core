"""Propose how a product is previewed — as its OWN pull request, which a person merges (ADR-0050
D12; the design on #265, §4.2–§4.3).

`preview_infer.py` reads; this module writes, and only in two places: a throwaway clone that
becomes a pull request on `openfactory/preview`, or — on the one-machine kind, where the repository
is the person's own — their checkout, with "commit these". Nothing here builds or runs what it
drafts. A `docker build` executes a Dockerfile's `RUN` lines with network access, and the files it
would build are the repository's history plus a draft an agent influenced, so the proof is never
this module's: `--prove` hands the drafted files to the deployment's preview runtime (the slice-2
row), which builds the BASE branch with the draft applied, on the deployment's own daemon.

THE TIERS DECIDE WHAT IS WRITTEN. An `observed` line is written; an `inferred` one only with
`--accept`; an `unknown` never — a person answers it with `--set preview.<path>=<value>`, and then
it is theirs. When `expose` stays unknown the `preview:` block is not written at all (a preview
with nothing to open is not one), and the question is the first line of the pull request.

THE MANIFEST KEEPS ITS COMMENTS. `merge_field` APPENDS the block to the end of the file and checks
that the result means exactly the old file plus one key; only when appending cannot do that is the
file re-dumped, and the pull request says the comments were lost. A tool that tidies somebody
else's file on the way past has not proposed anything — it has overwritten them.

THE FACTORY NEVER OPENS ONE OF THESE FROM A CARD. A job that reaches its gate on a project with no
`preview:` asks the forge whether a proposal is OPEN (`open_proposal`, a read) and the card says
so; opening one is a person's verb (`openfactory preview propose`, `onboard --with-preview`).
"""

from __future__ import annotations

import json
import logging
import re
import shutil
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field, ValidationError

from openfactory import namespace, preview
from openfactory.onboarding.infer import INFERRED, OBSERVED, UNKNOWN, Evidence
from openfactory.onboarding.preview_infer import (
    ANSWERED,
    DRAFT_COMPOSE,
    NOT_QUOTED,
    DockerfileDraft,
    Env,
    PreviewProposal,
    Service,
    infer_preview,
    weakest,
)
from openfactory.util.bounded import BoundedDict

log = logging.getLogger("openfactory.onboarding.preview_propose")

#: Deterministic, so a second run finds its own open pull request instead of opening another.
BRANCH = "openfactory/preview"
#: What `preview_infer` writes where a command needs the registry's project name, which a pure
#: reading of a repository cannot know. Filled in when the text reaches a person.
PROJECT = "<project>"

#: The block's fields that are lists; a `--set` value for one is split on commas.
_LISTS = frozenset({"compose", "exclude"})


def writable(tier: str, accept: bool) -> bool:
    """Whether a line of this tier is written: observed always, inferred with `--accept`, a
    person's answer always — and an `unknown` never."""
    return tier in (OBSERVED, ANSWERED) or (tier == INFERRED and accept)


# ── the manifest, with its comments ─────────────────────────────────────────────────────────────


class Merged(BaseModel):
    """The manifest with one key added — or why it was not."""

    text: str = ""
    #: False when appending could not be made to mean the old file plus one key and the file
    #: was re-dumped: the pull request says so
    comments_kept: bool = True
    refusal: str = ""


def merge_field(manifest_text: str, key: str, block: Any, *, rendered: str = "") -> Merged:
    """`manifest_text` with `key: block` added, comments and all.

    APPENDED, then proved: the appended text must parse to exactly the old mapping plus the one
    key, and validate as a `Manifest`. A file that ends inside a flow mapping, carries a document
    end marker, or is itself a flow mapping cannot take an append that means that, and only then
    is it loaded, extended and dumped — `comments_kept=False`, which the caller must say out loud.
    `rendered` is the block's own text (with its tier comments); it must parse to `{key: block}`.
    A key the file already declares is refused: that is the person's to edit, in the repository."""
    from openfactory.contracts.manifest import Manifest

    try:
        current = yaml.safe_load(manifest_text) if manifest_text.strip() else {}
    except yaml.YAMLError as exc:
        problem = getattr(exc, "problem", None) or str(exc).splitlines()[0]
        return Merged(refusal=f"the manifest is not valid YAML ({problem}) — fix it first; "
                              f"nothing was written.")
    current = current if current is not None else {}
    if not isinstance(current, dict):
        return Merged(refusal="the manifest is not a mapping — fix it first; nothing was written.")
    if key in current:
        return Merged(refusal=f"the manifest already declares `{key}:` — edit it in the "
                              f"repository; a proposal never overwrites what a person wrote.")
    wanted = {**current, key: block}
    piece = rendered or yaml.safe_dump({key: block}, sort_keys=False, default_flow_style=False,
                                       allow_unicode=True)
    appended = (manifest_text.rstrip("\n") + "\n\n" + piece) if manifest_text.strip() else piece
    try:
        if yaml.safe_load(appended) == wanted:
            Manifest.model_validate(wanted)
            return Merged(text=appended)
    except yaml.YAMLError:
        pass
    except ValidationError as exc:
        return Merged(refusal=f"`{key}:` would not validate in the manifest: "
                              f"{_first_error(exc)}")
    try:
        Manifest.model_validate(wanted)
    except ValidationError as exc:
        return Merged(refusal=f"`{key}:` would not validate in the manifest: "
                              f"{_first_error(exc)}")
    return Merged(text=yaml.safe_dump(wanted, sort_keys=False, default_flow_style=False,
                                      allow_unicode=True), comments_kept=False)


def _first_error(exc: ValidationError) -> str:
    errors = exc.errors()
    if not errors:
        return str(exc).splitlines()[0]
    err = errors[0]
    where = ".".join(str(p) for p in err.get("loc", ()))
    return f"{where}: {err.get('msg', '')}" if where else str(err.get("msg", ""))


def dotted(pairs: list[str]) -> dict[str, Any]:
    """`preview.expose.app=8000` → `{"preview": {"expose": {"app": 8000}}}`.

    Digits become integers (a port is a number); a value for `compose` or `exclude` is split on
    commas (both are lists); everything else stays the string a person typed. Raises `ValueError`
    naming the pair that is not `<dotted.path>=<value>`, or that contradicts an earlier one."""
    out: dict[str, Any] = {}
    for pair in pairs:
        key, sep, raw = str(pair).partition("=")
        parts = key.strip().split(".")
        if not sep or not key.strip() or any(not p.strip() for p in parts):
            raise ValueError(f"`{pair}` is not `<dotted.path>=<value>` (e.g. "
                             f"`preview.expose.app=8000`)")
        value: Any = raw.strip()
        if re.fullmatch(r"\d+", value):
            value = int(value)
        elif parts[-1] in _LISTS and len(parts) == 2:
            value = [v.strip() for v in value.split(",") if v.strip()]
        node = out
        for part in parts[:-1]:
            nxt = node.setdefault(part, {})
            if not isinstance(nxt, dict):
                raise ValueError(f"`{pair}` sets a key inside `{part}`, which an earlier "
                                 f"`--set` gave a value")
            node = nxt
        if isinstance(node.get(parts[-1]), dict):
            raise ValueError(f"`{pair}` gives `{parts[-1]}` a value, and an earlier `--set` put "
                             f"keys inside it")
        node[parts[-1]] = value
    return out


# ── what is written ─────────────────────────────────────────────────────────────────────────────


class Row(BaseModel):
    """One line of the pull request's table: what, its tier, where it was read."""

    what: str
    tier: str
    where: str


class Draft(BaseModel):
    """What a proposal WRITES, once the tiers have been applied."""

    #: repository path → text, every file the pull request adds
    files: dict[str, str] = Field(default_factory=dict)
    #: the `preview:` block, or None when it cannot be written
    block: dict[str, Any] | None = None
    block_text: str = ""
    #: the services the drafted compose file declares
    written: list[str] = Field(default_factory=list)
    #: service → the environment names written for it
    environment: dict[str, list[str]] = Field(default_factory=dict)
    rows: list[Row] = Field(default_factory=list)
    #: what was read and NOT written, and what writes it
    left_out: list[str] = Field(default_factory=list)
    #: why the block is not written — the pull request's first line
    first: str = ""
    refusal: str = ""


def _cite(evidence: list[Evidence]) -> str:
    return ", ".join(dict.fromkeys(e.locator for e in evidence)) or "—"


def draft(proposal: PreviewProposal, *, accept: bool = False,
          answers: dict[str, Any] | None = None) -> Draft:
    """Apply the tiers to a reading: what is written, what is left out and why, and the block."""
    from openfactory.contracts.manifest import PreviewConfig

    if proposal.case == "declared":
        return Draft(refusal="the manifest already declares `preview:` — edit it in the "
                             "repository; a proposal never overwrites what a person wrote.")
    answers = answers or {}
    stray = sorted(set(answers) - {"preview"})
    if stray:
        return Draft(refusal=f"`--set` writes the `preview:` block and nothing else — "
                             f"{', '.join(f'`{s}`' for s in stray)} is not in it.")
    asked = answers.get("preview") or {}
    if not isinstance(asked, dict):
        return Draft(refusal="`--set preview=…` would replace the whole block — set its fields "
                             "(`preview.expose.<service>=<port>`).")
    out = Draft()
    services = {s.name: s for s in proposal.services}
    included = {n for n, s in services.items() if writable(s.tier, accept)}
    for name in sorted(set(services) - included):
        svc = services[name]
        out.left_out.append(f"`{name}` ({svc.tier} · {_cite(svc.evidence)}) — "
                            + ("`--accept` writes it" if svc.tier == INFERRED else "not drafted"))
    envs: dict[str, list[Env]] = {}
    for name in sorted(included):
        kept = []
        for env in services[name].environment:
            if services[name].kind == "store" or (writable(env.tier, accept)
                                                  and set(env.needs) <= included):
                kept.append(env)
            elif not writable(env.tier, accept):
                out.left_out.append(f"`{name}`'s `{env.name}` ({env.tier} · "
                                    f"{_cite(env.evidence)}) — `--accept` writes it")
            else:
                out.left_out.append(f"`{name}`'s `{env.name}` — it points at "
                                    f"{', '.join(f'`{n}`' for n in env.needs)}, which is not "
                                    f"written")
        envs[name] = kept
    order = [s.name for s in proposal.services if s.name in included]
    out.written = order
    out.environment = {n: [e.name for e in envs.get(n, [])] for n in order}
    override = bool(proposal.overrides)
    if order:
        out.files[DRAFT_COMPOSE] = render_compose(proposal, order, envs, included,
                                                  override=override)
    for df in proposal.dockerfiles:
        if df.service in included:
            out.files[df.path] = render_dockerfile(df, proposal)
            out.files[df.ignore] = render_dockerignore(df)
    out.files = dict(sorted(out.files.items()))

    # the block
    first_file = proposal.compose.value[0] if (proposal.case == "compose"
                                               and proposal.compose.value) else ""
    compose: list[str] | None = None
    if first_file:
        compose = [first_file] + ([DRAFT_COMPOSE] if DRAFT_COMPOSE in out.files else [])
    elif DRAFT_COMPOSE in out.files:
        compose = [DRAFT_COMPOSE]
    present = ({e.name for e in proposal.existing} | included) if first_file else included
    block: dict[str, Any] = {}
    tiers: dict[str, str] = {}
    if compose:
        block["compose"] = compose
        tiers["compose"] = weakest(OBSERVED, *(services[n].tier for n in included)) \
            if not first_file else OBSERVED
    for field, found in (("expose", proposal.expose), ("data", proposal.data)):
        for name, p in sorted(found.items()):
            if p.value is None:
                continue
            if name in present and writable(p.confidence, accept):
                block.setdefault(field, {})[name] = p.value
                tiers[f"{field}.{name}"] = p.confidence
            elif name in present:
                out.left_out.append(f"`preview.{field}.{name}` = {p.value} ({p.confidence} · "
                                    f"{_cite(p.evidence)}) — `--accept` writes it")
    for key, value in sorted(asked.items()):
        if isinstance(value, dict):
            for inner, v in sorted(value.items()):
                block.setdefault(key, {})
                if not isinstance(block[key], dict):
                    block[key] = {}
                block[key][inner] = v
                tiers[f"{key}.{inner}"] = ANSWERED
        else:
            block[key] = [value] if key in _LISTS and isinstance(value, str) else value
            tiers[key] = ANSWERED
    named = sorted({n for field in ("expose", "data") for n in (block.get(field) or {})}
                   | set(block.get("exclude") or []))
    stray = [n for n in named if n not in present]
    # A FILE A PERSON NAMED is one this reading never opened, so its services are theirs to name;
    # admission checks every name against it when a preview is planned.
    if stray and asked and "compose" not in asked:
        return Draft(refusal=f"`--set` names {', '.join(f'`{n}`' for n in stray)}, which this "
                             f"proposal does not run (it runs "
                             f"{', '.join(f'`{n}`' for n in sorted(present)) or 'nothing'})"
                             + (" — `--accept` writes the inferred services" if not accept
                                else "") + ".")
    if "compose" not in block:
        if proposal.compose.confidence == UNKNOWN and proposal.compose.note:
            out.first = proposal.compose.note
        elif out.left_out:
            out.first = ("everything drafted here is inferred, and nothing inferred is written "
                         "without `--accept`.")
        else:
            out.first = next(iter(proposal.questions), "nothing here could be drafted.")
    elif not block.get("expose"):
        out.first = next((p.note for _, p in sorted(proposal.expose.items())
                          if p.confidence == UNKNOWN and p.note), "") or \
            "which service does a person open in a preview, and on which port? Answer with " \
            "`--set preview.expose.<service>=<port>`."
    else:
        try:
            PreviewConfig.model_validate(block)
        except ValidationError as exc:
            return Draft(refusal=f"the `preview:` block would not validate: {_first_error(exc)}")
        out.block = block
        out.block_text = render_block(block, tiers, proposal)
    out.rows = _rows(proposal, out, included, envs, tiers)
    return out


def _rows(proposal: PreviewProposal, out: Draft, included: set[str],
          envs: dict[str, list[Env]], tiers: dict[str, str]) -> list[Row]:
    rows: list[Row] = []
    if out.block is not None:
        rows.append(Row(what=f"`preview.compose` = {', '.join(out.block['compose'])}",
                        tier=tiers.get("compose", OBSERVED),
                        where=_cite(proposal.compose.evidence)))
        for field in ("expose", "data"):
            for name, value in (out.block.get(field) or {}).items():
                found = (proposal.expose if field == "expose" else proposal.data).get(name)
                tier = tiers.get(f"{field}.{name}", OBSERVED)
                rows.append(Row(what=f"`preview.{field}.{name}` = {_shown(value)}", tier=tier,
                                where="`--set`" if tier == ANSWERED else
                                _cite(found.evidence if found else [])))
    for svc in proposal.services:
        if svc.name not in included:
            continue
        rows.append(Row(what=f"service `{svc.name}`: {_what(svc, proposal)}", tier=svc.tier,
                        where=_cite(svc.evidence)))
        if svc.kind == "store":
            continue
        for env in envs.get(svc.name, []):
            shown = f"`{svc.name}` receives `{env.name}`" + (" (and as a build argument)"
                                                               if env.build_arg else "")
            rows.append(Row(what=shown, tier=env.tier, where=_cite(env.evidence)))
    for df in proposal.dockerfiles:
        if df.service not in included:
            continue
        rows.append(Row(what=f"`{df.path}`: `FROM {df.base}`", tier=INFERRED,
                        where=_cite([df.base_evidence])))
        rows.append(Row(what=f"`{df.path}`: installs with "
                             f"{', '.join(f'`{c}`' for c in df.install)}",
                        tier=df.install_tier, where=_cite(df.install_evidence)))
        rows.append(Row(what=f"`{df.path}`: starts `{_command(df.command)}`",
                        tier=df.command_tier, where=_cite([df.command_evidence])))
    return rows


def _shown(value: Any) -> str:
    if isinstance(value, list):
        return "`" + " ".join(map(str, value)) + "`"
    return f"`{value}`" if isinstance(value, str) else str(value)


def _command(command: str | list[str]) -> str:
    return command if isinstance(command, str) else " ".join(command)


def _what(svc: Service, proposal: PreviewProposal) -> str:
    if svc.kind == "store":
        return f"`{svc.image}`, healthchecked, a fresh volume for every preview"
    if svc.kind == "patch" and not svc.dockerfile:
        return "re-pointed at a drafted stand-in"
    if svc.kind == "draft":
        return f"built with the drafted `{svc.dockerfile}`"
    return f"built from {_where(_in_repo(proposal, svc))} with `{svc.dockerfile}`"


# ── rendering the files, by hand, so every line can say where it was read ────────────────────────

_PLAIN = re.compile(r"^[A-Za-z0-9_./@+-][A-Za-z0-9_./@:+-]*$")
_YAML_WORDS = frozenset({"true", "false", "yes", "no", "on", "off", "null", "y", "n", "~"})


def _scalar(value: Any) -> str:
    """A YAML scalar that parses back to exactly `value`: plain when that is unambiguous, a JSON
    string (which YAML reads as a double-quoted one) otherwise — `"1"` stays the string `1`, and
    `${OPENFACTORY_PREVIEW_URL_API}` stays one token."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    text = str(value)
    if _PLAIN.match(text) and text.lower() not in _YAML_WORDS and not text.endswith(":"):
        try:
            if yaml.safe_load(text) == text:
                return text
        except yaml.YAMLError:
            pass
    return json.dumps(text)


def _comment(tier: str, evidence: list[Evidence], note: str = "") -> str:
    return f"# {tier} · {_cite(evidence)}" + (f" — {note}" if note else "")


def render_compose(proposal: PreviewProposal, order: list[str], envs: dict[str, list[Env]],
                   included: set[str], *, override: bool) -> str:
    """The drafted compose file — or the override, merged after the client's own file."""
    services = {s.name: s for s in proposal.services}
    lines = [f"# A preview of `{proposal.name}`, drafted by `openfactory preview propose` from "
             f"files in this repository",
             "# (ADR-0050). Nothing was built or run. Each entry says where it was read: "
             "`observed` is a line",
             "# of yours, `inferred` a convention those lines imply. Edit anything wrong before "
             "merging."]
    if override:
        first = proposal.overrides[0]
        lines += ["#",
                  f"# Merged AFTER `{first}`. Relative paths here resolve against THAT file's "
                  f"directory — the",
                  "# compose CLI resolves every file it merges that way — so `.` is the "
                  "repository root."]
    else:
        lines += ["#",
                  "# Relative paths resolve against THIS file's directory (`.openfactory/`), so "
                  "`..` is the",
                  "# repository root."]
    lines.append("services:")
    volumes: list[str] = []
    for name in order:
        svc = services[name]
        lines.append(f"  {_scalar(name)}:")
        if svc.kind == "store":
            lines.append("    " + _comment(svc.tier, svc.evidence,
                                           "a fresh store only this preview reaches; its values "
                                           "are throwaway"))
            lines.append(f"    image: {_scalar(svc.image)}")
        elif svc.dockerfile:
            note = "; ".join(svc.notes) if svc.kind == "patch" else ""
            lines.append("    " + _comment(svc.tier, svc.evidence, note))
            lines.append("    build:")
            lines.append(f"      context: {_scalar(svc.context)}")
            lines.append(f"      dockerfile: {_scalar(svc.dockerfile)}")
            args = [e for e in envs.get(name, []) if e.build_arg]
            if args:
                lines.append("      args:")
                for env in args:
                    lines.append("        " + _comment(env.tier, env.evidence))
                    lines.append(f"        {env.name}: {_scalar(env.value)}")
        env_lines = envs.get(name, [])
        if env_lines:
            lines.append("    environment:")
            for env in env_lines:
                if svc.kind != "store":
                    lines.append("      " + _comment(env.tier, env.evidence, env.note))
                lines.append(f"      {env.name}: {_scalar(env.value)}")
        deps = [d for d in svc.depends_on if d in included]
        if deps:
            lines.append("    depends_on:")
            for dep in deps:
                lines.append(f"      {_scalar(dep)}:")
                lines.append("        condition: service_healthy")
        if svc.healthcheck:
            lines.append("    healthcheck:")
            lines.append(f"      test: {json.dumps(svc.healthcheck)}")
            lines += ["      interval: 2s", "      timeout: 5s", "      retries: 30"]
        if svc.volume:
            lines.append("    volumes:")
            lines.append(f"      - {_scalar(svc.volume)}")
            volumes.append(svc.volume.split(":", 1)[0])
    if volumes:
        lines.append("volumes:")
        lines += [f"  {_scalar(v)}: {{}}" for v in volumes]
    return "\n".join(lines) + "\n"


def render_dockerfile(df: DockerfileDraft, proposal: PreviewProposal) -> str:
    """A Dockerfile for a repository that has none, every line cited."""
    ignore = Path(df.ignore).name
    lines = [
        f"# A Dockerfile for a preview of `{proposal.name}`, drafted by `openfactory preview "
        f"propose` (ADR-0050).",
        "# Nothing was built or run: `--prove` builds it once, from the base branch, on the "
        "deployment's",
        "# own daemon — never on a laptop. Each line says where it was read.",
        _comment(INFERRED, [df.base_evidence]),
        f"FROM {df.base}",
        "WORKDIR /app",
        "# The repository's own files and directories — never `COPY . .` — and "
        f"{ignore}",
        "# keeps `.git` and every `.env` out of them too.",
    ]
    if df.copy_files:
        lines.append(f"COPY {' '.join(df.copy_files)} ./")
    lines += [f"COPY {d} ./{d}" for d in df.copy_dirs]
    lines.append(_comment(df.install_tier, df.install_evidence, "the manifest's `setup:`"
                          if df.install_tier == OBSERVED else ""))
    lines += [f"RUN {command}" for command in df.install]
    if df.port is not None and df.port_evidence is not None:
        lines.append(_comment(df.port_tier, [df.port_evidence]))
        if df.reads_port:
            lines.append(f"ENV PORT={df.port}")
        lines.append(f"EXPOSE {df.port}")
    lines.append(_comment(df.command_tier, [df.command_evidence]))
    lines.append(f"CMD {df.command}" if isinstance(df.command, str)
                 else f"CMD {json.dumps(df.command)}")
    return "\n".join(lines) + "\n"


def render_dockerignore(df: DockerfileDraft) -> str:
    """What never goes into the drafted image. Named `<Dockerfile>.dockerignore` beside it: that is
    the name BuildKit reads for a Dockerfile that is not the context's own `Dockerfile`."""
    return "\n".join([
        f"# Beside {Path(df.path).name}: what never goes into the image — the repository's "
        f"history, every env",
        "# file, and dependencies installed on somebody's machine.",
        ".git",
        ".env*",
        "node_modules",
    ]) + "\n"


def render_block(block: dict[str, Any], tiers: dict[str, str], proposal: PreviewProposal) -> str:
    """The `preview:` block as it is appended to the manifest, each line with its tier."""
    lines = ["# How a preview of this product runs (ADR-0050) — proposed by `openfactory preview "
             "propose`;",
             "# the pull request that added it says where each line was read.",
             "preview:"]
    compose = block.get("compose") or []
    lines.append(f"  compose: [{', '.join(_scalar(c) for c in compose)}]")
    for field in ("expose", "data"):
        values = block.get(field) or {}
        if not values:
            continue
        lines.append(f"  {field}:")
        for name, value in values.items():
            shown = json.dumps(value) if isinstance(value, list) else _scalar(value)
            tier = tiers.get(f"{field}.{name}", OBSERVED)
            found = (proposal.expose if field == "expose" else proposal.data).get(name)
            where = "`--set`" if tier == ANSWERED else _cite(found.evidence if found else [])
            lines.append(f"    {_scalar(name)}: {shown}   # {tier} · {where}")
    if block.get("exclude"):
        lines.append(f"  exclude: [{', '.join(_scalar(e) for e in block['exclude'])}]")
    return "\n".join(lines) + "\n"


# ── the pull request's body ─────────────────────────────────────────────────────────────────────


def _host(project: str, service: str) -> str:
    domain = preview.domain() or "<preview domain>"
    return f"{preview.host_label(project, '<n>', service)}.{domain}"


def _quote(evidence: list[Evidence]) -> list[str]:
    return [f"  - {e.excerpt if e.excerpt == NOT_QUOTED else f'`{e.excerpt}`'} — {e.locator}"
            for e in evidence if e.excerpt]


def pr_body(proposal: PreviewProposal, out: Draft, *, project: str, repo: str,
            proof: str = "", comments_kept: bool = True) -> str:
    """The pull request's body: what was read, the fixed section a person signs off, and every
    line's tier and source. Deterministic — the same reading gives the same bytes."""
    def say(text: str) -> str:
        return text.replace(PROJECT, project)

    lines: list[str] = []
    if out.block is None:
        lines += [f"**Before this can be previewed:** {say(out.first)}", ""]
    theirs = (proposal.overrides or proposal.compose.value or [""])[0]
    what = {"compose": f"the `preview:` block for the team's own `{theirs}`"
            + (" and an override beside it" if DRAFT_COMPOSE in out.files else ""),
            "dockerfiles": "a compose file drafted from its "
                           + ("Dockerfile" if sum(s.kind == "build" for s in proposal.services)
                              == 1 else "Dockerfiles") + ", and the `preview:` block",
            "draft": "a Dockerfile and a compose file drafted from what it says it runs, and the "
                     "`preview:` block"}.get(proposal.case, "what could be drafted")
    lines += [
        f"A preview of `{repo}`: {what}. **It was read from this repository, not invented** — "
        f"every line below cites the file it came from, and the fields nothing could answer were "
        f"left out rather than guessed.",
        "",
        proof or ("**Not built.** Nothing in this pull request was built or run, on any "
                  f"machine. `openfactory preview propose {project} --prove`, run where the "
                  f"deployment's preview runtime is, builds the base branch with this draft "
                  f"applied, once, on the deployment's own daemon — and takes it down."),
        "",
        "## What merging this lets the factory do",
        "",
        "Anyone the panel lets into this project can start this on the factory's daemon, on "
        "demand, and open it under the preview domain.",
    ]
    lines += _per_service(proposal, out, project)
    if out.rows:
        lines += ["", "## Each line, and where it was read", "",
                  "| what | tier | read from |", "|---|---|---|"]
        lines += [f"| {r.what} | {r.tier} | {r.where} |" for r in out.rows]
    questions = [q for q in proposal.questions if q != out.first]
    if questions:
        lines += ["", "## Questions only your team can answer", ""]
        lines += [f"- {say(q)}" for q in questions]
    if proposal.registry:
        lines += ["", "## For the registry, not this file", "",
                  "The application reads these names and their values are secrets or "
                  "per-environment, so they are never written into a file. The operator names "
                  "them for previews:", ""]
        for r in proposal.registry:
            lines.append(f"- `{r.name}` ({r.locator}) — {r.why}: `openfactory project "
                         f"set-preview {project} --env {r.service}={r.name}=<WORKER_NAME>`")
    if proposal.flags:
        lines += ["", "## Flagged", ""]
        for f in proposal.flags:
            lines.append(f"- {f.locator} gives `{f.service}` a literal `{f.name}` ({f.why}). A "
                         f"preview reads it as it is; if it is a real credential, anyone who can "
                         f"read this repository can too. Name its value in the registry instead: "
                         f"`openfactory project set-preview {project} --env "
                         f"{f.service}={f.name}=<WORKER_NAME>`.")
    notes = list(proposal.notes)
    for svc in proposal.services:
        if svc.name in out.written and svc.kind != "patch":
            notes += svc.notes
    if proposal.host_check:
        opened = sorted((out.block or {}).get("expose") or {}) or sorted(proposal.expose) or \
            [proposal.name]
        notes.append(f"{proposal.host_check}: for a named preview domain, add it to the "
                     f"application's allowed hosts — a preview forwards the browser's own "
                     f"`Host`, `{_host(project, opened[0])}`.")
    stores = [s for s in proposal.services if s.kind == "store" and s.name in out.written]
    if stores:
        notes.append(f"{_and_names([s.name for s in stores])} "
                     f"{'is' if len(stores) == 1 else 'are'} drafted with throwaway values "
                     f"(`app`/`app`) for a store only its own preview can reach; the address "
                     f"each service receives is written beside it — confirm your application "
                     f"reads that name.")
    if notes:
        lines += ["", "## Notes", ""]
        lines += [f"- {say(n)}" for n in dict.fromkeys(notes)]
    if out.left_out:
        lines += ["", "## Read, and not written", ""]
        lines += [f"- {say(n)}" for n in out.left_out]
    lines += ["", "---", "",
              "These files live under `.openfactory/` so they never collide with your own; move "
              "them and repoint `preview.compose` if you prefer. Nothing here is in effect until "
              "a person merges it, and the factory never merges it."]
    if out.block is not None and not comments_kept:
        lines += ["", f"**`{namespace.MANIFEST}` lost its comments**: the block could not be "
                      f"appended so that the file still meant the same thing, so the file was "
                      f"re-written whole. Put the comments back before merging, or add the block "
                      f"by hand."]
    return "\n".join(lines) + "\n"


def _and_names(names: list[str]) -> str:
    shown = [f"`{n}`" for n in names]
    return shown[0] if len(shown) == 1 else f"{', '.join(shown[:-1])} and {shown[-1]}"


def _in_repo(proposal: PreviewProposal, svc: Service) -> str:
    """A drafted build context as a REPOSITORY path. The file says it relative to the first
    compose file's directory, which is how the CLI reads it and not how a person does."""
    import posixpath

    first = proposal.overrides[0] if proposal.overrides else DRAFT_COMPOSE
    return posixpath.normpath(posixpath.join(posixpath.dirname(first) or ".", svc.context))


def _where(path: str) -> str:
    return "the whole repository (`.`)" if path in ("", ".") else f"`{path}/`"


def _per_service(proposal: PreviewProposal, out: Draft, project: str) -> list[str]:
    """The fixed section, one service at a time: what is built from where, what is pulled, what
    is opened and at which host, what is mounted, how its data is made."""
    block = out.block or {}
    expose = block.get("expose") or {}
    data = block.get("data") or {}
    drafted = {s.name: s for s in proposal.services if s.name in out.written}
    lines: list[str] = []
    names = [e.name for e in proposal.existing] + [n for n in out.written
                                                    if n not in {e.name for e in
                                                                 proposal.existing}]
    existing = {e.name: e for e in proposal.existing}
    for name in names:
        lines += ["", f"### `{name}`"]
        svc = drafted.get(name)
        mine = existing.get(name)
        if svc is not None and svc.kind in ("build", "patch", "draft") and svc.dockerfile:
            lines.append(f"- built from this repository: {_where(_in_repo(proposal, svc))}, "
                         f"with `{svc.dockerfile}`"
                         + (f" — instead of pulling `{mine.image}`" if mine and mine.image
                            else ""))
            if svc.kind == "draft":
                df = next(d for d in proposal.dockerfiles if d.service == name)
                lines.append(f"  - `FROM {df.base}` — drafted, {_cite([df.base_evidence])}")
                lines.append(f"  - `CMD {_command(df.command)}` — drafted, "
                             f"{_cite([df.command_evidence])}")
            else:
                lines += _quote(svc.quoted)
        elif mine is not None and mine.context:
            lines.append(f"- built from this repository: {_where(mine.context)}, with "
                         f"`{mine.dockerfile}`")
            lines += _quote(mine.quoted)
        elif svc is not None and svc.kind == "store":
            check = " ".join(svc.healthcheck[1:]) if svc.healthcheck else ""
            lines.append(f"- pulls `{svc.image}`, healthchecked with `{check}`; its data is a "
                         f"volume that is fresh for every preview")
        elif mine is not None and mine.image:
            lines.append(f"- pulls `{mine.image}`, every time a preview starts")
        if name in expose:
            lines.append(f"- opened on port {expose[name]}, as `{_host(project, name)}`")
        else:
            lines.append("- not opened: only the other services reach it")
        binds = mine.binds if mine is not None else []
        lines.append("- bind mounts: " + (", ".join(f"`{b}`" for b in binds) if binds
                                          else "none"))
        if name in data:
            value = data[name]
            lines.append(f"- data: `{_command(value)}`, run inside `{name}` once it is up")
        elif name in proposal.data:
            lines.append("- data: not declared — asked below")
        if svc is not None and svc.kind == "patch":
            for env in svc.environment:
                if env.name in out.environment.get(name, []):
                    lines.append(f"- `{env.name}` re-pointed at "
                                 f"{', '.join(f'`{n}`' for n in env.needs)}")
    return lines


# ── the card, while there is no preview to start ────────────────────────────────────────────────


class Shape(BaseModel):
    """What a card's job read about the base's shape, carried on the preview's record so the
    panel can say — at the moment it is asked — what would give this change a preview."""

    #: "compose" · "dockerfiles" · "draft" · "nothing"; "" = the base declares `preview:`
    case: str = ""
    #: what the repository says a draft could be read from (`Dockerfile, EXPOSE 8000`)
    reads: str = ""
    base: str = "main"
    repo: str = ""


def offer_facts(root: str | Path, *, repo: str = "", base: str = "main") -> Shape:
    """Read a BASE checkout for the card's record: whether it declares `preview:` and, when it
    does not, what a draft could be read from. Pure — `infer_preview` underneath — so the job
    that calls it never runs a runtime and never opens a proposal."""
    found = infer_preview(root, name=repo.rsplit("/", 1)[-1] if repo else "")
    if found.case == "declared":
        return Shape(repo=repo, base=base)
    return Shape(case=found.case, reads=found.said(), base=base, repo=repo)


def card_sentence(shape: Shape, *, project: str, proposal_url: str = "") -> str:
    """Why this change has no preview, and the one thing that gives it one — §4.3's sentences.
    Computed when the card is READ, because the proposal is opened and merged after the job wrote
    its record: the answer is the forge's now, not the record's then."""
    repo = shape.repo or project
    if proposal_url:
        what = {"compose": f"The block for its `{shape.reads}`",
                "dockerfiles": "A compose file drafted from its Dockerfile and the block",
                "draft": f"A Dockerfile and a compose file drafted from {shape.reads}"}.get(
            shape.case, "A draft")
        verb = "is" if shape.case == "compose" else "are"
        return (f"No preview of this change yet — `{repo}` declares no `preview:`. {what} {verb} "
                f"proposed at {proposal_url}; merge it (edit it first if it is wrong) and press "
                f"start here.")
    if shape.case in ("compose", "dockerfiles"):
        return (f"No preview of this change yet — `{repo}` declares no `preview:`; run "
                f"`openfactory preview propose {project}` to have one drafted from what the "
                f"repository says: {shape.reads}.")
    if shape.case == "draft":
        return (f"No preview of this change yet — nothing on `{shape.base}` says how it runs (no "
                f"compose file, no Dockerfile). `openfactory preview propose {project}` drafts "
                f"both from {shape.reads}.")
    return (f"No preview of this change yet — nothing on `{shape.base}` says how it runs (no "
            f"compose file, no Dockerfile), and nothing there anchors a draft. `openfactory "
            f"preview propose {project} --as-card` files the question as a card.")


#: (project, repo) → (when it was asked, the open proposal's URL). A minute: a card is re-read
#: every few seconds while somebody looks at it, and the forge's rate limit is somebody else's too.
#: BOUNDED, because the repository in the key comes from a record, not from the registry alone.
_ASKED: BoundedDict[tuple[str, str], tuple[float, str | None]] = BoundedDict(512)
_ASK_FOR = 60.0


def open_proposal(project, repo: str = "", *, forge=None, now: float | None = None) -> str | None:
    """The preview proposal still OPEN on `repo` — `""` for none, None for "could not ask". A READ:
    nothing here opens one."""
    from openfactory.onboarding.propose_manifest import already_proposed

    now = time.time() if now is None else now
    if not repo:
        from openfactory.adapters.forge.registry import repo_of

        repo = repo_of(project)
    key = (getattr(project, "name", str(project)), repo)
    cached = _ASKED.get(key)
    if cached is not None and now - cached[0] < _ASK_FOR:
        return cached[1]
    if forge is None:
        from openfactory.adapters.forge.registry import build_forge
        from openfactory.credentials import deployment_forge_token, forge_token_for

        try:
            forge = build_forge(project, token=forge_token_for(project)
                                or deployment_forge_token(project))
        except Exception:  # noqa: BLE001 — no forge is "could not ask", never "none open"
            log.info("could not build %s's forge to ask about its preview proposal",
                     key[0], exc_info=True)
            return None
    found = already_proposed(forge, repo, BRANCH)
    _ASKED[key] = (now, found)
    return found


def proposal_said(record, project, *, forge=None, now: float | None = None) -> dict[str, str]:
    """`{proposal_url, why}` for a card whose base declares no shape — asked of the forge NOW
    (cached a minute), the record's own URL only when the forge cannot be asked."""
    shape = Shape.model_validate(getattr(record, "shape", None) or {})
    if not shape.case:
        return {}
    url = open_proposal(project, shape.repo, forge=forge, now=now)
    if url is None:
        url = getattr(record, "proposal_url", "") or ""
    return {"proposal_url": url,
            "why": card_sentence(shape, project=getattr(project, "name", str(project)),
                                 proposal_url=url)}


# ── the verb ────────────────────────────────────────────────────────────────────────────────────


class Outcome(BaseModel):
    """What one proposal did, in the terms a person acts on."""

    ok: bool = False
    repo: str = ""
    url: str = ""
    existed: bool = False
    #: nothing could be drafted: the questions are the answer, and `--as-card` files them
    nothing: bool = False
    #: the one-machine kind: files written into the person's checkout, to commit
    wrote: list[str] = Field(default_factory=list)
    base: str = ""
    card: str = ""
    detail: str = ""
    questions: list[str] = Field(default_factory=list)
    body: str = ""


#: The proof, handed in by the caller: `(project, files, block) -> sentence`. The CLI builds it
#: from the deployment's preview runtime; a test hands a recorder. This module never builds.
Prover = Callable[[Any, dict[str, str], dict[str, Any]], str]


def proof_sentence(up, seconds: int) -> str:
    """What the deployment's proof answered, for the pull request's body: built and up (and how
    each opened service showed it), or the first reason it was not."""
    took = f"{seconds // 60}m{seconds % 60:02d}s"
    if getattr(up, "ok", False):
        health = getattr(up, "health", {}) or {}
        shown = " · ".join(f"{svc}: {'healthy' if how == 'healthy' else 'started, not '
                                                                        'health-checked'}"
                           for svc, how in sorted(health.items()))
        return (f"**Proved on the deployment:** the base branch with this draft applied was "
                f"built, came up and was taken down again in {took}"
                + (f" — {shown}." if shown else "."))
    why = str(getattr(up, "why", "") or "it said nothing")
    return (f"**Proved on the deployment, and it did not come up** ({took}): {why} Read this "
            f"before merging.")


def _is_url(raw: str) -> bool:
    return "://" in raw or raw.startswith("git@")


def _short(repo: str) -> str:
    return repo.rstrip("/").rsplit("/", 1)[-1] if repo else ""


class _Written(BaseModel):
    proposal: PreviewProposal
    out: Draft
    merged: Merged | None = None
    paths: list[str] = Field(default_factory=list)
    base: str = "main"


def _draft_into(checkout: Path, project, *, repo: str, accept: bool,
                answers: dict[str, Any] | None) -> _Written | Outcome:
    """Read `checkout`, draft, and WRITE the draft into it — files and the manifest's block.

    Refuses rather than overwrites: a drafted path that already exists is the person's file, and
    a manifest that already declares `preview:` is theirs to edit."""
    manifest_rel = str(getattr(project, "manifest_path", "") or namespace.MANIFEST)
    try:
        manifest = namespace.resolve(checkout, manifest_rel, project=project.name)
    except namespace.RetiredNamespace as exc:
        return Outcome(repo=repo, detail=str(exc))
    if not manifest.is_file():
        return Outcome(repo=repo, detail=(
            f"`{repo}` declares no manifest on its base branch, and the `preview:` block goes "
            f"into it — `openfactory onboard {project.name} --yes` proposes the manifest; propose "
            f"the preview once that is merged. Nothing was written."))
    text = manifest.read_text(encoding="utf-8")
    proposal = infer_preview(checkout, name=_short(repo) or project.name)
    out = draft(proposal, accept=accept, answers=answers)
    if out.refusal:
        return Outcome(repo=repo, detail=out.refusal + " Nothing was written.",
                       questions=proposal.questions)
    if not out.files and out.block is None:
        if out.left_out:
            # READ, AND ALL OF IT INFERRED: not "nothing here", which would send a person looking
            # for a file they have — the draft exists and waits for their `--accept`.
            return Outcome(ok=True, repo=repo, nothing=True, questions=proposal.questions,
                           detail=(f"everything drafted for `{repo}` is inferred, and nothing "
                                   f"inferred is written without `--accept` — "
                                   f"`openfactory preview draft {project.name}` shows it line by "
                                   f"line. Nothing was written."))
        return Outcome(ok=True, repo=repo, nothing=True, questions=proposal.questions,
                       detail=(f"nothing could be drafted for `{repo}` — "
                               + (proposal.questions[0] if proposal.questions else
                                  "the repository says nothing about how it runs")
                               + " Nothing was written."))
    clash = sorted(p for p in out.files if (checkout / p).exists())
    if clash:
        return Outcome(repo=repo, detail=(
            f"{', '.join(f'`{p}`' for p in clash)} already "
            f"{'exists' if len(clash) == 1 else 'exist'} in `{repo}` — a proposal never "
            f"overwrites a file of yours. Nothing was written."))
    merged = None
    if out.block is not None:
        merged = merge_field(text, "preview", out.block, rendered=out.block_text)
        if merged.refusal:
            return Outcome(repo=repo, detail=merged.refusal)
    for rel, body in out.files.items():
        target = checkout / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(body, encoding="utf-8")
    paths = list(out.files)
    if merged is not None:
        manifest.write_text(merged.text, encoding="utf-8")
        paths.insert(0, str(manifest.relative_to(checkout)))
    try:
        doc = yaml.safe_load(text) or {}
        base = str(doc.get("base_branch") or "main") if isinstance(doc, dict) else "main"
    except yaml.YAMLError:
        base = "main"
    return _Written(proposal=proposal, out=out, merged=merged, paths=paths, base=base)


def propose_preview(project, *, repo: str = "", accept: bool = False,
                    answers: dict[str, Any] | None = None, as_card: bool = False,
                    prove: Prover | None = None) -> Outcome:
    """Draft this project's preview and propose it: a pull request on `openfactory/preview` for a
    repository the factory reaches by URL, or files written into the checkout of a one-machine
    project, to commit. `as_card` files the questions as a card instead. `prove`, when given, is
    the deployment's proof of the base branch with the draft applied; its sentence goes into the
    pull request's body."""
    raw = str(getattr(project, "repo_path", "") or "")
    if _is_url(raw):
        return _propose_hosted(project, repo=repo, accept=accept, answers=answers,
                               as_card=as_card, prove=prove)
    return _propose_local(project, repo=repo, accept=accept, answers=answers, as_card=as_card,
                          prove=prove)


def _propose_local(project, *, repo: str, accept: bool, answers: dict[str, Any] | None,
                   as_card: bool, prove: Prover | None) -> Outcome:
    """The one-machine kind (ADR-0049): the repository is the person's own, so the draft is written
    into their checkout — never committed by us — and they commit it on the base branch, the
    `project init` shape."""
    from openfactory.adapters.forge.registry import repo_of

    checkout = Path(str(project.repo_path)).expanduser()
    repo = repo or repo_of(project) or project.name
    if not checkout.is_dir():
        return Outcome(repo=repo, detail=f"`{project.name}` is registered at {checkout}, and there "
                                         f"is no directory there. Nothing was written.")
    if as_card:
        return _as_card(project, repo, infer_preview(checkout, name=_short(repo) or project.name))
    written = _draft_into(checkout, project, repo=repo, accept=accept, answers=answers)
    if isinstance(written, Outcome):
        return written
    proof = prove(project, written.out.files, written.out.block or {}) if prove and \
        written.out.block else ""
    body = pr_body(written.proposal, written.out, project=project.name, repo=repo, proof=proof,
                   comments_kept=written.merged is None or written.merged.comments_kept)
    return Outcome(ok=True, repo=repo, wrote=written.paths, base=written.base, body=body,
                   questions=written.proposal.questions,
                   detail=(f"wrote {', '.join(f'`{p}`' for p in written.paths)} into {checkout} "
                           f"— commit these on `{written.base}`; a preview reads the base "
                           f"branch, never a working tree."))


def _propose_hosted(project, *, repo: str, accept: bool, answers: dict[str, Any] | None,
                    as_card: bool, prove: Prover | None) -> Outcome:
    from openfactory.adapters.forge.registry import build_forge, clone_url_for, repo_of
    from openfactory.credentials import deployment_forge_token, forge_token_for
    from openfactory.onboarding.propose_manifest import (
        already_proposed,
        clone_for_proposal,
        default_branch,
        leaves_the_repository,
        propose,
        scrub,
    )

    repo = repo or repo_of(project)
    manifest_rel = str(getattr(project, "manifest_path", "") or namespace.MANIFEST)
    if leaves_the_repository(manifest_rel):
        return Outcome(repo=repo, detail=(
            f"`{project.name}` is registered with manifest_path {manifest_rel!r}, outside the "
            f"repository — a pull request on `{repo}` carries only files that live in it. "
            f"Nothing was cloned or written."))
    token = forge_token_for(project) or deployment_forge_token(project)
    forge = build_forge(project, token=token)
    if not as_card:
        # ASKED FIRST, so an open proposal is named before anything is cloned — or proved: a proof
        # is a build on the deployment, and one for a proposal already open is a build for nothing
        found = already_proposed(forge, repo, BRANCH)
        if found is None:
            return Outcome(repo=repo, detail=(
                f"could not ask `{repo}` whether a preview is already proposed, so nothing was "
                f"proposed — asking again in a moment is safer than opening a second pull "
                f"request."))
        if found:
            return Outcome(ok=True, repo=repo, url=found, existed=True,
                           detail=f"a preview of `{repo}` is already proposed at {found} — "
                                  f"merge or close it first.")
    try:
        url = clone_url_for(project, repo, token=token)
    except Exception as exc:  # noqa: BLE001 — the message is the finding
        return Outcome(repo=repo, detail=f"could not compose a clone URL for `{repo}`: "
                                         f"{scrub(str(exc))[:200]}")
    checkout, why = clone_for_proposal(clone_url=url)
    if checkout is None:
        return Outcome(repo=repo, detail=f"could not clone `{repo}` to draft its preview: {why}")
    try:
        if as_card:
            return _as_card(project, repo,
                            infer_preview(checkout, name=_short(repo) or project.name))
        base = default_branch(checkout)
        written = _draft_into(checkout, project, repo=repo, accept=accept, answers=answers)
        if isinstance(written, Outcome):
            return written
        proof = prove(project, written.out.files, written.out.block or {}) if prove and \
            written.out.block else ""
        body = pr_body(written.proposal, written.out, project=project.name, repo=repo,
                       proof=proof,
                       comments_kept=written.merged is None or written.merged.comments_kept)
        first, rest = written.paths[0], written.paths[1:]
        result = propose(
            checkout=checkout, manifest_path=first, repo=repo, clone_url=url, base=base,
            forge=forge, project_name=project.name, branch=BRANCH, extra_paths=rest,
            title=f"OpenFactory: a preview of {repo}", body=body,
            message=(f"chore: propose how OpenFactory previews {project.name}\n\n"
                     f"Drafted from the repository's own files and never built or run; a person "
                     f"merges it."))
        return Outcome(ok=result.ok, repo=repo, url=result.url, existed=result.existed,
                       base=base, body=body, questions=written.proposal.questions,
                       detail=result.detail.replace("the manifest", "the preview"))
    finally:
        shutil.rmtree(checkout, ignore_errors=True)


def card_body(proposal: PreviewProposal, repo: str) -> str:
    """The card `--as-card` files: the questions a drafted file could not answer, for the
    factory's own executor to settle like any other card — `validate:` runs, the review reviews,
    a person merges."""
    asked = proposal.questions or ["how does it start, and on which port does it listen?"]
    read = ", ".join(f"`{r}`" for r in proposal.read) or "nothing that says how it runs"
    return "\n".join([
        "## Objective",
        "",
        f"Describe how `{repo}` runs, so a change to it can be previewed from its card "
        f"(ADR-0050): a compose file the factory reads, and the `preview:` block of "
        f"`{namespace.MANIFEST}` that names it.",
        "",
        "## Context",
        "",
        f"`openfactory preview propose` read the repository ({read}) and could not draft it on "
        f"its own. What it needs answered:",
        "",
        *[f"- {q.replace(PROJECT, repo)}" for q in asked],
        "",
        f"Drafted files live under `.openfactory/` (`{DRAFT_COMPOSE}`, "
        f"`.openfactory/preview/<service>.Dockerfile`). A secret's value never goes into a file: "
        f"name it for the operator, who sets it with `openfactory project set-preview`.",
        "",
        "## Acceptance criteria",
        "",
        f"- [ ] `{DRAFT_COMPOSE}` declares every service a person opens, each built from this "
        f"repository or pulled from a published image",
        f"- [ ] `{namespace.MANIFEST}` declares `preview:` with `compose:` naming that file and "
        f"`expose:` naming the port each opened service listens on",
        "- [ ] no secret's value is written into any file",
    ]) + "\n"


def _as_card(project, repo: str, proposal: PreviewProposal) -> Outcome:
    """File the questions as a card on the project's board, instead of a pull request."""
    from openfactory.adapters.tracker.registry import build_tracker
    from openfactory.credentials import deployment_tracker_token, tracker_token_for

    if proposal.case == "declared":
        return Outcome(repo=repo, detail="the manifest already declares `preview:` — edit it in "
                                         "the repository; there is nothing to ask.")
    title = f"Describe how {repo} runs for a preview"
    try:
        tracker = build_tracker(project, token=tracker_token_for(project)
                                or deployment_tracker_token(project))
        ref = tracker.create_ticket(title=title, body=card_body(proposal, repo))
    except Exception as exc:  # noqa: BLE001 — a tracker that refused is an outcome, said
        return Outcome(repo=repo, detail=f"the card was not filed: {str(exc)[:200]}")
    url = ""
    try:
        url = tracker.ticket_url(ref)
    except Exception:  # noqa: BLE001 — a card with no address is still a card
        log.info("the tracker filed %s and could not say its address", ref, exc_info=True)
    return Outcome(ok=True, repo=repo, card=str(ref), url=url, questions=proposal.questions,
                   detail=f"filed {ref} — \"{title}\"; move it to the queue when it should run.")


