"""Read a repository that already exists and PROPOSE what its manifest should say.

Everything the platform had before this module VERIFIES. `doctor` checks a manifest the client
already wrote, `conformance` grades it, `box prove` runs its commands. On a greenfield project
that is the whole job: somebody types four lines and the platform tells them whether the lines
are true. On fifteen years of legacy it is the wrong half of the problem — the hard part is not
verifying `validate.test`, it is FINDING it among four candidates, three of which only work on
one developer's laptop. The product owner, opening card #99:

    *"a large share of our clients will be LEGACY continuation... starting a project from
    scratch, all neat, is a happy path but it is not the reality."*

So this module proposes, and something else decides what to do with the proposal.

WHAT IT MAY TOUCH, and the boundary is the design
-------------------------------------------------
It reads files. That is the entire contract:

  * it never runs the client's commands — not `pytest`, not `dotnet restore`, not `make`. Running
    a legacy suite can truncate a shared dev database (card #99 §4.1, attack 2); a proposal must
    be safe to produce on the client's laptop, in the room, before anybody has agreed to anything.
  * it never touches the network. No clone, no API call, no `git fetch`.
  * it does not even shell out to `git`: `base_branch` is read out of `.git/HEAD` and
    `.git/refs/remotes/origin/HEAD` as text, so the answer carries a `file:line` like every other
    answer, and so `test_infer_never_runs_a_command_and_never_opens_a_socket` can forbid
    `subprocess` outright and have that forbid mean something.
  * it writes nothing. Not `.openfactory/project.yaml`, not a report file. It returns an object.

Same repository state → same proposal, byte for byte. Every list is sorted with an explicit key;
nothing depends on `os.walk` order. A proposal you cannot diff against last week's is a proposal
nobody can review.

THE THREE TIERS, which are the product
--------------------------------------
A field here is not a string. It is a value, where that value was read, and how much of it we
made up:

    observed   read verbatim out of a file the client wrote. Their CI runs this line; it passes
               on a machine that is not anybody's laptop. This is the strongest thing a first
               pass can find and it is the tier this module exists to maximise.
    inferred   a convention this stack implies, anchored to a marker we DID read (`[tool.pytest.
               ini_options]` is in their pyproject, so `pytest` is their runner — but the exact
               invocation is ours, not theirs).
    unknown    NOT GUESSED. The field is left for a human and it says so, in words, with the
               question a human has to answer.

The third tier is the one that earns trust in the room. A proposal that quietly guesses is how a
client stops believing the other two — and it is exactly the failure
`openfactory/policy/conformance.py`
already ships one instance of, where the printed remedy (`stack: security-oss`) is not expressible
in the schema it is a remedy for.

WHY NOT `brownfield.py`'s TIERS (`asked` / `tested` / `code`)
-------------------------------------------------------------
Card #99 §5.2 proposed reusing them, and they are the right three for the question that module
asks — *"where did this REQUIREMENT come from, and may we promise it?"* — where `asked` beats
`tested` because a person with a name wanted it. This module asks a different question: *"did we
read this command, or derive it?"* There is no `asked` here (nobody has been interviewed yet;
`env interview` is the next slice) and `tested` is meaningless for a build command. Borrowing the
labels would have made two different questions look like one, which is how a vocabulary starts
lying. `observed` maps cleanly onto `brownfield.CODE`-with-provenance if a caller ever needs to
join the two.

THE RICHEST SOURCE IS THE CLIENT'S OWN CI, and it is the one nobody thinks to read
----------------------------------------------------------------------------------
A legacy repo has `.github/workflows/*.yml`, `azure-pipelines.yml`, `.gitlab-ci.yml`, a Makefile,
a Dockerfile. Those files contain the REAL commands — the ones that actually pass, on a clean
machine, written by the people who own the code. They beat any convention we could guess, and the
gap is measurable: on `fx-ado` the CI hands over `python -m pytest -q` verbatim; convention alone
would have proposed `pytest`, which is not what that team runs.

Ranking, low wins, and the reason is *which machine has it already passed on*:

    0  CI that runs on pull request — the gate the team already lives with
    1  CI that runs on push to a branch
    2  CI on tags/schedules/manual — often the deploy pipeline, not the test gate
    3  a Makefile target named `test` / `lint` / `install`
    4  a `package.json` script
    5  a `Dockerfile` RUN line — an install recipe, rarely a gate

AND IT DECLARES ITS OWN BLINDNESS. `ManifestProposal.not_attempted` lists every `Manifest` field
this pass does not even try (computed from the schema, so it grows when the schema does), and
`ci_files_seen` lists CI-shaped files found but NOT parsed. A proposal that covers 2 of 31 fields
and says nothing about the other 29 reads as a complete proposal — the same collapse
`knowledge/generator.py` built its extension survey to prevent (C-49).

None vs empty, because it is this codebase's most expensive defect class: a `Proposal.value` of
`None` means *could not determine*; `[]` or `{}` means *read the source, and the honest answer is
nothing there* (a CI job whose test step needs no install really does have an empty `setup:`).
The two never share a tier: an empty value is only ever `observed`, never `unknown`.
"""

from __future__ import annotations

import json
import os
import re
import tomllib
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field

from openfactory.contracts import Manifest

# THE single pruning implementation, borrowed rather than copied. `knowledge/generator.py` already
# owns the answer to "which directories are never product code" (`node_modules`, `.venv`, `dist`,
# build output next to a `.csproj`, …) and it is exercised on every merge of every project. A
# second list here would drift, and the first symptom of the drift would be a proposal that
# reports a stack found inside a vendored dependency.
from openfactory.knowledge.generator import _walk_files
from openfactory.policy.presets import available_stacks

# --- tiers -------------------------------------------------------------------------------

#: read verbatim out of a file the client wrote
OBSERVED = "observed"
#: a convention this stack implies, anchored to a marker we did read
INFERRED = "inferred"
#: not guessed — left for a human, and it says so
UNKNOWN = "unknown"

TIERS = (OBSERVED, INFERRED, UNKNOWN)


class Evidence(BaseModel):
    """Where a claim came from. Without one, a proposal is an opinion."""

    #: repo-relative POSIX path (or a platform path when `origin` is "platform")
    path: str
    #: 1-based line. None does NOT mean "could not read" here — it means the evidence is the
    #: FILE, not a line inside it (a `pyproject.toml` exists, so this is a Python project). A file
    #: we genuinely could not read produces no `Evidence` at all, which is the difference.
    line: int | None = None
    #: the line, verbatim, stripped. Kept because a reviewer reads the excerpt, not the path.
    excerpt: str = ""
    #: "repo" = the client's file · "platform" = ours (a preset). A citation that does not say
    #: whose file it is invites a client to go looking for a file they do not have.
    origin: str = "repo"

    @property
    def locator(self) -> str:
        return f"{self.path}:{self.line}" if self.line else self.path


class Candidate(BaseModel):
    """One answer we found for a field. The plural is the point: on a legacy repo there are four
    candidates and the interesting output is the list, not the winner."""

    value: Any = None
    confidence: str = UNKNOWN
    evidence: list[Evidence] = Field(default_factory=list)
    #: why this one ranked where it did, in one line, for a human skimming the report
    why: str = ""


class Proposal(BaseModel):
    """One manifest field, its value, where that came from, and how much of it we made up."""

    field: str
    #: None = could not determine (and then `confidence` is `unknown`). `[]`/`{}` = we read the
    #: source and the honest answer is empty.
    value: Any = None
    confidence: str = UNKNOWN
    evidence: list[Evidence] = Field(default_factory=list)
    #: for `unknown`, the QUESTION a human must answer — never a shrug. For the other tiers, what
    #: the reader should know before accepting it.
    note: str = ""
    #: every candidate found, best first. `value` is `candidates[0].value` when there is one.
    candidates: list[Candidate] = Field(default_factory=list)

    @property
    def known(self) -> bool:
        return self.confidence in (OBSERVED, INFERRED) and self.value is not None


class StackSighting(BaseModel):
    """A stack the repository actually shows, and whether the platform can express it."""

    stack: str
    #: repo-relative directories where the marker lives, sorted
    roots: list[str] = Field(default_factory=list)
    confidence: str = OBSERVED
    evidence: list[Evidence] = Field(default_factory=list)
    #: does `available_stacks()` ship a preset for it? A `False` here is the client-2 story:
    #: `Component` requires BOTH `path` and `stack`, so a .NET or SPFx area cannot be declared
    #: at all, and pretending otherwise emits YAML `conformance` refuses.
    expressible: bool = False


class ManifestProposal(BaseModel):
    """What one read of one repository can say — and, deliberately, what it cannot."""

    #: the path as it was handed to us, absolute
    repo: str
    fields: dict[str, Proposal] = Field(default_factory=dict)
    stacks: list[StackSighting] = Field(default_factory=list)
    #: things this repository IS that the manifest schema has no way to say
    cannot_express: list[str] = Field(default_factory=list)
    #: what only the client can answer, one line each, ready to be read out loud
    questions: list[str] = Field(default_factory=list)
    #: EVERY COMMAND READ OUT OF A PIPELINE, verbatim, with where it was read (#176).
    #:
    #: NOT `fields`, AND THAT DISTINCTION IS THE WHOLE REASON THIS EXISTS. A field carries the one
    #: command this pass would RECOMMEND for a role, normalised and ranked — `ruff check .` where
    #: the pipeline says `uv run ruff check src tests`, `npm test -- --run` where the client also
    #: runs pytest. That is right for a proposal and wrong for the question `doctor` asks: *what
    #: does your pipeline run that nothing declares?* Answering it from the recommendations
    #: reported three false gaps in each direction on the pilot, in both directions at once.
    #:
    #: Sources are CI files only: a `make` target or an npm script is a convention this repository
    #: OFFERS, not a step anything runs before a change lands.
    ci_commands: list[Candidate] = Field(default_factory=list)
    #: Which of the parsed CI files carry THIS PROJECT'S CHECKS — a file that yields a test, a
    #: lint, a scanner or a type check (#176). A pipeline that yields none is a deploy, whatever
    #: it is called, and asking a client to declare `aws ssm send-command` as a validation is how
    #: a useful finding becomes one nobody reads.
    #:
    #: COMPUTED HERE BECAUSE THE ROLE IS KNOWN HERE. A consumer re-deriving it by calling
    #: `classify()` on the command text gets a different answer: the value carried by a named step
    #: is the WHOLE step, so `uv run ruff check src tests` classifies as nothing and the file that
    #: runs this project's ruff, mypy, bandit and pytest looked like a deploy pipeline. Measured —
    #: and it then reported the client's own declared validations as no longer run.
    ci_files_with_checks: list[str] = Field(default_factory=list)
    #: CI-shaped files found and PARSED, repo-relative
    ci_files_read: list[str] = Field(default_factory=list)
    #: CI-shaped files found and NOT parsed — declared, so "no CI" and "a CI we cannot read" stay
    #: distinguishable. They are not the same finding and they have opposite remedies.
    ci_files_seen: list[str] = Field(default_factory=list)
    #: `Manifest` fields this pass does not even attempt. Computed from the schema, so it grows
    #: by itself when the schema does.
    not_attempted: list[str] = Field(default_factory=list)
    #: how many paths the walk found, how many survived the ceiling, and whether it hit one
    files_walked: int = 0
    files_considered: int = 0
    truncated: bool = False
    #: directories that could not be opened. A stack living under one of them is invisible to this
    #: proposal, and silence about that reads as "there is nothing there".
    unreadable_dirs: list[str] = Field(default_factory=list)

    def proposed(self) -> list[Proposal]:
        return [p for p in self.fields.values() if p.known]

    def unknowns(self) -> list[Proposal]:
        return [p for p in self.fields.values() if not p.known]


# --- reading files, without ever letting a failure look like an answer -------------------


def _read(path: Path) -> str | None:
    """File text, or None when it could not be read. `utf-8-sig` because a `.csproj` written by
    Visual Studio starts with a BOM and a stray `\\ufeff` breaks an anchored regex silently."""
    try:
        return path.read_text(encoding="utf-8-sig", errors="replace")
    except OSError:
        return None


class _LocatedStr(str):
    """A YAML scalar that remembers which line it came from.

    Line numbers are the whole point of this module — an `observed` value without a `file:line` is
    an assertion, not evidence — and `yaml.safe_load` throws them away. Searching the raw text for
    the string afterwards was the other option and it is the one that quietly goes wrong: two
    identical `run: npm test` steps in one file, and every citation points at the first.
    """

    line: int = 0
    #: a block scalar (`|` / `>`). Its content starts on the line AFTER the marker, which is what
    #: makes multi-line `run: |` steps citable per command.
    block: bool = False


class _LineLoader(yaml.SafeLoader):
    pass


def _construct_located(loader: yaml.SafeLoader, node: yaml.Node) -> _LocatedStr:
    located = _LocatedStr(loader.construct_scalar(node))  # type: ignore[arg-type]
    located.line = node.start_mark.line + 1
    located.block = node.style in ("|", ">")
    return located


_LineLoader.add_constructor("tag:yaml.org,2002:str", _construct_located)


def _load_yaml(path: Path) -> Any:
    """Parsed YAML with line-carrying strings, or None when it could not be read or parsed.

    Best-effort by design: a client's pipeline full of Azure `${{ }}` template expressions or a
    GitHub `on:` we do not understand must degrade this module to "I could not read your CI",
    never crash the caller mid-workshop.
    """
    text = _read(path)
    if text is None:
        return None
    try:
        return yaml.load(text, Loader=_LineLoader)  # noqa: S506 - SafeLoader subclass
    except yaml.YAMLError:
        return None


def _line_of(value: Any, offset: int = 0) -> int | None:
    """The 1-based line a parsed scalar came from. `offset` is the index of a sub-line inside a
    block scalar: for `run: |`, the marker sits on the `run:` line and content starts on the next,
    so command *i* is at `start + 1 + i`."""
    line = getattr(value, "line", 0)
    if not line:
        return None
    if getattr(value, "block", False):
        return line + 1 + offset
    return line


# --- classifying a shell line into a manifest role ---------------------------------------

#: split a shell line into the commands it actually runs. `&&`, `||` and `;` only — NOT `|`,
#: because a pipe's head is still the command that matters (`pytest | tee log` is a test run) and
#: splitting on it would classify `tee` as the command.
_SEPARATORS = re.compile(r"\s*(?:&&|\|\||;)\s*")

#: noise that hides the real head of a command: make's silent/ignore prefixes, `sudo`, and
#: leading `VAR=value` assignments.
_PREFIX = re.compile(r"^(?:[-@+]\s*|sudo\s+|[A-Za-z_][A-Za-z0-9_]*=\S*\s+)+")

# Ordered. FIRST MATCH WINS, and every pattern is anchored at the head of the command — that
# anchoring is what stops `python -m pip install --quiet pytest` from being read as a test run,
# which is the single most likely way this classifier could produce a confident wrong answer.
# (fx-ado's pipeline contains exactly that line. It is the harness's own canary; see
# `tests/test_the_platform_reads_a_repository_and_proposes.py::
# test_an_install_line_that_mentions_pytest_is_not_a_test_command`. There is no `test_infer.py`;
# a citation a reader cannot open is the same defect as a `file:line` that does not resolve.)
_ROLE_PATTERNS: tuple[tuple[str, str], ...] = (
    # ---- setup / install --------------------------------------------------------------
    (r"^(?:python[0-9.]*\s+-m\s+)?pip3?\s+install\b", "setup"),
    # `uv python install` JOINS ITS SIBLINGS (#177). Installing a toolchain is setup by any
    # definition, and while it was missing the step named "Set up Python" fell through to
    # `classify() == ""` and was proposed to the client as a VALIDATION to declare.
    (r"^(?:python[0-9.]*\s+-m\s+)?uv\s+(?:pip\s+install|sync|python\s+install)\b", "setup"),
    (r"^poetry\s+install\b", "setup"),
    (r"^pipenv\s+(?:install|sync)\b", "setup"),
    (r"^conda\s+(?:env\s+)?(?:create|install|update)\b", "setup"),
    (r"^(?:npm|pnpm)\s+(?:ci|install|i)\b", "setup"),
    (r"^yarn\s+(?:install|--frozen-lockfile)\b", "setup"),
    (r"^yarn$", "setup"),
    (r"^dotnet\s+restore\b", "setup"),
    (r"^(?:nuget|msbuild)\s+.*restore\b", "setup"),
    (r"^go\s+mod\s+(?:download|tidy)\b", "setup"),
    (r"^(?:mvn|\./mvnw)\b[^\n]*\b(?:dependency:go-offline|-DskipTests)\b", "setup"),
    (r"^bundle\s+install\b", "setup"),
    (r"^composer\s+install\b", "setup"),
    (r"^cargo\s+fetch\b", "setup"),
    (r"^(?:apt-get|apk|yum|dnf|brew)\s+(?:-\S+\s+)*(?:install|add)\b", "setup"),
    (r"^make\s+(?:install|deps|bootstrap|setup)\b", "setup"),
    # ---- test -------------------------------------------------------------------------
    (r"^(?:python[0-9.]*\s+-m\s+)?pytest\b", "test"),
    (r"^(?:python[0-9.]*\s+-m\s+)?unittest\b", "test"),
    (r"^(?:python[0-9.]*\s+-m\s+)?tox\b", "test"),
    (r"^tox\b", "test"),
    (r"^(?:npm|pnpm|yarn)\s+(?:run\s+)?test\b", "test"),
    (r"^node\s+--test\b", "test"),
    (r"^(?:npx\s+)?(?:jest|vitest|mocha|ava|karma)\b", "test"),
    (r"^dotnet\s+test\b", "test"),
    (r"^(?:vstest\.console|dotnet\s+vstest)\b", "test"),
    (r"^go\s+test\b", "test"),
    (r"^(?:mvn|\./mvnw)\s+[^\n]*\btest\b", "test"),
    (r"^(?:gradle|\./gradlew)\s+[^\n]*\btest\b", "test"),
    (r"^cargo\s+test\b", "test"),
    (r"^(?:bundle\s+exec\s+)?rspec\b", "test"),
    (r"^(?:\./vendor/bin/)?phpunit\b", "test"),
    (r"^make\s+(?:test|tests|check)\b", "test"),
    # ---- lint -------------------------------------------------------------------------
    (r"^(?:python[0-9.]*\s+-m\s+)?ruff\b", "lint"),
    (r"^(?:python[0-9.]*\s+-m\s+)?flake8\b", "lint"),
    (r"^(?:python[0-9.]*\s+-m\s+)?pylint\b", "lint"),
    (r"^(?:python[0-9.]*\s+-m\s+)?black\s+[^\n]*--check\b", "lint"),
    (r"^(?:python[0-9.]*\s+-m\s+)?isort\s+[^\n]*--check\b", "lint"),
    (r"^(?:npx\s+)?eslint\b", "lint"),
    (r"^(?:npm|pnpm|yarn)\s+(?:run\s+)?lint\b", "lint"),
    (r"^dotnet\s+format\b", "lint"),
    (r"^golangci-lint\b", "lint"),
    (r"^(?:terraform|tofu)\s+fmt\b", "lint"),
    (r"^tflint\b", "lint"),
    (r"^rubocop\b", "lint"),
    (r"^make\s+(?:lint|format)\b", "lint"),
    # ---- type -------------------------------------------------------------------------
    (r"^(?:python[0-9.]*\s+-m\s+)?mypy\b", "type"),
    (r"^pyright\b", "type"),
    (r"^(?:npx\s+)?tsc\b", "type"),
    (r"^(?:npm|pnpm|yarn)\s+(?:run\s+)?(?:typecheck|type-check|types)\b", "type"),
    # ---- security ---------------------------------------------------------------------
    (r"^(?:python[0-9.]*\s+-m\s+)?bandit\b", "security"),
    (r"^(?:python[0-9.]*\s+-m\s+)?pip[-_]audit\b", "security"),
    (r"^semgrep\b", "security"),
    (r"^trivy\b", "security"),
    (r"^gitleaks\b", "security"),
    (r"^(?:npm|yarn)\s+audit\b", "security"),
    (r"^snyk\b", "security"),
    (r"^(?:tfsec|checkov)\b", "security"),
    # ---- build ------------------------------------------------------------------------
    (r"^(?:npm|pnpm|yarn)\s+(?:run\s+)?build\b", "build"),
    (r"^dotnet\s+build\b", "build"),
    (r"^go\s+build\b", "build"),
    (r"^(?:mvn|\./mvnw)\s+[^\n]*\bpackage\b", "build"),
    (r"^cargo\s+build\b", "build"),
    (r"^make\s+build\b", "build"),
)

_COMPILED_ROLES = tuple((re.compile(p), role) for p, role in _ROLE_PATTERNS)


def split_commands(line: str) -> list[str]:
    """The individual commands a shell line runs, prefixes stripped, empties dropped."""
    out: list[str] = []
    for part in _SEPARATORS.split(line.strip()):
        cleaned = _PREFIX.sub("", part.strip()).strip()
        if cleaned and not cleaned.startswith("#"):
            out.append(cleaned)
    return out


#: The role of a command the client's CI runs that fills none of ours (#175).
#:
#: `classify()` answering `""` used to mean FORGET IT, and the cost was measured on the pilot: a
#: client wrote a gate specifically because the defect it catches is invisible to local tests —
#: `alembic heads | grep -c '(head)'; test "$heads" -eq 1` — the inference read the file it lives
#: in, found no role for it, and dropped it. A pull request then went out with the exact defect
#: that gate exists to stop.
#:
#: It is not about that command. A `dotnet format --verify-no-changes`, an `mvn
#: enforcer:enforce`, a `dbt compile`, a `terraform validate` — none is a test, a lint or a
#: scanner, and every one of them is a thing the client's pipeline requires before a change
#: lands. `Manifest.validation` is `dict[str, str | Gate]` and takes any key; the READER had the
#: closed vocabulary.
NAMED_CHECK = "named-check"

#: WHAT BOUNDS THE NOISE, and it is structural rather than a guess about anybody's stack: only a
#: step the CI file itself NAMED is proposed. A validation needs a key in the manifest map, the
#: author already wrote one, and taking their word for it is the opposite of inventing a name.
#: An anonymous `run:` block — which is what the deploy and release pipelines here are made of —
#: has no name to take, so it is not proposed and the useful one is not drowned.
#:
#: NO RANK FILTER, deliberately, and this is the trap it avoids: "only steps that gate a pull
#: request" sounds right and would have excluded the very file this card is about. The pilot's
#: `ci-tests.yml` is `on: workflow_call` — rank 2, "anything else" — because it is a REUSABLE gate
#: the deploy calls. Structure said it was unimportant; the client's comment on it said the
#: opposite.
def slug_for(name: str) -> str:
    """A manifest key from the step's own name — lowercase, words joined by `-`.

    Deterministic and lossy in one direction only: two steps whose names differ by punctuation
    collapse, which is right (they are the same key), and a name that carries no word at all
    returns `""` so the caller drops it rather than minting `--`.
    """
    words = re.findall(r"[a-z0-9]+", (name or "").lower())
    return "-".join(words)[:60]


#: The launchers that run a tool INSIDE a managed environment (#177). Every role pattern below is
#: anchored at the head of the command — deliberately; that anchoring is what stops `python -m pip
#: install --quiet pytest` reading as a test run — so a launcher the reader does not know makes
#: everything behind it invisible.
#:
#: MEASURED, NOT SUSPECTED. `npx` was the only one present, so `uv run pytest`, `poetry run
#: pytest`, `bundle exec rubocop` and `uv run mypy src` all classified as nothing. The pilot is a
#: Python backend whose CI runs four `uv run` checks; none was read, and its proposal offered it
#: `npm test -- --run` — the FRONTEND's command — as its test command.
#:
#: A CLOSED SET OF TRANSPARENT LAUNCHERS, never a heuristic. `make test` is an alias whose recipe
#: this pass cannot see, and `docker compose run` enters a service the box does not start: both
#: have their own handling and neither belongs here.
_RUNNER = re.compile(
    r"^(?:uv|poetry|pipenv|pdm|hatch|rye|nox|tox)\s+run\s+"
    r"|^bundle\s+exec\s+"
    r"|^npx\s+(?:--yes\s+|-y\s+)?"
    r"|^(?:pnpm\s+(?:exec|dlx)|yarn\s+dlx)\s+"
    r"|^dotnet\s+tool\s+run\s+"
)


def classify(command: str) -> str:
    """The manifest validation role a command fills, or `""` for "not one of ours".

    `""` and not None on purpose: this is a lookup that ran and found nothing, not a lookup that
    failed. `echo "deploy simulado"` is a real line in fx-jira's pipeline and the right answer for
    it is "no role", every time.

    STRIPPED FOR THE LOOKUP, NEVER FOR THE VALUE (#177). The runner prefix is removed to ask what
    the command IS, and the caller keeps the command it read: `pytest` without its `uv run` does
    not run in the box, and proposing it would be worse than proposing nothing.
    """
    for candidate in (command, _RUNNER.sub("", command or "", count=1)):
        for pattern, role in _COMPILED_ROLES:
            if pattern.match(candidate):
                return role
    return ""


# --- what a CI file gives us -------------------------------------------------------------


class _Cmd(BaseModel):
    """One classified command, with where it was found and how much that source is worth."""

    command: str
    role: str
    #: The NAME the CI file gave this step, when it gave one (#175). It becomes the manifest key
    #: for a check that fills none of our roles — the client already named it, and inventing a
    #: name for somebody else's gate is how a proposal stops being reviewable.
    named: str = ""
    evidence: Evidence
    #: the job it belongs to. `setup:` is taken from the job that owns the chosen test command —
    #: CI jobs are independent, so an install step in the LINT job says nothing about what the
    #: test job needs.
    job: str
    rank: int
    source: str
    #: WHAT THE ENTRY POINT ACTUALLY RUNS, when the entry point hides it. A `make` target is
    #: proposed by NAME on purpose (it survives a change to the recipe), and that is exactly what
    #: made a real project's `test: docker-compose exec api pytest tests/ -v` unreadable from the
    #: proposal: the value said `make test` and nothing carried the fact that it enters a service
    #: the box does not start. Kept only to WARN — never to replace the value, which stays the
    #: line the team's own file states.
    runs: str = ""
    #: a tie-break INSIDE a rank, low wins. Two commands from the same file at the same rank used
    #: to be ordered by line number alone, which hands the verdict to whichever one the author
    #: happened to type first: a `package.json` listing `test:watch` above `test` proposed
    #: `npm run test:watch`. The script whose NAME is the role gets 0; a variant we chose gets 1.
    precedence: int = 0

    def sort_key(self) -> tuple[int, int, str, int, str]:
        return (
            self.rank,
            self.precedence,
            self.evidence.path,
            self.evidence.line or 0,
            self.command,
        )


def _cmds_from_script(
    script: Any, *, path: str, job: str, rank: int, source: str, lines: list[str],
    named: str = "",
) -> list[_Cmd]:
    """Turn one `run:`/`script:` scalar (possibly a multi-line block) into classified commands.

    `named` is the step's own name when the CI file gave it one. A command that fills none of our
    roles is KEPT under `NAMED_CHECK` when there is a name to key it by, and dropped when there is
    not (#175) — see the note on `NAMED_CHECK` for why the name is the boundary.
    """
    out: list[_Cmd] = []
    if not isinstance(script, str):
        return out
    for offset, raw in enumerate(script.splitlines() or [script]):
        line_no = _line_of(script, offset)
        for command in split_commands(raw):
            role = classify(command)
            if not role and slug_for(named):
                # THE WHOLE STEP IS THE VALUE, NOT A FRAGMENT OF IT. `split_commands` shreds a
                # shell block so each piece can be classified, which is right for finding a role
                # and wrong for reproducing a check: the pilot's gate is
                # `heads=$(… | grep -c '(head)')` then `test "$heads" -eq 1`, and the first
                # fragment alone proposed `run alembic heads 2>/dev/null | grep -c '(head)')` —
                # cut at the `$(`, unrunnable. A proposal whose value does not run is worse than
                # no proposal: it reads as an answer.
                role, command = NAMED_CHECK, script.strip()
            if not role:
                continue
            excerpt = lines[line_no - 1].strip() if line_no and line_no <= len(lines) else command
            out.append(
                _Cmd(
                    command=command,
                    role=role,
                    named=named if role == NAMED_CHECK else "",
                    evidence=Evidence(path=path, line=line_no, excerpt=excerpt),
                    job=job,
                    rank=rank,
                    source=source,
                )
            )
    return out


def _github_rank(doc: dict) -> int:
    """0 = runs on a pull request, 1 = on a push, 2 = anything else.

    `on:` IS NOT `"on"`. YAML 1.1 reads a bare `on` as the boolean True, so `doc["on"]` raises
    KeyError on every GitHub workflow ever written and a naive reader concludes "this workflow has
    no triggers" — then ranks a deploy pipeline level with the PR gate. Measured on this
    repository's own `.github/workflows/ci.yml`: `list(doc)` is `['name', True, 'jobs']`.
    """
    triggers = doc.get("on", doc.get(True))
    if isinstance(triggers, str):
        triggers = {triggers: None}
    if isinstance(triggers, list):
        triggers = dict.fromkeys(triggers)
    if not isinstance(triggers, dict):
        return 2
    if "pull_request" in triggers or "pull_request_target" in triggers:
        return 0
    if "push" in triggers:
        return 1
    return 2


def _read_github(path: Path, rel: str) -> list[_Cmd]:
    doc = _load_yaml(path)
    if not isinstance(doc, dict):
        return []
    lines = (_read(path) or "").splitlines()
    rank = _github_rank(doc)
    jobs = doc.get("jobs")
    if not isinstance(jobs, dict):
        return []
    out: list[_Cmd] = []
    for job_name, job in jobs.items():
        if not isinstance(job, dict):
            continue
        for step in job.get("steps") or []:
            if isinstance(step, dict) and "run" in step:
                out += _cmds_from_script(
                    step["run"],
                    path=rel,
                    job=str(job_name),
                    rank=rank,
                    source="github_actions",
                    lines=lines,
                    named=str(step.get("name") or ""),
                )
    return out


#: Azure DevOps runs a step's script under one of four keys. Missing one loses the whole pipeline
#: silently — a `pwsh:` shop reads as "no CI", which is the failure this module exists to end.
_ADO_SCRIPT_KEYS = ("script", "bash", "pwsh", "powershell")


def _ado_steps(node: Any) -> list[tuple[str, Any, str]]:
    """(job name, script scalar, step name) for every step reachable from an Azure pipeline doc.

    THE STEP NAME IS ADO'S `displayName` (#175) — the same fact GitHub spells `name:`. Threading
    it for one vendor and not the other would be this platform's signature defect committed one
    layer up from where #161 found it: a capability that exists for whichever provider somebody
    happened to be holding.

    ADO nests four ways — `steps:` at the root, under `jobs:`, under `stages: jobs:`, and inside a
    `deployment:`'s `strategy: runOnce: deploy: steps:` — and a reader that handles three of them
    is a reader that reports "no test command" on the pipelines that use the fourth. Every fixture
    in this platform's own toy-project set uses the deepest of the four for its deploy stage.
    """
    found: list[tuple[str, Any, str]] = []

    def walk(obj: Any, job: str) -> None:
        if isinstance(obj, list):
            for item in obj:
                walk(item, job)
            return
        if not isinstance(obj, dict):
            return
        name = str(obj.get("job") or obj.get("deployment") or obj.get("stage") or job)
        for key in ("stages", "jobs", "steps"):
            if key in obj:
                walk(obj[key], name)
        # `strategy: {runOnce|rolling|canary: {preDeploy|deploy|routeTraffic|postRouteTraffic: …}}`
        strategy = obj.get("strategy")
        if isinstance(strategy, dict):
            for phase in strategy.values():
                if isinstance(phase, dict):
                    for hook in phase.values():
                        walk(hook, name)
        for key in _ADO_SCRIPT_KEYS:
            if key in obj:
                found.append((name, obj[key], str(obj.get("displayName") or "")))

    walk(node, "")
    return found


def _read_azure(path: Path, rel: str, repo: Path, depth: int = 0) -> tuple[list[_Cmd], list[str]]:
    """Commands, plus the repo-relative paths of any `- template:` files this pipeline delegates
    to that we could NOT read. A real Azure repo puts its steps in templates; a reader that stops
    at the entry file finds an empty pipeline and reports it as an empty pipeline."""
    doc = _load_yaml(path)
    if not isinstance(doc, dict):
        return [], []
    lines = (_read(path) or "").splitlines()
    # `pr:` is the pull-request trigger. Present (and not `none`) → this is the gate the team
    # already lives with, which is exactly what rank 0 means.
    pr = doc.get("pr")
    rank = 0 if pr not in (None, "none", "None") else (1 if doc.get("trigger") else 2)
    out: list[_Cmd] = []
    for job, script, step_name in _ado_steps(doc):
        out += _cmds_from_script(
            script, path=rel, job=job, rank=rank, source="azure_pipelines", lines=lines,
            named=step_name,
        )

    unread: list[str] = []
    if depth < 2:
        for ref in _template_refs(doc):
            target = (repo / ref).resolve()
            try:
                target_rel = target.relative_to(repo.resolve()).as_posix()
            except ValueError:
                unread.append(ref)
                continue
            if not target.is_file():
                unread.append(ref)
                continue
            # A TEMPLATE THAT EXISTS AND DOES NOT PARSE IS STILL A TEMPLATE WE DID NOT READ.
            # `_read_azure` returns `([], [])` for a document it cannot load, which is
            # indistinguishable from a template that genuinely defines no commands — so without
            # this the steps in it vanish and the report says the pipeline has none.
            if not isinstance(_load_yaml(target), dict):
                unread.append(ref)
                continue
            nested, nested_unread = _read_azure(target, target_rel, repo, depth + 1)
            out += nested
            unread += nested_unread
    return out, unread


def _template_refs(node: Any) -> list[str]:
    """Every `template:` path in an Azure document, in document order, de-duplicated."""
    refs: list[str] = []

    def walk(obj: Any) -> None:
        if isinstance(obj, list):
            for item in obj:
                walk(item)
        elif isinstance(obj, dict):
            ref = obj.get("template")
            # `template: file.yml@resourceRepo` points at ANOTHER repository — unreadable here by
            # construction (we never fetch), and saying so is the honest answer.
            if isinstance(ref, str) and ref not in refs:
                refs.append(str(ref))
            for value in obj.values():
                walk(value)

    walk(node)
    return refs


def _read_gitlab(path: Path, rel: str) -> list[_Cmd]:
    doc = _load_yaml(path)
    if not isinstance(doc, dict):
        return []
    lines = (_read(path) or "").splitlines()
    out: list[_Cmd] = []
    for job_name, job in doc.items():
        if str(job_name).startswith(".") or not isinstance(job, dict):
            continue
        for key in ("before_script", "script", "after_script"):
            block = job.get(key)
            if isinstance(block, str):
                block = [block]
            for entry in block or []:
                out += _cmds_from_script(
                    entry, path=rel, job=str(job_name), rank=1, source="gitlab_ci", lines=lines
                )
    return out


def _read_circleci(path: Path, rel: str) -> list[_Cmd]:
    doc = _load_yaml(path)
    if not isinstance(doc, dict):
        return []
    lines = (_read(path) or "").splitlines()
    out: list[_Cmd] = []
    # `jobs` IS ONLY A MAPPING IN A CONFIG THAT IS CORRECT. `(doc.get("jobs") or {}).items()` was
    # the shorter spelling and it raises `AttributeError` the moment a client's config has
    # `jobs:` as a list — which prints a Python traceback on the screen in the room, from a
    # command whose entire promise is that it degrades to "I could not read your CI". Measured on
    # a two-line config; the same hole was in `_read_buildspec`. Type-check, do not truth-check.
    jobs = doc.get("jobs")
    if not isinstance(jobs, dict):
        return []
    for job_name, job in jobs.items():
        if not isinstance(job, dict):
            continue
        for step in job.get("steps") or []:
            run = step.get("run") if isinstance(step, dict) else None
            script = run.get("command") if isinstance(run, dict) else run
            # CircleCI's step name lives inside the `run:` mapping (#175) — the third spelling of
            # the same fact, after GitHub's `name:` and ADO's `displayName:`.
            out += _cmds_from_script(
                script, path=rel, job=str(job_name), rank=1, source="circleci", lines=lines,
                named=str(run.get("name") or "") if isinstance(run, dict) else "",
            )
    return out


def _read_travis(path: Path, rel: str) -> list[_Cmd]:
    """`.travis.yml` — dead as a service, alive in legacy repositories, and often the only written
    record of how a fifteen-year-old project builds."""
    doc = _load_yaml(path)
    if not isinstance(doc, dict):
        return []
    lines = (_read(path) or "").splitlines()
    out: list[_Cmd] = []
    for key in ("install", "before_script", "script"):
        block = doc.get(key)
        if isinstance(block, str):
            block = [block]
        for entry in block or []:
            out += _cmds_from_script(
                entry, path=rel, job=key, rank=1, source="travis", lines=lines
            )
    return out


def _read_buildspec(path: Path, rel: str) -> list[_Cmd]:
    """AWS CodeBuild. Common in the exact AWS-shop clients this platform is sold into."""
    doc = _load_yaml(path)
    if not isinstance(doc, dict):
        return []
    lines = (_read(path) or "").splitlines()
    out: list[_Cmd] = []
    # Same hole as `_read_circleci` above: a `phases:` that is a list raises rather than degrading.
    phases = doc.get("phases")
    if not isinstance(phases, dict):
        return []
    for phase_name, phase in phases.items():
        if not isinstance(phase, dict):
            continue
        for entry in phase.get("commands") or []:
            out += _cmds_from_script(
                entry, path=rel, job=str(phase_name), rank=1, source="buildspec", lines=lines
            )
    return out


_JENKINS_SH = re.compile(
    r"""\bsh\s+(?:label:\s*['"][^'"]*['"]\s*,\s*script:\s*)?['"]([^'"]+)['"]"""
)


def _read_jenkins(path: Path, rel: str) -> list[_Cmd]:
    text = _read(path)
    if text is None:
        return []
    out: list[_Cmd] = []
    for index, raw in enumerate(text.splitlines(), start=1):
        for match in _JENKINS_SH.finditer(raw):
            for command in split_commands(match.group(1)):
                role = classify(command)
                if role:
                    out.append(
                        _Cmd(
                            command=command,
                            role=role,
                            evidence=Evidence(path=rel, line=index, excerpt=raw.strip()),
                            job="pipeline",
                            rank=1,
                            source="jenkins",
                        )
                    )
    return out


_MAKE_TARGET = re.compile(r"^([A-Za-z0-9_][A-Za-z0-9_.\-/]*)\s*:(?!=)")
#: a Makefile target whose NAME is the client's own word for a role. `make test` beats the recipe
#: inside it: it is the entry point they type, so it survives a change to the recipe.
_MAKE_ROLE = {
    "test": "test",
    "tests": "test",
    "lint": "lint",
    "install": "setup",
    "deps": "setup",
    "build": "build",
    "typecheck": "type",
    "security": "security",
}


def _read_makefile(path: Path, rel: str) -> list[_Cmd]:
    text = _read(path)
    if text is None:
        return []
    out: list[_Cmd] = []
    lines = text.splitlines()
    for index, raw in enumerate(lines, start=1):
        if raw.startswith("\t") or not raw.strip() or raw.lstrip().startswith("#"):
            continue
        match = _MAKE_TARGET.match(raw)
        if not match:
            continue
        role = _MAKE_ROLE.get(match.group(1))
        if not role:
            continue
        # the recipe: the tab-indented lines under this target, until the next non-indented one
        recipe = []
        for follow in lines[index:]:
            if not follow.startswith("\t"):
                if follow.strip():
                    break
                continue
            recipe.append(follow.strip())
        out.append(
            _Cmd(
                command=f"make {match.group(1)}",
                runs=" && ".join(recipe),
                role=role,
                # VERBATIM, because `Evidence.excerpt` says verbatim and a reviewer reads the
                # excerpt rather than opening the file. An earlier version stripped the `##` help
                # text, so a client repository's `install:` target was cited with its help text
                # gone — the excerpt no longer matched the line it pointed at, and the stripped
                # half was the informative half.
                evidence=Evidence(path=rel, line=index, excerpt=raw.strip()),
                job="make",
                rank=3,
                source="makefile",
            )
        )
    return out


_DOCKER_RUN = re.compile(r"^\s*RUN\s+(.*)$", re.IGNORECASE)


def _read_dockerfile(path: Path, rel: str) -> list[_Cmd]:
    text = _read(path)
    if text is None:
        return []
    out: list[_Cmd] = []
    for index, raw in enumerate(text.splitlines(), start=1):
        match = _DOCKER_RUN.match(raw)
        if not match:
            continue
        for command in split_commands(match.group(1).rstrip("\\")):
            role = classify(command)
            if role:
                out.append(
                    _Cmd(
                        command=command,
                        role=role,
                        evidence=Evidence(path=rel, line=index, excerpt=raw.strip()),
                        job="image",
                        rank=5,
                        source="dockerfile",
                    )
                )
    return out


_PM_LOCKFILES = (("pnpm-lock.yaml", "pnpm"), ("yarn.lock", "yarn"), ("package-lock.json", "npm"))

#: Words in a `package.json` script NAME that disqualify it from being proposed as a gate, and
#: flags in its BODY that do the same.
#:
#: This is the one place in the module where we do not read a command — we SYNTHESISE one
#: (`npm run <name>`) from a name we chose off a list. Two of the commonest variants are
#: destructive in exactly that role: a `*:fix` script (or any body carrying `--fix`) REWRITES the
#: client's working tree, and a `*:watch` script never returns. The platform runs `validate:`
#: commands inside the sandbox on every ticket, so proposing one of these proposes that the first
#: thing the factory does to a fifteen-year-old repository is rewrite it, or hang on it.
#:
#: Measured before the rule existed: a `package.json` whose scripts read `test:watch, test,
#: lint:fix, lint` produced `validate.test: npm run test:watch` and `validate.lint: npm run
#: lint:fix`, both tagged `observed` — the module's strongest tier — because they sort first by
#: line. Nothing in that repository says those are the gate. So they are refused here and the
#: exact-named script survives, which is the answer a human would have given.
_NOT_A_GATE_WORDS = frozenset({"watch", "fix", "dev", "debug"})
_NOT_A_GATE_FLAGS = ("--watch", "--watchAll", "--fix")


def _gateable(name: str, body: str) -> bool:
    """May this `package.json` script be proposed as a validation gate?"""
    words = {w for w in re.split(r"[:\-_.\s]+", str(name).lower()) if w}
    if words & _NOT_A_GATE_WORDS:
        return False
    return not any(flag in str(body) for flag in _NOT_A_GATE_FLAGS)


def _read_package_json(path: Path, rel: str, manager: str) -> list[_Cmd]:
    """`scripts:` is a declaration the client wrote: `npm test` runs whatever `test` says, so the
    invocation is theirs, not ours. Rank 4 — a script is an entry point, but unlike a CI job
    nothing proves it passes anywhere."""
    text = _read(path)
    if text is None:
        return []
    try:
        doc = json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return []
    scripts = doc.get("scripts") if isinstance(doc, dict) else None
    if not isinstance(scripts, dict):
        return []
    lines = text.splitlines()
    out: list[_Cmd] = []
    for name, body in scripts.items():
        role = _MAKE_ROLE.get(str(name)) or classify(f"npm run {name}")
        if not role:
            continue
        if not _gateable(name, body):
            continue
        invocation = f"{manager} test" if name == "test" else f"{manager} run {name}"
        line_no = next(
            (i for i, raw in enumerate(lines, start=1) if f'"{name}"' in raw and str(body) in raw),
            None,
        )
        out.append(
            _Cmd(
                command=invocation,
                role=role,
                evidence=Evidence(
                    path=rel,
                    line=line_no,
                    excerpt=(lines[line_no - 1].strip() if line_no else f'"{name}": "{body}"'),
                ),
                job="package.json",
                rank=4,
                # A script whose NAME *is* the role (`test`, `lint`) is the entry point the team
                # types; `test:e2e` is one we picked off a list, and it needs a deployed
                # environment nobody has told us about. Both stay in the report as candidates —
                # only the winner changes.
                precedence=0 if str(name) in _MAKE_ROLE else 1,
                source="package_json",
            )
        )
    return out


# --- the repository walk -----------------------------------------------------------------


def _join(directory: Path, name: str) -> str:
    """A repo-relative POSIX path, with the `./` that `Path(".") / x` produces removed. Written as
    a helper because `.lstrip("./")` — the obvious one-liner — strips a *character set*, so it
    eats the leading dot of `.eslintrc` too."""
    joined = (directory / name).as_posix()
    return joined[2:] if joined.startswith("./") else joined


class _Tree(BaseModel):
    """Every path we considered, plus the directories we could not open at all."""

    #: repo-relative POSIX paths, sorted (depth, path) — so the root comes first
    files: list[str] = Field(default_factory=list)
    walked: int = 0
    truncated: bool = False
    #: directories `os.walk` raised on. Recorded rather than swallowed: `os.walk`'s default is to
    #: yield FEWER entries on an unreadable directory, so a repository the process cannot read is
    #: indistinguishable from an empty one — which is the exact collapse the knowledge generator's
    #: survey exists to prevent.
    unreadable: list[str] = Field(default_factory=list)

    def named(self, *names: str) -> list[str]:
        wanted = set(names)
        return [f for f in self.files if Path(f).name in wanted]

    def suffixed(self, *suffixes: str) -> list[str]:
        wanted = {s.lower() for s in suffixes}
        return [f for f in self.files if Path(f).suffix.lower() in wanted]


def _tree(repo: Path, max_files: int) -> _Tree:
    """The repository's paths, deterministically ordered and bounded.

    Sorted by (depth, path) and truncated from the END, so a repository big enough to hit the
    ceiling still yields its ROOT — which is where every build file, every CI file and every
    marker this module reads actually lives. Truncating a plain alphabetical sort would drop
    `pyproject.toml` from a repo whose `zzz/` tree is large, which is the sort of quietly wrong
    answer this whole module exists to refuse.
    """
    paths: list[str] = []
    unreadable: list[str] = []

    def on_error(error: OSError) -> None:
        unreadable.append(str(getattr(error, "filename", "") or error))

    # BY NAME ALONE, ON PURPOSE. `infer` reads a stranger's repository and NEVER runs a command
    # (`test_infer_never_runs_a_command_and_never_opens_a_socket` pins it) — so it does not ask git
    # what the repository ignores. The three readers that run on a checkout git itself made (the
    # map, the extension survey, the onboarding survey) do; this one keeps its promise and walks
    # what is on disk, as it always has.
    for rel_dir, filenames in _walk_files(repo, on_error=on_error, ignored=frozenset()):
        prefix = "" if rel_dir == Path(".") else f"{rel_dir.as_posix()}/"
        paths.extend(f"{prefix}{name}" for name in filenames)
    walked = len(paths)
    paths.sort(key=lambda p: (p.count("/"), p))
    return _Tree(
        files=paths[:max_files],
        walked=walked,
        truncated=walked > max_files,
        unreadable=sorted(unreadable),
    )


# --- base_branch, read as text so it carries a citation ----------------------------------


def _git_dir(repo: Path) -> Path | None:
    """`.git`, following the one-line `gitdir:` pointer a worktree leaves behind.

    This platform runs its own jobs in git worktrees, so `.git` being a FILE is the common case
    here, not an exotic one — and a reader that assumes a directory reports "not a git repository"
    on exactly the checkouts the factory produces.
    """
    dot = repo / ".git"
    if dot.is_dir():
        return dot
    if dot.is_file():
        text = _read(dot) or ""
        for line in text.splitlines():
            if line.startswith("gitdir:"):
                target = Path(line.split(":", 1)[1].strip())
                return target if target.is_absolute() else (repo / target)
    return None


def _common_dir(git_dir: Path) -> Path:
    """A worktree's gitdir holds its own HEAD but shares refs with the main checkout, recorded in
    a `commondir` file. Remote refs live there, never in the worktree's own gitdir."""
    text = _read(git_dir / "commondir")
    if not text:
        return git_dir
    target = Path(text.strip())
    return target if target.is_absolute() else (git_dir / target)


def _branch_from_ref(text: str, prefix: str) -> str:
    """`ref: refs/heads/release/2.4` → `release/2.4`.

    Written as a prefix strip and not as `rsplit("/", 1)[-1]`, which is the obvious one-liner and
    is wrong: a branch name may contain slashes, and most of them do — `feature/x`, `release/1.2`,
    `hotfix/PROJ-1234`. The short form silently returned `x` for `feature/x`, so the proposal named
    a branch that does not exist, `observed`, with a citation. Found by the test below, not by
    review.
    """
    ref = text.strip()
    if ref.startswith("ref:"):
        ref = ref.split(":", 1)[1].strip()
    return ref[len(prefix):] if ref.startswith(prefix) else ref.rsplit("/", 1)[-1]


def _base_branch(repo: Path) -> Proposal:
    field = "base_branch"
    git_dir = _git_dir(repo)
    if git_dir is None or not git_dir.exists():
        return Proposal(
            field=field,
            value=None,
            confidence=UNKNOWN,
            note=(
                "no readable `.git` here, so nothing in this directory states what the base branch "
                "is. Which branch do pull requests target?"
            ),
        )

    candidates: list[Candidate] = []

    # THE STRONG ANSWER. `refs/remotes/origin/HEAD` is what the remote itself says its default
    # branch is — a statement by the forge, not by whoever happens to be sitting at this checkout.
    origin_head = _common_dir(git_dir) / "refs" / "remotes" / "origin" / "HEAD"
    text = _read(origin_head)
    if text and text.strip().startswith("ref:"):
        branch = _branch_from_ref(text, "refs/remotes/origin/")
        candidates.append(
            Candidate(
                value=branch,
                confidence=OBSERVED,
                evidence=[
                    Evidence(
                        path=_rel_to(repo, origin_head),
                        line=1,
                        excerpt=text.strip(),
                    )
                ],
                why="the remote's own default branch (`refs/remotes/origin/HEAD`)",
            )
        )

    # THE WEAK ANSWER, and it is deliberately a tier lower. The branch somebody has checked out is
    # a fact about this working copy, not about where pull requests go: run this mid-feature and
    # the honest reading of `.git/HEAD` is `feature/whatever`.
    head_text = _read(git_dir / "HEAD")
    if head_text and head_text.strip().startswith("ref:"):
        branch = _branch_from_ref(head_text, "refs/heads/")
        candidates.append(
            Candidate(
                value=branch,
                confidence=INFERRED,
                evidence=[
                    Evidence(
                        path=_rel_to(repo, git_dir / "HEAD"),
                        line=1,
                        excerpt=head_text.strip(),
                    )
                ],
                why="the branch currently checked out here — a fact about this working copy",
            )
        )

    if not candidates:
        return Proposal(
            field=field,
            value=None,
            confidence=UNKNOWN,
            note=(
                "`.git` is present but neither `refs/remotes/origin/HEAD` nor `HEAD` names a "
                "branch (a detached HEAD does this). Which branch do pull requests target?"
            ),
        )

    best = candidates[0]
    note = ""
    if best.confidence == INFERRED:
        note = (
            "this clone has no `refs/remotes/origin/HEAD`, so the only thing the repository states "
            "is the branch checked out right now — confirm it is the branch PRs target"
        )
    elif len(candidates) > 1 and candidates[1].value != best.value:
        note = (
            f"the remote says `{best.value}` and this working copy is on `{candidates[1].value}` — "
            "the remote wins here"
        )
    return Proposal(
        field=field,
        value=best.value,
        confidence=best.confidence,
        evidence=best.evidence,
        note=note,
        candidates=candidates,
    )


def _rel_to(repo: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(repo.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


# --- stacks ------------------------------------------------------------------------------

#: filename → stack. The build file IS the declaration; nothing here is a guess.
_MARKER_NAMES: dict[str, str] = {
    "pyproject.toml": "python",
    "setup.py": "python",
    "setup.cfg": "python",
    "Pipfile": "python",
    "poetry.lock": "python",
    "uv.lock": "python",
    "tox.ini": "python",
    "package.json": "node",
    "go.mod": "go",
    "pom.xml": "java",
    "build.gradle": "java",
    "build.gradle.kts": "java",
    "Gemfile": "ruby",
    "composer.json": "php",
    "Cargo.toml": "rust",
}

#: suffix → stack, for stacks whose marker has no fixed name
_MARKER_SUFFIXES: dict[str, str] = {
    ".csproj": "dotnet",
    ".fsproj": "dotnet",
    ".vbproj": "dotnet",
    ".sln": "dotnet",
    ".slnx": "dotnet",
    ".tf": "terraform",
}

#: source-file extension → stack, used ONLY when no build file was found. Three of this repo's
#: fixtures (`py-simple`, `py-mono`, `py-serverless`) have no `pyproject.toml`, no `setup.py` and
#: no `requirements.txt` — which is also what a fifteen-year-old internal repository looks like.
#: Without this fallback the answer for all three is "no stack detected", which is false.
_SOURCE_SUFFIXES: dict[str, str] = {
    ".py": "python",
    ".ts": "node",
    ".tsx": "node",
    ".js": "node",
    ".jsx": "node",
    ".mjs": "node",
    ".cs": "dotnet",
    ".fs": "dotnet",
    ".go": "go",
    ".java": "java",
    ".kt": "java",
    ".rb": "ruby",
    ".php": "php",
    ".rs": "rust",
    ".tf": "terraform",
}

_REQUIREMENTS = re.compile(r"^requirements.*\.txt$")


def _detect_stacks(repo: Path, tree: _Tree) -> list[StackSighting]:
    expressible = set(available_stacks())
    markers: dict[str, list[Evidence]] = {}
    roots: dict[str, set[str]] = {}

    def record(stack: str, rel: str) -> None:
        markers.setdefault(stack, []).append(Evidence(path=rel, excerpt=Path(rel).name))
        roots.setdefault(stack, set()).add(str(Path(rel).parent.as_posix()))

    for rel in tree.files:
        name = Path(rel).name
        suffix = Path(rel).suffix.lower()
        if name in _MARKER_NAMES:
            record(_MARKER_NAMES[name], rel)
        elif _REQUIREMENTS.match(name):
            record("python", rel)
        elif suffix in _MARKER_SUFFIXES:
            record(_MARKER_SUFFIXES[suffix], rel)
        # A SAM/CloudFormation template is IaC and the fixtures declare it as a stack
        # (`py-serverless` writes `stack: sam`) — which `conformance.check` refuses, because no
        # such preset exists. Detected here precisely so the refusal is predicted rather than
        # discovered by the client.
        elif name in ("template.yaml", "template.yml"):
            text = _read(repo / rel) or ""
            if "AWS::Serverless" in text or "AWSTemplateFormatVersion" in text:
                record("sam", rel)

    sightings: list[StackSighting] = []
    for stack in sorted(markers):
        sightings.append(
            StackSighting(
                stack=stack,
                roots=sorted(roots[stack]),
                confidence=OBSERVED,
                evidence=sorted(markers[stack], key=lambda e: e.path)[:8],
                expressible=stack in expressible,
            )
        )

    # The fallback tier: source files with no build file above them.
    seen = {s.stack for s in sightings}
    census: dict[str, list[str]] = {}
    for rel in tree.files:
        stack = _SOURCE_SUFFIXES.get(Path(rel).suffix.lower())
        if stack and stack not in seen:
            census.setdefault(stack, []).append(rel)
    for stack in sorted(census):
        files = sorted(census[stack])
        sightings.append(
            StackSighting(
                stack=stack,
                roots=sorted({Path(f).parent.as_posix() for f in files}),
                confidence=INFERRED,
                evidence=[Evidence(path=f, excerpt=Path(f).name) for f in files[:8]],
                expressible=stack in expressible,
            )
        )
    return sorted(sightings, key=lambda s: (s.confidence != OBSERVED, s.stack))


# --- conventions, anchored to a marker we actually read ----------------------------------


def _find_line(text: str, needle: str) -> tuple[int | None, str]:
    for index, raw in enumerate(text.splitlines(), start=1):
        if needle in raw:
            return index, raw.strip()
    return None, ""


#: `python -m pytest`, NOT the bare `pytest` console script, and this platform paid to learn the
#: difference. Its own `pyproject.toml` records it: *"`python -m pytest` prepends the CWD and it
#: was; the bare `pytest` console script does not, and that is exactly what CI runs. So the suite
#: was green on every developer's machine and RED in CI on every push… after five commits had
#: landed on a red main."* A legacy repository with no packaging at all — which is `py-simple`,
#: `py-mono` and `py-serverless`, and every internal tool older than `pyproject.toml` — depends on
#: exactly that CWD entry to import its own modules. Proposing the bare form would hand each new
#: client the same red-for-a-week failure, on day one, in our own words. All four Python fixtures'
#: hand-written manifests independently chose the `-m` form.
_PYTEST = "python -m pytest -q"


def _python_conventions(repo: Path, tree: _Tree) -> list[_Cmd]:
    """What a Python repository's own files imply, each anchored to the line that implies it.

    `pip install -e '.[dev]'` is NOT emitted unless the repository has a `[project]` table and a
    `dev` extra to install. Card #99 §6 defect 9 is that exact line hardcoded into the project
    template for every client; on `py-simple` — no `pyproject.toml` at all — it fails outright,
    and a proposal that fails on contact is worse than an admitted `unknown`.
    """
    out: list[_Cmd] = []
    conv_rank = 6  # below every real source; conventions only win when nothing else answered

    pyprojects = [f for f in tree.named("pyproject.toml")]
    for rel in pyprojects[:1]:
        text = _read(repo / rel)
        if text is None:
            continue
        try:
            doc = tomllib.loads(text)
        except (tomllib.TOMLDecodeError, ValueError):
            doc = {}
        project = doc.get("project") if isinstance(doc, dict) else None
        extras = (project or {}).get("optional-dependencies") or {}
        if project is not None:
            extra = "dev" if "dev" in extras else ("test" if "test" in extras else "")
            command = f"pip install -e '.[{extra}]'" if extra else "pip install -e ."
            line, excerpt = _find_line(text, "[project]")
            out.append(
                _Cmd(
                    command=command,
                    role="setup",
                    evidence=Evidence(path=rel, line=line, excerpt=excerpt),
                    job="convention:python",
                    rank=conv_rank,
                    source="convention",
                )
            )
        if "pytest" in text:
            line, excerpt = _find_line(text, "pytest")
            out.append(
                _Cmd(
                    command=_PYTEST,
                    role="test",
                    evidence=Evidence(path=rel, line=line, excerpt=excerpt),
                    job="convention:python",
                    rank=conv_rank,
                    source="convention",
                )
            )
        if "[tool.ruff" in text:
            line, excerpt = _find_line(text, "[tool.ruff")
            out.append(
                _Cmd(
                    command="ruff check .",
                    role="lint",
                    evidence=Evidence(path=rel, line=line, excerpt=excerpt),
                    job="convention:python",
                    rank=conv_rank,
                    source="convention",
                )
            )

    requirement_files = [f for f in tree.files if _REQUIREMENTS.match(Path(f).name)]
    for rel in requirement_files[:1]:
        out.append(
            _Cmd(
                command=f"pip install -r {rel}",
                role="setup",
                evidence=Evidence(path=rel, excerpt=Path(rel).name),
                job="convention:python",
                rank=conv_rank,
                source="convention",
            )
        )

    # pytest, evidenced by the test files themselves. `tests/test_x.py` and `conftest.py` are the
    # convention pytest discovers by; a repository full of them is stating its runner even with no
    # config file anywhere — which is `py-simple`, `py-mono` and `py-serverless` exactly.
    if not any(c.role == "test" and c.source == "convention" for c in out):
        pytest_files = [
            f
            for f in tree.files
            if Path(f).name == "conftest.py"
            or (Path(f).suffix == ".py" and Path(f).name.startswith("test_"))
        ]
        if pytest_files:
            out.append(
                _Cmd(
                    command=_PYTEST,
                    role="test",
                    evidence=[
                        Evidence(path=f, excerpt=Path(f).name) for f in sorted(pytest_files)[:3]
                    ][0],
                    job="convention:python",
                    rank=conv_rank,
                    source="convention",
                )
            )

    for name in (".ruff.toml", "ruff.toml"):
        for rel in tree.named(name)[:1]:
            out.append(
                _Cmd(
                    command="ruff check .",
                    role="lint",
                    evidence=Evidence(path=rel, excerpt=name),
                    job="convention:python",
                    rank=conv_rank,
                    source="convention",
                )
            )
    return out


_PROJECT_REFERENCE = re.compile(r"""<ProjectReference\s[^>]*?Include\s*=\s*["']([^"']+)["']""",
                                re.IGNORECASE)


def _dotnet_conventions(repo: Path, tree: _Tree) -> tuple[list[_Cmd], str]:
    """.NET, which is the interesting case and the client-2 stack.

    `dotnet restore` with no target does not guess: with several projects and no solution file it
    fails. `fx-dotnet`'s hand-written manifest says so in a comment — *"a raiz não tem solution
    file e `dotnet restore` sem alvo não adivinha"* — and that comment is the human work this
    function replaces.

    The repository DOES state the answer, in `<ProjectReference>`: a test project references the
    code it tests, so restoring the test project restores both. The root of that reference graph —
    the project nothing else points at — is the single target. One root → propose it. Several
    roots and no solution → propose nothing and say which projects to choose between, because
    picking one at random is how a client's first `setup:` fails on a project we never read.

    Returns (commands, unresolvable-note).
    """
    solutions = sorted(tree.suffixed(".sln", ".slnx"), key=lambda p: (p.count("/"), p))
    projects = sorted(tree.suffixed(".csproj", ".fsproj", ".vbproj"))
    if not projects and not solutions:
        return [], ""

    conv_rank = 6
    target = ""
    evidence: Evidence | None = None
    note = ""

    if solutions:
        target = solutions[0]
        evidence = Evidence(path=target, excerpt=Path(target).name)
    elif len(projects) == 1:
        target = projects[0]
        evidence = Evidence(path=target, excerpt=Path(target).name)
    else:
        referenced: set[str] = set()
        for rel in projects:
            text = _read(repo / rel) or ""
            for raw in _PROJECT_REFERENCE.findall(text):
                # `Include="..\..\src\Functions\Functions.csproj"` — MSBuild writes Windows
                # separators even in repositories that only ever build on Linux agents, so the
                # path has to be normalised before it can be compared with a walked path.
                relative = os.path.join(os.path.dirname(rel), raw.replace("\\", "/"))
                referenced.add(Path(os.path.normpath(relative)).as_posix())
        roots = [p for p in projects if p not in referenced]
        if len(roots) == 1:
            target = roots[0]
            line, excerpt = _find_line(_read(repo / target) or "", "<ProjectReference")
            evidence = Evidence(path=target, line=line, excerpt=excerpt or Path(target).name)
        else:
            note = (
                f"{len(projects)} .NET projects, no solution file, and "
                f"{len(roots)} of them are referenced by nothing "
                f"({', '.join(roots[:4])}{'…' if len(roots) > 4 else ''}) — `dotnet restore` and "
                "`dotnet test` need a target and this repository does not name one. Which project "
                "(or solution) is the entry point?"
            )
            return [], note

    assert evidence is not None
    return (
        [
            _Cmd(
                command=f"dotnet restore {target}",
                role="setup",
                evidence=evidence,
                job="convention:dotnet",
                rank=conv_rank,
                source="convention",
            ),
            _Cmd(
                command=f"dotnet test {target} --nologo -v quiet",
                role="test",
                evidence=evidence,
                job="convention:dotnet",
                rank=conv_rank,
                source="convention",
            ),
        ],
        note,
    )


def _node_conventions(repo: Path, tree: _Tree) -> list[_Cmd]:
    """`npm ci` needs a lockfile; without one it fails outright rather than degrading, which is a
    red pipeline that says nothing about the code. `fx-dsk-ui`'s own pipeline carries that comment
    verbatim, so this rule is the client's, not ours."""
    roots = tree.named("package.json")[:1]
    if not roots:
        return []
    directory = Path(roots[0]).parent
    manager, lock_rel = "npm", ""
    for lock_name, lock_manager in _PM_LOCKFILES:
        candidate = _join(directory, lock_name)
        if candidate in tree.files:
            manager, lock_rel = lock_manager, candidate
            break
    # NO LOCKFILE, NO PROPOSAL. `npm ci` without one fails outright rather than degrading — a red
    # pipeline that says nothing about the code — and `npm install` mutates the dependency tree,
    # which is not something to hand a client as a default. `fx-dsk-ui`'s own pipeline carries
    # that reasoning in a comment, so the rule is theirs.
    if not lock_rel:
        return []
    install = "npm ci" if manager == "npm" else f"{manager} install --frozen-lockfile"
    return [
        _Cmd(
            command=install,
            role="setup",
            evidence=Evidence(path=lock_rel, excerpt=Path(lock_rel).name),
            job="convention:node",
            rank=6,
            source="convention",
        )
    ]


# --- CI discovery ------------------------------------------------------------------------

#: CI-shaped files this pass recognises but does NOT parse. Listed by name in the report so a
#: repository whose pipeline lives in one of them is told "we did not read your CI" rather than
#: "you have no CI". Those two findings have opposite remedies.
_CI_SEEN_ONLY = {
    "bitbucket-pipelines.yml",
    ".drone.yml",
    "appveyor.yml",
    "cloudbuild.yaml",
    "cloudbuild.yml",
    "Taskfile.yml",
    "justfile",
    "Justfile",
    ".teamcity",
    "codeship-steps.yml",
    "wercker.yml",
}


_Collected = tuple[list[_Cmd], list[str], list[str], list[str]]

#: The kinds whose reader needs a PARSED document. Everything else is read as raw text.
_YAML_CI_KINDS = frozenset({"github", "azure", "gitlab", "circleci", "travis", "buildspec"})

#: kind → the key that holds the commands, for the readers whose walk depends on its TYPE.
#: `gitlab`, `travis` and `azure` are absent on purpose: they walk defensively over several
#: legitimate shapes, so there is no single key whose type decides whether the file is readable.
_CI_COMMAND_KEY = {"github": "jobs", "circleci": "jobs", "buildspec": "phases"}


def _ci_shape_is_known(kind: str, doc: dict) -> bool:
    """Is the parsed document the SHAPE this reader can walk? Parsing is not understanding.

    A `.circleci/config.yml` whose `jobs:` is a LIST parses perfectly into a dict, so the parse
    gate passes it, the reader finds nothing it can walk, and returns `[]` — byte-for-byte what a
    config with no commands returns. Measured through the product surface after the parse gate
    landed: `openfactory env read` printed *"no test command anywhere … (CI read: "
                                            ".circleci/config.yml)"*
    over a file whose jobs block it had not been able to use. The same sentence, about the same
    file, for the opposite reason.

    Only a key that is PRESENT and of the wrong type counts. An ABSENT key is a different file
    (a composite action that happens to live under `.github/workflows`, a config with only
    `orbs:`), not a broken one, and calling those unreadable would trade a false silence for a
    false alarm.
    """
    key = _CI_COMMAND_KEY.get(kind)
    if key is None or key not in doc:
        return True
    return isinstance(doc[key], dict)


def _ci_kind(rel: str) -> str:
    """Which reader owns this path, or `""` for "not one of ours".

    Split out of `_collect_commands` so that the question "did this file actually parse?" is asked
    in ONE place. It used to be asked in none: every branch appended the path to `ci_files_read`
    unconditionally, so a workflow with a tab in it — or one the process could not open — was
    reported as a CI file we READ, and the refusal underneath it then said *"no test command
    anywhere … (CI read: .github/workflows/ci.yml)"*. That is a failure wearing the costume of an
    answer, aimed at the one file that would have contained the answer, and it is precisely the
    collapse `ci_files_seen` was built to prevent: *"you have no CI"* and *"we could not read your
    CI"* have opposite remedies. Nine branches each had to remember; now none of them can forget.
    """
    name = Path(rel).name
    parent = Path(rel).parent.as_posix()
    suffix = Path(rel).suffix.lower()
    if parent == ".github/workflows" and suffix in (".yml", ".yaml"):
        return "github"
    if name.startswith("azure-pipelines") and suffix in (".yml", ".yaml"):
        return "azure"
    if name in (".gitlab-ci.yml", ".gitlab-ci.yaml"):
        return "gitlab"
    if rel in (".circleci/config.yml", ".circleci/config.yaml"):
        return "circleci"
    if name in (".travis.yml", ".travis.yaml"):
        return "travis"
    if name in ("buildspec.yml", "buildspec.yaml"):
        return "buildspec"
    if name == "Jenkinsfile" or name.startswith("Jenkinsfile."):
        return "jenkins"
    if name in ("Makefile", "makefile", "GNUmakefile"):
        return "makefile"
    if name == "Dockerfile" or name.startswith("Dockerfile."):
        return "dockerfile"
    if name in _CI_SEEN_ONLY:
        return "seen-only"
    return ""


def _collect_commands(repo: Path, tree: _Tree) -> _Collected:
    """Every classified command the repository's own tooling contains.

    Returns (commands, ci files read, ci files seen-but-unread, notes).
    """
    commands: list[_Cmd] = []
    read: list[str] = []
    seen: list[str] = []
    notes: list[str] = []

    for rel in tree.files:
        kind = _ci_kind(rel)
        if not kind:
            continue
        path = repo / rel
        if kind == "seen-only":
            seen.append(rel)
            continue

        # THE GATE. A reader that could not load its document returns `[]`, which is exactly what a
        # reader that loaded a pipeline with no commands in it returns — so the readability
        # question has to be answered HERE, before the reader runs, or the two are indistinguishable
        # downstream. The parse happens twice on the handful of CI files a repository has; that
        # cost buys the distinction the whole report rests on.
        if kind in _YAML_CI_KINDS:
            doc = _load_yaml(path)
            usable = isinstance(doc, dict) and _ci_shape_is_known(kind, doc)
        else:
            usable = _read(path) is not None
        if not usable:
            seen.append(rel)
            notes.append(
                f"`{rel}` is CI-shaped and this pass could NOT read it — it could not be opened, "
                "did not parse as a document, or is not a shape this pass knows how to walk. The "
                "commands in it were not read, so anything below that says nothing runs your "
                "tests is a statement about what we could read, not about your pipeline. Is this "
                "file valid on your agents?"
            )
            continue

        if kind == "github":
            commands += _read_github(path, rel)
        elif kind == "azure":
            found, unread = _read_azure(path, rel, repo)
            commands += found
            for missing in unread:
                notes.append(
                    f"`{rel}` delegates to the template `{missing}`, which is not a readable file "
                    "in this repository (an `@repo` resource lives in another repository, and this "
                    "pass never fetches) — commands defined there were NOT read"
                )
        elif kind == "gitlab":
            commands += _read_gitlab(path, rel)
        elif kind == "circleci":
            commands += _read_circleci(path, rel)
        elif kind == "travis":
            commands += _read_travis(path, rel)
        elif kind == "buildspec":
            commands += _read_buildspec(path, rel)
        elif kind == "jenkins":
            commands += _read_jenkins(path, rel)
        elif kind == "makefile":
            commands += _read_makefile(path, rel)
        elif kind == "dockerfile":
            commands += _read_dockerfile(path, rel)
        read.append(rel)

    # package.json, root-most first (`tree.files` is depth-sorted), with the package manager its
    # lockfile names — `yarn test` is not `npm test` in a yarn workspace.
    for rel in tree.named("package.json")[:1]:
        directory = Path(rel).parent
        manager = "npm"
        for lock_name, lock_manager in _PM_LOCKFILES:
            if _join(directory, lock_name) in tree.files:
                manager = lock_manager
                break
        commands += _read_package_json(repo / rel, rel, manager)

    return commands, sorted(read), sorted(seen), notes


# --- assembling the proposal --------------------------------------------------------------

_RANK_WHY = {
    "github_actions": "GitHub Actions",
    "azure_pipelines": "Azure Pipelines",
    "gitlab_ci": "GitLab CI",
    "circleci": "CircleCI",
    "travis": "Travis CI",
    "buildspec": "AWS CodeBuild",
    "jenkins": "Jenkins",
    "makefile": "a Makefile target",
    "package_json": "a package.json script",
    "dockerfile": "a Dockerfile RUN line",
    "convention": "a convention this stack implies",
}


def _why(cmd: _Cmd) -> str:
    where = _RANK_WHY.get(cmd.source, cmd.source)
    if cmd.rank == 0:
        return f"{where} — runs on every pull request, so this command already passes off-laptop"
    if cmd.rank == 1:
        return f"{where} — runs on push"
    if cmd.rank == 2:
        return f"{where} — not a pull-request gate (tag/schedule/manual); often the deploy pipeline"
    if cmd.rank == 6:
        return where
    return where


def _tier(cmd: _Cmd) -> str:
    """`observed` only when the command is a line the client wrote, or the canonical invocation of
    a named entry point they wrote (`make test`, `npm test`). A convention we derived is
    `inferred`, always — even a very good one."""
    return INFERRED if cmd.source == "convention" else OBSERVED


def _to_candidate(cmd: _Cmd) -> Candidate:
    return Candidate(
        value=cmd.command, confidence=_tier(cmd), evidence=[cmd.evidence], why=_why(cmd)
    )


#: A command that reaches INTO a service somebody else started. Not "mentions docker" — building
#: an image is fine, and `docker run` brings its own container. These three enter a container that
#: has to already be up, which is the distinction that matters.
_INTO_A_RUNNING_SERVICE = re.compile(
    r"\b(?:docker[-\s]compose\s+(?:exec|run)|docker\s+exec|kubectl\s+exec)\b")


def _needs_a_stack_this_box_will_not_start(
    command: str, runs: str, candidates: list[Candidate]
) -> str:
    """A warning when the command we are proposing cannot run where the platform will run it.

    FOUND ON A REAL PROJECT, and it is the ambiguity nobody planted. A working application's
    Makefile said:

        test:  docker-compose exec api pytest tests/ -v

    That is CORRECT — for a developer with the stack up — and it is the line their own file
    states, so this pass reads it and proposes it with the highest confidence tier it has. It is
    also unrunnable in the box: the platform mounts the repository into ONE container, and there
    is no service called `api` inside it.

    WHAT WE DO NOT DO IS TRANSLATE IT. Rewriting `docker-compose exec api pytest tests/` into
    `pytest backend/tests` would be inventing a command nobody wrote, in the one field the whole
    run is gated on — and it would be silently wrong the first time the paths did not line up.
    The value stays what their file says, and the tier stays `observed`, because both are true.

    WHAT WE DO IS SAY SO. Without this, the first sign is `box prove` failing with the container
    runtime's own words ("no such service: api") minutes later, in front of the client, about a
    command they know works. With it, the same fact arrives as a question in the room — which is
    the whole shape of this module: propose, and name what a human still has to decide.
    """
    if not _INTO_A_RUNNING_SERVICE.search(command) and not _INTO_A_RUNNING_SERVICE.search(runs):
        return ""
    others = [c for c in candidates
              if c.value != command and not _INTO_A_RUNNING_SERVICE.search(str(c.value))]
    alternative = (
        f" Another candidate does not: `{others[0].value}` — check whether it covers the same "
        f"tests."
        if others else
        " Nothing else in this repository runs these tests another way, so the command that runs "
        "in the box has to come from the team."
    )
    return (
        "This command enters a service that has to be ALREADY RUNNING (`docker compose exec` or "
        "equivalent). It is right for a developer with the stack up and cannot run in the box, "
        "which mounts the repository into a single container and starts no services." + alternative
    )


#: A command's HEAD → the file it needs in the directory it runs in. Not a list of stacks we
#: like: every row is a tool this module's own classifier already recognises, and adding a
#: stack means adding a row here too. The operator set that bar while the pilot was running
#: (2026-08-14): *"vamos lembrando que colocaremos em ADO com c# front em typescript"* — a rule
#: written around one repository's npm would be a rule that fails the next client.
_NEEDS_A_FILE_HERE: tuple[tuple[str, tuple[str, ...]], ...] = (
    (r"^npm\s+ci\b", ("package-lock.json",)),
    (r"^pnpm\s+(?:install|i)\b", ("pnpm-lock.yaml",)),
    (r"^yarn\s+(?:install\b|--frozen-lockfile)", ("yarn.lock",)),
    (r"^(?:python[0-9.]*\s+-m\s+)?uv\s+sync\b", ("uv.lock", "pyproject.toml")),
    (r"^poetry\s+install\b", ("poetry.lock", "pyproject.toml")),
    (r"^pipenv\s+(?:install|sync)\b", ("Pipfile",)),
    (r"^dotnet\s+(?:restore|build|test)\b", (".sln", ".csproj", ".fsproj", ".vbproj")),
    (r"^(?:nuget|msbuild)\b", (".sln", ".csproj")),
    (r"^go\s+(?:mod|build|test)\b", ("go.mod",)),
    (r"^(?:mvn|\./mvnw)\b", ("pom.xml",)),
    (r"^(?:gradle|\./gradlew)\b", ("build.gradle", "build.gradle.kts", "settings.gradle")),
    (r"^cargo\s+\w+", ("Cargo.toml",)),
    (r"^bundle\s+\w+", ("Gemfile",)),
    (r"^composer\s+\w+", ("composer.json",)),
)
_COMPILED_NEEDS = tuple((re.compile(p, re.I), markers) for p, markers in _NEEDS_A_FILE_HERE)


def _runs_somewhere_else(command: str, tree) -> tuple[str, str]:
    """`(the file this command needs, where that file actually is)` — `("", "")` when fine.

    THE WORKING DIRECTORY IS THE PART WE DROP. A command read out of a client's CI carries an
    implicit location — GitHub Actions' `working-directory:`, a `cd` in a Makefile, Azure
    Pipelines' `workingDirectory:` — and this module proposes the TEXT, which the box then runs
    at the repository root. The pilot's first proven manifest carried `npm ci` from a job that
    ran it in a front-end folder; at the root there is no lockfile, so the proof failed on a
    command the client's pipeline runs green every day (2026-08-14).

    The synthesis half already refuses this ("NO LOCKFILE, NO PROPOSAL"); the observed half had
    no such rule, and observed is the STRONGER tier — so the better evidence produced the worse
    manifest. Same fact, both halves now.

    Answers with WHERE the file is when it exists elsewhere, because that is the useful half: it
    turns "this cannot run" into "this runs in `web/` — declare that component, or give the
    command its path"."""
    for pattern, markers in _COMPILED_NEEDS:
        if not pattern.match(command.strip()):
            continue
        # A COMMAND THAT NAMES ITS TARGET IS ALREADY LOCATED, and most do: `dotnet restore
        # tests/Orders.Tests.csproj` runs from the root exactly as its pipeline runs it, and
        # deferring it would delete a correct line over a rule about a file it never needed at
        # the root. Only the bare form — `npm ci`, `dotnet restore` with no argument — depends
        # on where it is standing.
        for token in command.split()[1:]:
            arg = token.strip("\"'")
            if arg and not arg.startswith("-") and (
                    arg in tree.files or any(f.startswith(arg.rstrip("/") + "/")
                                             for f in tree.files)):
                return "", ""
        here = any(m in tree.files or any(f == m for f in tree.files) for m in markers)
        if here:
            return "", ""
        elsewhere = ""
        for f in tree.files:
            if any(f.endswith(m) for m in markers) and "/" in f:
                elsewhere = str(Path(f).parent)
                break
        return markers[0], elsewhere
    return "", ""


def _named_check_proposals(commands: list[_Cmd]) -> list[Proposal]:
    """One proposal per NAMED check the client's CI runs that fills none of our roles (#175).

    Keyed by the client's own name for the step, because a validation needs a key in the manifest
    map and they already wrote one. Deterministic: sorted by key, and within a key the strongest
    occurrence wins by the same `sort_key` every other field uses.

    THE ONES WE ALREADY PROPOSE ARE NOT REPEATED. A step named "Run tests" whose command is the
    one `validate.test` proposes would arrive twice under two keys, and a client reading a
    proposal that asks them the same question in two places stops reading it.
    """
    # ONLY FROM A FILE THAT ALREADY GAVE US A ROLE, and this is what bounds the noise (measured:
    # without it, ten of seventeen proposals were deploy plumbing — `aws s3 cp`, `ssm
    # send-command`, a smoke test, an instance being started — and the one gate that mattered was
    # buried among them).
    #
    # STRUCTURAL, NOT A GUESS ABOUT DEPLOYMENT. The discriminator is this module's own
    # classification: a file that contributes a test, a lint or a scanner is demonstrably where
    # this project keeps its checks; one that contributes none is something else, whatever the
    # client happens to call it. No filename is matched, no `on:` trigger is read — and in
    # particular no rank filter, which was the trap: the pilot's gate lives in a `workflow_call`
    # file that ranks LAST precisely because it is the reusable one every other pipeline calls.
    with_roles = {c.evidence.path for c in commands
                  if c.role in ("test", "lint", "security", "types")}
    # A STEP OUR ROLES ALREADY COVER CANNOT REACH HERE, and it needs no filter to say so:
    # `classify()` is consulted FIRST, so a command with a role is never `NAMED_CHECK`. The first
    # version of this function carried a `spoken_for` set for that case; a mutation removing it
    # stayed green, which is how it was found to be unreachable. A guard below states the property
    # instead — dead code with a comment claiming it works is the shape this module exists to
    # avoid producing, and it is no better inside the module itself.
    named = [c for c in commands
             if c.role == NAMED_CHECK and slug_for(c.named)
             and c.evidence.path in with_roles]
    if not named:
        return []
    best: dict[str, _Cmd] = {}
    for cmd in sorted(named, key=lambda c: c.sort_key()):
        best.setdefault(slug_for(cmd.named), cmd)
    out: list[Proposal] = []
    for key, cmd in sorted(best.items()):
        out.append(
            Proposal(
                field=f"validate.{key}",
                value=cmd.command,
                confidence=_tier(cmd),
                evidence=[cmd.evidence],
                candidates=[_to_candidate(cmd)],
                note=(
                    f"your pipeline runs this as \"{cmd.named}\" and it fills none of the roles "
                    f"this platform names, so nothing would run it. Keep it if a change must pass "
                    f"it before landing; drop it if it belongs to a deploy or needs a secret the "
                    f"box does not carry."
                ),
            )
        )
    return out


def _command_proposal(
    field: str, role: str, commands: list[_Cmd], *, question: str
) -> tuple[Proposal, _Cmd | None]:
    """One command-valued field, with every candidate found, best first."""
    matches = sorted([c for c in commands if c.role == role], key=lambda c: c.sort_key())
    if not matches:
        return (
            Proposal(field=field, value=None, confidence=UNKNOWN, note=question),
            None,
        )
    best = matches[0]
    # De-duplicate identical commands, keeping the strongest occurrence, so a repository that runs
    # `npm test` in four workflows shows one candidate rather than four.
    candidates: list[Candidate] = []
    seen_values: set[str] = set()
    for cmd in matches:
        if cmd.command in seen_values:
            continue
        seen_values.add(cmd.command)
        candidates.append(_to_candidate(cmd))
    note = ""
    if len(candidates) > 1:
        note = (
            f"{len(candidates)} candidates were found; the one proposed comes from "
            f"{_why(best).split(' — ')[0]}. Review the others before accepting."
        )
    if _tier(best) == INFERRED:
        note = (note + " " if note else "") + (
            "no CI file in this repository runs this — the command is the convention the stack "
            "implies, not a line anybody wrote"
        )
    needs = _needs_a_stack_this_box_will_not_start(best.command, best.runs, candidates)
    if needs:
        note = (note + " " if note else "") + needs
    return (
        Proposal(
            field=field,
            value=best.command,
            confidence=_tier(best),
            evidence=[best.evidence],
            note=note.strip(),
            candidates=candidates,
        ),
        best,
    )


def _setup_proposal(
    commands: list[_Cmd], test_cmd: _Cmd | None, ci_read: list[str], ci_seen: list[str],
    tree=None,
) -> tuple[Proposal, list[str]]:
    """`setup:` comes from the job that owns the chosen test command.

    CI jobs are independent processes: an install step in the *lint* job says nothing about what
    the *test* job needs, and stitching the two together produces a `setup:` that no machine has
    ever run in that combination.
    """
    installs = sorted([c for c in commands if c.role == "setup"], key=lambda c: c.sort_key())
    if test_cmd is not None:
        same_job = [
            c
            for c in installs
            if c.evidence.path == test_cmd.evidence.path and c.job == test_cmd.job
        ]
        if same_job:
            ordered = sorted(same_job, key=lambda c: (c.evidence.line or 0, c.command))
            # THE NOTE HAS TO NAME THE SOURCE IT ACTUALLY USED. An earlier build printed "taken
            # from the same CI job as the test command" over a `dotnet restore` derived from a
            # `<ProjectReference>` graph, in a repository with no CI file at all — a citation that
            # sends a reviewer looking for a pipeline that does not exist. A note that describes
            # the wrong provenance is the same defect class as a value that is wrong, and harder
            # to catch, because it reads as diligence.
            note = (
                "derived alongside the test command from the same source, in file order"
                if ordered[0].source == "convention"
                else (
                    f"taken from the same {_RANK_WHY.get(ordered[0].source, ordered[0].source)} "
                    f"job (`{ordered[0].job}`) as the test command, in file order — an install "
                    "step from a different job has never run in this combination"
                )
            )
            # EVERY ITEM IN `setup:` MUST RUN, so one that cannot takes the whole install down
            # and the box proof reports the client's own pipeline as broken. A command whose
            # required file is not where the box will run it is LEFT OUT and asked about instead
            # — the same rule the synthesis half already applies, now on the stronger tier too.
            runnable, deferred = [], []
            for c in ordered:
                needs, where = _runs_somewhere_else(c.command, tree) if tree else ("", "")
                (deferred if needs else runnable).append((c, needs, where))
            asked = [
                (f"`{c.command}` was read from {_RANK_WHY.get(c.source, c.source)} "
                 f"({c.evidence.path}) and is NOT in the proposed `setup:`: it needs "
                 f"`{needs}`, which is not at the repository root"
                 + (f" — it is in `{where}`, so that job runs there. Declare that directory as a "
                    f"component, or give the command its own path."
                    if where else
                    ". Add it back with whatever makes it runnable from the root."))
                for c, needs, where in deferred
            ]
            return Proposal(
                field="setup",
                value=[c.command for c, _n, _w in runnable],
                confidence=_tier(ordered[0]),
                evidence=[c.evidence for c, _n, _w in runnable] or [ordered[0].evidence],
                note=note,
                candidates=[_to_candidate(c) for c in ordered],
            ), asked
        # THE HONEST EMPTY. We read the source that runs the tests and it installs nothing: a real
        # answer with evidence behind it, not a shrug — `fx-dsk-ui`'s pipeline says so in a comment
        # of its own. `[]` is only reachable here, and only ever `observed`.
        if _tier(test_cmd) == OBSERVED:
            where = _RANK_WHY.get(test_cmd.source, test_cmd.source)
            return Proposal(
                field="setup",
                value=[],
                confidence=OBSERVED,
                evidence=[test_cmd.evidence],
                note=(
                    f"{where} runs `{test_cmd.command}` with no install step before it — this "
                    "repository's tests need nothing installed first. Empty because we read it, "
                    "not because we could not"
                ),
                candidates=[_to_candidate(c) for c in installs],
            ), []
    if installs:
        best = installs[0]
        return Proposal(
            field="setup",
            value=[best.command],
            confidence=_tier(best),
            evidence=[best.evidence],
            note=(
                "no CI job pairs an install with a test command, so this is the strongest install "
                "line found on its own — confirm it is what the test run needs"
            ),
            candidates=[_to_candidate(c) for c in installs],
        ), []
    # "AND NO CI FILE AT ALL" IS A CLAIM ABOUT THE CLIENT'S REPOSITORY, and it was made from the
    # `ci_read` list alone — so a repository whose only pipeline we FAILED to read was told it had
    # no CI. That is the same collapse as counting an unparsed file as read, in the one sentence
    # a client is most likely to argue with. The three cases are three different sentences.
    if ci_read:
        where = f" (CI read: {', '.join(ci_read)})"
    elif ci_seen:
        where = (
            f" — and the CI-shaped file(s) here ({', '.join(ci_seen)}) could NOT be read by this "
            "pass, so this may be a gap in our reading rather than in your repository"
        )
    else:
        where = " and no CI file at all"
    return Proposal(
        field="setup",
        value=None,
        confidence=UNKNOWN,
        note=(
            "nothing in this repository installs dependencies: no CI install step, no dependency "
            "manifest we recognise" + where + ". What has to run before the tests can?"
        ),
    ), []


def _components_proposal(stacks: list[StackSighting]) -> tuple[Proposal, list[str]]:
    """Components only when the repository is genuinely polyglot — and only when EVERY area can
    be expressed.

    A partial component map is worse than none: `Component` is how a diff is mapped back to the
    gates and the risk level that apply to it, so an area with no component silently inherits
    repo-wide treatment while `max_touched_components` counts a repository that is larger than the
    map says. `available_stacks()` ships four presets (`node`, `python`, `security-oss`,
    `terraform`) and `Component` requires BOTH `path` and `stack`, so a .NET or SPFx area cannot be
    declared at all — which is client 2, entirely.
    """
    cannot: list[str] = []
    real = [s for s in stacks if s.stack != "security-oss"]
    inexpressible = [s for s in real if not s.expressible]
    for sighting in inexpressible:
        cannot.append(
            f"stack `{sighting.stack}` ({len(sighting.roots)} "
            f"{'directory' if len(sighting.roots) == 1 else 'directories'}, e.g. "
            f"`{sighting.roots[0] if sighting.roots else '.'}`) has no preset — "
            f"`available_stacks()` ships {available_stacks()}, and `Component` requires both "
            "`path` and `stack`, so this area cannot be declared as a component at all. Use "
            "repo-wide `validate:` gates instead of components."
        )

    # THE None/{} RULE, and this function is where it is hardest to hold. `{}` is a CLAIM — "we
    # read the repository and it has no components" — and it is true for exactly one of the four
    # exits below: a single expressible stack, where repo-wide gates are the right shape. The other
    # three are refusals: there ARE areas here and we cannot say them. Those return None, because
    # `{}` under an `unknown` tier tells a caller that keys off the value that this repository has
    # no components, which is the opposite of what we found. The module's own docstring states the
    # invariant ("an empty value is only ever `observed`, never `unknown`"); it used to return `{}`
    # from all four.
    if len(real) < 2:
        only = real[0].stack if real else "none detected"
        return (
            Proposal(
                field="components",
                value={} if real else None,
                confidence=OBSERVED if real else UNKNOWN,
                # The citation for "there is one stack here" is the marker that showed the stack.
                # An `{}` with no evidence at all reads as a default rather than as a reading.
                evidence=(real[0].evidence[:1] if real else []),
                note=(
                    f"one stack across the whole repository (`{only}`) — repo-wide gates are the "
                    "right shape here, and inventing components would only add a map to keep "
                    "correct"
                    if real
                    else "no stack was detected, so there is nothing to divide into components"
                ),
            ),
            cannot,
        )

    if inexpressible:
        names = ", ".join(f"`{s.stack}`" for s in inexpressible)
        return (
            Proposal(
                field="components",
                value=None,
                confidence=UNKNOWN,
                note=(
                    f"this repository is polyglot ({', '.join(f'`{s.stack}`' for s in real)}) but "
                    f"{names} cannot be expressed as a component, and a PARTIAL component map is "
                    "worse than none: an area with no component silently inherits repo-wide "
                    "treatment while `max_touched_components` counts against a map that does not "
                    "describe the repository. Decide with a human: repo-wide gates, or split the "
                    "repository"
                ),
            ),
            cannot,
        )

    components: dict[str, dict[str, str]] = {}
    evidence: list[Evidence] = []
    for sighting in sorted(real, key=lambda s: s.stack):
        for root in sighting.roots:
            if root in (".", ""):
                # A stack whose marker sits at the repo root cannot be given a narrower glob than
                # `**`, and `**` overlaps every other component — so the map would be ambiguous
                # exactly where it has to be precise.
                return (
                    Proposal(
                        field="components",
                        value=None,
                        confidence=UNKNOWN,
                        note=(
                            f"`{sighting.stack}` is rooted at the repository root, so its glob "
                            "would be `**` and would overlap every other component — a diff could "
                            "not be mapped to one area. Splitting this needs a human who knows "
                            "which directories belong to which stack"
                        ),
                    ),
                    cannot,
                )
        top = sorted({root.split("/")[0] for root in sighting.roots})
        for directory in top:
            key = re.sub(r"[^a-z0-9_]+", "_", directory.lower()).strip("_") or sighting.stack
            components[key] = {"path": f"{directory}/**", "stack": sighting.stack}
            evidence += [e for e in sighting.evidence if e.path.startswith(directory + "/")][:1]
    return (
        Proposal(
            field="components",
            value=components,
            confidence=INFERRED,
            evidence=sorted(evidence, key=lambda e: e.path),
            note=(
                f"{len(real)} stacks in disjoint directories — the globs are derived from where "
                "the build files sit, so confirm they match how the team actually divides the work"
            ),
            candidates=[],
        ),
        cannot,
    )


#: `Manifest` fields this pass attempts. Everything else is DECLARED as not attempted, computed
#: against the live schema so the declaration cannot go stale.
_ATTEMPTED = ("base_branch", "setup", "validation", "components")


def infer(repo: str | Path, *, max_files: int = 20_000) -> ManifestProposal:
    """Read `repo` and propose a manifest. Reads files; runs nothing; writes nothing.

    Deterministic: same repository state, same object.

    Raises `NotADirectoryError` when `repo` is not a readable directory, and that is deliberate.
    `os.walk` SWALLOWS the error and yields nothing, so a typo in a path would come back as a
    complete, confident proposal in which every field is `unknown` — a failure wearing the costume
    of an answer, which is the one thing this module must never produce.
    """
    root = Path(repo).expanduser()
    if not root.is_dir():
        raise NotADirectoryError(
            f"cannot read a repository at {root}: it is not a directory. Refusing to return a "
            "proposal, because an empty one here is indistinguishable from a repository that "
            "genuinely says nothing."
        )
    tree = _tree(root, max_files)
    stacks = _detect_stacks(root, tree)
    commands, ci_read, ci_seen, notes = _collect_commands(root, tree)

    detected = {s.stack for s in stacks}
    dotnet_note = ""
    if "python" in detected:
        commands += _python_conventions(root, tree)
    if "node" in detected:
        commands += _node_conventions(root, tree)
    if "dotnet" in detected:
        dotnet_cmds, dotnet_note = _dotnet_conventions(root, tree)
        commands += dotnet_cmds

    fields: dict[str, Proposal] = {}
    fields["base_branch"] = _base_branch(root)

    test_proposal, test_cmd = _command_proposal(
        "validate.test",
        "test",
        commands,
        question=(
            "no test command anywhere: no CI step, no Makefile target, no package script, and no "
            "stack convention this repository's own files support"
            + (f" (CI read: {', '.join(ci_read)}). " if ci_read else ". ")
            + "What command runs your tests, and does it pass on a clean checkout?"
        ),
    )
    if dotnet_note and not test_proposal.known:
        test_proposal.note = dotnet_note
    fields["validate.test"] = test_proposal

    lint_proposal, _ = _command_proposal(
        "validate.lint",
        "lint",
        commands,
        question=(
            "no linter is configured or run here — proposing one would be proposing a tool this "
            "team does not use, and the first thing it would do is report the accumulated debt of "
            "the repository's whole history. Which linter do you use, and should it be `advisory` "
            "on the first pass?"
        ),
    )
    fields["validate.lint"] = lint_proposal

    # THE FLOOR'S OTHER MANDATORY GATE, and it was the one field this pass classified and then
    # threw away. `_ROLE_PATTERNS` carries a full security table — bandit, pip-audit, semgrep,
    # trivy, gitleaks, npm audit, snyk, tfsec — and `classify()` answers `"security"` for each of
    # them; nothing consumed the answer. A fixture whose own pipeline runs `python -m pip_audit
    # --strict` produced a proposal with no security gate, no question about one, and no entry in
    # `not_attempted`: built, tested, reached by nothing.
    #
    # WHAT MADE IT WORSE THAN A MISSING FIELD. `doctor` refuses a project whose manifest does not
    # declare `security` AND `test` — the platform's own quality floor. So the proposal this
    # module exists to produce could not pass the check the same onboarding runs one step later,
    # and said nothing about why. A gap that reads as completeness.
    #
    # THE QUESTION IS DIFFERENT FROM THE LINTER'S, deliberately. A missing linter is a preference;
    # a missing security gate is the floor, so the question says that out loud rather than asking
    # politely — and it names the OSS preset, because "you need one" without "here is one" is how
    # an onboarding turns into homework.
    security_proposal, _ = _command_proposal(
        "validate.security",
        "security",
        commands,
        question=(
            "no security gate is configured or run here, and the platform's floor requires one "
            "alongside the tests — a project without it is refused before its first ticket. "
            "Which scanner do you use? If there is none, the OSS preset (`stack: security-oss`) "
            "runs one this deployment already ships, and `advisory` on the first pass keeps a "
            "noisy first scan from blocking anything."
        ),
    )
    fields["validate.security"] = security_proposal

    # WHAT THE CLIENT'S PIPELINE REQUIRES THAT FILLS NONE OF OUR ROLES (#175). Measured on the
    # pilot: a client wrote `alembic heads | grep -c '(head)'; test "$heads" -eq 1` into their CI,
    # with a comment saying it exists because the defect it catches is invisible to local tests.
    # This module read the file, found no role for the line, and dropped it — and a pull request
    # went out carrying exactly that defect.
    #
    # PROPOSED, NEVER IMPORTED. Some named steps must not run in a box — a deploy, anything
    # holding a secret, a matrix setup — and deciding which is guessing the client's stack, which
    # the floor rule forbids. Each arrives as its own field for the client to accept or drop, at
    # the tier its evidence earns, with the `file:line` it was read from.
    for extra in _named_check_proposals(commands):
        # IT MAY NEVER OVERWRITE A FIELD WE ALREADY PROPOSED. A client whose step is named "Test"
        # slugs to `test`, and this loop runs after `validate.test` is set — so the client's own
        # test command would be silently replaced by whatever that step happened to run. Found by
        # a mutation: substituting the job name for the step name produced exactly that, and the
        # proposal still LOOKED right because the key was one we expect.
        if extra.field not in fields:
            fields[extra.field] = extra

    fields["setup"], setup_questions = _setup_proposal(
        commands, test_cmd, ci_read, ci_seen, tree)
    notes += setup_questions

    components_proposal, cannot = _components_proposal(stacks)
    fields["components"] = components_proposal

    if dotnet_note and dotnet_note not in notes:
        notes.append(dotnet_note)

    questions = [p.note for p in fields.values() if not p.known and p.note]
    questions += notes
    if tree.unreadable:
        questions.append(
            f"{len(tree.unreadable)} director{'y' if len(tree.unreadable) == 1 else 'ies'} could "
            f"not be opened ({', '.join(tree.unreadable[:3])}) — anything under them is missing "
            "from this proposal, and that absence is a permissions problem, not a finding"
        )

    known_fields = set(Manifest.model_fields)
    not_attempted = sorted(known_fields - set(_ATTEMPTED))

    # WHAT THE PIPELINES ACTUALLY RUN, verbatim and deduplicated, newest evidence first (#176).
    # `convention`, `makefile` and `package_json` are excluded on purpose: a target this repo
    # OFFERS is not a step anything runs before a change lands, and reporting one as undeclared
    # would ask the client to declare a command nobody invokes.
    _CI_SOURCES = {"github_actions", "azure_pipelines", "gitlab_ci", "circleci", "travis",
                   "buildspec", "jenkins"}
    ci_commands: list[Candidate] = []
    seen_ci: set[tuple[str, str]] = set()
    for cmd in sorted(commands, key=lambda c: c.sort_key()):
        if cmd.source not in _CI_SOURCES:
            continue
        # DEDUPED BY (command, file), NOT BY LINE. A named check's value is the WHOLE step, and
        # the loop above emits one entry per unclassified line inside it — so a thirteen-line
        # deploy block arrived thirteen times, identical but for a line number. Measured: 81
        # entries where the pipelines run about twenty things.
        key = (cmd.command, cmd.evidence.path)
        if key in seen_ci:
            continue
        seen_ci.add(key)
        ci_commands.append(Candidate(value=cmd.command, confidence=_tier(cmd),
                                     evidence=[cmd.evidence], why=cmd.named or cmd.role))

    # THE ROLE TABLE'S OWN WORDS. `_ROLE_PATTERNS` says `type`, the manifest key is `types`, and
    # a set written from the manifest's spelling matches nothing — the silent kind of wrong, since
    # it just makes every file look like a deploy pipeline.
    _CHECK_ROLES = {"test", "lint", "security", "type"}
    with_checks = sorted({cmd.evidence.path for cmd in commands
                          if cmd.source in _CI_SOURCES and cmd.role in _CHECK_ROLES})

    return ManifestProposal(
        repo=str(root.resolve()),
        fields=fields,
        ci_commands=ci_commands,
        ci_files_with_checks=with_checks,
        stacks=stacks,
        cannot_express=cannot,
        questions=questions,
        ci_files_read=ci_read,
        ci_files_seen=ci_seen,
        not_attempted=not_attempted,
        files_walked=tree.walked,
        files_considered=len(tree.files),
        truncated=tree.truncated,
        unreadable_dirs=tree.unreadable,
    )


# --- rendering ----------------------------------------------------------------------------


def to_manifest_dict(proposal: ManifestProposal) -> dict[str, Any]:
    """The subset of a manifest this proposal is prepared to assert, as a dict that
    `Manifest.model_validate` accepts.

    Only `observed` and `inferred` fields appear. An `unknown` field is OMITTED rather than
    written empty: `setup: []` in a YAML file reads as "this project needs no install", which is a
    claim, and the whole point of the third tier is that we are not making it. The report says
    what is missing; the file never pretends.
    """
    out: dict[str, Any] = {"version": 1}
    base = proposal.fields.get("base_branch")
    if base and base.known:
        out["base_branch"] = base.value

    setup = proposal.fields.get("setup")
    if setup and setup.known and setup.value:
        out["setup"] = list(setup.value)

    validation: dict[str, str] = {}
    for role in ("test", "lint"):
        field = proposal.fields.get(f"validate.{role}")
        if field and field.known:
            validation[role] = field.value
    if validation:
        out["validate"] = validation

    components = proposal.fields.get("components")
    if components and components.known and components.value:
        out["components"] = components.value
    return out


def propose(repo_path: str | Path) -> dict[str, dict[str, Any]]:
    """The flat, JSON-shaped view of a proposal: `{field: {value, source, confidence, note}}`.

    WHAT ACTUALLY CALLS WHAT, measured rather than intended. An earlier version of this docstring
    called this function "THE CALL "
                         "SITE" that `openfactory env read` consumes. It is not, and the reason
    is a name collision in our own package: `openfactory/onboarding/__init__.py` re-exports a
    FUNCTION
    called `infer`, which shadows the SUBMODULE of the same name, so the action layer's
    `from openfactory.onboarding import infer` binds the function. Its resolver
    (`openfactory/actions/catalog.py::_entry_point`, which tries `propose` then `infer` then "is it
    callable?") therefore lands on `infer` — measured on this machine:

        type(openfactory.onboarding.infer) -> <class 'function'>
        _entry_point(...)           -> infer   (not propose)

    That resolution is the BETTER one and must not be "fixed" into calling this function: `infer()`
    returns the rich object, and `cannot_express`, `questions`, `stacks` and `unreadable_dirs` —
    the whole client-2 block of the report, the strongest thing `openfactory env read` prints —
    exist only
    on that object and cannot be expressed in this flat shape. Removing the re-export to
    disambiguate the name would silently delete that block from the report.

    So this is the adapter for a caller that asks for it BY NAME (`from openfactory.onboarding
    import
    propose`, or `getattr` on the submodule) and wants JSON rather than pydantic — an HTTP surface,
    a panel, a diff between two runs. Today the only such callers are its own tests. Said plainly
    because "a capability nothing reaches does not exist" is a rule this codebase has paid for
    twenty-one times, and a docstring that asserts the reach it wishes it had is how the count
    got that high.

    Field keys are the dotted manifest path, so a caller can write them straight into a manifest:
    `base_branch`, `setup`, `validate.test`, `validate.lint`, and either `components` (when there
    is nothing to declare, or nothing declarable) or `components.<name>.path` /
    `components.<name>.stack` per component.
    """
    proposal = infer(repo_path)
    out: dict[str, dict[str, Any]] = {}

    def emit(key: str, field: Proposal, value: Any = ...) -> None:
        out[key] = {
            "value": field.value if value is ... else value,
            "source": (field.evidence[0].locator if field.evidence else ""),
            "confidence": field.confidence,
            "note": field.note,
        }

    for key in ("base_branch", "setup", "validate.test", "validate.lint"):
        field = proposal.fields.get(key)
        if field is not None:
            emit(key, field)

    components = proposal.fields.get("components")
    if components is not None:
        if components.known and components.value:
            for name, body in sorted(components.value.items()):
                for attribute in ("path", "stack"):
                    emit(f"components.{name}.{attribute}", components, body[attribute])
        else:
            # `{}` and `None` both arrive here and they are NOT the same statement — `{}` is
            # "we read it: one stack, repo-wide gates are right" (and it is `observed`), `None` is
            # "there are areas here and we cannot express them" (and it is `unknown`). The value
            # must not be forced into one shape to make the caller's life easier: a caller that
            # keys off the value would write `components: {}` into a manifest for a repository
            # whose components we refused to name.
            emit("components", components)
    return out


def render_yaml(proposal: ManifestProposal) -> str:
    """`env-proposal.yaml` — never `.openfactory/project.yaml`, and this function writes neither.

    Every proposed line carries its tier and its citation as a comment, and every field we could
    NOT determine appears as a commented question rather than as an absence. A reviewer reading
    only this file has to be able to see the holes; a file that is silent about them is how a
    client reads a partial proposal as a complete one.
    """
    lines = [
        "# PROPOSED — not a manifest yet. Generated by reading the repository; nothing was run.",
        f"# repository: {proposal.repo}",
        "# Each field carries its tier: observed (read from a file you wrote) · inferred (a",
        "# convention your stack implies) · unknown (left for you, never guessed).",
        "",
        "version: 1",
    ]

    def emit(field: str, key: str, renderer: Any) -> None:
        proposal_field = proposal.fields.get(field)
        if proposal_field is None:
            return
        if not proposal_field.known:
            lines.append("")
            lines.append(f"# {key}: UNKNOWN — not guessed.")
            for chunk in _wrap(proposal_field.note):
                lines.append(f"#   {chunk}")
            return
        lines.append("")
        citation = ", ".join(e.locator for e in proposal_field.evidence) or "(no citation)"
        lines.append(f"# {proposal_field.confidence} · {citation}")
        for chunk in _wrap(proposal_field.note):
            lines.append(f"#   {chunk}")
        lines.extend(renderer(proposal_field.value))

    emit("base_branch", "base_branch", lambda v: [f"base_branch: {v}"])
    emit(
        "setup",
        "setup",
        lambda v: (["setup: []"] if not v else ["setup:"] + [f'  - "{c}"' for c in v]),
    )

    test = proposal.fields.get("validate.test")
    lint = proposal.fields.get("validate.lint")
    lines.append("")
    if (test and test.known) or (lint and lint.known):
        lines.append("validate:")
        for role, field in (("test", test), ("lint", lint)):
            if field and field.known:
                citation = ", ".join(e.locator for e in field.evidence) or "(no citation)"
                lines.append(f"  # {field.confidence} · {citation}")
                lines.append(f'  {role}: "{field.value}"')
    for role, field in (("test", test), ("lint", lint)):
        if field and not field.known:
            lines.append(f"# validate.{role}: UNKNOWN — not guessed.")
            for chunk in _wrap(field.note):
                lines.append(f"#   {chunk}")

    emit("components", "components", _render_components)

    if proposal.cannot_express:
        lines.append("")
        lines.append("# CANNOT BE EXPRESSED in this schema:")
        for entry in proposal.cannot_express:
            for chunk in _wrap(entry):
                lines.append(f"#   {chunk}")
    return "\n".join(lines) + "\n"


def _render_components(value: dict[str, dict[str, str]]) -> list[str]:
    if not value:
        return ["components: {}"]
    out = ["components:"]
    for name in sorted(value):
        out.append(f"  {name}:")
        for key in sorted(value[name]):
            out.append(f"    {key}: {value[name][key]}")
    return out


def _wrap(text: str, width: int = 92) -> list[str]:
    if not text:
        return []
    words, line, out = text.split(), "", []
    for word in words:
        if line and len(line) + 1 + len(word) > width:
            out.append(line)
            line = word
        else:
            line = f"{line} {word}".strip()
    if line:
        out.append(line)
    return out


def render_report(proposal: ManifestProposal) -> str:
    """The three blocks a human reads: what we propose, what only they can answer, and what this
    platform has no way to express."""
    out: list[str] = []
    out.append(f"repository: {proposal.repo}")
    out.append(
        f"read {len(proposal.ci_files_read)} CI/build file(s)"
        + (f": {', '.join(proposal.ci_files_read)}" if proposal.ci_files_read else "")
    )
    if proposal.ci_files_seen:
        out.append(
            "CI-shaped files found but NOT read by this pass (so 'no CI' is not the finding): "
            + ", ".join(proposal.ci_files_seen)
        )
    if proposal.truncated:
        out.append(
            f"WALK TRUNCATED: this repository has {proposal.files_walked} paths and only the "
            f"{proposal.files_considered} shallowest were read — anything deeper is missing from "
            "this proposal, and that absence is a ceiling, not a finding"
        )
    if proposal.unreadable_dirs:
        out.append(
            f"{len(proposal.unreadable_dirs)} directory/ies could not be opened: "
            + ", ".join(proposal.unreadable_dirs[:5])
        )
    out.append("")

    out.append("STACKS")
    if not proposal.stacks:
        out.append("  none detected")
    for sighting in proposal.stacks:
        mark = "" if sighting.expressible else "   [no preset — see CANNOT EXPRESS]"
        cite = sighting.evidence[0].locator if sighting.evidence else "?"
        out.append(f"  {sighting.stack:<12} {sighting.confidence:<9} {cite}{mark}")
    out.append("")

    out.append("PROPOSED")
    proposed = proposal.proposed()
    if not proposed:
        out.append("  (nothing — every field is below)")
    for field in proposed:
        citation = ", ".join(e.locator for e in field.evidence) or "(no citation)"
        out.append(f"  {field.field:<16} [{field.confidence}] {_show(field.value)}")
        out.append(f"  {'':<16} └ {citation}")
        for chunk in _wrap(field.note, 88):
            out.append(f"  {'':<16}   {chunk}")
        for candidate in field.candidates[1:]:
            other = candidate.evidence[0].locator if candidate.evidence else "?"
            out.append(f"  {'':<16}   also found: {_show(candidate.value)}  ({other})")
    out.append("")

    out.append("I DO NOT KNOW — only you can answer")
    unknowns = proposal.unknowns()
    if not unknowns:
        out.append("  (nothing)")
    for field in unknowns:
        out.append(f"  {field.field}")
        for chunk in _wrap(field.note, 88):
            out.append(f"      {chunk}")
    out.append("")

    out.append("I CANNOT EXPRESS THIS")
    if not proposal.cannot_express:
        out.append("  (nothing — everything found fits the schema)")
    for entry in proposal.cannot_express:
        for chunk in _wrap(entry, 92):
            out.append(f"  {chunk}")
    out.append("")

    out.append("NOT ATTEMPTED by this pass (read as unverified, not as absent):")
    for chunk in _wrap(", ".join(proposal.not_attempted), 92):
        out.append(f"  {chunk}")
    return "\n".join(out) + "\n"


def _show(value: Any) -> str:
    if isinstance(value, list):
        return "[]" if not value else " && ".join(str(v) for v in value)
    if isinstance(value, dict):
        return "{}" if not value else ", ".join(f"{k}={v.get('path')}" for k, v in value.items())
    return str(value)
