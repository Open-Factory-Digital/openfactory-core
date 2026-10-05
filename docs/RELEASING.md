# Releasing OpenFactory

How a version of OpenFactory goes from `main` to the people who install it. It is written for the
**release manager**: whoever holds that role follows this page, by hand or through the
`release-manager` agent (`.claude/agents/release-manager.md`), which executes it step by step and
stops before every step that cannot be undone.

## Roles

| role | who, today | what they decide or do |
|---|---|---|
| release manager | @robertocsp | the cut date, what goes in, every tag, the go/no-go for each release |
| reviewer | @hermesfelipe | reviews every pull request, the version and backport pull requests included |
| deputy release manager | @hermesfelipe | takes the role when the release manager cannot: the `v*` ruleset lists both, so a release never waits on one person |
| release agent | `release-manager` | audits, prepares the pull requests, runs the rehearsals, drafts the notes. It never tags, publishes, merges or changes a setting without the release manager's explicit go |

## Running it with the agent

The agent is `.claude/agents/release-manager.md`. Claude Code loads it from this repository's
checkout; `/agents` lists it.

**What you need:**
- a checkout of this repository, up to date with `origin`;
- Claude Code;
- `gh` logged in as the release manager, the account allowed to create release branches and tags;
- the one-time setup below done, the rulesets in particular. The agent's "never without a go" is
  an instruction to a model; the rulesets are what actually stop a tag nobody approved;
- Docker running, for the upgrade rehearsal and the fresh install;
- the project's virtual environment, for the tests.

**Start it as the session itself**, from the root of the checkout:

```bash
claude --agent release-manager
```

The whole session is then the agent:
- It reads this page first, every time.
- It tells you where the release stands (the milestone, the branches, the tags, the tracking issue) and what comes next.
- It speaks to you in the language you write in, and writes everything on GitHub in English.

**Ask in plain words.** For example:

| phase | ask |
|---|---|
| before the cut | "Audit milestone 0.5.0 for the cut on Friday." / "Draft the release notes for 0.5.0." |
| the cut | "Cut release/0.5." |
| a candidate | "Prepare 0.5.0-rc.1." / "Verify v0.5.0-rc.1." |
| fixes | "Backport the pull requests labelled backport-0.5." |
| the final release | "Prepare the final 0.5.0." |

**The go.** Before every step that cannot be undone (a branch, a tag, a merge, a publication, a
setting), the agent stops. It says what it will do, on which commit or name, and which checks are
green, and then waits.
- **Answer "go" (or "pode seguir")** to approve that one step. Anything else is a no.
- **A go covers one step.** The agent asks again for the next.

**Picking up later.** The agent writes every result into the release tracking issue. A new session,
yours or the next release manager's, reads the issue and continues from it.

**From an ordinary session**, mention the agent at the start of a request, followed by what you want
done, in plain words:

```
@agent-release-manager audit milestone 0.5.0 for the cut on Friday
```

That runs it as a subagent. A subagent works to the end and returns a report; it cannot wait for
an answer. Use it for the reversible work: an audit, the notes, the backport pull requests. For
anything that needs a go, start `claude --agent release-manager`, or take the step by hand.

**Without Claude Code,** this page is the whole process: every step has its command.

## The model, in one picture

```
main         ──●──●──●──●──●──●──●──●──●──►   every pull request merges here, always
                    \          ↑ cherry-pick (fixes only)
release/0.5          ●───●─────●────●──────►   cut at the freeze; receives only backported fixes
                         │          │
                   v0.5.0-rc.1    v0.5.0      (then v0.5.1, v0.5.2… from the same branch)
```

- **`main` is where all work lands.** Every pull request targets `main`. The milestone on a pull
  request says which version it may ship in.
- **A release branch per minor line** (`release/0.5`), cut from `main` on the freeze date. It is
  a snapshot of `main` that then receives only the fixes the release manager chooses to backport.
  Every release of the line is tagged on it: the candidates, `v0.5.0`, and every `v0.5.x`.
- **A fix lands on `main` first, then is copied to the release branch.** Never the other way
  round: a fix made on the release branch and "merged back later" is how the next version ships
  the bug the previous patch fixed. The exception, rare, is a fix to code `main` no longer has;
  that one goes straight to the release branch, and its pull request says why.
- **There is no long-lived development branch beside `main`.** Work for the next version that is
  ready before the cut waits in its open pull request (milestone `0.6.0`) and merges right after
  the cut. Large work that would rot waiting can merge earlier behind a setting that is off by
  default, and the pull request says so.

## Versions

- **`x.y.z`, pre-1.0 semver.** A minor (`0.5.0`) carries features and changes of behaviour. A patch
  (`0.5.1`) carries fixes only, and is always tagged on `release/x.y`, never on `main`.
- **A release candidate is `vx.y.z-rc.N`.** It is published like a release (images, wheel, GitHub
  release), but as a pre-release: `install.sh` and an install of the wheel from PyPI keep
  resolving the last final release, and only somebody who names the candidate gets it
  (`install.sh --version v0.5.0-rc.1`, or the wheel's exact version `0.5.0rc1`). A minor always goes
  through at least one candidate. A patch may skip it, at the release manager's call.
- **The package declares exactly the tag without its `v`.** `pyproject.toml` and
  `openfactory/__init__.py` say `0.5.0-rc.1` for the tag `v0.5.0-rc.1` (PyPI normalises it to
  `0.5.0rc1`). The release workflow refuses a tag whose version the package does not declare.
- **The final release is tagged on the commit the last candidate was verified on**, plus the one
  commit that declares the final version. Nothing else changes between the last candidate and the
  release: what everybody installs is what was tested.
- **After the cut, `main` declares the next minor's development version** (`0.6.0.dev0`), so a
  build of `main` never claims to be a release it is not.

## Rules that do not bend

1. **A published release is frozen.** Never move, delete or re-push a tag, never re-publish an
   image under a released tag, never edit a released wheel. What a release lacks is a new patch,
   tracked as an issue on the next milestone.
2. **Rehearse the upgrade before every tag**, candidate or final (below), on the commit being
   tagged. A final release whose only change since its last verified candidate is the version line
   carries that candidate's rehearsal, recorded again for the final. Anything else is rehearsed
   again. It caught #363 before `v0.4.0`: an upgrade that emptied every credential, which two
   tests had pinned as the contract.
3. **A security defect never becomes a public issue or an ordinary pull request.** It follows the
   private advisory path (below). Release first, publish the advisory second.
4. **Only the release manager creates a release branch or a tag**, and only after the checks of
   that phase are green.
5. **The suite runs with a temporary `HOME`** on every machine that holds a real `gh` login: a
   test once posted 31 comments to a real issue through the operator's credentials (#488).

## The cycle

A cycle is **three weeks** by default. The release manager sets the **release date** as the **due
date of the milestone** when the milestone opens, so the date is visible next to the scope. The cut
comes before it, **two days before by default**, so the first candidate is tested for that long
before the final (section 4). What is merged on `main` by the cut ships; what is not moves to the
next milestone and ships in the next train, without holding this one. A `release-blocker` label marks the few issues the cut waits for; the
release manager decides what earns it.

### 1. Before the cut (the last days of the cycle)

- Audit the milestone: open issues, open pull requests, their review state, and every
  `release-blocker`. The agent produces this list.
- The release manager decides, item by item, what still goes in and what moves to the next
  milestone. Moving an item is a milestone change on the issue or pull request, with one line
  saying why.
- Draft the release notes from the merged pull requests of the milestone, grouped by what a reader
  installing it would notice. The draft lives in the release tracking issue.

**Exit:** no open `release-blocker`, and `main`'s CI is green on the commit to be cut.

### 2. The cut

1. **Open the release tracking issue**, `Release x.y.0`, from the template at the end of this page.
2. **Create `release/x.y` from the green commit of `main`** (release manager's go):
   `git push origin <sha>:refs/heads/release/x.y`.
3. **On `main`, a pull request declares the next development version**: "The package declares
   x.(y+1).0.dev0".

**Exit:** `release/x.y` exists and is protected by the `release/*` ruleset.

### 3. A release candidate

1. **A pull request on `release/x.y`** declares the candidate's version: "The package declares
   x.y.z-rc.N". The reviewer approves it, and it is squash-merged.
2. **Tag the merge commit** (release manager's go):
   ```bash
   git fetch origin
   git tag -a vx.y.z-rc.N origin/release/x.y -m "OpenFactory x.y.z-rc.N"
   git push origin vx.y.z-rc.N
   ```
3. **Watch the `release` workflow to the end**, then check what it published:
   - the three images, under `ghcr.io/open-factory-digital/openfactory-{worker,sandbox,cli}:vx.y.z-rc.N`;
   - the wheel, as version `x.y.zrcN` on PyPI, with its provenance (the workflow publishes it with
     attestations: the file's page on PyPI shows them);
   - the GitHub release, **marked as a pre-release and not as Latest**, with its assets and `SHA256SUMS`.
4. **Tell whoever will test it how to install it**, with the commands below. The install line the
   workflow writes on the release page installs the latest *final* release, not the candidate.

#### Installing a candidate

Only somebody who names the candidate gets it:

- **A new installation:**
  ```bash
  curl -fsSL https://github.com/Open-Factory-Digital/openfactory-core/releases/download/vx.y.z-rc.N/install.sh -o install.sh
  sh install.sh --version vx.y.z-rc.N
  ```
  This is the candidate's own installer, the one `SHA256SUMS` lists.
- **Upgrading an existing installation**, such as a staging box:
  ```bash
  sh install.sh --version vx.y.z-rc.N --dir <the installation's directory> --force
  ```
  - `--force` keeps every value in the installation's `.env.compose` and moves only its pinned
    version.
  - Without `--no-run`, the installer starts the stack on the candidate's images.
- **The wheel:** `pip install openfactory==x.y.zrcN`, PyPI's spelling of the candidate. A plain
  `pip install openfactory` keeps resolving the last final release.
- **Back to the last final release:** the same upgrade command with that release's tag. This
  direction is **not rehearsed**: what the candidate wrote stays where it is. Take a backup of the
  installation before trying a candidate on it.

### 4. Verifying a candidate

Every item below is run against the published candidate, and its result is written in the
tracking issue.

- **The upgrade rehearsal**, from the previous final release:
  1. In a scratch directory, write an `.env.compose` with the previous release's published CLI
     (`install.sh --version <previous> --no-run`).
  2. Fill in marker credentials, a moved port and a row added by hand.
  3. Run the candidate's `init --force`, the way `install.sh` runs it.
  4. Apply the installer's pin step, then `docker compose … config` to read the published ports.
  5. Compare before and after: every value kept, the pin moved, the ports where they were.
  6. Remove the images and the directories.

  Never start the stack, and never touch a live installation.
- **A fresh install** with `install.sh --version vx.y.z-rc.N --no-run`.
- **The end-to-end bed** (Playwright over the panel) against the candidate.
- **A real deployment**, when one is available for it (a staging box), at the release manager's
  call.

**How long a candidate is tested.** The first candidate is tested at least until the milestone's
due date, the release date. A later candidate (`rc.N+1`) is tested for at least two days, or until
the due date when that is later. The release manager may lengthen this, and records why in the
tracking issue.

A defect found here is fixed on `main`, backported, and becomes the next candidate (`rc.N+1`).
Nothing is tagged final before the candidate's testing time is over, nor while a defect found in a
candidate is open, unless the release manager records in the tracking issue why it ships anyway
and what the workaround is.

### 5. The final release

1. **A pull request on `release/x.y`** declares `x.y.z`. Its body carries the release notes as
   they will be published.
2. **Rehearse the upgrade on that commit**, as rule 2 says: when only the version line changed
   since the last verified candidate, record that candidate's rehearsal for the final.
3. **Tag `vx.y.z` on the merge commit** (release manager's go), the same commands as for a
   candidate.
4. **Check the publication**, as for a candidate. This time the GitHub release is **Latest**.
5. **Replace the generated notes on the GitHub release with the curated ones.** The install block
   and the image list the workflow writes stay.
6. **Close the milestone.** Open the next one, if it is not open, with its due date.
7. **Close the tracking issue.**

### 6. Patch releases

- A merged fix that the line needs gets the label `backport-x.y`.
- **Backporting a fix:**
  1. Branch from `release/x.y`.
  2. `git cherry-pick -x <the squash commit on main>`.
  3. Open a pull request into `release/x.y` titled `[x.y] <the original title> (#<original>)`, with a
     body that links the original and names any conflict resolved.

  The agent prepares these; the reviewer approves them like any other pull request.
- A patch release is then steps 3–5 with `z+1`. Its candidate is optional, and its rehearsal is not.
- **Which lines get patches:** the latest minor line. The line before it gets security fixes only,
  and only when the release manager decides so.

### 7. A security release

The repository is public, and `SECURITY.md` forbids public reports, so a security fix never travels
as an issue or an ordinary pull request:

1. **Open a draft advisory.** It is private.
2. **Open the advisory's temporary private fork** and add the reviewer as a collaborator.
3. **Put the fix there:** one pull request into `main`, and one into each `release/x.y` that
   receives it.
4. **Request the CVE.** The number is assigned after the advisory is published.
5. **Merge from the advisory page.** A repository admin's "merge and bypass branch protections" is
   scoped to that merge. Never add a bypass actor to a ruleset.
6. **Release the patch**, steps 3–5 above. Until the advisory is published, every result of
   those steps (the rehearsal, the checks, the decisions) is written in the **advisory**, which is
   private, and not in a public tracking issue. The tracking issue gets them when the advisory is
   published.
7. **Only then publish the advisory.** Publishing before an installable fix exists teaches the
   flaw to people who cannot yet protect themselves.

### 8. When a release goes wrong

- **A tag whose run failed half way** (images pushed, the wheel not, or the reverse): the version
  is burned. Never re-push the tag or re-publish under it. Fix on `main`, backport, and tag the
  next candidate or patch.
- **A wheel published wrong:** yank it on PyPI (it stays installable by its exact version, and
  stops being chosen), and release the next patch. PyPI never replaces a published file.
- **A release that ships a defect:** it is the next patch's, tracked as an issue on the next
  milestone (rule 1).

## One-time setup (done once per repository, by an admin)

- **A ruleset on `release/*`**: no deletion, no force-push, and changes only through a reviewed
  pull request, merged by squash. Creating a `release/*` branch is restricted to the release
  manager and the deputy, not forbidden, or the cut itself is blocked.
  - **No "Require linear history" rule.** GitHub checks it over the whole history of a branch being
    created. `main`'s history holds one merge commit, `dd8072e` (#1, from before `main` had the
    rule), so that rule refused the cut of `release/0.5` and would refuse every later one.
    Squash-only merges keep the line linear without it.
- **A tag ruleset on `v*`:** creation restricted to the release manager and the deputy; update
  and deletion forbidden to everybody (a published release is frozen).
- **The labels** `release-blocker` and `backport-x.y` (one per supported line).

## The release tracking issue

Opened at the cut for a minor (`Release x.y.0`), and for every patch when its first backport is
labelled (`Release x.y.z`), on the release's milestone:

```markdown
- [ ] Milestone audited; everything left moved or marked `release-blocker`
- [ ] `release/x.y` cut from <sha> (main's CI green on it)
- [ ] `main` declares x.(y+1).0.dev0 (#…)
- [ ] rc.1 declared (#…), tagged, published as a pre-release
- [ ] Upgrade rehearsal from v<previous>: <result>
- [ ] Fresh install of the candidate: <result>
- [ ] End-to-end bed against the candidate: <result>
- [ ] Candidate tested until <date>, and no defect found in a candidate is open
- [ ] Final version declared (#…) with the release notes
- [ ] vx.y.z tagged, published, Latest; curated notes on the release page
- [ ] Milestone closed; next milestone open with its due date
```
