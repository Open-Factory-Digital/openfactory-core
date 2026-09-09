"""The factory asks before it spends (ADR-0048) — the gather between the sizing and the plan.

Every rule the critique left is a guard here: the gather is OFF unless the project opted in AND
enforces the gate; an unreadable context repository or an absent bundle proceeds without touching
the card; a directory the sizer names is expanded to files before the gate judges it; what the
bundle covers is not asked about; what the code could tell is published first; the product role's
answer counts only when its evidence VERIFIED; the question is ONE comment, marker first, to a
requester the tracker can name — and to nobody when it cannot; the park is read back; the loop
opens last; and the whole activity never raises.
"""

from __future__ import annotations

from pathlib import Path

from openfactory.contracts import AcceptanceCriterion, JobState, Ticket
from openfactory.contracts.manifest import Manifest
from openfactory.knowledge.contracts import Concept, ConceptSource, OkfManifest
from openfactory.knowledge.okf import write_okf
from openfactory.knowledge.pipeline import Fetched
from openfactory.onboarding.cover import Covered
from openfactory.runtime.temporal import activities as acts
from openfactory.runtime.temporal.io import GatherInput

# ── the world ───────────────────────────────────────────────────────────────────────────────────


class _Tracker:
    """A tracker that records EVERYTHING in order — the order is the contract (§5)."""

    def __init__(self, ticket: Ticket, *, park_lands: bool | None = True,
                 renders_mentions: bool = True) -> None:
        self._ticket = ticket
        self.said: list[tuple[str, str]] = []
        self.moves: list[tuple[str, JobState, bool | None]] = []
        self.order: list[str] = []
        self._park_lands = park_lands
        self._renders_mentions = renders_mentions

    def mention(self, login: str) -> str:
        """THE ROW ANSWERS, which is what moved (ADR-0049 D7). This used to be decided for the
        tracker by comparing the project's provider kind to `"github"` somewhere else entirely;
        a fake with a kind and no opinion is exactly the row that got it wrong.

        The real rendering is borrowed rather than copied — `GitHubIssuesTracker.mention` — so
        this double cannot drift from the row it stands in for."""
        from openfactory.adapters.tracker.github import GitHubIssuesTracker

        return GitHubIssuesTracker.mention(self, login) if self._renders_mentions else login

    def get_ticket(self, ref: str) -> Ticket:
        return self._ticket

    def comment(self, ref: str, body: str) -> None:
        self.said.append((ref, body))
        self.order.append("comment")

    def set_state(self, ref: str, state: JobState, reason: str | None = None, *,
                  needs_person: bool | None = None) -> bool | None:
        self.moves.append((ref, state, needs_person))
        self.order.append("park")
        return self._park_lands


class _Role:
    """The product role, scripted: `answers[path] -> (text, verified)`."""

    def __init__(self, answers: dict[str, tuple[str, dict]]) -> None:
        self.answers = answers
        self.asked: list[str] = []

    def __call__(self, project, *, via="api"):
        return self

    def answer(self, question, *, context="", **_):
        from openfactory.product.role import ProductAnswer, Reading

        self.asked.append(question)
        for path, (text, verified) in self.answers.items():
            if f"`{path}`" in question:
                return ProductAnswer(ok=True, text=text,
                                     reading=Reading(kind="question", verified=verified))
        return ProductAnswer(ok=False, error="not mounted")


def _ticket(**over) -> Ticket:
    base = dict(id="#41", title="Charge the late fee", repo="acme/app", objective="x",
                acceptance_criteria=[AcceptanceCriterion(text="c")], author="octocat")
    base.update(over)
    return Ticket(**base)


def _repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    (repo / "billing").mkdir(parents=True)
    (repo / "billing" / "tax.py").write_text("x = 1\n")
    (repo / "billing" / "fees.py").write_text("y = 2\n")
    (repo / "README.md").write_text("r\n")
    return repo


def _bundle(tmp_path: Path) -> Path:
    """`billing/tax.py` is described; `billing/fees.py` is not."""
    bundle = tmp_path / "bundle"
    write_okf(bundle, manifest=OkfManifest(source_commit="c1"), concepts=[
        Concept(type="policy", title="Tax", description="Taxes the fee.",
                sources=[ConceptSource(path="billing/tax.py")])])
    return bundle


class _World:
    def __init__(self, tmp_path, monkeypatch, *, gather=True, okf_gate="enforce",
                 fetched=None, ticket=None, park_lands=True, cover=None, people=None,
                 tracker_kind="github", ledger=None):
        import openfactory.adapters.forge.registry as forge
        import openfactory.knowledge.pipeline as pipeline
        import openfactory.memory.store as loop_store
        import openfactory.onboarding.cover as cover_mod
        import openfactory.product.module as product

        self.repo = _repo(tmp_path)
        self.bundle = _bundle(tmp_path)
        self.manifest = Manifest(version=1, base_branch="main", okf_gate=okf_gate,
                                 preflight={"gather": gather})
        # A row that renders `@` stands in for GitHub; one that does not stands in for Jira or
        # Azure Boards, which resolve no bare `@name` in a comment body.
        self.tracker = _Tracker(ticket or _ticket(), park_lands=park_lands,
                                renders_mentions=(tracker_kind == "github"))
        self.project = type("P", (), {
            "name": "acme", "repo_path": str(self.repo), "language": "", "people": people or {},
            "product": type("Pr", (), {"docs_repo": "acme/context", "docs_branch": "main"})(),
            "forge": type("F", (), {"repo": "acme/app", "kind": "github", "options": {}})(),
            "tracker": type("T", (), {"repo": "acme/app", "kind": tracker_kind,
                                      "options": {}})(),
        })()
        self.fetches: list[Path] = []
        self.published: list[tuple] = []
        self.covered: list[list[str]] = []
        self.loops_written: list = []
        self.discarded: list = []
        self.role = _Role({})
        fetched = fetched if fetched is not None else Fetched(self.bundle)

        def fetch(url, *, subpath):
            self.fetches.append(subpath)
            return fetched

        def publish(bundle_dir, url, *, subpath, source_commit="", author=None):
            self.published.append((subpath, source_commit))
            return True

        def cover_paths(project, bundle_dir, source, paths, *, commit, generated_at):
            self.covered.append(list(paths))
            if cover is not None:
                return cover(paths)
            return Covered(0, (), tuple(paths), "no harness on this machine")

        monkeypatch.setattr(acts.ProjectRegistry, "get", lambda self_, name: self.project)
        monkeypatch.setattr(acts, "_tracker_for", lambda project: self.tracker)
        monkeypatch.setattr(acts, "_worker_checkout",
                            lambda project, repo: (self.repo, self.manifest, "url", "tok"))
        monkeypatch.setattr(forge, "clone_url_for",
                            lambda project, repo="", *, token=None: f"https://x/{repo}")
        monkeypatch.setattr(pipeline, "fetch_bundle", fetch)
        monkeypatch.setattr(pipeline, "publish_bundle", publish)
        monkeypatch.setattr(pipeline, "discard_fetched_bundle",
                            lambda p: self.discarded.append(p))
        monkeypatch.setattr(cover_mod, "cover_paths", cover_paths)
        monkeypatch.setattr(product, "ProductModule", self.role)
        monkeypatch.setattr(loop_store, "read", lambda name: list(ledger or []))
        monkeypatch.setattr(loop_store, "write",
                            lambda name, rows: self.loops_written.extend(rows) or len(rows))

    def gather(self, *touches: str):
        return acts._do_gather(GatherInput(project="acme", issue="41", touches=list(touches)))


# ── the gates in front of the gather ────────────────────────────────────────────────────────────

def test_the_gather_is_off_by_default(tmp_path, monkeypatch):
    assert Manifest(version=1, base_branch="main").preflight.gather is False, (
        "a default of true changes behaviour for every manifest that does not mention it — a "
        "schema bump (refutation 7)")
    w = _World(tmp_path, monkeypatch, gather=False)
    v = w.gather("billing/fees.py")
    assert v.verdict == "proceed" and "off" in v.note
    assert not w.fetches and not w.tracker.said and not w.tracker.moves


def test_the_gather_runs_under_enforce_only(tmp_path, monkeypatch):
    """`okf_gate` defaults to advise BECAUSE every project is dark before its first backfill; a
    gather firing on advise would bounce every card of every un-onboarded project (refutation 6)."""
    w = _World(tmp_path, monkeypatch, okf_gate="advise")
    v = w.gather("billing/fees.py")
    assert v.verdict == "proceed" and "advise" in v.note
    assert not w.fetches and not w.tracker.said


def test_an_unreadable_context_repository_proceeds_and_says_so_without_touching_the_card(
        tmp_path, monkeypatch):
    w = _World(tmp_path, monkeypatch, fetched=Fetched(None, unreadable="clone refused: 403"))
    v = w.gather("billing/fees.py")
    assert v.verdict == "proceed" and v.degraded and "403" in v.degraded
    assert not w.tracker.said and not w.tracker.moves, "a failed read never bounces a card"


def test_nothing_published_proceeds_quietly(tmp_path, monkeypatch):
    w = _World(tmp_path, monkeypatch, fetched=Fetched(None))
    v = w.gather("billing/fees.py")
    assert v.verdict == "proceed" and v.degraded is None and "backfill" in v.note
    assert not w.tracker.said and not w.tracker.moves


def test_a_sizer_that_named_no_area_gathers_nothing(tmp_path, monkeypatch):
    w = _World(tmp_path, monkeypatch)
    assert w.gather().verdict == "proceed" and not w.fetches


# ── what is judged ──────────────────────────────────────────────────────────────────────────────

def test_a_directory_is_expanded_to_files_before_the_gate_sees_it(tmp_path, monkeypatch):
    """`judge()` cannot take a directory: it answers `new-file` (green) for `billing/` and the
    open-question half is never evaluated (refutation 15). Expanded, `billing/fees.py` is dark."""
    w = _World(tmp_path, monkeypatch)
    w.gather("billing/")
    assert w.covered == [["billing/fees.py"]], w.covered


def test_what_the_bundle_covers_is_not_asked_about(tmp_path, monkeypatch):
    w = _World(tmp_path, monkeypatch)
    v = w.gather("billing/tax.py", "README.md")
    assert v.verdict == "proceed" and "covers" in v.note
    assert not w.covered and not w.tracker.said


def test_a_file_that_does_not_exist_yet_is_not_dark(tmp_path, monkeypatch):
    """Without an inventory the gate cannot tell a new file from an old one and calls it dark;
    a file the change will CREATE has no bytes to describe, so it is not judged at all
    (refutation 16: `new-file` is green)."""
    w = _World(tmp_path, monkeypatch)
    v = w.gather("billing/refunds.py")
    assert v.verdict == "proceed" and not w.covered and not w.tracker.said


# ── gather first ────────────────────────────────────────────────────────────────────────────────

def test_what_the_code_could_tell_is_authored_published_and_said_before_anything_is_asked(
        tmp_path, monkeypatch):
    def cover(paths):
        write_okf(_bundle(tmp_path), manifest=OkfManifest(source_commit="c2"), concepts=[
            Concept(type="policy", title="Tax", sources=[ConceptSource(path="billing/tax.py")]),
            Concept(type="policy", title="Late fees", description="Adds 2% after 30 days.",
                    sources=[ConceptSource(path="billing/fees.py")])])
        return Covered(1, ("billing/fees.py",), (), "fake-harness")

    w = _World(tmp_path, monkeypatch, cover=cover)
    v = w.gather("billing/fees.py")
    assert v.verdict == "proceed" and v.authored == 1 and v.asked == 0
    assert w.published, "authored and not published is knowledge the next card cannot read"
    assert len(w.tracker.said) == 1 and "Late fees" in w.tracker.said[0][1]
    assert "Adds 2% after 30 days" in w.tracker.said[0][1]
    assert not w.tracker.moves


def test_an_answer_the_product_role_verified_is_established_and_nobody_is_asked(tmp_path,
                                                                               monkeypatch):
    w = _World(tmp_path, monkeypatch)
    w.role.answers = {"billing/fees.py": ("Late fees follow REQ-0007: 2% after 30 days.",
                                          {"concepts": {"Tax": "fresh"},
                                           "requirements": {7: True}})}
    v = w.gather("billing/fees.py")
    assert v.verdict == "proceed" and v.established == 1 and v.asked == 0
    assert len(w.tracker.said) == 1 and "REQ-0007" in w.tracker.said[0][1]
    assert not w.tracker.moves and not w.loops_written


def test_an_answer_graded_media_from_a_fabricated_requirement_is_NOT_established(tmp_path,
                                                                                 monkeypatch):
    """`bound` demotes a cited REQ that does not exist to `média`, not `baixa` — so a grade-based
    gate would write a hallucinated citation into the client's register as a person's decision
    (refutation 3). Verified, not graded."""
    w = _World(tmp_path, monkeypatch)
    w.role.answers = {"billing/fees.py": ("Per REQ-0099, fees are waived.",
                                          {"concepts": {}, "requirements": {99: False}})}
    v = w.gather("billing/fees.py")
    assert v.verdict == "asked" and v.established == 0 and v.asked == 1


def test_an_answer_standing_on_a_stale_concept_is_NOT_established(tmp_path, monkeypatch):
    """The bytes moved under the concept; the answer stands on what the code used to say."""
    w = _World(tmp_path, monkeypatch)
    w.role.answers = {"billing/fees.py": ("2% after 30 days, per the Tax concept.",
                                          {"concepts": {"Tax": "stale"}, "requirements": {}})}
    assert w.gather("billing/fees.py").verdict == "asked"


def test_an_answer_that_cites_nothing_is_an_opinion(tmp_path, monkeypatch):
    w = _World(tmp_path, monkeypatch)
    w.role.answers = {"billing/fees.py": ("Probably 2%.", {"concepts": {}, "requirements": {}})}
    assert w.gather("billing/fees.py").verdict == "asked"


# ── the question ────────────────────────────────────────────────────────────────────────────────

def test_the_question_is_one_comment_marker_first_to_the_requester_the_tracker_knows(
        tmp_path, monkeypatch):
    w = _World(tmp_path, monkeypatch)
    v = w.gather("billing/fees.py")
    assert v.verdict == "asked" and v.asked == 1
    (ref, body), = w.tracker.said
    assert body.splitlines()[0].startswith("[openfactory:question] "), body
    assert "@octocat" in body and "`billing/fees.py`" in body
    assert all(ord(ch) < 128 for ch in body.splitlines()[0]), "the marker is ASCII"


def test_the_bundles_open_questions_about_the_file_ride_the_comment_and_their_keys_the_loop(
        tmp_path, monkeypatch):
    """ADR-0048 §7's other half, wired after the slice shipped: the author's own caveats about the
    file nobody described are put to the one person being asked about it, in the same comment —
    and their keys travel with the loop, so the answer retires them in the bundle. An answered one
    does not ride again, a caveat about another file does not ride at all, and the bound holds:
    two per file, not every caveat the author ever had."""
    from openfactory.knowledge.contracts import ANSWERED, Gap
    from openfactory.knowledge.okf import read_concepts

    w = _World(tmp_path, monkeypatch)
    asked = [Gap(kind="open-question", path="billing/fees.py", detail=f"Caveat {n} about fees?")
             for n in range(3)]
    done = Gap(kind="open-question", path="billing/fees.py", detail="Settled already?",
               status=ANSWERED, answer="yes", answered_by="carol", answered_at="t")
    elsewhere = Gap(kind="open-question", path="billing/tax.py", detail="About tax, not fees?")
    write_okf(w.bundle, manifest=OkfManifest(source_commit="c1", gaps=[*asked, done, elsewhere]),
              concepts=read_concepts(w.bundle))

    v = w.gather("billing/fees.py")

    assert v.verdict == "asked" and v.asked == 1
    (_ref, body), = w.tracker.said
    assert "Caveat 0 about fees?" in body and "Caveat 1 about fees?" in body, body
    assert "Caveat 2 about fees?" not in body, "two per file, not every caveat the author had"
    assert "Settled already?" not in body and "About tax" not in body, body
    (loop,) = w.loops_written
    assert loop.context["gap_keys"] == "\n".join(gp.key for gp in asked[:2])


def test_the_order_is_comment_park_loop_and_the_park_asks_for_a_person(tmp_path, monkeypatch):
    w = _World(tmp_path, monkeypatch)
    w.gather("billing/fees.py")
    assert w.tracker.order == ["comment", "park"]
    assert w.tracker.moves == [("#41", JobState.NEEDS_REFINEMENT, True)]
    (loop,) = w.loops_written
    assert loop.kind == "card_question" and loop.subject == "41"
    assert loop.context["requester"] == "octocat" and loop.context["paths"] == "billing/fees.py"
    assert loop.context["asked_at"] and loop.ts == loop.context["asked_at"]


def test_a_park_that_did_not_land_is_not_a_park(tmp_path, monkeypatch):
    """Two vendors have no Needs Action unless mapped; their `set_state` is a no-op with a warning.
    A card left in the pickup column with the job ended `skipped` is re-picked next tick and asked
    again — a new loop every hour (refutation 13)."""
    w = _World(tmp_path, monkeypatch, park_lands=False)
    v = w.gather("billing/fees.py")
    assert v.verdict == "proceed" and v.degraded and "park" in v.degraded
    assert not w.loops_written, "no loop waits on a card that did not move"
    assert len(w.tracker.said) == 2 and "Needs Action" in w.tracker.said[1][1]


def test_an_adapter_that_does_not_say_is_trusted(tmp_path, monkeypatch):
    w = _World(tmp_path, monkeypatch, park_lands=None)
    assert w.gather("billing/fees.py").verdict == "asked"


def test_nobody_the_tracker_can_name_means_no_question_and_the_work_proceeds(tmp_path,
                                                                            monkeypatch):
    """A card the factory opened from a chat carries a chat identity; its `author` is the bot. The
    question is written on the card for whoever reads it, and nothing waits (refutation 9)."""
    w = _World(tmp_path, monkeypatch,
               ticket=_ticket(author="openfactory-bot[bot]", requester="U04ABC"))
    v = w.gather("billing/fees.py")
    assert v.verdict == "proceed" and v.asked == 1
    (ref, body), = w.tracker.said
    assert "nobody" in body and "`billing/fees.py`" in body
    assert not w.tracker.moves and not w.loops_written


def test_a_chat_requester_the_deployment_mapped_is_asked_by_their_forge_login(tmp_path,
                                                                             monkeypatch):
    w = _World(tmp_path, monkeypatch,
               ticket=_ticket(author="openfactory-bot[bot]", requester="U04ABC",
                              requester_forge="mara"))
    v = w.gather("billing/fees.py")
    assert v.verdict == "asked" and "@mara" in w.tracker.said[0][1]


def test_on_a_tracker_without_mentions_the_name_is_written_plain(tmp_path, monkeypatch):
    w = _World(tmp_path, monkeypatch, tracker_kind="azure_devops",
               ticket=_ticket(author="mara@acme.example"))
    w.gather("billing/fees.py")
    assert "mara@acme.example" in w.tracker.said[0][1] and "@mara@" not in w.tracker.said[0][1]


def test_the_same_question_already_waiting_is_not_posted_twice(tmp_path, monkeypatch):
    from openfactory.knowledge.gather import question_hash
    from openfactory.memory.ledger import CARD_QUESTION, open_loop

    waiting = open_loop(CARD_QUESTION, "41", owner="techlead",
                        about=question_hash(["billing/fees.py"]), ts="2026-09-06T10:00:00+00:00")
    w = _World(tmp_path, monkeypatch, ledger=[waiting])
    v = w.gather("billing/fees.py")
    assert v.verdict == "asked" and not w.tracker.said and not w.tracker.moves


def test_at_most_three_questions_ride_one_card(tmp_path, monkeypatch):
    from openfactory.knowledge.gather import QUESTIONS_PER_CARD

    for i in range(5):
        (tmp_path / "repo" / "billing" / f"r{i}.py").write_text("z\n") if (
            tmp_path / "repo").exists() else None
    w = _World(tmp_path, monkeypatch)
    for i in range(5):
        (w.repo / "billing" / f"r{i}.py").write_text("z\n")
    v = w.gather("billing/")
    assert v.verdict == "asked" and v.asked == QUESTIONS_PER_CARD == 3


# ── it never raises, and it cleans up ───────────────────────────────────────────────────────────

def test_a_gather_that_blows_up_proceeds_and_says_so(tmp_path, monkeypatch):
    def boom(paths):
        raise RuntimeError("harness exploded")

    w = _World(tmp_path, monkeypatch, cover=boom)
    v = w.gather("billing/fees.py")
    assert v.verdict == "proceed" and v.degraded and "exploded" in v.degraded
    assert w.discarded == [w.bundle], "the fetched checkout is discarded on every path"


def test_the_fetched_bundle_is_discarded_after_an_ask_too(tmp_path, monkeypatch):
    w = _World(tmp_path, monkeypatch)
    w.gather("billing/fees.py")
    assert w.discarded == [w.bundle]


# ── the workflow's half, by inspection of the one file that cannot run here ─────────────────────

def test_the_workflow_gathers_after_a_fit_behind_a_patch_marker_and_frees_the_floor_on_asked():
    """The workflow body cannot run under pytest without a Temporal environment; what it MUST say
    is checkable: the gather is a second activity gated by `workflow.patched` (a new command in a
    file with jobs in flight — refutation 8 and D3), and `asked` is `SKIPPED`, short-circuited
    beside `DONE` (not DONE: the panel would read "shipped", #166; not a park: nothing waits)."""
    src = Path("openfactory/runtime/temporal/workflow.py").read_text(encoding="utf-8")
    gather = src[src.index("    async def _gather("):src.index("    @staticmethod", src.index(
        "    async def _gather("))]
    assert 'workflow.patched("preflight-gathers")' in gather
    assert "gather_context" in gather and "state=JobState.SKIPPED" in gather
    lifecycle = src[src.index("    async def _lifecycle("):]
    assert "result.state == JobState.SKIPPED" in lifecycle.split("_run_job_once")[0]
    stations = Path("docs/pipeline-stations.md").read_text(encoding="utf-8")
    assert "ADR-0048" in stations or "0048" in stations, "the stations doc names the gather"
