# What works today

Read this before deciding anything. It is ordered by what would stop you, not by what is
impressive.

Status as of **2026-08-26**, cut from `cb3013d` of `openfactory`, the source tree this page was
written in — its gate ran 8,465 tests green in both orders there. This tree holds fewer:
the tests that leave with the add-on packages are not in it.

> **Where the numbers on this page come from.** Every git ref named here says whose history it
> belongs to, because the public repository is cut from a different one and a bare sha there is a
> reference nobody can resolve. The count above is the ONE place a count of this repository is
> written down; **no guard measures it against the tree** — it is typed from the run that produced
> the line, so it is as fresh as the last person who ran the suite before editing.
> `tests/test_the_docs_do_not_drift.py` holds the *sole-home* rule instead: any other document
> that wants a number links here rather than typing one, so a stale count can only ever be stale
> in one place.

---

## Verified end to end

Things somebody has actually watched work, not things that have tests.

**A ticket, from a board column to an open pull request.** On the cloud deployment — standing
since 2026-07-15 — this is routine against a real client product; 19 tickets are measured in the
`v1.1.0` tag of `openfactory`. On a fresh installation it was done on
2026-08-02: a new GitHub org, a new App, a new board, a new project — ticket to PR in **4m31s** for
**$0.65**, with an independent reviewer that ran a 200,000-case randomized sweep against the
implementation's stated invariant before signing off.

**The local stack.** `docker compose up` brings up Temporal, a worker, the panel and the box image,
on one machine, with no cloud anything. First executed end to end on 2026-08-02.

On **2026-08-26** it was measured on the PUBLIC shape as well — the tracked tree with the paths
excluded below actually removed — because it did not work there: both images did `COPY addons
./addons`, and the export died at `"/addons": not found` on the first command README gives a
stranger. `docker compose --env-file .env.compose build sandbox-image worker` now exits 0 in both
trees, the private images carrying `openfactory-aws` and `openfactory-slack` and the public one
carrying the core alone. The four `make` targets that drive the cloud deployment refuse by name
there instead of failing halfway. What keeps it that way is a guard that judges the public shape
from the PRIVATE tree — `tests/test_the_public_cut_is_written_down.py`'s last section — because
every guard that only runs where `addons/` is absent is blind in the one tree where the cut can
be wrong.

**The harness toolbox inside a foreign image.** All three agent CLIs run from a read-only mount
inside `mcr.microsoft.com/dotnet/sdk:9.0` — an image with no Node and no knowledge of this
platform. This is the mechanism that lets a client bring their own image.

**Cloud independence, for the runner and now for the panel.** With `boto3`, `botocore` and
`temporalio` blocked at `sys.meta_path`, and a full production `.env` loaded, the whole `JobRunner`
assembles with zero attempted cloud imports; the compose worker holds no AWS credential and has
exactly one established connection, its own Temporal container.

The panel was NOT clean until 2026-08-02: an audit found it calling SSM on every project view and
building a CloudWatch tail on every event stream. Both are fixed, and the guard is now the property
over every endpoint rather than a check naming one reader — which is precisely why the second one
had survived the first fix.

**Telemetry, written AND read locally.** `OPENFACTORY_METRICS_SINK=sqlite` fills a file and both readers
now ask the same sink, so the cost dashboard, the tech-lead's memory of what it has already said,
recurring-failure detection and the open-loop ledger work with no DynamoDB. Until 2026-08-02 only
the write half was wired: `SqliteMetricsSink.scan()` existed, was tested, and was called by
nothing, so every reader answered "nothing recorded" over a file that was filling up.

**`openfactory doctor`.** Nine checks always, plus the agent credential, the declared CI checks, the
box proof and the API budget where those apply — each with its own remedy line. It is the first thing to run and the
fastest way to find out which of the below applies to you.

---

## The provider axes, honestly

[ADR-0022](adr/0022-provider-seams.md)'s rule — *an axis is agnostic when it is born with
two* — is the bar for this table. Where an axis still has one implementation it says so.

| axis | implementations | notes |
|---|---|---|
| tracker | GitHub, **Jira**, **Azure DevOps** | the Jira one is why refs are opaque strings rather than integers |
| forge | GitHub, **Azure Repos** | branches, PRs, merges, tags on both |
| board | GitHub Projects v2, **Azure Boards** | plus Jira, where the workflow status IS the board |
| CI / environment | GitHub Actions, **Azure Pipelines** | read-only observation on both |
| agent | Claude Code, Codex, Kimi, **OpenCode** | four, selectable per role AND per model (`model:`); OpenCode proven end to end against Amazon Bedrock |
| sandbox | worktree, container, `fargate` (add-on) | worktree and container are local; `fargate` is described by the core (its traits are a row) and RUN by the `openfactory-aws` add-on through the `box_runner.fargate` entry point — absent the add-on, the kind is refused by name |
| channel | panel, Slack (add-on) | the panel is the reference surface (ADR-0038); the Slack connector leaves the public tree as `openfactory-slack` — a channel is an add-on, never a prerequisite |
| telemetry | SQLite, DynamoDB, null | SQLite is the local default |
| events | file journal, stdout, in-memory | file journal is the local default |

**Azure DevOps has run against a live organisation** (fx-ado, 2026-08-06): work items read and
moved, pull requests opened in Azure Repos, pipelines observed — and its port surfaced eight
defects that were already latent on the GitHub/Jira paths, which is what a second vendor is
for. The end-to-end setup path is [docs/setup/azure-devops.md](setup/azure-devops.md).

---

## Known broken or incomplete

Each has an issue. None is a surprise waiting to happen — they are written down because they were
found by running the thing.

**First-time setup runs in the box, per repository — closed 2026-08-13.** Raised by the pilot
operator as a design flaw, not a bug: the setup artefacts were *proposed* but never *measured*
("porque não é criado um BOX onde todo o setup ocorra?"), and the journey read single-repo
while the next client is multi-repo on Azure DevOps. Closed with `openfactory onboard`: per
repository it reads the manifest from the code, **proves it in the real box before proposing
it**, generates the module map, and opens one pull request carrying artefacts + proof verdict +
the questions only the team can answer; the context repository is created-or-used and the
backfill proposed the same way, saying which mode it ran (agent-checked or deterministic, with
the why). Underneath it, the box proof and its pickup gate became per-`(project, repository)` —
before this, a proof of the default repo admitted cards on repositories whose box had never
run. A card on an unproven repo is now held by name while proven repos' cards flow.
`knowledge build` also stopped walking `Path(clone_url)` — third sighting of that bug — and
grew `--publish` for factory-cloned projects.

**The first live `onboard` run then found what only a run finds (same day).** The proof died on
`uv sync` — read from the client's own CI by our own proposer, inside our own image, which never
carried uv: the stock image now holds the rule *if the proposer can name it, the box can run it*
(uv/pnpm/yarn added; dotnet & co. deliberately beyond the floor), and a missing binary's finding
now names the two stack-agnostic remedies (`box.image`, or fix the command in the PR) instead of
leaking the shell's `not found` — the operator's constraint verbatim: "there is no way for us to know what
será a stack de cada um". And the context half met GitHub refusing `createRepository` to every
App installation token: an organisation owner now falls back to REST (Administration write — the
permission table row was wrong and is fixed), a personal account borrows the classic PAT the
board already requires, and the new `openfactory product declare <name> <owner/repo>` closes the
flow gap where declaring a PRE-EXISTING context repository had no command at all.

**Onboarding no longer needs a checkout anywhere — closed 2026-08-12.** The factory's own work
was always server-side (it clones, runs the box, pushes, opens the pull request); the one
exception was AUTHORING `.openfactory/project.yaml`, which wrote a file into a checkout and so
refused a project registered by clone URL. Raised by the pilot operator — *"como isso poderia
ter a opção de rodar 100% na nuvem se existe uma dependência do meu laptop?"* — and closed with
`openfactory env apply <project> --yes --pr`: the worker clones, proposes the manifest and opens
a pull request for a human to correct and merge. The review the file exists for is kept (it is
a diff either way); the machine holding the checkout is not. `env read`/`env apply` against a
local path still work exactly as before, and remain the better session when the developers who
know the repository are in the room.

**The container box obtains the client's repository — #65 closed.** A project registered by clone URL is fetched into the worker's repo cache; private repositories ride the forge credential. The residual: a LOCAL PATH registration still requires the repository on the worker's own disk, which in compose means a mounted checkout.

**The panel cannot see local jobs — #67.**
Event journals are written beside the client's repository; the panel reads a mounted volume at a
different path. The volume is empty and always would be. In the cloud the panel gets events through
CloudWatch instead, which is why this was invisible until the local stack ran.

**A parked job's reason can be lost — #66.**
~~`str(ActivityError)` is the fixed string `Activity task failed`~~ — **fixed.** The park note now
carries the first message in the exception chain that is not a wrapper's placeholder
(`openfactory/util/causes.py`), and a box-image refusal no longer burns the activity's retry budget on a
declaration that will never change.

**One deployment serves one GitHub organisation — #64.**
The channel credential is per-project; the forge credential is process-global, because a GitHub App
*installation* belongs to one org. One deployment serves one organisation, and that is now **enforced
rather than assumed**: `openfactory project add` refuses a project in a second organisation, naming both
orgs and the projects in each, and a hand-edited registry that spans two logs
`OPENFACTORY_REGISTRY_SPANS_INSTALLATIONS` on every load.

The load path WARNS rather than refusing, deliberately: that file is gitignored and baked into the
worker image, so raising there would turn one stale line in an unreviewable file into a total outage
for every project — including the healthy ones. A second organisation needs a second deployment.

**`box.image` is honoured only by the container box.** A Fargate deployment runs the whole job
inside a task whose image is baked into the task definition. Declaring `box.image` there now
**raises** rather than being ignored — deliberately, so it cannot become a setting that looks
configured and is not. The cloud path honouring a client image is phase 2 of
[ADR-0037](adr/0037-the-box.md).

**`openfactory box prove` exists and gates pickup — on the `container` box only.** It resolves the image
digest, checks the image contract, checks the toolbox can execute in that image (the glibc/musl
trap), runs the client's own `setup:` and `validate:` on untouched main, and probes the harness's
own auth route. It costs zero harness tokens. But `gate_reason` returns None for `fargate` and
`worktree` — and both live deployments are fargate, so on them the gate is a no-op and the proof
is something an operator runs by hand.

**The quality floor REFUSES on the job path, and there is no switch.** It used to do neither: the
floor was checked only by `openfactory conformance`, a command nothing on the job path calls, and
`all([])` being `True` meant a project with no `validate:` block passed every gate vacuously and
was eligible for auto-merge. Then it announced but did not refuse, behind `OPENFACTORY_ENFORCE_FLOOR` —
off by default, because no project this platform drove declared a `security` gate, including the
live client's, and a floor that arrives as an outage is a floor an operator disables.

Both halves are closed. `org_defaults/floor.yaml` gives every project an inherited `security`
gate — advisory, needing only a POSIX shell and `git` — so the only way to violate the floor is to
declare no `test` command, which is exactly the project that must not buy an agent pass. And the
variable was **removed** rather than defaulted on: a switch that can turn the floor off is the
floor being negotiable, and `policy/floor.py` calls it non-negotiable. An unmet floor now holds the
ticket for a human before any agent runs, on every deployment, with the remedy on the card.

The escape hatch is `advisory: true` on a gate, never an absent gate.

**Jira has run against a live Jira instance** (project DAR, 2026-08-05): a ticket crossed from the
board to a merged PR with the deploy watched. Five defects surfaced on that first real contact —
among them the space-containing label Jira rejects, and `scan_projects` filtering on GitHub
Projects coordinates so a Jira project was never scanned at all. All fixed. What that run did NOT
prove is whether the POLLER picked the ticket up or the starter was invoked by hand; nothing in
the repository records which.

**The `setup:` and `validate:` commands are shell strings and only the exit code is read.** That is
what makes any stack work at the calling surface, and it is also the whole extent of the
integration: there is no stack-specific intelligence beyond the presets' command tables.

---

## Deliberately not built

Not gaps — decisions, each with an ADR.

- **Production deploys are never triggered from chat.** The prod gate is the panel with a password
  ([ADR-0016](adr/0016-slack-actions-authorization.md)).
- **The bot never gets `workflows` permission.** CI/CD stays human-only; a push touching
  `.github/workflows/**` is rejected by design, and the fix for a client who needs it is policy
  routing, not permission.
- **Review is advisory by default.** It comments, it does not block ([ADR-0014](adr/0014-single-agent-execution-and-advisory-review.md)).
  A rejection with concrete findings triggers a repair pass; a vague rejection escalates to a human.
- **One job at a time — deployment-wide.** The floor frees at merge, not at agent-done, so the
  next ticket builds on a base that contains the last one
  ([ADR-0007](adr/0007-floor-frees-at-merge.md)). It is dependency safety by construction and
  it costs throughput. Precisely: the slot count is `OPENFACTORY_MAX_CONCURRENT_JOBS` (default
  1) counted across ALL projects; raising it adds parallelism with no per-project cap.
- **Cross-repository ordering does not exist.** Two repositories are two floors; nothing stops the
  front-end ticket merging before the API it depends on. Designed in
  [ADR-0036](adr/0036-cross-repo-ordering.md), not built.

---

## What the public repository contains

The public repository — `openfactory-core` — receives this tracked tree by `git archive`, minus
the paths below and the tests that exist only for them (the owner's decision, 2026-08-24/26).
Azure DevOps and Jira stay in the core beside GitHub: *not a lock-in, an option*. A vendor that
leaves is installed from outside through the `openfactory.adapters` entry-point group
([core/07-extensibility.md](core/07-extensibility.md) §2 and §10), and this table is the one
place the excluded paths are written down — `tests/test_the_public_cut_is_written_down.py`
holds it to the tree and to §10's ledger.

| excluded from the public tree | where it lives instead |
|---|---|
| `addons/` | the add-on packages themselves — each is built from this tree into its own wheel and installed beside the core; private, and the documents of the deployment a package carries live under its own `docs/` |
| `infra/` | `openfactory-aws` — the reference deployment on one cloud (its walkthrough and runtime document are that package's `docs/DEPLOYMENT.md` and `docs/runtime-architecture.md`) |
| `openfactory/runtime/fargate/` | `openfactory-aws` — the cloud box (`box_runner.fargate`) and the token pool (`token_pool.ssm`) |
| `openfactory/observability/dynamo.py` | `openfactory-aws` — the managed metrics table (`metrics.dynamodb`) |
| `openfactory/adapters/agent/s3_session_store.py` | `openfactory-aws` — the remote session store (`session_store.s3`) |
| `openfactory/runtime/slack/` | `openfactory-slack` — the chat channel's runtime |
| `openfactory/adapters/channel/slack.py` | `openfactory-slack` — the channel adapter |
| `openfactory/adapters/notify/slack.py` | `openfactory-slack` — the channel's push half |
| `openfactory/adapters/notify/telegram.py` | `openfactory-slack` — the deployment-wide fallback notifier (`notifier.telegram`), reached when `OPENFACTORY_NOTIFIER_FALLBACK=telegram` declares it |
| `docs/core/01-reality-check.md` | a dated audit of this tree; `docs/STATUS.md` answers the same question and a guard keeps it current |
| `docs/core/03-extraction-strategy.md` | the plan for making this cut; the four anti-patterns it wrote down are in `CONTRIBUTING.md` |
| `docs/core/04-business-and-licensing.md` | `NOTICE` carries the licence-and-mark rule a user needs, and `docs/core/07-extensibility.md` §2 the rule that the open build is never hobbled |
| `docs/core/05-open-questions.md` | the answers are in `LICENSE`, `NOTICE`, `CONTRIBUTING.md` and `docs/STATUS.md` |
| `docs/core/06-onboarding-and-project-shape.md` | `docs/ONBOARDING.md` §10 carries the project shape in the present tense, and `docs/architecture.md` §5 the egress a security review asks for |
| `docs/site-guide.md` | website copy source; `README.md` and this page are the public claims |

**Six of those rows are documents, and the criterion is the owner's** (2026-08-26): every document
that ships must serve someone who will use or contribute to the core. A dated audit of this tree,
the plan for making this cut, a commercial-line record, a page of questions that are all now
answered, a gap analysis with a backlog, and a website copy source serve the people who wrote
them, so they stay here and travel no further. What each of them owed
a reader was moved first, into the page named beside it — `docs/core/` in the public tree is
`README.md` and the three design documents it indexes, and `docs/core/README.md` ships with them.
The reference deployment's incident page moved rather than being excluded: it is
`addons/openfactory-aws/docs/runbook.md` now, beside that package's
`addons/openfactory-aws/docs/DEPLOYMENT.md` and
`addons/openfactory-aws/docs/runtime-architecture.md`, and the `addons/` row above already
carries all three.

Two facts a reader of that table needs. Both sides are a **directory delete** (the chat side
since 2026-08-26): every row registers through the entry-point group from its package —
`addons/openfactory-aws` and `addons/openfactory-slack`, tracked here and excluded from the
export by the `addons/` row above, with the paths they carry — and the core's own `pyproject.toml`
declares no row. The presence of that one directory is how a guard tells which tree it measures
(`tests/add_ons.py::public_tree_signal`), and the row is what keeps the signal honest.
`tests/test_the_cloud_is_a_directory_delete.py` and `tests/test_the_chat_is_a_directory_delete.py`
prove the core imports, every registry answers, and a project declaring `channel: slack` (or
carrying a `channel_id`) on a deployment without the package is refused by name, naming
`openfactory-slack` as the package that carries the row and the `channel.slack` entry point as
what any package must declare to answer for it — never a `pip install <name>`, because these
packages are on no index (`openfactory/plugins.py::install_hint`);
`adapters/channel/registry.py` and `adapters/notify/registry.py`
hold the panel and nothing else, and the deployment-wide fallback notifier is declared
(`OPENFACTORY_NOTIFIER_FALLBACK`) rather than inferred from a vendor's variables.
`tests/test_the_add_on_packages_install.py` installs the public tree and the two packages into a
scratch environment and shows the rows resolving.

**Behaviour change (2026-08-26).** The deployment-wide fallback notifier is no longer inferred
from a vendor's variables: setting `OPENFACTORY_TELEGRAM_BOT_TOKEN` and
`OPENFACTORY_TELEGRAM_CHAT_ID` alone now switches nothing on — the two are read by the
`notifier.telegram` row only, and that row is reached only when
`OPENFACTORY_NOTIFIER_FALLBACK=telegram` declares it (with `openfactory-slack` installed). A
deployment that set the old switch must add that declaration, or its project-less
notifications go nowhere. `openfactory doctor` prints the fallback state as one line and, when
a notifier is installed and not declared, names the line to add.
