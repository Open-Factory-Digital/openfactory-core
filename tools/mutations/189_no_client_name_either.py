"""The identity guard has to bite on a CLIENT's name, not only the owner's (#188 sibling).

Each cut is a way the name comes back: quoted as evidence in a docstring, left in a fixture
identifier, published in a how-to, or dropped from the list that forbids it. The last two cuts
are about the guard's own shape — a list emptied of the client shape, and a list nobody reads.

SYNTHETIC NAMES ONLY (2026-08-25): the client names this plan used to plant were real, which made
the plan one more tracked file naming a client. See `tests/identity_forbidden.py`.
"""

TEST = "tests/test_the_product_carries_no_owners_name.py"
SHAPES = "tests/identity_forbidden.py"

MUTATIONS = [
    ("a client's organisation comes back as evidence in a docstring",
     "openfactory/adapters/forge/azure_devops.py",
     "        deployment has both shapes at once — measured on a real enterprise organisation,",
     "        deployment has both shapes at once (ExampleClient, 2026-08-12), an organisation"),

    ("a client's project name comes back in a fixture identifier",
     "tests/test_project_add_speaks_azure_devops.py",
     '_URL = "https://dev.azure.com/acme-ai/Deskline/_git/dsk-api"',
     '_URL = "https://dev.azure.com/exampleclient/Deskline/_git/dsk-api"'),

    ("an internal repository URL is published in a how-to",
     "docs/setup/azure-devops.md",
     "    repo_path: https://dev.azure.com/acme-ai/Deskline/_git/dsk-api",
     "    repo_path: https://dev.azure.com/exampleclient/Deskline/_git/dsk-api"),

    ("the maintainer's address is pasted into a document",
     "README.md",
     "# OpenFactory",
     "# OpenFactory\n\nQuestions: maint@example.invalid"),

    ("the client shape is dropped from the list — the guard keeps passing and means nothing",
     SHAPES,
     '    ("exampleclient", "a client\'s name"),\n',
     ''),

    ("the list is built but only its first entry is scanned",
     "tests/test_the_product_carries_no_owners_name.py",
     "        rx = refused.in_exempt if rel in ALLOWED else refused.everywhere",
     "        rx = refused.in_exempt if rel in ALLOWED else "
     "identity.pattern(list(refused.entries[:1]))"),
]
