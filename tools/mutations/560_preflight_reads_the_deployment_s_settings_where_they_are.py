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
    ("TODAY'S DEFECT: the credential is looked for in the installer's empty environment",
     PREFLIGHT,
     "    for name in (\"CLAUDE_CODE_OAUTH_TOKEN\", \"ANTHROPIC_API_KEY\"):\n"
     "        if settings.get(name):\n",
     "    for name in (\"CLAUDE_CODE_OAUTH_TOKEN\", \"ANTHROPIC_API_KEY\"):\n"
     "        if os.environ.get(name):\n"),
    ("the moved ports are not the ones checked", PREFLIGHT,
     '        raw = (settings.get(variable) or "").strip()\n',
     '        raw = (os.environ.get(variable) or "").strip()\n'),
    ("the file wins over the environment", PREFLIGHT,
     "    return {**_env_file_rows(), **os.environ}\n",
     "    return {**os.environ, **_env_file_rows()}\n"),
    ("the finding says the file where the environment held it", PREFLIGHT,
     '            where = "in the environment" if os.environ.get(name) else "in .env.compose"\n',
     '            where = "in .env.compose"\n'),
]
