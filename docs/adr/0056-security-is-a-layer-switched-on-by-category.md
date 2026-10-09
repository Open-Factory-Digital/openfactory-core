# ADR 0056 — Security is a layer switched on by category: a change is blocked only by what it introduced, the running product is probed in its preview, and what ran is evidence

- **Status:** Proposed (design only — no code changes with this ADR; the slices below implement it)
- **Date:** 2026-10-09
- **Milestone:** 0.7.0, where it is discussed. When each slice is built is decided there; nothing
  here is scheduled by this record.
- **Relates to:**
  - ADR-0001 D-2, the floor: a project may add to what the platform guarantees and never subtract.
  - ADR-0005: deploys are the client's pipeline; the platform observes.
  - ADR-0011: a diff that adds a gate suppression goes to a person.
  - ADR-0014: the LLM review informs and does not gate; the deterministic gates are the floor.
  - ADR-0037: the box is the client's image plus an injected, pinned toolbox, proven before pickup.
  - ADR-0044: a profile promotes a gate that already runs; it never invents one.
  - ADR-0050: the preview, the only place the product runs before the merge (D2, D6, D7, D9).
  - ADR-0055 D4: the card's one record of what happened.
  - Issues: #569 (this record and its slices); #356 (`openfactory certify`, the evidence pack).

## Context

### What the platform already has

More than "no SAST" suggests. Every piece below is in the tree at `a72fe22`, except the last,
which is in an open pull request (#549):

| Piece | Where | What it does |
|---|---|---|
| A `security` gate is required | `policy/floor.py::REQUIRED_VALIDATION_ROLES` | a project with no `security` role is refused before any agent pass |
| The deployment's default `security` gate | `org_defaults/floor.yaml` | a `git grep` for unambiguous credential formats in tracked files, advisory |
| Stack presets | `presets/python.yaml` (`bandit`), `presets/terraform.yaml` (`tfsec`), `presets/security-oss.yaml` (`semgrep`, `trivy fs`) | a command per role, attached to a component's `stack` |
| The starter manifest | `cli.py`, the `project init` template | a repo-wide `semgrep --config=auto`, advisory |
| `advisory` per gate | `contracts/manifest.py::Gate`, `orchestrator/machine.py::_all_passed` | advisory: ⚠️ in the PR body, never blocks, never repairs. Blocking: the job fails and the gate's output goes to the executor's repair pass (`_gates_brief`), then the card is held |
| Profile promotion | `org_defaults/profiles/regulated.yaml`, `contracts/profile.py::RiskPolicy` | `regulated` makes `security` blocking at every risk level and sends high risk to a person |
| The agent cannot retune its own gates | `org_defaults/floor.yaml`, `protected_paths: .openfactory/**` | a change to the manifest goes to a person |
| Added suppressions go to a person | `orchestrator/machine.py::_SUPPRESSION_RE` (ADR-0011) | a diff that adds `nosec`, `noqa`, `type: ignore`, `pragma: no cover` never auto-merges |
| The box is proven | `box_prove.py`, the `validate` station | every repo-wide gate runs on untouched `main`; a blocking one must exit 0, an advisory one is a warning (#11) |
| Evidence | #356 (#549), control `C-SECURITY` | records that every repository has a security gate, declared or inherited |

### The shape that limits it

Security is **one gate role**, `security`, holding **one command**, judged by **its exit code over
the whole tree**. `applicable_validations` builds a map keyed by role, so a diff gets exactly one
`security` command: the component's preset if the diff reaches a component, else the project's
repo-wide one, else the deployment's. Everything below follows from that shape.

### Where it shows

1. **The whole tree, never the change.** An exit code over the tree answers "is there a finding in
   this repository", not "did this change add one". On any real codebase the first answer is yes,
   so every security gate the platform ships is advisory — the preset and the floor say so in their
   own comments — and an advisory finding never reaches the repair pass. **The agent is never asked
   to fix a vulnerability it has just written.** Blocking does not help: `box prove` runs every
   repo-wide gate on untouched `main` and requires exit 0 from a blocking one, so one old finding
   holds pickup for every card on that repository.
2. **One role, so the categories replace each other.** Secrets, code, dependencies, infrastructure
   and images are different questions with different remedies (*"a CVE in a transitive dependency
   is not a code change"*, `security-oss.yaml`). But a project that declares `security` loses the
   floor's credential scan (*"the project's own value wins, always, and nothing here is merged for
   that role"*, `floor.yaml`), and a diff that reaches a `python` component runs `bandit` as its
   `security` and not the credential scan. The `project init` template declares `security:
   semgrep`, so **every project started from it has no credential scan**, and on an image without
   semgrep — both default images, measured in `floor.yaml` — its one security gate cannot run.
3. **A preset is a stack.** `security-oss` can only attach as a component's `stack`, and a
   component has one stack: it cannot be `python` and `security-oss`. The CLI calls printing it
   *"a remedy that cannot be typed"*. Adopting it is copying commands by hand. Its comment lists
   `gitleaks`; it configures none.
4. **The tools are not in the box.** The floor stayed on `git grep` because the scanners are in
   neither default image, and under ADR-0037 D1 the image is the client's. The toolbox (D2) already
   mounts framework-owned, version-pinned binaries into every box — `gh`, `git`, the harnesses —
   and carries no scanner.
5. **A tool's own suppression is unseen.** `_SUPPRESSION_RE` matches `#`-comment pragmas only. A
   `nosemgrep`, a `NOSONAR`, a `gitleaks:allow`, or an ignore file the change adds
   (`.semgrepignore`, `.trivyignore`) is not detected and is not a protected path.
6. **A dependency the change adds is not read.** An agent can name a package that does not exist,
   and a name that does not exist yet can be registered by whoever is waiting for it. A
   vulnerability database has no entry for either. No gate reads what a diff adds to a dependency
   manifest.
7. **A secret's value travels.** The floor's credential scan prints the matching lines, and
   `_failure_log` hands a failed blocking gate's `output_tail` to the repair pass verbatim. A
   client who makes the credential scan blocking sends the credential to the model provider.
8. **Nothing probes the running product.** Every gate runs in the box over files. The one place
   the product runs before the merge is the preview (ADR-0050), and the preview's minute look
   (D6) is health.
9. **What ran is not evidence.** `C-SECURITY` records that a gate exists; not which tool ran, in
   which mode, what it found, or what was repaired.

## Decision

### D1. Security is a layer of categories, each `off`, `advisory` or `blocking`

The categories are `secrets`, `code`, `dependencies`, `infrastructure`, `image` and `running`. Each
is switched on its own, with the three words `review_mode` already uses:

```yaml
# the deployment's default (org_defaults/security.yaml); a project's .openfactory/project.yaml
# may strengthen any of it
security:
  secrets:        {mode: blocking}
  code:           {mode: blocking}
  dependencies:   {mode: advisory}
  infrastructure: {mode: off}
  image:          {mode: off}
  running:        {mode: advisory}   # D6: against the preview
```

- **The cascade:** the deployment's default, then the project's file (under `.openfactory/**`, so
  a change to it goes to a person), then the profile, then the risk level. A profile and a risk
  level may only promote a category that is on, as `RiskPolicy.gates` does today.
- **The floor:** the deployment may name a minimum per category that no project goes below
  (`secrets` at least `advisory`, everywhere). May add, may not subtract — the rule
  `protected_paths` already follows.
- **Categories never replace each other.** A project that switches `code` on keeps `secrets`;
  a component's stack adds its own tools to a category and removes none.
- **The `security` role the floor requires is filled by the layer**, so `REQUIRED_VALIDATION_ROLES`
  and `C-SECURITY` keep their meaning. A manifest's existing `validate.security` keeps running as it
  does today: the layer adds, it does not reinterpret a file that already exists.

### D2. A tool is a row; the category is the contract

A row names: the category; the command; the output, as SARIF 2.1.0 or through an adapter that
produces it; where the binary comes from (the toolbox or the client's image); the rule set, pinned
or vendored; and the tool's own suppression markers and ignore files.

- **Rules are never fetched at run time.** A rule set that moves under a run makes D3's comparison
  lie, and a fetch needs egress the box may not have.
- **The suppression markers feed ADR-0011's guard, and the ignore files become protected paths**
  (closes 5).
- **Rows ship for free tools.** A client's licensed tool is a row in their deployment. The core
  never branches on a tool's name: a tool it has never heard of works by its row.

### D3. A change is blocked only by what it introduced

- **The comparison:** the category's tool runs on the change, and its findings are compared with
  the base's for the same base commit, tool version and rule set.
- **Matched by fingerprint, never by line number:** SARIF's `partialFingerprints` where the tool
  gives one, the rule and a normalised snippet otherwise.
- **Three sets:** *introduced*, *existing*, *fixed*. `blocking` fails on introduced findings only.
- **Introduced findings go to the repair pass as data,** through the brief and the bounded attempts
  that exist (`_gates_brief`). Existing findings are reported — a count and the first few — and never
  repaired by a job that did not cause them. Fixed findings are reported.
- **`box prove` on untouched `main` records the existing count as information, never a failure.**
  This is what makes `blocking` usable on the first day of a fifteen-year-old repository (closes 1).
- **A suppression or ignore entry the change adds for an introduced finding counts as the
  finding,** and goes to a person (ADR-0011).
- **A secrets finding carries its location and rule, never its value:** not in the brief, the PR
  body, the job log, the card or the evidence (closes 7).

### D4. The scanners ride in the toolbox, and the proof covers every category switched on

- **A self-contained binary goes in the toolbox,** pinned like `gh` and `git` (ADR-0037 D2), so a
  category does not wait on the client rebuilding their image. A tool that needs the client's
  runtime stays in the client's image; the row says which (closes 4).
- **`box prove` runs every category that is not `off` on untouched `main`.** One that cannot run is
  a refusal when `blocking` and a warning when `advisory`, as gates are today.
- **The floor's `secrets` category moves off `git grep` only once a scanner can run in every box,**
  and only after it is measured on the registered repositories, as the `git grep` was.

### D5. A dependency the change adds is read

- **The added names:** the `dependencies` category reads what the diff adds to the dependency
  manifests its row names.
- **Each name is asked** whether it resolves in the registry the project uses, and when it was first
  published.
- **An introduced finding:** a name that does not resolve, or that was first published inside the
  row's window.
- **The PR body lists every added dependency,** whether or not it was a finding (closes 6).

### D6. The running product is probed in its preview

- **When:** `running` runs once per preview build, after the preview's first healthy look (ADR-0050
  D6), never every minute.
- **From where:** from inside the preview's own network. Never through the panel's router (ADR-0050
  D7), and never with a person's key.
- **Passive by default:** it requests the exposed services and reads what they answer (headers,
  cookies, exposed paths, error pages). Active probing, which sends payloads, is a separate setting,
  off by default: it writes to the preview's data and runs long.
- **Introduced or existing:** a finding on a service the change touched (ADR-0050 D2, read from the
  diff) is introduced; the rest are existing.
- **Where results go:** to the card beside the preview link, and to the PR body. `blocking` adds a
  refusal to `orchestrator/merge_policy.py::should_auto_merge`, where every other refusal lives, and
  the person who merges sees it (ADR-0050 D9 already sends a project that requires a preview to a
  person).
- **Staging and production stay the client's pipeline (ADR-0005).** The factory does not probe them
  (closes 8).

### D7. What ran is evidence

- **The record:** each job records, per category — the tool row, its version, the rules' hash, the
  mode, and the counts of introduced, existing, fixed, repaired and suppressed findings. It goes into
  the card's record (ADR-0055 D4) and the PR body's *Validations*.
- **`certify` (#356) reads that record.** `C-SECURITY` moves from "a gate exists" to "the categories
  the profile requires ran, in the required mode, over the window", with the counts. A finding's
  content never enters the pack, under the pack's redaction (closes 9).

## Slices

Tracked on #569, in this order; each one ships on its own:

1. **D3 on the `security` role that exists** — SARIF, the fingerprint comparison, blocking on
   introduced only, the repair brief, `box prove`'s existing count, and the secret's value withheld.
   It is the foundation: without it, every other slice is a ⚠️ nobody reads.
2. **D1 and D2** — the `security:` layer, its cascade, its floor and the rows. `security-oss` stops
   being a stack, the suppression guard reads the rows, and the `project init` template stops
   replacing the credential scan.
3. **D4** — the scanners in the toolbox and the proof per category.
4. **D5** — the added dependencies.
5. **D6** — the preview probe.
6. **D7** — the record and `certify`, after #356 lands.

## Consequences

- **Blocking becomes adoptable,** because a change answers for what it introduced, and the agent
  repairs its own findings in the box before a person sees the pull request.
- **Switching on a code scanner no longer switches off the credential scan.**
- **One place says what a deployment checks, and the evidence pack can show it.**
- **Cost:** two runs per category per job (the change and its base) unless the base's findings are
  kept per base commit; a larger toolbox; an adapter for each tool that writes no SARIF.
- **Fingerprints are a heuristic.** A finding that moved can read as introduced. That costs one
  repair attempt and then a person; it never fails silently in the other direction.
- **`security-oss` retires** into rows.

## Not decided here

- **The default rows and modes.** They are measured on the registered repositories before they
  ship, as the floor's `git grep` was.
- **The base's findings:** kept per base commit, or run beside the change.
- **Licence compliance:** the same shape as a category, with a different owner of the answer.
- **How existing findings become work.** A person asks and the role files the cards; never
  automatically.
- **`image`:** the client's base image, the preview's built images, or both.
- **The factory's own attack surface** — a card's text read as an instruction to the agent, the
  box's egress — is a different record.

## What this does NOT mean

- **OpenFactory does not become a scanner.** It runs the tools a deployment chose and reads what
  they say.
- **It does not replace the client's pipeline.** The client's CI keeps its own scans; the factory's
  gates run before the pull request exists.
- **No vendor enters the core.** A tool is a row.
