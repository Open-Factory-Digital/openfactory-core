"""Session-wide guarantees for the test suite.

The one that matters: **a test can never hold a credential that acts on something real.**

This is not hypothetical. `openfactory/cli.py` used to call `load_dotenv()` at module import time, so any
test that imported it — directly or transitively — pulled the whole of `.env` into the process:
live GitHub App credentials for a client's repository, a Slack bot token, a Temporal API key, a
Claude OAuth token. Under `pytest-randomly` the tests that ran afterwards inherited them, and two
of them made a real authenticated HTTPS call to GitHub, surfacing as a `ReadTimeout` that vanished
in isolation.

The import-time load is fixed at its source. This is the floor underneath it, because the fix and
the floor fail differently: the fix can be undone by the next person who adds a convenience import
of `load_dotenv`, and nothing about that change would look dangerous in review.
"""

from __future__ import annotations

import os
import re
import shutil
import tempfile
from pathlib import Path

import pytest

#: Everything that would let a test ACT on real infrastructure. Deliberately not "every secret" —
#: the criterion is authority, not confidentiality.
LIVE_CREDENTIALS = (
    # the forge: create issues, comment, push, merge
    "OPENFACTORY_GH_APP_ID",
    "OPENFACTORY_GH_APP_INSTALLATION_ID",
    "OPENFACTORY_GH_APP_KEY",
    "OPENFACTORY_GH_APP_KEY_CONTENT",
    "OPENFACTORY_BOT_TOKEN",
    "GITHUB_TOKEN",
    "GH_TOKEN",
    # the channel: post to a client's workspace
    "SLACK_BOT_TOKEN",
    "SLACK_APP_TOKEN",
    "SLACK_SIGNING_SECRET",
    # the durable engine: start and signal real workflows
    "TEMPORAL_API_KEY",
    "TEMPORAL_TLS_CERT",
    "TEMPORAL_TLS_KEY",
    # the harness: spend money
    "CLAUDE_CODE_OAUTH_TOKEN",
    "ANTHROPIC_API_KEY",
    # the cloud: launch tasks, write telemetry
    "AWS_ACCESS_KEY_ID",
    "AWS_SECRET_ACCESS_KEY",
    "AWS_SESSION_TOKEN",
    "AWS_PROFILE",
)


def _axis_overrides() -> tuple[str, ...]:
    """The deployment's OPINIONS about which harness, model and auth route to use.

    Not credentials — configuration — and it leaks by the same route and does the same damage. A
    `.env` carrying `OPENFACTORY_EXECUTOR_MODEL=opus` reaches the session through any entry point that
    loads it, outlives the test that called one, and then every later test resolves a model the
    developer's machine chose rather than the one the test declared. Assertions about the harness
    axis silently measure `.env`; under `pytest-randomly` a different set each run.

    It surfaced when the OpenCode adapter started refusing a model with no `provider/` prefix:
    29 tests failed on a random seed and none on a fixed one, which is the signature of a leak
    rather than a flake — the same signature the credential half of this file was written for.

    DERIVED from the registries rather than listed, so a new role or a new override cannot join
    the axis and quietly stay out of the strip."""
    from openfactory.adapters.agent.registry import ROLE_MODELS, ROLES

    return (*ROLES.values(), *ROLE_MODELS.values(), "OPENFACTORY_PLANNER_MODEL",
            # what `routes.py` reads to decide where the harness talks
            "OPENFACTORY_HARNESS_ENDPOINT", "ANTHROPIC_BASE_URL",
            "CLAUDE_CODE_USE_BEDROCK", "CLAUDE_CODE_USE_VERTEX")


def _strip() -> None:
    """Delete rather than blank: `os.environ["X"] = ""` still satisfies `"X" in os.environ`, and
    several call sites test membership rather than truthiness."""
    import os

    for name in (*LIVE_CREDENTIALS, *_axis_overrides()):
        os.environ.pop(name, None)


@pytest.fixture(autouse=True, scope="session")
def _no_live_credentials_at_import() -> None:
    """Strip before anything is collected.

    Session scope is what catches an IMPORT-time loader — the failure that started this. A
    function-scoped fixture runs after every module has already been imported, by which time the
    damage is done.
    """
    _strip()


@pytest.fixture(autouse=True, scope="session")
def _git_asks_this_suite_who_it_is() -> object:
    """The suite commits as ITSELF, never as whoever happens to own the machine.

    Dozens of tests build a real repository and commit into it. Thirty-one of them pass
    `-c user.name=… -c user.email=…`; six do not, and those six borrowed the developer's global
    git config. On a machine that has no identity — a fresh CI runner, a container, a new
    contributor's laptop before their first commit — git refuses with *"Please tell me who you
    are"* and exits 128. It passed here for the same reason everything else did: this machine has
    an identity, so the dependency was invisible.

    A CONFIG FILE, NOT `GIT_AUTHOR_*`. The environment variables would win over a test's own
    `-c user.email=…`, and `test_product_authoring.py` reads `%an <%ae>` back to prove the bot
    signed a commit — that assertion must keep measuring what the product does, not what this
    fixture does. `GIT_CONFIG_GLOBAL` sits below command-line config, which is exactly the rank a
    default should have.

    It also cuts the OTHER ambient dependencies in the same stroke: a developer with
    `commit.gpgsign = true` cannot run this suite at all, and `init.defaultBranch` differs between
    machines — both are the machine leaking into the measurement."""
    config = Path(tempfile.mkdtemp(prefix="openfactory-suite-git")) / "gitconfig"
    config.write_text(
        "[user]\n\tname = OpenFactory Suite\n\temail = suite@openfactory.invalid\n"
        "[commit]\n\tgpgsign = false\n"
        "[tag]\n\tgpgsign = false\n"
        "[gpg]\n\tformat = openpgp\n"
    )
    patch = pytest.MonkeyPatch()
    patch.setenv("GIT_CONFIG_GLOBAL", str(config))
    patch.setenv("GIT_CONFIG_SYSTEM", os.devnull)
    yield
    patch.undo()
    shutil.rmtree(config.parent, ignore_errors=True)


#: A CACHE ROOT PER WORKER (#185). `RepoCache()` built with no root asks `default_root()`, whose
#: fallback is ONE fixed `/tmp` directory — so a `-n auto` run has several workers cloning
#: different repositories into the same tree and swapping it under one another. The loser's
#: pre-flight degrades with "clone: could not reach the repo — proceeding UNSIZED", which is
#: indistinguishable from the live #37 bug the offline harness exists to catch. It cost most of a
#: day of intermittency wearing two different masks — `test_local_flow` and `test_preflight`,
#: never the same one twice, roughly one run in three.
#:
#: SET ONLY WHEN NOBODY ELSE DID, so a test that wants its own root still says so and wins.
@pytest.fixture(autouse=True)
def _repo_cache_is_not_shared_between_workers(monkeypatch, tmp_path_factory, request) -> None:
    if os.environ.get("OPENFACTORY_REPO_CACHE"):
        return
    worker = getattr(getattr(request.config, "workerinput", None), "get", lambda *_: None)(
        "workerid") or os.environ.get("PYTEST_XDIST_WORKER") or "main"
    monkeypatch.setenv("OPENFACTORY_REPO_CACHE",
                       str(tmp_path_factory.getbasetemp() / f"repo-cache-{worker}"))


@pytest.fixture(autouse=True)
def _no_tree_pollution_by_url_paths() -> None:
    """Fail the test that treats a clone URL as a filesystem path in the repository root.

    Found as debris, not as a failure: `https:/github.com/acme/demo.git/knowledge/*.yaml` and
    `https:/…/.sdlc-logs/…` sitting untracked in the repo root (2026-08-02, -06, -13) — some
    caller handed `Path("https://…")` to a writer, the write SUCCEEDED into a directory literally
    named `https:`, and every suite run stayed green. The polluter fires rarely (ordering-
    dependent; four full-suite spy runs could not reproduce the 08-13 write), which is exactly
    why absence-of-debris cannot be the check: this trips inside the polluting test itself, the
    one time it runs.
    """
    yield
    for stray in ("https:", "http:"):
        if os.path.exists(stray):
            found = [str(p) for p in Path(stray).rglob("*") if p.is_file()][:5]
            shutil.rmtree(stray, ignore_errors=True)  # keep ONE test red, not every test after
            pytest.fail(
                f"this test wrote through a clone URL treated as a path: ./{stray} now exists "
                f"(e.g. {found}) — find the Path(url) and route it through resolve_repo_path"
            )


@pytest.fixture(autouse=True)
def _no_live_credentials_per_test() -> None:
    """Strip again before each test, because the session fixture only runs once and the code
    under test puts them back.

    Two ways that happens, both legitimate for the function and poisonous for the session:

        `materialize_app_key` WRITES `OPENFACTORY_GH_APP_KEY` into `os.environ` — that is its job, and
        `test_fargate_entrypoint` asserts it. The value then outlives the test.

        `load_dotenv()` still lives inside `worker.main`, `starter`, `schedule` and the Slack bot.
        Those are entry points and are right to load it; a test that calls one re-imports the whole
        of `.env` into the session.

    Session-scope alone therefore protects only the tests that run first, which under
    `pytest-randomly` is a different set every time — the exact shape of the bug this file exists
    to end.
    """
    _strip()


#: THE CREDENTIAL FLOOR ABOVE CANNOT SEE THIS ONE, and the reason is written into its own
#: criterion: *"the criterion is authority, not confidentiality."* A durable engine on
#: `localhost:7233` needs **no credential at all** — `connection.address()` defaults to it and
#: `_auth()` adds nothing — so stripping `TEMPORAL_API_KEY` protects exactly the deployment that
#: was never reachable from a laptop, and none of the ones that are.
#:
#: MEASURED, NOT SUSPECTED (#107). With the OSS `docker compose` stack up — which is the
#: development loop this repository ships and documents — a suite run left a REAL workflow behind:
#:
#:     workflow_id : openfactory-demo-7
#:     identity    : 40513@Mac.lan          ← the host running pytest
#:     input       : {"project":"demo","issue":"7","sandbox":"worktree", …}
#:     state       : on_hold — KeyError: "project not registered: 'demo'"
#:
#: It parked because `demo` is a test name that no registry has. A project that HAPPENED to exist
#: under that name would have been worked on for real: an agent, a checkout, a client's board.
#: And the suite stayed green throughout, which is what makes it this repository's signature
#: defect rather than a flake — the damage is invisible from inside the run that caused it.
_LIVE_ENGINE = (
    "a test tried to open a REAL connection to a durable engine.\n\n"
    "Nothing in this suite may reach one. `connect()` defaults to localhost:7233 with no auth, so "
    "on any machine running the OSS compose stack this starts real workflows — measured: a suite "
    "run created `openfactory-demo-7` on a developer's engine (#107).\n\n"
    "Patch the seam the code under test resolves instead — `openfactory.runtime.temporal.view.connect` "
    "for a row or a route, `openfactory.runtime.temporal.connection.connect` for the engine itself — and "
    "hand back a double. Every durable test in this suite already does.\n\n"
    "If an integration test one day genuinely needs a live engine, it has to say so here, "
    "deliberately, with the reason — not by deleting this fixture."
)


#: The one legitimate reason to open a real connection: a test that STARTS ITS OWN engine and
#: throws it away. `temporalio.testing.WorkflowEnvironment` does exactly that — an ephemeral
#: server on a port it picked, which is not a deployment's engine in any sense that matters.
#:
#: A MARKER RATHER THAN AN ADDRESS COMPARISON, and the two failure directions are why. Allowing
#: "anything that is not the configured address" reads well and fails silently in the direction
#: that costs — a test that reached some OTHER real engine would sail through. A marker cannot do
#: that: it is declared on the file, it is greppable, and the guard in
#: `test_the_suite_cannot_reach_a_live_engine` proves every file carrying it really does start
#: its own server.
OWNS_ITS_ENGINE = "owns_its_engine"


@pytest.fixture(autouse=True)
def _no_live_durable_engine(request, monkeypatch) -> None:
    """No test may open a connection to a durable engine it did not start itself.

    BLOCKED AT THE LIBRARY, not at our wrapper, and that is the whole point. Six production call
    sites resolve `connect` by four different routes, and **three of them bind it at module
    import** (`worker.py`, `schedule.py`, `starter.py`) — so a `monkeypatch` of
    `connection.connect` would leave those three untouched while looking like a barrier. That is
    this repository's signature defect wearing a guard's clothes: green, and blind to half of what
    it names. `Client.connect` is where a socket is actually opened; below it there is nowhere to
    go.

    A DOUBLE NEVER REACHES THIS. Every durable test patches a seam above it and hands back a fake
    client, so this fixture is invisible to them — it only fires for a call that would have talked
    to a server, which is exactly the set it is written to stop.
    """
    if request.node.get_closest_marker(OWNS_ITS_ENGINE):
        return

    async def _refuse(*_args, **_kwargs):
        raise RuntimeError(_LIVE_ENGINE)

    monkeypatch.setattr("temporalio.client.Client.connect", _refuse)


def pytest_terminal_summary(terminalreporter, exitstatus, config):
    """Every failure's NAME survives the run, in a ledger nothing truncates.

    An order-dependent failure hit ONE test in ~18 full-suite runs (2026-08-14) and its name
    was lost — the run's output went through `tail -1`, pytest's `lastfailed` is a palimpsest
    that targeted runs keep rewriting, and the randomly seed had been overwritten by the next
    run. Fifteen full suites were spent hunting a name this hook would have kept for free.

    Appended, never truncated; gitignored; carries the seed so `-p randomly
    --randomly-seed=<n>` can replay the exact order. Reading it costs `tail`.

    KNOWN NOISE, on purpose: tests that spawn an INNER pytest (the live-engine barrier probes)
    make this hook fire in the inner session too, so their deliberate failures appear here
    (`test__live_engine_probe__` and kin) while the outer run stays green. Filtered out would
    mean a list of exemptions this file has to chase; recorded, they are self-explanatory by
    name and cost a `grep -v`."""
    failed = terminalreporter.stats.get("failed", []) + terminalreporter.stats.get("error", [])
    if not failed:
        return
    import datetime as _dt
    from pathlib import Path as _Path

    seed = getattr(config.option, "randomly_seed", None)
    stamp = _dt.datetime.now(_dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    with _Path(__file__).with_name(".failures.log").open("a", encoding="utf-8") as fh:
        for rep in failed:
            fh.write(f"{stamp} seed={seed} {rep.nodeid}\n")


def code_only(source: str) -> str:
    """`source` with every COMMENT and every DOCSTRING removed — the code, and only the code.

    ONE HOME FOR THIS BECAUSE THE HAND-WRITTEN VERSIONS KEEP FAILING THE SAME WAY. A guard that
    asserts "this vendor's name does not appear here" reads the paragraph explaining why it must
    not appear and fails on it. That has now happened with `#135` as a hex colour, an `onclick=`
    example, a `hash(text)` mention inside the note describing the fix, and — writing the guard
    below — the sentence "`x-access-token:<token>@` into ANY https URL" in the docstring of the
    function that stopped doing it.

    Comments were already being stripped by several callers; docstrings were not, and a docstring
    is where the explanation actually lives.
    """
    import ast

    tree = ast.parse(source)
    drop: set[int] = set()
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        body = getattr(node, "body", None) or []
        first = body[0] if body else None
        if (isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant)
                and isinstance(first.value.value, str)):
            drop.update(range(first.lineno, (first.end_lineno or first.lineno) + 1))

    kept = [("" if n in drop else re.sub(r"(^|\s)#.*$", "", line))
            for n, line in enumerate(source.splitlines(), start=1)]
    # A TRAILING NEWLINE, so `code_only(src).splitlines()` has the SAME length as
    # `src.splitlines()` and line N of one is line N of the other. `"\n".join(...)` alone drops the
    # final element whenever the last line strips to nothing — a trailing comment, a blank line, or
    # the tail of a docstring — which is true of 14 modules in this package including `api/app.py`.
    # A caller aligning two readings of one file (a marker in the raw text, the code with prose
    # gone) would have been silently off by one on exactly the files that matter.
    # …and an EMPTY file stays empty: `"\n".join([]) + "\n"` is one line where the source had none,
    # which is the same off-by-one facing the other way (four `__init__.py` files in this package).
    return ("\n".join(kept) + "\n") if kept else ""


#: WHAT IS INSTALLED IN THIS INTERPRETER IS A FACT ABOUT THE BENCH, NOT ABOUT THE CASE. The
#: repository's own add-on packages under `addons/` are installed by `make install` — which is
#: what CI runs — and NOT by a developer's `pip install -e '.[dev]'`. On 2026-08-26 that one
#: difference was five tests red on CI and green on every laptop: four asserting an exact
#: `FallbackState` and one asserting that `channel: slack` is REFUSED before its row is served.
#: Both read `importlib.metadata.entry_points()`, which answers the truth about the machine.
#:
#: This is the same doctrine as the credential floor above, one axis over: the suite's view of
#: "what is installed" becomes a controlled input. The platform's own declared rows are filtered
#: out of discovery; a test that wants one SERVES it (`vendor_addons.install`, which replaces
#: this function outright and therefore wins), and a stranger's distribution
#: (`stranger_addon.installed`) is untouched, because the filter hides only what the packages
#: under `addons/` declare. In the public tree there is no `addons/`, nothing is declared, and
#: the filter is a no-op — which is correct, since nothing is installed there either.
@pytest.fixture(autouse=True)
def _the_bench_is_not_the_case(monkeypatch) -> None:
    import importlib.metadata as _md

    try:
        import vendor_addons
    except ImportError:  # a context that does not put tests/ on sys.path
        return
    ours = vendor_addons.declared()
    if not ours:
        return

    real = _md.entry_points

    def _filtered(**params):
        points = real(**params)
        return vendor_addons.not_ours(points, ours) if params.get("group") else points

    monkeypatch.setattr(_md, "entry_points", _filtered)
    from openfactory import plugins as _plugins
    monkeypatch.setattr(_plugins, "_cache", None)
