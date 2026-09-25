"""Every source the product declares, mounted for the product role — sparsely, and fetched when a
turn mounts it (#268 slice 1; ADR-0052 D14, D16, D18 and D20's bound).

A PRODUCT IS NOT A REPOSITORY. It is a monolith, a monorepo, a front end and its services, and it
declares them as N sources in its context repository's `.openfactory/product.yaml`. The
conversation mounted ONE of them — the registry project's `forge.repo` — so in a multi-repository
product the role could read the other services' concepts and could not open their code to check
them. It could repeat the map and could not look at the territory.

THE BOUNDARY IS `sources:` (ADR-0019 §8, #266 decision 1). A source is mounted because the product
declares it, never because something else names it — the registry project's own repository
included, which `config.resolve_product_link` already refuses to link unless `sources:` lists it.
A repository the product would reach and does not declare is NAMED, with that reason, and never
fetched.

THE FORGE CHOOSES THE HOST. An entry is read for the repository it names (`normalize_repo`), and the
clone is addressed by THIS project's forge (`clone_url_for`). A URL somebody wrote into `sources:`
therefore cannot aim the deployment's credential at a host of their choosing: `https://evil.example
/acme/web` is `acme/web` on the forge the registry authorised.

SPARSE, AND ON DEMAND (#266 decision 11). Each source is a `SparseRepoCache`: a partial clone
(commits and trees, and only the blobs a checkout asks for), checked out through a cone that leaves
out the directories holding nothing but pictures, fonts and archives. Nothing is cloned until a turn
mounts the source; a later turn fetches what moved. The sources are brought up side by side, so a
turn waits for the slowest of them rather than for their sum.

"COULD NOT MOUNT" IS NEVER "NOTHING THERE". A source that is not mounted is kept, with the reason,
and the prompt names it. The reason is one of a few fixed sentences chosen from what git said —
never git's own words, which carry the URL, and a URL can carry a token.

THE MAP IS CHECKED BEFORE IT IS GIVEN (D18). A source's module map is named to the role only after
it was verified against the code mounted for that source this turn — the check the coding agent's
`load_agent_knowledge` makes — and one that no longer matches is named as not given, with why.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

log = logging.getLogger("openfactory.product")

#: How many sources are brought up at once for one turn. Each is one git process talking to one
#: forge; eight keeps a large product's first turn short without opening a connection per service.
PARALLEL = 8

# ── why a source is not mounted: said in the prompt, and nothing else is ───────────────────────

NOT_DECLARED = ("it is not among the product's `sources:` in `.openfactory/product.yaml`, so it "
                "is never mounted")
UNREADABLE_ENTRY = ("`sources:` names it in a form that is not a repository reference, so it is "
                    "never mounted")
NO_SOURCES = ("the product's `.openfactory/product.yaml` could not be read, so no source is "
              "mounted")
NOT_AUTHORISED = "this deployment's credential is not authorised to read it"
NOT_FOUND = ("its forge says it does not exist, or does not let this deployment's credential see "
             "it")
NO_BRANCH = "the branch it is read from does not exist in it"
UNREACHABLE = "its forge could not be reached just now"
NOT_ADDRESSABLE = "this deployment's forge cannot address it"
NOT_CHECKED_OUT = "it could not be checked out"

#: What git says, in order: the first family a message matches decides. Authorisation first,
#: because a refused credential also reads "unable to access" and "not found" on some forges; a
#: missing branch before a missing repository, because git says "Remote branch x not found".
_SAID = (
    (NOT_AUTHORISED, ("authentication failed", "returned error: 401", "returned error: 403",
                      "http 401", "http 403", "invalid username or password",
                      "could not read username", "could not read password", "permission denied",
                      "access denied", "unauthorized", "forbidden")),
    (NO_BRANCH, ("remote branch", "couldn't find remote ref", "invalid reference")),
    (NOT_FOUND, ("repository not found", "not found", "does not exist",
                 "does not appear to be a git repository", "no such file or directory",
                 "tf401019")),
    (UNREACHABLE, ("could not resolve host", "failed to connect", "connection refused",
                   "connection timed out", "operation timed out", "timed out", "network is "
                   "unreachable", "unable to access", "connection reset", "early eof")),
)


def why_not(said: str) -> str:
    """The sentence the prompt says about a source git could not bring up, from what git said."""
    text = (said or "").lower()
    for sentence, words in _SAID:
        if any(w in text for w in words):
            return sentence
    return NOT_CHECKED_OUT


# ── what the product declares ──────────────────────────────────────────────────────────────────

#: A URL's userinfo, which is where a pasted clone URL keeps a token.
_USERINFO = re.compile(r"([a-z][a-z0-9+.-]*://)[^@/\s]+@", re.IGNORECASE)


@dataclass(frozen=True)
class Declared:
    """The product's `sources:`, read.

    `sources` is `(coordinate, spelling)` in the order declared and once each: the coordinate is
    the canonical name everything here is keyed and shown by, the spelling is what the forge is
    asked to clone (`sources:`'s own case, when it is the coordinate and nothing more — a URL, a
    suffix or a query is replaced by the coordinate, so the forge and not the declaration chooses
    the host). `refused` is every entry that names no repository, keyed by what was written with
    any credential taken out. `error` says why the file could not be read, when it could not."""

    sources: tuple[tuple[str, str], ...] = ()
    refused: dict[str, str] = field(default_factory=dict)
    error: str = ""

    @property
    def repos(self) -> list[str]:
        return [coordinate for coordinate, _ in self.sources]


def declared(docs_path) -> Declared:
    """What `.openfactory/product.yaml` in the documentation checkout at `docs_path` declares."""
    from openfactory.product.config import normalize_repo
    from openfactory.product.loader import _read_docs_manifest

    docs, error = _read_docs_manifest(Path(docs_path))
    if docs is None:
        return Declared(error=error or "unreadable")
    seen: set[str] = set()
    out: list[tuple[str, str]] = []
    refused: dict[str, str] = {}
    for entry in docs.sources:
        written = str(entry or "").strip()
        coordinate = normalize_repo(written)
        if not coordinate:
            from openfactory.product.model import scrub_credentials

            refused[scrub_credentials(_USERINFO.sub(r"\1", written)) or "(empty)"] = \
                UNREADABLE_ENTRY
            continue
        if coordinate in seen:
            continue
        seen.add(coordinate)
        # THE SPELLING IS KEPT ONLY WHEN IT IS THE COORDINATE, in the case it was written in. A
        # URL, a `.git`, a query — anything a forge's URL builder could read as more than a name —
        # is replaced by the coordinate, so the forge is asked for exactly that repository.
        plain = written.strip("/")
        out.append((coordinate, plain if plain.lower() == coordinate else coordinate))
    return Declared(sources=tuple(out), refused=refused)


# ── bringing them up ───────────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Checkout:
    """One source brought up for a turn — its cached checkout, or why there is none."""

    path: Path | None = None
    why: str = ""
    left_out: tuple[str, ...] = ()


@dataclass
class Checkouts:
    """Every declared source, brought up: where each is, why each missing one is not, and which
    one is the registry project's own repository (`""` when the product does not declare it)."""

    placed: dict[str, Path] = field(default_factory=dict)
    missing: dict[str, str] = field(default_factory=dict)
    left_out: dict[str, tuple[str, ...]] = field(default_factory=dict)
    own: str = ""
    declared: tuple[str, ...] = ()


def check_out(own_repo: str, found: Declared,
              checkout: Callable[[str, str, bool], Checkout]) -> Checkouts:
    """Every source `found` declares, brought up side by side through `checkout(coordinate,
    spelling, own)` — and nothing else.

    `own_repo` is the registry project's repository. It is brought up when the product declares it,
    like every other source; when it does not, it is named as not declared and never fetched, which
    is the boundary this function exists to hold."""
    from openfactory.product.config import normalize_repo, repo_match

    out = Checkouts(missing=dict(found.refused), declared=tuple(found.repos))
    if found.error:
        if own_repo:
            out.missing[normalize_repo(own_repo) or own_repo] = NO_SOURCES
        return out
    out.own = next((c for c in found.repos if own_repo and repo_match(own_repo, c)), "")
    if own_repo and not out.own:
        out.missing[normalize_repo(own_repo) or own_repo] = NOT_DECLARED
    if not found.sources:
        return out

    def one(source: tuple[str, str]) -> Checkout:
        coordinate, spelling = source
        try:
            return checkout(coordinate, spelling, coordinate == out.own)
        except Exception as exc:  # noqa: BLE001 — one source's trouble never costs the others
            log.warning("product: could not bring up the source %s (%s)", coordinate,
                        type(exc).__name__)
            return Checkout(why=NOT_CHECKED_OUT)

    with ThreadPoolExecutor(max_workers=min(PARALLEL, len(found.sources)),
                            thread_name_prefix="product-source") as pool:
        results = list(pool.map(one, found.sources))
    for (coordinate, _), got in zip(found.sources, results, strict=True):
        if got.path is not None:
            out.placed[coordinate] = got.path
            out.left_out[coordinate] = got.left_out
        else:
            out.missing[coordinate] = got.why or NOT_CHECKED_OUT
    return out


# ── what the prompt says about each ────────────────────────────────────────────────────────────

NO_MAP = "no module map is published for it yet"
MAP_UNREADABLE = "its module map could not be read"
MAP_STALE = ("its module map no longer matches the code mounted for it — the code moved since the "
             "map was drawn — so it is not given")


@dataclass(frozen=True)
class Mount:
    """One declared source as this turn's view holds it, and as the prompt says it.

    Paths are relative to the root the role stands in. `path` is "" when the source is not mounted,
    and `why` says why; `map` is "" when no module map is given for it, and `map_why` says why."""

    repo: str
    path: str = ""
    why: str = ""
    own: bool = False
    left_out: tuple[str, ...] = ()
    map: str = ""
    map_why: str = ""


def bundle_home(docs_root, repo: str) -> Path | None:
    """The folder of `repo`'s knowledge in the context repository (`.okf/repos/<owner>--<name>/`),
    or None.

    Found by the NAME IT WAS PUBLISHED UNDER, which is the spelling the pipeline was handed — the
    registry's `forge.repo` or the onboarding's — and not necessarily the one `sources:` uses: an
    exact folder first, then the same folder in another case, then the same repository written
    with less qualification (a bare Azure name beside its `organisation/project/name`)."""
    from openfactory.knowledge.pipeline import okf_subpath
    from openfactory.product.config import repo_match

    exact = Path(docs_root) / okf_subpath(repo)
    if exact.is_dir():
        return exact
    try:
        folders = sorted(p for p in exact.parent.iterdir() if p.is_dir())
    except OSError:
        return None
    for folder in folders:
        if folder.name.lower() == exact.name.lower():
            return folder
    for folder in folders:
        if repo_match(folder.name.replace("--", "/"), repo):
            return folder
    return None


def module_map(docs_root, repo: str, code: Path) -> tuple[Path | None, str]:
    """`repo`'s module map, CHECKED AGAINST `code` — the tree mounted for it this turn: `(file, "")`
    when it may be read, `(None, why)` when it may not.

    The same gate the coding agent's map passes (`knowledge/staleness.py::is_trustworthy`): every
    file it was drawn from is still there with the same bytes, and every link it holds still
    resolves. A map that fails is not given, because a map that points at code which moved is worse
    than no map — it sends the reader to the wrong place with confidence."""
    from openfactory.knowledge.bundle import MODULES_FILE, read_bundle_dir
    from openfactory.knowledge.staleness import is_trustworthy

    home = bundle_home(docs_root, repo) if docs_root is not None else None
    if home is None or not (home / MODULES_FILE).is_file():
        return None, NO_MAP
    bundle = read_bundle_dir(home)
    if bundle is None:
        return None, MAP_UNREADABLE
    if not is_trustworthy(bundle, code):
        return None, MAP_STALE
    return home / MODULES_FILE, ""


__all__ = ["MAP_STALE", "NOT_AUTHORISED", "NOT_DECLARED", "NOT_FOUND", "NO_MAP", "UNREACHABLE",
           "Checkout", "Checkouts", "Declared", "Mount", "bundle_home", "check_out", "declared",
           "module_map", "why_not"]
