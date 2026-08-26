"""`sdlc box prove` printed PROVEN about a file it had not written.

`save` swallowed the OSError — correctly, because an unwritable proof directory must not fail a
proof that genuinely succeeded — and then returned the path REGARDLESS. So the CLI printed
*"PROVEN — … (recorded at /var/lib/openfactory/proofs/<p>.json)"* about a file that does not exist. The
`log.warning` underneath is invisible: `openfactory/cli.py` configures no logging at all.

ONE LINE EXPLAINED WHAT LOOKED LIKE THREE SEPARATE BUGS. An audit measured, at the same instant on
the same project: `sdlc doctor` → *"OK — can run a ticket"*; `box_prove.gate_reason` → *"the box has
never been proven"*; and the poller holding pickup. The proof had succeeded and nothing was
recorded, so the gate was right and the operator had been told otherwise.

AND IT FAILS IN THE EXACT SCENE THE PRODUCT IS SOLD INTO — the OpenFactory tech-lead running this
beside the client's developers, reading PROVEN, and the first ticket then sitting still with no
explanation. This platform's headline promise is that no stall is ever silent. Onboarding was
outside it, and this is what "outside it" costs.
"""

from __future__ import annotations

import pathlib

from openfactory.box_prove import Proof, save


def test_a_proof_that_could_not_be_written_returns_None(tmp_path, monkeypatch):
    """`None` is the answer that lets the caller tell the truth. The path was a claim."""
    unwritable = tmp_path / "nope"
    unwritable.write_text("i am a file, not a directory")

    assert save(Proof(project="p", image="img", ok=True), root=unwritable / "proofs") is None


def test_a_proof_that_WAS_written_returns_where(tmp_path):
    """The positive twin: a change that returned None always would hide every successful proof."""
    where = save(Proof(project="p", image="img", ok=True), root=tmp_path)

    assert where is not None and where.exists(), "a real proof must still report where it landed"
    assert where.name == "p.json"


def test_save_still_never_raises(tmp_path):
    """The original reasoning stands and must not be lost: an unwritable directory is not a failed
    proof. What changed is that it is no longer reported as a successful RECORD."""
    blocked = tmp_path / "blocked"
    blocked.write_text("not a directory")
    save(Proof(project="p", image="img", ok=True), root=blocked / "x")  # must not raise


def test_the_CLI_refuses_to_call_an_unrecorded_proof_a_success():
    """Reachability, by AST: the helper being honest is worth nothing if the command still prints
    one sentence for both outcomes."""
    import ast

    source = (pathlib.Path(__file__).resolve().parents[1] / "openfactory" / "cli.py").read_text()
    tree = ast.parse(source)
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.FunctionDef) and n.name == "box_prove_cmd")
    body = ast.unparse(fn)

    assert "where is None" in body, (
        "the command does not distinguish a proof that was recorded from one that was not — it "
        "prints PROVEN either way, and the next pickup is then held with no explanation"
    )
    assert "could NOT" in body and "held" in body, (
        "the unrecorded branch must say what happens next, not merely that something went wrong"
    )
