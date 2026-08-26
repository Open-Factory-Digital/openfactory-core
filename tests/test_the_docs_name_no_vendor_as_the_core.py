"""A vendor is a connector, and the documents must read that way too (ADR-0038, ADR-0040).

THE CODE ALREADY HELD THIS LINE. `test_the_core_addon_ledger.py` derives every vendor import in the
core from the AST and ratchets it — the list can only shrink. `test_the_platform_is_complete.py`
holds ADR-0038's half: no capability may live in `runtime/<channel>/`.

THE DOCUMENTS DID NOT, and on 2026-08-24, at the point of publishing, the gap was wide:

  · `docs/glossary.md` — the CANONICAL VOCABULARY — defined the worker as *"the always-on Fargate
    service"* and the job as *"an ephemeral Fargate task"*, and closed with a section titled
    "AWS names you'll see in the console";
  · `docs/autonomous-flow.md` described six of the nine pipeline stations as running on a "Fargate
    task", and priced the platform in one provider's line items;
  · `docs/architecture.md` §5 drew the runtime as that provider's product names, and listed a chat
    channel beside the panel as though the two were peers.

None of that was true of the code — ADR-0040 had already made the default `docker compose` on the
operator's own machine, with no cloud account at all. The documents simply never caught up with the
decision, and a reader forms their belief about what a product IS from the documents.

    The operator, 2026-08-24: *"Slack, AWS, all these vendor lock-ins can no longer be considered
    that — they are connectors, add-ons, as the product's solution already expects. That cannot be
    part of the core. You may mention it, but as an add-on to be developed."*
    And: *"Slack and AWS are the ones I am sure I used… but there may be others."*

So this is a CLASS guard, not a two-name one: the conceptual documents may not name any vendor's
product, and the documents that legitimately may are an explicit, short list.
"""

from __future__ import annotations

import pathlib
import re
import subprocess

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]

#: Product names belonging to one vendor's infrastructure. Not "cloud words" — `container`,
#: `worker`, `box` and `journal` are the platform's own vocabulary and appear everywhere.
#:
#: `azure` is deliberately NOT here on its own: Azure DevOps, Azure Repos, Azure Boards and Azure
#: Pipelines are ADAPTERS on axes that are born with two (ADR-0022), and naming an implementation
#: of an axis is the opposite of the defect — it is the evidence the axis is real.
#: AN ADD-ON PACKAGE'S NAME IS NOT A VENDOR'S PRODUCT. `openfactory-aws` is the package a reader
#: installs to get a cloud box, and the front door names it in exactly the framing this file
#: exists to enforce — "a cloud box is an add-on package". The lookbehind exempts the name and
#: nothing else: `on AWS` two words later still fires, and the verifier below proves both.
VENDOR_PRODUCTS = re.compile(
    r"\b(?<!openfactory-)(?:fargate|dynamodb|cloudwatch|app\s?runner|secrets\s+manager|elasticache"
    r"|ec2|ecs|ecr|rds|s3|ssm|iam|lambda|eks|gke|bigquery|pub/sub"
    r"|aws|gcp|google\s+cloud"
    r"|azure\s+(?:functions|blob|storage)"
    # THE ENGINE IS NOT THE SAAS. Plain `Temporal` is the open-source engine that ships as a
    # container in the compose stack — naming it is naming a dependency, like Postgres.
    # `Temporal Cloud` is that vendor's managed product, and in a conceptual document it
    # reads as a requirement the platform does not have.
    r"|temporal\s+cloud)\b", re.IGNORECASE)

#: The documents that MAY name a vendor's products, and the reason each one may.
#:
#: A SHORT, EXPLICIT LIST IS THE POINT. Anything not here is a conceptual document, and a
#: conceptual document that starts naming a provider is exactly the drift this file exists to
#: catch — including a document nobody has written yet.
#:
#: EVERY ENTRY IS EARNED, BOTH WAYS, and `test_the_documents_that_MAY_name_a_vendor_carry_the_framing`
#: is what makes that true of all of them rather than of the three it used to check (extended in
#: the pre-launch audit, 2026-08-26). An entry must NAME a vendor's product — a document that
#: names none needs no exemption, and one sitting here unused is a door standing open for the
#: day somebody fills it silently — and it must say, somewhere in its own words, what a vendor
#: IS to this platform: an add-on, a connector, an adapter. Seven entries were dropped that day
#: for naming none: the chat package's README, `core/05`, `engineering-lessons`, `operations`,
#: `reference/cli` and the two per-vendor setup guides. All seven still pass the neutral rule —
#: which is the point: they never needed the exemption.
MAY_NAME_A_VENDOR = {
    # ── the front door, where the vendor is named INSIDE the add-on framing ──────────────────
    # Both of these carry a local-vs-cloud column, or state the add-on rule outright; naming the
    # provider in the right-hand column is what makes "you do not need one" checkable rather than
    # a slogan. The framing test holds them to a NAMED sentence, not just the vocabulary.
    "docs/ONBOARDING.md",
    # the website's copy source. It leaves the public tree (docs/STATUS.md's table, 2026-08-26)
    # and stays here, so the exemption is still earned in the private repository and simply has
    # no subject in the export — `_docs()` asks git, and git there does not list it. Membership
    # costs nothing; a `read_text()` on it would be the defect, and none is left.
    "docs/site-guide.md",
    # ── documents that name a vendor in order to state the rule about it ─────────────────────
    # 00-vision's table literally reads "The Core names no vendor — no AWS, Slack, Claude,
    # GitHub, Postgres, Temporal". A guard that forbade that sentence would forbid the doctrine.
    "docs/core/00-vision.md",
    # the worked example of one realisation, banner and all — the two documents travel with
    # the cloud package since 2026-08-26 (docs/STATUS.md excludes `addons/` whole)
    "addons/openfactory-aws/docs/runtime-architecture.md",
    "addons/openfactory-aws/docs/DEPLOYMENT.md",
    # the operator's pages for a deployment on one cloud. Each drives `infra/`, which is that
    # package's directory and not this tree's, and each carries the banner that says so.
    "docs/configuration.md",
    # the reference deployment's incident page — it moved inside the cloud package on
    # 2026-08-26, so the exemption follows the file rather than the old path
    "addons/openfactory-aws/docs/runbook.md",
    "docs/rotation-and-retention.md",
    # what is true today, including which paths were proven on which infrastructure
    "docs/STATUS.md",
    # reference material: an environment variable that exists has to be named
    "docs/reference/configuration.md",
    # the add-on package's own page: it IS one vendor's realisation, says so in its first
    # line, and leaves the public tree with its package (docs/STATUS.md)
    "addons/openfactory-aws/README.md",
    # the dossier on where the core/add-on line falls, which must discuss both sides
    "docs/core/02-boundary.md",
    "docs/core/03-extraction-strategy.md",
    "docs/core/04-business-and-licensing.md",
    "docs/core/07-extensibility.md",
    "docs/core/01-reality-check.md",
    "docs/core/06-onboarding-and-project-shape.md",
    # decision records are history: an ADR describes the world on the day it was accepted
    # (they are matched by prefix below)
}

#: The platform's three words for what a vendor is to it — ADR-0038's own vocabulary, from the
#: sentence quoted in this file's docstring ("they are connectors, add-ons") and ADR-0022's axis
#: rule ("an adapter on an axis born with two"). A document may name a provider's products as
#: long as it says, somewhere, which of these the provider is. Deliberately NOT "optional": that
#: word appears in every document about anything, so a check that accepted it would pass on a
#: page describing the runtime as one vendor's console.
VENDOR_IS_A = re.compile(r"add-?on|connector|adapter", re.IGNORECASE)

#: History, not doctrine. An ADR that named a provider in 2026-07 is a record of that decision and
#: rewriting it would be the one thing an ADR directory forbids.
HISTORY_PREFIXES = ("docs/adr/",)


def _docs() -> list[str]:
    out = subprocess.run(["git", "ls-files", "-z", "*.md"], cwd=ROOT,
                         capture_output=True, text=True, timeout=120)
    assert out.returncode == 0, out.stderr[:200]
    return [p for p in out.stdout.split("\0") if p]


def _conceptual() -> list[str]:
    return [rel for rel in _docs()
            if rel not in MAY_NAME_A_VENDOR
            and not rel.startswith(HISTORY_PREFIXES)]


def test_no_conceptual_document_names_a_vendors_product():
    """The rule, over every document at once — including one added tomorrow."""
    conceptual = _conceptual()
    assert len(conceptual) > 5, f"only {len(conceptual)} conceptual documents — this measures nothing"

    offenders = []
    for rel in conceptual:
        text = (ROOT / rel).read_text()
        for hit in VENDOR_PRODUCTS.finditer(text):
            line = text.count("\n", 0, hit.start()) + 1
            offenders.append(f"{rel}:{line}  {hit.group(0)}")

    assert not offenders, (
        "these documents describe the platform in one vendor's product names — the platform's "
        "default is the operator's own machines and a cloud is an add-on (ADR-0040), so the "
        "vocabulary here is `worker` / `box` / `durable engine` / `journal`. If the document "
        "genuinely IS about one realisation, add it to MAY_NAME_A_VENDOR with the reason:\n  "
        + "\n  ".join(offenders))


def test_the_neutral_documents_still_SAY_that_a_cloud_is_possible():
    """The positive twin, and it is the one that stops this rule being satisfied by silence.

    Neutral does not mean "pretends clouds do not exist" — a reader deciding whether this fits a
    company that runs on one has to find the answer. What changes is the framing: an add-on, not
    the architecture."""
    architecture = (ROOT / "docs" / "architecture.md").read_text().lower()
    readme = (ROOT / "README.md").read_text().lower()

    assert "cloud" in architecture, (
        "architecture.md no longer mentions a cloud at all — the rule was satisfied by deleting "
        "the answer instead of by framing it")
    assert "no cloud account is required" in readme, (
        "the README stops promising the thing that makes the add-on framing true")
    assert "add-on" in architecture or "add-ons" in architecture


def test_a_chat_channel_is_never_presented_as_required():
    """ADR-0038's half, in prose. The panel is the reference surface; a channel is where a team
    that already talks somewhere gets the same thing delivered. A conceptual document naming one
    without saying so reads as a dependency."""
    named, unmarked = [], []
    for rel in _conceptual():
        text = (ROOT / rel).read_text()
        if not re.search(r"\b(slack|telegram|teams|discord)\b", text, re.IGNORECASE):
            continue
        named.append(rel)
        if not re.search(r"add-?on|optional|connector", text, re.IGNORECASE):
            unmarked.append(rel)

    assert named, "no conceptual document names a channel at all — this guard measures nothing"
    assert not unmarked, (
        "these name a chat channel and never say it is an add-on, so it reads as part of the "
        f"platform: {unmarked}")


def test_the_guard_can_SEE_the_shapes_it_is_named_for():
    """Verify the verifier, with the real lines that were in this tree on 2026-08-24."""
    was_true = [
        "| **Worker** (`sdlc-worker`) | The **always-on** Fargate service.",
        "## AWS names you'll see in the console (region `eu-west-2`)",
        "| CloudWatch `/ecs/sdlc-worker` | worker logs |",
        "| Secrets Manager `sdlc/*` | Claude token, bot key |",
        "     DynamoDB        ── cost telemetry        App Runner ── the web panel",
        "| 4 | **Clone** | `preparing` | Fargate task |",
    ]
    missed = [line for line in was_true if not VENDOR_PRODUCTS.search(line)]
    assert not missed, f"the pattern walks past lines that really were here: {missed}"

    # …and does not fire on the platform's own vocabulary, or this rule is unusable
    ours = ["the worker orchestrates and the box executes",
            "a throwaway Docker container, sized per ticket",
            "the durable engine holds every workflow's state",
            "the journal on disk carries cost and event telemetry"]
    false = [line for line in ours if VENDOR_PRODUCTS.search(line)]
    assert not false, f"the pattern fires on our own words: {false}"

    # …an add-on PACKAGE name is ours too, and the exemption is exactly that wide
    package = "│   └── sandbox/     a cloud box is an add-on package (openfactory-aws)"
    assert not VENDOR_PRODUCTS.search(package), "the pattern fires on an add-on package's name"
    assert VENDOR_PRODUCTS.search("a cloud box runs on AWS (openfactory-aws)").group(0) == "AWS", (
        "the package-name exemption swallowed a real vendor name beside it")


#: Two documents earn their exemption with a NAMED sentence rather than the vocabulary alone,
#: because each is somebody's first page and a reader forms their belief there. `architecture.md`
#: is not exempt at all — it is held to the neutral rule — and is checked here for the same
#: sentence, since it is the page that answers "does this need a cloud".
MUST_SAY = {
    "docs/ONBOARDING.md": ("add-on", "if you later add a cloud", "none of them a cloud"),
    "docs/architecture.md": ("add-on",),
}


@pytest.mark.parametrize("rel", sorted(MAY_NAME_A_VENDOR | set(MUST_SAY)))
def test_the_documents_that_MAY_name_a_vendor_carry_the_framing(rel):
    """The exemption is not a hole — for ANY entry on the list, which is what this checks since
    the pre-launch audit (2026-08-26); before it, three of twenty-four were held to anything.

    Two halves, and the first is the one a hand-kept list rots without. An entry must still NAME
    a vendor's product: five kept operator documents drove a directory that had left with the
    cloud package, and an exemption for a document that no longer needs one is a hole nobody is
    watching. And it must say what a vendor IS here — `VENDOR_IS_A`, the platform's own three
    words — because naming a provider without that framing is how a connector reads as the
    architecture."""
    path = ROOT / rel
    if not path.exists():
        pytest.skip(f"{rel} is not in this tree — it leaves with its package (docs/STATUS.md)")
    text = path.read_text()

    if rel in MAY_NAME_A_VENDOR:
        assert VENDOR_PRODUCTS.search(text), (
            f"{rel} names no vendor's product any more, so it does not need this exemption — "
            f"drop it from MAY_NAME_A_VENDOR and let the neutral rule hold it. An unused "
            f"exemption is a door standing open.")

    assert VENDOR_IS_A.search(text), (
        f"{rel} names a provider's products and never says what a provider IS to this platform "
        f"(an add-on, a connector, an adapter) — so it reads as the architecture. The platform's "
        f"default is the operator's own machines (ADR-0040); say so once, in this document's own "
        f"words.")

    for phrase in (MUST_SAY.get(rel) or ()):
        if phrase.lower() in text.lower():
            break
    else:
        assert rel not in MUST_SAY, (
            f"{rel} is somebody's first page and no longer says anywhere that the provider is "
            f"optional — one of {MUST_SAY[rel]} has to be in it")
