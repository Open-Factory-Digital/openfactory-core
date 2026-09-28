"""The doctor's `box_identity` line says a box reaches the metadata endpoint only when the endpoint
answered as itself, and never says "safe" by not recognising an answer (#376, review of #377).

Run:  .venv/bin/python tools/mutate.py tools/mutations/376_a_proxy_is_not_the_metadata_endpoint.py

Row 1 is the defect as it shipped in #374: any HTTP status line counted, so Docker Desktop's proxy
refusing `403 … unreachable network` read as the endpoint answering. Row 2 is the one the review of
#377 found: an answer nobody recognises read as "did not reach", so a service this build does not
know, or Azure's refusal reworded, turned the line green. Rows 3-5 are the control: it must name the
address, every path must match it, and it must be asked. Rows 6-7 read words on the wrong path and
turn an unfinished probe into "safe". Rows 8-10 each drop one service's answer, the positive a fix
could lose. Row 11 sends the header that would make the probe mint the identity's token. Row 12 is
the doctor giving an unplaceable answer the wrong remedy.
"""

TEST = "tests/test_a_proxy_is_not_the_metadata_endpoint.py"

PROBE = "openfactory/adapters/sandbox/container.py"

_PRINTF = 'f\'printf "GET %s HTTP/1.0\\\\r\\\\nHost: {address}\\\\r\\\\n'

MUTATIONS = [
    ("TODAY'S DEFECT: any HTTP answer counts, so a proxy's refusal reads as the endpoint", PROBE,
     '        if any(word in answers.get(path, "") for word in words):',
     '        if "HTTP/" in answers.get(path, ""):'),

    ("THE REVIEW'S DEFECT: an answer nobody recognises reads as 'did not reach', so a service "
     "this build does not know, or Azure reworded, turns the line green", PROBE,
     '    return None, (f"something on {address} answered,',
     '    return False, (f"something on {address} answered,'),

    ("the control need not name the address, so a 404 that is the same everywhere reads as a "
     "proxy and as safe", PROBE,
     '    if (address in control and control.startswith("HTTP/")',
     '    if (control.startswith("HTTP/")'),

    ("one path matching the control is enough, so a proxy forwarding one path to something it "
     "can reach reads as safe", PROBE,
     "            and all(a == control for a in spoken)):",
     "            and any(a == control for a in spoken)):"),

    ("the control path is not asked, so a proxy can no longer be told from a service", PROBE,
     "[p for p, _ in _METADATA_ANSWERS] + [_CONTROL_PATH]",
     "[p for p, _ in _METADATA_ANSWERS]"),

    ("a service's words count on any path", PROBE,
     '        if any(word in answers.get(path, "") for word in words):',
     '        if any(w in answers.get(path, "") for _, ws in _METADATA_ANSWERS for w in ws):'),

    ("a probe that did not run to its end is reported as not reaching", PROBE,
     '        return None, "the probe did not run to its end"',
     '        return False, ""'),

    ("Azure's own refusal is no longer recognised, so a box that reaches it is not red", PROBE,
     '("Required metadata header not specified",)',
     '("an answer no Azure endpoint gives",)'),

    ("GCP's own refusal is no longer recognised", PROBE,
     '("/computeMetadata/v1/", ("Metadata-Flavor",)),',
     '("/computeMetadata/v1/", ("an answer no GCP endpoint gives",)),'),

    ("AWS's own answers are no longer recognised", PROBE,
     '("/latest/meta-data/", ("ami-id", " 401 Unauthorized")),',
     '("/latest/meta-data/", ("an answer no AWS endpoint gives",)),'),

    ("the probe sends the metadata header, so the diagnostic can mint the identity's token", PROBE,
     _PRINTF + '\\\\r\\\\n" "$p" \'',
     _PRINTF + 'Metadata: true\\\\r\\\\n\\\\r\\\\n" "$p" \''),

    ("the doctor gives an answer it cannot place the remedy for docker not answering",
     "openfactory/doctor.py",
     '        if reached is None and detail.startswith("something on"):',
     "        if False:"),
]
