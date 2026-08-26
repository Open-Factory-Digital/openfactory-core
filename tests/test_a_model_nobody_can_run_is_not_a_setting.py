"""A model this harness will not run must not look like a configuration (pilot, 2026-08-15).

`openfactory project set-model podbeam claude-fiofo2` was accepted in silence, and the panel then
showed `agent claude-fiofo2` in the MODELS gauge exactly as it shows a real one. The next job would
have failed — and failed obscurely, because the harness answers a rejected model with
`subtype: "success"`, `is_error: true`, `total_cost_usd: 0`, an assistant message from
`<synthetic>`, and exit code ZERO. Measured against the real CLI, not assumed.

The fix is two-sided, and the shape of it is forced by a third measurement:

    claude-sonnet-4-5-20250929              → silence           (known)
    claude-fiofo2                           → "is not a model…" (a typo)
    arn:aws:bedrock:…:inference-profile/…   → "is not a model…" (LEGITIMATE)

A typo and an enterprise route are indistinguishable at set time, so the command WARNS and never
refuses — blocking the third line would break the deployments this platform exists to serve. The
authority is the first job, which now fails naming the model and the command that changes it.
"""

from __future__ import annotations

import json

from openfactory.adapters.agent.claude_code import _parse_stream, recognises_model


def _stream(**result) -> str:
    """The CLI's own shape for a rejected model, as measured."""
    return "\n".join([
        json.dumps({"type": "system", "subtype": "init", "session_id": "s-1"}),
        json.dumps({"type": "assistant", "message": {"model": "<synthetic>", "content": [
            {"type": "text", "text": result.get("result", "")}]}}),
        json.dumps({"type": "result", "subtype": "success", "is_error": True,
                    "total_cost_usd": 0, "duration_api_ms": 0, "session_id": "s-1", **result}),
    ])


REJECTION = ("There's an issue with the selected model (claude-fiofo2). It may not exist or you "
             "may not have access to it. Run --model to pick a different model.")


def test_a_rejected_model_fails_BY_NAME_and_says_where_it_came_from():
    """The harness's sentence names the model and stops there. An operator needs the rest: that it
    is THIS PROJECT's setting, and the command that changes it — before the job spends its repair
    attempts on a ticket that was never the problem."""
    res = _parse_stream(0, _stream(result=REJECTION))

    assert res.ok is False
    assert "claude-fiofo2" in res.summary
    assert "set-model" in res.summary, "the failure does not say how to change the model"
    assert res.pause_reason is None, "a model nobody can run is not a rate limit to wait out"


def test_the_operator_reads_a_sentence_and_not_an_envelope():
    """The harness's sentence arrives INSIDE a JSON event, so "to the end of the line" dragged the
    rest of the envelope into the note an operator reads — `…pick a different model."}],
    "context_management":null,"parent_tool_use_id":null,…` (pilot, 2026-08-15). A message that
    turns into a wall of JSON is one nobody reads to the end, including the part that matters."""
    from openfactory.adapters.agent.claude_code import _model_rejection

    event = ('{"type":"assistant","message":{"content":[{"type":"text","text":"There\'s an issue '
             'with the selected model (claude-fiofo553). It may not exist or you may not have '
             'access to it. Run --model to pick a different model."}],"context_management":null},'
             '"session_id":"dee65d00","error":"model_not_found","is_api_error_message":true}')
    got = _model_rejection(event)

    assert got.endswith("Run --model to pick a different model.")
    assert "claude-fiofo553" in got
    for debris in ('"}', '":', "context_management", "session_id", "null"):
        assert debris not in got, f"the note carries the JSON envelope: {debris!r}"

    # and a harness that prints the same sentence as PLAIN TEXT is still matched whole
    plain = "There's an issue with the selected model (x). Run --model to pick a different model."
    assert _model_rejection(plain) == plain


def test_the_exit_code_cannot_be_trusted_here():
    """MEASURED: the CLI exits ZERO for a rejected model. Any detection keyed on `rc` would see a
    successful run that produced nothing."""
    res = _parse_stream(0, _stream(result=REJECTION))
    assert res.ok is False, "a zero exit made a rejected model read as a successful job"


def test_a_healthy_run_is_never_mistaken_for_a_rejected_model():
    """The negative twin. `result` text is the AGENT's own prose on a successful run — a ticket
    about model selection legitimately quotes this sentence, and classifying that as a
    configuration failure would park a healthy job (the same trap `_detect_pause` documents)."""
    healthy = "\n".join([
        json.dumps({"type": "result", "subtype": "success", "is_error": False,
                    "result": "I fixed the model picker; it no longer says there's an issue with "
                              "the selected model.", "total_cost_usd": 0.4, "num_turns": 3}),
    ])
    res = _parse_stream(0, healthy)
    assert res.ok is True
    assert "set-model" not in res.summary


def test_an_unrecognised_name_is_reported_and_never_refused(monkeypatch):
    """A Bedrock ARN and a typo produce the SAME answer from the harness, so this can only ever be
    a warning. The guard pins that: an unrecognised name still reaches the registry."""
    from openfactory import cli

    monkeypatch.setattr(cli, "_model_recognition_note",
                        lambda project, model: "⚠ the harness does not recognise it")
    # the note is printed by the command, but nothing about it may change what is stored
    import inspect

    src = inspect.getsource(cli.project_set_model)
    assert src.index("reg.set_model") < src.index("_model_recognition_note"), (
        "the model is only saved if the harness recognises it — an enterprise route is refused")
    assert "raise typer.Exit" not in src.split("_model_recognition_note")[1], (
        "an unrecognised name exits non-zero — a Bedrock ARN would be treated as a typo")


def test_could_not_ask_is_never_reported_as_approved(monkeypatch, tmp_path):
    """THE DEFECT THIS TURN FOUND, in the fix from the turn before. The probe returned "" for
    both "the harness approved it" and "the harness could not be asked", so on a machine where
    it cannot run — no CLI, a container too cold to answer, a binary that exits at once — the
    operator saw the same silence as a confirmation and read it as one.

    `tail()` on the sandbox port documents the same distinction in as many words: `None` and `[]`
    are different answers, and collapsing them is this repository's most expensive defect."""
    from openfactory.adapters.agent.claude_code import recognises_model

    verdict, detail = recognises_model("x", harness="no-such-binary-anywhere-xyz")
    assert verdict == "unchecked", "a missing harness was reported as approval"
    assert detail, "the operator is not told WHY it could not be checked"

    # a harness that exits without ever reading the model name says nothing ABOUT THE MODEL
    assert recognises_model("x", harness="true")[0] == "unchecked"


def test_the_command_says_it_could_not_check_rather_than_nothing(monkeypatch, tmp_path):
    """A blank line where a check was expected is indistinguishable from a check that passed."""
    from openfactory import cli

    reg = tmp_path / "registry.yaml"
    reg.write_text(json.dumps({"projects": {"demo": {
        "name": "demo", "repo_path": str(tmp_path), "harness": "claude_code"}}}))
    monkeypatch.setenv("OPENFACTORY_REGISTRY", str(reg))

    class _Cannot:
        @staticmethod
        def recognises_model(model):
            return "unchecked", "the harness said nothing in 3s"

    class _Approves:
        @staticmethod
        def recognises_model(model):
            return "known", ""

    monkeypatch.setattr("openfactory.adapters.agent.registry.build_executor",
                        lambda *a, **k: _Cannot())
    note = cli._model_recognition_note("demo", "whatever")
    assert "not checked" in note, "an unrunnable probe reported as a clean bill of health"

    monkeypatch.setattr("openfactory.adapters.agent.registry.build_executor",
                        lambda *a, **k: _Approves())
    assert cli._model_recognition_note("demo", "whatever") == "", (
        "a model the harness approved still prints a line — noise the operator learns to ignore")


def test_the_verdict_needs_the_harness_to_have_READ_the_name(monkeypatch):
    """THE DEFECT THE PILOT'S WORKER EXPOSED. The previous cut inferred "known" from the process
    being ALIVE after a three-second wall — true of a healthy run, and equally true of a node CLI
    still booting in a cold container. So a typo came back approved, in silence, on the one
    machine that matters. `init` is the harness saying it has read its arguments; without it there
    is no verdict, only "I could not ask"."""
    import select as _select
    import subprocess

    def _run(lines, alive=True):
        class _Pipe:
            def __init__(self):
                self._left = list(lines)

            def fileno(self):
                return 0

            def readline(self):
                return self._left.pop(0) if self._left else ""

            def close(self):
                pass

        class _Proc:
            returncode = 0 if alive else 1

            def __init__(self):
                self.stdout = _Pipe()
                self.killed = False

            def poll(self):
                return None if alive else 1

            def kill(self):
                self.killed = True
                _run.last = self

        _run.last = None
        monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: _Proc())
        monkeypatch.setattr(_select, "select", lambda r, w, x, t: (r, [], []))
        return recognises_model("x-9")

    INIT = '{"type":"system","subtype":"init","model":"x-9"}\n'
    REJECT = ('{"type":"assistant","message":{"model":"<synthetic>","content":'
              '[{"text":"There\'s an issue with the selected model (x-9)."}]}}\n')

    assert _run([INIT, REJECT])[0] == "unknown"
    assert _run([INIT])[0] == "known", "the name was read and not objected to"

    # THE SECOND NET, ON ITS OWN. `<synthetic>` is the CLI answering from nowhere — it contacted
    # no model (`duration_api_ms: 0`), so whatever it says, it did not run this one. Worded
    # differently by a future version, the sentence match would miss and this must still catch it.
    SYNTHETIC_ONLY = ('{"type":"assistant","message":{"model":"<synthetic>","content":'
                      '[{"text":"Try a different model."}]}}\n')
    verdict, detail = _run([INIT, SYNTHETIC_ONLY])
    assert verdict == "unknown", "a locally-answered rejection was read as a working model"
    assert "x-9" in detail, "the note does not name the model it is about"
    # NO init: the CLI never got that far, whatever else it printed
    assert _run(["Booting…\n", "still booting…\n"], alive=True)[0] == "unchecked"
    assert _run([], alive=False)[0] == "unchecked"


def test_the_probe_stops_the_harness_rather_than_letting_it_work(monkeypatch):
    """A configuration command may not quietly buy an agent turn: whatever the verdict, the
    process is killed rather than left to work through the prompt."""
    import select as _select
    import subprocess

    state = {}

    class _Pipe:
        def fileno(self):
            return 0

        def readline(self):
            return '{"type":"system","subtype":"init","model":"x"}\n'

        def close(self):
            pass

    class _Proc:
        returncode = 0

        def __init__(self):
            self.stdout = _Pipe()
            state["proc"] = self
            self.killed = False

        def poll(self):
            return None

        def kill(self):
            self.killed = True

    monkeypatch.setattr(subprocess, "Popen",
                        lambda cmd, **k: state.setdefault("cmd", cmd) and _Proc() or _Proc())
    monkeypatch.setattr(_select, "select", lambda r, w, x, t: (r, [], []))

    recognises_model("x")
    assert state["proc"].killed, "the harness was left running after the verdict"
    assert "--max-turns" not in state["cmd"], "the probe asks the model to WORK, not to start"
    assert "--permission-mode" in state["cmd"], (
        "the probe runs with different flags from the real invocation, so it answers a "
        "different question — the pilot's worker refused the probe and ran the job fine")


def test_a_harness_without_the_capability_SAYS_it_cannot_check(monkeypatch, tmp_path):
    """CLAUDE IS ONE HARNESS OF SEVERAL, and the model string is whatever that harness names its
    own way — so `codex`, `kimi` and `opencode` have no recognition capability to probe. The port
    says an optional capability is degraded without, and the first cut degraded to SILENCE: the
    same blank line a checked-and-fine model produces. A deployment on another harness would have
    read it as approval (pilot, 2026-08-15: *"the claude harness is one of the options,
    like the anthropic models — this tool will have to serve several harnesses x models"*)."""
    from openfactory import cli

    reg = tmp_path / "registry.yaml"
    reg.write_text(json.dumps({"projects": {"demo": {
        "name": "demo", "repo_path": str(tmp_path), "harness": "codex"}}}))
    monkeypatch.setenv("OPENFACTORY_REGISTRY", str(reg))

    class _Mute:
        pass  # a harness with no recognition capability at all

    monkeypatch.setattr("openfactory.adapters.agent.registry.build_executor",
                        lambda *a, **k: _Mute())
    note = cli._model_recognition_note("demo", "o4-mini")
    assert "not checked" in note, "a harness that cannot check reported as one that approved"
    assert "codex" in note, "the operator is not told WHICH harness could not answer"


def test_the_model_surfaces_name_no_harness_and_no_vendor():
    """The tool serves harness × model, so nothing that decides what to SHOW or SAVE may know a
    harness's name. Claude-specific knowledge belongs in the Claude adapter — the CLI asks the
    harness the project declared, and the panel renders whatever string came back."""
    import ast
    import inspect
    import textwrap
    from pathlib import Path

    from openfactory import cli

    vendors = ("claude", "anthropic", "gpt", "codex", "kimi", "opencode", "bedrock")
    for fn in (cli._model_recognition_note, cli.project_set_model):
        tree = ast.parse(textwrap.dedent(inspect.getsource(fn)))
        # NAMING a vendor is fine and is not the defect — the command's own help text lists
        # `claude-fable-5`, `gpt-5` and a Bedrock ARN precisely to show that any of them fits.
        # DECIDING on one is the defect. So the question is whether any COMPARISON or branch
        # tests a harness name, which is what "this tool serves several harnesses" forbids.
        for node in ast.walk(tree):
            if not isinstance(node, ast.Compare):
                continue
            literals = [n.value.lower() for n in [node.left, *node.comparators]
                        if isinstance(n, ast.Constant) and isinstance(n.value, str)]
            hit = [v for v in vendors for lit in literals if v in lit]
            assert not hit, (
                f"{fn.__name__} branches on the harness {hit[0]!r} — it must ask the harness the "
                "project declared and pass the model string through verbatim")
    assert "harness_kind(" in inspect.getsource(cli._model_recognition_note), (
        "the harness is assumed rather than resolved from the project")

    panel = (Path(cli.__file__).resolve().parent / "api" / "panel.html").read_text()
    bar = panel[panel.index('<span class="lbl">models</span>'):][:400]
    assert "claude" not in bar.lower(), "the MODELS gauge hardcodes a vendor's name"
