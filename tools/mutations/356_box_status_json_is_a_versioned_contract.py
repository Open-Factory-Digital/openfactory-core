"""`openfactory box status --json` is a versioned contract — the proof's digest, its toolchain pins
and its validity, per repository — and the text report is the one it always was (#356, core
change 2).

Run:  .venv/bin/python tools/mutate.py tools/mutations/356_box_status_json_is_a_versioned_contract.py

The claims, each a row below that must go RED:

  · the document says which version of itself it is, and its keys are pinned by equality;
  · it carries the digest, the toolchain ONE PIN PER LINE, the validity and the remedy;
  · `advisories` keeps three states — no record is not a record of none;
  · freshness is judged by `_freshness_reason`, the poller's own function, and a failed proof is
    not reported as an expired one;
  · `--json` exits with the status's code, and the lines a person reads did not move.
"""

TEST = "tests/test_box_status_json_is_a_versioned_contract.py"

BOX = "openfactory/box_prove.py"
CLI = "openfactory/cli.py"

MUTATIONS = [
    ("the document stops saying which version of itself it is", BOX,
     'STATUS_SCHEMA = "openfactory.box-status/1"',
     'STATUS_SCHEMA = "openfactory.box-status"'),

    ("a key joins the document without the schema moving", BOX,
     '            "schema": STATUS_SCHEMA,',
     '            "schema": STATUS_SCHEMA,\n            "measured_on": "worker",'),

    ("the toolchain is one string instead of one pin per line", BOX,
     '            "toolchain": [pin for pin in (proof.toolchain if proof else "").split("\\n") '
     'if pin],',
     '            "toolchain": [proof.toolchain] if proof else [],'),

    ("the digest is dropped from the document", BOX,
     '            "digest": proof.digest if proof else "",',
     '            "digest": "",'),

    ("every repository reads as valid", BOX,
     '            "valid": self.valid,',
     '            "valid": True,'),

    ("the remedy is dropped from a status that needs one", BOX,
     '            "remedy": "" if self.valid else f"run `{self.command}`",',
     '            "remedy": "",'),

    ("no record reads as a record of zero advisories", BOX,
     "                            for a in proof.advisories()] if recorded else None),",
     "                            for a in proof.advisories()] if recorded else []),"),

    ("the status stops asking the poller's freshness function", BOX,
     '    why = _freshness_reason(proof, digest=live_digest, variant=variant, commands=current,\n'
     '                            run_it=f"run `{command}`")',
     "    why = None"),

    ("a failed proof is reported as an expired one", BOX,
     '        return BoxStatus(name, repo, proof_key, "failed", "the last proof FAILED", command,',
     '        return BoxStatus(name, repo, proof_key, "expired", "the last proof FAILED", command,'),

    ("the toolchain line a person reads stops splitting the pins", BOX,
     '                out.append("  toolchain " + " · ".join(proof.toolchain.split("\\n")))',
     '                out.append("  toolchain " + proof.toolchain)'),

    ("--json exits 0 whatever the status", CLI,
     "        typer.echo(box_prove.status_json(st))",
     "        typer.echo(box_prove.status_json(st))\n        return"),
]
