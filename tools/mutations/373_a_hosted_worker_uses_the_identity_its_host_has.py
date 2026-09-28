"""A hosted worker uses the identity its machine was given, declared rather than guessed; the doctor
reports the source the adapter uses; a box is handed a value, never the declaration (#373).

Run:  .venv/bin/python tools/mutate.py tools/mutations/373_a_hosted_worker_uses_the_identity_its_host_has.py

The first row is the defect as it shipped: a declared identity is resolved like no declaration at
all, which is what a hosted worker had — a PAT, or `az`, and no `az` in its image. Rows 2-4 are
the declaration's own rules (never a fallback, never beside `token_env`, never asked undeclared);
5-9 the request to the endpoint and the one refresh machinery; 10-11 the agreement the doctor owes
the adapter — row 10 is the measured case, the doctor counting a GitHub token for an Azure axis;
12-16 the box; 17-19 the doctor's `box_identity` line.
"""

TEST = "tests/test_a_hosted_worker_uses_the_identity_its_host_has.py"

ADO = "openfactory/adapters/azure_devops.py"
REGISTRY = "openfactory/adapters/credential/registry.py"
CREDENTIALS = "openfactory/credentials.py"
DOCTOR = "openfactory/doctor.py"

MUTATIONS = [
    ("TODAY'S DEFECT: a declared identity resolves like no declaration — a PAT, else `az`, and a "
     "hosted worker has neither", ADO,
     "    if declared:\n        client_id",
     "    if False:\n        client_id"),

    ("a declaration nothing can use falls back to whatever else is set", ADO,
     "    if problem:\n        return \"\", None\n    if declared:",
     "    if problem:\n        pass\n    if declared:"),

    ("`token_env` beside `identity: workload` is accepted, so the axis has two credentials",
     REGISTRY,
     "    if str(options.get(\"token_env\") or \"\").strip():\n        return False, (f\"it declares both",
     "    if False:\n        return False, (f\"it declares both"),

    ("an axis that declares nothing asks the metadata endpoint because it happens to be there",
     ADO,
     "    if declared:\n        client_id",
     "    if True:\n        client_id"),

    ("the user-assigned identity's client id never reaches the endpoint, so the machine's own "
     "identity answers instead", ADO,
     "        query[\"client_id\"] = client_id",
     "        pass"),

    ("the identity's request goes through the worker's proxy", ADO,
     "urllib.request.ProxyHandler({})",
     "urllib.request.ProxyHandler()"),

    ("the request carries no `Metadata: true`, which the endpoint refuses", ADO,
     "headers={\"Metadata\": \"true\"}",
     "headers={}"),

    ("one refresh machinery for every identity, so two projects hand each other a token", ADO,
     "        held = _WORKLOAD.get(key)\n        if held is None:\n            held = _WORKLOAD[key] =",
     "        held = _WORKLOAD.get(\"\")\n        if held is None:\n            held = _WORKLOAD[\"\"] ="),

    ("the identity is minted per call rather than held by the shared machinery", ADO,
     "    return held()\n",
     "    return ShortLivedToken(lambda: _workload_mint(key))()\n"),

    ("THE MEASURED CASE: an Azure axis falls through to the deployment's generic pair, so the "
     "doctor counts a GitHub token the Azure adapter never uses", CREDENTIALS,
     "    if row is not None and row.source is not None:\n        if named and announce",
     "    if False:\n        if named and announce"),

    ("the doctor reports a source that answered nothing — a declared identity on the wrong "
     "machine reads as reachable", CREDENTIALS,
     "        return identity if (identity and provider is not None and provider()) else \"\"",
     "        return identity if identity else \"\""),

    ("the box is handed the declaration, and mints from the machine it runs on", CREDENTIALS,
     "    if not declared or problem:\n        return options",
     "    if True:\n        return options"),

    ("a declared identity that did not answer launches a box with no credential", CREDENTIALS,
     "        if not token:\n            raise CredentialUnavailable(",
     "        if False:\n            raise CredentialUnavailable("),

    ("a box handed a declaration anyway keeps it", "openfactory/runtime/boxed_job.py",
     "    if not any(k in options for k in (IDENTITY_OPTION, IDENTITY_CLIENT_ID_OPTION)):\n"
     "        return options",
     "    if True:\n        return options"),

    ("the minted box token reaches the agent's environment",
     "openfactory/adapters/sandbox/worktree.py",
     "    \"OPENFACTORY_BOX_TRACKER_TOKEN\",\n    \"OPENFACTORY_BOX_FORGE_TOKEN\",\n",
     ""),

    ("the doctor's pass names no source, so nobody can tell a PAT from the machine's identity",
     DOCTOR,
     "        using = f\"the forge is reachable with {describe_source(source)}\"",
     "        using = \"\""),

    ("a box that reaches the metadata endpoint is reported as not reaching it", DOCTOR,
     "        if reached:\n            subnet",
     "        if False:\n            subnet"),

    ("a box whose reach could not be measured is reported as safe", DOCTOR,
     "        if reached is None:",
     "        if False:"),

    ("the worktree box, where the agent runs as this machine, passes", DOCTOR,
     "        if not traits.isolates_resources:\n            return (False,",
     "        if not traits.isolates_resources:\n            return (True,"),
]
