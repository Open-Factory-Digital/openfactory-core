"""The harness says which of a deployment's settings it authenticates with, and every probe asks it
(#582), proven by breaking it.

Run:  .venv/bin/python tools/mutate.py \
        tools/mutations/582_the_harness_says_which_credential_it_runs_on.py

A deployment on the token pool alone ran, passed the doctor and failed the installer's preflight:
three lists of what an agent credential is, compared by nothing. The claims, each a row:

  1. the adapter's one reading: the pool first, then the single names, a broken pool beside a token
     said as no failover, and a pool with no token in it said as such — and `_load_agent_token_pool`
     acts on that same reading;
  2. the registry hands every probe the harness's own reading;
  3. the preflight asks it over the deployment's settings — the file under the environment — for
     the harness the deployment names, and its failure says what was read;
  4. the doctor asks it for the project's harness.
"""

TEST = "tests/test_the_harness_says_which_credential_it_runs_on.py"
ADAPTER = "openfactory/adapters/agent/claude_code.py"
REGISTRY = "openfactory/adapters/agent/registry.py"
PREFLIGHT = "openfactory/preflight.py"
DOCTOR = "openfactory/doctor.py"

MUTATIONS = [
    # 1. the adapter's one reading
    ("the reading ignores the pool, as the preflight's list did", ADAPTER,
     '    if pool:\n        return POOL, f"a pool of {len(pool)}"\n',
     ""),
    ("a broken pool beside a token says nothing of the failover it lost", ADAPTER,
     '    broken = f"{POOL} is set and {why}, so there is no failover" if why else ""',
     '    broken = ""'),
    ("a pool with no token in it is taken for no pool at all", ADAPTER,
     '    return pool, ("" if pool else "it holds no entry with a token")',
     "    return pool, \"\""),
    ("the adapter runs on a reading of its own, not the one the probes are given", ADAPTER,
     "    pool, why = _pool_in(os.environ)\n    if pool:\n        return pool\n",
     "    pool, why = [], \"\"\n    if pool:\n        return pool\n"),
    ("a broken pool alone is said as nothing set", ADAPTER,
     '    return "", (f"{POOL} is set and {why}" if why else',
     '    return "", (f"none of {POOL} is set" if why else'),

    # 2. the registry
    ("the harness that reads a credential is missing from the table", REGISTRY,
     '    "claude_code": _claude_credential,\n',
     ""),

    # 3. the preflight
    ("TODAY'S DEFECT, BACK: the preflight reads the environment alone", PREFLIGHT,
     "    reading = harness_credential(kind, settings)",
     "    reading = harness_credential(kind, os.environ)"),
    ("the preflight asks the default harness, whatever the deployment names", PREFLIGHT,
     '    kind = (settings.get(variable) or "").strip() or default',
     "    kind = default"),
    ("the preflight's failure says nothing of what it read", PREFLIGHT,
     '        "agent_credential", f"no agent credential is visible to this deployment ({detail})",',
     '        "agent_credential", "no agent credential is visible to this deployment",'),

    # 4. the doctor
    ("the doctor asks one harness whatever the project runs", DOCTOR,
     "        reading = harness_credential(kind, os.environ)",
     '        reading = harness_credential("claude_code", os.environ)'),
    ("the doctor passes a broken pool alone", DOCTOR,
     "        name, said = reading\n        if not name:\n            return False, said\n"
     '        return True, (f"{name} is present"',
     "        name, said = reading\n"
     '        return True, (f"{name} is present"'),
]
