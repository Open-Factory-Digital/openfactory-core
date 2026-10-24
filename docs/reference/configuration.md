# Configuration

Three places, and **which one a thing lives in is a decision, not an accident**:

| | who owns it | why |
|---|---|---|
| **the manifest** — `.openfactory/project.yaml`, in your repository | the client's team | it describes the *work*: how to install, how to validate, what the components are |
| **the registry** — `registry.yaml`, on the deployment | the operator | it describes the *installation*: credentials, which board, which harness, which box |
| **the environment** — `.env`, SSM, Secrets Manager | the operator | secrets, and only secrets — or where a store reads them from ([the credential store](#the-credential-store)) |

The boundary between the first two is a **security boundary**. The manifest lives in the repository
the agent edits, so anything an agent could rewrite to its own advantage belongs in the registry.
`box.image` is the sharpest case: an agent able to set it would be choosing its own root filesystem,
turning *"the agent wrote the wrong code"* into *"the agent picked the machine"*.

---

## The manifest

38 fields, **all optional** — an empty file loads. The ones that matter:

```yaml
version: 1
base_branch: main
merge_policy: human          # human | auto

setup:
  - "pip install -e '.[dev]'"

validate:                    # the REAL quality floor: the platform runs these
  test: "pytest -q"          # and reads the exit codes. It does not trust the
  security: "bandit -r . -ll -q"   # agent to have run them.
  lint: "ruff check ."
  type: "mypy ."

docs:
  constraints: docs/adr/**   # the constitution — inlined newest first, the rest named by path

components: {}               # only if polyglot or with risk zones
  # backend: { path: app/, stack: python, risk: normal }
  # infra:   { path: terraform/, stack: terraform, risk: high }
```

**`merge_policy: human`** is the recommended first setting: the bot opens the PR, a person merges.
`auto` merges when gates are green, review did not reject, and no high-risk component was touched.

**A `risk: high` component stays human-gated even on `auto`.**

**`validate` is the whole integration.** Commands are shell strings and only the exit code is read.
That is what makes any stack work at the calling surface — and it is also the entire extent of the
stack knowledge, so a language the presets do not know still works, it just brings its own commands.

The floor (`openfactory conformance`) requires `test` and `security`. Note that it is a command somebody
runs, not a gate on the job path — see [05](../STATUS.md).

**A field name typo is fatal here** (`extra="forbid"`), deliberately: the manifest is in your
repository, in your diff, in your review. The one trap is that `validation:` is silently accepted as
a synonym for `validate:`.

**The promotion chain is yours to name** (#109). `environments:` declares the deploy targets the
platform observes after a merge; `promote: [dev, qa, producao]` declares the order it walks them,
and the LAST entry is production — a human approves it from the panel, always, whatever your shop
calls it, so the manifest agrees with your change-management document instead of renaming a stage
to satisfy ours. A chain step with no matching environment is refused with both sides named; an
environment declared but absent from the chain is warned as unwatched, never silently accepted.
Omit `promote:` and the two fixed names apply — `staging` observed if declared, `prod` gated if
declared; environments with neither name and no `promote:` are refused, because that chain walks
nothing and the delivery would be announced at the merge. Every stage the chain walks, production
included, declares `deploy_ref`, `health_url`, or both — a stage with neither is refused rather
than counted as reached with nothing seen — and a deploy still pending is waited for, never
passed (#501). A stage counts as reached only on what was observed (#518): a green deploy of this
change, or a `health_url` that answered healthy. A `deploy_ref` nothing recorded this change
against (*unknown*) goes to the `health_url`, and with none the stage is held as not reached. On a
project with no CI (`ci: none`, which a `forge: local` project gets by default), nothing reads a
deploy, so every stage of the chain needs a `health_url`; the manifest is refused when it loads
until it has one, or until the registry names a CI that reads deploys (`forge.options.ci`).

**Measured limitation — one base branch.** `base_branch` is both where the factory's PRs land and
where the release tag is cut. A two-branch flow (integration `develop` + release `main`) cannot be
expressed: with the integration branch as base the release tag lands on the integration tip, and
with the release branch as base the factory's PRs bypass integration. If your shop runs two
branches, point the factory at the branch releases actually cut from and let your own CI carry
integration — and raise it during onboarding rather than discovering it at the first release.

**`preview:` says how the product runs for a preview** of a change before it merges ([ONBOARDING
§11c](../ONBOARDING.md)): `compose` (one file or several, merged the way compose merges them, read
from the base branch and never from the change), `expose` (service → the port it listens on inside
its container), `data` (per service, a shell command or an argument list, run into fresh volumes)
and `exclude`. Nothing in it grants anything: which names a preview may receive, whether one is
required before a merge, how long it lives and what it may reach are the operator's, in the
registry below. `env apply` never writes it; `openfactory preview propose` proposes it on a pull
request of its own. A product of several repositories declares the same block, plus where its
compose file lives (`compose: {repository, paths}`) and `dirs:`, in the context repository's
`.openfactory/product.yaml` instead.

---

## The registry

```yaml
projects:
  acme:
    name: acme
    repo_path: /var/lib/openfactory/repos/acme      # local path
    tracker: { kind: github, repo: acme/api,
               options: { board_owner: acme, board_number: "3" } }
    harness: codex                            # or per role, below
    language: pt-BR                           # when an agent SPEAKS FIRST (unset: en)
    box:
      image: mycorp.azurecr.io/ci-base:2026.7 # what your CI already runs on
      pull_credential: file:acme-registry     # a REFERENCE to the registry's secret, never the secret
      pull_username: ci-bot                   # the registry user it belongs to
      network: openfactory-egress                    # bound what agent code can reach
      cache_volume: openfactory_cache                # skip a full install per job
      cpus: "4"
      memory: "8g"
```

**The box image's pull credential is a reference, used for the pull and never handed to the box.**
`box.pull_credential` names the registry's secret the way `token_env` names an axis's
([the credential store](#the-credential-store)), and `box.pull_username` the registry user it
belongs to. When the image is not already on the worker's daemon, the worker resolves the secret, writes it
into a client configuration made for that one pull, pulls, and deletes the configuration; the
daemon keeps the image and never the login, and nothing of it reaches the box, whose environment
holds only `box.env` and the harness's own token. `openfactory box prove` pulls the same way. Unset,
the image is pulled as before, with whatever the daemon's client already holds. A container box
honours it; a box that runs no image of its own says it is ignored, as it does for every image
setting.

**A project on ONE MACHINE names no vendor at all**, which is what `openfactory project init
<name> <path>` writes:

```yaml
projects:
  myapp:
    name: myapp
    repo_path: /home/me/code/myapp          # the person's own checkout — this IS the forge
    tracker: { kind: local, repo: myapp }   # the board and the cards, in a file beside this one
    forge:   { kind: local, repo: myapp }   # branches, pull requests and the merge, in git
    ci:      { kind: none,  repo: myapp }   # there is no pipeline to observe, and that is a row
```

Every axis is spelled, deliberately: an axis left unwritten inherits the model's `github` default
and would be handed a credential belonging to somebody else's system. `local` and `none` need no
credential at all, and `openfactory doctor` reports them as needing none rather than as missing
one.

**The registry NAMES a credential; it never HOLDS one.** Every axis takes an `options.token_env`
(the channel takes `bot_token_env` / `app_token_env`) naming the environment variable that
carries the secret — or any reference [the credential store](#the-credential-store) resolves,
such as `token_env: file:acme-ado-pat` for a secret mounted as a file:

```yaml
    tracker: { kind: azure_devops, repo: Deskline,     # the ADO PROJECT — work items live here
               options: { organization: acme, token_env: ACME_ADO_PAT } }
    forge:   { kind: azure_devops, repo: dsk-api,          # the git repository inside it
               options: { organization: acme, project: Deskline, token_env: ACME_ADO_PAT } }
```

(`openfactory project add` writes exactly this shape from a `dev.azure.com` clone URL — the
complete ADO walkthrough, `work_item_type`, `state_map` and the multi-repo `areas` map included,
is [docs/setup/azure-devops.md](../setup/azure-devops.md).)

**An Azure Boards project can be limited to one Epic** with `scope_epic: "70133"` in the tracker's
options, the id of the Epic whose work items are this project's: the pickup queue, the board and
the search for an already filed card then read only the work items under it, at any depth, and an
Epic that cannot be resolved reads as an unreadable board, never as no scope. It is the Azure
counterpart of Jira's `scope_jql` (below), and
[docs/setup/azure-devops.md](../setup/azure-devops.md) §8 says what it limits, what it costs, and
the two limits to plan around.

**A Jira tracker names the site's own words**, because every Jira project has its own workflow and
its administrator named — and localised — everything in it:

```yaml
    tracker: { kind: jira, repo: DAR,                        # the Jira PROJECT KEY
               options: { site: "https://acme.atlassian.net", email: bot@acme.ai,
                          token_env: ACME_JIRA_TOKEN,
                          issue_type: Tarefa,                # default `Task`
                          status_map: '{"backlog": "A Fazer", "todo": "Pronto", "in_progress": "Em andamento", "done": "Concluído"}',
                          intake_status: "A Fazer",          # where Jira creates a new issue
                          scope_jql: 'labels = "of-api"',    # this project's slice of DAR
                          not_delivered_resolution: "Won't Do" } }
```

**`email` and the token `token_env` names must be one account's**: the token is created at
id.atlassian.com by the account whose address `email` holds. Jira Cloud does not refuse a token of
another account, nor an empty one; it answers as if nobody had signed in, a 404 on every card that
exists (measured 2026-10-19). The tracker tells that apart by asking Jira who is signed in, and
refuses by name: *"the email … and the API token belong to different accounts, or the token was
revoked"*, or *"no API token reached this tracker"* — never "not found". The first sentence names
a revoked token too, because nothing tells the two apart; a revoked token was not measured. A card
that is really missing still reads as missing.

`status_map` says which status each lifecycle key (`todo`, `in_progress`, `in_review`,
`needs_review`, `needs_action`, `done`, `backlog`) means; an unmapped key leaves the card where it
is, with a warning — except `needs_review`, which is optional: it is where a pull request waiting
on a person (their review, or the click that merges it) goes, and while the map does not name it that pull request goes to
`needs_action`'s status, as it did before the key existed. A site status already called
`Needs Review` is read back as that key, but the factory moves a card there only when
`status_map` names it — and the name `Needs Review` is that key's only while `status_map` gives
it to no other key: a park already called `Needs Review` (`"needs_action": "Needs Review"`) is
still read as a park. Two keys mapped to one status (`"in_review"` and `"needs_review"` both
`"In Review"`, or both `"In review"`) are read back as `in_review`, the factory's own review: a shared status cannot tell
the two apart, so give the wait a status of its own to have it read as a wait. It is also what the platform READS the board back with — a Jira project's statuses ARE
its columns, so `status_map` is how it knows a card in `Concluído` is delivered work and one in
`A Fazer` has not been picked up yet. A status it names nowhere is reported as such, by name, when
somebody tries to edit or close that card. **`columns` is not read on a Jira row**: it is the
option the GitHub, Azure Boards and local rows take (below), and the two maps are never both
consulted — each board answers for its own columns.

**Several projects can share one Jira project** with `scope_jql`, a JQL condition that selects this
project's issues out of it. Without it every registry project on `DAR` reads all of `DAR` as its
queue, and a deployment of about nineteen repositories on one Jira project had one ticket picked up
by three of them in one night (v0.6.0-rc.2). The condition is ANDed, in parentheses, onto every
search of the project's issues: the pickup queue, the board the panel, the product role and
`openfactory forget` read, and the search for an open ticket of the same title that keeps an
impediment or a product filing from being filed twice. So `labels = "of-api" OR labels = "of-web"`
reads `project = "DAR" AND (labels = "of-api" OR labels = "of-web")` and cannot widen the read past
the project. It does **not** narrow what is read or moved by key (a card, its transitions, its
children by parent), the workflow's statuses, or the check that the project exists: a slice with
nothing in it reads as an empty board, and a project that is not there still reads as unreadable.
Single-quote it in YAML, because JQL quotes with `"`. Unset, or blank, the queries are exactly
those of a project without it.

**The cockpit's Board link opens the panel's own board for a project with `scope_jql`**, so it
shows that project's scoped slice. An Azure Boards project with `scope_epic` follows the same
rule. Every other project opens its provider's board.

**Every project on a shared Jira project needs its own `scope_jql`, and no issue may be in two
scopes.** The scope narrows only the project that declares it: one project left without a scope
still reads all of `DAR` as its queue and picks up every other project's tickets. Nothing compares
one project's scope with another's, so two scopes that both select an issue — two labels on one
issue, or `labels = "of-api" OR component = "Web"` beside `component = "Web"` — put that issue in
both slices: each project's pickup reads it in its queue, as three did in the incident above, and
each project may edit, close, remove, queue or rank it. Pick a field that takes one value per issue (a component
the issue has only one of, or a single label of a set), and give every project on the Jira project
its own.

**A scoped project refuses to edit, close, remove, queue or rank a card outside its slice.**
Editing, closing, removing or queueing a card first asks where it sits, and a card outside the
slice is not on this project's board; ranking one in the product role's order writes by key. So
the factory asks Jira once more, `project = "DAR" AND (<scope>) AND key = "<card>"`, and refuses a
card that is not in the slice by name: it is another project's card, or one this project filed
that the scope does not select, and only from inside a slice can the factory tell whether a job is
on it — act on it from the project whose slice it is in, or put it in this one's scope. If that
search cannot be made, the action is refused as for an unreadable board. A project without
`scope_jql` makes no extra request.

Three acts are **not** held to the slice yet, and reach any card of the Jira project by its key:
starting a job on a card (the floor's `start` and `openfactory run <project> <card>`), which an
operator does by naming the card; reopening a closed card, which the reopen reaches by key
without asking the slice; and commenting on a card, which is written in the person's own name.
Name only cards of this project's slice to them.

A condition Jira cannot parse — an unclosed quote, an `ORDER BY` inside it — is answered `400`
(measured on Jira Cloud 2026-10-19): the board and the ticket list read as unreadable, never as
empty, the pickup queue picks up nothing, and the warning names the `scope_jql` it searched with.
A condition that parses but selects nothing is an empty queue, and nothing says so yet.

**The factory's own new tickets must match the scope.** Its create writes only the project, the
summary, the description and the issue type, so a split's children, the product role's cards and
an impediment it files carry no label of yours. Outside the scope, the poller never picks them up,
the panel and the product role do not see them, and the search for an earlier filing does not
find them, so each retry files another. Scope by something every new issue of this project
receives on create — a label or a component that a Jira automation rule sets on each issue the
project's own account creates (one `email` and `token_env` per project, so the rule can tell them
apart) — rather than by a label nobody writes. This is the Jira counterpart of
the team area paths an Azure Boards board reads (`docs/setup/azure-devops.md`); there, what the
factory creates is put in the area, so it stays inside what it reads.

**The queue needs a status of its own.** Jira creates a new issue in its workflow's first status,
and its create cannot be told another — so where `todo` names that status (`To Do`, `A Fazer`, on
the templates a project starts from), every card the factory files would be picked up and built,
and paid for, with nobody queueing it. Nothing files a card there: the product role, the board's
own `card_create`, a split that keeps its children in the backlog, the factory's impediment and
`preview propose --as-card` each refuse and say why, and `openfactory doctor` fails `board_intake`
with the line that repairs it — add a status of the To Do category for the queue (`Pronto` above)
and map the first status as `backlog`, as the example does.

**Where a new issue starts is read, never guessed.** It is read off the project's statuses for the
`issue_type` only where it cannot be a guess: the type's one status of the To Do category. Jira
publishes a workflow's initial status only to its administrator and documents no order for the
statuses it lists, so a workflow with several — the example's, once `Pronto` is added — says which
with `intake_status`: the status the workflow starts a new issue in. Undeclared there, or declared
as a status the type does not have, nothing is filed and `openfactory doctor` fails `board_intake`
naming the statuses; the line it hands over for the queue declares `intake_status` with it.

`not_delivered_resolution` is the **resolution** this site gives a card that was closed
*without* the work being done — a duplicate, a withdrawn request. With it, such a close carries
that resolution and reads back as not delivered. It has **no default**: the list of resolutions
is the site's, and a literal would be a name most sites do not have. Without it — or where the
closing transition's screen has no Resolution field, as Atlassian documents for team-managed
projects — the card is still closed, a note on it says the work was withdrawn, the log line
`OPENFACTORY_JIRA_WITHDRAWN_READS_AS_DELIVERED` names this option, and **the card counts as
delivered** in everything that reads the board: Jira then holds nothing that says otherwise.

A site that says "withdrawn" with a **status** instead — `Cancelled`, `Won't do`, a column of its
own in the Done category, which is the only way a team-managed project has — names that:

```yaml
                          not_delivered_status: "Cancelado"
```

The withdrawn close is then the plain transition into that status, with no field a screen could
refuse; a closed card sitting in it reads as not delivered whoever put it there, and a card moved
back out of it stops reading that way by itself. It has **no default** either. Name both and the
status is tried first; the resolution is what is left for a card whose workflow has no move into
that status from where it is, and the degraded close above is what is left after that. A status
the site files *outside* its Done category is not used — moving a card there would not close it —
and the same log line says so. The board needs nothing: on Jira the column is the status, so the
card shows in the site's own column and never in the pickup queue.

That is what lets ONE deployment drive projects on different vendors — and it is not a
refinement, it is a correctness fix: with a single process-wide token, a worker serving a GitHub
project and a Jira project authenticated both with whichever one the environment happened to
carry, and the Jira board came back with an empty queue (found live, fx-jira 2026-08-05). Name
nothing and the axis falls back to the deployment-wide default (`OPENFACTORY_BOT_TOKEN`,
`AZURE_DEVOPS_PAT`…), which is correct exactly while one vendor exists. The registry is also
often gitignored and baked into a worker image — a token written here is a token in an image
layer.

**`harness`** takes one value for everything, or one per role:

```yaml
harness: { executor: codex, reviewer: claude_code, techlead: claude_code }
```

The keys are the shipped roles (`executor`, `reviewer`, `techlead`, `product`), `default` for
every role not named, and any role a deployment installed as an add-on (a `role.<name>` entry
point — [configuration §11](../configuration.md)). A key that is none of these is **warned by
name** when the registry loads; it configures nothing.

**`model`** — which model that harness runs — takes the same two shapes, in the harness's OWN
naming (each CLI names models differently; a Bedrock inference profile ARN is a legitimate
value). You never have to edit this by hand: `openfactory project add --model <m>` sets the
blanket form at registration, and `openfactory project set-model <name> <m> [--role executor]`
changes it later — per role too — from the CLI.

Keeping an *independent* reviewer on a different engine from the one that wrote the code is what
makes the review prompt's *"you did NOT write this code"* structurally true. Rotating between
harnesses never touches an image — they are mounted, not baked ([ADR-0037](../adr/0037-the-box.md)).

**`box`** is only honoured by the container box. On a Fargate deployment `box.image` **raises**
rather than being ignored, and the other four warn — a setting that looks configured and is not is
this codebase's most expensive recurring defect, and refusing loudly is cheaper than a silent lie.

**`preview`** — what the OPERATOR decides about a project's previews, written with `openfactory
project set-preview <name>` and read back with `openfactory project show <name>`:

```yaml
    preview:
      required: true            # the factory never merges this project on its own; a person looks
      hours: 24                 # how long a preview lives, 1–168
      env:                      # per service ("*" = every one): container name → WORKER variable
        api: {DATABASE_URL: MYAPP_PREVIEW_DATABASE_URL}
      build_args: {}            # names a BUILD of a changed service may also read; empty by default
      network: ""               # an operator network for egress; "" = nothing outside
      cpus: "2"                 # per service
      memory: 2g                # per service
```

`set-preview` has no flag for the rest, which keep their defaults unless this block says
otherwise: `memory_total` (8g, what one preview's services may reserve together), `max_services`
(12), `pids_limit` (512), `tmpfs_size` (256m), `caps` (what is left after dropping every
capability), `start_timeout_minutes` (30), `upstream_timeout_seconds` (180) and
`keep_failed_minutes` (30). A name that is one of the factory's own credentials — `OPENFACTORY_*`,
`TEMPORAL_*`, `ANTHROPIC_*`, `CLAUDE_*`, the known vendor tokens, any project's `token_env`, and
every name a harness route requires (`OPENAI_API_KEY`, `AZURE_API_KEY`, `AZURE_RESOURCE_NAME`,
`AWS_REGION`, `AWS_DEFAULT_REGION`, `CLOUD_ML_REGION`, `VERTEX_REGION`) — is refused on either side
of a mapping, and said; `bridge` and `host` are refused as the network. The same policy is the
`project_set_preview` action, so any credential that is the installation's administrator on the
panel sets it too, within the same refusals.

**`channel`** — where the factory speaks to *this project's* humans. It is deliberately absent
from the example above: unset means **the panel**, the one surface that always exists, and that
is the shape a stranger should copy. `channel: <kind>` names a row on the channel axis, and
nothing else does (#266 slice 6): a chat add-on's own settings — the room it posts to under
`channel`, the variables naming its secrets — go in `channel_options`, opaque to the core, and
never imply a kind. A kind no installed package declares is **refused by name** when the channel is
built, naming the package that carries the row. Declare the kind in the registry of a deployment
that installed that add-on; the worker keeps serving every other project through the panel either
way. The old coordinate keys (`channel_id`, and `slack_channel` before it) are still read into
`channel_options.channel`, with a deprecation warning that names them, until 0.5.0 — and a
project that carried one without declaring its kind is on the panel now, which that warning says.

**`language`** is a default, not a hard setting, and the difference matters: it only governs an
agent SPEAKING FIRST — an announcement, a diagnosis, a question nobody prompted. A reply always
mirrors whatever language the human just wrote in, regardless of this. It lives here rather than
in the manifest because it is about how the factory talks to *this project's humans* — the same
axis as `channel`, not the code — and it reaches every human-facing role (tech-lead and
product); the coding phases are untouched. `openfactory project add --language <code>` sets it from the
CLI too.

**An unknown key here is IGNORED and reported by name**, not fatal — the opposite of the manifest,
and for a concrete reason: this file is often gitignored and baked into a worker image, so nobody
reviews it, and one stale line becoming an outage is a failure the operator could not have caught.

---

## The credential store

**Every secret the core reads comes through one seam**, the credential store: the per-axis tokens,
the generic pair, the GitHub App key, the harness tokens, the panel's tokens and keys, the engine's
key, a `box.env` name the box passes through, and the box image's pull credential. The readiness
report and `openfactory certify` also measure an environment or audit `.env.compose`, and ask the
store beside it; the stack preflight, which runs before the stack and its store exist, reads
`.env.compose` alone, and when `OPENFACTORY_CREDENTIAL_STORE` declares a store other than `env` it
sends a missing agent credential to that store, not to `.env.compose`, and names `openfactory
doctor` as the check once the stack is up; the doctor's own remedy for that missing credential
names the same store (and, for `file`, the directory `OPENFACTORY_CREDENTIAL_DIR` names), not
`.env.compose`. `tests/test_every_stored_credential_is_read_through_the_store.py`
holds every module of the package to that: a credential read by a name the code spells (a
literal, a constant, a table of them), from the environment or through any other mapping, fails it
outside the store unless the function says what its mapping is. A name computed while running is
beyond such a scan, and each reader of that kind has a test of its own.

**A reference is `<store>:<name>`**: `env:ACME_JIRA_TOKEN` is a variable, `file:acme-jira` is a file
in the credential directory, and an installed add-on's store reads its own (`credential_store.<kind>`
in the `openfactory.adapters` group, the axis [writing an add-on](../writing-an-addon.md) lists). A
**bare name** — every `token_env` written before references existed — is a deployment credential by
that name.

**A deployment credential is asked of the store the deployment declares, then of the
environment.** `OPENFACTORY_CREDENTIAL_STORE` names that store, and unset it is `env`: one lookup,
the variable, exactly as before references existed — nothing changes for an installation that
declares nothing. Set it to `file` and the credential `CLAUDE_CODE_OAUTH_TOKEN` is the file
`CLAUDE_CODE_OAUTH_TOKEN` in the credential directory when there is one, and the variable when there
is not, so secrets move into files one at a time. A file holds the value its variable would have
held: the PEM for `OPENFACTORY_GH_APP_KEY_CONTENT`, a path for `OPENFACTORY_GH_APP_KEY`.

**The file store**, for secrets mounted into the worker the way container platforms deliver them:

- `OPENFACTORY_CREDENTIAL_DIR` is the directory, `/run/secrets` for a compose stack's `secrets:`
  and a mounted cluster secret volume alike. A reference names one file in it, never a path.
- **Read at each use, kept by nobody.** A rotated file is the next use's.
- **Refused by name**, and never replaced by the variable, when:
  - a directory on the name's way may be written by anyone but its owner, on a mount that accepts
    writes. Those directories are the credential directory, the directory the file is in, each
    directory one of the name's links is in, and every directory between one of those and the
    credential directory;
  - on a mount that refuses writes, such a directory belongs to anyone but root or the worker's
    user — and then every file read through it must belong to root or the worker's user too;
  - a link on the name's way, the one under the name or one further along, was made by anyone but
    root or the worker's user. The name is followed one link at a time (`readlink`), and it is
    refused when it leads through more than 40 links or ends outside the directory;
  - the file is not a regular file, is larger than a credential (64 KB), or is not text;
  - on a mount that accepts writes, the file may be written by anyone but its owner, or it has
    more than one name (a hard link).

  Each refusal ends with its repair. A cluster's secret volume, mounted read-only and owned by
  root, is read as it is mounted.
- **Except on a mount that refuses writes.** Compose mounts a `secrets:` file read-only with the
  mode it has on the host, and on a host whose umask is `0002` (Ubuntu's, for users) a file made
  with `echo … >` is `0664`. Nobody who sees a read-only mount can write through it, so its write
  bits are not asked; what guards the file is its mode **on the host**, where it is created: make
  it `chmod 600` there (`640` or `644` work as well — the read bits are the container's
  business). On a writable mount the rule stands: `chmod go-w` the file, or mount it read-only.
  What is asked is the mount the file is read through: a volume mounted writable at another
  path is writable there, whatever this path says, so mount a secrets volume read-only
  everywhere it is mounted.
- Its content, with the surrounding whitespace and a byte-order mark removed, is the secret; an
  empty file holds nothing, and the variable of the same name answers then, as where there is
  no file — to revoke a secret, remove the file and unset the variable.
- The worktree box withholds the directory's path from the workload, but the files are on the
  worker's filesystem, readable by the worker's user — [SECURITY.md](../../SECURITY.md).

**A refusal is final.** A credential the store refuses is not replaced: not by the variable of the
same name, not by the next name a credential falls back to (`OPENFACTORY_TRACKER_TOKEN`, then
`OPENFACTORY_BOT_TOKEN`), not by a mint, a login or a generated key. A refused panel token keeps the
panel closed — every request is answered "identity provider unavailable" (503) until it is fixed,
and the log and `openfactory doctor` name the variable and the reason. A refused harness
credential stops the agent rather than letting it run on the next one, and a refused `box.env`
name crosses into neither box. A declared store that cannot be read at all, or a kind nobody
installed, refuses every credential in the same way. With no token, the GitHub forge, tracker,
board, CI observer and `openfactory project init`'s board creation do not run `gh` on the
machine's own login in its place either.

**A remote box** cannot read the worker's files, and what its launcher is handed for a stored
secret depends on what the launcher declares. A launcher that declares nothing is handed values:
short-lived minted tokens only (the machine's own identity, minted on the worker), because a
launcher may keep its launch environment where others can read it, and a stored secret lives as
long as its owner keeps it. So an axis whose secret a store other than the environment holds is
refused for it, by name, before anything is launched: "the `fargate` box's launcher does not
declare that it resolves credential references itself, so it is handed only short-lived minted
tokens and the store's secret is not put into its launch environment". The core's `fargate` row
declares nothing, so it receives minted tokens only. A launcher that declares
`resolves_references = True` is handed references to stored secrets and resolves them on its own
side: it receives the reference (`file:<name>`, or `<kind>:<name>`), never the value, and the box
reads that axis from the variable the launcher fills. For a box whose launcher declares nothing,
hold such a secret in a variable the box reads for itself (`env:<NAME>`), which is handed over by
name only, or declare the machine's own identity (`identity: workload`). The doctor's
`launcher_credentials` line says, for each remote box, whether its launcher is handed references
or values (or that its runner is not installed here, so what it declares cannot be seen), and fails
before the first job when this deployment's box is remote, its launcher declares nothing, and one
of the project's secrets is held in the store.

**`openfactory doctor` says where each credential comes from, never its value**: the
`credential_store` line names the store the deployment declares and every reference the project
names, with the store that answers for it — and fails a store nobody installed, a directory it
cannot read, a reference that can never answer, a pull credential with no user name or no
secret, and every deployment credential the store refuses, whether a reader names it or the store
merely holds it, each with its repair. The forge line says which reference answered, and the
agent credential line says which reference the harness token came from; when the store refused
one, the forge, board and agent credential lines say that instead of "not configured", and never
ask for a variable that is already set.

---

## The environment

Secrets and deployment coordinates. The ones you will actually set:

| | |
|---|---|
| `CLAUDE_CODE_OAUTH_TOKEN` / `ANTHROPIC_API_KEY` | the harness. Irreducible |
| `OPENFACTORY_GH_APP_ID` · `OPENFACTORY_GH_APP_KEY` *(path)* or `OPENFACTORY_GH_APP_KEY_CONTENT` *(the PEM)* · `OPENFACTORY_GH_APP_INSTALLATION_ID` | the GitHub App |
| `OPENFACTORY_BOT_TOKEN` | a static forge/tracker token instead of the App. `OPENFACTORY_TRACKER_TOKEN` / `OPENFACTORY_FORGE_TOKEN` override per axis |
| `OPENFACTORY_BOT_NAME` · `OPENFACTORY_BOT_EMAIL` · `OPENFACTORY_BOT_LOGIN` | who the factory commits as |
| *(the chat channel's variables)* | **not read by the core.** The rows that read them ship in the `openfactory-slack` add-on package and declare their own names (`plugins.environment`); the package's README lists them. Setting them on a core without the package switches nothing on — the channel is the panel and the notifier is the panel's |
| `OPENFACTORY_PANEL_TOKEN` | **unset means the panel is OPEN** — and it is the SHARED token; approvals recorded under it have no name |
| `OPENFACTORY_PANEL_TOKENS` | per-person panel identity, `token:id:display,...` — the only way "who approved that release" has an answer |
| `OPENFACTORY_PRODUCT_TOKEN` / `OPENFACTORY_PRODUCT_TOKENS` | the product-owner surface (`/product/<name>`), and the board of a project with a product role, read only (`/p/<name>/board`; its cards, never a pull request's diff). The shared form is read-only in practice — writes check `product.admins` against the per-person `id` ([06](product-role.md)) |
| `OPENFACTORY_BOARD_TOKEN` / `OPENFACTORY_BOARD_TOKENS` | the board and the rest of the floor, and nothing of the product owner's area, which refuses it by name (#562). The panel token stays the administrator's |
| `OPENFACTORY_IDENTITY` | which identity provider the panel asks: `local` (the token variables above, the default) or `oidc` (log in through your own OpenID Connect provider — Entra ID, Okta, Keycloak, Google, Auth0). Never inferred; an unknown kind refuses every request |
| `OPENFACTORY_OIDC_ISSUER` · `OPENFACTORY_OIDC_CLIENT_ID` · `OPENFACTORY_OIDC_CLIENT_SECRET` | the provider's issuer URL and the client it registered for the panel (callback `https://<panel>/auth/callback`). The secret is optional — PKCE is used either way |
| `OPENFACTORY_OIDC_REDIRECT_URL` · `OPENFACTORY_OIDC_SCOPES` · `OPENFACTORY_OIDC_ID_CLAIM` · `OPENFACTORY_OIDC_GROUPS_CLAIM` | the callback as the provider knows it (set it behind a TLS-terminating proxy), the scopes asked for (`openid profile email`), which claim is a person's id (`email`), which claim carries their groups (`groups`) |
| `OPENFACTORY_OIDC_GROUPS` | `<provider group>=<platform group>` rows, comma-separated — `product` scopes its members to the product surface; a group not named passes through so `admins` may name it |
| `OPENFACTORY_OIDC_TRUST_UNVERIFIED_EMAIL` | `1` to accept an `email` id the provider did not mark verified — for a provider emitting no `email_verified`. Default refuses: an address nobody verified is not an identity an allowlist may spell |
| `OPENFACTORY_PROD_APPROVERS` | deployment-wide release allowlist (the manifest's `prod_approvers` is the per-project form) |
| `OPENFACTORY_APPROVERS` / `OPENFACTORY_APPROVERS_FILE` | the hashed release passwords, when `~/.openfactory/approvers.json` cannot be mounted. `OPENFACTORY_APPROVERS` (JSON, login → hash) wins: while it is set the file is neither read nor written, and a value that is not a JSON object means nobody can approve — `openfactory approver list` says which. Mint an entry with `OPENFACTORY_APPROVERS= openfactory approver add <login>` and copy it from the file |
| `OPENFACTORY_SANDBOX` | which box every job runs in: `worktree` \| `container` \| the kind an installed box add-on registers (`fargate`, from the AWS add-on). Unset → `container`. **Never inferred** — a cloud deployment DECLARES `OPENFACTORY_SANDBOX=fargate`; setting only the add-on's cluster coordinates leaves every job in a local container |
| `OPENFACTORY_CREDENTIAL_STORE` | which store the deployment's own credentials are asked of before the environment: `env` (unset means this — the environment alone) \| `file` \| the kind an installed add-on registers. Never inferred; a kind nobody installed refuses every credential by name rather than falling back ([the credential store](#the-credential-store)) |
| `OPENFACTORY_CREDENTIAL_DIR` | the file store's directory, where the deployment's secret files are mounted (`/run/secrets`). A reference `file:<name>` names one file in it. Withheld from a worktree workload |
| `OPENFACTORY_TOKEN_POOL_SOURCE` | where the panel reads the agent-token pool from (count and ids, never a value): `env` (the default — this process's environment) \| the kind an installed add-on registers (`ssm`, from the AWS add-on). Unset → `env`. Never inferred — the reference cloud deployment declares `ssm` |
| `OPENFACTORY_SANDBOX_IMAGE` | deployment-wide box image; a project's `box.image` wins |
| `OPENFACTORY_METRICS_SINK` · `OPENFACTORY_METRICS_DB` | `sqlite` locally, `dynamodb` in the cloud, `null` for neither |
| `OPENFACTORY_NOTIFIER_FALLBACK` | the deployment-wide fallback notifier, as a KIND on the notifier axis — where speech goes when a project's own channel cannot carry it, and where a project with no channel is spoken to. Unset → the panel. `telegram` is the row the `openfactory-slack` package declares (it reads `OPENFACTORY_TELEGRAM_BOT_TOKEN` and `OPENFACTORY_TELEGRAM_CHAT_ID`; the core reads neither). A declared kind nobody installed, or a row that cannot post, is a warning naming what is missing — never silently the panel |
| `OPENFACTORY_GUIDELINES_DIR` | the DEPLOYMENT's own guidelines (#318): a directory whose `*.md` are inlined into every job **after** the framework baseline and **before** the project's own `docs.guidelines`, and whose `reference/*.md` are INDEXED and read on demand. An OPERATOR setting, read from the environment and nowhere else — never a manifest, never an add-on, because it decides what every job on the deployment reads. Paths are contained: a symlink leading out of it is ignored with a warning. On a box that ISOLATES, the directory is mounted read-only into the box and the index names that mount; on compose it must ALSO be visible to the worker **at the same absolute path as on the host** (like `OPENFACTORY_WORK_DIR`), because the worker reads the documents and the host's daemon resolves the bind |
| `OPENFACTORY_PROMPT_BUDGET` | how many BYTES of the brief a pass is handed may take beside its role prompt — the card, the plan, the knowledge map, a repair's failure log, the reference index and every declared document together (ADR-0056). Unset → 160,000 bytes; `off` → no bound, every document inlined. The project's own guidelines are kept first, then the decision records newest first, then the operator's, and every document left out or cut is named in the prompt by the path the agent can open it at. An OPERATOR setting, read from the worker's environment and never from a manifest. Any other value is refused by name: `openfactory doctor` fails its `documents` line and every job holds before a pass |
| `OPENFACTORY_ROLE` | what `openfactory doctor` calls the container it runs in, on its `pid_headroom` line: the compose stack's file sets `worker` and `panel`. Unset → `container <hostname>` |
| `OPENFACTORY_LOG_DIR` | where the job journals are written and read — the panel's **Logs** button, and the free counterpart of a cloud log group. The worker and the panel must agree |
| `OPENFACTORY_LOG_LEVEL` | the level the platform's own log lines are kept from, in the worker's and the panel's log (`DEBUG`, `INFO`, `WARNING`, `ERROR`). Unset, or not a level → `INFO`. Every line carries its UTC time, its level and its logger's name; the libraries' own lines stay at `WARNING`, the panel's request lines at `INFO` |
| `OPENFACTORY_LOG_FORMAT` | `json` makes the worker and the panel write one JSON object per line, on stderr and on stdout alike. What either would print for a person is logged rather than printed: the line each prints when it starts, the sentence a worker that cannot start ends with, and what the work a worker runs says (a pre-flight that could not size, a leftover box removed, a resumed session, a token failed over), at its level. So are the live feed's `OPENFACTORY_EVENT:` envelopes, each the `message` of an INFO line from `openfactory.journal`, Python's own warnings (`py.warnings`), and an exception nobody caught, in any thread (`openfactory.uncaught`, its traceback in `exception`, written whatever `OPENFACTORY_LOG_LEVEL` says, as Python's own report is). A box's own program keeps its stdout as it was. The fields: `ts` (UTC, to the millisecond), `level`, `logger`, `message`, `exception` when the record carries one, `stack` when it was logged with `stack_info`, `deployment` when `OPENFACTORY_DEPLOYMENT` is set, and `project` and `product` when the record concerns one — every record a worker activity or a panel route about a project writes, the body of a stream it answers with included. The product is what the registry said at this process's last read of it, at most a few seconds old; a line written before the first read leaves it out. The durable engine client's own lines come through the same format; each client is made on a runtime of its own, so a connect first asks whether anything listens at the engine's address, and an attempt that fails after that leaves the address alone for `OPENFACTORY_ENGINE_UNREACHABLE_FOR` seconds, then twice that after each attempt that fails again, up to a minute. Unset, or any other value → the readable line above, unchanged |
| `OPENFACTORY_DEPLOYMENT` | a name for this deployment, written as `deployment` on every JSON log line, for a log store several deployments write to. Unset → no `deployment` key |
| `OPENFACTORY_HEALTH_PORT` | the port the WORKER answers `/healthz` and `/readyz` on — it serves no other HTTP — once its boot's own steps are done (a first boot copies the harness toolbox first). The compose file sets `8788` and its healthcheck asks it there, from inside the container, every 15 seconds. The panel's healthcheck asks the panel's port as often, and each of those asks is a `uvicorn.access` line in the panel's log. Unset → the worker answers nothing and opens no port. The panel answers both on its own port, always (`docs/reference/the-front-end-api.md`) |
| `OPENFACTORY_HEALTH_HOST` | the address the worker answers `/healthz` and `/readyz` on, when `OPENFACTORY_HEALTH_PORT` is set. Unset → `127.0.0.1`, the default `openfactory serve` binds the panel to: only this machine (or this container) can ask. Set `0.0.0.0` where a supervisor probes from outside, such as an orchestrator's probe of a container; the compose file needs neither, because its healthcheck runs inside the container. The probe asks `127.0.0.1`, which `0.0.0.0` includes; where this names one other address, give the probe that address with `--host` |
| `OPENFACTORY_ENGINE_DEADLINE` | how long the worker and the panel wait for the durable engine to answer one read, and to take a connection, in seconds (a worker being born waits for its first connection as long as `OPENFACTORY_ENGINE_STARTS_IN` allows instead). Unset, or not a positive number → `3`. `/readyz` waits twice that and one second more for any one check (7 s by default), and the probe a healthcheck runs (`python -m openfactory.observability.health`) waits two seconds more than `/readyz` (9 s), so a deployment that raises it raises its healthchecks' `timeout:` with it, above twice the deadline plus three seconds: the compose file's is `10s`, which holds the default. A timeout shorter than that kills the probe before it prints which check failed |
| `OPENFACTORY_ENGINE_UNREACHABLE_FOR` | how long the panel leaves the durable engine alone after a read it did not answer in time, in seconds: reads in that window are answered at once with the engine unreachable, instead of each waiting `OPENFACTORY_ENGINE_DEADLINE` again. With `OPENFACTORY_LOG_FORMAT=json` it is also the first wait after a connect that failed once the address had taken it, which doubles after each attempt that fails again, up to a minute. Unset, or not a positive number → `3` |
| `OPENFACTORY_IMAGE_DIGEST` | the digest of the image this process runs from, as the deployment that pulled it by digest names it; `/api/v1/version` answers it as `image.digest`. An image cannot carry its own digest (writing it in would change it), so only its deployment can say it. Unset → `null`, beside the build stamp the image wrote itself |
| `OPENFACTORY_SESSION_STORE` · `OPENFACTORY_RESUME_DIR` | where a paused agent session waits so the next run continues it instead of replanning: `file` (the default — a directory on this machine) or `s3`. Unset → `s3` if `OPENFACTORY_RESUME_BUCKET` is set, else `file` |
| `OPENFACTORY_REGISTRY` · `OPENFACTORY_REGISTRY_SEED` | where the registry is read and what seeds it on first boot |
| `OPENFACTORY_TOOLBOX` · `OPENFACTORY_TOOLBOX_VOLUME` | the harness toolbox: where the worker keeps it, and the docker volume name it mounts into boxes |
| `TEMPORAL_ADDRESS` · `TEMPORAL_NAMESPACE` | the durable engine. Compose sets these to its own container |
| `OPENFACTORY_MAX_CONCURRENT_JOBS` · `OPENFACTORY_MAX_TURNS` · `OPENFACTORY_AGENT_TIMEOUT` | the throttles |
| `OPENFACTORY_PREVIEW_RUNTIME` | which runtime runs a preview: `compose` \| `none` \| the kind an installed add-on registers. Unset → `none`; the compose stack's file sets `compose`. The deployment's to name, never a repository's ([setup/previews.md](../setup/previews.md)) |
| `OPENFACTORY_PREVIEW_REACH` · `OPENFACTORY_PANEL_CONTAINER` · `OPENFACTORY_PREVIEW_PORTS` | how the panel reaches a preview: `network` (unset means this) — the worker joins the panel's container, `openfactory-panel` on the compose stack, to each preview's own network — or `loopback`, one machine: exposed services on 127.0.0.1 at ports within `lo-hi` |
| `OPENFACTORY_PREVIEW_DOMAIN` | the domain previews are served under; the worker and the panel must agree. Unset → no preview is served; the compose stack's file sets `preview.localhost`. Sharing a plain-http panel's registrable domain fails `openfactory doctor` |
| `OPENFACTORY_PREVIEW_SECRET` | the key preview links are signed with; `init` generates it. Unset → one per panel process |
| `OPENFACTORY_PREVIEW_DOCKER_CONFIG` | the registry logins previews pull with (`openfactory preview login`). Unset → `~/.docker`; the compose stack's file sets `/var/lib/openfactory/docker` |
| `OPENFACTORY_PREVIEW_MAX` | how many previews run at once. Unset → 4 |
| `OPENFACTORY_SOURCES_PARALLEL` | how many of a product's sources are brought up at once — for a turn of the product role and for the system layer's refresh. Each is one git process talking to its forge. Unset → `8`; a value that is not a positive number is 8, said once in the log |
| `OPENFACTORY_LIST_CONCURRENCY` | how many recent jobs the job list asks the engine about at once — the list the panel, the floor and the tech-lead read. Each running job is a describe plus up to three queries a worker answers by replaying its history; readers asking the same question together share one scan. Unset → `8`; a value that is not a positive number is 8, said once in the log |
| `OPENFACTORY_SOURCES_FRESH_SECONDS` | how long a source brought up for the product role is served again without asking its forge, so a conversation's back-and-forth costs one question per source per window instead of per message. Unset → `60`; `0` asks on every turn; a value that is not a number of seconds is 60, said once. A commit pushed inside the window reaches the role on the first turn after it. Never applied to the system layer's refresh, which publishes the map right after a merge |
| `OPENFACTORY_EMBED` · `OPENFACTORY_EMBED_MODEL` · `OPENFACTORY_EMBED_MODEL_SHA256` | the product's search by meaning (#337). `local` (unset means this) reads a model from the folder `OPENFACTORY_EMBED_MODEL` names — the worker image carries `minishlab/potion-multilingual-128M` at a pinned revision and names it — and loads only a model whose weights' SHA-256 the platform pins or `…_SHA256` declares. Nothing is downloaded and no text leaves the machine. `none` turns it off on purpose; the search then runs by exact words, metadata and time, and `openfactory doctor` says so |
| `OPENFACTORY_OCR_LANGS` · `OPENFACTORY_EXTRACT_ROWS` | how the product's documents are read: the languages OCR reads a scanned PDF in (`por+eng` unset; only those installed are asked for), and which row reads each document type as `type=row` pairs — images are described by the product role's model unset (charged per image), `image=ocr` reads them by OCR |

There are around seventy `OPENFACTORY_*` variables in total; the rest are per-job values the runtime sets
for itself inside a box, or cloud-only coordinates (`OPENFACTORY_FARGATE_*`, `OPENFACTORY_RESUME_BUCKET`,
`OPENFACTORY_*_LOG_GROUP`) that a local deployment never reads — a cloud-only *coordinate*, never a
cloud-only *capability*: every one of them has a free counterpart above, because a deployment with no
cloud may cost you a vendor and must never cost you a feature.

**Precedence, where it exists**, is always most-specific-wins: an explicit CLI flag, then the
project's registry entry, then a deployment-wide environment variable, then the framework's default.
