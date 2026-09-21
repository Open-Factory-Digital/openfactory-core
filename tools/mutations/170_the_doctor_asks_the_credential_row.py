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
    ("THE DEFECT ITSELF: the Azure row declares no provider, so the `az` path is invisible again",
     ROWS,
     '        env=SHIPPED_ENV["azure_devops"], provider=provider,\n',
     '        env=SHIPPED_ENV["azure_devops"],\n'),

    ("the Azure provider claims a credential with no `az` login behind it", ROWS,
     "        return az_token if az_token() else None\n",
     "        return az_token\n"),

    ("the Azure row declares a MINT, freezing a JWT into every tracker client", ROWS,
     '        env=SHIPPED_ENV["azure_devops"], provider=provider,\n',
     '        env=SHIPPED_ENV["azure_devops"], provider=provider,\n'
     '        mint=lambda: provider() and provider()(),\n'),

    ("the doctor stops asking the row: only a static token counts", DOCTOR,
     "        provided = token is not None or deployment_forge_provider(project) is not None\n",
     "        provided = token is not None\n"),

    ("THE OLD READING BACK: one vendor's App variables decide for every vendor", DOCTOR,
     "        provided = token is not None or deployment_forge_provider(project) is not None\n",
     "        from openfactory.credentials import app_id, app_installation_id, app_private_key\n"
     "        provided = token is not None or bool(app_id() and app_installation_id()\n"
     "                                             and app_private_key())\n"),

    ("the row is asked even when a static token already answered, spawning `az` on a PAT",
     DOCTOR,
     "        provided = token is not None or deployment_forge_provider(project) is not None\n",
     "        provided = deployment_forge_provider(project) is not None or token is not None\n"),

    # re-pinned 2026-09-19: the remedy is the Azure credential row's own `when_missing` now —
    # the doctor chose it by finding the kind inside its probe's sentence — and the same cut
    # is made where the words live.
    ("the remedy forgets the login and sends a tenant user to make a PAT they cannot", ROWS,
     '        when_missing=("run `az login` on the machine the worker runs on — the adapter '
     'mints its "\n'
     '                      "own token from that login at each use — or set AZURE_DEVOPS_PAT '
     '(or the "\n',
     '        when_missing=("set AZURE_DEVOPS_PAT (or the "\n'),
]
