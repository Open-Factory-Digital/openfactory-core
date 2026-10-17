"""The typed reads are served under `/api/v1`, their old paths deprecated aliases, and the API's
description committed (#678, slice b), proven by breaking it.

Run:  .venv/bin/python tools/mutate.py tools/mutations/the_reads_are_served_under_api_v1.py

The claims, each a row:
  1. a typed read answers under `/api/v1/…`;
  2. its unversioned path is marked deprecated;
  3. a versioned path is in its alias's area at the gate — only a registered typed read's;
  4. the committed description says the package's version.
"""

TEST = "tests/test_the_api_is_versioned.py"
APP = "openfactory/api/app.py"

MUTATIONS = [
    # 1. the versioned address
    ("a typed read is served only at its unversioned path", APP,
     '        app.get(API_V1 + path.removeprefix("/api"), **_reads(model))(handler)\n',
     ""),

    # 2. the alias, deprecated
    ("the alias is not marked deprecated", APP,
     "        app.get(path, deprecated=True, **_reads(model))(handler)",
     "        app.get(path, **_reads(model))(handler)"),

    # 3. the gate
    ("the gate reads a versioned path as the floor's", APP,
     "    path = _unversioned(path)\n    if path in",
     "    if path in"),

    # 3b. only a registered read is mapped
    ("any path under /api/v1 inherits its alias's area", APP,
     "    if any(read.match(path) for read in _VERSIONED_READS):",
     '    if path.startswith(API_V1 + "/"):'),

    # 4. the version
    ("the app does not say the package's version", APP,
     '              version=__version__)',
     '              version="0.1.0")'),
]
