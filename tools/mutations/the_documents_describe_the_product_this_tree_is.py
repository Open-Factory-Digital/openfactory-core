"""Package 4's proof: break what each guard claims to protect and watch it go red.

TWO KINDS OF CUT, DELIBERATELY MIXED. Half of these break the CODE — flip the manifest default,
drop a harness from the registry, move the cache mount, remove the fallback's condition, change a
terraform count. Those are the rows that prove a guard reads the source of truth rather than a
second copy of a string: a guard that hard-coded `true`, or `/cache`, or `30`, survives them.

The other half break the DOCUMENTS the way a hostile reviewer would — keeping the vocabulary and
inverting the meaning ("defaults to `false`"), reaching the same defect through a different
spelling ("The layer is opt-in.", added somewhere else on the page), and putting back the exact
sentence that shipped ("not yet built", "keep last 10", the wrapped "Leave it\\noff (the
default)"). Those are the rows that prove the guard is not decoration.

Point-in-time, as every plan here is: anchors rot as the code moves and a rotted one fails loudly
on rerun rather than passing quietly.
"""

TEST = "tests/test_the_documents_describe_the_product_this_tree_is.py"

MUTATIONS = [
    # ── (a) the knowledge layer's default ──────────────────────────────────────────────────────
    ("the manifest's default flips, and the page's rendered sentence must flip with it",
     "openfactory/contracts/manifest.py",
     "    knowledge_map: bool = True",
     "    knowledge_map: bool = False"),

    ("THE HOSTILE CUT: the page keeps the field name and the word 'defaults' and inverts it",
     "docs/knowledge-layer.md",
     "**`knowledge_map` defaults to `true`**",
     "**`knowledge_map` defaults to `false`**"),

    ("…and the same defect through a different spelling, added elsewhere on the page",
     "docs/knowledge-layer.md",
     "", "\n\nThe layer is opt-in and a project switches it on when it wants it.\n"),

    ("…and the wrapped sentence a line-by-line scan reads as absent",
     "docs/knowledge-layer.md",
     "", "\n\nThen set it in the project's file. Leave it\noff (the default) to keep "
         "today's behaviour.\n"),

    # ── (b) what the operations page calls built ───────────────────────────────────────────────
    ("the composition root stops constructing the promotion chain the page calls built",
     "openfactory/factory.py",
     "    return PromotionRunner(",
     "    return _promotion_runner_type()("),

    ("the page puts the shipped post-PR lifecycle back in the future",
     "docs/operations.md",
     "Beyond the PR (D-12 — **built**)",
     "Beyond the PR (D-12 — not yet built)"),

    ("the box mounts the dependency cache somewhere else than the page says",
     "openfactory/adapters/sandbox/container.py",
     'run_cmd += ["-v", f"{self.cache_volume}:/cache"]',
     'run_cmd += ["-v", f"{self.cache_volume}:/deps"]'),

    ("the cache is mounted even when nobody declared one — 'off unless you ask' stops being true",
     "openfactory/adapters/sandbox/container.py",
     "        if self.cache_volume:",
     "        if True:"),

    ("the page states a mount point the argv does not carry",
     "docs/operations.md",
     "volume at `/cache` (`openfactory/adapters/sandbox/container.py`)",
     "volume at `/deps` (`openfactory/adapters/sandbox/container.py`)"),

    ("THE HOSTILE CUT: the state label stops being a fallback and is written unconditionally",
     "openfactory/adapters/tracker/github.py",
     "        if self.board is None or not moved:",
     "        if True:"),

    ("the label prefix is renamed and the page goes on naming the old one",
     "openfactory/adapters/tracker/github.py",
     '_STATE_LABEL_PREFIX = "openfactory:"',
     '_STATE_LABEL_PREFIX = "of:"'),

    ("the page puts the board movement back the way round it was",
     "docs/operations.md",
     "the card's **Status column** is the movement",
     "labels are the v1 board movement and a richer implementation sits behind the seam"),

    # ── (c) the retention counts ───────────────────────────────────────────────────────────────
    ("the terraform's worker count moves and the page's table does not",
     "infra/terraform/alerting.tf",
     "countNumber = 30",
     "countNumber = 25"),

    ("the page re-certifies the wrong number, exactly as it did",
     "docs/rotation-and-retention.md",
     "| **30** |",
     "| **10** |"),

    # ── (d) the agents page ────────────────────────────────────────────────────────────────────
    ("a fourth harness leaves the registry while the page still lists it",
     "openfactory/adapters/agent/registry.py",
     '    "opencode": _opencode,',
     ""),

    ("the page lists three of the four the registry ships",
     "docs/agents.md",
     "`claude_code`, `codex`, `kimi` and `opencode`",
     "`claude_code`, `codex` and `kimi`"),

    ("the page states a harness count the registry does not hold",
     "docs/agents.md",
     "**Four harnesses ship**",
     "**Three harnesses ship**"),

    ("the reviewer row points back at the prompt file that has never existed",
     "docs/agents.md",
     "`openfactory/adapters/reviewer/harness.py` → `build_review_prompt` |\n| **tech lead**",
     "`openfactory/org_defaults/roles/reviewer.md` |\n| **tech lead**"),

    ("…and at a symbol that file does not define",
     "docs/agents.md",
     "`openfactory/adapters/reviewer/harness.py` → `build_review_prompt` |\n| **tech lead**",
     "`openfactory/adapters/reviewer/harness.py` → `build_reviewer_prompt` |\n| **tech lead**"),

    ("the 'where to change things' table sends a reader to a path this tree does not carry",
     "docs/agents.md",
     "the registry → `product.admins` |",
     "`deploy/registry.yaml` → `product.admins` |"),

    ("the page offers the retired alias as the field to set, with nothing marking it as one",
     "docs/agents.md",
     "", "\n| who may authorise | the registry → `product.slack_admins` |\n"),

    ("the contract renames the field and the page keeps the old canonical name",
     "openfactory/contracts/product.py",
     '    admins: list[str] = Field(\n        default_factory=list, '
     'validation_alias=AliasChoices("admins", "slack_admins"))\n\n    #: What this agent calls',
     '    approvers: list[str] = Field(\n        default_factory=list, '
     'validation_alias=AliasChoices("admins", "slack_admins"))\n\n    #: What this agent calls'),

    # ── (e) the worker's diagnostic ────────────────────────────────────────────────────────────
    ("THE REGRESSION ITSELF: the first sentence wins unconditionally again",
     "openfactory/runtime/temporal/worker.py",
     "    return sentence if len(sentence) > len(truncated) else truncated",
     "    return sentence or truncated"),

    ("…and the other direction: the sentence stops being bounded",
     "openfactory/runtime/temporal/worker.py",
     "len(first) <= _SENTENCE_CAP",
     "len(first) <= 10 ** 9"),

    # ── (f) the small ones ─────────────────────────────────────────────────────────────────────
    ("one vendor's credential variable is pinned in the compose environment again",
     "docker-compose.yml",
     "      OPENFACTORY_GH_APP_ID: ${OPENFACTORY_GH_APP_ID:-}",
     "      JIRA_API_TOKEN: ${JIRA_API_TOKEN:-}\n"
     "      OPENFACTORY_GH_APP_ID: ${OPENFACTORY_GH_APP_ID:-}"),

    ("the twin: the worker stops forwarding the file the vendors' variables were moved into",
     "docker-compose.yml",
     "    env_file:\n      - path: .env.compose\n        required: false\n    environment:\n"
     "      TEMPORAL_ADDRESS: temporal:7233\n      TEMPORAL_NAMESPACE: default\n"
     "      # Where jobs run.",
     "    environment:\n"
     "      TEMPORAL_ADDRESS: temporal:7233\n      TEMPORAL_NAMESPACE: default\n"
     "      # Where jobs run."),

    ("the quickstart goes back to a command that only runs from the repository root",
     "addons/openfactory-aws/README.md",
     "pip install .                        # from THIS directory, where this README is\n",
     ""),

    ("the lesson names the variable under the spelling the record keeps, and they disagree again",
     "docs/engineering-lessons.md",
     "today `OPENFACTORY_AGENT_TOKENS`",
     "today `SDLC_AGENT_TOKENS`"),
]
