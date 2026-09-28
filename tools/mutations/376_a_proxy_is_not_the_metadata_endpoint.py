"""The doctor's `box_identity` line says a box reaches the metadata endpoint only when the endpoint
answered as itself (#376).

Run:  .venv/bin/python tools/mutate.py tools/mutations/376_a_proxy_is_not_the_metadata_endpoint.py

The first row is the defect as it shipped in #374: any HTTP status line counted, so Docker Desktop's
proxy refusing `403 … unreachable network` read as the endpoint answering. Row 2 reads a service's
words on any path; row 3 turns an unfinished probe into "safe"; rows 4-6 each drop one service's
answer, the positive a fix could lose (row 4 is also caught by the real-daemon test); row 7 sends
the header that would make the probe mint the identity's token.
"""

TEST = "tests/test_a_proxy_is_not_the_metadata_endpoint.py"

PROBE = "openfactory/adapters/sandbox/container.py"

MUTATIONS = [
    ("TODAY'S DEFECT: any HTTP answer counts, so a proxy's refusal reads as the endpoint", PROBE,
     "        if any(word in answer for word in answers.get(path.strip(), ())):",
     '        if "HTTP/" in answer:'),

    ("a service's words count on any path", PROBE,
     "        if any(word in answer for word in answers.get(path.strip(), ())):",
     "        if any(w in answer for ws in answers.values() for w in ws):"),

    ("a probe that did not run to its end is reported as not reaching", PROBE,
     "    if _PROBE_END not in out:\n        return None",
     "    if _PROBE_END not in out:\n        return False"),

    ("Azure's own refusal is no longer recognised, so a box that reaches it reads as safe", PROBE,
     '("Required metadata header not specified",)',
     '("an answer no Azure endpoint gives",)'),

    ("GCP's own refusal is no longer recognised", PROBE,
     '("/computeMetadata/v1/", ("Metadata-Flavor",)),',
     '("/computeMetadata/v1/", ("an answer no GCP endpoint gives",)),'),

    ("AWS's own answers are no longer recognised", PROBE,
     '("/latest/meta-data/", ("ami-id", " 401 Unauthorized")),',
     '("/latest/meta-data/", ("an answer no AWS endpoint gives",)),'),

    ("the probe sends the metadata header, so the diagnostic can mint the identity's token", PROBE,
     'f\'printf "GET %s HTTP/1.0\\\\r\\\\nHost: {address}\\\\r\\\\n\\\\r\\\\n" "$p" \'',
     'f\'printf "GET %s HTTP/1.0\\\\r\\\\nHost: {address}\\\\r\\\\n'
     'Metadata: true\\\\r\\\\n\\\\r\\\\n" "$p" \''),
]
