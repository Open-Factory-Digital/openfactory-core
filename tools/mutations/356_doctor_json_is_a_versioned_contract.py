"""`openfactory doctor --json` is a versioned contract, and the screen and the document read ONE
verdict (#356, core change 1).

Run:  .venv/bin/python tools/mutate.py tools/mutations/356_doctor_json_is_a_versioned_contract.py

The claims, each a row below that must go RED:

  · the document says which version of itself it is (`openfactory.doctor/1`);
  · its keys are the promised ones, by EQUALITY — a key added is a schema change;
  · a check's result is the mark the screen prints, never a constant;
  · the attribution that separates "broken" from "a step ahead answers it" survives (`awaiting`,
    `not_yet`), and so does the EXPECTED verdict, which is decided in one place for both renderings;
  · the build stamp rides inside the document, and stdout carries the document and nothing else;
  · the exit code is the report's in both renderings;
  · the keys are sorted, so two runs of one deployment diff cleanly.
"""

TEST = "tests/test_doctor_json_is_a_versioned_contract.py"

DOCTOR = "openfactory/doctor.py"
CLI = "openfactory/cli.py"

MUTATIONS = [
    ("the document stops saying which version of itself it is", DOCTOR,
     'SCHEMA = "openfactory.doctor/1"',
     'SCHEMA = "openfactory.doctor"'),

    ("a key joins every check without the schema moving", DOCTOR,
     '                "not_yet": f.not_yet,\n',
     '                "not_yet": f.not_yet,\n                "measured_on": "worker",\n'),

    ("a check's result stops being the mark the screen prints", DOCTOR,
     '                "result": "ok" if f.ok else "fail",',
     '                "result": "ok",'),

    ("the downstream attribution is dropped from the document", DOCTOR,
     '                "awaiting": f.awaiting,',
     '                "awaiting": "",'),

    ("the EXPECTED verdict collapses into NOT ready for the document and the screen alike", DOCTOR,
     '    if failed <= answered_later and failed & {"manifest", "box_proof"}:',
     "    if False:"),

    ("the build stamp is dropped from the document", DOCTOR,
     '        "build": {"code": code, "built": built} if code else None,',
     '        "build": None,'),

    ("the keys stop being sorted", DOCTOR,
     "    return json.dumps(document, indent=2, sort_keys=True)",
     "    return json.dumps(document, indent=2)"),

    ("a banner line is printed above the document, so stdout no longer parses", CLI,
     "        typer.echo(doc.as_json(doc.as_document(report, project=name, build=(code, built))))",
     '        typer.echo(f"· this worker runs build {code}")\n'
     "        typer.echo(doc.as_json(doc.as_document(report, project=name, build=(code, built))))"),

    ("--json exits 0 over a red report", CLI,
     "        if not report.ok:\n            raise typer.Exit(1)\n        return\n    if code:",
     "        return\n    if code:"),

    ("the screen's EXPECTED sentence stops naming the step the verdict carries", CLI,
     '                   f"Next: {said.next_step}. Then run this again; it is the same command '
     'that "',
     '                   f"Next: the steps ahead. Then run this again; it is the same command '
     'that "'),
]
