# 06 — The product role: switching it on for a real product owner

The engineering loop ships tickets. The product role decides WHAT becomes a ticket: requirements
written as reviewed documents in a **context repository**, a panel surface at **`/product/<name>`**
for the person who owns the product, and a human release gate before production. This page is the
whole enablement chain, in order — every command verified against the CLI.

## 1 · Three declarations that must agree

The role refuses to run half-configured, so three places name each other:

| where | what it declares |
|---|---|
| the registry entry | `product: {docs_repo: <org>/<name>-context}` — where requirements live |
| the context repo | `.openfactory/product.yaml` — `product: <name>` + `sources:` (EVERY repo implementing it) |
| each source repo | `docs_repo: <org>/<name>-context` in its `.openfactory/project.yaml` |

A mismatch is reported as a sentence naming both sides, not a stack trace. Two of the three are
written for you:

```bash
openfactory product init <name>                   # shows what it would write, and where
openfactory product init <name> --create-context  # no context repo yet? create one in the client's org
openfactory product init <name> --write           # open the PR on the context repository
```

**Both shapes, on either vendor.** A client's projects rarely all look the same — some already
keep a documentation repository, some have none at all — and the command answers to that
rather than to a flag:

| the project | what to run | what happens |
|---|---|---|
| **already has** a context repository | set `product.docs_repo` in its registry entry, then `product init <name> --write` | it is USED: cloned, read, and the declaration proposed as a pull request on it |
| **has none** | `product init <name> --create-context --write` | one is created in the client's own organisation, recorded in the registry, and the declaration proposed |

`--create-context` is the one operation that makes a repository in somebody's organisation, so
it is behind its own flag and says whether it CREATED or FOUND it. It is implemented for
**GitHub and Azure Repos**; a forge without the capability refuses by name and tells you to
create it by hand and set `product.docs_repo`. On Azure DevOps the repository is created in the
project the forge already drives, and a context repository that lives in a **different project
of the same organisation** is addressed by qualifying it — `product.docs_repo: SharedDocs/
product-context` — which the clone, the branch lookup and the pull request all follow.

`--write` opens the PR carrying `.openfactory/product.yaml`; the THIRD declaration — the
`docs_repo:` line in each source repo's own manifest — is **printed as a todo, not written**:
it lives in a repository you review, so committing it is deliberately yours.

## 2 · Who the product owner IS to the platform

**What the role can open while it answers:** the documentation repository, the source code,
the knowledge bundle when one has been published, and — since #33 — its own **facts pack**: the
board *whole* (every card and title, where the prompt's own board section is budgeted), what it
is waiting on a person for, and the register of every decision it asked somebody to take. The
pack's `README.md` names what could **not** be read, so a failed read is never reported as
"nothing there".

The panel identifies people by token. Two shapes, and the difference is the whole point:

```bash
# .env.compose (or the deployment's secret store)
OPENFACTORY_PRODUCT_TOKENS="tok-ana:ana:Ana Souza,tok-rui:rui:Rui Lima"   # per person: token:id:display
OPENFACTORY_PRODUCT_TOKEN="one-shared-token"                              # shared: READ-ONLY in practice
```

The shared token resolves to a subject with no id, and **every write path checks
`product.admins`** — so a shared-token holder can look and never act. For a PO who accepts,
drops, queues and releases:

1. issue a per-person entry in `OPENFACTORY_PRODUCT_TOKENS`, and
2. list that person's `id` in the registry entry's `product.admins`:

```yaml
# the registry entry (openfactory project add wrote the rest)
product:
  docs_repo: <org>/<name>-context
  admins: [ana, rui]          # the ids from OPENFACTORY_PRODUCT_TOKENS — these may accept/release
```

Then hand them the link — `http://<panel>/product/<name>` — which is the entire onboarding for
somebody holding a product credential. A legacy corpus of existing requirements is adopted with
`openfactory product baseline <name>` (it proposes, a human confirms; nothing is rewritten
silently).

## 3 · The release gate

Production is human-approved, always (D-12), and the chain has two halves — WHO may approve, and
HOW they prove it is them:

```yaml
# .openfactory/project.yaml — beside environments/promote
prod_approvers: [ana, rui]        # or the deployment-wide OPENFACTORY_PROD_APPROVERS env
```

```bash
openfactory approver add ana      # sets the password, stored hashed in ~/.openfactory/approvers.json
# deployments that cannot mount a home dir: OPENFACTORY_APPROVERS='{"ana": "<scrypt-hash>"}'
# or OPENFACTORY_APPROVERS_FILE=/path/to/approvers.json
```

The panel's release form asks login + password; the approval is recorded on the ticket with the
approver's name and the version tag. With a declared promotion chain (`promote: [dev, qa, prod]`
— see [04](configuration.md)), the gate sits before the LAST stage, whatever you named it.

## 4 · The fifteen-minute checklist

```bash
openfactory product init <name> --create-context --write   # context repo + three-way declaration
# put OPENFACTORY_PRODUCT_TOKENS in .env.compose; add the ids to product.admins in the registry
# restart the stack with --env-file so the tokens reach the panel
openfactory approver add <login>                           # the release password
open http://localhost:8787/product/<name>                  # hand this link to the PO
```

If any of it is missing the surface says so by name — a PO who sees "every write refuses" was
given the shared token; go back to §2.
