# The developer's guide: why the agent was told this, and where you may change it

This page is for whoever reads, configures or bends the platform rather than runs it. It is
**executable**: every command below starting with `$ openfactory` is run by the suite
(`tests/test_the_developer_guide_runs.py`), from the repository's root, and what it prints must
equal the block under it — and every path written in backticks exists in this repository. A
guide about a surface that is meant to change often rots fastest of all, so this one is held to
the rule the rest of the tree is held to: a rule in prose is the weak form, a rule a guard checks
is the strong one.

It is organised by reader, not by feature. Two readers have a door today; two do not yet, and
the last section says what is missing before they do.

| reader | their question | the door |
|---|---|---|
| developer | why did the agent write it this way? | `openfactory explain`, below, and the files it names |
| AI engineer | how do I improve this? | the role prompts, the profiles, the operator's directory, and the one behaviour that is still code |
| architect | are my decisions being complied with? | not yet a door — see the end |
| security engineer | what can the agent do, and what stops it? | not yet a door — see the end |

---

## The developer: why did the agent write it this way?

### One command answers it

`openfactory explain <checkout>` prints every block a planner or executor pass of that project is
handed, one line each, in the order the job inlines them: where each comes from, and what the
project's profile did to it. It reads a checkout on this machine and writes nothing — no harness,
forge or network is called, and no card or registry is touched.

The worked example in `docs/examples/profiled-project` is a small project with a profile and house
rules:

```console
$ openfactory explain docs/examples/profiled-project
```

```text
openfactory explain · docs/examples/profiled-project

  profile   prototype → house-style
              prototype    openfactory/org_defaults/profiles/prototype.yaml — shipped with the package
              house-style  .openfactory/profiles/house-style.yaml — the project's own

What a planner or executor pass is handed, in order (the card is each ticket's own):

  role prompt       planner                          openfactory/org_defaults/roles/planner.md — the package's own; nothing overrides it
  role prompt       executor                         openfactory/org_defaults/roles/executor.md — the package's own; nothing overrides it
  docs.constraints  docs/adr/0001-money-in-cents.md  inlined in full
  framework         engineering.md                   replaced by docs/engineering.md
  framework         tdd.md                           waived by prototype → house-style
  docs.guidelines   HOUSE-RULES.md                   kept
  index             docs/architecture/overview.md    the three modules and which one owns money
  knowledge map                                      on — added per job when a fresh bundle describes its checkout; not read here
```

Under the header, every row is a block of the prompt, in the order the prompt has them:

- **The profile** is the project's declaration of what it IS, and the chain it composes. Here the
  project's own `house-style` extends the shipped `prototype`.
- **The role prompt** comes first in every pass. It has exactly ONE layer: the package's own
  `openfactory/org_defaults/roles/planner.md` (or `executor.md`), or, for a role this package does
  not ship, an add-on's own text. Nothing overrides a shipped one: the deployment overlay
  [ADR-0044](adr/0044-a-project-declares-what-it-is.md) names does not exist yet.
- **`docs.constraints`** — the project's decision records, inlined in full on every pass.
- **framework** — `openfactory/org_defaults/engineering.md` and `openfactory/org_defaults/tdd.md`,
  each with its fate. `prototype` waives `tdd.md`; `house-style` replaces `engineering.md` with
  the project's own (`docs/examples/profiled-project/docs/engineering.md`).
- **`docs.guidelines`** — the project's house rules, last, so the project keeps the last word.
- **index** — `docs.architecture` is not inlined: the agent gets each document's title or
  summary and opens the one it needs.
- **knowledge map** — the module map, added per job when a fresh bundle describes that job's own
  checkout. It is generated, fenced as data, and not read here.

What is NOT printed is the card: the ticket's own words, its plan and any decision a person gave
it are each ticket's own. The brief that carries them is fenced with a random marker drawn per
brief, so it is never the same text twice, and `explain` shows what every ticket of the project
carries instead. `--full` prints each block's text under its line, exactly as the prompt carries
it.

### The cascade, as it is

The issue that asked for this page imagined a chain from the role prompts through a deployment
overlay to the project's profile. That is not what exists, and `explain` prints what exists:

1. **The role prompt** — one layer, as above (`openfactory/adapters/agent/roles.py`).
2. **The constraints** — `docs.constraints`, every file the glob matches, in full.
3. **The guidelines**, in this order (`openfactory/orchestrator/context.py`):
   1. the framework's `openfactory/org_defaults/*.md`, which the project's profile may **waive**,
      **replace** (by filename, with a file of the checkout) or **extend** (with more files of the
      checkout, right after the framework's);
   2. the operator's own directory, `$OPENFACTORY_GUIDELINES_DIR`, on every project of the
      deployment — a profile waives or replaces those by filename too;
   3. the project's `docs.guidelines`, then each component's `components.<name>.guidelines`.
4. **The index** — `docs.architecture`, and the operator's `$OPENFACTORY_GUIDELINES_DIR/reference/`
   documents where the job's box can open them.

**A profile acts on the guidelines and on nothing else in the prompt** — never the role prompt,
the constraints or the index. (Its `risk:` block acts on the merge gate, which is not part of the
prompt.) Profiles resolve across two layers: the shipped examples,
`openfactory/org_defaults/profiles/prototype.yaml` and `regulated.yaml`, and the project's own
`.openfactory/profiles/`, which wins.

Every row `explain` prints is written by the job's own code: `build_context` records each file it
keeps, waives, replaces or refuses while it assembles the context, and `explain` prints that
record. It cannot say one thing while a job does another.

### Where you may touch, and what it changes

| you want | you change | `explain` shows it as |
|---|---|---|
| a house rule for the whole project | a file named in `docs.guidelines` | `docs.guidelines` … `kept` |
| a rule for one area of a polyglot repository | `components.<name>.guidelines` | `components.<name>.guidelines` … `kept` |
| a decision no change may violate | a record under `docs.constraints` | `docs.constraints` … `inlined in full` |
| a long document read only when needed | `docs.architecture` | `index` |
| to say what the project is: drop or swap a framework guideline | a profile in `.openfactory/profiles/` and `profile:` in the manifest | `framework` … `waived by` / `replaced by` |
| the organisation's standards on every project | the operator's `OPENFACTORY_GUIDELINES_DIR` | `operator` |

The manifest is the annotated `docs/project.yaml.example`; the worked example's own is
`docs/examples/profiled-project/.openfactory/project.yaml`, and its profile is
`docs/examples/profiled-project/.openfactory/profiles/house-style.yaml`.

A path the manifest names is read from the checkout and from nowhere else: an entry that resolves
outside the repository is **refused** — the job's log says so, `openfactory doctor` fails the
project, and `explain` prints the row as `refused`. A path that is not there prints as
`missing`. Either way the agent runs without it, which is exactly what the row is for.

### With the operator's directory

The operator's tier appears only when the variable is set. The suite sets it to the example
directory `docs/examples/operator-guidelines`:

```console
$ OPENFACTORY_GUIDELINES_DIR=docs/examples/operator-guidelines openfactory explain docs/examples/profiled-project
```

```text
openfactory explain · docs/examples/profiled-project

  profile   prototype → house-style
              prototype    openfactory/org_defaults/profiles/prototype.yaml — shipped with the package
              house-style  .openfactory/profiles/house-style.yaml — the project's own
  operator  OPENFACTORY_GUIDELINES_DIR=docs/examples/operator-guidelines

What a planner or executor pass is handed, in order (the card is each ticket's own):

  role prompt       planner                          openfactory/org_defaults/roles/planner.md — the package's own; nothing overrides it
  role prompt       executor                         openfactory/org_defaults/roles/executor.md — the package's own; nothing overrides it
  docs.constraints  docs/adr/0001-money-in-cents.md  inlined in full
  framework         engineering.md                   replaced by docs/engineering.md
  framework         tdd.md                           waived by prototype → house-style
  operator          security.md                      kept
  docs.guidelines   HOUSE-RULES.md                   kept
  index             docs/architecture/overview.md    the three modules and which one owns money
  knowledge map                                      on — added per job when a fresh bundle describes its checkout; not read here
```

`security.md` lands after the framework's guidelines and before the project's, so the deployment
outranks the class and the project still has the last word.

### In Portuguese

Every label and every refusal is written in English and in Brazilian Portuguese. File names,
manifest keys and the profile chain are identifiers and stay as they are; so does the summary an
index entry quotes from the document itself.

```console
$ openfactory explain docs/examples/profiled-project --language pt-BR
```

```text
openfactory explain · docs/examples/profiled-project

  perfil    prototype → house-style
              prototype    openfactory/org_defaults/profiles/prototype.yaml — vem com o pacote
              house-style  .openfactory/profiles/house-style.yaml — do próprio projeto

O que um passo de planner ou executor recebe, em ordem (o cartão é de cada ticket):

  prompt do papel   planner                          openfactory/org_defaults/roles/planner.md — o do pacote; nada o sobrepõe
  prompt do papel   executor                         openfactory/org_defaults/roles/executor.md — o do pacote; nada o sobrepõe
  docs.constraints  docs/adr/0001-money-in-cents.md  incluído inteiro
  framework         engineering.md                   substituído por docs/engineering.md
  framework         tdd.md                           dispensado por prototype → house-style
  docs.guidelines   HOUSE-RULES.md                   mantido
  índice            docs/architecture/overview.md    the three modules and which one owns money
  mapa do código                                     ligado — entra por job quando um pacote atualizado descreve o checkout; não é lido aqui
```

### When it refuses

A refusal is one sentence and a non-zero exit, never a traceback: a path with no manifest, a
profile that does not resolve (it names where it looked), or an address instead of a checkout.

```console
$ openfactory explain https://github.com/acme/shop
```

```text
https://github.com/acme/shop is an address, and explain reads a checkout on this machine — clone it and pass the directory.
```

When the job's own code logs a warning while `explain` runs it — a guideline refused, a profile
naming a file no tier has — the warning is printed once, at the end, under *the job's log says*:
that is the line to look for in a real job's log.

---

## The AI engineer: how do I improve this?

Everything above, plus the places the platform's opinion is written.

**The role prompts** are `openfactory/org_defaults/roles/*.md` — one file per role, plain
instructions, no harness in them. Changing one changes what that role means on every project of
every deployment that installs the package, so it is a pull request to this repository and not a
setting. A role this package does not ship arrives as an add-on and carries its own prompt
(`docs/writing-an-addon.md`); an add-on may not replace a shipped one. [The agents
page](agents.md) says what each role may and may not do and where each rule is written.

**The profiles** are the tuning surface a project owns. A shipped profile is a worked example,
not a vocabulary: `prototype` waives `tdd.md`, `regulated` adds evidence at the merge gate and
changes no guideline. A project writes its own beside its manifest, `extends` one, and is shown
exactly what it did by `explain`.

**The operator's directory** carries an organisation's central standards into every project of a
deployment. The `.md` files directly in it are inlined; the ones under
`$OPENFACTORY_GUIDELINES_DIR/reference/` are indexed and read on demand.

**How a change is shown to work.** The house rule for any behaviour is a guard and a mutation
plan that proves the guard bites: `tools/mutations/` holds one plan per claim, run by
`tools/mutate.py`, and every row must turn its test red. This page has one,
`tools/mutations/the_developer_guide_runs.py`. When you change a prompt or a guideline, run
`openfactory explain --full` on a project and read the text the agent will read.

**The one behaviour that is not written in markdown yet: the product role's gestures.** What a
person can ask the product role to do beyond talking — announce, triage, accept, close, refine,
break down — is recognised by a word list of regular expressions, in Portuguese and English,
anchored and conservative on purpose: `openfactory/product/intents.py`. It is correct, and it is
not something a client customises; changing what it recognises is a code change with its own
tests. Turning it into a typed decision the model returns — so that changing how the agents
behave is role markdown and profiles all the way down — is the half of this work that has not
been built.

---

## Not yet a door

**The architect** — *are my decisions being complied with?* What exists: the decision records in
`docs.constraints` are inlined in full on every pass (`explain` lists them), and the independent
review reads each change against its card. What does not: a trace from a change to the records it
followed, and a map from each acceptance criterion to the test that holds it. Until those exist
this page would be telling an architect to read diffs, which is not a door.

**The security engineer** — *what can the agent do, and what stops it?* What exists: the floor
every project must declare (`openfactory/org_defaults/floor.yaml`, a `security` gate among it),
the box each job runs in, and the operator-owned registry the agent cannot reach. What does not:
one page that walks those as a reader of this guide walks the cascade above, each claim with the
command that shows it.
