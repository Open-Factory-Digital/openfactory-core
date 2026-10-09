"""`openfactory certify` — evidence that a deployment is built the way the guidelines say (#356).

Implementation partners are certified from evidence gathered on a LIVE deployment, not from an
exam: a command runs on the deployment, reads what the platform already knows about itself,
replaces every identifying name with a pseudonym, and writes a pack a bot can validate. This
package is that command's machinery, in five pieces that each answer one question:

    controls.py   what is checked, which profile requires it, and the answer each control gives
                  from what the deployment says about itself — never from a guess
    redact.py     what must never leave the deployment, and the pseudonyms that stand for it
    schema.py     the published shape of `pack.json` (`pack.schema.json` beside it), and a small
                  validator the standard library can run, so a pack is checked before it is written
    pack.py       reading the deployment, assembling the files, and the tarball
    verify.py     checking a pack offline — its schema, its checksums, its signature and every
                  threshold in `thresholds.yaml` — the way the submissions bot does

THE OUTCOME AGGREGATES are not this package's: `observability/query.outcomes` reads them from the
job journals and the metrics store, and the pack carries its block as it comes — each measure a
count or a median, or null with the reason it could not be read, never a zero.

THE FORGE IS ASKED THREE READ-ONLY QUESTIONS (slice 3), through optional capabilities of each
project's forge row (`adapters/forge/base.py`): what protects the branch the platform merges into
(C-BRANCH), what the credential a job holds is granted (C-WORKFLOWS), and which releases of the
platform are published (C-VERSION). A row that cannot answer, a credential without the scope to
ask and a machine with no network all answer `None`, which those controls read as `unknown`,
never `pass`.

WHAT IS NOT DONE YET, said here and in every pack it writes rather than discovered by a reader: it
does not sign the pack (minisign is a follow-up). A pack that claimed it would be a certificate for
something nobody looked at.

NOTHING HERE READS A CUSTOMER REPOSITORY'S CONTENTS beyond the manifests the platform already
reads to run a job: no ticket text, no pull request bodies, no commit messages, no diffs.
"""
