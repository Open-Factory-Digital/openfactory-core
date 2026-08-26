"""The facts as files, so the tech-lead opens the one the question is about (#169).

Everything it knew was frozen into one prompt string before its process started — measured at
~20-25k characters — and capped at 30 tickets / 8 comment threads / 8 verdicts. The caps are
LOGGED when they bite and invisible to the model, so it answered thin and confident about a floor
it had been shown a truncation of.

WHY FILES AND NOT A PROTOCOL, and this is the vendor-neutrality claim in one line: every judging
role this platform supports is already a read-only loop with filesystem reads over the checkout —
`claude Read,Grep,Glob`, `codex -s read-only` (a sandbox POLICY), opencode's read-only profile
(the mutating tools removed from the model's list), kimi's plan mode. A fact written as a file is
therefore a tool on ALL FOUR today, with no new flag, no dependency and no second-class deployment.

THE PACK IS NOT THE POINT — THE PAIR IS. A shrunk prompt is only correct when the pack landed.
Shrinking unconditionally would leave a tech-lead answering from nothing while believing it has
files to open, which is absence reading as compliance.
"""

from __future__ import annotations

import inspect
from pathlib import Path

import pytest

from openfactory.techlead import pack
from openfactory.util import scratch


def _root(tmp_path: Path) -> Path:
    (tmp_path / ".git" / "info").mkdir(parents=True)
    return tmp_path


# ── 1. what the pack writes ─────────────────────────────────────────────────────────────────────

def test_the_pack_writes_what_it_was_given_and_names_it(tmp_path):
    into = pack.write_pack(_root(tmp_path), floor="# Floor\nthings are running",
                           board="# Board\n- 7: In review", thread="you: hello there",
                           comments={"7": "# Thread 7\nsomebody said a thing"},
                           verdicts={"7": "# Review 7\napproved (score 90)"}, gaps=[])

    assert into is not None and into.exists()
    assert (into / "floor.md").read_text().startswith("# Floor")
    assert (into / "comments" / "7.md").exists()
    assert (into / "verdicts" / "7.md").exists()

    readme = (into / "README.md").read_text()
    for name in ("floor.md", "board.md", "thread.md", "comments/7.md", "verdicts/7.md"):
        assert f"{into.name}/{name}" in readme, f"{name} is on disk and not in the manifest"


def test_the_manifest_names_what_could_NOT_be_read(tmp_path):
    """THE HALF A DIRECTORY LISTING CANNOT CARRY. A missing `comments/87.md` reads exactly like a
    ticket nobody has commented on — a claim about the client's ticket, made from a read that
    failed. Both `comments_for` and `_verdicts` return an option type so this can be said."""
    into = pack.write_pack(_root(tmp_path), floor="# Floor\nsomething", board="", thread="",
                           comments={}, verdicts={},
                           gaps=["the ticket thread for 87 could not be read"])

    readme = (into / "README.md").read_text()
    assert "could NOT be read" in readme
    assert "the ticket thread for 87 could not be read" in readme
    assert "FAILED READS, not absences" in readme, (
        "the manifest lists the gap and does not say what a gap MEANS — a model resolves it as "
        "'nothing to show', which is the sentence this platform forbids")


def test_a_clean_read_says_so_rather_than_leaving_the_section_blank(tmp_path):
    """The positive twin: an empty gaps list must render as a statement, or 'no gaps section' and
    'gaps we forgot to render' look identical."""
    into = pack.write_pack(_root(tmp_path), floor="# Floor\nsomething", board="", thread="",
                           comments={}, verdicts={}, gaps=[])

    assert "Everything asked for was read." in (into / "README.md").read_text()


def test_an_empty_fact_is_not_written_at_all(tmp_path):
    """A file whose body says nothing is a file the model spends a turn opening to learn it wasted
    the turn."""
    into = pack.write_pack(_root(tmp_path), floor="# Floor\nreal content here", board="  ",
                           thread="", comments={"7": ""}, verdicts={}, gaps=[])

    assert not (into / "board.md").exists() and not (into / "thread.md").exists()
    assert not (into / "comments" / "7.md").exists()


@pytest.mark.parametrize("ref,expected", [
    ("87", "87"), ("#87", "87"), ("CONT-412", "CONT-412"),
    ("Deskline/ui#15", "Deskline-ui-15"), ("../../etc/passwd", "etc-passwd"), ("", "unknown"),
])
def test_a_providers_own_ref_becomes_a_filename_and_never_a_path(ref, expected):
    """Refs are the PROVIDER'S strings (C-05) — `CONT-412`, `owner/repo#15`. Anything that is not
    a plain word becomes a dash, so a ref can never walk out of the pack directory."""
    assert pack._safe(ref) == expected


# ── 2. it never touches the client's tree ───────────────────────────────────────────────────────

def test_the_pack_is_not_written_inside_the_clients_own_config_directory():
    """`.openfactory/` is the CLIENT'S manifest directory (`.openfactory/project.yaml`). Our
    scratch belongs beside it, never inside it."""
    assert pack._PREFIX.startswith(".openfactory-")
    assert pack._PREFIX != ".openfactory/"
    assert pack.pack_dir(Path("/tmp/x")).name != ".openfactory"


def test_two_packs_never_collide(tmp_path):
    assert pack.pack_dir(tmp_path) != pack.pack_dir(tmp_path)


def test_a_name_that_already_exists_REFUSES_rather_than_overwriting(tmp_path, monkeypatch):
    """Eight random hex colliding is not a collision, it is the wrong tree. Overwriting there
    would put our scratch on top of somebody's file."""
    root = _root(tmp_path)
    fixed = root / f"{pack._PREFIX}deadbeef"
    fixed.mkdir()
    monkeypatch.setattr(pack, "pack_dir", lambda r: fixed)

    assert pack.write_pack(root, floor="x" * 40, board="", thread="", comments={}, verdicts={},
                           gaps=[]) is None


def test_the_pack_is_kept_out_of_the_clients_git_status(tmp_path):
    root = _root(tmp_path)
    into = pack.write_pack(root, floor="x" * 40, board="", thread="", comments={}, verdicts={},
                           gaps=[])

    assert f"{into.name}/" in (root / ".git" / "info" / "exclude").read_text()


def test_a_tree_with_no_git_info_still_gets_its_pack(tmp_path):
    """Best effort: a repository we cannot write an exclude into is a reason to skip the exclude,
    never to lose the facts."""
    assert pack.write_pack(tmp_path, floor="x" * 40, board="", thread="", comments={},
                           verdicts={}, gaps=[]) is not None


def test_an_unwritable_root_returns_NONE_rather_than_raising(tmp_path, monkeypatch):
    def _boom(*a, **k):
        raise OSError("read-only file system")

    monkeypatch.setattr(Path, "mkdir", _boom)
    assert pack.write_pack(tmp_path, floor="x" * 40, board="", thread="", comments={},
                           verdicts={}, gaps=[]) is None


# ── 3. the prompt shrinks ONLY when the pack landed ─────────────────────────────────────────────

class _Project:
    name = "demo"
    repo_path = "/tmp/demo"


def _context(monkeypatch, *, pack_ok: bool, jobs=None):
    import openfactory.adapters.agent as agent_registry
    from openfactory.techlead import conversation

    seen: dict[str, str] = {}

    class _Harness:
        def chat(self, *, sandbox, workspace, question, context):
            seen["context"] = context
            return {"text": "ok"}

    monkeypatch.setattr(conversation, "gather_jobs", lambda p: jobs or [])
    # A SCRATCH DIR, NEVER "/tmp". `_answer` owns what `clone_repo` hands back and deletes it
    # recursively in a `finally`; this line used to say "/tmp", so the suite ran
    # `rmtree("/tmp")`. Harmless-looking on macOS, where pytest keeps its files under
    # /private/var/folders — on Linux it deleted pytest's own temp root and failed 898 later
    # tests (2026-08-21). `util/scratch.discard` now refuses it; this keeps the stub honest.
    monkeypatch.setattr(conversation, "clone_repo",
                        lambda p: (scratch.make("test-facts"), True))
    monkeypatch.setattr(conversation, "answer_text", lambda res: "an answer")
    monkeypatch.setattr(conversation, "_record_chat_spend", lambda *a, **k: None)
    monkeypatch.setattr(agent_registry, "build_techlead", lambda p: _Harness())
    if not pack_ok:
        monkeypatch.setattr(conversation.pack, "write_pack", lambda *a, **k: None)

    conversation._answer(_Project(), "why is #7 parked?", cap=None, can=(),
                         thread="you: I asked before")
    return seen.get("context", "")


def test_a_pack_that_could_not_be_written_brings_the_FULL_render_back(monkeypatch):
    """THE POSITIVE TWIN, and the reason the pair is the point. Shrinking unconditionally leaves a
    tech-lead answering from nothing while believing it has files to open."""
    built = _context(monkeypatch, pack_ok=False)

    assert "I asked before" in built, "the thread vanished with the pack"
    assert "Current jobs" in built


def test_the_manifest_reaches_the_prompt_when_the_pack_landed(monkeypatch, tmp_path):
    from openfactory.techlead import conversation

    landed = pack.write_pack(_root(tmp_path), floor="# Floor\nrunning", board="", thread="",
                             comments={}, verdicts={}, gaps=[])
    monkeypatch.setattr(conversation.pack, "write_pack", lambda *a, **k: landed)

    built = _context(monkeypatch, pack_ok=True)

    assert "The facts for this question" in built, "the manifest never reached the model"
    assert landed.name in built, "the model is not told where the files are"


def test_the_floor_INDEX_stays_inline_either_way(monkeypatch, tmp_path):
    """The two things most questions need — what is on the floor, and what else exists — stay in
    the prompt. A model told a file exists and choosing not to open it answers worse than one
    handed the text; the index is what makes the choice informed."""
    from openfactory.techlead import conversation

    landed = pack.write_pack(_root(tmp_path), floor="# Floor", board="", thread="", comments={},
                             verdicts={}, gaps=[])
    monkeypatch.setattr(conversation.pack, "write_pack", lambda *a, **k: landed)

    assert "Current jobs" in _context(monkeypatch, pack_ok=True)


# ── 4. every harness can read it ────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("module,marker", [
    ("claude_code", "Read"),
    ("codex", "read-only"),
    ("opencode", "read"),
    ("kimi", "plan"),
])
def test_every_judging_harness_can_read_the_workspace(module, marker):
    """THE VENDOR-NEUTRALITY CLAIM, asserted rather than assumed. If a harness's judging role
    could not read files, the pack would be a Claude-only feature wearing agnostic clothes — and
    a deployment on that harness would silently get a worse tech-lead, which is the one outcome
    the three product promises forbid."""
    mod = __import__(f"openfactory.adapters.agent.{module}", fromlist=["x"])
    src = inspect.getsource(mod)

    assert marker.lower() in src.lower(), (
        f"{module} shows no sign of a read-only file-reading judging role — the fact pack is not "
        f"reachable there, and this guard is the only thing that would say so")


# ── 5. the gaps are GATHERED, not just rendered ─────────────────────────────────────────────────
#
# Two mutations survived the first round and both were the same hole: every guard above feeds
# `write_pack` a gaps list by hand, so deleting the code that COLLECTS gaps from the job rows left
# them all green. The manifest would then say "Everything asked for was read" about a floor where
# two reads had failed — which is worse than saying nothing, because it is a claim.

@pytest.mark.parametrize("job,expected", [
    ({"issue": "87", "state": "on_hold", "comments": None},
     "the ticket thread for 87 could not be read"),
    ({"issue": "87", "state": "on_hold", "verdict_unread": True},
     "the review verdict for 87 could not be read"),
])
def test_a_failed_read_becomes_a_named_gap(job, expected):
    from openfactory.techlead.conversation import _gaps

    assert expected in _gaps([job]), (
        "a read that FAILED is being carried as if it had returned nothing — the manifest will "
        "tell the model everything was read")


@pytest.mark.parametrize("job", [
    {"issue": "87", "state": "on_hold", "comments": []},          # read, genuinely empty
    {"issue": "87", "state": "pr_open", "comments": None},        # not parked: never asked
    # `comments: []` on purpose: for a PARKED job the key absent and the key None both mean the
    # platform does not have the thread, and both are gaps. This case isolates the verdict claim.
    {"issue": "87", "state": "on_hold", "comments": [], "verdict_unread": False},
])
def test_and_a_read_that_SUCCEEDED_is_not_a_gap(job):
    """The twin. A ticket nobody has commented on and a ticket we could not read are different
    facts; a collector that reports both would make the gaps section noise, and a noisy warning is
    one nobody reads."""
    from openfactory.techlead.conversation import _gaps

    assert _gaps([job]) == []


def test_the_gaps_reach_the_manifest_from_the_job_rows(monkeypatch, tmp_path):
    """End to end, because the two halves were guarded separately and the wire between them was
    not: an unreadable thread on a real job row has to come out in the file the model reads."""
    from openfactory.techlead import conversation

    seen: dict[str, object] = {}
    real = conversation.pack.write_pack

    def _spy(root, **kw):
        seen.update(kw)
        return real(_root(tmp_path), **kw)

    monkeypatch.setattr(conversation.pack, "write_pack", _spy)
    landed_context = _context(monkeypatch, pack_ok=True, jobs=[
        {"issue": "87", "state": "on_hold", "title": "t", "comments": None}])

    assert any("87" in g for g in seen.get("gaps", [])), (
        f"the failed read never reached the pack: {seen.get('gaps')}")
    assert "The facts for this question" in landed_context
