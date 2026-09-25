"""The battery asked of the product role, through the one door, and the record of how it did.

THROUGH THE DOOR, NEVER AROUND IT (ADR-0051 D12). Each question becomes a `Message` and goes to
`engine.turn` — the same call the panel's turn makes — with a real `ProductModule` over the
fixture: the real loader reads its context repository, the real workspace mounts its code, and
the real role writes the prompt. The ONE thing a caller may replace is the model at the harness
boundary (`agent`, `judge`), which is what the suite does and what `make eval-product` does not.
So a score measures the role a person meets, and a change to any stage of the turn moves it.

A QUESTION IS ASKED BY A STRANGER, FIRST TIME. Every question has a conversation of its own, and
the run keeps no memory: the metrics sink the transcript and the loops write to is `null` for
its whole length, and its state — the repository cache, the board, the memory index — lives in a
directory made for the run and removed after it. So a score does not depend on the order the
questions are in, and a run leaves nothing in the operator's own stores. What the model is
handed is the fixture and the question: nothing from this machine's projects reaches a prompt.

THE CONTEXT REPOSITORY IS SERVED FROM THE FIXTURE. On the one-machine row a context repository
lives under the operator's home (`LocalForge.clone_url`), and this run must not touch it; the
loader takes its checkouts from the `cache` it is handed, and the run hands it one that answers
the context repository's key with the fixture's own. The source repository needs no such help:
on the local row the project's own repository IS its `repo_path`.

A LIVE RUN NEVER HAPPENS INSIDE THE SUITE. With no `agent` or no `judge` handed in, this builds
the deployment's own harnesses and spends tokens — refused by name when pytest is running, so a
test that forgot its doubles fails instead of paying.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import shutil
import subprocess
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

import yaml
from pydantic import BaseModel, Field

from openfactory.product.evaluation.battery import NO_QUESTIONS, Battery, BatteryRefused, Question
from openfactory.product.evaluation.score import Judge, Tally, Verdict, score, totals

log = logging.getLogger("openfactory.product.evaluation")

#: The checkout this module sits in. The battery is a maintainer's instrument: its fixture lives in
#: the suite's tree, which a wheel does not carry, and the CLI says so when it is absent.
ROOT = Path(__file__).resolve().parents[3]
FIXTURES = ROOT / "tests" / "fixtures" / "evaluation"
DEFAULT_FIXTURE = FIXTURES / "larkledger"
DEFAULT_RESULTS = FIXTURES / "results"
QUESTIONS_FILE = "questions.yaml"

#: Who says each question, by audience (decision 8). The admin is on the product's allowlist and
#: the other two are not — the one difference today's role can see; slice 4 makes a speaker a
#: person with a role per product, and the battery already asks from all three.
SPEAKERS = {"client": "evaluation-client", "product admin": "evaluation-admin",
            "engineer": "evaluation-engineer"}

#: Provenance on every message and on the module: what asked, never a permission.
VIA = "evaluation"

#: The judging axis the judge runs on. The REVIEWER's, because it is the platform's independent
#: reader of somebody else's work — and a separate axis from the product role's, so a deployment
#: can judge with another engine than the one being judged.
JUDGE_ROLE = "reviewer"
JUDGE_PHASE = "evaluation_judge"


class FixtureRefused(ValueError):
    """The fixture is not a product the module accepts, with the reason it gave."""


class LiveRunRefused(RuntimeError):
    """A live run was asked for where none may happen."""


# ── the fixture, as the product module reads a product ──────────────────────────────────────────

def fixture_name(fixture: str | Path) -> str:
    """The product the fixture is: the `product:` its context repository declares."""
    manifest = Path(fixture) / "context" / ".openfactory" / "product.yaml"
    try:
        data = yaml.safe_load(manifest.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError) as exc:
        raise FixtureRefused(f"{manifest} could not be read: {exc}") from exc
    name = str(data.get("product") or "").strip() if isinstance(data, dict) else ""
    if not name:
        raise FixtureRefused(f"{manifest} names no `product:`")
    return name


def _git(repo: Path, *args: str) -> None:
    proc = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True,
                          timeout=120, check=False)
    if proc.returncode != 0:
        raise FixtureRefused(f"git {' '.join(args)} failed in {repo}: "
                             f"{(proc.stderr or proc.stdout).strip()[:300]}")


def _repository(src: Path, dest: Path) -> Path:
    """`src` as a git repository at `dest`: its files, one commit, on `main`."""
    shutil.copytree(src, dest)
    _git(dest, "init", "-q", "-b", "main")
    # the repository's own identity and no signing: a maintainer's global git configuration must
    # not decide whether the fixture can be committed
    _git(dest, "config", "user.name", "evaluation")
    _git(dest, "config", "user.email", "evaluation@example.invalid")
    _git(dest, "config", "commit.gpgsign", "false")
    _git(dest, "add", "-A")
    _git(dest, "commit", "-qm", "the fixture")
    return dest


def materialise(fixture: str | Path, into: Path) -> tuple[Path, Path]:
    """The fixture's two repositories, made real under `into`: `(context, source)`."""
    root, name = Path(fixture), fixture_name(fixture)
    into.mkdir(parents=True, exist_ok=True)
    return (_repository(root / "context", into / f"{name}-context"),
            _repository(root / "source", into / name))


def fixture_project(name: str, source: Path):
    """The registry entry of a one-machine product (ADR-0049): every axis local, the project's
    own repository its source, and the context repository the product declares."""
    from openfactory.contracts.product import ProductConfig
    from openfactory.contracts.project import Project, ProviderRef

    local = {"kind": "local", "repo": name, "options": {}}
    return Project(name=name, repo_path=str(source),
                   tracker=ProviderRef(**local), forge=ProviderRef(**local),
                   ci=ProviderRef(kind="none", repo=name, options={}),
                   product=ProductConfig(docs_repo=f"{name}-context",
                                         admins=[SPEAKERS["product admin"]]))


class _FixtureCheckouts:
    """The loader's `cache`, answering the context repository's key with the fixture's own.

    Every other key — none today — goes where its URL says. The checkout is still a real
    `RepoCache` clone, so the loader reads what it always reads."""

    def __init__(self, cache, context: Path) -> None:
        self._cache = cache
        self._context = context

    def sync(self, project: str, clone_url: str, base_branch: str = ""):
        from openfactory.product.loader import DOCS_CACHE_SUFFIX

        url = str(self._context) if project.endswith(DOCS_CACHE_SUFFIX) else clone_url
        return self._cache.sync(project, url, base_branch)


def load_fixture(fixture: str | Path, workdir: Path):
    """`(project, context)` for the fixture, through the product loader. Call inside `isolated`,
    which is what points the repository cache at `workdir`."""
    from openfactory.product.loader import load_product_context
    from openfactory.runtime.repo_cache import RepoCache

    context_repo, source = materialise(fixture, workdir / "repositories")
    project = fixture_project(fixture_name(fixture), source)
    ctx = load_product_context(project, cache=_FixtureCheckouts(RepoCache(), context_repo))
    return project, ctx


@contextmanager
def isolated(workdir: Path) -> Iterator[None]:
    """This process's stores pointed into `workdir` for the length of a run, and put back.

    The metrics sink is `null`: the transcript, the loops and the metering all write there, and a
    run that wrote into the operator's own would leave a battery's conversations in a real
    project's memory — and let one question remember another."""
    values = {
        "OPENFACTORY_METRICS_SINK": "null",
        "OPENFACTORY_REPO_CACHE": str(workdir / "cache"),
        "OPENFACTORY_LOG_DIR": str(workdir / "logs"),
        "OPENFACTORY_BOARD_DB": str(workdir / "board.db"),
        "OPENFACTORY_REGISTRY": str(workdir / "registry.yaml"),
    }
    dropped = ("OPENFACTORY_METRICS_TABLE", "OPENFACTORY_METRICS_DB")
    saved = {k: os.environ.get(k) for k in (*values, *dropped)}
    os.environ.update(values)
    for k in dropped:
        os.environ.pop(k, None)
    try:
        yield
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


# ── the record ──────────────────────────────────────────────────────────────────────────────────

class Harness(BaseModel):
    """Which engine and which model — `model` None is the harness's own default."""

    harness: str
    model: str | None = None


class Answer(BaseModel):
    """One question, what the role said, and the three verdicts on it."""

    id: str
    audience: str
    question: str
    answer: str
    #: every reply the turn earned, receipts included, in order — `kind: text`
    replies: list[dict] = Field(default_factory=list)
    correct: Verdict
    cited: Verdict
    abstained_correctly: Verdict
    abstained: bool | None
    seconds: float


class Record(BaseModel):
    """One run of the battery: what was asked of what, and how it did."""

    fixture: str
    questions_file: str
    questions_sha256: str
    started_at: str
    finished_at: str
    commit: str
    #: uncommitted changes in the checkout the run came from — its score is not that commit's
    dirty: bool | None
    role: Harness
    judge: Harness
    totals: dict[str, Tally]
    answers: list[Answer]


def checkout_state(root: Path = ROOT) -> tuple[str, bool | None]:
    """`(sha, dirty)` of the checkout the battery runs from — `("unknown", None)` outside one."""
    def git(*args: str) -> subprocess.CompletedProcess:
        return subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True,
                              timeout=60, check=False)

    head = git("rev-parse", "HEAD")
    if head.returncode != 0:
        return "unknown", None
    status = git("status", "--porcelain")
    return head.stdout.strip(), (bool(status.stdout.strip()) if status.returncode == 0 else None)


def _described(harness, *, project, role: str, built: bool) -> Harness:
    """What answered. A harness this run BUILT is described by the configuration it was built
    from — the same resolution the registry used; one handed in says its own name and model."""
    from openfactory.adapters.agent.registry import harness_kind, model_for

    if built:
        return Harness(harness=harness_kind(project, role), model=model_for(project, role))
    return Harness(harness=str(getattr(harness, "name", "") or type(harness).__name__),
                   model=getattr(harness, "model", None))


def bind_judge(harness, project, room: Path) -> Judge:
    """The judge as the scorer takes it — a prompt in, the text out — over any harness that can
    `ask`. It stands in an empty directory: the answer key is in the prompt, and there is nothing
    for it to open."""
    from openfactory.adapters.agent.base import final_text
    from openfactory.adapters.sandbox.base import Workspace
    from openfactory.adapters.sandbox.registry import judging_worktree

    room.mkdir(parents=True, exist_ok=True)
    sandbox = judging_worktree(project, root=room)
    workspace = Workspace(path=room, branch="main", base_branch="main")

    def ask(prompt: str) -> str | None:
        res = harness.ask(sandbox=sandbox, workspace=workspace, prompt=prompt, phase=JUDGE_PHASE)
        return final_text(res) if getattr(res, "ok", False) else None

    return ask


# ── the run ─────────────────────────────────────────────────────────────────────────────────────

def _under_test() -> bool:
    return bool(os.environ.get("PYTEST_CURRENT_TEST"))


def run(battery: Battery, *, fixture: str | Path, workdir: Path, questions_file: str | Path = "",
        agent=None, judge=None,
        on_answer: Callable[[int, int, Answer], None] | None = None) -> Record:
    """Ask every question of the role, score each answer, and return the record.

    `agent` is the product role's harness and `judge` the judge's; either left out is built from
    this deployment's configuration, which is a live model — refused inside the suite."""
    if not battery.questions:
        raise BatteryRefused(NO_QUESTIONS)
    if (agent is None or judge is None) and _under_test():
        raise LiveRunRefused(
            "the evaluation battery asks a live model and spends tokens, so it never runs inside "
            "the test suite — hand `run` a scripted `agent` and `judge`, or run `make "
            "eval-product`")
    from openfactory.product import engine
    from openfactory.product.module import ProductModule

    started = datetime.now(UTC)
    commit, dirty = checkout_state()
    source = Path(questions_file) if questions_file else Path(fixture) / QUESTIONS_FILE
    digest = hashlib.sha256(source.read_bytes()).hexdigest() if source.is_file() else ""
    answers: list[Answer] = []
    with isolated(workdir):
        project, ctx = load_fixture(fixture, workdir)
        if not ctx.available:
            raise FixtureRefused(f"the fixture at {fixture} is not a product the module "
                                 f"accepts: {ctx.reason}")
        built_agent, built_judge = agent is None, judge is None
        if built_agent:
            from openfactory.adapters.agent.registry import build_product

            agent = build_product(project)
        if built_judge:
            from openfactory.adapters.agent.registry import build_asker

            judge = build_asker(project, role=JUDGE_ROLE)
        ask_judge = bind_judge(judge, project, workdir / "judge")
        for n, q in enumerate(battery.questions, 1):
            answer = _ask(engine, ProductModule, project, ctx, agent, q, judge=ask_judge)
            answers.append(answer)
            if on_answer is not None:
                on_answer(n, len(battery.questions), answer)
        role = _described(agent, project=project, role="product", built=built_agent)
        judged_by = _described(judge, project=project, role=JUDGE_ROLE, built=built_judge)
    return Record(fixture=fixture_name(fixture), questions_file=_shown(source),
                  questions_sha256=digest, started_at=_stamp(started),
                  finished_at=_stamp(datetime.now(UTC)), commit=commit, dirty=dirty,
                  role=role, judge=judged_by, totals=totals(answers), answers=answers)


def _ask(engine, module_type, project, ctx, agent, q: Question, *, judge: Judge) -> Answer:
    """One question, in a conversation of its own, through the turn engine — and its verdicts.

    The module is built fresh for the message, as every surface builds it: one conversation must
    not carry another's state."""
    module = module_type(project, context=ctx, agent=agent, via=VIA)
    message = engine.Message(project=project.name, conversation=f"evaluation-{q.id}",
                             speaker=SPEAKERS[q.audience], text=q.question, via=VIA)
    began = time.monotonic()
    replies = engine.turn(project, message, module=module)
    seconds = round(time.monotonic() - began, 2)
    # what the person reads: the receipt ("I am on it") carries no answer and is not scored
    said = "\n\n".join(r.text for r in replies if r.kind == "answer").strip()
    verdicts = score(q, said, judge=judge)
    return Answer(id=q.id, audience=q.audience, question=q.question, answer=said,
                  replies=[{"kind": r.kind, "text": r.text} for r in replies],
                  correct=verdicts.correct, cited=verdicts.cited,
                  abstained_correctly=verdicts.abstained_correctly,
                  abstained=verdicts.abstained, seconds=seconds)


def _stamp(when: datetime) -> str:
    return when.strftime("%Y-%m-%dT%H:%M:%SZ")


def _shown(path: Path) -> str:
    """A path as the record shows it: relative to the checkout when it is inside it."""
    try:
        return str(path.resolve().relative_to(ROOT))
    except ValueError:
        return str(path)


# ── writing it down ─────────────────────────────────────────────────────────────────────────────

_NAMES = {"correct": "correct", "cited": "cited", "abstained_correctly": "abstained correctly"}


def _cell(v: Verdict) -> str:
    if v.passed is None:
        return v.decided_by
    return f"{'yes' if v.passed else 'no'} · {v.decided_by}"


def _model(h: Harness) -> str:
    return f"{h.harness}, model {h.model or 'the harness default'}"


def summary(record: Record) -> str:
    """The short markdown beside the JSON: what ran, the totals, one line per question."""
    state = {True: " (with uncommitted changes)", False: "", None: " (checkout state unknown)"}
    lines = [
        f"# Product role evaluation — {record.fixture}",
        "",
        f"- **run:** {record.started_at} → {record.finished_at}",
        f"- **commit:** {record.commit}{state[record.dirty]}",
        f"- **role:** {_model(record.role)}",
        f"- **judge:** {_model(record.judge)}",
        f"- **questions:** {len(record.answers)}, from {record.questions_file} "
        f"(sha256 {record.questions_sha256[:12]})",
        "",
        "| verdict | passed | failed | undecided | not applicable |",
        "|---|---|---|---|---|",
    ]
    for key, name in _NAMES.items():
        t = record.totals[key]
        lines.append(f"| {name} | {t.passed} | {t.failed} | {t.undecided} | {t.not_applicable} |")
    lines += ["", "| question | audience | correct | cited | abstained correctly |",
              "|---|---|---|---|---|"]
    for a in record.answers:
        lines.append(f"| {a.id} | {a.audience} | {_cell(a.correct)} | {_cell(a.cited)} | "
                     f"{_cell(a.abstained_correctly)} |")
    lines += ["", "Why each verdict went the way it did, and every answer in full, are in the "
                  "JSON record beside this file."]
    return "\n".join(lines) + "\n"


def write_record(record: Record, results: str | Path) -> tuple[Path, Path]:
    """The record as `<started>-<fixture>.json` and `.md` under `results` — dated, so a run never
    overwrites the one before it."""
    out = Path(results)
    out.mkdir(parents=True, exist_ok=True)
    stem = f"{record.started_at.replace(':', '')}-{record.fixture}"
    as_json, as_md = out / f"{stem}.json", out / f"{stem}.md"
    as_json.write_text(json.dumps(record.model_dump(mode="json"), indent=2, ensure_ascii=False)
                       + "\n", encoding="utf-8")
    as_md.write_text(summary(record), encoding="utf-8")
    return as_json, as_md
