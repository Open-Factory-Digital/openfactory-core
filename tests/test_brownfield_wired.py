"""The reverse-engineering pass, end to end — the capability the product owner is about to ask
for.

`role.survey` and all of `brownfield.py` existed, tested, since the product role shipped, and were
called by NOTHING: asking "faz o levantamento" got an honest "I still cannot do that on my own".
Honest beat pretending, and doing beats both.

The one rule that makes reverse engineering safe (brownfield.py's opening argument): a requirement
says what MUST be true; code says what IS true, bugs included. Turning the second into the first
freezes bugs into promises the factory would then defend, with "asked by: the code" as provenance.
So the output is OBSERVATIONS, in one pull request, and a human confirming is the only event that
creates a promise.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from openfactory.contracts.product import ProductConfig
from openfactory.contracts.project import Project, ProviderRef
from openfactory.product import channel as pc
from openfactory.product.authoring import WriteResult
from openfactory.product.brownfield import Baseline, Observation, milestone_files

ADMIN, CLIENT = "U0ADMIN", "U0CLIENT"


def _project():
    return Project(name="books", language="pt-BR", repo_path="/t",
                   tracker=ProviderRef(kind="github", repo="a/code"),
                   forge=ProviderRef(kind="github", repo="a/code"),
                   product=ProductConfig(docs_repo="a/docs", channel_id="C0PROD",
                                         admins=[ADMIN], agent_name="Nina"))


class _Module:
    def __init__(self, result=None):
        self.result = result or WriteResult(ok=True, url="https://x/pull/9")
        self.called = False

    def baseline(self, **kw):
        self.called = True
        return self.result

    def context(self, **kw):
        class _C:
            available = True
        return _C()


@pytest.fixture(autouse=True)
def _clean():
    pc._PENDING.clear()
    yield
    pc._PENDING.clear()


# ── it is REACHABLE now ─────────────────────────────────────────────────────────────────────────

def test_the_whole_chain_exists_from_the_channel_to_the_pull_request():
    """Intent → reply → module → survey → PR. Each link asserted by CALL, because this capability
    spent its whole life with three of the four present and no one joining them."""
    channel = Path("openfactory/product/channel.py").read_text()
    module = Path("openfactory/product/module.py").read_text()
    assert "module.baseline()" in channel, "the channel no longer starts the pass"
    assert ".survey(" in module, "the module no longer runs the survey"
    assert "propose_baseline(" in module, "the module no longer writes the result"


def test_asking_for_it_starts_it_and_says_so_immediately():
    """It takes minutes. A Socket Mode handler that blocks that long times out and takes the
    channel down for everyone — and silence until it finishes is the "looks broken while working"
    failure this layer exists to remove."""
    module = _Module()
    reply = pc._baseline_reply(_project(), module, "Nina", ADMIN)
    assert "minutos" in reply, reply
    assert "OBSERVA" in reply.upper(), "it must warn that the output is not promises"


def test_a_non_admin_cannot_start_it():
    """It costs an agent pass over a whole repository."""
    module = _Module()
    reply = pc._baseline_reply(_project(), module, "Nina", CLIENT)
    assert not module.called
    assert reply


def test_it_runs_OFF_the_listener_thread():
    """Asserted structurally: the reply returns while the work continues."""
    src = Path("openfactory/product/channel.py").read_text()
    tree = ast.parse(src)
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.FunctionDef) and n.name == "_baseline_reply")
    body = ast.unparse(fn)
    assert "threading.Thread" in body, "a survey on the listener thread kills the socket"


# ── what it writes ──────────────────────────────────────────────────────────────────────────────

def test_everything_lands_as_ONE_pull_request():
    """A team asked to review forty requirement PRs reviews none, and the exercise dies in its
    first week."""
    # THE ARGV GREP IS GONE WITH THE `gh` IT WATCHED (#95). It counted `"pr", "create"` in the
    # source, which was only ever a proxy; the baseline opens its pull request through the port
    # now, so the property is asserted where it lives — one `_open_review_request` call, on a
    # deterministic branch, so a retry finds its own pull request instead of opening a second.
    src = Path("openfactory/product/authoring.py").read_text()
    body = src[src.index("def propose_baseline"):]
    body = body[:body.index("\ndef ")] if "\ndef " in body else body
    assert 'branch = "product/baseline"' in body, "a retry must find its own PR, not open a second"
    assert "merge" not in body, (
        "the baseline was merged — a reading of the code must be READ by a person before it "
        "becomes the base the factory answers from")

    # COUNTED BY RUNNING IT, NOT BY GREPPING THE SOURCE. This asserted
    # `body.count("_open_review_request(") == 1`, which is a spelling of the property and not the
    # property: the function grew a second call site on a MUTUALLY EXCLUSIVE branch — the arm that
    # recovers a branch pushed by an attempt whose pull request never opened — and the syntax
    # count went red over a change that cannot open two. What matters is that no single pass opens
    # more than one, so the pass is driven and the opens are counted.
    from openfactory.product import authoring

    class _Forge:
        def __init__(self, branches):
            self.branches, self.opened = list(branches), []

        def list_branches(self):
            return list(self.branches)

        def pr_for_head(self, *_a, **_k):
            return ""          # asked, and there is none — `None` means could not ask

        def open_pr(self, **kw):
            self.opened.append(kw)
            return "https://forge/pr/1"

    # the world where a previous attempt left the branch behind with no pull request
    forge = _Forge(["main", "product/baseline"])
    authoring.propose_baseline(
        forge=forge, docs_repo="acme/ctx", clone_url="https://x/acme/ctx.git", base="main",
        product="acme", observations=3, covered=["a"], files={"a.md": "x"})
    assert len(forge.opened) <= 1, f"more than one PR per pass: {forge.opened}"

    # AND THE PATHS THAT THE FAKE CANNOT REACH, asserted structurally: no single BLOCK may open
    # two. Mutually exclusive branches are fine — that is what the recovery arm is — but two opens
    # in sequence is a pass that files twice, and the clone in between means no in-process probe
    # can drive it.
    fn = next(n for n in ast.walk(ast.parse(src))
              if isinstance(n, ast.FunctionDef) and n.name == "propose_baseline")

    def _opens(stmts):
        return sum(
            1 for st in stmts for n in ast.walk(st)
            if isinstance(n, ast.Call) and getattr(n.func, "id", "") == "_open_review_request")

    blocks = [fn.body]
    while blocks:
        block = blocks.pop()
        direct = [st for st in block if not isinstance(st, (ast.If, ast.Try, ast.For, ast.While))]
        assert _opens(direct) <= 1, "one block opens two pull requests — a pass that files twice"
        for st in block:
            for field in ("body", "orelse", "finalbody"):
                nested = getattr(st, field, None)
                if isinstance(nested, list) and nested:
                    blocks.append(nested)


def test_the_files_carry_the_inventory_and_one_candidate_each():
    baseline = Baseline(
        observations=[Observation(title="Exporta balancete", behaviour="gera PDF mensal",
                                  evidence="tested", citations=["tests/test_x.py"]),
                      Observation(title="Concilia extrato", behaviour="casa lançamentos",
                                  evidence="code", citations=["app/rec.py"])],
        covered=["app/"], commit="abc123")
    files = milestone_files(baseline, product="books", first_number=1)
    assert any("inventory.md" in p for p in files)
    assert len([p for p in files if "requirements/" in p]) == 2
    for path, body in files.items():
        if "requirements/" in path:
            assert "observed" in body, f"{path} did not land as an observation"
            assert "não é uma promessa" in body.lower() or "not a commitment" in body.lower()


def test_the_pull_request_says_it_is_a_READING_not_a_set_of_promises():
    """The one moment somebody could mistake a reverse-engineered description for something the
    product agreed to — so the PR body says it in its first line."""
    src = Path("openfactory/product/authoring.py").read_text()
    start = src.index("def propose_baseline")
    body = src[start:]
    body = body[:body.index("\ndef ")] if "\ndef " in body else body
    assert "LEITURA do código" in body
    assert "observed" in body


def test_the_client_is_told_what_the_pass_cannot_claim():
    """Coverage and intent are both unknowable from a reading — stating that is the difference
    between a document somebody can trust and one that grants false confidence."""
    from openfactory.product.voice import baseline_started, jargon_in

    # pt-BR NAMED: the assertion below is the Portuguese sentence, and the platform
    # default became English (2026-08-14)
    text = baseline_started(agent_name="Nina", language="pt-BR")
    assert "acidente" in text or "defeito" in text
    assert not jargon_in(text)
