# Security policy

## Reporting a vulnerability

Please report suspected vulnerabilities privately via GitHub's **Report a vulnerability**
(Security → Advisories) on this repository:
https://github.com/Open-Factory-Digital/openfactory-core/security/advisories/new
You will get an acknowledgement within 72 hours. Please do not open public issues for security
reports.

## What counts as security-sensitive here

OpenFactory runs coding agents against real repositories with real credentials, so the
interesting surface is well-defined:

- **Credential reach.** How a workload's environment is built depends on which box the
  deployment runs jobs in, and the two boxes make different promises.

  The **container** box — the default, and what `docker-compose.yml` sets — builds that
  environment by *allow list*: the harness's own model auth
  (<!-- box-allow-list -->`CLAUDE_CODE_OAUTH_TOKEN`, `ANTHROPIC_API_KEY`<!-- /box-allow-list -->)
  plus the variable names the project declares in `box.env`. Nothing else crosses, including
  names nobody here has heard of.

  The **worktree** box (`_scrubbed_env`) works the other way round: it starts from the worker's
  whole environment and *removes* the names its deny lists carry — ambient cloud credentials, the
  agent-token pool, and the forge push credential under every spelling `credentials.py` serves
  it. This is not only the local-development path: every judging role runs in a worktree on
  every deployment (the sizer, the tech-lead's chat and its diagnosis, the product module).

  A deny list gives exactly one guarantee, and we state it in the one direction it holds: **a
  name the list carries is removed from the workload's environment; a name it does not carry is
  not.** It is not a claim that no credential reaches the agent, and it could not become one — a
  project may name any variable as its own credential (`token_env: ACME_ADO_PAT`), and a name
  nobody can enumerate is a name no deny list can hold. The container box is the answer to that
  problem, because it enumerates from the other end.

  So this paragraph cannot drift from the code again, here is the measurement. Of every
  credential-shaped variable this core reads, these
  <!-- reach-count -->13<!-- /reach-count --> are the ones a worktree workload can read today:

  <!-- reaches-the-agent -->

  | variable | what it is |
  |---|---|
  | `ANTHROPIC_API_KEY`, `ANTHROPIC_AUTH_TOKEN`, `CLAUDE_CODE_OAUTH_TOKEN`, `OPENAI_API_KEY`, `AZURE_API_KEY` | the harness's own model credential. The agent has to reach a model; the deliberate line is that the *failover pool* does not travel with it — only the one active token does. |
  | `AZURE_DEVOPS_PAT`, `JIRA_API_TOKEN` | the shipped default credential for the two non-GitHub vendors. On an Azure DevOps deployment that PAT is the forge credential as well as the tracker's (`docs/setup/azure-devops.md` issues one PAT for both), so there a worktree workload can reach the repository with it — run those jobs in the container box. |
  | `OPENFACTORY_PANEL_TOKEN`, `OPENFACTORY_PANEL_TOKENS`, `OPENFACTORY_PRODUCT_TOKEN`, `OPENFACTORY_PRODUCT_TOKENS` | the panel's *inbound* sign-in tokens. They authenticate a person to this platform; holding one is being that person to the panel. |
  | `TEMPORAL_API_KEY`, `TEMPORAL_TLS_KEY` | the orchestrator connection's API key, and the path to its client key. |

  <!-- /reaches-the-agent -->

  That table is the **core's**. An installed add-on package brings its own vendor credentials,
  and they reach a worktree workload in exactly the same way — read that package's own policy
  alongside this one.

  Anything that lets workload code reach a credential outside that set is a vulnerability — a
  spelling a deny list misses, a credential in a log line or a diff, a name crossing the
  container box without `box.env` naming it. So is that set growing while this table does not:
  the table is derived and compared against the code by
  `tests/test_the_environment_carries_the_products_name.py`, which fails when the two disagree.
- **The pipeline's control of version control.** The agent must not be able to push, open PRs,
  or merge on its own — those are the framework's acts, under policy. A path that lets generated
  code do them directly is a vulnerability.
- **Gate suppression.** A change that silences a quality gate (`noqa`, `pragma: no cover`,
  `nosec`) must disarm auto-merge and route to a human. A way around that routing is a
  vulnerability.
- **The human gates.** Production release requires a named approver with a password (scrypt,
  salted). Anything that bypasses approver verification is a vulnerability.

## Supported versions

Pre-1.0: only the `main` branch receives fixes.
