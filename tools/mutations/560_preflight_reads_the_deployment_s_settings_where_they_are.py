"""Preflight reads a deployment's settings where the deployment keeps them (#560), proven by
breaking it.

Run:  .venv/bin/python tools/mutate.py \
        tools/mutations/560_preflight_reads_the_deployment_s_settings_where_they_are.py

The installer's preflight runs with `.env.compose` in its working directory and none of it in its
environment; the credential and port probes read the environment alone, so an upgrade was told no
agent credential was visible. The claims, each a row:

  1. the credential and the ports are read from the file under the environment (rows 1-2);
  2. the environment wins over the file, as compose's own reading does (row 3);
  3. the finding says where the credential was found (row 4).
"""

TEST = "tests/test_preflight_reads_the_deployment_s_settings_where_they_are.py"

PREFLIGHT = "openfactory/preflight.py"

MUTATIONS = [
    # RE-PINNED 2026-10-10 (#582): the harness's own reading is asked over the settings, where
    # this probe kept a list of two names
    ("TODAY'S DEFECT: the credential is looked for in the installer's empty environment",
     PREFLIGHT,
     "    reading = harness_credential(kind, settings)\n",
     "    reading = harness_credential(kind, os.environ)\n"),
    ("the moved ports are not the ones checked", PREFLIGHT,
     '        raw = (settings.get(variable) or "").strip()\n',
     '        raw = (os.environ.get(variable) or "").strip()\n'),
    ("the file wins over the environment", PREFLIGHT,
     "    return {**_env_file_rows(), **os.environ}\n",
     "    return {**os.environ, **_env_file_rows()}\n"),
    # RE-PINNED 2026-10-10 (#582): one level out, after the harness's reading
    ("the finding says the file where the environment held it", PREFLIGHT,
     '    where = "in the environment" if os.environ.get(name) else "in .env.compose"\n',
     '    where = "in .env.compose"\n'),
]
