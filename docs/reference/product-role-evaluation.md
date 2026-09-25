# The product role's evaluation battery

A set of product-owner questions about one small product, asked of the product role through the
same door the panel uses. Each answer gets three verdicts:

| verdict | passes when |
|---|---|
| **correct** | every fact a right answer carries is there, and nothing it must not say |
| **cited** | the requirement or file a right answer rests on is named |
| **abstained correctly** | it said "I do not know" exactly when nothing it can read answers the question |

Every run is written down with the commit and the model it ran on. That way a change to the role
([#266](https://github.com/Open-Factory-Digital/openfactory-core/issues/266)) shows up as a number
that moved, not as an impression. This is slice 0 of ADR-0051.

**Who writes what (decision 9).**

- The **questions** are the product owner's.
- The **expected answers** (the facts, the sources, and whether "I do not know" is right) are
  written by whoever implements the battery, against the fixture.
- The automation is also the implementer's.

The question file ships empty. Until a question is in it, `make eval-product` refuses with:
*the battery has no questions yet; the product owner writes them (decision 9)*.

## The product the questions are about

`tests/fixtures/evaluation/larkledger/` is one small invoicing product, Lark Ledger, laid out the
way a real one is:

- **`context/` is its context repository.** It holds:
  - `.openfactory/product.yaml`, with `sources:`;
  - three requirements: numbering, payment reminders and partial payments, the last one still
    proposed with an open question;
  - the decisions recorded in the requirements' own *Decisions taken during execution* tables;
  - a glossary under `domain/`.
- **`source/` is its code.** It has three small modules (invoices, numbering, reminders) and a
  manifest that names the context repository back.

Read both before writing questions. Some answers are only in a requirement, some only in the
code, and some only in a recorded decision. Some are nowhere, like how a customer pays, or whether
a partial payment restarts the reminders: those are the questions whose right answer is "I do not
know".

## Writing a question

The file is `tests/fixtures/evaluation/larkledger/questions.yaml`. Its header repeats this format.

```yaml
questions:
  - id: first-reminder                 # unique; lowercase, digits, hyphens
    question: When does a customer get the first reminder about an unpaid invoice?
    audience: client                   # client | product admin | engineer; client if left out

    # the expected answer, written by the implementer
    facts:
      - 7 days                         # as written: case, accents and spacing are ignored
      - any: [due date, overdue]       # any one of these spellings
      - claim: the reminder goes out a week after the invoice was due   # a meaning, judged by a model
    must_not:
      - 14 days                        # the tempting wrong answer; same three shapes
    sources:
      - context/requirements/0002-payment-reminders.md   # cited as REQ-0002, REQ-2, "requirement 2"
      - path: source/larkledger/reminders.py             # cited by its path or its file name,
        cited_as: [reminder schedule]                    # or a spelling named here
    expect_unknown: false
```

**For the product owner.**

- Write `id`, `question` and, when it is not a client asking, `audience`. That is the whole of your
  half.
- Ask the way a client, a product admin or an engineer really would, in their words.
- Put in some questions nobody can answer from what the product holds. Saying "I do not know" at
  the right moment is a third of the score.
- A question without its expected answer is refused by name ("… the implementer's to write
  (decision 9)"). It is never scored as the role's mistake.

**For the implementer.**

- **Use a plain spelling for anything exact:** a number, a name, an identifier. It is checked with a
  string comparison: free, reproducible, and whole-word, so `7 days` is not found in `17 days`.
- **Use `claim:` only for a meaning** that can be worded many ways, such as "the owner is told
  after the second reminder". A judge model decides it, at most once per answer.
- **Quote anything YAML would read as a boolean.** `yes`, `no`, `true` and `false` left bare are
  refused rather than guessed.
- **Sources are paths inside the fixture**, starting `context/` or `source/`. A path the fixture
  does not hold is refused when the file is loaded.
- **What counts as a citation** is what the role is told to give:
  - a requirement file counts when its number is named, because the role cites requirement
    numbers and never documentation paths;
  - any other file counts by its path or its file name;
  - add `cited_as` when something else should count, such as a glossary term.
- **Set `expect_unknown: true`** when nothing in the fixture answers the question. Such a question
  lists no facts and no sources, and puts the likely wrong guesses under `must_not`.

## Running it

```bash
make eval-product
```

**It asks a LIVE model, so every run spends tokens.** That is why it is its own target and is never
reached from `make test` or `make check`. `tests/test_the_evaluation_battery.py` holds that rule,
and the runner refuses a live run inside pytest.

**What happens on a run.**

- Each question is asked in a conversation of its own, by a person the role has never heard from.
  The run keeps no memory, so the order of the questions cannot change the score.
- The run's state (repository cache, board, memory) lives in a temporary directory, which is
  removed afterwards.
- What reaches the model is the fixture and the questions, and nothing else.

**Which engines it uses.**

- The role runs on the deployment's product harness: `OPENFACTORY_HARNESS_PRODUCT`, with
  `OPENFACTORY_PRODUCT_MODEL` for the model.
- The judge runs on the reviewer's harness: `OPENFACTORY_HARNESS_REVIEWER`, with
  `OPENFACTORY_REVIEWER_MODEL`. Point it at another engine to judge with something other than the
  model being judged.

**What it writes.** Two dated files under `tests/fixtures/evaluation/results/`:

- a JSON record: the commit, whether the checkout had uncommitted changes, the harness and model of
  the role and of the judge, every answer in full, and every verdict with the reason for it;
- a short markdown summary of the same run.

Commit the pair: the first one is today's baseline.

**Exit status.**

- `0` when every question was asked and scored, whatever the score.
- Non-zero when there was nothing to run: no questions, a question file that does not validate, or
  a fixture the product module does not accept.

## Reading a score

Every verdict says who decided it:

| `decided_by` | meaning |
|---|---|
| `deterministic` | a string comparison over the answer |
| `judge` | a model read the answer against the key: a `claim`, or an abstention the phrase list could not see |
| `not applicable` | nothing to decide: an answer that should be "I do not know" cites nothing |
| `undecided` | the judge was needed and gave no readable ruling. It is counted apart, never as a pass or a fail |

**When the judge is called.** Only for what a string cannot decide:

- the `claim` facts;
- whether the answer abstained, and only when the phrase list's reading would count against the
  role.

When the phrase list agrees with the key, it decides alone.

**What the score cannot see yet.**

- Today's role treats the three audiences the same, except that a product admin may confirm writes.
  The battery asks from all three anyway, so the difference shows once slice 4 gives a speaker a
  role.
- The battery has one fixture. A monorepo, a product made of several services, and a product years
  old arrive with #268 and #269.
