# Readiness assessment report

*Phase 1 of the [delivery method](../01-delivery-method.md). The document a sponsor decides on
and an architect designs from. Attach the scorecard and the raw `env read` / `env context`
outputs.*

| | |
|---|---|
| organisation | |
| repositories assessed | |
| assessed by (name, credential number) | |
| dates | |
| version of the platform used for the assessment | |

## 1. Summary for the sponsor

Five sentences at most: whether the factory can work on this codebase, what it would cost per
merged ticket (a range, with what the range depends on), what has to change first, the
recommended profile, and the recommended pilot.

## 2. Findings

### 2.1 The organisation
From the scorecard: the people named against each role; the flow of work; the constraints.

### 2.2 Each repository
One subsection per repository: the real `setup:` and `validate:` commands and whether they ran
green on a clean clone; the stack and the image question; CI and required checks; the shape;
side effects; documentation; the module map's coverage; high-risk areas; the areas that change
and that no test names.

### 2.3 Tooling and security
Forge and tracker access path; where the factory runs; egress; identity; secrets. On Enterprise,
the security checklist's status.

## 3. Recommended profile and shape

Light / Standard / Enterprise ([profiles](../02-profiles.md)); the door; the provider axes; the
box; what is out of scope for the pilot.

## 4. What the client must do first

| work item | owner | needed before |
|---|---|---|
| | | |

## 5. Risks

| risk | likelihood | impact | mitigation | owner |
|---|---|---|---|---|
| | | | | |

## 6. The costed estimate

| line | estimate | basis |
|---|---|---|
| agent spend per merged ticket | | the rehearsal's cost on a synthetic ticket; the published reference is one codebase, n = 8 |
| infrastructure per month | | |
| people: operator hours per week; reviewer time per pull request | | |
| partner: implementation (fixed); support (per tier) | | |

## 7. The proposed pilot

| | |
|---|---|
| projects and repositories | |
| number of tickets, duration | |
| merge policy | human |
| success numbers (from [method §3.6](../01-delivery-method.md#36-the-pilot)) and targets | |
| who chooses the tickets | |
| budget cap | |

## 8. Decision

- [ ] the sponsor accepts the report and funds design and implementation
- [ ] the engagement pauses until the work items in §4 are done; next conversation on: ____

Signed: sponsor ________ date ____ · architect ________ date ____
