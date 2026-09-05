"""The BACKFILL: the context an AI needs, reverse-engineered from a legacy codebase.

The product owner, reframing card #99 the day after opening it:

    *"this stage is, in practice, a REVERSE ENGINEERING job for OpenFactory: producing the
    documentation that supports the product role, and so on. It is the REAL CREATION OF THE
    CONTEXT THE AI WILL NEED."*

TWO KNOWLEDGE PRODUCTS, AND THE PLATFORM SHIPPED ONE
----------------------------------------------------
`docs/knowledge-layer.md` already draws the line; this module lives on the other side of it.

    the OKF bundle   STRUCTURAL. Where things are. DERIVED, deterministic, regenerated on every
                     merge. `knowledge/generator.py:115` says of itself *"Never an LLM, never
                     invented"* and that is CORRECT: an artefact that rewrites itself on every
                     merge must not hallucinate, because nobody re-reads it.
    the context      SEMANTIC. What the system does, its vocabulary, its entities, its
                     invariants, why decisions were made. AUTHORED. Reverse-engineered ONCE,
                     corrected by the client's own developers, then maintained by hand.

*"Never an LLM"* is right for the first and wrong for the second, and this module does NOT
loosen the first to get the second — two artefacts, two contracts. `survey()` below is as
deterministic as the bundle and shares its walker; `propose_context()` is the authored half and
it is the only place a model is involved.

THE MEASUREMENT THAT MAKES THE GAP REAL, run on a three-module Python monorepo (`py-mono`):

    modules=3  degraded_purpose=3
      'functions'      -> 'functions'
      'services.api'   -> 'api'
      'services.worker'-> 'worker'

Three modules, three purposes, and every one of them is the folder's own name handed back. That
is the deterministic rule working exactly as designed and producing nothing, because the rule can
only quote what somebody wrote and nobody wrote anything. A legacy repository is that repository
at scale. `RepoSurvey.degraded_purposes` measures it per repo so the gap is a number in the room
rather than an argument.

THE DIFFERENCE BETWEEN INVENTING AND PROPOSING IS THE PERSON PRESENT — plus one mechanism
------------------------------------------------------------------------------------------
"A human corrects it in the room" is a process promise, and this codebase's own history says a
promise no code enforces is a promise that survives exactly until the first busy afternoon. So
the room is backed by a mechanism: **every claim the model makes is checked against the
filesystem before it is allowed to be a sentence.**

    * a citation naming a file that does not exist         → the claim is DEMOTED to a question
    * a citation naming a line past the end of that file   → the same
    * a claim that ends with no surviving citation         → the same

`ContextProposal.demoted` lists every one of them with the citation that failed, so a reader sees
what the model believed AND why it was not printed as fact. The three tiers of `infer.py` say the
same thing about a manifest field; this says it about a sentence.

WHAT THIS MODULE MAY TOUCH
--------------------------
`survey()` reads files, runs nothing, opens no socket, writes nothing, spends no tokens.
`propose_context()` adds exactly one read-only agent pass and still writes nothing.
`write_documents()` is the only function here that can create a file, it refuses without explicit
`consent=True`, and it NEVER overwrites: a path that already exists is skipped and reported. The
context repository belongs to the client (`product/onboard.py`'s rule, same reason).

None = could not read. [] / {} = read, and nothing there. Held throughout, because it is this
codebase's most expensive defect class and this module's whole job is to say what a repository
does and does not contain.

WHAT NOTHING REACHES YET, said out loud rather than left to be discovered
-------------------------------------------------------------------------
There is no CLI verb and no `actions/catalog.py` row for this module. `openfactory env read` reaches
`infer` through `catalog._entry_point` (`catalog.py:1174`); the equivalent for this module — an
`env context` verb, and a `CATALOG` row that runs the agent pass where a harness actually exists
— is NOT built, and until it is, this capability does not exist for a user. It is named here
because "a capability nothing reaches does not exist" has cost this repository ~21 shipped
occurrences, and a docstring that stays quiet about it is how the twenty-second happens.
"""

from __future__ import annotations

import json
import logging
import os
import re
from collections.abc import Callable
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

# The OKF bundle is the structural half and this module consumes it rather than re-deriving it:
# one walker, one pruning rule, one notion of what a module is. `_walk_files` and `_humanize` are
# private, and importing them anyway is deliberate — `infer.py` already borrows `_walk_files` for
# the same reason. A second copy of either would drift, and the first symptom of the drift is a
# survey that disagrees with the map the coding agent is given on the very next ticket.
from openfactory.adapters.agent.base import final_text, json_envelope
from openfactory.adapters.agent.roles import DEFAULT_LANGUAGE, can_judge, language_directive
from openfactory.knowledge.contracts import Module, UnreadExtension
from openfactory.knowledge.generator import (
    _SOURCE_SUFFIXES,
    _humanize,
    _walk_files,
    build_module_map,
    ignored_by_git,
    survey_extensions,
)
from openfactory.onboarding.history import RepoHistory, change_surface
from openfactory.onboarding.infer import (
    Evidence,
    ManifestProposal,
    StackSighting,
    _find_line,
    _line_of,
    _load_yaml,
    _read,
)
from openfactory.onboarding.infer import (
    infer as infer_manifest,
)
from openfactory.onboarding.questions import (
    BLIND_MODULES,
    DROPPED_TERMS,
    NO_ENTRY_POINTS,
    UNREAD_CODE,
    UNREADABLE_DIRS,
    UNTESTED_MODULES,
    SurveyQuestion,
)

log = logging.getLogger("openfactory.onboarding.context")


# ---------------------------------------------------------------------------------------------
# What a repository is made of, read deterministically
# ---------------------------------------------------------------------------------------------

#: Extensions whose NAME is worth reading even when no parser here understands their CONTENT.
#: This is deliberately much wider than the bundle's four families: reading a file name requires
#: no parser at all, so on a Java, Go or Ruby legacy repository — where `build_module_map` returns
#: an empty map and honestly says so — the domain vocabulary in `PedidoRepository.java` is still
#: legible. The module map answers "where is the code"; this answers "what words does this
#: business use", and the second survives a stack the first has never been taught.
_CODE_SUFFIXES = frozenset({
    ".py", ".pyi", ".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".vue", ".svelte",
    ".cs", ".vb", ".fs", ".java", ".kt", ".kts", ".scala", ".groovy", ".go", ".rb", ".php",
    ".rs", ".swift", ".m", ".mm", ".c", ".h", ".cpp", ".hpp", ".cc", ".hh", ".sql", ".pas",
    ".pl", ".pm", ".ex", ".exs", ".erl", ".dart", ".lua", ".r", ".jl", ".clj", ".cbl", ".cob",
    ".csproj", ".fsproj", ".vbproj",
})

#: Extensions that are documentation, configuration or an asset — present in every repository and
#: never the reason a stack is invisible. Anything NOT here and not in `_CODE_SUFFIXES` is
#: reported as code this pass could not read, which is the safe direction: over-reporting costs a
#: line in a table, under-reporting hides an entire subsystem.
_INERT_SUFFIXES = frozenset({
    "", ".md", ".markdown", ".rst", ".txt", ".adoc", ".json", ".yaml", ".yml", ".toml", ".ini",
    ".cfg", ".conf", ".properties", ".lock", ".xml", ".xsd", ".resx", ".html", ".htm", ".css",
    ".scss", ".sass", ".less", ".png", ".jpg", ".jpeg", ".gif", ".svg", ".ico", ".webp", ".bmp",
    ".pdf", ".csv", ".tsv", ".xlsx", ".docx", ".zip", ".gz", ".tar", ".7z", ".woff", ".woff2",
    ".ttf", ".eot", ".otf", ".map", ".snap", ".log", ".example", ".sample", ".tmpl", ".dll",
    ".exe", ".pdb", ".so", ".dylib", ".bin", ".cache", ".editorconfig", ".gitignore",
    ".gitattributes", ".gitkeep", ".dockerignore", ".npmrc", ".nvmrc", ".env",
    # MEASURED, not imagined: every one of these showed up as "probably code" on this
    # repository's own first run — a private key, a terraform state file and its `.backup`, an
    # event log. None of them is a stack, and a report where `.sh` and `.tf` sit in a list of
    # twelve is a report nobody reads to the end.
    ".pem", ".crt", ".cer", ".key", ".p12", ".pfx", ".der", ".jsonl", ".ndjson", ".tfstate",
    ".backup", ".bak", ".orig", ".rej", ".pyc", ".pyo", ".class", ".jar", ".nupkg", ".min",
})

#: Directory names whose contents are tests, matched on any path segment. `testing` is
#: deliberately ABSENT: this very repository has `openfactory/testing/`, which is test *machinery*
#: shipped as product code, and counting it as tests would report the module that provides the
#: fakes as if it were covered by them.
_TEST_DIRS = frozenset({"test", "tests", "spec", "specs", "__tests__", "unittest", "unittests"})

#: A stem that names a test. Case matters on the .NET form: `Tests?$` matches `AdmissaoTests` and
#: not `Latest` or `Contest`, which a case-insensitive pattern would swallow whole.
_TEST_PREFIX = re.compile(r"^[Tt]est[_.-]")
_TEST_SUFFIX = re.compile(r"([_.-](?:test|tests|spec|specs)|Tests?|Specs?)$")

#: One identifier split into words: `AdmissaoService` → admissao, service; `order_created` →
#: order, created; `HTTPError` → http, error (the acronym branch is what keeps `HTTP` from
#: becoming `h`, `t`, `t`, `p`).
_WORD = re.compile(r"[A-Z]+(?![a-z])|[A-Z][a-z]+|[a-z]+|[0-9]+")

#: Words that name PLUMBING in every domain, so they say nothing about this client's business.
#: Deliberately TIGHT, and the bias is documented because the two mistakes are not symmetric: a
#: technical word left in the glossary is a five-second correction in the room, and a domain word
#: silently removed is invisible — nobody misses a term they never saw. Anything a reader would
#: have to think about (`task`, `order`, `account`, `job`) is NOT here.
_TERM_STOPWORDS = frozenset({
    "abstract", "adapter", "adapters", "async", "await", "base", "bool", "builder", "class",
    "common", "config", "configuration", "const", "controller", "controllers", "core", "data",
    "default", "delete", "dto", "enum", "error", "errors", "exception", "exceptions", "factory",
    "func", "function", "functions", "generated", "getter", "handler", "handlers", "helper",
    "helpers", "http", "https", "impl", "implementation", "index", "info", "init", "int",
    "interface", "internal", "json", "lib", "list", "main", "manager", "middleware", "mock",
    "mocks", "model", "models", "module", "modules", "null", "object", "options", "package",
    "param", "params", "partial", "private", "provider", "providers", "public", "repository",
    "repositories", "request", "response", "result", "results", "return", "schema", "self",
    "service", "services", "setter", "settings", "setup", "shared", "spec", "specs", "static",
    "string", "struct", "stub", "temp", "test", "tests", "tmp", "type", "types", "util", "utils",
    "value", "values", "void", "xml", "yaml",
    # English function words. They arrive through SYMBOL splitting — `github_app_token_from_env`
    # contributes `from` — and they were the second and fourth entries of this repository's own
    # first term list, above `ticket` and `product`. Unlike a verb they cannot be domain
    # vocabulary in any language, which is why they are cut and verbs are not: `conciliar`,
    # `faturar` and `aprovar` ARE the business in a Brazilian codebase, and a stoplist that
    # removed verbs would delete exactly the words this module exists to find.
    "about", "after", "also", "been", "before", "both", "does", "each", "else", "from", "have",
    "into", "must", "only", "over", "such", "than", "that", "their", "them", "then", "there",
    "these", "they", "this", "those", "were", "when", "where", "which", "while", "with",
})

#: How many characters of a term to require. Three-letter tokens are overwhelmingly abbreviations
#: of the plumbing above (`api`, `dao`, `dal`, `svc`, `cfg`) and drown the real words.
_TERM_MIN_LEN = 4

#: Ceilings, every one of them declared on the object so a truncated survey never reads as a
#: complete one. They exist because this output is also a PROMPT: an unbounded survey of a
#: 5,000-module monolith is both unreadable and unaffordable.
_MAX_MODULES = 200
_MAX_TERMS = 60
_MAX_ENTRY_POINTS = 60
_MAX_DOCS = 200


class SurveyedModule(BaseModel):
    """One module of the OKF map, plus the three things the map cannot say about it."""

    name: str
    path: str
    #: the bundle's deterministic purpose — a real sentence, or the folder's own name
    purpose: str
    #: TRUE means the deterministic rule found nothing and fell through to `_humanize`. This is
    #: the measurement card #99 turns on: it is not a defect in the generator, it is the exact
    #: count of modules about which the platform currently knows nothing at all.
    purpose_is_folder_name: bool
    files: int
    public_surface: list[str] = Field(default_factory=list)
    dependencies: list[str] = Field(default_factory=list)
    #: reverse edges. The most-depended-on module is rarely the biggest one, and it is the one a
    #: reverse-engineering session should start from.
    depended_on_by: list[str] = Field(default_factory=list)
    #: test-shaped files INSIDE this module's directory
    tests_inside: int = 0
    #: test files elsewhere in the repository whose name names one of this module's files
    #: (`tests/test_pricing.py` ↔ `orders/pricing.py`). Repo-relative, sorted, capped.
    tested_by: list[str] = Field(default_factory=list)
    anchor: str = ""

    # -- what the repository's own history says about this module -----------------------------
    # A MODULE IS AN AREA. The map already knew everything about one except the fact that predicts
    # where the next change lands — and its own ordering, by SIZE, is the wrong question on a
    # long-lived codebase, where the biggest module is routinely the one nobody has opened in
    # years. These come from `onboarding/history.py`, attributing each changed path to the module
    # that owns it by the same walk-up the file and test joins already use.
    #
    # A zero here means two different things, and the survey keeps them apart one level up:
    # `RepoSurvey.history` is None when nobody looked, and only then is a zero not a measurement.
    #
    # FILE CHANGES, NOT COMMITS, and the name is the fix rather than a compromise. A module's
    # number is the sum of its files' commit counts, so one commit touching five files of a module
    # counts five. Calling that "commits" would put two columns of the same name in one document
    # measuring different things — the file table's IS a commit count — and a reader comparing them
    # would be quietly wrong. De-duplicating would mean carrying a commit id per file-touch, which
    # is storage this buys nothing else with: for ranking, a commit that rewrites five files of a
    # module IS more activity than one that edits a line, and that is the whole use.
    file_changes: int = 0
    author_count: int = 0
    #: ISO date of the most recent commit in the window; "" when the window saw none
    last_touched: str = ""
    #: work items named in the commits that touched this module, sorted, capped
    tickets: list[str] = Field(default_factory=list)

    @property
    def named_by_no_test(self) -> bool:
        """No test file lives inside it, and none names it.

        NOT "untested", and the distinction is the platform's own — name matching is not coverage,
        so this says nothing about whether the code is exercised. What it does say is that nobody
        reading the repository could find its tests by looking, which is the cheap honest question
        `untested_modules` already asks repository-wide."""
        return self.tests_inside == 0 and not self.tested_by

    @property
    def changes_and_no_test_names_it(self) -> bool:
        """The two facts that are dangerous together, and that no single field could state.

        A module nothing names is unremarkable in a corner nobody touches. The same module in the
        path of every change is where a green suite proves least — and that is precisely what a
        factory about to start work needs told. Measured on a real client bundle: the most-changed
        business file in the repository had no live test and its own test file existed, commented
        out. Every fact recorded separately and correctly; the sentence nowhere."""
        return self.file_changes > 0 and self.named_by_no_test

    @property
    def has_tests(self) -> bool:
        return bool(self.tests_inside or self.tested_by)


class EntryPoint(BaseModel):
    """A place execution begins, read out of a file that declares it."""

    #: repo-relative path of the thing that RUNS (a script name, a handler, a project)
    target: str
    #: what kind of door this is, in words a reader can act on
    kind: str
    evidence: Evidence


class TermSighting(BaseModel):
    """A word this codebase keeps saying, and where it says it.

    A CANDIDATE, NOT A DEFINITION. Frequency proves a word is load-bearing in the code; only a
    developer can say what it means, and that is exactly the sentence the glossary needs."""

    term: str
    #: how many distinct files/symbols the word appears in
    occurrences: int
    #: modules it appears in, sorted, capped at five for readability
    modules: list[str] = Field(default_factory=list)
    evidence: list[Evidence] = Field(default_factory=list)


class RepoSurvey(BaseModel):
    """The deterministic reading. No model was involved in producing any field on this object.

    This IS the evidence a proposal must be anchored to, and it is worth something on its own:
    `render_survey()` turns it into a document the client did not have, at a cost of zero tokens.
    """

    #: absolute path as it was handed to us
    repo: str

    # -- the structural map (OKF) ---------------------------------------------------------
    modules: list[SurveyedModule] = Field(default_factory=list)
    module_count: int = 0
    modules_truncated: bool = False
    #: how many modules' purpose is nothing but the humanized folder name
    degraded_purposes: int = 0

    # -- what it is built from -------------------------------------------------------------
    stacks: list[StackSighting] = Field(default_factory=list)
    entry_points: list[EntryPoint] = Field(default_factory=list)
    entry_points_truncated: bool = False

    # -- what it says about itself ----------------------------------------------------------
    #: documentation the CLIENT already wrote — READMEs, `docs/`, ADRs, CONTRIBUTING. The first
    #: thing a reverse-engineering session should read, and the last thing it should overwrite.
    existing_docs: list[str] = Field(default_factory=list)
    existing_docs_truncated: bool = False
    terms: list[TermSighting] = Field(default_factory=list)
    #: frequent words the stoplist removed. Present so the filtering is VISIBLE: a term list with
    #: no record of what it dropped cannot be audited, and the stoplist is ours, not the client's.
    terms_dropped: list[str] = Field(default_factory=list)

    # -- what is and is not tested -----------------------------------------------------------
    test_files: int = 0
    #: module names with neither a test inside them nor a test elsewhere naming their files,
    #: biggest first. NAME MATCHING IS NOT COVERAGE and the renderer says so out loud — this
    #: finds the modules nothing even mentions, which is a different and cheaper question.
    untested_modules: list[str] = Field(default_factory=list)

    # -- the blindness, declared --------------------------------------------------------------
    files_read: int = 0
    files_unread: int = 0
    unread_extensions: list[UnreadExtension] = Field(default_factory=list)
    #: of those, the ones that are neither documentation nor an asset — i.e. a stack living in
    #: this repository that the structural map is blind to. `[]` = surveyed, nothing of the sort.
    unread_code_extensions: list[str] = Field(default_factory=list)
    #: directories that could not be OPENED. `[]` means the walk completed and every directory was
    #: entered — a measured answer. It is never None: a survey that could not walk at all raises.
    unreadable_dirs: list[str] = Field(default_factory=list)
    walk_truncated: bool = False

    #: the slice-1 manifest proposal, which is also deterministic and carries the client's own CI.
    #: None = the read raised and this survey deliberately carries no manifest rather than an
    #: empty one that would read as "their CI says nothing".
    manifest: ManifestProposal | None = None

    # -- the repository's own history ----------------------------------------------------------
    #: what `onboarding/history.py` read out of `git log`, or None.
    #:
    #: THIS SURVEY DOES NOT GATHER IT, and that is the design rather than an omission. `survey()`
    #: promises no model, no network, NO SUBPROCESS and no writes, and reading a log means running
    #: `git`. So the caller does the impure part and hands the result over — which also keeps the
    #: three states apart:
    #:
    #:     None                        nobody looked at the history on this pass
    #:     set, `.unavailable` filled  somebody looked and could not read it, and it says why
    #:     set, `.usable`              somebody looked and this is what the log says
    #:
    #: A `None` here must never be rendered as "this repository is quiet". It is the difference
    #: between a survey run on a shallow clone and one run on a repository nobody has touched.
    history: RepoHistory | None = None

    @property
    def biggest_modules(self) -> list[SurveyedModule]:
        return sorted(self.modules, key=lambda m: (-m.files, m.name))

    @property
    def busiest_modules(self) -> list[SurveyedModule]:
        """The modules the work actually lands on, busiest first — the ordering a reader of a
        long-lived codebase wants and `biggest_modules` structurally cannot give.

        Falls back to size when nobody read the log, so a caller always gets an ordering rather
        than an empty list it would have to special-case."""
        if not (self.history and self.history.usable):
            return self.biggest_modules
        return sorted(self.modules, key=lambda m: (-m.file_changes, -m.author_count, m.name))

    @property
    def changed_and_named_by_no_test(self) -> list[SurveyedModule]:
        """Modules the work lands on that no test file names, busiest first.

        THIS IS THE SENTENCE THE SURVEY COULD NOT SAY. Both halves were already collected and both
        were correct — churn on one side, `tests_inside` and `tested_by` on the other — and nothing
        crossed them, so the most-changed undefended area of a codebase read exactly like the
        quietest one.

        EMPTY IS NOT ABSENT. When nobody read the history every `commits` is 0 and this is empty
        for a reason that has nothing to do with tests, so a caller branches on `history` first.
        The renderer does."""
        return [m for m in self.busiest_modules if m.changes_and_no_test_names_it]


# ---------------------------------------------------------------------------------------------
# survey() — the deterministic read
# ---------------------------------------------------------------------------------------------


def _stem_words(stem: str) -> list[str]:
    return [w.lower() for w in _WORD.findall(stem)]


def _test_subject(stem: str) -> str:
    """What a test file's NAME says it tests: `test_pricing` → `pricing`, `AdmissaoTests` →
    `admissao`, `admissao.test` → `admissao`. Lowercased, because the same subject is spelled
    `Pricing` in C# and `pricing` in Python and a case-sensitive join would match neither."""
    out = _TEST_PREFIX.sub("", stem)
    out = _TEST_SUFFIX.sub("", out)
    return out.lower()


def _is_test_path(rel: str) -> bool:
    parts = rel.split("/")
    if any(p in _TEST_DIRS for p in parts[:-1]):
        return True
    stem = Path(parts[-1]).stem
    return bool(_TEST_PREFIX.match(stem) or _TEST_SUFFIX.search(stem))


class _Files(BaseModel):
    """Every path of the repository, split the three ways this module needs it."""

    #: repo-relative POSIX paths, sorted
    all: list[str] = Field(default_factory=list)
    code: list[str] = Field(default_factory=list)
    tests: list[str] = Field(default_factory=list)
    docs: list[str] = Field(default_factory=list)
    unreadable: list[str] = Field(default_factory=list)
    #: what the repository itself ignores (`generator.ignored_by_git`) — pruned before the walk,
    #: recorded so "not inventoried" is a statement and not a silence
    ignored: list[str] = Field(default_factory=list)
    truncated: bool = False


_DOC_SUFFIXES = frozenset({".md", ".markdown", ".rst", ".adoc", ".txt"})

#: Files that carry a documentation SUFFIX and are not documentation ANYBODY WROTE about this
#: product — a licence, a dependency pin, a generated changelog, a template. Matched on the stem so
#: `LICENSE`, `LICENSE.txt` and `LICENSE.md` are one rule.
#:
#: THIS LIST IS NEW BECAUSE THE FIELD GAINED ITS FIRST READER. `existing_docs` was collected and
#: consumed by nothing, so "every .txt is a doc" cost nothing; the moment it is published to the
#: client under "documentation you already wrote", a section listing `requirements.txt` and
#: `LICENSE.txt` tells them we did not read what we are about to reason over.
_NOT_AUTHORED_DOCS = frozenset({
    "license", "licence", "copying", "notice", "authors", "contributors", "patents",
    "changelog", "changes", "history", "requirements", "requirements-dev", "constraints",
    "pipfile", "codeowners", "code_of_conduct", "security", "funding", "issue_template",
    "pull_request_template",
})

#: Directories whose contents belong to SOMEBODY ELSE. A vendored library's own manual is not the
#: client's account of their system, and reading it as one is how a survey concludes that an
#: accounting product is a JSON parser.
_NOT_OURS = frozenset({"node_modules", "vendor", "vendored", "third_party", "thirdparty",
                       "site-packages", "dist-packages", ".venv", "venv", "dist", "build",
                       "target", ".git", "bower_components", "packages"})


def _is_client_doc(rel: str, suffix: str) -> bool:
    """Documentation THIS CLIENT wrote about THIS system — the thing a reverse-engineering pass
    should read first and never overwrite.

    Three questions, and the first two are exclusions because the suffix test alone is far too
    generous: `.txt` is also how a dependency pin and a licence are spelled."""
    parts = rel.split("/")
    lowered = [p.lower() for p in parts[:-1]]
    if any(p in _NOT_OURS for p in lowered):
        return False
    # A FORM SOMEBODY FILLS IN IS NOT AN ACCOUNT OF THE SYSTEM. `.github/ISSUE_TEMPLATE/bug.md`
    # has a documentation suffix and a stem nobody can enumerate, so the directory is the rule.
    if any(p in {"issue_template", "pull_request_template"} for p in lowered):
        return False
    if Path(parts[-1]).stem.lower() in _NOT_AUTHORED_DOCS:
        return False
    return suffix in _DOC_SUFFIXES or any(p.lower() in _DOC_DIRS for p in parts[:-1])
#: Documentation is recognised by LOCATION as well as extension: a `.txt` at the root of a
#: fifteen-year-old repository is very often the only design note anybody wrote.
_DOC_DIRS = frozenset({"doc", "docs", "documentation", "adr", "adrs", "rfc", "rfcs", "wiki",
                       "decisions", "decisoes", "arquitetura", "architecture"})


def _collect_files(repo: Path, max_files: int) -> _Files:
    """One walk, three lists, and the directories that could not be opened.

    `on_error` is passed on purpose: `os.walk`'s default is to SWALLOW an unreadable directory and
    simply yield fewer entries, so a vendored subtree the process cannot read is indistinguishable
    from one that is empty. That collapse — could-not-read reading as read-and-empty — is the
    defect class this whole module is written against, and it would be embarrassing to ship it
    inside the function that measures it."""
    unreadable: list[str] = []

    def on_error(error: OSError) -> None:
        raw = getattr(error, "filename", "") or ""
        try:
            unreadable.append(Path(raw).relative_to(repo).as_posix() if raw else ".")
        except ValueError:
            unreadable.append(str(raw))

    ignored = ignored_by_git(repo)
    paths: list[str] = []
    for rel_dir, filenames in _walk_files(repo, on_error=on_error, ignored=ignored):
        prefix = "" if rel_dir == Path(".") else f"{rel_dir.as_posix()}/"
        paths.extend(f"{prefix}{name}" for name in filenames)
    walked = len(paths)
    # (depth, path) so a repository big enough to hit the ceiling still yields its ROOT, where
    # every build file, CI file and README actually lives. Same reasoning as `infer._tree`.
    paths.sort(key=lambda p: (p.count("/"), p))
    kept = paths[:max_files]

    code, tests, docs = [], [], []
    for rel in kept:
        suffix = Path(rel).suffix.lower()
        if suffix in _CODE_SUFFIXES:
            (tests if _is_test_path(rel) else code).append(rel)
        elif _is_test_path(rel) and suffix not in _INERT_SUFFIXES:
            tests.append(rel)
        if _is_client_doc(rel, suffix):
            docs.append(rel)
    return _Files(all=kept, code=sorted(code), tests=sorted(tests), docs=sorted(docs),
                  unreadable=sorted(set(unreadable)), ignored=sorted(ignored),
                  truncated=walked > max_files)


def _module_rows(modules: list[Module], files: _Files,
                 history: RepoHistory | None = None) -> list[SurveyedModule]:
    """The OKF modules, enriched with reverse dependencies, with what tests them, and with what
    the repository's own log says has been happening to them."""
    incoming: dict[str, list[str]] = {}
    for mod in modules:
        for dep in mod.dependencies:
            incoming.setdefault(dep, []).append(mod.name)

    # stem → the modules owning a source file with that stem. Built once; the join below is what
    # lets `tests/test_pricing.py` be credited to `orders/`, which is the layout of every Python
    # repository that keeps its tests out of the package.
    owners: dict[str, set[str]] = {}
    by_dir = {m.path.rstrip("/"): m.name for m in modules}

    def owner_of(rel: str) -> str | None:
        """The module that owns a repo-relative path, or None.

        Walks up to the nearest directory that IS a module, because a .NET project folds its
        subfolders under one. Extracted rather than written a third time: the file join and the
        test join each carried a copy, and the history join below needs the same answer — three
        copies of a loop is how the three stop agreeing."""
        cur = rel.rsplit("/", 1)[0] if "/" in rel else "."
        while True:
            found = by_dir.get(cur if cur else ".")
            if found or cur in ("", "."):
                return found
            cur = cur.rsplit("/", 1)[0] if "/" in cur else "."

    for rel in files.code:
        owner = owner_of(rel)
        if owner:
            owners.setdefault(Path(rel).stem.lower(), set()).add(owner)

    # A TEST FILE MAY NAME A PACKAGE INSTEAD OF A FILE, and this repository is the proof:
    # `tests/test_knowledge.py` covers `openfactory/knowledge/`, where no file is called
    # `knowledge.py`.
    # Matching only file stems reported `openfactory.knowledge` — nine files, its own test module —
    # as
    # named by nothing, which is a confident wrong finding about somebody's test discipline. The
    # leaf of the dotted module name is the other thing a test author writes down.
    for mod in modules:
        leaf = mod.name.rsplit(".", 1)[-1].lower()
        if leaf and leaf != "<root>":
            owners.setdefault(leaf, set()).add(mod.name)

    def credited(subject: str) -> set[str]:
        """The modules a test file named `test_<subject>.py` plausibly names.

        LONGEST PREFIX WINS, and it is walked rather than matched exactly because a test file
        names the thing it tests with as many words as it needs. Measured here: this repository
        has `tests/test_product_role.py` and no file called `product_role.py`, so exact matching
        reported `openfactory.product` — eighteen files with a test module of its own — as named by
        nothing at all. Stripping one `_`-segment at a time finds `product`; stopping at the
        FIRST hit keeps `test_box_prove.py` credited to the file `box_prove.py` rather than to
        every module whose name starts with `box`."""
        parts = subject.split("_")
        while parts:
            hit = owners.get("_".join(parts))
            if hit:
                return hit
            parts.pop()
        return set()

    tested_by: dict[str, list[str]] = {}
    inside: dict[str, int] = {}
    for rel in files.tests:
        subject = _test_subject(Path(rel).stem)
        for named in sorted(credited(subject)):
            tested_by.setdefault(named, []).append(rel)
        owner = owner_of(rel)
        if owner:
            inside[owner] = inside.get(owner, 0) + 1

    # THE HISTORY JOIN. Each changed path is attributed to the module that owns it, so a module's
    # churn is the churn of its files — the same walk-up, so a path counted for the map and a path
    # counted for the log cannot land in different modules. A path the map does not own (a
    # top-level config file, a deleted directory) is simply not attributed: it is in the change
    # surface already, and inventing an owner for it would put churn on a module that never saw it.
    churn: dict[str, dict] = {}
    for row in (history.files if history and history.usable else []):
        owner = owner_of(row.path)
        if not owner:
            continue
        seen = churn.setdefault(owner, {"changes": 0, "authors": set(), "last": "",
                                        "tickets": set()})
        seen["changes"] += row.commits
        seen["authors"].update(row.authors)
        seen["tickets"].update(row.tickets)
        seen["last"] = max(seen["last"], row.last_touched)

    rows = [
        SurveyedModule(
            name=m.name,
            path=m.path,
            purpose=m.purpose,
            purpose_is_folder_name=(m.purpose == _humanize(m.name)),
            files=m.file_count,
            public_surface=list(m.public_surface),
            dependencies=list(m.dependencies),
            depended_on_by=sorted(incoming.get(m.name, [])),
            tests_inside=inside.get(m.name, 0),
            tested_by=sorted(set(tested_by.get(m.name, [])))[:10],
            anchor=m.source.file,
            file_changes=churn.get(m.name, {}).get("changes", 0),
            # NOT the sum of each file's author count — the same person touching four files of a
            # module is one author of that module, and summing would report a team where there is
            # one maintainer, which is the opposite of the truth a reader needs.
            author_count=len(churn.get(m.name, {}).get("authors", ())),
            last_touched=churn.get(m.name, {}).get("last", ""),
            tickets=sorted(churn.get(m.name, {}).get("tickets", ()))[:10],
        )
        for m in modules
    ]
    rows.sort(key=lambda r: r.name)
    return rows


# --- entry points ---------------------------------------------------------------------------

#: Conventional file names that ARE a door, and what kind. Read as names only — no parsing, so it
#: works on a stack nothing here understands.
_ENTRY_NAMES: dict[str, str] = {
    "__main__.py": "python module entry (`python -m <package>`)",
    "main.py": "conventional Python entry point",
    "app.py": "conventional Python/Flask application object",
    "wsgi.py": "WSGI application entry point",
    "asgi.py": "ASGI application entry point",
    "manage.py": "Django management entry point",
    "Program.cs": ".NET program entry point (`Main`)",
    "Startup.cs": "ASP.NET startup / composition root",
    "host.json": "Azure Functions host — this directory is a function app",
    "serverless.yml": "Serverless Framework service",
    "serverless.yaml": "Serverless Framework service",
    "server.js": "Node server entry point",
    "server.ts": "Node server entry point",
    "index.js": "Node package entry point",
    "index.ts": "Node package entry point",
}

_DOCKER_ENTRY = re.compile(r"^\s*(ENTRYPOINT|CMD)\s+(.*)$", re.IGNORECASE)
_CSPROJ_EXE = re.compile(r"<OutputType>\s*(Exe|WinExe)\s*</OutputType>", re.IGNORECASE)


def _toml_key_line(text: str, section: str, key: str) -> tuple[int | None, str]:
    """The line of `key` inside `[section]` of a TOML file.

    Scoped to the section rather than searched globally, because `test = "…"` appears in
    `[project.scripts]`, in `[tool.poetry.scripts]` and in half a dozen tool tables, and a global
    search cites whichever came first — a citation that points at the wrong line is worse than no
    citation, since a reader who opens it and sees something unrelated stops trusting all of them.
    """
    inside = False
    for index, raw in enumerate(text.splitlines(), start=1):
        stripped = raw.strip()
        if stripped.startswith("["):
            inside = stripped.rstrip().rstrip("]").lstrip("[").strip() == section
            continue
        if inside and re.match(rf"^\s*[\"']?{re.escape(key)}[\"']?\s*=", raw):
            return index, stripped
    return None, ""


def _entry_points(repo: Path, files: _Files) -> tuple[list[EntryPoint], bool]:
    """Where execution begins, each anchored to the file that declares it.

    Declared doors first (a `[project.scripts]` entry, a `bin` in `package.json`, a Dockerfile
    `ENTRYPOINT`), conventional names second. The declared ones are stronger evidence for the same
    reason a CI file beats a convention in `infer.py`: somebody wrote them down on purpose, and
    they are what actually runs in production."""
    out: list[EntryPoint] = []

    def add(target: str, kind: str, path: str, line: int | None, excerpt: str = "") -> None:
        out.append(EntryPoint(target=target, kind=kind,
                              evidence=Evidence(path=path, line=line, excerpt=excerpt[:200])))

    for rel in files.all:
        name = Path(rel).name
        text: str | None
        if name == "pyproject.toml":
            text = _read(repo / rel)
            if text is None:
                continue
            try:
                import tomllib

                data = tomllib.loads(text)
            except (ValueError, TypeError):
                continue
            scripts = ((data.get("project") or {}).get("scripts") or {})
            poetry = (((data.get("tool") or {}).get("poetry") or {}).get("scripts") or {})
            for section, table in (("project.scripts", scripts), ("tool.poetry.scripts", poetry)):
                for script, target in sorted((table or {}).items()):
                    line, excerpt = _toml_key_line(text, section, script)
                    add(f"{script} → {target}", "console script", rel, line, excerpt)

        elif name == "package.json":
            text = _read(repo / rel)
            if text is None:
                continue
            try:
                data = json.loads(text)
            except ValueError:
                continue
            if not isinstance(data, dict):
                continue
            binaries = data.get("bin")
            if isinstance(binaries, str):
                line, excerpt = _find_line(text, '"bin"')
                add(binaries, "npm bin", rel, line, excerpt)
            elif isinstance(binaries, dict):
                for script, target in sorted(binaries.items()):
                    line, excerpt = _find_line(text, f'"{script}"')
                    add(f"{script} → {target}", "npm bin", rel, line, excerpt)
            main = data.get("main")
            if isinstance(main, str) and main:
                line, excerpt = _find_line(text, '"main"')
                add(main, "node package main", rel, line, excerpt)
            start = (data.get("scripts") or {}).get("start") if isinstance(
                data.get("scripts"), dict) else None
            if isinstance(start, str) and start:
                line, excerpt = _find_line(text, '"start"')
                add(start, "npm start script", rel, line, excerpt)

        elif (name == "Dockerfile" or name.startswith("Dockerfile.")
              or name.endswith(".Dockerfile")):
            # ALL THREE SPELLINGS. This repository's own images are `docker/worker.Dockerfile`
            # and `docker/sandbox.Dockerfile`; a check for the bare name would have found the
            # container entry points of every client except the one that wrote this module.
            text = _read(repo / rel)
            if text is None:
                continue
            for index, raw in enumerate(text.splitlines(), start=1):
                m = _DOCKER_ENTRY.match(raw)
                if m:
                    add(m.group(2).strip(), f"container {m.group(1).upper()}", rel, index,
                        raw.strip())

        elif Path(rel).suffix.lower() in (".csproj", ".fsproj", ".vbproj"):
            text = _read(repo / rel)
            if text is None:
                continue
            if _CSPROJ_EXE.search(text):
                line, excerpt = _find_line(text, "<OutputType>")
                add(rel, "executable .NET project", rel, line, excerpt)

        elif name in ("template.yaml", "template.yml"):
            # AWS SAM. Every `Handler:` is a lambda, i.e. a door into this codebase from outside.
            # Every level is isinstance-checked rather than trusted: a client's template may be
            # any YAML at all (a Helm chart, a CloudFormation snippet, a file called
            # `template.yaml` for unrelated reasons), and an `AttributeError` here would take
            # down the whole survey over a file that was never ours to read.
            doc = _load_yaml(repo / rel)
            resources = doc.get("Resources") if isinstance(doc, dict) else None
            for resource, body in sorted((resources or {}).items()
                                         if isinstance(resources, dict) else []):
                properties = body.get("Properties") if isinstance(body, dict) else None
                handler = properties.get("Handler") if isinstance(properties, dict) else None
                if isinstance(handler, str):
                    add(f"{resource} → {handler}", "SAM lambda handler", rel, _line_of(handler),
                        f"Handler: {handler}")

        if name in _ENTRY_NAMES:
            add(rel, _ENTRY_NAMES[name], rel, None)

    # Declared doors before conventional ones, then by path — deterministic and useful in that
    # order. `kind` sorts before `target` so the reader sees the categories grouped.
    conventional = set(_ENTRY_NAMES.values())
    out.sort(key=lambda e: (e.kind in conventional, e.kind, e.target, e.evidence.path))
    return out[:_MAX_ENTRY_POINTS], len(out) > _MAX_ENTRY_POINTS


# --- domain vocabulary ------------------------------------------------------------------------


def _terms(files: _Files, modules: list[SurveyedModule]) -> tuple[list[TermSighting], list[str]]:
    """The words this codebase keeps saying, from file names and public symbols.

    FILE NAMES ARE THE PART THAT SURVIVES EVERYTHING. Public symbols come from the OKF map, which
    understands four stacks; a file name is legible in every stack there is, which is why a Java
    or COBOL repository still produces a vocabulary here while its module map is empty.

    Tests are excluded as a SOURCE but not as a subject: `AdmissaoTests.cs` would double-count
    `admissao` and inflate exactly the words that already rank highest."""
    hits: dict[str, dict[str, Any]] = {}
    dropped: dict[str, int] = {}

    def note(word: str, module: str, evidence: Evidence | None) -> None:
        if word in _TERM_STOPWORDS:
            # ONLY the stoplist is recorded as "dropped". A three-letter token or a digit run is
            # cut by a rule nobody would argue with; the stoplist is a JUDGEMENT about somebody
            # else's vocabulary, and it is the only one worth putting in front of them.
            dropped[word] = dropped.get(word, 0) + 1
            return
        if len(word) < _TERM_MIN_LEN or word.isdigit():
            return
        row = hits.setdefault(word, {"n": 0, "modules": set(), "evidence": []})
        row["n"] += 1
        if module:
            row["modules"].add(module)
        # DEDUPED BY LOCATOR: a word reaches this function twice for one file — once from the
        # file's stem and once from a symbol whose module anchor is that same file — and without
        # this the glossary printed `ex. src/Admissao.cs, src/Admissao.cs`, which reads as a
        # careless tool in the first three lines a client sees.
        if (evidence is not None and len(row["evidence"]) < 3
                and all(e.locator != evidence.locator for e in row["evidence"])):
            row["evidence"].append(evidence)

    by_dir = {m.path.rstrip("/"): m.name for m in modules}
    for rel in files.code:
        directory = rel.rsplit("/", 1)[0] if "/" in rel else "."
        module = by_dir.get(directory, "")
        ev = Evidence(path=rel)
        for word in _stem_words(Path(rel).stem):
            note(word, module, ev)

    for mod in modules:
        # A TEST MODULE'S PUBLIC SURFACE IS NOT VOCABULARY. Test files are already excluded as a
        # source of file-stem terms, but their SYMBOLS arrive here through the OKF map, and on
        # `fx-dsk-flows` that put `respeita`, `ignora`, `todas`, `nada` and `caixa` — the words of
        # one C# test method name — into a client's glossary above their real domain terms. A
        # glossary whose first entries are somebody's assertion phrasing is not read twice.
        if _is_test_path(f"{mod.path.rstrip('/')}/x"):
            continue
        anchor = Evidence(path=mod.anchor) if mod.anchor else None
        for symbol in mod.public_surface:
            for word in _stem_words(symbol):
                note(word, mod.name, anchor)

    # NO MINIMUM FREQUENCY, and an earlier draft had one (`n > 1`, on the reasoning that a word
    # said once is a file name rather than a vocabulary). Measured against a three-file Java
    # repository, that rule returned NOTHING: every one of `Boleto`, `Fatura`, `Conciliacao`
    # appears exactly once, and the smallest repositories are precisely where the map is emptiest
    # and this list is the only vocabulary anybody gets. Rarity is handled by the SORT instead —
    # a once-seen word ranks below every recurring one and falls off the end of `_MAX_TERMS` on
    # any repository big enough for that to matter.
    rows = [
        TermSighting(term=term, occurrences=row["n"],
                     modules=sorted(row["modules"])[:5], evidence=row["evidence"])
        for term, row in hits.items()
    ]
    rows.sort(key=lambda t: (-len(t.modules), -t.occurrences, t.term))
    # …and the words the stoplist removed, most frequent first. Ours is the only judgement being
    # applied to a client's vocabulary anywhere in this module, so it is the one that has to be
    # visible; a filter nobody can audit is a filter that quietly deletes a domain.
    removed = sorted((w for w, n in dropped.items() if n > 1),
                     key=lambda w: (-dropped[w], w))[:15]
    return rows[:_MAX_TERMS], removed


def _is_tooling(rel: str) -> bool:
    """A path that is somebody's tooling by universal convention: a dotfile, or anything under a
    dot-directory. A stack does not hide in `.terraform/providers/…` or in `.secrets/`, and on
    this repository's first run those two directories contributed `.0_x5`, `.hcl` and `.pem` to a
    list headed *"code this map cannot read"* — three entries of noise around the two that
    mattered (`.sh`, `.tf`). A blind-spot report with a 6:2 noise ratio is not read to the end,
    and the entries it buries are the whole reason it exists."""
    return any(part.startswith(".") for part in rel.split("/"))


def _unread_code(files: _Files) -> list[str]:
    """Extensions present in this repository that are probably CODE the structural map cannot
    read — biggest first, so the largest blind spot leads.

    Counted over this module's own walk rather than over `survey_extensions().unread`, because
    the judgement is per FILE (*is this path tooling?*) and that survey reports per SUFFIX. Both
    use `_walk_files`, so on an untruncated walk they see the same repository; when the walk hits
    `max_files` this list covers only what was walked, and `walk_truncated` on the survey says so.

    The rule is: not inert, not tooling, and NOT ONE OF THE FOUR FAMILIES THE MAP ACTUALLY READS.
    That last clause is `_SOURCE_SUFFIXES` — the generator's own set — and not `_CODE_SUFFIXES`,
    which is this module's much wider list of extensions whose NAME is worth reading. Using the
    wide one here was measured and was exactly backwards: `.java` is in it, so a Java repository
    (empty module map, by construction) reported no unread code at all — the C-49 collapse
    reproduced inside the field written to declare it.

    Anything the platform has never heard of counts as code, which is the safe direction —
    over-reporting costs one line in a table, under-reporting hides a subsystem written in a
    language nobody here has met."""
    counts: dict[str, int] = {}
    for rel in files.all:
        suffix = Path(rel).suffix
        if suffix.lower() in _INERT_SUFFIXES or suffix.lower() in _SOURCE_SUFFIXES:
            continue
        if _is_tooling(rel):
            continue
        counts[suffix] = counts.get(suffix, 0) + 1
    return sorted(counts, key=lambda s: (-counts[s], s))


def survey(repo_path: str | Path, *, max_files: int = 20_000,
           history: RepoHistory | None = None) -> RepoSurvey:
    """Read `repo_path` deterministically and return everything a proposal must be anchored to.

    `history` is RECEIVED, never gathered — reading a log means running `git`, and the promise
    below is that this function runs nothing. The caller reads it (`onboarding/history.py`) and
    hands it over, which is also what keeps "nobody looked" distinguishable from "looked and the
    repository is quiet". See `RepoSurvey.history`.

    No model, no network, no subprocess, no writes. Same repository state → identical object.

    Raises `NotADirectoryError` when `repo_path` is not a readable directory, for the same reason
    `infer()` does: `os.walk` swallows that error and yields nothing, so a typo in a path would
    come back as a confident survey of a repository with no modules, no stacks and no tests — a
    failure wearing the costume of an answer, on the day a client is deciding whether to buy.
    """
    root = Path(repo_path).expanduser()
    if not root.is_dir():
        raise NotADirectoryError(
            f"cannot survey {root}: it is not a directory. Refusing to return a survey, because "
            "an empty one here is indistinguishable from a repository that genuinely holds "
            "nothing — and this survey is read aloud as a statement about the client's code."
        )
    resolved = root.resolve()
    files = _collect_files(resolved, max_files)

    module_map = build_module_map(resolved)
    rows = _module_rows(module_map.modules, files, history)
    degraded = sum(1 for r in rows if r.purpose_is_folder_name)

    extensions = survey_extensions(resolved)
    unread_code = _unread_code(files)

    entry_points, entry_truncated = _entry_points(resolved, files)
    terms, dropped = _terms(files, rows)

    # THE SLICE-1 READ IS PART OF THE EVIDENCE, not a separate product: the client's own CI file
    # is where the real commands live, and a reverse-engineering session that does not have them
    # in front of it asks questions the repository already answered. It is best-effort — a
    # proposal that raises must not take the survey down with it, because everything above is
    # still true and still worth reading aloud.
    manifest: ManifestProposal | None = None
    try:
        manifest = infer_manifest(resolved, max_files=max_files)
    except Exception as exc:  # noqa: BLE001 — a client's repository may be anything at all
        log.warning("context survey: the manifest read failed on %s (%s) — the survey carries "
                    "no manifest rather than an empty one", resolved, exc)

    untested = sorted(
        (r for r in rows if not r.has_tests),
        key=lambda r: (-r.files, r.name),
    )

    return RepoSurvey(
        repo=str(resolved),
        modules=rows[:_MAX_MODULES],
        module_count=len(rows),
        modules_truncated=len(rows) > _MAX_MODULES,
        degraded_purposes=degraded,
        stacks=list(manifest.stacks) if manifest else [],
        entry_points=entry_points,
        entry_points_truncated=entry_truncated,
        existing_docs=files.docs[:_MAX_DOCS],
        existing_docs_truncated=len(files.docs) > _MAX_DOCS,
        terms=terms,
        terms_dropped=dropped,
        test_files=len(files.tests),
        untested_modules=[r.name for r in untested],
        files_read=extensions.files_read,
        files_unread=extensions.files_unread,
        unread_extensions=[UnreadExtension(suffix=s, files=n) for s, n in extensions.unread],
        unread_code_extensions=unread_code,
        unreadable_dirs=sorted(set(files.unreadable) | set(extensions.unreadable)),
        walk_truncated=files.truncated,
        manifest=manifest,
        history=history,
    )


# ---------------------------------------------------------------------------------------------
# The semantic proposal
# ---------------------------------------------------------------------------------------------


class Claim(BaseModel):
    """One sentence the model proposed, and the citations that survived verification."""

    text: str
    evidence: list[Evidence] = Field(default_factory=list)
    #: what the model cited that does not exist. Kept ON the claim rather than discarded, so a
    #: reader can see the shape of the mistake instead of a claim that quietly lost a source.
    rejected_citations: list[str] = Field(default_factory=list)


class Term(BaseModel):
    """A glossary entry: the word, what the model thinks it means here, and where it read it."""

    term: str
    meaning: str
    evidence: list[Evidence] = Field(default_factory=list)
    rejected_citations: list[str] = Field(default_factory=list)


class ContextDocument(BaseModel):
    """A file ready to be authored into the CONTEXT repository. Nothing writes it here."""

    #: repo-relative path INSIDE the context repository
    path: str
    title: str
    body: str
    #: "survey" | "overview" | "glossary" | "invariants" | "questions"
    kind: str
    #: False means every line of it was derived deterministically and costs nothing to trust.
    from_model: bool
    #: None = no `docs_root` was given, so this was never checked. True/False = it was.
    exists: bool | None = None


class ContextProposal(BaseModel):
    """What one pass over one repository proposes as its context — and what it refuses to."""

    repo: str
    #: whether this object is usable at all. False ONLY when a semantic pass was attempted and
    #: failed; a deterministic-only proposal (`ask=None`) is a legitimate answer, not a failure.
    ok: bool = True
    #: non-empty iff `ok` is False. Says what happened, in the operator's terms.
    refusal: str = ""
    #: True when a model actually contributed. False + ok=True means "deterministic only".
    semantic: bool = False
    #: agent passes actually spent. The bound is the product: an onboarding session that costs an
    #: unpredictable number of passes is one nobody can price.
    asked: int = 0

    what_it_does: list[Claim] = Field(default_factory=list)
    vocabulary: list[Term] = Field(default_factory=list)
    entities: list[Claim] = Field(default_factory=list)
    invariants: list[Claim] = Field(default_factory=list)
    #: the ones only a developer can answer — the agenda for the room, and the reason the session
    #: is worth an hour of their time.
    questions: list[str] = Field(default_factory=list)
    #: the subset of `questions` the SURVEY earned, each with the code that makes it the same
    #: question next month (`onboarding/questions.py`). `questions` carries their text alongside
    #: the model's and the demoted claims', so there is one source and two views rather than two
    #: lists that drift. Empty on a proposal built before questions had identity.
    tracked: list[SurveyQuestion] = Field(default_factory=list)
    #: claims that lost every citation and became questions. Each entry names the sentence AND
    #: the citation that failed, because "the model was wrong" and "the model was right about a
    #: file it mis-spelled" need different reactions from the person reading this.
    demoted: list[str] = Field(default_factory=list)
    #: citations whose FILE was verified and whose LINE could not be — `_Anchorer` reached its
    #: own ceiling on distinct files, or a file could not be opened. The claims are published
    #: (the file is real) but WITHOUT the unchecked line, and the locators are named here.
    #: `[]` = every line in every surviving citation was checked against the file on disk.
    citations_unverified: list[str] = Field(default_factory=list)

    documents: list[ContextDocument] = Field(default_factory=list)


#: The one-argument read-only primitive this module needs: a prompt in, the agent's complete final
#: text out. Every judging role in the platform is built on `ask()` (`adapters/agent/roles.py`);
#: `agent_ask()` below binds a real adapter into this shape.
AskFn = Callable[[str], str]


def agent_ask(agent: object, *, sandbox: object, workspace: object, phase: str = "ask") -> AskFn:
    """Bind a harness adapter's read-only `ask` into the primitive `propose_context` takes.

    THE PHASE IS `ask` ON PURPOSE. `roles.HUMAN_PHASES` is the set whose output a human reads, and
    it drives the language directive at every call site that consults it. A new phase string
    invented here would not be in that set — and it lives in a file this change does not touch —
    so the documents would silently come back in the model's default language at a Brazilian
    client. Reusing the phase that is already in the set keeps the behaviour that every other
    human-facing role already gets.

    Raises `TypeError` when the harness cannot run a read-only prompt at all, rather than
    returning a callable that fails later inside a `try`: a harness with no `ask` is a
    configuration fact, and discovering it in front of the client is not the moment."""
    if not can_judge(agent):
        raise TypeError(
            f"{type(agent).__name__} has no read-only `ask` — it cannot serve a judging role, so "
            "it cannot propose a context either. Configure a harness that implements `ask` "
            "(claude/codex/kimi/opencode all do) or run the survey alone, which spends no tokens."
        )

    def _ask(prompt: str) -> str:
        return final_text(agent.ask(  # type: ignore[attr-defined]
            sandbox=sandbox, workspace=workspace, prompt=prompt, phase=phase))

    return _ask


_JSON_SHAPE = """{
  "does":       [{"text": "one sentence on what the system does", "cites": ["path/f.ext:12"]}],
  "vocabulary": [{"term": "Admissao", "meaning": "what it means IN THIS SYSTEM", "cites": ["..."]}],
  "entities":   [{"text": "the main entity and what it holds", "cites": ["..."]}],
  "invariants": [{"text": "a rule the code enforces everywhere", "cites": ["..."]}],
  "questions":  ["a question only a developer who worked here can answer"]
}"""


def build_prompt(survey_result: RepoSurvey, *, language: str | None = None) -> str:
    """The single read-only pass. Exposed (rather than inlined) so it can be read and tested:
    a prompt nobody can see is a prompt nobody can review, and this one is the only place in the
    module where the platform asks a model to say something about a client's business."""
    return "\n".join([
        "# Reverse-engineering the context of an existing codebase",
        "",
        "You are reading a repository that already exists, alongside the developers who wrote it.",
        "Your output is the FIRST DRAFT of its context documentation: what the system does, the",
        "vocabulary of its domain, its main entities, the invariants visible in the code, and the",
        "questions only its developers can answer. They will correct you, out loud, today.",
        "",
        "## The rules, and they are the product",
        "",
        "1. EVERY claim cites at least one real file from this repository, as `path` or",
        "   `path:line`. Paths are repository-relative, exactly as they appear on disk.",
        "2. A citation is CHECKED against the filesystem before your sentence is published. A",
        "   file that does not exist, or a line past the end of a real file, deletes the claim —",
        "   it is republished as a question with your sentence attached. Guessing costs you the",
        "   sentence; it does not buy you one.",
        "3. Anything you cannot anchor to a file goes in `questions`, phrased as a question. A",
        "   plausible sentence about a business you have not read is the one output that makes",
        "   this document worthless, because a reader cannot tell it from the anchored ones.",
        "4. Vocabulary means THIS BUSINESS's words, not the framework's. `Admissao`, `Apolice`,",
        "   `Conciliacao` are entries; `Repository`, `Handler`, `DTO` are not.",
        "5. Invariants are rules the CODE enforces (a guard, a constraint, a check repeated in",
        "   several places), not rules you would recommend.",
        "",
        language_directive(language),
        "",
        "## What a deterministic read already established",
        "",
        "This was produced by reading files, with no model involved. It is evidence, not a",
        "summary: correct it where the code disagrees, and use it to know where to look.",
        "",
        render_survey(survey_result, for_prompt=True, language=language),
        "",
        "## Answer with one fenced JSON object and nothing else that matters",
        "",
        "```json",
        _JSON_SHAPE,
        "```",
        "",
        "Empty lists are allowed and are a real answer: a repository whose invariants you cannot",
        "see in the code should come back with `\"invariants\": []` and a question, never with a",
        "sentence you composed to fill the field.",
    ])


def _repo_relative(repo: Path, raw: str) -> str | None:
    """A cited path, normalised, or None when it escapes the repository or is empty.

    `../../etc/passwd` is not a hypothetical just because a model wrote it: the citation string is
    used to open a file, and a proposal is produced on a laptop sitting in front of a client. The
    check is on the RESOLVED path so a symlink cannot walk out either."""
    text = (raw or "").strip().strip("`")
    # THE ABSOLUTE CHECK COMES BEFORE ANY STRIPPING, and an earlier draft of this function had it
    # the other way round: `"/etc/passwd".lstrip("./")` is `"etc/passwd"`, so the `startswith("/")`
    # guard could never fire and an absolute path was quietly reinterpreted as a relative one.
    # Nothing escaped the repository, but the citation printed under the claim was a path the
    # model never wrote — a wrong citation, which is the one output this module cannot ship.
    if not text or text.startswith(("/", "~", "\\")) or ":" in text.split("/")[0]:
        return None
    if text.startswith("./"):
        text = text[2:]
    normalised = os.path.normpath(text)
    if normalised.startswith("..") or os.path.isabs(normalised):
        return None
    try:
        target = (repo / normalised).resolve()
        target.relative_to(repo.resolve())
    except (OSError, ValueError):
        return None
    return Path(normalised).as_posix()


def _split_citation(raw: str) -> tuple[str, int | None]:
    """`"openfactory/box_prove.py:52"` → `("openfactory/box_prove.py", 52)`. A trailing `:52`
    only counts when
    it is digits: a Windows-style `C:\\src` or a `namespace:name` must not lose its tail.

    A RANGE IS A CITATION, AND REFUSING IT COST A WHOLE PASS. `file.py:139-186` is how a model
    cites a block — it is MORE precise than a single line, not less — and this returned the
    whole string as the path, so the file was looked up as `…/content.py:139-186`, found
    missing, and the claim was demoted with a sentence that says the repository *does not
    contain the file*. Measured on the pilot (2026-08-14): every ranged citation in a real
    backfill was rejected and the one single-line citation survived, so a semantic pass that had
    read the repository correctly produced a document of "is this true?" questions and one
    invariant. The tokens were spent; the verdict was the parser's.

    The START of the range is what anchors: it is the line the claim is about, and the caller
    still checks it exists in that file."""
    text = (raw or "").strip().strip("`")
    head, sep, tail = text.rpartition(":")
    if not (sep and head):
        return text, None
    if tail.isdigit():
        return head, int(tail)
    start, dash, end = tail.partition("-")
    if dash and start.isdigit() and end.isdigit() and int(end) >= int(start):
        return head, int(start)
    return text, None


class _Anchorer:
    """Turns a model's citation strings into `Evidence`, or into a reason it was rejected.

    THIS IS THE MECHANISM THAT REPLACES TRUST. `ask` produced the sentence; nothing about the
    sentence is verifiable. The citation is, and it is verifiable cheaply and completely: the file
    either exists in this repository or it does not, and the line either exists in that file or it
    does not. A model that invents a source loses the sentence, every time, without anybody
    noticing in the room.

    Line counts are cached per file and the number of files opened is capped, because a proposal
    with two hundred citations must not turn into two hundred stat+read calls on a client's
    laptop mid-session."""

    #: how many distinct files this pass will open to check a line number
    MAX_FILES_OPENED = 200

    def __init__(self, repo: Path) -> None:
        self._repo = repo
        self._lines: dict[str, int | None] = {}
        #: citation strings whose FILE was verified and whose LINE was not — the ceiling above was
        #: reached, or the file could not be opened. Named rather than counted, because the
        #: reader's next move is to open the one that matters.
        self.unverified_lines: list[str] = []

    def _line_count(self, rel: str) -> int | None:
        """Lines in the file, or None when the count is UNKNOWN — the file could not be read, or
        this pass has already opened `MAX_FILES_OPENED` distinct files.

        None is not "zero lines" and it is not "the line is fine": it is the absence of the
        measurement, and `anchor()` below refuses to print a `:line` it did not measure."""
        if rel in self._lines:
            return self._lines[rel]
        if len(self._lines) >= self.MAX_FILES_OPENED:
            return None
        text = _read(self._repo / rel)
        count = None if text is None else len(text.splitlines())
        self._lines[rel] = count
        return count

    def anchor(self, cites: Any) -> tuple[list[Evidence], list[str]]:
        """`(evidence that survived, citation strings that did not)`."""
        raw_list = cites if isinstance(cites, list | tuple) else [cites]
        kept: list[Evidence] = []
        rejected: list[str] = []
        for raw in raw_list[:20]:
            if not isinstance(raw, str):
                rejected.append(repr(raw))
                continue
            path, line = _split_citation(raw)
            rel = _repo_relative(self._repo, path)
            if rel is None or not (self._repo / rel).is_file():
                # SAY WHICH OF THE THREE IT IS. Every rejection used to read as "the repository
                # does not contain this", and the demoted-claim sentence says exactly that to
                # the client — while the commonest causes are a locator this parser could not
                # read and a citation naming a DIRECTORY. Both were reported as a missing file,
                # which sends a reviewer looking for a deletion that never happened (pilot,
                # 2026-08-14).
                bare = _repo_relative(self._repo, _split_citation(raw)[0].split(":")[0])
                if bare is not None and (self._repo / bare).is_dir():
                    rejected.append(f"{raw} (that is a directory — cite a file)")
                elif bare is not None and (self._repo / bare).is_file():
                    rejected.append(f"{raw} (the file is there; the line locator is unreadable)")
                else:
                    rejected.append(raw)
                continue
            count = self._line_count(rel)
            excerpt = ""
            if line is not None and count is None:
                # AN UNVERIFIABLE LINE IS NOT PUBLISHED. Measured before this branch existed:
                # once the cache reached `MAX_FILES_OPENED`, `_line_count` returned None for
                # every further file and the `and count is not None` above let the citation
                # through UNCHECKED — thirty claims citing line 500 of one-line files came back
                # as twenty anchored facts, each printing `pkg/m2xx.py:500` under a sentence, and
                # nothing anywhere said a ceiling had been reached. That is the exact output this
                # class exists to prevent, and it appears only on the large legacy repositories
                # the module was written for, where a model has enough to cite to exhaust the
                # cache. The FILE was checked and is real, so the claim survives — with the
                # citation that was actually verified, and the discarded locator named on this
                # object rather than silently dropped.
                self.unverified_lines.append(raw)
                line = None
            elif line is not None and count is not None:
                if line > count or line < 1:
                    # THE FILE IS REAL AND THE LOCATION IS NOT. This is the tell that separates a
                    # model reading a file from a model reciting a plausible path, and it is
                    # free to check.
                    rejected.append(f"{raw} (file has {count} line(s))")
                    continue
                text = _read(self._repo / rel)
                if text is not None:
                    excerpt = text.splitlines()[line - 1].strip()[:200]
            kept.append(Evidence(path=rel, line=line, excerpt=excerpt))
        return kept, rejected


def _claims(raw: Any, anchorer: _Anchorer, demoted: list[str], *,
            label: str, w: dict[str, str]) -> list[Claim]:
    """Parse one section, keeping only claims whose citations survived verification.

    A DEMOTED CLAIM IS WRITTEN IN THE CLIENT'S LANGUAGE, like everything else that reaches the
    documents. It is the line most likely to be read out loud in the room — it is where the
    platform says "the agent believes this and could not show me where" — and it arrived in
    English inside a Portuguese document until this was measured on `fx-dsk-flows`."""
    out: list[Claim] = []
    for item in (raw if isinstance(raw, list) else [])[:40]:
        if not isinstance(item, dict):
            continue
        text = str(item.get("text") or "").strip()
        if not text:
            continue
        evidence, rejected = anchorer.anchor(item.get("cites"))
        if not evidence:
            demoted.append(w["q_demoted_claim"].format(
                label=label, text=text,
                cites=", ".join(rejected) if rejected else w["q_cited_nothing"]))
            continue
        out.append(Claim(text=text, evidence=evidence, rejected_citations=rejected))
    return out


def _vocabulary(raw: Any, anchorer: _Anchorer, demoted: list[str],
                *, w: dict[str, str]) -> list[Term]:
    out: list[Term] = []
    for item in (raw if isinstance(raw, list) else [])[:60]:
        if not isinstance(item, dict):
            continue
        term = str(item.get("term") or "").strip()
        meaning = str(item.get("meaning") or "").strip()
        if not term or not meaning:
            continue
        evidence, rejected = anchorer.anchor(item.get("cites"))
        if not evidence:
            demoted.append(w["q_demoted_term"].format(
                term=term, meaning=meaning,
                cites=", ".join(rejected) if rejected else w["q_cited_nothing"]))
            continue
        out.append(Term(term=term, meaning=meaning, evidence=evidence,
                        rejected_citations=rejected))
    out.sort(key=lambda t: t.term.lower())
    return out


def _survey_questions(s: RepoSurvey, w: dict[str, str]) -> list[SurveyQuestion]:
    """The questions the DETERMINISTIC read already earns, with no model involved.

    These are the ones that hold up on their own: a module the platform knows nothing about, a
    stack it cannot read, a directory it could not open. They are also why `ask=None` is a usable
    mode — the agenda for the room exists before any token is spent."""
    out: list[SurveyQuestion] = []
    blind = [m for m in s.modules if m.purpose_is_folder_name]
    if blind:
        biggest = sorted(blind, key=lambda m: (-m.files, m.name))[:5]
        out.append(SurveyQuestion(BLIND_MODULES, w["q_blind"].format(
            n=len(blind), total=s.module_count,
            listed=", ".join(f"{m.name} ({m.files})" for m in biggest))))
    if s.unread_code_extensions:
        out.append(SurveyQuestion(UNREAD_CODE, w["q_unread_code"].format(
            exts=", ".join(s.unread_code_extensions[:8]))))
    untested = [m for m in s.modules if m.name in set(s.untested_modules)]
    if untested:
        biggest = sorted(untested, key=lambda m: (-m.files, m.name))[:5]
        out.append(SurveyQuestion(UNTESTED_MODULES, w["q_untested"].format(
            n=len(untested), listed=", ".join(m.name for m in biggest))))
    if s.unreadable_dirs:
        out.append(SurveyQuestion(UNREADABLE_DIRS, w["q_unreadable"].format(
            n=len(s.unreadable_dirs), listed=", ".join(s.unreadable_dirs[:3]))))
    if not s.entry_points:
        out.append(SurveyQuestion(NO_ENTRY_POINTS, w["q_no_entry"]))
    if s.terms_dropped:
        out.append(SurveyQuestion(DROPPED_TERMS, w["q_dropped"].format(
            listed=", ".join(s.terms_dropped[:8]))))
    return out


def propose_context(
    survey_result: RepoSurvey,
    *,
    ask: AskFn | None = None,
    language: str | None = None,
    docs_root: str | Path | None = None,
) -> ContextProposal:
    """Propose the SEMANTIC context of a surveyed repository. Writes nothing.

    `ask` is the read-only agent primitive (`agent_ask()` binds a harness into it). Passing None
    is a first-class mode, not a degraded one: the deterministic survey and the questions it earns
    are produced with zero tokens, and on a client with no harness configured yet — which is
    every client on the morning of day one — that is the whole session's material.

    EXACTLY ONE AGENT PASS. Not a loop, not a per-module fan-out. An onboarding step whose cost
    depends on the size of the client's monolith is one nobody can quote a price for, and the
    platform's own `env rehearse` design took the same decision for the same reason.

    A FAILED PASS IS NEVER AN EMPTY DOCUMENT. If the agent raises, or answers with nothing this
    module can parse, `ok` is False and `refusal` says which of the two happened — and the
    deterministic documents are still returned, because they were true before the model was asked
    and they are true after it failed.
    """
    repo = Path(survey_result.repo)
    proposal = ContextProposal(repo=survey_result.repo)
    w = _words(language)
    # ONE SOURCE, TWO VIEWS. `tracked` carries the identity; `questions` carries the text of
    # everything a reader should see, the model's and the demoted claims' included. Deriving
    # the second from the first is what stops them becoming two lists that disagree.
    proposal.tracked = _survey_questions(survey_result, w)
    proposal.questions = [q.text for q in proposal.tracked]

    if ask is not None:
        raw = ""
        try:
            raw = ask(build_prompt(survey_result, language=language))
            proposal.asked = 1
        except Exception as exc:  # noqa: BLE001 — any harness, any failure mode
            log.exception("context proposal: the agent pass failed on %s", survey_result.repo)
            proposal.ok = False
            proposal.refusal = (
                f"the read-only agent pass failed ({type(exc).__name__}: {exc}). Nothing semantic "
                f"is proposed and nothing was written. The deterministic survey below is "
                f"unaffected — it never involved the agent.")
        else:
            envelope = json_envelope(raw)
            if envelope is None:
                proposal.ok = False
                proposal.refusal = (
                    f"the agent answered {len(raw)} character(s) with no JSON object in them, so "
                    f"there is nothing to verify and nothing to publish. An unparseable answer is "
                    f"reported as a failure rather than rendered as an empty context: a document "
                    f"saying this system does nothing is a claim about the client's code, and "
                    f"this is a claim about us.")
            else:
                anchorer = _Anchorer(repo)
                demoted: list[str] = []
                proposal.what_it_does = _claims(envelope.get("does"), anchorer, demoted,
                                                label=w["l_does"], w=w)
                proposal.entities = _claims(envelope.get("entities"), anchorer, demoted,
                                            label=w["l_entities"], w=w)
                proposal.invariants = _claims(envelope.get("invariants"), anchorer, demoted,
                                              label=w["l_invariants"], w=w)
                proposal.vocabulary = _vocabulary(envelope.get("vocabulary"), anchorer, demoted,
                                                  w=w)
                # TYPE-CHECK, DO NOT TRUTH-CHECK — the rule `infer._read_circleci` already paid
                # for, in the only section that was missing it. `(x or [])[:60]` assumes a list:
                # a model answering `"questions": {...}` raised `KeyError: slice(None, 60, None)`
                # out of this function (a traceback on the screen, in the room), and
                # `"questions": "como isso funciona?"` sliced the STRING — every character became
                # its own numbered question, so the agenda document handed to the client opened
                # `1. c  2. o  3. m  4. o`. Both were measured; a failure that reads as an answer
                # is the worse of the two.
                raw_questions = envelope.get("questions")
                model_questions = [
                    q.strip() for q in (raw_questions if isinstance(raw_questions, list) else [])
                    [:60] if isinstance(q, str) and q.strip()
                ]
                # DEMOTED CLAIMS ARE QUESTIONS, and they lead: an unanchored belief is the single
                # most useful thing to put in front of a developer, because it is either the
                # answer nobody wrote down or the misunderstanding that would have shipped.
                proposal.demoted = demoted
                proposal.citations_unverified = anchorer.unverified_lines
                proposal.questions = demoted + model_questions + proposal.questions
                proposal.semantic = True

    proposal.documents = _documents(survey_result, proposal, language=language,
                                    docs_root=docs_root)
    return proposal


# ---------------------------------------------------------------------------------------------
# The documents, and the only function here that can write
# ---------------------------------------------------------------------------------------------


class ContextLayout(BaseModel):
    """Where documents go in THIS client's context repository.

    Read from the repository rather than imposed, because the second external client arrived with
    `ACM.CA.Deskline.Context` — `docs/arquitetura/`, `docs/decisoes/`, its own `DEC-001…`
    numbering — written long before it met us. Landing an `docs/architecture/overview.md` beside
    their `docs/arquitetura/visao-geral.md` is not onboarding them, it is starting a second
    documentation tree in their repository on day one."""

    architecture_dir: str = "docs/arquitetura"
    glossary_path: str = "docs/glossario.md"
    invariants_path: str = "docs/invariantes.md"
    questions_path: str = "docs/perguntas-abertas.md"
    survey_path: str = "docs/levantamento.md"
    overview_name: str = "visao-geral.md"
    #: "pt-BR" LITERALLY, because this class IS the Portuguese layout — every field above names
    #: a Portuguese file. It read `DEFAULT_LANGUAGE`, a pydantic field default frozen at import,
    #: so the day the platform's default became English this layout kept its Portuguese
    #: filenames and started rendering English prose into them: `docs/glossario.md` opening with
    #: "Glossary". The sibling below has always spelled its own language out; this one now does
    #: too (2026-08-14).
    language: str = "pt-BR"


_LAYOUT_EN = ContextLayout(
    architecture_dir="docs/architecture",
    glossary_path="docs/glossary.md",
    invariants_path="docs/invariants.md",
    questions_path="docs/open-questions.md",
    survey_path="docs/survey.md",
    overview_name="overview.md",
    language="en",
)


def context_layout(
    docs_root: str | Path | None, *, language: str | None = None
) -> ContextLayout:
    """Where to put things, preferring folders the client already has.

    `docs_root` is a CHECKOUT of the context repository, or None when there is none yet (then
    the layout follows `language`, whose default is the platform's — English since 2026-08-14,
    so a client who never declared one gets `docs/architecture/overview.md` rather than another
    deployment's mother tongue)."""
    layout = _LAYOUT_EN.model_copy() if not str(_lang(language)).lower().startswith("pt") \
        else ContextLayout()
    if docs_root is None:
        return layout
    root = Path(docs_root).expanduser()
    if not root.is_dir():
        return layout
    for candidate in ("docs/arquitetura", "docs/architecture", "docs/arch"):
        if (root / candidate).is_dir():
            layout.architecture_dir = candidate
            break
    for field, candidates in (
        ("glossary_path", ("docs/glossario.md", "docs/glossary.md")),
        ("invariants_path", ("docs/invariantes.md", "docs/invariants.md")),
        ("questions_path", ("docs/perguntas-abertas.md", "docs/open-questions.md")),
    ):
        for candidate in candidates:
            if (root / candidate).is_file():
                setattr(layout, field, candidate)
                break
    for candidate in ("visao-geral.md", "overview.md", "README.md"):
        if (root / layout.architecture_dir / candidate).is_file():
            layout.overview_name = candidate
            break
    return layout


_HEADINGS = {
    "pt": {
        "draft": "Rascunho gerado pela leitura do código — **não é documentação aprovada**",
        "correct": ("Cada afirmação cita o arquivo de onde foi lida. Corrija o que estiver "
                    "errado: o valor deste documento vem da revisão dos seus desenvolvedores, "
                    "não da leitura automática."),
        "deterministic": ("Este documento foi produzido apenas lendo arquivos — nenhum modelo "
                          "participou. É evidência, não resumo."),
        "overview": "O que este sistema faz",
        "entities": "Entidades principais",
        "entry_points": "Por onde a execução começa",
        "modules": "Módulos",
        "glossary": "Glossário do domínio",
        "invariants": "Invariantes visíveis no código",
        "questions": "Perguntas que só os desenvolvedores respondem",
        "survey": "Levantamento do repositório",
        "stacks": "Stacks encontradas",
        "client_docs": "Documentação que o cliente já escreveu",
        "client_docs_none": ("nenhuma encontrada — o levantamento abaixo veio só do código"),
        "client_docs_note": ("Leia estes ANTES de concluir qualquer coisa a partir do código. "
                             "Onde eles discordarem do que o código faz, diga as duas coisas e "
                             "pergunte — não escolha em silêncio."),
        "client_docs_more": "(+{n} não listados)",
        "tests": "Testes",
        "hot": "Onde o trabalho realmente acontece",
        "hot_note": ("Isto vem do log do próprio repositório, não do código. Comece por aqui: um "
                     "módulo grande que ninguém toca há anos vale menos do que o arquivo que seis "
                     "pessoas mexeram no mês passado."),
        "hot_never": ("o histórico não foi lido nesta passagem — nada aqui diz que o repositório é "
                      "parado, apenas que ninguém olhou"),
        "hot_unavailable": "o histórico NÃO pôde ser lido: {why}",
        "hot_quiet": "nenhum commit na janela de {days} dias",
        "hot_window": "janela: {days} dias, a partir de {since} · commits lidos: {n}",
        "hot_truncated": "  (o teto de commits foi atingido — isto é a parte mais recente)",
        "hot_risk": "Áreas que mudam e que NENHUM teste nomeia",
        "hot_risk_note": ("Cada metade disto já era conhecida; o que faltava era cruzá-las. Uma "
                          "área que ninguém nomeia é banal num canto que ninguém toca — a mesma "
                          "área no caminho de cada mudança é onde uma suíte verde prova menos. "
                          "ATENÇÃO: nomear não é cobrir. Isto diz que ninguém acharia os testes "
                          "dela olhando, não que o código não seja exercitado."),
        "hot_risk_none": ("nenhuma — toda área que mudou na janela tem ao menos um teste que a "
                          "nomeia"),
        "hot_risk_unknown": ("não dá para dizer: sem o histórico, nada distingue uma área que "
                             "muda toda semana de uma parada desde 2019"),
        "t_changes": "mudanças em arquivos",
        "t_order_churn": "ordenados por quanto mudam (o histórico foi lido). "
                         "'mudanças em arquivos' NÃO é contagem de commits: um commit que "
                         "mexe em cinco arquivos do módulo conta cinco",
        "t_order_size": "ordenados por tamanho — o histórico não foi lido, então isto NÃO diz "
                        "onde o trabalho acontece",
        "t_file": "arquivo",
        "t_commits": "commits",
        "t_people": "pessoas",
        "t_last": "último",
        "t_tickets": "itens de trabalho",
        "blind": "O que este levantamento NÃO enxergou",
        "nothing": "_Nada foi proposto aqui — veja as perguntas em aberto._",
        "terms_seen": "Palavras que o código repete (candidatas a verbete)",
        "none_found": "nenhum encontrado",
        "none_detected": "nenhuma detectada",
        "no_preset": "  — não existe preset para ela",
        "s_repository": "repositório",
        "s_modules": "módulos",
        "s_showing": "mostrando",
        "s_files_read": ("arquivos-fonte lidos pelo mapa estrutural: {read}; arquivos que ele "
                         "não lê: {unread}"),
        "s_degraded": "módulos cuja única descrição é o próprio nome da pasta: {n}",
        "s_test_files": "arquivos de teste: {n}",
        "s_more": "… mais de {n} encontrados; os demais não estão listados",
        "s_more_modules": "mais {n}",
        "t_module": "módulo",
        "t_files": "arquivos",
        "t_tests": "testes",
        "t_knows": "o que a plataforma sabe sobre ele",
        "t_knows_nothing": "— nada: sem README, sem docstring",
        "s_no_terms": "nenhuma: nenhuma palavra aparece em mais de um lugar",
        "s_term_line": "{n}×, {m} módulo(s), ex. {where}",
        "s_unread_ext": "extensões que o mapa estrutural não lê: ",
        "s_probably_code": "dessas, as que provavelmente são código: ",
        "s_unreadable": "diretórios que não puderam ser abertos: ",
        "s_walk_clean": "nenhum — a varredura foi completa",
        "s_truncated": ("**a varredura atingiu o próprio teto** — este levantamento não cobre o "
                        "repositório inteiro, e isso é um limite nosso, não um achado sobre o "
                        "código"),
        "s_untested": "módulos que nenhum arquivo de teste nomeia: ",
        "s_untested_note": ("(correspondência por NOME, não cobertura: uma suíte que exercita um "
                            "módulo sem nomear seus arquivos aparece aqui como ausente)"),
        "s_stacks_unread": ("**não foi possível ler** — a leitura de stacks/CI não terminou deste "
                            "lado, então isto NÃO quer dizer que o repositório não tenha stack "
                            "nenhuma"),
        "s_no_manifest": ("a leitura de manifesto não terminou, então nenhum comando vindo do CI "
                          "aparece acima"),
        "s_ci_read": "arquivos de CI/build lidos: ",
        "s_none": "nenhum",
        "q_cited_nothing": "nada",
        "q_demoted_claim": ("[{label}] o agente propôs: “{text}” — mas citou {cites}, que este "
                            "repositório não contém. Isso é verdade?"),
        "q_demoted_term": ("[glossário] o agente propôs “{term}” = “{meaning}” — mas citou "
                           "{cites}, que este repositório não contém. O que {term} significa "
                           "aqui?"),
        "q_blind": ("{n} de {total} módulo(s) não têm README nem docstring, então tudo o que a "
                    "plataforma “sabe” sobre eles é o nome da pasta — a começar por {listed}. Em "
                    "uma frase cada: para que servem?"),
        "q_unread_code": ("este repositório tem arquivos {exts} que o mapa estrutural não lê — a "
                          "lógica importante está em algum deles, e qual você mostraria primeiro "
                          "a um desenvolvedor novo?"),
        "q_untested": ("nenhum arquivo de teste nomeia {n} módulo(s) — os maiores primeiro: "
                       "{listed}. Eles são testados em algum lugar que esta leitura não alcança "
                       "(uma suíte de integração, outro repositório), ou realmente não têm "
                       "cobertura?"),
        "q_unreadable": ("{n} diretório(s) não puderam ser abertos ({listed}) — tudo o que está "
                         "sob eles está ausente de todas as afirmações acima, e isso é um "
                         "problema de permissão do nosso lado, não um achado sobre o código de "
                         "vocês."),
        "q_no_entry": ("nenhum ponto de entrada foi encontrado — nenhum console script, nenhum "
                       "ENTRYPOINT de container, nenhum `Program.cs`, nenhum handler. Como este "
                       "código é iniciado de fato, e por quê?"),
        "q_dropped": ("o vocabulário abaixo exclui palavras que esta plataforma trata como "
                      "encanamento, e ela descartou {listed} do código de vocês. Se alguma delas "
                      "é uma palavra que o negócio realmente usa, diga — o filtro é nosso."),
        "l_does": "o que faz",
        "l_entities": "entidades",
        "l_invariants": "invariantes",
    },
    "en": {
        "draft": "Draft produced by reading the code — **not approved documentation**",
        "correct": ("Every statement cites the file it was read from. Correct what is wrong: the "
                    "value of this document comes from your developers' review, not from the "
                    "automated read."),
        "deterministic": ("This document was produced by reading files only — no model was "
                          "involved. It is evidence, not a summary."),
        "overview": "What this system does",
        "entities": "Main entities",
        "entry_points": "Where execution begins",
        "modules": "Modules",
        "glossary": "Domain glossary",
        "invariants": "Invariants visible in the code",
        "questions": "Questions only the developers can answer",
        "survey": "Repository survey",
        "stacks": "Stacks found",
        "client_docs": "Documentation the client already wrote",
        "client_docs_none": "none found — the survey below came from the code alone",
        "client_docs_note": ("Read these BEFORE concluding anything from the code. Where they "
                             "disagree with what the code does, say both and ask — do not choose "
                             "in silence."),
        "client_docs_more": "(+{n} not listed)",
        "tests": "Tests",
        "hot": "Where the work actually lands",
        "hot_note": ("This comes from the repository's own log, not from its code. Start here: a "
                     "large module nobody has touched for years is worth less than the file six "
                     "people changed last month."),
        "hot_never": ("the history was not read on this pass — nothing here says the repository is "
                      "quiet, only that nobody looked"),
        "hot_unavailable": "the history could NOT be read: {why}",
        "hot_quiet": "no commits in a {days}-day window",
        "hot_window": "window: {days} days, from {since} · commits read: {n}",
        "hot_truncated": "  (the commit ceiling was reached — this is the most recent part)",
        "hot_risk": "Areas that change and that NO test names",
        "hot_risk_note": ("Both halves of this were already known; what was missing was crossing "
                          "them. An area nothing names is unremarkable in a corner nobody "
                          "touches — the same area in the path of every change is where a green "
                          "suite proves least. CAREFUL: naming is not covering. This says nobody "
                          "could find its tests by looking, not that the code is unexercised."),
        "hot_risk_none": ("none — every area that changed in the window has at least one test "
                          "naming it"),
        "hot_risk_unknown": ("cannot be said: without the history nothing separates an area that "
                             "changes weekly from one untouched since 2019"),
        "t_changes": "file changes",
        "t_order_churn": "ordered by how much they change (the history was read). 'file "
                         "changes' is NOT a commit count: one commit touching five of the "
                         "module's files counts five",
        "t_order_size": "ordered by size — the history was not read, so this does NOT say where "
                        "the work happens",
        "t_file": "file",
        "t_commits": "commits",
        "t_people": "people",
        "t_last": "last",
        "t_tickets": "work items",
        "blind": "What this survey did NOT see",
        "nothing": "_Nothing proposed here — see the open questions._",
        "terms_seen": "Words the code keeps repeating (glossary candidates)",
        "none_found": "none found",
        "none_detected": "none detected",
        "no_preset": "  — no preset ships for it",
        "s_repository": "repository",
        "s_modules": "modules",
        "s_showing": "showing",
        "s_files_read": ("source files read by the structural map: {read}; files it does not "
                         "read: {unread}"),
        "s_degraded": "modules whose only description is their own folder name: {n}",
        "s_test_files": "test files: {n}",
        "s_more": "… more than {n} found; the rest are not listed",
        "s_more_modules": "{n} more",
        "t_module": "module",
        "t_files": "files",
        "t_tests": "tests",
        "t_knows": "what the platform knows about it",
        "t_knows_nothing": "— nothing: no README, no docstring",
        "s_no_terms": "none: no word appears in more than one place",
        "s_term_line": "{n}×, {m} module(s), e.g. {where}",
        "s_unread_ext": "extensions the structural map does not read: ",
        "s_probably_code": "of those, ones that are probably code: ",
        "s_unreadable": "directories that could not be opened: ",
        "s_walk_clean": "none — the walk completed",
        "s_truncated": ("**the walk hit its own ceiling** — this survey does not cover the whole "
                        "repository, and that is a limit of ours, not a finding about the code"),
        "s_untested": "modules nothing names in a test file: ",
        "s_untested_note": ("(name matching, NOT coverage: a suite that exercises a module "
                            "without naming its files reads as absent here)"),
        "s_stacks_unread": ("**could not be read** — the stack/CI read did not complete on our "
                            "side, so this does NOT mean the repository has no stack"),
        "s_no_manifest": ("the manifest read did not complete, so no CI-derived command appears "
                          "above"),
        "s_ci_read": "CI/build files read: ",
        "s_none": "none",
        "q_cited_nothing": "nothing",
        "q_demoted_claim": ("[{label}] the agent proposed: “{text}” — but cited {cites}, which "
                            "this repository does not contain. Is it true?"),
        "q_demoted_term": ("[glossary] the agent proposed “{term}” = “{meaning}” — but cited "
                           "{cites}, which this repository does not contain. What does {term} "
                           "mean here?"),
        "q_blind": ("{n} of {total} module(s) have no README and no docstring, so everything the "
                    "platform “knows” about them is their folder name — starting with {listed}. "
                    "In one sentence each: what are they for?"),
        "q_unread_code": ("this repository holds {exts} files that the structural map does not "
                          "read — is the important logic in any of them, and which one would you "
                          "show a new developer first?"),
        "q_untested": ("nothing names {n} module(s) in a test file — biggest first: {listed}. Are "
                       "they tested somewhere this pass cannot see (an integration suite, a "
                       "separate repository), or genuinely uncovered?"),
        "q_unreadable": ("{n} director(y/ies) could not be opened ({listed}) — anything under "
                         "them is absent from every statement above, and that is a permissions "
                         "problem on our side, not a finding about your code."),
        "q_no_entry": ("no entry point was found — no console script, no container ENTRYPOINT, no "
                       "`Program.cs`, no handler. How is this code actually started, and by "
                       "what?"),
        "q_dropped": ("the vocabulary below excludes words this platform treats as plumbing, and "
                      "it dropped {listed} from your code. If any of those is a word your "
                      "business actually uses, say so — the filter is ours."),
        "l_does": "what it does",
        "l_entities": "entities",
        "l_invariants": "invariants",
    },
}


def _lang(language: str | None) -> str:
    """The language to speak: the caller's, or the platform's default READ NOW.

    Late binding on purpose. `language: str = DEFAULT_LANGUAGE` in a signature freezes the
    module's value at import time, so a deployment that changes the default — or a test that
    declares one — is silently ignored by every function already defined. Measured the day the
    product's default became English: an autouse fixture setting pt-BR changed nothing at all
    (2026-08-14)."""
    return language or DEFAULT_LANGUAGE


def _words(language: str | None) -> dict[str, str]:
    return _HEADINGS["pt"] if str(_lang(language)).lower().startswith("pt") else _HEADINGS["en"]


def _cite(evidence: list[Evidence]) -> str:
    return ", ".join(f"`{e.locator}`" for e in evidence) or "`?`"


def render_survey(survey_result: RepoSurvey, *, for_prompt: bool = False,
                  language: str | None = None) -> str:
    """The deterministic survey as markdown — the body of the survey document AND the evidence
    block of the prompt. One renderer, so the agent is shown exactly what the client is shown; two
    would drift, and the day they drift the agent is answering about a repository nobody saw.

    EVERY SENTENCE COMES OUT OF `_HEADINGS`, including the prose, and that is not tidiness. This
    document is written into the CLIENT's repository. `roles.py` already records what a mixed
    document costs — *"an English block between two Portuguese ones reads as two different people
    wrote the ticket"* — and a first version of this renderer had Portuguese headings over English
    body text, measured on `fx-dsk-flows`. A deliverable a client is meant to keep cannot be half
    in a language nobody there asked for."""
    w = _words(language)
    s = survey_result
    out: list[str] = []
    if not for_prompt:
        out += [f"# {w['survey']}", "", f"> {w['deterministic']}", ""]
    out.append(f"- {w['s_repository']}: `{s.repo}`")
    out.append(f"- {w['s_modules']}: {s.module_count}"
               + (f" ({w['s_showing']} {len(s.modules)})" if s.modules_truncated else ""))
    out.append("- " + w["s_files_read"].format(read=s.files_read, unread=s.files_unread))
    out.append("- " + w["s_degraded"].format(n=s.degraded_purposes))
    out.append("- " + w["s_test_files"].format(n=s.test_files))
    out.append("")

    # THE CLIENT'S OWN DOCUMENTATION, READ FIRST. The field carrying it has always said so —
    # "the first thing a reverse-engineering session should read, and the last thing it should
    # overwrite" — and until now NOTHING read it: `survey` collected the paths and neither this
    # renderer nor `build_prompt` mentioned them, so every backfill was code-only and a client
    # who had written down how their system works watched it be re-derived from scratch.
    #
    # THE INSTRUCTION MATTERS MORE THAN THE LIST. A disagreement between a document and the code
    # is the most valuable thing this pass can find, and the failure mode is an agent quietly
    # picking the code because the code is what it can see. So the note says: say both, and ask.
    out.append(f"## {w['client_docs']}")
    if not s.existing_docs:
        out.append(f"- {w['client_docs_none']}")
    else:
        out.append(f"> {w['client_docs_note']}")
        out.append("")
        for path in s.existing_docs:
            out.append(f"- `{path}`")
        if s.existing_docs_truncated:
            out.append(f"- {w['client_docs_more'].format(n='…')}")
    out.append("")

    out.append(f"## {w['stacks']}")
    if s.manifest is None:
        # NONE IS NOT EMPTY, IN THE ARTEFACT THE CLIENT KEEPS. `stacks` is populated from the
        # manifest read; when that read fails the list is `[]`, and `[]` printed "none detected"
        # — a measurement about the CLIENT'S repository, produced by a failure of OURS. The
        # object was already honest (`manifest is None` says so, and is documented as saying so);
        # this is the document catching up with it.
        out.append(f"- {w['s_stacks_unread']}")
    elif not s.stacks:
        out.append(f"- {w['none_detected']}")
    for sighting in s.stacks:
        cite = sighting.evidence[0].locator if sighting.evidence else "?"
        note = "" if sighting.expressible else w["no_preset"]
        out.append(f"- **{sighting.stack}** ({sighting.confidence}) `{cite}`{note}")
    out.append("")

    out.append(f"## {w['entry_points']}")
    if not s.entry_points:
        out.append(f"- {w['none_found']}")
    for entry in s.entry_points[:30]:
        out.append(f"- `{entry.target}` — {entry.kind} `{entry.evidence.locator}`")
    if s.entry_points_truncated:
        out.append("- " + w["s_more"].format(n=_MAX_ENTRY_POINTS))
    out.append("")

    # WHERE THE WORK LANDS, BEFORE THE MODULE TABLE. Ordering is the message: the module table is
    # sorted by SIZE, and size is the wrong question on a legacy repository — the biggest module
    # is routinely the one nobody has opened since 2019. This section answers "where would a
    # change go" and it is put first so it is read first.
    out.append(f"## {w['hot']}")
    h = s.history
    if h is None:
        # NOT "this repository is quiet". Nobody looked, and a reader who cannot tell those apart
        # will draw the same conclusion from both.
        out.append(f"- {w['hot_never']}")
    elif not h.usable:
        out.append("- " + w["hot_unavailable"].format(why=h.unavailable))
    else:
        out.append("- " + w["hot_window"].format(days=h.window_days, since=h.since,
                                                 n=h.commits_read))
        if h.truncated:
            out.append(w["hot_truncated"])
        hot = change_surface(h, limit=25)
        if not hot:
            out.append("- " + w["hot_quiet"].format(days=h.window_days))
        else:
            out.append("")
            out.append(f"> {w['hot_note']}")
            out.append("")
            out.append(f"| {w['t_file']} | {w['t_commits']} | {w['t_people']} | {w['t_last']} "
                       f"| {w['t_tickets']} |")
            out.append("| --- | ---: | ---: | --- | --- |")
            for row in hot:
                refs = ", ".join(f"`{t}`" for t in row.tickets[:4]) or "—"
                out.append(f"| `{row.path}` | {row.commits} | {row.author_count} "
                           f"| {row.last_touched or '?'} | {refs} |")
    out.append("")

    # THE SENTENCE THE SURVEY COULD NOT SAY. Both halves were already here and both were correct;
    # nothing crossed them, so the most-changed undefended area of a codebase read exactly like the
    # quietest one. It is its own section rather than a column because a reader scanning a table
    # infers nothing, and this is the one finding a factory about to start work must not miss.
    out.append(f"## {w['hot_risk']}")
    if h is None or not h.usable:
        # An empty list here would mean "every changed area is named by a test", which is a
        # measurement. Without the history there is no measurement, only an absence.
        out.append(f"- {w['hot_risk_unknown']}")
    else:
        exposed = s.changed_and_named_by_no_test
        if not exposed:
            out.append(f"- {w['hot_risk_none']}")
        else:
            out.append("")
            out.append(f"> {w['hot_risk_note']}")
            out.append("")
            out.append(f"| {w['t_module']} | {w['t_changes']} | {w['t_people']} "
                       f"| {w['t_last']} |")
            out.append("| --- | ---: | ---: | --- |")
            for mod in exposed[:20]:
                out.append(f"| `{mod.name}` | {mod.file_changes} | {mod.author_count} "
                           f"| {mod.last_touched or '?'} |")
            if len(exposed) > 20:
                out.append("| … | | | " + w["s_more_modules"].format(n=len(exposed) - 20) + " |")
    out.append("")

    out.append(f"## {w['modules']}")
    out.append("")
    # ORDERED BY CHURN WHERE THERE IS A LOG, AND THE ORDERING IS STATED. This table is capped at
    # 40, so its sort decides which 40 of a large repository a reader ever sees — and by size the
    # answer is routinely the forty nobody has opened in years. Which ordering is in force is said
    # out loud, because a reader who assumes the wrong one draws exactly the wrong conclusion from
    # a correct table.
    ordered = s.busiest_modules if (h and h.usable) else s.biggest_modules
    out.append(f"_{w['t_order_churn'] if (h and h.usable) else w['t_order_size']}_")
    out.append("")
    churn_column = bool(h and h.usable)
    head = f"| {w['t_module']} |" + (f" {w['t_changes']} |" if churn_column else "")
    out.append(head + f" {w['t_files']} | {w['t_tests']} | {w['t_knows']} |")
    out.append("| --- |" + (" ---: |" if churn_column else "") + " ---: | ---: | --- |")
    for mod in ordered[:40]:
        tests = mod.tests_inside + len(mod.tested_by)
        # THE TELL, and it is the point of the table: a purpose that is only the folder name is
        # printed as the empty statement it is, not as a description.
        knows = w["t_knows_nothing"] if mod.purpose_is_folder_name \
            else mod.purpose.replace("|", "\\|")
        row = f"| `{mod.name}` |" + (f" {mod.file_changes} |" if churn_column else "")
        out.append(row + f" {mod.files} | {tests} | {knows} |")
    if s.module_count > 40:
        pad = "| … | |" if churn_column else "| … |"
        out.append(pad + " | | " + w["s_more_modules"].format(n=s.module_count - 40) + " |")
    out.append("")

    out.append(f"## {w['terms_seen']}")
    if not s.terms:
        out.append(f"- {w['s_no_terms']}")
    for term in s.terms[:30]:
        where = ", ".join(f"`{e.path}`" for e in term.evidence[:2]) or "?"
        out.append(f"- **{term.term}** — " + w["s_term_line"].format(
            n=term.occurrences, m=len(term.modules), where=where))
    out.append("")

    out.append(f"## {w['blind']}")
    out.append("- " + w["s_unread_ext"]
               + (", ".join(f"`{e.suffix or '?'}` ×{e.files}"
                            for e in s.unread_extensions[:12]) or w["s_none"]))
    out.append("- " + w["s_probably_code"]
               + (", ".join(f"`{x}`" for x in s.unread_code_extensions) or w["s_none"]))
    out.append("- " + w["s_unreadable"]
               + (", ".join(f"`{d}`" for d in s.unreadable_dirs) or w["s_walk_clean"]))
    if s.walk_truncated:
        out.append(f"- {w['s_truncated']}")
    out.append("- " + w["s_untested"]
               + (", ".join(f"`{n}`" for n in s.untested_modules[:15]) or w["s_none"]))
    out.append(f"  {w['s_untested_note']}")
    if s.manifest is None:
        out.append(f"- {w['s_no_manifest']}")
    else:
        out.append("- " + w["s_ci_read"]
                   + (", ".join(f"`{f}`" for f in s.manifest.ci_files_read) or w["none_found"]))
    return "\n".join(out) + "\n"


def _doc_header(survey_result: RepoSurvey, w: dict[str, str]) -> list[str]:
    return [
        f"> {w['draft']}.",
        f"> {w['correct']}",
        f"> _(`{survey_result.repo}`)_",
        "",
    ]


def _documents(
    survey_result: RepoSurvey,
    proposal: ContextProposal,
    *,
    language: str,
    docs_root: str | Path | None,
) -> list[ContextDocument]:
    """The files this session proposes for the context repository. Nothing is written here.

    `.openfactory/product.yaml` is DELIBERATELY NOT among them. `product/onboard.py::plan` already
    owns
    that file — it merges rather than replaces, honours a `requirements_dir` the client already
    chose, and refuses a folder that already holds somebody else's numbering. A second writer of
    the same file is how two tools start disagreeing about which repository a product's
    requirements live in, which ADR-0019 calls a client isolation breach."""
    layout = context_layout(docs_root, language=language)
    w = _words(layout.language)
    root = Path(docs_root).expanduser() if docs_root is not None else None
    docs: list[ContextDocument] = []

    def add(path: str, title: str, body: list[str], kind: str, from_model: bool) -> None:
        # `or is_symlink()` for the same reason `write_documents` needs it, and so the two agree:
        # a report that says "new" about a path the writer will skip sends a reader looking for a
        # file that was never going to be created.
        exists = None if root is None else ((root / path).exists() or (root / path).is_symlink())
        docs.append(ContextDocument(path=path, title=title, body="\n".join(body).rstrip() + "\n",
                                    kind=kind, from_model=from_model, exists=exists))

    # 1. The survey. Costs nothing, involves no model, and is the document a client can keep even
    #    if they walk away from everything else in the room.
    add(layout.survey_path, w["survey"], [render_survey(survey_result, language=layout.language)],
        "survey", from_model=False)

    # 2. The overview: what it does + entities + where it starts.
    overview = [f"# {w['overview']}", ""] + _doc_header(survey_result, w)
    if proposal.what_it_does:
        for claim in proposal.what_it_does:
            overview.append(f"- {claim.text} {_cite(claim.evidence)}")
    else:
        overview.append(w["nothing"])
    overview += ["", f"## {w['entities']}", ""]
    if proposal.entities:
        overview += [f"- {c.text} {_cite(c.evidence)}" for c in proposal.entities]
    else:
        overview.append(w["nothing"])
    overview += ["", f"## {w['entry_points']}", ""]
    if survey_result.entry_points:
        overview += [f"- `{e.target}` — {e.kind} (`{e.evidence.locator}`)"
                     for e in survey_result.entry_points[:30]]
    else:
        overview.append(f"- {w['none_found']}")
    add(f"{layout.architecture_dir}/{layout.overview_name}", w["overview"], overview,
        "overview", from_model=bool(proposal.what_it_does or proposal.entities))

    # 3. The glossary — the reason a virtual PO can write a requirement that means something here.
    glossary = [f"# {w['glossary']}", ""] + _doc_header(survey_result, w)
    if proposal.vocabulary:
        for term in proposal.vocabulary:
            glossary.append(f"- **{term.term}** — {term.meaning} {_cite(term.evidence)}")
    else:
        glossary.append(w["nothing"])
    if survey_result.terms:
        glossary += ["", f"## {w['terms_seen']}", ""]
        glossary += [
            f"- `{t.term}` — " + w["s_term_line"].format(
                n=t.occurrences, m=len(t.modules),
                where=", ".join(f"`{e.path}`" for e in t.evidence[:2]) or "?")
            for t in survey_result.terms[:30]]
    add(layout.glossary_path, w["glossary"], glossary, "glossary",
        from_model=bool(proposal.vocabulary))

    # 4. The invariants.
    invariants = [f"# {w['invariants']}", ""] + _doc_header(survey_result, w)
    if proposal.invariants:
        invariants += [f"- {c.text} {_cite(c.evidence)}" for c in proposal.invariants]
    else:
        invariants.append(w["nothing"])
    add(layout.invariants_path, w["invariants"], invariants, "invariants",
        from_model=bool(proposal.invariants))

    # 5. The questions. THE AGENDA — and the one document that is more valuable when it is longer.
    questions = [f"# {w['questions']}", ""] + _doc_header(survey_result, w)
    if proposal.questions:
        questions += [f"{i}. {q}" for i, q in enumerate(proposal.questions, start=1)]
    else:
        questions.append("- none")
    add(layout.questions_path, w["questions"], questions, "questions",
        from_model=proposal.semantic)
    return docs


class WriteOutcome(BaseModel):
    """What `write_documents` did, or refused to do."""

    #: repo-relative paths actually created
    wrote: list[str] = Field(default_factory=list)
    #: paths left untouched because a file was already there. NEVER overwritten.
    skipped: list[str] = Field(default_factory=list)
    #: paths that could not be written, with the reason. `[]` = every attempt succeeded.
    failed: list[str] = Field(default_factory=list)
    #: non-empty means nothing at all was attempted, and this says why
    refusal: str = ""


def write_documents(
    proposal: ContextProposal, docs_root: str | Path, *, consent: bool = False
) -> WriteOutcome:
    """Write the proposed documents into a CHECKOUT of the context repository.

    TWO GATES, and both were paid for elsewhere in this platform.

    `consent=False` refuses. This module proposes; a caller decides. Slice 1 took the same
    decision for `.openfactory/project.yaml` and it is the reason a client can be shown a proposal
    without wondering what it just did to their repository.

    An existing path is SKIPPED, never overwritten, even with consent. The context repository
    belongs to the client — `product/onboard.py` says it in the same words, after a client
    arrived with a context repo it had written long before it met us. A tool that tidies somebody
    else's repository on first contact has not onboarded them, it has overwritten them.
    """
    outcome = WriteOutcome()
    if not consent:
        outcome.refusal = (
            "nothing was written: `write_documents` requires `consent=True`. This module proposes "
            "documents about a client's own codebase, and the decision to put them in their "
            "repository is theirs to make out loud, not a side effect of producing them.")
        return outcome
    if not proposal.documents:
        outcome.refusal = (
            "nothing was written: the proposal carries no documents at all. That is a defect in "
            "the proposal, not an empty repository — the deterministic survey document is "
            "produced unconditionally, so its absence means something upstream failed.")
        return outcome

    root = Path(docs_root).expanduser()
    if not root.is_dir():
        outcome.refusal = (
            f"nothing was written: {root} is not a directory. This function writes into a CHECKOUT "
            f"of the context repository; it does not clone one, and it does not create one.")
        return outcome

    for doc in proposal.documents:
        target = root / doc.path
        # `is_symlink()` AS WELL AS `exists()`, because a BROKEN symlink is a path that exists on
        # disk and about which `exists()` answers False — it follows the link. Measured: with a
        # dangling `docs/glossario.md -> ../../fora.md` in the checkout, `write_text` followed the
        # link and put 662 bytes OUTSIDE the repository while the outcome reported
        # `wrote: docs/glossario.md`. Two promises broken at once (writes stay inside the
        # checkout; the outcome says where the bytes went), and a broken relative symlink is
        # ordinary in a legacy repository whose docs were moved years ago — no attacker needed.
        if target.exists() or target.is_symlink():
            outcome.skipped.append(doc.path)
            continue
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(doc.body, encoding="utf-8")
            outcome.wrote.append(doc.path)
        except OSError as exc:
            # A WRITE THAT FAILED MUST NOT LOOK LIKE ONE THAT SUCCEEDED. `box_prove.save` swallowed
            # exactly this `OSError` and returned the path anyway, so `openfactory box prove`
            # printed
            # "recorded at …" over a file that was never created — card #99 §0 measured it. Named
            # here, in the outcome, and the caller can see it without reading a log.
            outcome.failed.append(f"{doc.path}: {exc}")
    return outcome


def render_context_report(proposal: ContextProposal, *, language: str | None = None) -> str:
    """What a human sees after a proposal run: what is proposed, what was demoted and why, and
    what still has to be asked. Deliberately no colour — this is screen-shared and pasted."""
    w = _words(language)
    out = [f"context proposal · {proposal.repo}"]
    if not proposal.ok:
        out += ["", f"REFUSED: {proposal.refusal}", ""]
    elif not proposal.semantic:
        out += ["", "DETERMINISTIC ONLY — no agent pass was requested, so nothing below was "
                    "written by a model. Zero tokens spent.", ""]
    else:
        out += ["", f"{proposal.asked} agent pass(es) spent.", ""]

    for title, claims in ((w["overview"], proposal.what_it_does),
                          (w["entities"], proposal.entities),
                          (w["invariants"], proposal.invariants)):
        out.append(f"{title} ({len(claims)})")
        for claim in claims:
            out.append(f"  · {claim.text}")
            out.append(f"      {_cite(claim.evidence)}")
        if not claims:
            out.append("  (none)")
        out.append("")

    out.append(f"{w['glossary']} ({len(proposal.vocabulary)})")
    for term in proposal.vocabulary:
        out.append(f"  · {term.term}: {term.meaning}")
        out.append(f"      {_cite(term.evidence)}")
    if not proposal.vocabulary:
        out.append("  (none)")
    out.append("")

    if proposal.demoted:
        out.append(f"DEMOTED — the agent said these and could not anchor them, so they are "
                   f"questions, not sentences ({len(proposal.demoted)})")
        for entry in proposal.demoted:
            out.append(f"  · {entry}")
        out.append("")

    if proposal.citations_unverified:
        # A CEILING OF OURS IS AN OPERATOR'S PROBLEM, NOT THE CLIENT'S. It never reaches the
        # documents — the claims there carry the citation that WAS verified — but it must reach
        # the person running the session, because it is the one thing here that silently makes
        # the verification weaker than the prompt promised the model it would be.
        out.append(f"LINES NOT CHECKED — the file was verified and the line was not (this pass "
                   f"opens at most {_Anchorer.MAX_FILES_OPENED} distinct files, or the file "
                   f"could not be opened). The claims stand, citing the file only "
                   f"({len(proposal.citations_unverified)})")
        for entry in proposal.citations_unverified[:20]:
            out.append(f"  · {entry}")
        out.append("")

    out.append(f"{w['questions']} ({len(proposal.questions)})")
    for question in proposal.questions:
        out.append(f"  · {question}")
    out.append("")

    out.append("DOCUMENTS PROPOSED (nothing was written)")
    for doc in proposal.documents:
        mark = {True: "already exists — would be SKIPPED", False: "new", None: "not checked"}[
            doc.exists]
        origin = "agent + verified citations" if doc.from_model else "deterministic, zero tokens"
        out.append(f"  {doc.path:<40} {origin}; {mark}")
    return "\n".join(out) + "\n"
