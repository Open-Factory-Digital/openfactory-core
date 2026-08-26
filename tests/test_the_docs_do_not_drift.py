"""The documents a stranger and a client read are checked against the code (C-46, #89).

`README.md` described a "Foundation scaffold… adapters and the orchestrator are interfaces with
`TODO(slice-N)` seams" and told the reader `docker compose up -d # Postgres + Redis`. It listed
"Jira later", "GitLab later", "Aider later". Every one of those was false: four working harnesses,
a live Jira tracker, and a compose file whose own header records that Postgres and Redis are gone.
It is the only page most evaluators read, and it undersold a working platform as a skeleton while
handing a stranger a command that is both wrong and unsafe.

`docs/STATUS.md` — titled "Read this before deciding anything", and the
artefact most likely to be in front of an enterprise client — was three days stale in BOTH
directions: it denied `sdlc box prove` exists, denied Jira had ever run live, listed three
harnesses, and correctly named the one real hole.

CORRECTING THEM IS NOT THE FIX. Nothing kept them in step and nothing in CI looked, so in two
weeks they lie again — as they already had. These assertions are the mechanism: each one is a
claim from the documents that the code can answer, so the document cannot drift without the suite
going red.
"""

from __future__ import annotations

import pathlib
import re
import subprocess

import add_ons
import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
README = (ROOT / "README.md").read_text()
WORKS = (ROOT / "docs/STATUS.md").read_text()


def _carries_a_measurable_number() -> list[str]:
    """Every document that SHIPS and states how things are, so the two count guards below cover
    all of them rather than four names somebody typed.

    THAT LIST OF FOUR IS WHY THE ROT LIVED. `docs/core/01-reality-check.md` announced "~1,600
    tests and 32 ADRs" and `docs/site-guide.md` shipped "4,971 tests" beside STATUS's own count,
    for as long as they did, because neither was one of the four names. Derived instead: the
    tracked documents under `docs/`, plus the two at the root a reader meets first — minus the
    decision records, which are history and state the world on the day they were accepted; minus
    `docs/STATUS.md`, which is the ONE home of a count; and minus whatever the public cut
    excludes, because a document that does not ship owes a stranger nothing."""
    out = subprocess.run(["git", "ls-files", "-z", "docs/*.md"], cwd=ROOT,
                         capture_output=True, text=True, timeout=120)
    assert out.returncode == 0, out.stderr[:200]
    excluded = add_ons.excluded_paths()

    def ships(rel: str) -> bool:
        return not any(rel == p or (p.endswith("/") and rel.startswith(p)) for p in excluded)

    docs = [p for p in out.stdout.split("\0")
            if p and not p.startswith("docs/adr/") and p != "docs/STATUS.md" and ships(p)]
    return ["README.md", "CONTRIBUTING.md", *sorted(docs)]


def test_the_documents_a_count_guard_covers_are_DERIVED_and_not_a_list_of_four():
    """The twin of the widening. A set that shrank back to a handful, or to nothing, would make
    both guards below pass by scanning almost no prose — which is exactly how they passed while
    two shipped documents carried wrong numbers."""
    covered = _carries_a_measurable_number()
    assert len(covered) > 10, f"only {covered} are covered — the derivation has collapsed"
    for rel in ("README.md", "CONTRIBUTING.md", "docs/README.md", "docs/architecture.md"):
        assert rel in covered, f"{rel} is no longer covered by the count guards"
    assert not any(rel.startswith("docs/adr/") for rel in covered), (
        "a decision record is being held to today's numbers — an ADR states the world on the day "
        "it was accepted")
    assert "docs/STATUS.md" not in covered, (
        "docs/STATUS.md is in the set that may not carry a count, and it is the one place a "
        "count lives")


def test_the_readme_and_the_onboarding_register_a_project_the_SAME_way():
    """THE SPINE PROMISE: the README's quickstart is a strict PREFIX of ONBOARDING, so a reader
    who starts at either arrives at the same place.

    It broke in front of the pilot operator (2026-08-12): he followed the README, which taught
    `project add` — registration WITHOUT a board — while ONBOARDING §2 leads with `project
    init`, which registers AND creates the board the later steps ("drag it to TO-DO") require.
    Two entry documents, two different first commands, and the reader had to ask which.

    Pinned as the VERB each document leads with, not as literal text, so either page may keep
    its own prose."""
    onboarding = (ROOT / "docs/ONBOARDING.md").read_text()

    def _first_project_verb(text: str) -> str:
        return next(m.group(1) for m in re.finditer(r"openfactory project ([a-z-]+)", text))

    assert _first_project_verb(README) == _first_project_verb(onboarding), (
        f"README leads with `project {_first_project_verb(README)}` and ONBOARDING with "
        f"`project {_first_project_verb(onboarding)}` — one of them sends the reader down a "
        f"path the other does not")


def test_the_readme_lists_every_harness_that_exists():
    """It said "Claude Code over `claude -p`; Aider later" while four adapters shipped."""
    from openfactory.adapters.agent.registry import HARNESSES, harness_binary

    line = next(ln for ln in README.splitlines() if "CodingAgentAdapter" in ln)
    for kind in HARNESSES:
        label = {"claude_code": "Claude Code"}.get(kind, harness_binary(kind))
        assert label.lower().replace("_", " ") in line.lower(), f"{kind} is not in the README"


def test_the_works_today_page_lists_every_harness():
    from openfactory.adapters.agent.registry import HARNESSES

    row = next(ln for ln in WORKS.splitlines() if ln.startswith("| agent |"))
    assert str(len(HARNESSES)) in row or "four" in row.lower(), row
    assert "OpenCode" in row


@pytest.mark.parametrize("claim", ["Jira later", "GitLab later", "Aider later"])
def test_the_readme_does_not_promise_LATER_what_already_ships(claim):
    provider = claim.split()[0].lower()
    exists = (ROOT / f"openfactory/adapters/tracker/{provider}.py").exists() \
        or (ROOT / f"openfactory/adapters/agent/{provider}.py").exists()
    if exists:
        assert claim not in README, f"{claim!r} — it ships"


def test_the_readme_does_not_call_a_working_platform_a_scaffold():
    assert "Foundation scaffold" not in README
    assert "TODO(slice-N)" not in README


def test_the_quickstart_describes_what_compose_actually_starts():
    """It promised "Postgres + Redis (single-process for now)"; the compose file's own header
    records both as no longer used, and it brings up the worker, the panel and Temporal."""
    compose = (ROOT / "docker-compose.yml").read_text()
    assert "Postgres + Redis" not in README
    for service in ("worker", "panel"):
        assert f"{service}:" in compose


def test_every_numbered_section_is_on_the_map_that_opens_the_document():
    """The table at the top is how a reader decides where to go. A section missing from it is a
    section written for whoever already knew it was there — §12 shipped that way, which is how
    the pilot came to ask whether any of this was documented at all (2026-08-15)."""
    onboarding = (ROOT / "docs" / "ONBOARDING.md").read_text()
    the_map = onboarding[:onboarding.index("> **What this document assumes about you")]
    # A RANGE POINTS AT EVERY SECTION IN IT — `§5–§7` is how the map covers the three steps of
    # the proof, and reading it as a literal accused §6 of being missing from a row that names it.
    pointed = {int(n) for n in re.findall(r"§(\d+)", the_map)}
    for lo, hi in re.findall(r"§(\d+)\s*[–-]\s*§?(\d+)", the_map):
        pointed |= set(range(int(lo), int(hi) + 1))
    missing = [n for n in re.findall(r"^## (\d+) · ", onboarding, re.M)
               if int(n) not in pointed]
    assert not missing, (
        f"these sections exist and the opening map never points at them: {missing}")


def test_the_auto_merge_conditions_are_documented_where_the_policy_is_offered():
    """`merge_policy: auto` decides whether a pull request lands without a person, so a document
    that offers it owes the reader EVERY condition it still checks — otherwise "auto" reads as
    "merge whatever comes out", which is the opposite of what the code does. Derived from
    `should_auto_merge`, so a condition added there cannot stay unwritten (pilot, 2026-08-15:
    *"the natural thing is for the merge NOT to be done by a human every time — it depends on the company"*)."""
    import inspect

    from openfactory.orchestrator import merge_policy

    rules = inspect.getsource(merge_policy.should_auto_merge)
    onboarding = (ROOT / "docs" / "ONBOARDING.md").read_text()
    # THE SECTION, NOT THE DOCUMENT. The first cut searched the whole file and passed while the
    # suppression row was deleted, because the word appears in the row beside it — a guard that
    # cannot fail is worse than none, and this one is guarding the sentence that decides whether
    # somebody's `noqa` merges itself.
    section = onboarding[onboarding.index("## 11b · WHO MERGES"):]
    section = section[:section.index("\n## ")]

    owed = {
        "all_passed": ("every gate passed", "every gate the manifest declares"),
        "rejected": ("did not reject", "a rejecting review"),
        "added_suppressions": ("HARD suppression", "a suppression that survived the repair loop"),
        "RiskLevel.HIGH": ("risk: high", "a high-risk component"),
    }
    for token, (phrase, what) in owed.items():
        if token not in rules:
            continue  # the rule is gone; the document is free to stop mentioning it
        assert phrase in section, (
            f"`auto` still refuses to merge on {what} and §11b does not say so")


def _section(title: str) -> str:
    """One numbered section of ONBOARDING, with its line breaks flattened.

    THE WRAPPING IS NOT PART OF THE CLAIM. The first version of the guard below searched the raw
    text and failed on a sentence the document really does contain — the editor had wrapped it
    between "no" and "production". A guard that depends on where a line broke sends somebody
    hunting for a missing paragraph that is on screen in front of them."""
    onboarding = (ROOT / "docs" / "ONBOARDING.md").read_text()
    body = onboarding[onboarding.index(title):]
    body = body[:body.index("\n## ")]
    return re.sub(r"\s+", " ", body)


def test_the_post_merge_section_teaches_keys_that_REALLY_EXIST():
    """§13 hands the reader three YAML blocks to paste, so every key in them is checked against
    the contract that parses them — a manifest key that is documented and misspelled fails with a
    strict-model error at the worst possible moment (pilot, 2026-08-16).

    Derived from the pydantic models, so renaming a field breaks this test rather than the
    reader's manifest."""
    from openfactory.contracts.manifest import Environment, Manifest, PostMergeDeploy

    section = _section("## 13 · AFTER THE MERGE")

    for key in ("post_merge_deploy", "environments", "promote", "prod_tag_prefix"):
        assert key in Manifest.model_fields, f"§13 teaches `{key}:` and the manifest has no such field"
        assert key in section, f"the manifest has `{key}` and §13 never mentions it"
    for key in PostMergeDeploy.model_fields:
        assert key in section, f"§13 shows `post_merge_deploy:` without its `{key}` field"
    for key in Environment.model_fields:
        assert key in section, f"§13 shows an environment without its `{key}` field"


def test_the_post_merge_section_states_the_rule_the_CHAIN_actually_applies():
    """"The last name is production" is not prose — it is `promotion_chain()`'s definition, and a
    reader who gets it wrong declares a production stage they think is a staging one."""
    import inspect

    from openfactory.contracts.manifest import Manifest

    rule = inspect.getsource(Manifest.promotion_chain)
    section = _section("## 13 · AFTER THE MERGE")

    if "self.promote[-1]" in rule:
        assert "LAST one is production" in section or "last name is production" in section, (
            "§13 does not tell the reader that the final entry of `promote:` IS production")
    if "no `promote:`" in section or "omit `promote:`" in section:
        assert "no production environment" in section


def test_the_merge_that_ENDS_a_job_points_at_the_section_that_explains_it():
    """The ticket comment a merged job leaves is the only place most operators will ever be told
    the post-merge half exists — so the section it names has to be there."""
    import inspect

    from openfactory.runtime.temporal import workflow as wf

    note = inspect.getsource(wf.JobWorkflow._finish_at_the_merge)
    onboarding = (ROOT / "docs" / "ONBOARDING.md").read_text()
    referenced = re.findall(r"ONBOARDING §(\d+)", note)
    assert referenced, "the closing comment names no section at all"
    for num in referenced:
        assert f"\n## {num} · " in onboarding, (
            f"a merged ticket sends the reader to ONBOARDING §{num}, which does not exist")


def test_the_onboarding_does_not_promise_an_expiry_the_gate_no_longer_takes():
    """A DOCUMENT THAT CONTRADICTS THE CODE SENDS SOMEBODY TO WORK FOR NOTHING. §5 said a proof
    "expires when the image … move[s] underneath it", which stopped being true the day the gate
    learned that a rebuild with an unchanged toolchain is not a change — and following it means
    re-proving after every platform update, which is exactly the cost that was removed.

    Derived from the code: while `_freshness_reason` has the toolchain branch, the section that
    explains expiry has to mention it (pilot, 2026-08-15)."""
    import inspect

    from openfactory import box_prove

    if "toolchain" not in inspect.getsource(box_prove._freshness_reason):
        return  # the rule is gone; the doc is free to stop mentioning it
    onboarding = (ROOT / "docs" / "ONBOARDING.md").read_text()
    section = onboarding[onboarding.index("## 5 · Prove the box"):]
    section = section[:section.index("\n## ")]
    assert "toolchain" in section, (
        "§5 explains what expires a proof and never mentions the toolchain — an operator reads "
        "that every rebuild expires it, and re-proves after every update")
    assert "does NOT expire" in section


def test_the_onboarding_explains_the_line_set_model_prints():
    """A ⚠ nobody was told about reads as a failure. The command has three answers and two of
    them are new; the section that teaches `set-model` owes the operator all three — especially
    that an unrecognised name is EXPECTED for a Bedrock ARN and blocks nothing."""
    import inspect

    from openfactory import cli

    if not hasattr(cli, "_model_recognition_note"):
        return
    note = inspect.getsource(cli._model_recognition_note)
    onboarding = (ROOT / "docs" / "ONBOARDING.md").read_text()
    section = onboarding[onboarding.index("## 11 ·"):]
    section = section[:section.index("\n## ")]

    for phrase, why in (("does not recognise", "the warning it prints"),
                        ("not checked", "the case where it could not ask"),
                        ("Bedrock", "why an unrecognised name is not a typo")):
        assert phrase in note or phrase in section, f"§11 never mentions {why}"
        assert phrase in section, f"§11 never mentions {why} — only the code says it"


def test_no_doc_tells_an_operator_to_tail_a_container_that_does_not_exist():
    """A `docker compose logs <service>` in a document is a command somebody will paste.

    Written the day the surfaces section was added and got this exact thing wrong: it offered
    `logs -f poller` and `logs api`, and neither is a service — the poller is a schedule inside
    the worker. The command does not fail loudly, it just prints nothing, which reads as "the
    factory is silent" (2026-08-15).
    """
    import re

    compose = (ROOT / "docker-compose.yml").read_text()
    services = set(re.findall(r"^  ([a-z][a-z0-9_-]*):", compose, re.M))
    offenders = []
    for doc in sorted(ROOT.glob("docs/**/*.md")) + [ROOT / "README.md"]:
        for named in re.findall(r"compose[^\n`]*\blogs\b((?:\s+-\w+)*(?:\s+[a-z][a-z0-9_-]*)+)",
                                doc.read_text()):
            for word in named.split():
                if not word.startswith("-") and word not in services:
                    offenders.append(f"{doc.relative_to(ROOT)} — `docker compose logs {word}`")

    assert not offenders, (
        "these documents tail a compose service that does not exist (it prints nothing and "
        "reads as a silent factory):\n  " + "\n  ".join(offenders)
        + f"\n\nthe services are: {', '.join(sorted(services))}")


def test_the_works_today_page_does_not_deny_what_now_exists():
    """Both of these were true when written and false by the time a client would have read them."""
    assert "It does not exist yet" not in WORKS, "`sdlc box prove` exists and gates pickup"
    assert "Jira has never run against a live Jira instance" not in WORKS


def test_the_works_today_page_does_not_still_claim_the_floor_is_only_announced():
    """The inverse of the guard this replaces, and for the same reason it existed.

    It used to assert the page NAMED the hole — *"the floor is announced, not enforced"* — because
    the correction must not become a sales page. That hole is closed: the floor refuses, and
    `OPENFACTORY_ENFORCE_FLOOR` no longer exists. A page still describing the switch would send a reader
    to set a variable nothing reads, which is the same failure in the opposite direction.

    The page must still say what CHANGED rather than quietly dropping it, so the history stays
    readable — hence the second assertion.
    """
    assert not re.search(r"not yet\s+enforced|announced.*not yet enforced", WORKS, re.I), (
        "the page still says the floor is not enforced; it refuses unconditionally now"
    )
    assert re.search(r"floor\s+REFUSES|no switch", WORKS, re.I), (
        "the page no longer states what the floor does at all"
    )


def test_the_works_today_page_carries_the_commit_it_describes():
    """A page dated by hand drifts silently. Naming the commit makes the staleness visible to the
    next reader even when this suite has not run.

    AND THE COMMIT MUST BE REAL. Asserting only the SHAPE of a sha accepts one that no longer
    exists — a rebase, a typo, or a number somebody updated by editing digits — and then the
    reader who tries to measure the drift gets `fatal: bad object` and learns nothing. That is
    the failure this page exists to prevent, wearing the guard as a disguise."""
    # TWO FORMS, AND ONLY ONE IS VERIFIED. `main at \`sha\`` names a commit of THIS history and is
    # checked below. `cut from \`sha\`` is what the public export writes (2026-08-26): a
    # fresh-history repository cannot hold the source tree's commit, and a guard that demanded it
    # would be red on the first commit of every public clone — so that form names where the tree
    # came from and is not verified, and the first maintainer who edits the page in the public
    # repository writes the strict form against a commit that exists there.
    cut = re.search(r"cut from `([0-9a-f]{7,})`", WORKS)
    named = re.search(r"main at `([0-9a-f]{7,})`", WORKS)
    assert named or cut, "docs/STATUS.md no longer names the commit it describes"
    if cut and not named:
        pytest.skip("a fresh-history export: the page names the source tree's commit, not one "
                    "of this history — nothing here can verify it")

    # A SHALLOW CLONE HAS NO OPINION ON THIS, and saying otherwise is how a guard earns a
    # reputation for lying. `actions/checkout` fetches depth 1 by default, so on CI every commit
    # but the tip is genuinely absent — asking there would fail on a page that is perfectly
    # correct. This guard is about a sha somebody typed wrong or rebased away, and only a full
    # history can tell those apart from "not fetched".
    shallow = subprocess.run(["git", "rev-parse", "--is-shallow-repository"],
                             cwd=ROOT, capture_output=True, text=True, timeout=60)
    if shallow.stdout.strip() == "true":
        pytest.skip("shallow clone: absence of a commit here means nothing")

    known = subprocess.run(["git", "cat-file", "-e", f"{named.group(1)}^{{commit}}"],
                           cwd=ROOT, capture_output=True, timeout=60)

    assert known.returncode == 0, (
        f"docs/STATUS.md says it describes `{named.group(1)}`, which is not a commit in this "
        f"repository — nobody can measure how stale the page is, which is the whole point of "
        f"naming it")


def test_the_adr_count_the_docs_CLAIM_is_the_number_of_ADRs_there_are():
    """A number a command can measure, typed by hand, is a number that rots — and it had: four
    documents said "42 decision records" over 41 ADRs, because `docs/adr/` also holds its own
    README and somebody counted files.

    That is #113's whole lesson, in the smallest possible form. `docs/OVERVIEW.md` was retired for
    announcing "402 tests" and "17 decisions"; the same rot was live in the README on the same day,
    two orders of magnitude smaller and therefore invisible.
    """
    records = sorted(p.name for p in (ROOT / "docs" / "adr").glob("[0-9][0-9][0-9][0-9]-*.md"))
    assert len(records) > 30, f"only {len(records)} ADRs found — this guard is measuring nothing"

    claimed = []
    for rel in _carries_a_measurable_number():
        for found in re.finditer(r"(\d+) decision records", (ROOT / rel).read_text()):
            claimed.append((rel, int(found.group(1))))

    assert claimed, "no document states the count any more — this guard is measuring nothing"
    wrong = [f"{rel} says {n}" for rel, n in claimed if n != len(records)]
    assert not wrong, (
        f"there are {len(records)} decision records and {'; '.join(wrong)}. The directory also "
        f"holds its own README, which is the off-by-one this guard exists for")


def _status_word(status: str) -> str:
    return re.sub(r"\*\*", "", status).strip().split()[0].rstrip(";,(").lower()


def test_the_adr_index_status_column_is_the_ADRs_own_status():
    """The same hand copy one level down. `docs/adr/README.md` copies each ADR's Status line into
    a column, and a column is edited when a reader notices, not when the ADR changes — ADR-0034's
    row said the model "stays deliberately undecided" for as long as the ADR said so, and the
    addendum that decided the in-process step (2026-08-26) would have left the row saying the
    opposite of the record it indexes.

    Two rules, both derived from the ADR files: every row's leading word (Accepted / Proposed)
    is the ADR's own; and an ADR whose Status line names an addendum is copied VERBATIM, because
    that line is the one that changed after the row was written. The addendum must also exist as
    a heading, or the Status line claims a record that is not there."""
    index = (ROOT / "docs" / "adr" / "README.md").read_text()
    rows = re.findall(r"^\| \[(\d{4})\]\([^)]+\) \| .*? \| (.*?) \|$", index, re.M)
    assert len(rows) > 30, f"only {len(rows)} rows parsed from the ADR index — this measures nothing"

    wrong, with_addendum = [], []
    for num, row in rows:
        adr = next((ROOT / "docs" / "adr").glob(f"{num}-*.md"))
        text = adr.read_text()
        own = re.search(r"^- \*\*Status:\*\*\s*(.*)$", text, re.M)
        assert own, f"{adr.name} has no Status line"
        own_plain = re.sub(r"\*\*", "", own.group(1)).strip()
        row_plain = re.sub(r"\*\*", "", row).strip()
        if _status_word(row_plain) != _status_word(own_plain):
            wrong.append(f"{num}: the index says {row_plain!r}, the ADR says {own_plain!r}")
        if "addendum" in own_plain.lower():
            with_addendum.append(num)
            if row_plain != own_plain:
                wrong.append(f"{num}: the index's copy {row_plain!r} is not the ADR's {own_plain!r}")
            if not re.search(r"^## Addendum \(", text, re.M):
                wrong.append(f"{num}: the Status line names an addendum the file does not have")
    assert not wrong, "docs/adr/README.md disagrees with the records it indexes:\n  " + "\n  ".join(wrong)
    assert "0034" in with_addendum, (
        "ADR-0034's Status line no longer names its addendum — the verbatim-copy rule has "
        "nothing to measure")


def test_the_status_page_is_the_ONE_place_a_test_COUNT_is_written():
    """The other half of the same rule. A count in the README and a count in STATUS drift apart the
    first time only one of them is edited — so exactly one document carries it, and this asserts
    that the others do not grow their own."""
    others = []
    for rel in _carries_a_measurable_number():
        text = (ROOT / rel).read_text()
        # THREE DIGITS, NOT FOUR. The first version of this guard looked for `[\d,]{4,}` and
        # walked straight past `402 tests green` in architecture.md — the very number 
        # docs/OVERVIEW.md was retired for. A guard that only catches the big rot is a 
        # guard that certifies the small rot.
        for found in re.finditer(r"(\d[\d,]{2,})\+?\s+tests\b", text):
            others.append(f"{rel}: {found.group(0)!r}")

    assert not others, (
        "a test count is written outside docs/STATUS.md, which is the one place it lives: "
        + "; ".join(others))

    assert re.search(r"[\d,]{4,} tests green", (ROOT / "docs" / "STATUS.md").read_text()), (
        "docs/STATUS.md no longer carries the count it is supposed to be the only home for")


# ── architecture.md §6: the seam table is read off the registries ───────────────────────────────

def _seam_table(text: str | None = None) -> list[tuple[str, str, str, str]]:
    """The rows of §6's fenced table: (axis label, protocol, what ships, the entry-point name).

    Cells are separated by two or more spaces, so a cell may carry single-spaced prose ("a cloud
    box (an add-on package: openfactory-aws)"); the header row and the rule line are not rows."""
    text = text if text is not None else (ROOT / "docs" / "architecture.md").read_text()
    section = text[text.index("## 6. "):]
    block = re.search(r"```\n(.*?)```", section, re.DOTALL)
    assert block, "architecture.md §6 has no fenced seam table"
    rows = []
    for line in block.group(1).splitlines():
        cells = re.split(r"\s{2,}", line.strip())
        if len(cells) == 4 and cells[0] != "axis":
            rows.append((cells[0], cells[1], cells[2], cells[3]))
    return rows


def _seam_axes() -> dict[str, tuple[dict, str]]:
    """Row label → (the registry's table, the axis name the loader publishes for it). Eight rows,
    because §6 is the presentation-level page and lists the axes a reader mixes per project; the
    positive twin below holds the table to exactly these labels, so a row cannot vanish quietly."""
    from openfactory.adapters.agent.registry import HARNESSES
    from openfactory.adapters.board.factory import BOARDS
    from openfactory.adapters.channel.registry import CHANNELS
    from openfactory.adapters.environment.registry import OBSERVERS
    from openfactory.adapters.forge.registry import FORGES
    from openfactory.adapters.notify.registry import NOTIFIERS
    from openfactory.adapters.sandbox.registry import BOXES
    from openfactory.adapters.tracker.registry import TRACKERS

    return {"harness": (HARNESSES, "harness"), "tracker": (TRACKERS, "tracker"),
            "board": (BOARDS, "board"), "forge": (FORGES, "forge"),
            "CI/deploy": (OBSERVERS, "ci"), "channel": (CHANNELS, "channel"),
            "notifier": (NOTIFIERS, "notifier"), "sandbox": (BOXES, "box")}


def _add_on_kinds(axis: str, rows: dict[str, str] | None = None) -> dict[str, str]:
    """kind → the package that declares `<axis>.<kind>`, read off the packages' own
    `pyproject.toml` files under `addons/` (`vendor_addons`). Empty in the public tree, where
    the packages are absent — there the table's add-on framing cannot be checked against a
    declaration, and the guard says so instead of reading absence as agreement."""
    if rows is None:
        from vendor_addons import declared_by, packages

        rows = {point: name for name, where in packages().items()
                for point in declared_by(where)}
    return {point.partition(".")[2]: package for point, package in rows.items()
            if point.partition(".")[0] == axis}


def _cell_kinds(ships: str) -> tuple[list[str], list[str]]:
    """The `·`-separated tokens of a "ships" cell with the framing parentheses stripped, split
    into key-shaped names (`azure_devops`) and prose placeholders (`a cloud box`)."""
    tokens = [t.strip() for t in re.sub(r"\([^)]*\)", "", ships).split("·") if t.strip()]
    keys = [t for t in tokens if re.fullmatch(r"[a-z_]+", t)]
    return keys, [t for t in tokens if t not in keys]


def _architecture_section_6() -> str:
    text = (ROOT / "docs" / "architecture.md").read_text()
    section = text[text.index("## 6. "):]
    return section[:section.index("\n## ", 1)]


def test_the_seam_table_ships_what_the_registries_ship():
    """`docs/architecture.md` §6 said `tracker: github · jira`, `board: github`, `forge: github
    (gitlab →)` and three harnesses for as long as those were true — and for the weeks after
    Azure DevOps shipped on four axes and OpenCode on the harness axis, because nothing read the
    table against the registries (found 2026-08-26, two waves after the cut).

    Derived, in both directions, from two sources. THE CORE'S TABLES: every distinct BUILDER a
    registry ships must be named by one of its keys (the CI observer has two builders under four
    keys — `github`/`github_actions`, `azure_devops`/`azure_pipelines` — and naming one alias is
    naming the builder). The one exception is a builder whose every key is a vendor's product
    name: a conceptual document may not spell it (`test_the_docs_name_no_vendor_as_the_core.py`),
    so the row must instead frame it as an add-on and name a package `docs/STATUS.md` knows.
    THE PACKAGES' DECLARATIONS: every `<axis>.<kind>` a package under `addons/` declares on the
    row's axis must be named on the row, framed with that package (`notifier.telegram` is a row
    since the fallback became declared, 65a0522, and the table said `panel · slack`). And every
    kind the row names must be one a registry ships or a package declares — `(gitlab →)` was a
    promise no registry kept."""
    import add_ons
    from test_the_docs_name_no_vendor_as_the_core import VENDOR_PRODUCTS
    from test_the_public_cut_is_written_down import _excluded, _packages

    known_packages = set().union(*(_packages(where) for where in _excluded().values()))
    assert known_packages, "docs/STATUS.md names no add-on package — this guard cannot frame a cloud row"
    declarations_readable = not add_ons.is_public_tree()
    rows = {row[0]: row for row in _seam_table()}
    wrong = []
    for label, (table, axis) in _seam_axes().items():
        row = rows.get(label)
        if row is None:
            wrong.append(f"{label}: §6 has no row for it")
            continue
        ships = row[2]
        keys, prose = _cell_kinds(ships)
        named = set(keys)
        framing = _packages(ships) & known_packages
        framed = "add-on" in ships and bool(framing)
        by_builder: dict[int, list[str]] = {}
        for kind, build in table.items():
            by_builder.setdefault(id(build), []).append(kind)
        for kinds in by_builder.values():
            if named & set(kinds):
                continue
            if all(VENDOR_PRODUCTS.search(k) for k in kinds) and framed:
                continue
            wrong.append(f"{label}: the registry ships {kinds} and the row does not name it "
                         f"(or frame it as an add-on package): {ships!r}")
        add_ons_here = _add_on_kinds(axis) if declarations_readable else {}
        for kind, package in add_ons_here.items():
            if kind not in named or package not in framing:
                wrong.append(f"{label}: {package} declares `{axis}.{kind}` and the row does not "
                             f"name it as that package's add-on: {ships!r}")
        for kind in keys:
            if kind in table:
                continue
            if declarations_readable and add_ons_here.get(kind) in framing:
                continue
            if not declarations_readable and framed:
                continue  # the public tree cannot read the declaration; the framing stands
            wrong.append(f"{label}: the row names {kind!r}, which no registry ships and no "
                         f"add-on package under addons/ declares on this axis")
        for token in prose:
            if not framed:
                wrong.append(f"{label}: the row says {token!r} and names no add-on package "
                             f"docs/STATUS.md lists")
    assert not wrong, ("architecture.md §6's seam table disagrees with the registries:\n  "
                       + "\n  ".join(wrong))


def test_the_add_on_kinds_are_read_off_a_declaration_and_split_by_axis():
    """Verify the verifier on a planted declaration: only the asked axis's rows come back, keyed
    by kind, naming the package — and the real packages' declarations, where present, reach
    the same reader (a row a package declares is one the seam guard will ask the table for)."""
    import add_ons
    from vendor_addons import declared

    planted = {"notifier.telegram": "openfactory-x", "notifier.slack": "openfactory-x",
               "channel.slack": "openfactory-x", "box_runner.fargate": "openfactory-y"}
    assert _add_on_kinds("notifier", planted) == {"telegram": "openfactory-x", "slack": "openfactory-x"}
    assert _add_on_kinds("box", planted) == {}, "box_runner is not the box axis"
    if not add_ons.is_public_tree():
        real = {point for axis in {p.partition(".")[0] for p in declared()}
                for kind in _add_on_kinds(axis) for point in [f"{axis}.{kind}"]}
        assert real == set(declared()), (real, set(declared()))


def test_the_cell_reader_splits_keys_from_prose_and_drops_the_framing():
    assert _cell_kinds("panel · slack · telegram (an add-on package: openfactory-slack)") == (
        ["panel", "slack", "telegram"], [])
    assert _cell_kinds("container · worktree · a cloud box (an add-on package: openfactory-aws)") == (
        ["container", "worktree"], ["a cloud box"])
    assert _cell_kinds("github_actions · azure_pipelines") == (["github_actions", "azure_pipelines"], [])


def test_the_seam_table_names_the_axis_the_loader_publishes_for_every_row():
    """The last column is what a stranger types into their pyproject. It said `agent` once in
    `core/07` — the guard there caught it; this is the same check on the presentation page, plus
    the group name, which is the other half of the address."""
    from openfactory import plugins

    section = _architecture_section_6()
    assert f"`{plugins.GROUP}`" in section, (
        f"architecture.md §6 no longer names the entry-point group the loader reads (`{plugins.GROUP}`)")
    rows = {row[0]: row for row in _seam_table()}
    wrong = []
    for label, (_table, axis) in _seam_axes().items():
        cell = rows[label][3] if label in rows else ""
        m = re.fullmatch(r"([a-z_]+)\.<kind>", cell)
        if not m:
            wrong.append(f"{label}: the last column is {cell!r}, not `<axis>.<kind>`")
        elif m.group(1) != axis or axis not in plugins.AXES:
            wrong.append(f"{label}: the row says `{m.group(1)}.<kind>`; the loader publishes `{axis}`")
    assert not wrong, "\n  ".join(["architecture.md §6 tells a stranger the wrong address:", *wrong])


def test_the_seam_table_has_exactly_the_rows_this_guard_reads():
    """The positive twin: a row deleted from the table is a registry the page stops describing,
    and the guards above would simply have one less row to check."""
    labels = [row[0] for row in _seam_table()]
    assert labels == list(_seam_axes()), (
        f"architecture.md §6 lists {labels}; this guard reads {list(_seam_axes())} — a row was "
        f"removed, renamed or added without the guard following")


def test_the_seam_parser_can_SEE_a_row_and_skips_the_header():
    """Verify the verifier on the exact shape §6 uses, including a cell with single-spaced prose."""
    planted = ("## 6. Provider-neutral\n\ntext\n\n```\n"
               "   axis        protocol       ships in the core                          a third one\n"
               "   ────────────────────────────────────────────────────────────────────────────────\n"
               "   forge       ForgeAdapter   github · azure_devops                      forge.<kind>\n"
               "   sandbox     SandboxAdapter  container · a cloud box (an add-on: x-y)  box.<kind>\n"
               "```\n\n## 7. Next\n")
    assert _seam_table(planted) == [
        ("forge", "ForgeAdapter", "github · azure_devops", "forge.<kind>"),
        ("sandbox", "SandboxAdapter", "container · a cloud box (an add-on: x-y)", "box.<kind>")]


def test_telegram_is_described_as_the_declared_fallback_row_that_leaves():
    """§6 said *"GitLab and Telegram are deferred by decision, and no stub adapters exist"* while
    `adapters/notify/telegram.py` shipped and the notifier registry consulted it as the
    deployment-wide fallback; the first rewrite (3724056) then said it was switched on by *"two
    environment variables, no row of its own"* — true at its base and false one commit later,
    when the fallback became a DECLARED row (`notifier.telegram`, `OPENFACTORY_NOTIFIER_FALLBACK`).

    Derived from `docs/STATUS.md`'s table, which names the module, its package and its row in
    both trees: while a `notify/telegram.py` row is there, the sentence that names Telegram must
    call it a fallback, name the variable that declares it (read off the registry, never typed
    here), name the row and the package STATUS names, and say the module leaves. Where the
    packages are present, that package must really declare the row. Once STATUS drops the row
    the page is free to stop describing it."""
    from test_the_public_cut_is_written_down import _excluded, _packages

    from openfactory.adapters.notify import registry

    excluded = _excluded()
    rows = {path: where for path, where in excluded.items()
            if path.endswith("/adapters/notify/telegram.py")}
    if not rows:
        return  # the fallback module is no longer one that leaves; nothing to hold the page to
    (path, where), = rows.items()
    point = re.search(r"`(notifier\.[a-z_]+)`", where)
    assert point, f"docs/STATUS.md's row for {path} no longer names its `notifier.<kind>` entry point"
    packages = _packages(where)
    assert len(packages) == 1, f"docs/STATUS.md's row for {path} names {packages}, not one package"
    (package,) = packages
    declared = _add_on_kinds("notifier")
    if declared:
        assert declared.get(point.group(1).partition(".")[2]) == package, (
            f"docs/STATUS.md says {package} ships {point.group(1)}; the packages under addons/ "
            f"declare {declared}")
    section = re.sub(r"\s+", " ", _architecture_section_6())
    # a dot inside a code span (`notifier.telegram`) does not end the sentence
    masked = re.sub(r"`[^`]*`", lambda m: m.group(0).replace(".", "\x00"), section)
    sentence = re.search(r"[^.]*\bTelegram\b[^.]*\.", masked)
    assert sentence, "architecture.md §6 no longer mentions Telegram, which docs/STATUS.md still lists as a leaving row"
    said = sentence.group(0).replace("\x00", ".")
    for must, why in ((" fallback", "does not call it the fallback"),
                      (f"`{registry.FALLBACK_ENV}=", "does not name the variable that declares it"),
                      (f"`{point.group(1)}`", "does not name its entry-point row"),
                      (f"`{package}`", "does not name the package that declares it"),
                      (" leaves", "does not say its module leaves the public tree")):
        assert must in said, f"§6's sentence about Telegram {why} ({must.strip()!r}): {said!r}"
