"""The tech-lead reasons only about state it can actually see (#121).

THE ANSWER THAT NAMED THIS CARD. The pilot had `#87`'s pull request open, the panel showing
`View PR · Merge · Adjust… · Discard`, and asked the tech-lead *"pode fazer o merge"*. It replied
that the PR was *"esperando revisão humana"* and that merging needed *"alguém com acesso ao
GitHub"*. Two claims, delivered with complete confidence, and it could check neither:

  - it was never told the job was AT the merge gate. `view.list_jobs` computes an `action` payload
    on every panel refresh — `{kind: "merge_wait", pr_url: …, auto: false}` — hands it to
    `gather_jobs`, and `state_snapshot` dropped it on the floor;
  - it was never told what THIS platform's own review concluded. An independent reviewer had read
    the entire diff and scored it; that verdict lives in the RunResult, which is readable only
    once the workflow FINISHES — and a job at the merge gate has not finished. That is what the
    gate IS. So on the one screen where somebody is deciding whether to land a change, the
    factory's own reading of that change was structurally unavailable;
  - `deploy` was dropped the same way, so a merged job's deploy outcome never reached it either;
  - and its instructions ended with *"never suggest prod/merge actions"* — a rule written when the
    catalogue had no merge row. #120 added one, gated, reachable from this very chat.

A THIRD DEFECT FELL OUT OF WRITING THIS. `state_snapshot` rendered `job["note"]` — the park reason,
which the guidance explicitly tells the model to use ("use its park note to explain WHY"). No row
has ever carried a top-level `note`: `view._row` does not set one, `list_jobs` does not set one,
and the note lives INSIDE the `action` payload nobody read. It rendered as nothing on every job of
every answer ever given, and the test covering it passed because it hand-built a dict in a shape
the producer does not emit. `built-tested-reached-by-nothing`, for the seventeenth time.

WHAT KEEPS IT FIXED is the last section of this file. `_RENDERED` and `_NOT_RENDERED` account for
every key a row can carry, and a field in neither fails the suite — because the thing that went
wrong here was never a bug in a line of code. It was that nothing in the repository related "what
a row carries" to "what the tech-lead is shown", so two fields could be added upstream and land
nowhere, quietly, for months.
"""

from __future__ import annotations

import ast
import inspect

import add_ons
import pytest

from openfactory import actions
from openfactory.actions.base import Actor
from openfactory.runtime.temporal import view as tv
from openfactory.techlead import conversation as conv


def _lines(jobs):
    return conv.state_snapshot(jobs)


#: A job at the merge gate, in the shape `view.list_jobs` really produces.
AT_THE_GATE = {
    "issue": "87", "title": "Plan 3 — the merge gate", "state": "awaiting_your_merge",
    "attention": True, "workflow_id": "openfactory-podbeam-87", "run_id": "r1",
    "action": {"kind": tv.MERGE_WAIT, "pr_url": "https://github.com/o/r/pull/12",
               "auto": False, "gate_live": True, "note": "PR ready — waiting for your merge"},
}


# ── 1. what a job is waiting on ─────────────────────────────────────────────────────────────────

def test_a_job_at_the_merge_gate_says_so_and_gives_the_address():
    out = _lines([AT_THE_GATE])
    assert "WAITING ON" in out, "the merge gate is invisible again — this is the whole card"
    assert "merge" in out.lower()
    assert "https://github.com/o/r/pull/12" in out, (
        "the tech-lead is told a job waits on a pull request and not WHICH pull request")


def test_the_park_note_reaches_the_answer_from_where_it_actually_LIVES():
    """The note is inside `action`. Rendered from a top-level `job["note"]` it was always empty —
    on every job, on every question — while the guidance told the model to reason from it."""
    out = _lines([{"issue": "42", "state": "on_hold", "attention": True,
                   "action": {"kind": "impediment", "state": "on_hold",
                              "note": "gates unfixable after 3 repairs"}}])
    assert "gates unfixable after 3 repairs" in out


def test_a_park_that_asked_a_QUESTION_says_what_it_asked():
    out = _lines([{"issue": "42", "state": "on_hold",
                   "action": {"kind": "impediment", "note": "planner blocked",
                              "decision": {"question": "Which auth provider should this use?",
                                           "options": []}}}])
    assert "Which auth provider should this use?" in out, (
        "a job that asked somebody a question reads as a job that merely failed")


def test_a_park_kind_NOBODY_wrote_prose_for_renders_its_own_name():
    """THE POSITIVE TWIN OF THE WHOLE FIX, and the property the card asks for by name: derived
    from `action`, so a new park kind cannot be invisible. A label table with no fallback would
    reintroduce the exact defect one kind at a time."""
    out = _lines([{"issue": "9", "state": "on_hold",
                   "action": {"kind": "quantum_entanglement", "note": "n/a"}}])
    assert "quantum_entanglement" in out, (
        "a park kind with no phrasing renders as SILENCE — which is what a job that is not "
        "waiting at all also renders as")


def test_the_module_and_the_view_agree_on_what_a_merge_gate_is_CALLED():
    """One string, three surfaces, and a second spelling would not raise — it would quietly mean
    "not a merge", which is a sentence every one of them is willing to say."""
    assert conv._MERGE_WAIT_KIND == tv.MERGE_WAIT
    assert tv.MERGE_WAIT in conv._WAITING_ON


def test_a_job_that_is_simply_WORKING_says_nothing_about_waiting():
    """The negative side. If every job grew a WAITING ON line the phrase would stop meaning
    anything, and the merge gate would be hidden in noise instead of hidden in silence."""
    assert "WAITING ON" not in _lines([{"issue": "5", "state": "running", "title": "x"}])


# ── 2. the deploy outcome ───────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("outcome", ["deploying", "deployed", "deploy_failed", "deploy_timeout"])
def test_the_deploy_outcome_of_a_merged_job_reaches_the_answer(outcome):
    """`deploying` matters as much as the terminal ones: a job that merged four minutes ago is not
    a job whose deploy went missing, and without this they were the same sentence."""
    assert outcome in _lines([{"issue": "90", "state": "merged", "deploy": outcome}])


# ── 3. the factory's own verdict ────────────────────────────────────────────────────────────────

def test_the_review_and_the_gates_reach_the_answer():
    out = _lines([{**AT_THE_GATE, "verdict": {
        "decision": "approved_with_findings", "score": 82, "summary": "solid, two nits",
        "gates": [{"name": "test", "passed": True}, {"name": "lint", "passed": False}],
        "findings": [], "suppressions": []}}])
    assert "approved_with_findings" in out and "82" in out
    assert "test PASSED" in out and "lint FAILED" in out, (
        "the gate results are missing — the tech-lead is guessing at quality it was handed")


def test_a_critical_finding_is_not_averaged_into_a_score():
    out = _lines([{**AT_THE_GATE, "verdict": {
        "decision": "approved_with_findings", "score": 91, "summary": "looks fine",
        "gates": [], "suppressions": [],
        "findings": [{"severity": "critical", "description": "drops the tenant filter",
                      "file": "api/query.py"},
                     {"severity": "low", "description": "naming"}]}}])
    assert "drops the tenant filter" in out and "api/query.py" in out
    assert "looks fine" not in out, (
        "a reassuring summary is shown ALONGSIDE a critical finding — #478 merged that way")


def test_an_added_suppression_is_named_because_it_is_why_a_human_was_asked():
    out = _lines([{**AT_THE_GATE, "verdict": {
        "decision": "approved", "score": 100, "gates": [], "findings": [],
        "suppressions": ["pragma: no cover"]}}])
    assert "pragma: no cover" in out and "suppression" in out.lower()


def test_an_advisory_gate_says_it_is_advisory():
    out = _lines([{**AT_THE_GATE, "verdict": {
        "decision": "", "score": None, "gates": [{"name": "security", "passed": False,
                                                  "advisory": True}],
        "findings": [], "suppressions": []}}])
    assert "advisory" in out, "a reported-never-blocking gate reads as a broken build (C-37)"


def test_a_verdict_that_could_not_be_READ_is_not_a_verdict_of_nothing():
    """The failure mode this module exists to refuse, on the field somebody acts on hardest:
    telling a person the review found nothing, when the query simply failed, is how a rejected
    pull request gets merged on our own advice."""
    out = _lines([{**AT_THE_GATE, "verdict_unread": True}])
    assert "UNREADABLE" in out
    assert "not 'unreviewed'" in out


def test_a_job_NOBODY_ASKED_ABOUT_says_nothing_rather_than_UNREADABLE():
    """Three answers, not two — the same distinction the ticket and board reads pay for. Past the
    cap, or not worth a round trip, is "we did not look", which is neither a verdict nor a
    failure to read one."""
    out = _lines([{"issue": "5", "state": "running", "title": "x"}])
    assert "UNREADABLE" not in out and "review" not in out


# ── 4. the read that makes any of this possible ─────────────────────────────────────────────────

def test_the_workflow_answers_what_its_review_found_WHILE_IT_IS_STILL_RUNNING():
    """A query, not the result. The RunResult carries all of this and is readable only after the
    workflow closes — so at the merge gate, the one state where somebody needs it, it was
    unavailable by construction."""
    from openfactory.runtime.temporal.workflow import JobWorkflow

    assert hasattr(JobWorkflow, "verdict")
    assert getattr(JobWorkflow.verdict, "__temporal_query_definition", None) is not None, (
        "`verdict` stopped being a Temporal query — nothing can ask a running job any more")


def test_adding_it_did_not_need_a_PATCH_and_must_not_grow_one():
    """A query issues no command, so it never enters history and cannot diverge one — which is why
    this shipped to a floor with jobs in flight. `_remember_verdict` must stay the same kind of
    change: state assignment only. An activity or a timer in there is TMPRL1100 on every job that
    was running when it deployed."""
    from openfactory.runtime.temporal.workflow import JobWorkflow

    src = inspect.getsource(JobWorkflow._remember_verdict)
    for command in ("execute_activity", "workflow.sleep", "start_child_workflow", "wait_condition"):
        assert command not in src, (
            f"`_remember_verdict` issues {command} — it runs on the replay path of every job that "
            f"was in flight when this deployed, and a new command there diverges every one of them")


def test_every_attempt_records_what_it_found():
    """On the ATTEMPT path — the one point every run passes through — so a job that parks, is
    resumed and reviewed again reports the LATEST reading, not the first and not nothing.

    Anchored to the call to `_run_job_once` rather than to a method name: what matters is that the
    recording sits with the result of an attempt, wherever that loop is currently spelled."""
    from openfactory.runtime.temporal.workflow import JobWorkflow

    tree = ast.parse(inspect.getsource(JobWorkflow))
    holders = [n.name for n in ast.walk(tree)
               if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
               and "_run_job_once" in ast.unparse(n)
               and "self._remember_verdict(result)" in ast.unparse(n)]
    assert holders, (
        "nothing records the verdict beside the attempt that produced it — the query answers None "
        "for every job, forever, and the tech-lead is blind again")


def test_the_reader_asks_the_jobs_a_person_is_deciding_about_FIRST():
    """The cap's policy is the ordering. A floor with twenty jobs must spend its reads on the one
    at the gate, not on the twenty-first thing that merged last week."""
    gate = {"action": {"kind": tv.MERGE_WAIT}}
    assert conv._worth_a_verdict(gate) > conv._worth_a_verdict({"state": "on_hold"})
    assert conv._worth_a_verdict({"state": "on_hold"}) > conv._worth_a_verdict({"state": "merged"})
    assert conv._worth_a_verdict({"state": "running"}) == 0, (
        "a job that is simply working costs a query per question and answers nothing useful")


# ── 5. what the tech-lead may offer ─────────────────────────────────────────────────────────────

def test_the_vocabulary_is_the_catalogue_filtered_by_the_ASKER():
    admin = Actor(id="a", admin=True)
    # DERIVED, so a row added to the floor grammar appears here without this test being edited —
    # which is what happened when `stop` arrived (#127). What must stay asserted is the RULE, not
    # the list: performable, typeable, and addressable by a ticket alone.
    assert set(actions.proposable(admin)) >= {"resume", "skip", "merge", "discard"}
    assert actions.proposable(Actor(id="b", admin=False)) == (), (
        "somebody who cannot act is being invited to")
    assert actions.proposable(Actor(id="c", admin=True, scopes=frozenset({"product"}))) == (), (
        "a product credential is being offered the floor's actions")


def test_a_PRODUCTION_release_can_never_appear_in_it():
    """The one thing the old sentence got right, now enforced by the catalogue instead of by
    prose: `approve_prod` takes a version and an approver, so no ticket-shaped tag can address it,
    and no grammar a human types at the floor accepts it."""
    for who in (Actor(id="a", admin=True), Actor(id="b", admin=True, scopes=None)):
        offered = set(actions.proposable(who))
        assert not (offered & {"approve_prod", "promote", "product_release", "release_prod"})


def test_the_PROPOSABLE_set_is_exactly_what_it_should_be():
    """THE CLAIM CHANGED, and it is the point of #170. This pinned `adjust` OUT, because
    `[[SUGGEST adjust #87]]` had nowhere to put the instruction — so the tech-lead could propose
    that you throw work away and could not propose what to change. The proposal carries an
    instruction now, and the blast radius is closed by the filter ABOVE this one: `typeable` is a
    fixed set, so relaxing addressability admits exactly `adjust`.

    Asserted as an EXACT set, computed from the catalogue: a new typeable row quietly joining the
    proposable list is a red test, not a surprise on somebody's floor."""
    offered = set(actions.proposable(Actor(id="a", admin=True)))

    assert offered == {"resume", "skip", "merge", "adjust", "discard", "stop", "review"}, offered
    assert not (offered & {"approve_prod", "promote", "product_release", "release_prod"}), (
        "a row that spends money or ships to users became proposable")
    assert "adjust" in __import__(
        "openfactory.actions.floor_intents", fromlist=["x"]).FLOOR_ROWS, (
        "this test is now measuring nothing — adjust left the floor grammar")


def test_the_guidance_stops_forbidding_what_the_catalogue_offers():
    text = conv._guidance(("resume", "skip", "merge", "discard"))
    assert "never suggest prod/merge" not in text.lower()
    assert "merge" in text and "discard" in text
    for verb in ("resume", "skip", "merge", "discard"):
        # FROM THE CATALOGUE ROW since #172. The prose used to live in a map beside the prompt,
        # where it could disagree with the row it described — and did, for `adjust`.
        assert actions.CATALOG[verb].choose_when in text, (
            f"{verb} is offered without saying WHEN to pick it — the model then chooses on the "
            f"verb's English, which is how 'discard' becomes a way to clear a queue")


def test_the_guidance_offers_ONLY_what_the_asker_can_do():
    text = conv._guidance(("resume", "skip"))
    assert "merge" not in text.split("WHAT YOU CAN ACTUALLY DO")[1], (
        "an asker who cannot merge is being told they can — the offer is refused a click later")


def test_a_suggestion_the_asker_could_not_perform_does_not_parse():
    prose, sugg = conv.extract_suggestion(
        "land it.\n[[SUGGEST merge #87]]", can=("resume", "skip"))
    assert sugg is None, "a verb outside the asker's vocabulary was staged for them to approve"
    assert "[[" not in prose, "the raw tag was posted to a person"

    _prose, allowed = conv.extract_suggestion(
        "land it.\n[[SUGGEST merge #87]]", can=("resume", "skip", "merge"))
    assert allowed == ("merge", "87")


def test_the_default_vocabulary_is_the_SAFE_pair():
    """`answer()` is reachable from a script and any future front end. A caller that never thought
    about authority must not be able to stage a merge — the direction `needs_admin` defaults in."""
    assert conv.extract_suggestion("[[SUGGEST merge #87]]")[1] is None
    assert conv.extract_suggestion("[[SUGGEST skip #87]]")[1] == ("skip", "87")


def test_the_asker_is_decided_at_the_DOOR_and_travels_as_data():
    """Authority resolved on the worker would be authority granted on the worker. `_ask` holds the
    actor; the worker holds none and must not build one."""
    from openfactory.runtime.temporal.io import AskInput

    assert AskInput(project="p", question="q").can == [], (
        "an AskWorkflow started before this field existed must still deserialise")
    src = inspect.getsource(__import__(
        "openfactory.actions.catalog", fromlist=["x"])._ask)
    assert "proposable(by)" in src, "the asker's own credential no longer decides what is offered"


def test_a_channel_never_stages_what_it_cannot_PERFORM():
    """Slack's allow-list is narrower than the catalogue on purpose. Offering an action and then
    refusing the "ok" is worse than never offering it."""
    bot = add_ons.module("openfactory.runtime.slack.bot")

    src = inspect.getsource(bot.build_listener) if hasattr(bot, "build_listener") else \
        inspect.getsource(bot)
    assert "_SLACK_MAY" in src
    idx = src.index("answer.suggestion")
    assert "_SLACK_MAY" in src[idx:idx + 600], (
        "the bot stages whatever the tech-lead proposed, including verbs `act_job` refuses")


def test_the_panel_holds_no_second_copy_of_the_vocabulary():
    """READ WITH THE COMMENTS STRIPPED, because the first cut of this guard failed on the comment
    explaining why the list was removed — the third time a guard in this repository has tripped on
    the prose that documents it. What is being asserted is about CODE."""
    from pathlib import Path

    panel = Path(inspect.getfile(
        __import__("openfactory.api.app", fromlist=["x"]))).parent / "panel.html"
    code = "\n".join(ln for ln in panel.read_text().splitlines()
                     if not ln.lstrip().startswith("//"))
    deciding = [ln for ln in code.splitlines() if "m.sugg" in ln and "includes" in ln]
    assert not deciding, (
        f"the panel re-decides which suggestions get a button — it went stale the moment the "
        f"catalogue grew a merge row, rendering the answer as grey text with nothing to "
        f"press: {deciding}")
    assert "/suggestion" in code, (
        "this guard is measuring a page that no longer offers the suggestion at all")


# ── 6. the guard the card asks for: no field lands nowhere ──────────────────────────────────────

def _keys_a_row_can_carry() -> set[str]:
    """Every key the tech-lead's job dicts can hold, read from the code that WRITES them.

    Three producers: `view._row` (a dict literal), `view.list_jobs` (`row["x"] = …`), and
    `conversation.gather_jobs` (`j["x"] = …`). Read from source rather than listed here, so a
    field added upstream reaches this guard without anybody remembering to."""
    def named(target) -> set[str]:
        """The string keys a single assignment target writes.

        TUPLE TARGETS ARE WALKED, and the first version of this did not walk them — so it missed
        `row["state"], row["action"], live = await _domain_state(...)`, which is the line that
        writes the very field this whole card is about. A guard blind to the defect it exists to
        catch is the failure this repository keeps paying for; it was caught here only because the
        vacuity check below demanded `action` by name."""
        if isinstance(target, ast.Tuple):
            return {k for elt in target.elts for k in named(elt)}
        if (isinstance(target, ast.Subscript) and isinstance(target.slice, ast.Constant)
                and isinstance(target.slice.value, str)):
            return {target.slice.value}
        return set()

    found: set[str] = set()
    for obj in (tv._row, tv.list_jobs, conv.gather_jobs):
        tree = ast.parse(inspect.cleandoc("\n" + inspect.getsource(obj)))
        for node in ast.walk(tree):
            if isinstance(node, ast.Dict):
                found |= {k.value for k in node.keys
                          if isinstance(k, ast.Constant) and isinstance(k.value, str)}
            if isinstance(node, ast.Assign):
                for t in node.targets:
                    found |= named(t)
    return found


def test_every_field_a_row_carries_is_either_RENDERED_or_dropped_with_a_REASON():
    """THE GUARD THAT WOULD HAVE PREVENTED THIS CARD. `action` and `deploy` were computed on every
    panel refresh, handed to this module, and dropped — silently, because nothing anywhere related
    the two. A field is either shown to the tech-lead or it is written down as deliberately not
    shown; the reason column is the deliberate half, and only a sentence tells "we decided against
    run_id" apart from "nobody noticed action"."""
    unaccounted = _keys_a_row_can_carry() - conv._RENDERED - set(conv._NOT_RENDERED)
    assert not unaccounted, (
        f"these fields reach the tech-lead's snapshot and nothing decides what happens to them: "
        f"{sorted(unaccounted)}. Render them, or add them to `_NOT_RENDERED` with the reason.")


def test_the_guard_is_reading_real_fields_and_not_an_empty_set():
    """If the producers were rewritten in a shape the walker cannot see, the check above would
    pass by finding nothing — the failure mode every AST guard in this repository has hit."""
    keys = _keys_a_row_can_carry()
    assert {"action", "deploy", "state", "board", "ticket_state"} <= keys, (
        f"the walker no longer sees the fields it exists to police (found {sorted(keys)})")


#: A plausible value per rendered field, so the check below can ask "does this change the answer?"
#: A key in `_RENDERED` with no probe FAILS rather than being skipped.
_PROBES = {
    "issue": "777", "title": "a title", "state": "on_hold", "attention": True,
    "board": "Needs Action", "board_unread": True,
    "ticket_state": "closed", "ticket_unread": True,
    "deploy": "deploy_failed",
    "action": {"kind": tv.MERGE_WAIT, "pr_url": "https://x/pull/1", "note": "n"},
    "verdict": {"decision": "rejected", "score": 3, "gates": [], "findings": [],
                "suppressions": []},
    "verdict_unread": True,
    "wedged": True,
}


def test_everything_claimed_as_RENDERED_actually_changes_the_answer():
    """The positive twin of the registry. Listing a field as rendered while rendering nothing is
    the same lie as dropping it, wearing a label that says otherwise — and it is how this guard
    would rot: somebody removes a line and the registry keeps saying it is shown."""
    base = {"issue": "1", "state": "running"}
    missing_probe = conv._RENDERED - set(_PROBES)
    assert not missing_probe, f"no probe value for {sorted(missing_probe)} — add one"
    for key in sorted(conv._RENDERED):
        without = _lines([base])
        with_it = _lines([{**base, key: _PROBES[key]}])
        assert with_it != without, (
            f"`{key}` is listed in `_RENDERED` and changes nothing the tech-lead reads")

