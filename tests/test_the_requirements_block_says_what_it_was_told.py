"""#125: the requirements block prints the reason it was given, never one it made up.

Measured on a real deployment's product page: the block said *"could not read the requirements —
the documentation repository may need a credential"* while the API answered 200 with the actual
reason in its hand:

    {"ok":true,"data":{"requirements":[],
      "findings":[{"level":"error","message":"the requirements directory does not exist", …}]}}

The credential was fine. A credential is ONE cause; a missing directory, an absent repository and a
`sources:` mismatch are others, and each sends the reader somewhere different. Guessing the
expensive one is what #113 is about, one surface over.

Two truths were being discarded, and both arrive in the same response: `act()`'s `message` (on a
refusal, the corpus's own `ctx.reason`) and `data.findings`, which `actions/catalog.py` builds
precisely so they reach a person — *"a requirement that contradicts another is a thing the person
reading this list is the one who can settle"*. Without them an error-level finding rendered as a
cheerful "nothing written yet".

THESE GUARDS EXECUTE THE FUNCTION. A guard that grepped `panel.html` would be satisfied by this
docstring quoting the sentence it forbids — the failure CONTRIBUTING names. So the real
`paintRequirements` is extracted from the shipped file and run under node against stated state.
"""

from __future__ import annotations

import json
import pathlib
import shutil
import subprocess

import pytest

PANEL = (pathlib.Path(__file__).resolve().parents[1] / "openfactory" / "api"
         / "panel.html").read_text()


def _fn(name: str) -> str:
    """One function, verbatim from the shipped panel, by brace balance."""
    start = PANEL.index(f"function {name}(")
    # `async ` IS PART OF THE FUNCTION. Slicing from `function` drops it, and node then refuses the
    # `await` inside with a syntax error about the caller rather than about the cut.
    if PANEL[max(0, start - 6):start] == "async ":
        start -= 6
    depth, i = 0, PANEL.index("{", start)
    while True:
        if PANEL[i] == "{":
            depth += 1
        elif PANEL[i] == "}":
            depth -= 1
            if depth == 0:
                return PANEL[start:i + 1]
        i += 1


def _line_starting(prefix: str) -> str:
    """One whole source LINE, verbatim — `esc` is a const arrow, not a `function`."""
    for line in PANEL.splitlines():
        if line.strip().startswith(prefix):
            return line.strip()
    raise AssertionError(f"panel.html no longer declares {prefix!r}")


def _paint(state: dict) -> str:
    """Run the shipped `paintRequirements` against `state` and return the HTML it wrote."""
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not on PATH")

    script = f"""
      const el={{innerHTML:""}}, cnt={{textContent:""}};
      const $=(sel)=> sel==="#prodReqs" ? el : sel==="#prodCount" ? cnt : null;
      {_line_starting("const esc=")}
      const _prod={json.dumps(state)};
      {_fn("paintRequirements")}
      paintRequirements();
      console.log(JSON.stringify(el.innerHTML));
    """
    out = subprocess.run([node, "-e", script], capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout)


# ── the failure branch ──────────────────────────────────────────────────────────────────────────

def test_a_failed_read_prints_the_reason_it_was_given():
    html = _paint({"reqs": None, "reqsWhy": "the documentation repository is not reachable",
                   "reqsFindings": []})

    assert "the documentation repository is not reachable" in html
    assert "may need a credential" not in html, (
        "the block invented a cause while holding the one the response carried"
    )


def test_a_failed_read_with_no_reason_admits_it_rather_than_naming_one():
    """The reverse, and it is the half that would quietly come back: a fallback that names a
    plausible cause is the defect again, written as a default."""
    html = _paint({"reqs": None, "reqsWhy": "", "reqsFindings": []})

    assert "it did not say why" in html
    assert "credential" not in html


# ── the success branch ──────────────────────────────────────────────────────────────────────────

def test_an_empty_corpus_carrying_an_error_does_not_read_as_merely_empty():
    """THE DEFECT AS FOUND. The API answered `ok` with an empty list and an error-level finding,
    and the page said 'nothing written yet' — cheerful, and wrong about why."""
    html = _paint({"reqs": [], "reqsWhy": "",
                   "reqsFindings": [{"level": "error",
                                     "message": "the requirements directory does not exist",
                                     "path": "/cache/routing--docs/requirements"}]})

    assert "the requirements directory does not exist" in html
    assert "/cache/routing--docs/requirements" in html, "the path is what a person acts on"
    assert "nothing written yet" in html, "the count is still true and must not be dropped"


def test_a_genuinely_empty_corpus_stays_quiet():
    """…and the reverse: a corpus with nothing wrong must not grow a warning shelf. A block that
    always shows something teaches the reader to stop looking at it."""
    html = _paint({"reqs": [], "reqsWhy": "", "reqsFindings": []})

    assert "nothing written yet" in html
    assert "error" not in html and "note" not in html


def test_findings_ride_along_with_a_populated_corpus_too():
    """A contradiction between two requirements is exactly the case the catalog builds findings
    for, and it happens when the list is NOT empty."""
    html = _paint({"reqs": [], "reqsWhy": "",
                   "reqsFindings": [{"level": "warning", "message": "R2 contradicts R1",
                                     "path": ""}]})

    assert "R2 contradicts R1" in html


def test_a_finding_stays_data_when_it_contains_markup():
    """Everything here is a value from a repository somebody else writes."""
    html = _paint({"reqs": None, "reqsWhy": "<img src=x onerror=alert(1)>",
                   "reqsFindings": [{"level": "error", "message": "<script>bad()</script>",
                                     "path": ""}]})

    assert "<img src=x" not in html and "<script>bad()" not in html
    assert "&lt;img" in html or "&lt;script" in html


# ── the loader, which is where the discarding happened ──────────────────────────────────────────
#
# The guards above state the painter's input and were satisfied by a cut that stopped the LOADER
# capturing it — two mutation rows survived, which is the runner saying the guards were decoration
# for the half that actually broke. These drive `loadRequirements` end to end against a stubbed
# `act()`, so the response is the input and the rendered page is the output.

def _load_then_paint(response) -> dict:
    """Run the shipped `loadRequirements` against a stated API response, then read what the page
    shows and what state it kept. `response` is what `act()` resolves to — `None` for a throw."""
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not on PATH")

    script = f"""
      const el={{innerHTML:""}}, cnt={{textContent:""}};
      const $=(sel)=> sel==="#prodReqs" ? el : sel==="#prodCount" ? cnt : null;
      {_line_starting("const esc=")}
      const _prod={{project:"routing"}};
      const _response={json.dumps(response)};
      // The seam the real one reaches over HTTP. `.catch(()=>null)` in the loader is for a throw,
      // so a null response is delivered as a rejection rather than as a resolved null.
      async function act(){{ if(_response===null) throw new Error("boom"); return _response; }}
      {_fn("paintRequirements")}
      {_fn("loadRequirements")}
      loadRequirements().then(()=>console.log(JSON.stringify(
        {{html:el.innerHTML, why:_prod.reqsWhy, findings:_prod.reqsFindings, reqs:_prod.reqs}})));
    """
    out = subprocess.run([node, "-e", script], capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout)


def test_the_loader_keeps_the_reason_the_action_gave():
    """The line that used to throw it away. `act()` returns `{ok, message, data, status}` and the
    message is the corpus's own sentence on a refusal."""
    got = _load_then_paint({"ok": False, "message": "the documentation repository is not reachable",
                            "data": {}, "status": 200})

    assert got["why"] == "the documentation repository is not reachable"
    assert "the documentation repository is not reachable" in got["html"]
    assert "may need a credential" not in got["html"]


def test_the_loader_keeps_the_corpus_complaints():
    """The second discarded truth, and the one that made an error read as 'nothing written yet'."""
    got = _load_then_paint({"ok": True, "message": "0 requirements", "status": 200,
                            "data": {"requirements": [],
                                     "findings": [{"level": "error",
                                                   "message": "the requirements directory does "
                                                              "not exist",
                                                   "path": "/cache/routing--docs/requirements"}]}})

    assert got["reqs"] == [], "an empty list is not a failed read"
    assert len(got["findings"]) == 1
    assert "the requirements directory does not exist" in got["html"]
    assert "nothing written yet" in got["html"]


def test_a_throw_still_reaches_the_page_without_inventing_a_cause():
    """`.catch(()=>null)` is the branch where there is genuinely nothing to report — and it must
    say that rather than fall back on the guess this issue is about."""
    got = _load_then_paint(None)

    assert got["reqs"] is None and got["why"] == ""
    assert "it did not say why" in got["html"]
    assert "credential" not in got["html"]
