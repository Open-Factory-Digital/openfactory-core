# GitHub setup: the App, the board token, the board

This is everything the GitHub side of a deployment needs. `openfactory init` and
[docs/ONBOARDING.md](../ONBOARDING.md) send you here at the two moments that need it; nothing
on this page is a step you do on your own initiative.

| you are here for | go to |
|---|---|
| the factory's identity on GitHub | §1–§5, the App, creation to proven |
| a **personal** account's board credential | §6 |
| a board you already have, or want to build by hand | §7 |

> **Trying the platform out?** Use a **separate organisation** from anything real. The App you
> create below holds write access to everything you grant it, and keeping evaluation apart from
> production is cheaper than un-granting later.

---

## The GitHub App, start to proven

The factory can sign in to GitHub two ways. A **personal access token** is fastest and reads as
YOU on every commit — fine for trying it out, and `openfactory init` writes that row for you. A
**GitHub App** is what a team should run: its own identity, its own audit trail, a token that
expires. This page is the App path, every screen of it, ending with the command that proves the
three values you collected actually work.

**This is the ONE home of the permission table.** Every other document points here; if you find
another copy anywhere, it is a bug (a guard test enforces this).

It is two pages on GitHub and one trap per page: **creating the App and installing it are
different pages, and finishing the first looks like finishing.** The App reaches no repository
until you also install it.

---

## 1 · Create the App

Open the creation form for the account that owns the repositories:

| the repos live under | open |
|---|---|
| an **organisation** | `https://github.com/organizations/<ORG>/settings/apps/new` |
| your **personal account** | `https://github.com/settings/apps/new` |

(Personal account? Read [§6](#6--personal-account-the-board-needs-one-extra-token) before you
start — the board needs one extra token there.)

On the form, in order:

- **GitHub App name** — must be unique across ALL of GitHub, not just your account.
  `OpenFactory Bot` is taken; `<yourco>-factory-bot` will not be.
- **Homepage URL** — mandatory field, never used. Your company site, or this repository's URL.
- **Webhook → uncheck "Active"** — and this must happen **before** you submit: with it checked,
  the Webhook URL field is required and the form refuses to submit. The platform polls; it
  receives nothing.
- **Permissions** — exactly this table, dictated from a live working installation
  (2026-08-02) and verified against every GitHub call in the adapters:

  | | permission | level |
  |---|---|---|
  | Repository | Contents | **Read and write** |
  | Repository | Issues | **Read and write** |
  | Repository | Pull requests | **Read and write** |
  | Repository | Actions | **Read and write** |
  | Repository | Checks | Read-only |
  | Repository | Deployments | Read-only |
  | Repository | Administration | **Read and write** ¹ | 
  | Repository | Metadata | Read-only *(auto-selected)* |
  | Organization | Projects | **Read and write** |

  ¹ Administration write exists for ONE act: creating the **context repository** in your
  organisation (`onboard`'s context half, `product init --create-context`). If your product's
  context repository already exists — declare it with `openfactory product declare` — Read-only
  is enough. On a **personal account** no App permission can create a repository at all; the
  classic PAT of §6 is what does it there, and the command says so when it applies.

  **Do not grant Workflows — its absence is a feature.** It is what makes a push touching
  `.github/workflows/**` fail, which keeps CI/CD definitions human-only. A client who needs the
  factory to edit pipelines gets that through policy routing, never through this checkbox.

  Getting the table wrong is quiet in both directions: granting Workflows removes a guardrail;
  omitting Projects means no card ever moves and the error is obscure. Deployments Read-only is
  what lets the factory watch your declared environments after a merge
  (`repos/<repo>/deployments`); without it the deploy watch reads as "no deployment ever
  happened".

- **Where can this App be installed?** → *Only on this account* → **Create GitHub App**.

## 2 · Collect the App ID and the private key (same page)

You land on the App's **General** settings page.

- **App ID** — the "About" block at the **top** of this page: `App ID: 123456`. Note it. (The
  Installation ID is NOT on this page — that is §4, and confusing the two numbers is classic.)
- **Private key** — scroll down to "Private keys" → **Generate a private key**. A file named
  `<app-slug>.<date>.private-key.pem` lands in `~/Downloads`. For the compose stack the file is
  only a vehicle: what §5 needs is its **content**, so move it there right now and be done with
  the file —

  ```bash
  cat ~/Downloads/*.private-key.pem | pbcopy     # macOS; Linux: xclip -sel c < the file
  # paste between the double quotes init already wrote: OPENFACTORY_GH_APP_KEY_CONTENT="…"
  rm ~/Downloads/*.private-key.pem
  ```

  Losing the key is never fatal — this same page generates a NEW one whenever you need;
  paste the new content and recreate the stack. Keep the `.pem` around only if your deployment
  delivers the key **by path** (`OPENFACTORY_GH_APP_KEY=…`, the laptop/terraform shape) — then
  it belongs in a gitignored directory with `chmod 600`, never in `~/Downloads`.

## 3 · Install the App — the second page

On the App's settings page, click **Install App** in the **left sidebar** (or open
`https://github.com/apps/<app-slug>/installations/new`). Press **Install** next to your account,
then choose the repositories: *All repositories*, or *Only select repositories* — in which case
the selection must include every repository the factory works on **and the context repository**,
if you use the product role. (A context repository the factory CREATES is not in that selection
yet — add it right after, or the very next step fails to clone what was just made. *All
repositories* has no such gap.)

## 4 · Read the Installation ID off the URL

After installing you land on the installation's configuration page. The Installation ID is the
**number at the end of the URL in the address bar** — it appears nowhere in the page body:

```
https://github.com/organizations/<ORG>/settings/installations/<INSTALLATION_ID>   ← this number
https://github.com/settings/installations/<INSTALLATION_ID>                       ← personal form
```

To find it again later: Settings → *(Developer settings' sibling)* **GitHub Apps** →
**Configure** next to your App → read the URL again.

## 5 · Put the trio in `.env.compose`, quoted, and prove it

```bash
# .env.compose
OPENFACTORY_GH_APP_ID=123456
OPENFACTORY_GH_APP_INSTALLATION_ID=87654321
OPENFACTORY_GH_APP_KEY_CONTENT="-----BEGIN RSA PRIVATE KEY-----
...the whole file, line breaks and all...
-----END RSA PRIVATE KEY-----"
```

Two traps, both measured:

- **The PEM must be wrapped in double quotes.** Unquoted, its line breaks corrupt the parse of
  the **entire env file** (`docker compose` fails with *"key cannot contain a space"*) — every
  other credential in the file silently stops arriving with it.
- **Leave `OPENFACTORY_BOT_TOKEN` empty.** A filled PAT beats the App at every resolver, so a
  leftover token makes the App decorative and every commit reads as the token's owner.

Recreate the stack (compose bakes environment in at container creation — editing the file
changes nothing until you do), then **prove the trio**:

```bash
docker compose --env-file .env.compose up -d
docker compose --env-file .env.compose exec worker openfactory bot-token
```

A printed `ghs_…` token **is** the proof that App ID, private key and Installation ID agree —
it was minted from GitHub with them. **Do not save it anywhere**: it expires in about an hour,
and the factory mints its own for every job. The command is a test, not a step that produces a
credential you keep.

It proves minting, not repository access: `openfactory doctor <project>` checks reachability
and the board next (its board check authenticates for real; run it after registering the
project).

## 6 · Personal account: the board needs one extra token

An App's installation token generally **cannot drive a user-owned Projects v2 board** — that is
GitHub's limitation, not a permission you forgot. The working shape on a personal account is
mixed: **the App for code, a classic PAT for the board**. (`openfactory init` already wrote the
empty `OPENFACTORY_TRACKER_TOKEN=` row for you when you answered *personal*; this is how to
fill it.) The same PAT quietly covers the OTHER thing an App token cannot do on a personal
account: **creating the context repository** — `onboard` borrows it there, so no extra step.

**Create it** at `https://github.com/settings/tokens` → *Generate new token* → **Generate new
token (classic)**. The form, field by field:

- **Note** — any name you will recognise later: `openfactory board — <project>`.
- **Expiration** — the default is **30 days**, and this is the field that bites: when it lapses
  the cards simply stop moving and the failure reads as *"the board could not be read"*, weeks
  after you set this up. Pick the longest span your policy allows and put the date in a
  calendar, or plan to rotate.
- **Scopes** — exactly two:

  | check | why |
  |---|---|
  | **`repo`** (the parent box; its children come with it) | read the repository and its issues |
  | **`project`** — *"Full control of projects"* | move the cards. **It is far down the page**, below `codespace`/`copilot` — the single most missed checkbox on this form: without it the board exists, looks right, and nothing ever moves |

  **Never `workflow`.** Its absence is the same guardrail the App's table describes: it is what
  keeps the factory out of your CI/CD definitions.

- **Generate token**, copy the `ghp_…` value — GitHub shows it once — and paste it:

```bash
# .env.compose — beside the App trio
OPENFACTORY_TRACKER_TOKEN=ghp_…   # classic token, scopes: repo + project, NEVER workflow
```

Then recreate the stack (`docker compose --env-file .env.compose up -d`) so the row reaches the
worker — compose bakes the environment in at container creation.

The tracker/board axes then authenticate with the PAT while branches, pushes and PRs stay on the
App's identity. (An organisation-owned board has no such limitation — the Projects permission in
the table covers it.)

## 7 · The board — when you build it by hand

`openfactory project init <name>` creates the board with the right columns, and that is the
path ONBOARDING §2 walks. Build it by hand only when the board already exists, or when you want
it somewhere `init` would not put it. GitHub Projects v2, **six columns, named exactly** — this
is also the order `init` creates them in:

```
Backlog · TO-DO · In progress · In review · Needs Action · Done
```

- **Backlog** — parked or sequencing
- **TO-DO** — the drop zone; a card here gets picked up
- **In progress** — a job is running it
- **In review** — PR open
- **Needs Action** — parked, waiting for a person, with the reason on the ticket
- **Done** — merged

> **What bit us.** GitHub ships `Todo · In Progress · Done`. Note `In Progress` versus
> `In progress` — one letter. Rename it wrong and the column exists, the board looks right, and
> the job cannot find where to move the card. (Renaming your OWN names instead is supported:
> `columns:` in the project's registry entry maps them.)

Two more facts about an existing board, both measured: adding a Status option by **API** is what
`init` does on a NEW board, but editing an existing board's Status field re-mints every option
id and drops every card's assignment — so on a board with cards, add the missing columns in the
GitHub UI. And attach it to the project with
`openfactory project add … --board-owner <owner> --board-number <N>`; the number is the one in
the board's URL.
