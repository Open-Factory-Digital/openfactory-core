"""The deployment's env file is read by one set of rules, and an unreadable one is said as such
(#583), proven by breaking it.

Run:  .venv/bin/python tools/mutate.py \
        tools/mutations/583_one_reader_reads_the_deployment_s_env_file.py

The preflight read `PANEL_PORT=8788  # moved` as `8788  # moved` and checked the default port, read
`export KEY=v` as the key `export KEY`, and read a file it could not open as no file at all. The
claims, each a row:

  1. `envfile` reads by dotenv's rules: comments, quotes and `export`; a name with no value is left
     out; nothing is interpolated;
  2. a file that is there and cannot be read is not an absent one;
  3. the preflight reads through it, fails `env_file` on an unreadable file with the repair, and
     the credential line says the file could not be read rather than that nothing is set;
  4. the preview assembler reads a product's env file through it.
"""

TEST = "tests/test_one_reader_reads_the_deployment_s_env_file.py"
ENVFILE = "openfactory/envfile.py"
PREFLIGHT = "openfactory/preflight.py"
ASSEMBLE = "openfactory/preview/assemble.py"

MUTATIONS = [
    # 1. the one set of rules
    ("TODAY'S DEFECT, BACK: the rows are split by hand", ENVFILE,
     "    values = dotenv_values(stream=io.StringIO(text), interpolate=False)\n",
     "    values = {k.strip(): v.strip().strip(\"'\\\"\") for k, _, v in\n"
     "              (line.strip().partition(\"=\") for line in text.splitlines())\n"
     "              if k.strip() and not k.strip().startswith(\"#\")}\n"),
    ("a value is expanded as it is read", ENVFILE,
     "interpolate=False)\n",
     "interpolate=True)\n"),
    ("a name with no value is kept as one", ENVFILE,
     "if key and value is not None}",
     "if key}"),

    # 2. there and not to be read
    ("an unreadable file reads as an absent one", ENVFILE,
     "        return EnvFile(exists=True, unreadable=(exc.strerror or type(exc).__name__).lower())",
     "        return EnvFile()"),

    # 3. the preflight
    ("the preflight keeps a parser of its own", PREFLIGHT,
     "    return envfile.read(path).rows\n",
     "    return {k: v for k, _, v in (line.partition(\"=\") for line in\n"
     "            envfile.Path(path).read_text().splitlines()) if \"=\" in line}\n"),
    ("an unreadable file passes `env_file`", PREFLIGHT,
     "    if unreadable:\n        return _fail(",
     "    if False:\n        return _fail("),
    ("the credential line says nothing is set where the file could not be read", PREFLIGHT,
     '"neither CLAUDE_CODE_OAUTH_TOKEN nor ANTHROPIC_API_KEY is set" + _unread()',
     '"neither CLAUDE_CODE_OAUTH_TOKEN nor ANTHROPIC_API_KEY is set"'),

    # 4. the preview
    ("the preview reads a product's env file by no rules at all", ASSEMBLE,
     "        out.extend(envfile.read(path).rows.items())\n",
     "        out.extend((line.partition(\"=\")[0], line.partition(\"=\")[2]) for line in\n"
     "                   open(path).read().splitlines() if \"=\" in line)\n"),
]
