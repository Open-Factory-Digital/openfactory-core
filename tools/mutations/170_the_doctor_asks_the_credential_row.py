"""#170, proven by breaking it — the doctor asks the vendor's row whether a forge credential exists.

Presence was read in the doctor: a static token, or ONE vendor's App variables by name, for every
vendor. An Azure DevOps deployment minting from the machine's `az` login cloned, read its context
repository and opened pull requests, and the doctor said `no forge credential is configured`,
ended `NOT ready`, and sent the operator to create the static token that path exists to avoid.
The same reading passed an Azure project on a machine that also holds a GitHub App.

FOUR CLAIMS:

  1. **The row declares what the adapter brings.** Azure's row carries a `provider` that answers
     from the `az` login and answers None without one — and no `mint`, which would freeze an
     hour-long JWT into the tracker's client for a whole job.
  2. **The doctor asks the row, not one vendor's variables.** No static token → the project's
     row's provider decides; GitHub's App is that row answering, and a stranger's row is believed
     the same way.
  3. **A deployment holding a static token never spawns `az`** to learn what it already knows.
  4. **The remedy names both paths**, so the person who cannot create a PAT is told the login
     counts.

The guard is `tests/test_a_forge_that_brings_its_own_credential_is_not_reported_as_having_none.py`.
"""

TEST = "tests/test_a_forge_that_brings_its_own_credential_is_not_reported_as_having_none.py"

ROWS = "openfactory/adapters/credential/registry.py"
DOCTOR = "openfactory/doctor.py"

MUTATIONS = [
    # RE-PINNED 2026-09-28 (#373): the Azure row also declares `source`, the adapter's own
    # resolution, and the doctor's presence is `forge_credential_source` — the same cuts, made
    # where the lines now are.
    ("THE DEFECT ITSELF: the Azure row declares no provider, so the `az` path is invisible again",
     ROWS,
     '        env=SHIPPED_ENV["azure_devops"], provider=provider, source=source,\n',
     '        env=SHIPPED_ENV["azure_devops"], source=source,\n'),

    ("the Azure provider claims a credential with no `az` login behind it", ROWS,
     "        return az_token if az_token() else None\n",
     "        return az_token\n"),

    ("the Azure row declares a MINT, freezing a JWT into every tracker client", ROWS,
     '        env=SHIPPED_ENV["azure_devops"], provider=provider, source=source,\n',
     '        env=SHIPPED_ENV["azure_devops"], provider=provider, source=source,\n'
     '        mint=lambda: provider() and provider()(),\n'),

    ("the doctor stops asking the row: only a static token counts", DOCTOR,
     "        provided = bool(source)\n",
     "        provided = token is not None\n"),

    ("THE OLD READING BACK: one vendor's App variables decide for every vendor", DOCTOR,
     "        provided = bool(source)\n",
     "        from openfactory.credentials import app_id, app_installation_id, app_private_key\n"
     "        provided = token is not None or bool(app_id() and app_installation_id()\n"
     "                                             and app_private_key())\n"),

    # The ORDER is the vendor's resolution now (`azure_devops.credential_source`), which the
    # doctor asks: the login consulted before the stored secret is the same cut, made there.
    ("the row is asked even when a static token already answered, spawning `az` on a PAT",
     "openfactory/adapters/azure_devops.py",
     "    if (os.environ.get(name) or \"\").strip():\n        return f\"env:{name}\"",
     "    if az_token() is None and (os.environ.get(name) or \"\").strip():\n"
     "        return f\"env:{name}\""),

    # re-pinned 2026-09-19: the remedy is the Azure credential row's own `when_missing` now —
    # the doctor chose it by finding the kind inside its probe's sentence — and the same cut
    # is made where the words live. Re-pinned again 2026-09-28: the sentence names three sources.
    ("the remedy forgets the login and sends a tenant user to make a PAT they cannot", ROWS,
     '                      "the adapter mints its own token from it; on a machine where a person '
     'runs "\n'
     '                      "`az login`, that login — the adapter mints from it at each use; '
     'otherwise "\n',
     '                      "the adapter mints its own token from it; otherwise "\n'),
]
