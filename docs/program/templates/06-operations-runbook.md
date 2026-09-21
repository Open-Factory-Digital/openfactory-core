# Operations runbook

*Phases 3.7–4 of the [delivery method](../01-delivery-method.md). Completed from the design
record with everything the pilot taught; owned by the operator from go-live; re-read quarterly.
Everything a person on call needs, and nothing that lives elsewhere: link to the design record,
do not copy it.*

| | |
|---|---|
| deployment | |
| design record | (link) |
| operator, backup, escalation (partner desk, tier) | |
| platform version | |
| last revision | |

## Where everything is

| thing | where | command |
|---|---|---|
| the panel | | |
| the engine's UI | | |
| the stack's logs | | `docker compose --env-file .env.compose logs -f worker` |
| the journals | `OPENFACTORY_LOG_DIR` | `/logs`, `/logs/<project>`, `/logs/<project>/<ticket>` |
| the registry | | `openfactory project list` |
| the environment file | `.env.compose` (0600) | |
| the state store (board db, metrics db, proofs, resume) | `OPENFACTORY_STATE_DIR` | |
| the approvers | | `openfactory approver list` |
| the work directory | `OPENFACTORY_WORK_DIR` | |
| the backups | | |

The worker prefix, for every command below: `docker compose --env-file .env.compose exec worker openfactory …`

## The cadences

| when | do | evidence |
|---|---|---|
| continuously | the attention bar: Needs Action, waiting merges, the production gate | — |
| daily | the Logs page for yesterday; answer every parked card on the card and move it back to TO-DO; token-pool state on the panel | the log |
| weekly | the cost dashboard against the budget; `doctor` per project; `box status` per repository; recurring failures the tech lead reported; the API budget line | the log |
| monthly | release notes read; upgrade decided; credentials nearing expiry; `docker system df` | the calendar |
| quarterly | merge-policy review; manifest review with the developers; this runbook re-read | a revision |

## When something is wrong

| you see | it means | do |
|---|---|---|
| a card in Needs Action | the card's latest comment says why | act on the comment; Resume or Skip from the panel |
| "pre-flight sizing did not run" | the sizer degraded (usually the worker's harness token) | check `OPENFACTORY_PREFLIGHT: DEGRADED` in the worker log; fix the token; the ticket already ran unsized |
| a ticket split into children, parent closed | the sizer judged it too large | nothing; the children run in order |
| ON_HOLD, effort budget exhausted | the ticket out-ran its budget after recovery | split the remainder, or raise `effort_budget_turns` and Resume; the work is on the branch |
| ⏸ paused (usage limit) | the whole token pool is exhausted | wait for the backoff; check the pool; the session resumes on its own |
| `doctor` red | the line names the remedy | apply it; re-run |
| `box status` says the proof expired | commands, toolchain or image moved | `box prove` |
| the panel is empty after a restart | the engine's retention or a volume | the Logs page still has the journals; check `OPENFACTORY_ENGINE_RETENTION_DAYS` and the volumes |
| a merge landed that should not have | check the pull-request body's conditions | revert through a card; file with the desk as Sev1 |
| nothing happens at all | the worker is not polling, the board column is mis-named, or the box is unproven | `floor`, `doctor`, `poller status` |

Severity definitions and response times: the [standard](../06-support-and-maintenance-standard.md).
How to reach the desk: ____

## Upgrade

1. read the release notes; note behaviour changes;
2. (Enterprise) stage on the non-production deployment;
3. back up (below);
4. re-run the installer with `--force`, or `git pull && docker compose --env-file .env.compose up -d --build`; move `OPENFACTORY_VERSION` deliberately;
5. `doctor` per project; `box status` per repository; `env rehearse` on one project;
6. record in the calendar.

Never during a job that holds the floor. Never two minors in one step.

## Backup and restore

| what | how | where | cadence |
|---|---|---|---|
| the registry, the state store, the approvers, the environment file | | | daily, and before every upgrade |
| the journals volume | | | |
| the engine database volume | | | |

Restore test: onto a clean machine, then `doctor` green on every project. Last performed: ____

## Credentials and rotation

| credential | rotate by | last rotated | next |
|---|---|---|---|
| | | | |

After any change: recreate the stack with `--env-file .env.compose`; editing the file alone changes nothing.

## Contacts

| role | name | how |
|---|---|---|
| operator | | |
| backup | | |
| partner desk | | |
| product owner | | |
| release approvers | | |
| security | | |
