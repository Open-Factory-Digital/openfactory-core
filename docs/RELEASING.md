# Releasing OpenFactory

How a version of OpenFactory goes from `main` to the people who install it. It is written for the
**release manager**: whoever holds that role follows this page, by hand or through the
`release-manager` agent (`.claude/agents/release-manager.md`), which executes it step by step and
stops before every step that cannot be undone.

## The whole process in five minutes

A version reaches the people who install it in five moments. 0.5.0 is the example, with its real
dates.

| when | what happens | who | what it means |
|---|---|---|---|
| **the cycle** (one week) | Pull requests merge into `main`, each with the milestone of the version it ships in (`0.5.0`), and each with the line the release notes will read for it (a **fragment**). | everybody; the reviewer approves the change and its line | The milestone is the list of what the version will contain, and its **due date is the release date** (2026-10-07). |
| **the cut** (2026-10-05, two days before) | `release/0.5` is created from a green commit of `main`, and `main` starts declaring `0.6.0.dev0`. | the release manager | The content of 0.5.0 is now **frozen**. New work keeps merging into `main`, for 0.6.0. Only fixes reach `release/0.5`, copied from `main`. |
| **a candidate** (2026-10-05) | `v0.5.0-rc.1` is tagged on `release/0.5` and published **as a pre-release**. | the release manager tags it; the reviewer approves its version pull request | A real release, with images and a wheel, that **only somebody who names it** installs. Everything that resolves "the newest version" (the one-line install, `install.sh` without `--version`, an install of the wheel without a version, the `:0.5` and `:0` images) keeps giving the last final release, so nobody gets a candidate by accident. |
| **testing** (2026-10-05 → 2026-10-07) | The candidate is installed and used: the upgrade rehearsal, a fresh install, the end-to-end bed, and a real deployment. | the release manager, and whoever tests it | A defect found here is fixed on `main`, copied to `release/0.5`, and becomes `v0.5.0-rc.2`, whose testing starts again. |
| **the final** (2026-10-07) | `v0.5.0` is tagged on the last candidate plus the one commit that declares `0.5.0` and assembles its notes, and becomes **Latest**. | the release manager | What everybody installs is exactly what was tested, and its notes are in `CHANGELOG.md` and on its page. Later fixes become `v0.5.1`, `v0.5.2`… from the same branch. |

Every step that cannot be undone (a branch, a tag, a merge, a publication, a setting) waits for the
release manager's explicit **go**. Every result is written in the release's **tracking issue**
(`Release 0.5.0`), so anybody can see where the release stands and pick it up from there.

### The words this page uses

| word | meaning |
|---|---|
| **milestone** | The GitHub milestone named after the version (`0.5.0`): what the version contains, and its due date, the release date. |
| **the cut**, **the freeze** | The moment the release branch is created from `main`. After it, the version's content changes only by a fix copied from `main`. |
| **release branch** | `release/x.y`, one per minor line (`release/0.5`). Every release of the line is tagged on it: the candidates, `v0.5.0`, `v0.5.1`… |
| **candidate**, **rc** | `vx.y.z-rc.N`, a release published so it can be tested before the final. It is a **pre-release** on GitHub, `0.5.0rcN` on PyPI, and is installed only by naming it. |
| **final** | `vx.y.z`, the release everybody installs. On GitHub it is **Latest**. |
| **Latest** | The GitHub release that "the newest version" resolves to: the one-line install, `install.sh` without `--version`, and the site's installer. Never a candidate. |
| **floating tag** | An image tag that moves to each new final release: `:0.5` (the line) and `:0`. A candidate moves neither. `:latest` is no longer published: it stays on v0.4.2's images for ever, so pin a version instead. |
| **backport** | Copying a fix merged on `main` to the release branch, with `git cherry-pick -x`, in a pull request of its own. |
| **fragment** | A file a pull request adds, `changes/<issue>.<type>.md`, holding the line the release notes will read for it. At the final release the fragments are assembled into `CHANGELOG.md` and the release page, and removed. |
| **the go** | The release manager's explicit approval of one step that cannot be undone. A go covers that step only. |
| **tracking issue** | The issue `Release x.y.z`: the checklist of this page, with the result of every step. |
| **ruleset** | A GitHub rule on branches or tags (`release/*`, `v*`) that enforces what this page says, whoever runs it. |

## Roles

| role | who, today | what they decide or do |
|---|---|---|
| release manager | @robertocsp | the cut date, what goes in, every tag, the go/no-go for each release |
| reviewer | @hermesfelipe | reviews every pull request, the version and backport pull requests included |
| deputy release manager | @hermesfelipe | takes the role when the release manager cannot: the `v*` ruleset lists both, so a release never waits on one person |
| release agent | `release-manager` | audits, prepares the pull requests, runs the rehearsals, previews and assembles the notes. It never tags, publishes, merges or changes a setting without the release manager's explicit go |

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
| before the cut | "Audit milestone 0.6.0 for Monday's cut." / "Preview the release notes of 0.6.0." |
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
@agent-release-manager audit milestone 0.6.0 for Monday's cut
```

That runs it as a subagent. A subagent works to the end and returns a report; it cannot wait for
an answer. Use it for the reversible work: an audit, the notes' preview, the backport pull
requests. For anything that needs a go, start `claude --agent release-manager`, or take the step
by hand.

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
  commit that declares the final version and assembles its notes. Nothing else changes between the
  last candidate and the release: what everybody installs is what was tested.
- **After the cut, `main` declares the next minor's development version** (`0.6.0.dev0`), so a
  build of `main` never claims to be a release it is not.

## The release notes

**Every pull request carries the line the release notes will read for it**, and nobody drafts the
notes at the cut. The line is written by whoever knows the change, the reviewer reads it beside the
code it describes, and the release only assembles the lines, by a command.

**A fragment** is the file that holds the line: `changes/<issue>.<type>.md`.
- `<issue>` is the number of the issue the pull request closes, or of the pull request itself when
  it closes none. A security fix uses its advisory's id (`GHSA-xxxx-xxxx-xxxx`).
- `<type>` is the group of the notes a reader looks in:

  | type | heading on the page | for |
  |---|---|---|
  | `highlight` | Highlights | one of the few changes a reader should hear about first; instead of a `behaviour` line, not beside it |
  | `behaviour` | New behaviour | what the product does that it did not do, or does differently |
  | `fix` | Fixes | a defect that no longer happens |
  | `security` | Security | a vulnerability fixed |
  | `upgrade` | Upgrade notes | what an existing installation must do, or will notice, when it upgrades |
  | `limitation` | Known limitations | what does not work yet in this release, and the workaround |

- The text is the line in Markdown, as somebody installing the release should read it, **one
  sentence or paragraph per line** (a release page shows a line break inside a paragraph as a
  break), with `- ` sub-items for detail. It does not carry its number: the assembly adds
  `(#<issue>)` from the file name.
- One pull request may carry several fragments, of different types or for different issues.

**The check `release-note`** (`.github/workflows/release-note.yml`) runs on every pull request, and
again when its labels change. It fails when the pull request adds or edits no fragment and does not
carry the label `no-release-note`, and it names every fragment that is malformed.

**The label `no-release-note`** exempts a pull request that changes nothing a reader of the notes
would notice: documents only, tests only, and the release's own pull requests (a version, the
notes brought back to `main`). It is visible to the reviewer, who can question it.

**`CHANGELOG.md`**, at the root of the repository, holds every version's notes, newest first, from
0.6.0 on. The notes of earlier versions are on their GitHub release pages.

**The commands**, run from the root of a checkout. `scripts/release_notes.py` uses Python's
standard library only:

| command | when | what it does |
|---|---|---|
| `python3 scripts/release_notes.py preview x.y.z` | before the cut, or any time | prints the notes the fragments make now; changes nothing |
| `python3 scripts/release_notes.py assemble x.y.z --date <the release date>` | in the final's version pull request | writes the version's section at the top of `CHANGELOG.md`, removes the fragments it used, and prints the notes the release page will carry |
| `sh scripts/release-page-body.sh vx.y.z` | to read a release's page before tagging it | prints how to install it, its images, and its notes (`python3 scripts/release_notes.py page vx.y.z`): a final's section of `CHANGELOG.md`, or a candidate's fragments so far |
| `python3 scripts/release_notes.py check` | CI, on every pull request | the check above |

## Rules that do not bend

1. **A published release is frozen.** Never move, delete or re-push a tag, never re-publish an
   image under a released tag, never edit a released wheel. What a release lacks is a new patch,
   tracked as an issue on the next milestone.
2. **Rehearse the upgrade before every tag**, candidate or final (below), on the commit being
   tagged. A final release whose only change since its last verified candidate is the version line
   and its notes carries that candidate's rehearsal, recorded again for the final. Anything else is
   rehearsed again. It caught #363 before `v0.4.0`: an upgrade that emptied every credential,
   which two tests had pinned as the contract.
3. **A security defect never becomes a public issue or an ordinary pull request.** It follows the
   private advisory path (below). Release first, publish the advisory second.
4. **Only the release manager creates a release branch or a tag**, and only after the checks of
   that phase are green.
5. **The suite runs with a temporary `HOME`** on every machine that holds a real `gh` login: a
   test once posted 31 comments to a real issue through the operator's credentials (#488).

## The cycle

**One release a week**, decided by the release manager on 2026-10-05:

```
Monday     the cut: release/x.y from a green main, and its first candidate (rc.1)
Mon → Wed  the candidate is tested
Wednesday  the final, when nothing found in a candidate is open
```

| version | cut and rc.1 | final |
|---|---|---|
| 0.5.0 | Monday 2026-10-05 | Wednesday 2026-10-07 |
| 0.6.0 | Monday 2026-10-12 | Wednesday 2026-10-14 |
| 0.7.0 | Monday 2026-10-19 | Wednesday 2026-10-21 |

- **The milestone's due date is the release date**, the Wednesday, set when the milestone opens, so
  the date is visible next to the scope.
- **The cut comes two days before it**, so the first candidate is tested for that long (section 4).
- **It is a train.** What is merged on `main` by Monday's cut ships that Wednesday. What is not
  moves to the next milestone and ships the week after, without holding this one.
- **`main` never stops.** Between the cut and the final, new work keeps merging into `main` for the
  next version; only fixes reach the release branch.
- A `release-blocker` label marks the few issues the cut waits for; the release manager decides
  what earns it.

### 1. Before the cut (the days before Monday's cut)

- Audit the milestone: open issues, open pull requests, their review state, and every
  `release-blocker`. The agent produces this list.
- The release manager decides, item by item, what still goes in and what moves to the next
  milestone. Moving an item is a milestone change on the issue or pull request, with one line
  saying why.
- **Read the notes as they stand**, assembled from the fragments on `main`, and put them in the
  release tracking issue:
  ```bash
  python3 scripts/release_notes.py preview x.y.0
  ```
  It changes nothing. A line that reads wrong is corrected by a pull request that edits its
  fragment, reviewed like any other; the notes are never rewritten by hand in the issue.
- **Every merged pull request of the milestone carries a fragment or the label `no-release-note`.**
  The audit lists those that carry neither, and each gets its fragment in a small pull request, or
  the label.

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
4. **Check that the release page says how to install the candidate**, with the commands below,
   and carries the notes so far, from the fragments on the branch. The workflow writes both
   (`scripts/release-page-body.sh`, #531, #517). A release line cut before the first of those
   changes, such as 0.5, prints the one-line install on a candidate's page, which installs the
   last *final* release. On such a line, the release manager replaces the page's install block by
   hand with the commands below, as was done for `v0.5.0-rc.1`, or backports
   `scripts/release-page-body.sh`, `scripts/release_notes.py` and its workflow step with the fixes
   of the line's next candidate.
5. **Tell whoever will test it** where the release page is, and to report what they find in the
   tracking issue.

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
- **The wheel**, when the release published it to PyPI (its page says so): its exact version,
  `pip install openfactory==x.y.zrcN`, PyPI's spelling of the candidate. An install of the wheel
  without a version keeps resolving the last final release.
- **Back to the last final release:** restore the backup taken before the upgrade (below). Running
  the upgrade command again with the older tag is **not rehearsed**: what the candidate wrote would
  stay where it is.

#### Backing up an installation before a candidate

Going back from a candidate is not rehearsed, so a test on an installation somebody relies on
starts with a backup, and an installation that misbehaves goes back by restoring it. An
installation is everything `docker-compose.yml` mounts that the stack writes, and the two files
beside it:
- **the files**, `.env.compose` and `docker-compose.yml`. The installer replaces
  `docker-compose.yml` with the candidate's, so both are kept;
- **the Docker volumes**, which Compose names `openfactory_<volume>` because `docker-compose.yml`
  says `name: openfactory` (so the volume `openfactory_state` is `openfactory_openfactory_state`);
- **two directories of the host**, which `.env.compose` names:
  - `OPENFACTORY_WORK_DIR`, a job's files while it runs (unset: `/var/lib/openfactory-work`);
  - `OPENFACTORY_REPOS_DIR`, the working clones the worker and the panel share (unset:
    `$HOME/openfactory/repos`).

`OPENFACTORY_GUIDELINES_DIR` is mounted read-only: the stack never writes it, so it needs no
backup. `tests/test_a_backup_covers_everything_the_stack_writes.py` holds this list to
`docker-compose.yml`, so a mount added there fails the suite until this section names it.

**The backup**, from the installation's directory:

```bash
docker compose --env-file .env.compose stop      # nothing writes while the copy is taken
cp -p .env.compose .env.compose.backup
cp -p docker-compose.yml docker-compose.yml.backup
for v in temporal_db openfactory_state openfactory_toolbox openfactory_repos openfactory_logs; do
  docker run --rm -v "openfactory_$v:/v:ro" -v "$PWD:/b" busybox tar czf "/b/backup-$v.tgz" -C /v .
done
setting() { v=$(sed -n "s/^$1=//p" .env.compose | tail -n 1 | tr -d "\"'"); echo "${v:-$2}"; }
WORK=$(setting OPENFACTORY_WORK_DIR /var/lib/openfactory-work)
REPOS=$(setting OPENFACTORY_REPOS_DIR "$HOME/openfactory/repos")
tar czf backup-work-dir.tgz -C "$WORK" .
tar czf backup-repos-dir.tgz -C "$REPOS" .
docker compose --env-file .env.compose start
```

**Going back**, if the candidate has to be left:

```bash
docker compose --env-file .env.compose down       # stops it; the volumes stay
cp -p .env.compose.backup .env.compose            # as it was, with the previous pin
cp -p docker-compose.yml.backup docker-compose.yml
for v in temporal_db openfactory_state openfactory_toolbox openfactory_repos openfactory_logs; do
  docker run --rm -v "openfactory_$v:/v" -v "$PWD:/b" busybox \
    sh -c "cd /v && find . -mindepth 1 -delete && tar xzf /b/backup-$v.tgz"
done
setting() { v=$(sed -n "s/^$1=//p" .env.compose | tail -n 1 | tr -d "\"'"); echo "${v:-$2}"; }
WORK=$(setting OPENFACTORY_WORK_DIR /var/lib/openfactory-work)
REPOS=$(setting OPENFACTORY_REPOS_DIR "$HOME/openfactory/repos")
(cd "$WORK" && find . -mindepth 1 -delete) && tar xzf backup-work-dir.tgz -C "$WORK"
(cd "$REPOS" && find . -mindepth 1 -delete) && tar xzf backup-repos-dir.tgz -C "$REPOS"
docker compose --env-file .env.compose up -d
```

- The restored files pin the previous release and describe its stack, so `up -d` runs it again.
- A directory created by root (the old `/var/lib/openfactory-work` default) is read and written
  with `sudo`.
- The commands were checked on 2026-10-05 on scratch copies: a volume, and the two directories
  read from an `.env.compose` that sets one and leaves the other to its default. The checks
  covered a hidden file, a changed file and a new file. They have not been run on a whole
  installation.

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

1. **A pull request on `release/x.y` declares `x.y.z` and assembles its notes**, in one commit:
   the version line, as for a candidate, and
   ```bash
   python3 scripts/release_notes.py assemble x.y.z --date <the release date>
   ```
   - It writes the section `## x.y.z (<the release date>)` at the top of `CHANGELOG.md`, and
     removes from `changes/` the fragments it used.
   - It prints the notes as the release page will carry them. They are the pull request's body.
   - The pull request carries the label `no-release-note`: its notes are the fragments'.
   - The check `release-note` refuses a final version whose notes are not in `CHANGELOG.md`, or
     whose pull request leaves a fragment behind.
2. **Rehearse the upgrade on that commit**, as rule 2 says: when only the version line and the
   notes changed since the last verified candidate, record that candidate's rehearsal for the
   final.
3. **Tag `vx.y.z` on the merge commit** (release manager's go), the same commands as for a
   candidate.
4. **Check the publication**, as for a candidate. This time:
   - the GitHub release is **Latest**;
   - the floating image tags `:x.y` and `:x` point at this release's images, and `:latest` has not moved (it is no longer published);
   - **the site serves this release's installer.** In the `openfactory-website` repository, run
     Actions → installer → Run workflow (it also runs every hour). Then check that
     `curl -fsSL https://openfactory.digital/install.sh | sha256sum` equals the `install.sh` line
     of this release's `SHA256SUMS`.
5. **Check that the release page carries the notes**, under the install block and the image
   list. The workflow writes them from `CHANGELOG.md`; GitHub's list of the merged pull requests
   follows them.
6. **Bring the notes back to `main`**, in a pull request titled "The notes of x.y.z reach main",
   with the label `no-release-note`:
   ```bash
   git switch -c notes/x.y.z origin/main
   git diff vx.y.z^ vx.y.z -- CHANGELOG.md changes/ | git apply --3way
   git commit -m "The notes of x.y.z reach main"
   ```
   - It applies to `main` what the final's commit did to the notes: the new section of
     `CHANGELOG.md`, and the removal of the fragments it used, so the next version's notes do
     not list them again.
   - On a patch of an older line than `main`'s, `CHANGELOG.md` may conflict: keep both sections,
     the newest version first.
7. **Close the milestone.** Open the next one, if it is not open, with its due date.
8. **Close the tracking issue.**

### 6. Patch releases

- A merged fix that the line needs gets the label `backport-x.y`.
- **Backporting a fix:**
  1. Branch from `release/x.y`.
  2. `git cherry-pick -x <the squash commit on main>`.
  3. Open a pull request into `release/x.y` titled `[x.y] <the original title> (#<original>)`, with a
     body that links the original and names any conflict resolved.

  The agent prepares these; the reviewer approves them like any other pull request. The
  cherry-pick carries the original's fragment, so the fix's line reaches the patch's notes.
- A patch release is then steps 3–5 with `z+1`, its notes assembled the same way. Its candidate is
  optional, and its rehearsal is not.
- **Which lines get patches:** the latest minor line. The line before it gets security fixes only,
  and only when the release manager decides so.

### 7. A security release

The repository is public, and `SECURITY.md` forbids public reports, so a security fix never travels
as an issue or an ordinary pull request:

1. **Open a draft advisory.** It is private.
2. **Open the advisory's temporary private fork** and add the reviewer as a collaborator.
3. **Put the fix there:** one pull request into `main`, and one into each `release/x.y` that
   receives it. Its fragment is `changes/GHSA-xxxx-xxxx-xxxx.security.md`, named by the advisory.
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
- **The labels** `release-blocker`, `backport-x.y` (one per supported line), and
  `no-release-note`, which exempts a pull request from the release-note check.
- **The check `release-note` as a required status check** of `main`'s ruleset, if the release
  manager wants a pull request without its line to be unable to merge. Without it, the check
  still says which pull request lacks one, and the audit before the cut catches what merged red.

## The release tracking issue

Opened at the cut for a minor (`Release x.y.0`), and for every patch when its first backport is
labelled (`Release x.y.z`), on the release's milestone:

```markdown
- [ ] Milestone audited; everything left moved or marked `release-blocker`
- [ ] Notes previewed from the fragments; every merged pull request carries one or `no-release-note`
- [ ] `release/x.y` cut from <sha> (main's CI green on it)
- [ ] `main` declares x.(y+1).0.dev0 (#…)
- [ ] rc.1 declared (#…), tagged, published as a pre-release
- [ ] Upgrade rehearsal from v<previous>: <result>
- [ ] Fresh install of the candidate: <result>
- [ ] End-to-end bed against the candidate: <result>
- [ ] Candidate tested until <date>, and no defect found in a candidate is open
- [ ] Final version declared and its notes assembled into `CHANGELOG.md` (#…)
- [ ] vx.y.z tagged, published, Latest; its notes on the release page
- [ ] The notes of x.y.z reached main (#…)
- [ ] The site serves vx.y.z's installer (sha256 matches its SHA256SUMS)
- [ ] Milestone closed; next milestone open with its due date
```
