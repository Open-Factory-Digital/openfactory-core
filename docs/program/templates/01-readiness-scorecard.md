# Readiness scorecard

Phase 1 of the [delivery method](../01-delivery-method.md). One per organisation, with one
repository table per repository in scope. Scores: 0 absent, 1 partial (work item named),
2 in place.

## The organisation

| item | finding | score |
|---|---|---|
| Tickets are born somewhere with an owner, and acceptance criteria exist or can be written | | |
| The path from merge to production is known and repeatable | | |
| Branch protection exists on the default branch, or may be set | | |
| A named **operator** and a backup | | |
| Named **requesters** who will write cards | | |
| Named **reviewers** who will read pull requests, with the time | | |
| A named **product owner** (Standard/Enterprise) | | |
| Named **release approvers** (if production is in scope) | | |
| The budget authority for agent spend is identified | | |
| The security team is identified (Enterprise) and its questionnaire is in hand | | |
| A GitHub App may be installed on the organisation, or a PAT is acceptable, or Azure DevOps / Jira credentials may be issued | | |
| Model providers approved (direct, Bedrock, Vertex, gateway) | | |
| Data residency and egress constraints known | | |
| A bot may create repositories, or the client's process will create the context repository | | |

## Per repository

Repeat for each repository in scope.

| | |
|---|---|
| repository | |
| stack(s) | |
| shape | monorepo with components / one of several repositories / single |

| item | finding (from `env read`, `env context`, the room) | score |
|---|---|---|
| `setup:` runs green on a clean clone | | |
| `validate.test` exists, runs green on a clean clone, and tests something | | |
| `security`, `lint`, `type` gates exist or the floor's inherited scan suffices | | |
| The test suite has no side effects on shared systems (or `--no-gates` is accepted for the rehearsal) | | |
| CI exists; disabled workflows identified; checks that run on every PR identified | | |
| The stock box image carries the toolchain, or a client image is needed | | |
| Documentation for `docs.constraints` / `architecture` / `guidelines` exists | | |
| The module map covers the stack (Python, TypeScript/JavaScript, C#) | | |
| High-risk areas identified for `risk: high` | | |
| Areas that change and that no test names (from the survey) | | |
| A single `base_branch` flow (a develop + main flow cannot be expressed) | | |

## Totals and reading

| | score | of |
|---|---|---|
| organisation | | 28 |
| repository *name* | | 22 |

- Organisation score below half: pause the engagement until the people rows are resolved.
- `validate.test` scored 0: this is the first prerequisite work item.
- Toolchain row scored 0: design a customer image in the design record, section 2.4.
