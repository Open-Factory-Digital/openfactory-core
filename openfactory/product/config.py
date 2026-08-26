"""Which documentation repository holds a project's requirements — and who gets to say so.

ADR-0019 §8: the link is declared TWICE and authorized ONCE.

    the source repo   `.openfactory/project.yaml` → `docs_repo:`     a CLAIM
    the docs repo     `.openfactory/product.yaml` → `sources:`       the MEMBERSHIP SET
    the registry      `product: {docs_repo: …}`               the AUTHORIZATION

Each direction answers a question the other cannot. The source→docs pointer means anyone who clones
a service finds the requirements, and a new service joins a product by changing itself rather than a
central file. The docs→sources list gives the product role the COMPLETE membership — you cannot
discover a repository you do not know exists.

And because both sides declare it independently, a disagreement is a DETECTABLE inconsistency
rather than a silently wrong answer. That is the entire point of the redundancy: a one-way pointer
fails quietly, and the failure here is severe — writing requirements into the wrong product's
repository is not a glitch, it is a client isolation breach.

WHY THE REGISTRY IS THE AUTHORITY: anyone with write access to a source repo could otherwise point
the product role at any repository at all by editing one line. So a claim is only ever confirmation,
never redirection — the same shape as ADR-0001 D-2, where a project manifest may TIGHTEN permissions
but never loosen them.

WHEN IT DOES NOT ADD UP, THE MODULE TURNS OFF — it never guesses. A product role running against
the wrong corpus would author confident, well-formatted requirements for the wrong product, and
nobody would see a stack trace. Off, with a message naming the file to fix, is strictly better.
"""

from __future__ import annotations

import re

from pydantic import BaseModel, Field

from openfactory import namespace
from openfactory.contracts.product import ProductConfig, ProductDocs

#: The scheme/userinfo/host prefix of a pasted clone URL, in the two spellings a URL can take:
#: `https://dev.azure.com/…`, `https://client-org@dev.azure.com/…` (what the Azure DevOps UI hands
#: you), `ssh://git@ssh.dev.azure.com/…` — and the scp-style `git@github.com:owner/name.git`.
#:
#: A SCHEME OR A `user@host:` IS REQUIRED, and that is not pedantry. An earlier draft accepted a
#: bare `host/` prefix so it could handle both forms with one branch, and it then read the OWNER of
#: `ClientOrg/client-repo` as a hostname and threw it away — every two-segment GitHub reference
#: silently became its repository name. Kept as a *prefix strip* rather than a whole-string match
#: because what identifies a repository is the PATH, and how many segments that path has is the
#: provider's business, not this pattern's.
_URL_PREFIX_RE = re.compile(
    r"""^(?:
        [a-z][a-z0-9+.-]*://(?:[^/@\s]+@)?(?P<host>[^/:\s]+)[:/]   # scheme://[user@]host/
      | [^/@\s]+@(?P<scp_host>[^/:\s]+):                           # user@host:  (scp-style)
    )""",
    re.IGNORECASE | re.VERBOSE,
)

#: What one segment of a repository coordinate may contain. Deliberately narrow: without it a
#: single segment accepts anything at all, and `git@github.com` — a real typo out of a client's
#: `.openfactory/project.yaml` — would parse as a repository NAMED `git@github.com` and be reported
#: as a
#: membership conflict rather than as the unreadable reference it is. GitHub allows
#: `[A-Za-z0-9._-]`; Azure DevOps allows the same plus spaces, which arrive percent-encoded in the
#: URLs anybody pastes and are rejected as raw whitespace either way.
_SEGMENT_RE = re.compile(r"^[A-Za-z0-9._%-]+$")

def _without_route_segments(segments: list[str], *, from_url: bool) -> list[str]:
    """Drop the path segments that address the API rather than the repository.

    `_git` is the literal Azure Repos puts between the project and the repository name; `v3` is the
    version segment its SSH remotes carry (`git@ssh.dev.azure.com:v3/org/project/repo`). Removing
    them is what makes a pasted URL and the coordinate a human writes in a YAML file the SAME
    string, which is the whole job of this module.

    POSITIONAL, NOT A SET MEMBERSHIP TEST, and that distinction is load-bearing in both directions.
    A blanket "drop any segment called `v3`" turns the perfectly ordinary GitHub repository
    `ClientOrg/v3` into the bare owner `clientorg`, and the bare repository `v3` into nothing at
    all — a silent corruption of a VALID coordinate, which is precisely the class of bug this
    function exists to remove rather than to add.

    So `v3` counts only where a route can put it: leading the path OF A URL. `_git` counts only
    where something follows it, which no repository name can satisfy since it is always last."""
    out = list(segments)
    if from_url and len(out) > 1 and out[0].lower() == "v3":
        out = out[1:]
    return [s for i, s in enumerate(out) if not (s.lower() == "_git" and i < len(out) - 1)]

#: How deep a repository coordinate can legitimately be. GitHub addresses one with two segments
#: (`owner/name`) and Azure DevOps with three (`organization/project/repository`); one segment is
#: the bare repository name, which is how every Azure row in this deployment's registry is actually
#: written — the organisation and project live in the provider's `options`, not in `repo`.
_MAX_SEGMENTS = 3


def normalize_repo(ref: str | None) -> str:
    """A repository coordinate in ONE canonical spelling: lowercased segments joined by `/`.

    ONE TO THREE SEGMENTS, BECAUSE PROVIDERS NEST DIFFERENTLY. This function used to require
    exactly two, and that assumption is GitHub's shape wearing the name of a general one:

        ClientOrg/fx-dsk-context                → clientorg/fx-dsk-context
        client-org/proj/fx-dsk-context          → client-org/proj/fx-dsk-context
        fx-dsk-context                          → fx-dsk-context
        https://dev.azure.com/client-org/proj/… → client-org/proj/fx-dsk-context

    The last three all returned `""` — and `""` is not a harmless "unknown" here. `authorized`
    being empty turns the module OFF for the whole deployment, and a `sources:` list that
    normalises to nothing empties the MEMBERSHIP SET, which is the one check standing between an
    agent and another client's requirements. An unreadable coordinate that reads as an empty set
    passes that check silently, which is the same defect class as an unreadable board reading as an
    empty queue.

    The bare single segment is not a concession: it is the shape the registry actually uses for
    Azure Repos (`forge: {repo: fx-ado, options: {organization: …, project: …}}`), because the
    other two coordinates belong to the provider's options and not to the repository's name.

    "" still means UNUSABLE — nothing, whitespace inside, or more segments than any provider
    addresses a repository with. The caller decides what that means, since "absent" and "malformed"
    are different problems with different messages."""
    text = (ref or "").strip().strip("/")
    if not text:
        return ""
    # a query string or fragment is decoration a browser added; `?path=/x` and `#L4` name a place
    # INSIDE the repository, never a different one
    text = re.split(r"[?#]", text, maxsplit=1)[0].strip().strip("/")
    host = ""
    m = _URL_PREFIX_RE.match(text)
    if m:
        host = (m.group("host") or m.group("scp_host") or "").lower()
        text = text[m.end():]
    text = re.sub(r"\.git$", "", text, flags=re.IGNORECASE).strip("/")
    if not text:
        return ""
    segments = _without_route_segments([s for s in text.split("/") if s], from_url=bool(m))
    if not all(_SEGMENT_RE.match(s) for s in segments):
        return ""
    # THE LEGACY AZURE HOST CARRIES THE ORGANISATION. `https://client-org.visualstudio.com/df/_git/x`
    # is the same repository as `https://dev.azure.com/client-org/df/_git/x`, and Azure DevOps still
    # serves both. Dropping the host would silently turn a three-segment coordinate into a
    # two-segment one — which does not fail, it MISMATCHES, and a mismatch here is reported to a
    # human as a membership inconsistency: the most alarming failure this module has, for a URL
    # somebody copied out of the wrong browser tab.
    if host.endswith(".visualstudio.com"):
        segments = [host.split(".", 1)[0], *segments]
    if not segments or len(segments) > _MAX_SEGMENTS:
        return ""
    if any(s in (".", "..") for s in segments):
        return ""
    return "/".join(s.lower() for s in segments)


#: An exact coordinate match — the same repository, written the same way on both sides.
MATCH_EXACT = "exact"
#: The same repository NAME, where at least one side named nothing else. Not a lesser truth: it is
#: a match made on less evidence, and the caller says so out loud rather than presenting it as an
#: identity it did not establish.
MATCH_NAME = "name"


def repo_match(a: str | None, b: str | None) -> str:
    """`MATCH_EXACT` · `MATCH_NAME` · `""` — do these two references name the same repository, and
    on what evidence?

    WHY THIS IS NOT `==`, AND WHY IT IS NOT A SUFFIX TEST EITHER. Azure Repos coordinates arrive at
    this module in two legitimate spellings on the SAME deployment: the registry names a bare
    `fx-dsk-context` (organisation and project live in the forge's `options`), while a person
    documenting the product in `.openfactory/product.yaml` pastes the URL their browser showed them
    and
    writes `client-org/proj/fx-dsk-context`. Comparing those with `==` reports a membership
    inconsistency about one repository written twice; that is a false alarm, and this module's own
    docstring says a false alarm here is the failure it most wants to avoid.

    So an UNQUALIFIED side is compared on the repository name alone — and only an unqualified one.
    Two fully-qualified coordinates that disagree stay a conflict, which is what keeps the check
    that stops one client's requirements being written into another's doing its job: `one-org/x` and
    `someone-else/x` are not the same repository and must never be reported as one.

    The two outcomes are DISTINGUISHED rather than collapsed into a bool because the caller warns
    on the weaker one. A match made on a bare name is correct on this deployment and would stop
    being correct the day two of its projects host repositories of the same name — telling somebody
    now, while it costs a line of text, is cheaper than telling them then."""
    left, right = normalize_repo(a), normalize_repo(b)
    if not left or not right:
        return ""
    if left == right:
        return MATCH_EXACT
    if "/" in left and "/" in right:
        return ""
    return MATCH_NAME if left.rsplit("/", 1)[-1] == right.rsplit("/", 1)[-1] else ""


class ProductLink(BaseModel):
    """The verdict: may the product module run for this project, and against what.

    Carries a reason whether or not it is active. An inactive module that cannot say WHY is
    indistinguishable from one nobody enabled — which is how a misconfiguration survives."""

    active: bool
    docs_repo: str = ""
    #: `off` (nobody enabled it) · `config` (enabled but unusable) · `conflict` (the two
    #: declarations disagree) · `ok`. Distinguished because they need different humans: `off` is
    #: nothing, `config` is the operator's, `conflict` is whoever edited one of the two files.
    kind: str = "off"
    reason: str = ""
    #: non-fatal observations — the module runs, but something is worth fixing
    warnings: list[str] = Field(default_factory=list)


def _off(kind: str, reason: str) -> ProductLink:
    return ProductLink(active=False, kind=kind, reason=reason)


def resolve_product_link(
    *,
    project,
    manifest_docs_repo: str | None = None,
    docs: ProductDocs | None = None,
    docs_error: str = "",
) -> ProductLink:
    """Reconcile the three declarations into one verdict.

    `manifest_docs_repo` is the source repo's claim (None when it makes none), `docs` the parsed
    `.openfactory/product.yaml` from the documentation repo (None when it could not be read, with
    `docs_error` saying why). Pure: every input is already fetched, so this is exhaustively
    testable — which matters, because it is the function that decides whether an agent may write
    into a client's requirements."""
    cfg: ProductConfig | None = getattr(project, "product", None)
    if cfg is None:
        return _off("off", "the product module is not enabled for this project (no `product:` "
                           "section in its registry entry)")
    if not cfg.enabled:
        return _off("off", "the product module is configured but switched off (`enabled: false`)")

    authorized = normalize_repo(cfg.docs_repo)
    if not authorized:
        return _off("config", f"the registry's `product.docs_repo` is missing or unreadable "
                              f"({cfg.docs_repo!r}); expected a repository reference — "
                              f"`owner/name` on GitHub, `organization/project/repository` or the "
                              f"bare repository name on Azure Repos, or any clone URL of one")

    warnings: list[str] = []
    # THE FILE THESE SENTENCES NAME IS THE ONE THE LOADER READ — the project's own `manifest_path`
    # when it declared one, the platform's default otherwise. A remedy naming a path nothing
    # reads sends the person to create a file the platform will never open.
    manifest_rel = getattr(project, "manifest_path", None) or namespace.MANIFEST

    # 1. the source repo's CLAIM may confirm, never redirect
    claimed = normalize_repo(manifest_docs_repo)
    if manifest_docs_repo and not claimed:
        warnings.append(
            f"the source repo's `{manifest_rel}` has an unreadable `docs_repo` "
            f"({manifest_docs_repo!r}); expected a repository reference or a clone URL. "
            f"Ignored — the registry authorizes."
        )
    elif claimed and not (how := repo_match(claimed, authorized)):
        return _off(
            "conflict",
            f"the source repo claims its documentation lives in {claimed!r}, but this deployment "
            f"authorizes {authorized!r}. Refusing to follow the claim: anyone with write access to "
            f"a source repo could otherwise redirect where its requirements are written. Fix "
            f"`docs_repo` in the source repo's `{manifest_rel}`, or the registry entry.",
        )
    elif claimed and how == MATCH_NAME:
        warnings.append(
            f"the source repo claims {claimed!r} and this deployment authorizes {authorized!r}; "
            f"they were matched on the repository NAME alone, because one of the two names nothing "
            f"else. That is correct today and stops being correct the day two of this "
            f"deployment's projects host a repository of the same name — write both the same way."
        )
    elif not claimed:
        warnings.append(
            f"the source repo does not declare `docs_repo: {authorized}` in its "
            f"`{manifest_rel}`. The module still runs, but anyone cloning that repo has no way "
            f"to find its requirements."
        )

    # 2. the documentation repo must be readable — its membership set is not optional
    if docs is None:
        return _off("config", f"could not read `.openfactory/product.yaml` in {authorized}"
                              + (f": {docs_error}" if docs_error else ""))

    # 3. …and must describe THIS product
    if (docs.product or "").strip().lower() != str(project.name).strip().lower():
        return _off(
            "conflict",
            f"{authorized} holds requirements for product {docs.product!r}, but this project is "
            f"{project.name!r}. Refusing: writing one client's requirements into another's "
            f"repository is an isolation breach, not a typo to work around.",
        )

    # 4. …and must count this source repo as a member. The DETECTABLE inconsistency the two-way
    #    declaration exists to produce: authorized to use the corpus, but not listed as part of it.
    declared_source = _source_repo(project)
    source = normalize_repo(declared_source)
    members = {normalize_repo(s) for s in docs.sources} - {""}
    unreadable = [s for s in docs.sources if not normalize_repo(s)]
    # A MEMBER THIS CANNOT READ IS NOT A MEMBER THIS CAN VOUCH FOR. It used to be dropped by
    # `- {""}` and nothing said so, which is the shape that made this whole card matter: a
    # `sources:` list of Azure coordinates normalised to an empty set, the membership check
    # then compared against nothing, and "not listed" and "list unreadable" produced the same
    # silence. A dropped member is invisible to the product role for ever.
    #
    # ONE SENTENCE, TWO DESTINATIONS, and the second is the one that actually costs. `_off`
    # carries NO warnings, so on the refusal below — which is precisely where every member being
    # unreadable lands — the operator was told "it lists nothing" about a `sources:` block they
    # can see listing things, and would add the entry a second time in the same spelling that
    # failed. Warning on the surviving path and going silent on the refusing one is the same
    # collapse of "not listed" into "list unreadable", one branch further down.
    dropped = (
        f"`sources:` in {authorized}'s `.openfactory/product.yaml` has {len(unreadable)} "
        f"entry(ies) "
        f"this cannot read ({', '.join(repr(s) for s in unreadable[:3])}); they are NOT part "
        f"of the membership set, so anything living in them is invisible to the product role."
    ) if unreadable else ""
    if dropped:
        warnings.append(dropped)
    if not source and declared_source:
        # REFUSED, NOT WARNED. An unreadable source coordinate makes the membership check
        # vacuously true — `source` is falsy, so the `not in members` branch never runs and the
        # one check standing between an agent and another client's requirements reads as passed.
        # Absence must never read as compliance; the module goes off and names the field to fix.
        return _off(
            "config",
            f"this project's code repository is declared as {declared_source!r}, which is not a "
            f"repository reference this can read. Refusing rather than skipping the membership "
            f"check: an unreadable source coordinate makes that check pass without ever running, "
            f"and it is the check that stops one client's requirements being written from "
            f"another's code. Fix `forge.repo` (or `tracker.repo`) in this project's registry "
            f"entry.",
        )
    if source:
        hits = {m: how for m in sorted(members) if (how := repo_match(source, m))}
        if not hits:
            return _off(
                "conflict",
                f"{source} is not listed in `sources:` of {authorized}'s "
                f"`.openfactory/product.yaml` "
                f"(it lists {sorted(members) or 'nothing'}). "
                f"{dropped + ' ' if dropped else ''}"
                f"The product role needs the COMPLETE set of source repos to reason about the "
                f"product, and one missing from it would be invisible. Add it there.",
            )
        if MATCH_EXACT not in hits.values():
            warnings.append(
                f"{source} was matched to {sorted(hits)} in `sources:` on the repository NAME "
                f"alone, because one side names no organisation or project. Write both the same "
                f"way — on a deployment with two repositories of one name this would match the "
                f"wrong one, and the symptom would be a product role reasoning over the wrong code."
            )
    else:
        warnings.append("this project declares no source repo, so membership could not be checked")

    return ProductLink(active=True, docs_repo=authorized, kind="ok",
                       reason="registry, source repo and documentation repo agree",
                       warnings=warnings)


def _source_repo(project) -> str:
    """The project's code repository — the forge's, falling back to the tracker's (a project may
    track tickets in one place and hold code in another; membership is about CODE)."""
    for axis in ("forge", "tracker"):
        ref = getattr(project, axis, None)
        repo = getattr(ref, "repo", None) if ref is not None else None
        if repo:
            return str(repo)
    return ""
