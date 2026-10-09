"""`openfactory explain` — why an agent got this instruction, answered by the job's own code (#81).

THE QUESTION A DEVELOPER ASKS FIRST, and until this command the answer was a reading exercise:
`context.py` to see which tiers exist, the profile to see what it waives, the manifest to see what
the project names, and a guess about which of them reached the prompt. A guess is the wrong tool
for the one surface that is meant to change often.

THE CASCADE IT PRINTS IS THE REAL ONE, not the chain the issue imagined
(`org_defaults/roles/*.md` → deployment overlay → the project's profile). What exists today:

    the role prompt      ONE layer — the package's `org_defaults/roles/<role>.md`, or an add-on's
                         own text for a role the package does not ship (`roles.role_prompt`). The
                         deployment overlay ADR-0044 names does not exist yet.
    the guidelines       the framework's `org_defaults/*.md`, waived, replaced or extended by the
                         project's profile; then the operator's `$OPENFACTORY_GUIDELINES_DIR`;
                         then the project's own `docs.guidelines` and `components.*.guidelines`.
                         A profile acts on these and on nothing else.
    the constraints      `docs.constraints`, in full, always.
    the index            `docs.architecture`, titles only, read on demand.

NOTHING HERE DECIDES ANYTHING. The rows are `context.Traced` entries written by `build_context`
itself, from the branch that kept, waived, replaced or refused each file, so this cannot say one
thing while the job does another. It is the job's code run on a blank card with a trace attached.

AND IT WRITES NOTHING. No knowledge bundle is read (that can fetch), no harness, forge or network
is asked anything, no registry or card is touched. The ticket brief itself is never printed: its
fence is drawn with a random marker (`base._marker_nonce`), so no two runs would print the same
text, and the card is each ticket's own — the blocks every ticket of this project carries are the
explanation.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import openfactory
from openfactory import namespace
from openfactory.techlead.voice import say as _say

#: The languages the labels and refusals are written in.
LANGUAGES = ("en", "pt-BR")

#: Where the package's own files are shown from: `openfactory/org_defaults/...`, the same path in
#: this repository and in an installed wheel.
_PACKAGE_PARENT = Path(openfactory.__file__).resolve().parent.parent

#: EVERY LABEL AND EVERY REFUSAL, in both languages. Manifest keys (`docs.guidelines`), file names
#: and the profile chain are identifiers and are never translated.
SAY: dict[str, dict[str, str]] = {
    # ── refusals: one sentence each, and the command exits 1 ──────────────────────────────────
    "refuse.language": {
        "en": "`--language` is en or pt-BR, not {asked!r}.",
        "pt-BR": "`--language` é en ou pt-BR, não {asked!r}."},
    "refuse.url": {
        "en": "{target} is an address, and explain reads a checkout on this machine — clone it "
              "and pass the directory.",
        "pt-BR": "{target} é um endereço, e o explain lê um checkout nesta máquina — clone o "
                 "repositório e passe o diretório."},
    "refuse.no_dir": {
        "en": "{target} is not a directory on this machine, so there is no checkout to read.",
        "pt-BR": "{target} não é um diretório nesta máquina, então não há checkout para ler."},
    "refuse.no_manifest": {
        "en": "{target} has no manifest at {manifest}, so nothing tells the platform what this "
              "project is — `openfactory env read {target}` proposes one.",
        "pt-BR": "{target} não tem manifesto em {manifest}, então nada diz à plataforma o que é "
                 "este projeto — `openfactory env read {target}` propõe um."},
    "refuse.retired": {
        "en": "{target} keeps its manifest under {retired}/, a name this platform no longer "
              "reads — rename the directory to {current}/.",
        "pt-BR": "{target} guarda o manifesto em {retired}/, um nome que a plataforma não lê "
                 "mais — renomeie o diretório para {current}/."},
    "refuse.invalid_manifest": {
        "en": "The manifest at {manifest} does not load: {why}.",
        "pt-BR": "O manifesto em {manifest} não carrega: {why}."},
    "refuse.no_profile": {
        "en": "The manifest declares `profile: {name}` and no such profile exists — looked in "
              "{looked}.",
        "pt-BR": "O manifesto declara `profile: {name}` e esse perfil não existe — procurei em "
                 "{looked}."},
    "refuse.bad_profile": {
        "en": "The profile `{name}` does not resolve, and a job would hold on it: {why}",
        "pt-BR": "O perfil `{name}` não resolve, e um job pararia nele: {why}"},
    "or": {"en": " or ", "pt-BR": " ou "},

    # ── the header ────────────────────────────────────────────────────────────────────────────
    "profile": {"en": "profile", "pt-BR": "perfil"},
    "profile.none": {
        "en": "none declared — every framework file is kept",
        "pt-BR": "nenhum declarado — todo arquivo do framework é mantido"},
    "profile.project": {"en": "the project's own", "pt-BR": "do próprio projeto"},
    "profile.shipped": {"en": "shipped with the package", "pt-BR": "vem com o pacote"},
    "operator": {"en": "operator", "pt-BR": "operador"},
    "intro": {
        "en": "What a planner or executor pass is handed, in order (the card is each ticket's "
              "own):",
        "pt-BR": "O que um passo de planner ou executor recebe, em ordem (o cartão é de cada "
                 "ticket):"},

    # ── the layers ────────────────────────────────────────────────────────────────────────────
    "layer.role": {"en": "role prompt", "pt-BR": "prompt do papel"},
    "layer.framework": {"en": "framework", "pt-BR": "framework"},
    "layer.profile": {"en": "profile", "pt-BR": "perfil"},
    "layer.operator": {"en": "operator", "pt-BR": "operador"},
    "layer.index": {"en": "index", "pt-BR": "índice"},
    "layer.knowledge": {"en": "knowledge map", "pt-BR": "mapa do código"},

    # ── what became of each ───────────────────────────────────────────────────────────────────
    "role.shipped": {
        "en": "{path} — the package's own; nothing overrides it",
        "pt-BR": "{path} — o do pacote; nada o sobrepõe"},
    "role.add-on": {
        "en": "the add-on's own prompt (its RoleSpec), one layer",
        "pt-BR": "o prompt do próprio add-on (seu RoleSpec), uma camada só"},
    "role.missing": {
        "en": "missing — {path} ships with the package, so the installation is incomplete",
        "pt-BR": "ausente — {path} vem com o pacote, então a instalação está incompleta"},
    "kept": {"en": "kept", "pt-BR": "mantido"},
    "kept.unreplaced": {
        "en": "kept — the profile replaces it with {detail}, which is not in the checkout",
        "pt-BR": "mantido — o perfil o substitui por {detail}, que não está no checkout"},
    "kept.extend": {
        "en": "added by the profile (extend)",
        "pt-BR": "acrescentado pelo perfil (extend)"},
    "kept.constraint": {"en": "inlined in full", "pt-BR": "incluído inteiro"},
    "waived": {"en": "waived by {detail}", "pt-BR": "dispensado por {detail}"},
    "replaced": {"en": "replaced by {detail}", "pt-BR": "substituído por {detail}"},
    "refused": {"en": "refused — {detail}", "pt-BR": "recusado — {detail}"},
    "missing": {
        "en": "missing — no such file in the checkout",
        "pt-BR": "ausente — esse arquivo não existe no checkout"},
    "missing.glob": {
        "en": "matched no .md files — the agent runs without them",
        "pt-BR": "não encontrou nenhum .md — o agente roda sem eles"},
    "missing.name": {
        "en": "named by the profile's `{detail}:` and no framework or operator guideline has "
              "that name — the line changes nothing",
        "pt-BR": "citado no `{detail}:` do perfil e nenhuma diretriz do framework ou do "
                 "operador tem esse nome — a linha não muda nada"},
    "missing.dir": {
        "en": "no such directory — every job runs without the operator's guidelines",
        "pt-BR": "esse diretório não existe — todo job roda sem as diretrizes do operador"},
    "empty": {
        "en": "holds no .md guidelines — every job runs without the operator's guidelines",
        "pt-BR": "não tem nenhuma diretriz .md — todo job roda sem as diretrizes do operador"},
    "unreachable": {
        "en": "{detail} document(s), indexed only by a box that can open the directory — "
              "explain runs in none, so they are not in the index below",
        "pt-BR": "{detail} documento(s), indexados só por uma caixa que consegue abrir o "
                 "diretório — o explain não roda em nenhuma, então não estão no índice abaixo"},
    "knowledge": {
        "en": "on — added per job when a fresh bundle describes its checkout; not read here",
        "pt-BR": "ligado — entra por job quando um pacote atualizado descreve o checkout; não é "
                 "lido aqui"},
    "log": {
        "en": "The job's log says, on every pass:",
        "pt-BR": "O log do job diz, a cada passo:"},

    # ── why a path was refused (`context.resolve_inside`'s reasons) ───────────────────────────
    "why.outside the repository": {"en": "outside the repository",
                                   "pt-BR": "fora do repositório"},
    "why.the repository itself, not a file": {"en": "the repository itself, not a file",
                                              "pt-BR": "o próprio repositório, não um arquivo"},
    "why.could not be resolved": {"en": "could not be resolved",
                                  "pt-BR": "não pôde ser resolvido"},
}


class Refused(Exception):
    """One sentence, already in the reader's language. The command prints it and exits 1."""


def _shown(path: Path) -> str:
    """A package file as `openfactory/org_defaults/...`; anything else as it was given."""
    try:
        return path.resolve().relative_to(_PACKAGE_PARENT).as_posix()
    except (OSError, ValueError):
        return str(path)


def _is_an_address(target: str) -> bool:
    """The same reading `env apply` and the doctor give a registered `repo_path`."""
    return "://" in target or target.startswith("git@")


@contextmanager
def _the_jobs_log() -> Iterator[list[str]]:
    """Every warning the job's own code logs while it runs here — captured and printed once, under
    its own heading, instead of interleaved with the table on stderr."""
    said: list[str] = []

    class _Keep(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            said.append(record.getMessage())

    logger = logging.getLogger("openfactory")
    keep = _Keep(level=logging.WARNING)
    propagated = logger.propagate
    logger.addHandler(keep)
    logger.propagate = False
    try:
        yield said
    finally:
        logger.removeHandler(keep)
        logger.propagate = propagated


def _manifest(checkout: Path, target: str, language: str):
    import yaml
    from pydantic import ValidationError

    from openfactory.contracts import Manifest

    try:
        manifest_file = namespace.resolve(checkout, namespace.MANIFEST, project=checkout.name)
    except namespace.RetiredNamespace:
        raise Refused(_say(SAY, "refuse.retired", language, target=target,
                           retired=namespace.RETIRED_DIR, current=namespace.DIR)) from None
    if not manifest_file.is_file():
        raise Refused(_say(SAY, "refuse.no_manifest", language, target=target,
                           manifest=namespace.MANIFEST))
    shown = (Path(target) / namespace.MANIFEST).as_posix()
    try:
        data = yaml.safe_load(manifest_file.read_text()) or {}
        if not isinstance(data, dict):
            raise ValueError(f"a YAML mapping, not {type(data).__name__}")
        # VALIDATED WITHOUT THE REGISTRY'S CONTEXT, as every `Manifest(...)` outside
        # `loader.load_manifest` is: a path is not a registered project, and the one rule that
        # needs the registry (`CI_THAT_READS_NO_DEPLOY`) is about deploys, not about the prompt
        return Manifest.model_validate(data)
    except ValidationError as exc:
        first = exc.errors()[0]
        where = ".".join(str(part) for part in first.get("loc", ())) or "manifest"
        why = f"{where}: {first.get('msg', '')}".rstrip(". ")
    except (ValueError, OSError, yaml.YAMLError) as exc:
        why = " ".join(str(exc).split()).rstrip(". ")
    raise Refused(_say(SAY, "refuse.invalid_manifest", language, manifest=shown, why=why))


def _profile(manifest, checkout: Path, language: str):
    from openfactory.policy.profiles import ProfileError, resolve_profile

    try:
        return resolve_profile(manifest.profile, project_dir=checkout)
    except ProfileError as exc:
        looked = getattr(exc, "looked", ())
        if looked:
            joined = _say(SAY, "or", language).join(_shown(Path(p)) for p in looked)
            name = getattr(exc, "name", "") or manifest.profile
            raise Refused(_say(SAY, "refuse.no_profile", language, name=name,
                               looked=joined)) from None
        raise Refused(_say(SAY, "refuse.bad_profile", language, name=manifest.profile,
                           why=" ".join(str(exc).split()))) from None


def _header(profile, checkout: Path, language: str) -> list[str]:
    """The profile the project declares — its chain, and where each link was read — and the
    operator's directory when one is set."""
    from openfactory.orchestrator import operator_guidelines
    from openfactory.policy.profiles import FRAMEWORK_PROFILES_DIR, _locate

    labels = [_say(SAY, "profile", language), _say(SAY, "operator", language)]
    width = max(len(label) for label in labels)
    if profile is None:
        lines = [f"  {labels[0].ljust(width)}  {_say(SAY, 'profile.none', language)}"]
    else:
        lines = [f"  {labels[0].ljust(width)}  {' → '.join(profile.names)}"]
        links = [(name, _locate(name, checkout)) for name in profile.names]
        named = max(len(name) for name, _ in links)
        for name, where in links:
            if where is None:
                continue
            if where.parent == FRAMEWORK_PROFILES_DIR:
                source = f"{_shown(where)} — {_say(SAY, 'profile.shipped', language)}"
            else:
                source = (f"{where.relative_to(checkout).as_posix()} — "
                          f"{_say(SAY, 'profile.project', language)}")
            lines.append(f"  {''.ljust(width)}    {name.ljust(named)}  {source}")
    directory = operator_guidelines.configured_dir()
    if directory is not None:
        lines.append(f"  {labels[1].ljust(width)}  {operator_guidelines.ENV_VAR}={directory}")
    return lines


def _fate(t, language: str) -> str:
    from openfactory.orchestrator import context as ctx

    if t.fate == ctx.KEPT:
        if t.layer == "docs.constraints":
            return _say(SAY, "kept.constraint", language)
        if t.layer == ctx.PROFILE:
            return _say(SAY, "kept.extend", language)
        if t.detail:
            return _say(SAY, "kept.unreplaced", language, detail=t.detail)
        return _say(SAY, "kept", language)
    if t.fate == ctx.REFUSED:
        return _say(SAY, "refused", language,
                    detail=_say(SAY, f"why.{t.detail}", language).removeprefix("why."))
    if t.fate == ctx.MISSING:
        if t.layer in ("docs.constraints", "docs.architecture"):
            return _say(SAY, "missing.glob", language)
        if t.layer == ctx.OPERATOR:
            return _say(SAY, "missing.dir", language)
        if t.layer == ctx.PROFILE and t.detail:
            return _say(SAY, "missing.name", language, detail=t.detail)
        return _say(SAY, "missing", language)
    return _say(SAY, t.fate, language, detail=t.detail)


def _layer(t, language: str) -> str:
    from openfactory.orchestrator import context as ctx

    if t.layer in (ctx.FRAMEWORK, ctx.PROFILE, ctx.OPERATOR):
        return _say(SAY, f"layer.{t.layer}", language)
    return t.layer  # a manifest key, which is an identifier


def explain(target: str, *, language: str = "en", full: bool = False) -> str:
    """The blocks a planner or executor pass of the project at `target` is handed, one line each,
    in the order the job inlines them — or `Refused`, one sentence, in `language`.

    `full` prints each block's text under its line, exactly as the prompt carries it."""
    from openfactory.adapters.agent import roles
    from openfactory.orchestrator import context as ctx

    if language not in LANGUAGES:
        raise Refused(_say(SAY, "refuse.language", "en", asked=language))
    if _is_an_address(target):
        raise Refused(_say(SAY, "refuse.url", language, target=target))
    checkout = Path(target).expanduser()
    if not checkout.is_dir():
        raise Refused(_say(SAY, "refuse.no_dir", language, target=target))

    with _the_jobs_log() as said:
        manifest = _manifest(checkout, target, language)
        profile = _profile(manifest, checkout, language)
        trace: list[ctx.Traced] = []
        context = ctx.build_context(manifest, checkout, ctx._BLANK_CARD, knowledge_map="",
                                    profile=profile, trace=trace)

    # ── the rows: (layer, name, fate, text) ──────────────────────────────────────────────────
    rows: list[tuple[str, str, str, str | None]] = []
    for role in ctx._PASSES_THAT_INLINE_THE_DOCUMENTS:
        kind, path = roles.role_prompt_source(role)
        fate = _say(SAY, f"role.{kind}", language, path=_shown(path) if path else "")
        rows.append((_say(SAY, "layer.role", language), role, fate,
                     roles.role_prompt(role) if kind != roles.NOWHERE else None))
    for t in trace:
        rows.append((_layer(t, language), t.name, _fate(t, language), t.text))
    for line in context.doc_index.splitlines():
        name, _, summary = line.partition(" — ")
        rows.append((_say(SAY, "layer.index", language), name, summary, None))
    if manifest.knowledge_map:
        rows.append((_say(SAY, "layer.knowledge", language), "", _say(SAY, "knowledge", language),
                     None))

    out = [f"openfactory explain · {target}", "", *_header(profile, checkout, language), "",
           _say(SAY, "intro", language), ""]

    width_layer = max(len(layer) for layer, _, _, _ in rows)
    width_name = min(max(len(name) for _, name, _, _ in rows), 40)
    for layer, name, fate, text in rows:
        out.append(f"  {layer.ljust(width_layer)}  {name.ljust(width_name)}  {fate}".rstrip())
        if full and text:
            out += [("      " + line).rstrip() for line in text.rstrip("\n").splitlines()]
            out.append("")

    if said:
        out += ["", _say(SAY, "log", language)]
        out += [f"  {' '.join(line.split())}" for line in said]
    return "\n".join(out) + "\n"
