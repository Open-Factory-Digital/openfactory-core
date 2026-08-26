"""The migration code that answered to the platform's former name has left; these prove the
guards that keep it out. Each mutation grows one shape of it back — a constant, a reader, a
shim, a remedy sentence, a fixture fallback, a console script — and the guard must go red.

Run: .venv/bin/python tools/mutate.py tools/mutations/public_no_legacy_name.py
"""

NS = "tests/test_the_namespace_is_the_products_name.py"
ENV = "tests/test_the_environment_carries_the_products_name.py"
BRANCH = "tests/test_the_branch_carries_the_products_name.py"
DOCS = "tests/test_a_remedy_names_a_document_that_exists.py"
PAST = "tests/test_the_product_carries_no_ones_past.py"
WHEEL = "tests/test_the_wheel_ships_what_the_platform_needs.py"
ONBOARD = "tests/test_onboard_proposes_a_measured_setup.py"
DOCTOR = "tests/test_doctor.py"
GATE = "tests/test_the_proof_gates_pickup.py"
KNOWLEDGE = "tests/test_knowledge_pipeline.py"
DOORS = "tests/test_a_repository_on_the_former_name_is_refused_at_every_door.py"

TEST = NS

MUTATIONS = [
    # ── the refusal ────────────────────────────────────────────────────────────────────────────
    ("the refusal becomes a silent read of the retired path",
     "openfactory/namespace.py",
     "        raise RetiredNamespace(\n            f\"project",
     "        return root / old_rel\n        raise RetiredNamespace(\n            f\"project"),
    ("the refusal stops saying what to rename",
     "openfactory/namespace.py",
     "            f\"`{old_rel}`, which is this platform's former name and is not read. "
     "Rename the \"\n"
     "            f\"directory `{RETIRED_DIR}/` to `{DIR}/` in that repository; nothing under \"\n"
     "            f\"`{RETIRED_DIR}/` is read.\")",
     "            f\"`{old_rel}`, which is not read.\")"),
    ("the manifest loader folds the refusal into a plain missing",
     "openfactory/loader.py",
     "    manifest_file = namespace.resolve(repo_root, project.manifest_path, "
     "project=project.name)",
     "    try:\n"
     "        manifest_file = namespace.resolve(repo_root, project.manifest_path,\n"
     "                                          project=project.name)\n"
     "    except namespace.RetiredNamespace:\n"
     "        manifest_file = repo_root / project.manifest_path"),
    ("the product module folds the retired name into 'missing'",
     "openfactory/product/loader.py",
     "        return None, str(exc)",
     "        return None, f\"{DOCS_MANIFEST} is missing from the repository root\""),
    # ── no constant, no reader ─────────────────────────────────────────────────────────────────
    ("a second directory name comes back as a constant",
     "openfactory/namespace.py",
     "RETIRED_DIR = \".sdlc\"",
     "RETIRED_DIR = \".sdlc\"\nLEGACY_DIR = \".sdlc\""),
    ("the operator path migrates from the old home again",
     "openfactory/namespace.py",
     "    return Path.home() / DIR / filename",
     "    new = Path.home() / DIR / filename\n"
     "    old = Path.home() / RETIRED_DIR / filename\n"
     "    if not new.exists() and old.exists():\n"
     "        import shutil\n"
     "        new.parent.mkdir(parents=True, exist_ok=True)\n"
     "        shutil.copy2(old, new)\n"
     "    return new"),
    ("the working label's old spellings come back",
     "openfactory/orchestrator/machine.py",
     "_BOT_WORKING_LABEL = \"openfactory-working\"",
     "_BOT_WORKING_LABEL = \"openfactory-working\"\n_LEGACY_WORKING_LABELS = (\"sdlc-working\",)"),
    ("the tracker sweeps the old state prefix again",
     "openfactory/adapters/tracker/github.py",
     "            stale = [lbl for lbl in labels if lbl.startswith(_STATE_LABEL_PREFIX) "
     "and lbl != want]",
     "            stale = [lbl for lbl in labels\n"
     "                     if lbl.startswith((_STATE_LABEL_PREFIX, \"sdlc:\")) and lbl != want]"),
    ("the knowledge fetch reads the old branch again",
     "openfactory/knowledge/pipeline.py",
     "    if rc != 0:\n        # No published bundle yet",
     "    if rc != 0:\n"
     "        rc, out = _git(\"clone\", \"--depth\", \"1\", \"--single-branch\", \"--branch\",\n"
     "                       \"sdlc-knowledge\", remote_url, str(tmp / \"pub\"))\n"
     "    if rc != 0:\n        # No published bundle yet"),
    ("the box stream parser hears the old prefix again",
     "openfactory/runtime/fargate/launcher.py",
     "        if not s.startswith(_EVENT_PREFIX):",
     "        if not s.startswith((_EVENT_PREFIX, \"SDLC_EVENT:\")):"),
    ("the Slack bot honours the old button ids again",
     "openfactory/runtime/slack/bot.py",
     "        if action_id not in (APPROVE_ACTION, REJECT_ACTION):",
     "        if action_id not in (APPROVE_ACTION, REJECT_ACTION, \"sdlc_confirm_approve\"):"),
    ("the container name strips the old prefix again",
     "openfactory/adapters/sandbox/container.py",
     "    tail = safe_branch.removeprefix(\"openfactory-\") or safe_branch",
     "    tail = safe_branch.removeprefix(\"openfactory-\").removeprefix(\"sdlc-\") "
     "or safe_branch"),
    # ── the sentences a person reads ───────────────────────────────────────────────────────────
    ("the action summary names the retired manifest",
     "openfactory/actions/catalog.py",
     "            summary=f\"read a repository and propose what its {namespace.MANIFEST} "
     "should say — \"",
     "            summary=\"read a repository and propose what its .sdlc/project.yaml "
     "should say — \""),
    ("the doctor's conflict remedy names the retired manifest",
     "openfactory/doctor.py",
     "            f\"{namespace.PRODUCT_MANIFEST}, or `docs_repo:` in this repo's "
     "{namespace.MANIFEST}. \"",
     "            f\"{namespace.PRODUCT_MANIFEST}, or `docs_repo:` in this repo's "
     ".sdlc/project.yaml. \""),
    ("the product warnings name the retired manifest",
     "openfactory/product/config.py",
     "    manifest_rel = getattr(project, \"manifest_path\", None) or namespace.MANIFEST",
     "    manifest_rel = \".sdlc/project.yaml\""),
    ("the product warnings ignore the project's own manifest path",
     "openfactory/product/config.py",
     "    manifest_rel = getattr(project, \"manifest_path\", None) or namespace.MANIFEST",
     "    manifest_rel = namespace.MANIFEST"),
    ("the wide scan goes blind",
     NS,
     "OLD_NAME = re.compile(r\"(?<![A-Za-z0-9])sdlc(?![A-Za-z0-9])\", re.IGNORECASE)",
     "OLD_NAME = re.compile(r\"(?<![A-Za-z0-9])sdlc_never(?![A-Za-z0-9])\", re.IGNORECASE)"),
    # ── the environment ────────────────────────────────────────────────────────────────────────
    ("an adoption shim grows back in the environment module",
     "openfactory/environ.py",
     "",
     "\n\nLEGACY_ENV_PREFIX = \"SDLC_\"\n\n\n"
     "def adopt_legacy_environment() -> list[str]:\n"
     "    adopted = []\n"
     "    for name in sorted(os.environ):\n"
     "        if name.startswith(LEGACY_ENV_PREFIX):\n"
     "            os.environ.setdefault(ENV_PREFIX + name[len(LEGACY_ENV_PREFIX):],\n"
     "                                  os.environ[name])\n"
     "            adopted.append(name)\n"
     "    return adopted\n",
     ENV),
    ("a reader serves the old spelling",
     "openfactory/environ.py",
     "    return (os.environ.get(SSM_PREFIX_VAR) or \"\").strip().rstrip(\"/\")",
     "    return (os.environ.get(SSM_PREFIX_VAR) or os.environ.get(\"SDLC_SSM_PREFIX\")\n"
     "            or \"\").strip().rstrip(\"/\")",
     ENV),
    ("the scrub forgets the forge token",
     "openfactory/adapters/sandbox/worktree.py",
     "    \"OPENFACTORY_FORGE_TOKEN\",\n    \"OPENFACTORY_BOT_TOKEN\",",
     "    \"OPENFACTORY_BOT_TOKEN\",",
     ENV),
    # ── the branch ─────────────────────────────────────────────────────────────────────────────
    ("a job branch is minted under the old prefix",
     "openfactory/namespace.py",
     "    return f\"{BRANCH_PREFIX}/{str(ticket_id).lstrip('#')}\"",
     "    return f\"sdlc/{str(ticket_id).lstrip('#')}\"",
     BRANCH),
    ("the runner asks a remote for the branch again",
     "openfactory/orchestrator/machine.py",
     "        return namespace.job_branch(ticket.id)",
     "        self.forge.push_remote()\n        return namespace.job_branch(ticket.id)",
     BRANCH),
    # ── the stale document path ────────────────────────────────────────────────────────────────
    ("the refusal points at a document that does not exist",
     "openfactory/cli_refusals.py",
     "        \"(docs/setup/github.md). `openfactory doctor <project>` reports which one this \"",
     "        \"(docs/setup/github-app.md). `openfactory doctor <project>` reports which one "
     "this \"",
     DOCS),
    ("the doc-path scan goes blind",
     DOCS,
     "DOC_PATH = re.compile(r\"docs/[\\w./-]+\\.md\")",
     "DOC_PATH = re.compile(r\"docz/[\\w./-]+\\.md\")",
     DOCS),
    # ── the former product name in the suite ───────────────────────────────────────────────────
    # THE FORMER NAME IS ASSEMBLED, NOT SPELLED: the guard these two prove is a text scan over
    # every published file, this plan included, and it self-exempts one file only. Adjacent
    # literals join at compile time, so the mutant plants the whole word while this file never
    # contains it.
    ("the author's fixture directory comes back as the default",
     "tests/demo_projects.py",
     "_DEFAULT = \"openfactory-fixtures\"",
     "_DEFAULT = \"" "Dark" "Factory" "DemoProjects\"",
     PAST),
    ("a test module hardcodes the author's directory again",
     "tests/test_the_proposal_covers_the_floor.py",
     "FIXTURES = demo_projects_root()",
     "FIXTURES = Path.home() / \"Projects/" "Dark" "Factory" "DemoProjects\"",
     PAST),
    # ── the console script ─────────────────────────────────────────────────────────────────────
    ("a second console script ships in the wheel",
     "pyproject.toml",
     "openfactory = \"openfactory.cli:app\"",
     "openfactory = \"openfactory.cli:app\"\nsdlc = \"openfactory.cli:app\"",
     WHEEL),
    # ── the doors the review found folded (2026-08-25) ─────────────────────────────────────────
    ("the onboarding door reads the refusal as 'undeclared' and writes a second manifest",
     "openfactory/onboarding/onboard.py",
     "        except namespace.RetiredNamespace as exc:\n"
     "            # A REPOSITORY STILL ON THE DIRECTORY'S RETIRED NAME IS REFUSED HERE, BY NAME — "
     "before\n"
     "            # anything is inferred or written. The refusal is a `FileNotFoundError`, and the "
     "arm\n"
     "            # below would read it as \"undeclared\": infer a manifest, write it under the "
     "current\n"
     "            # name and open a pull request that never mentions the one the repository has — "
     "the\n"
     "            # second-manifest defect above, back on the first door a new client walks "
     "through\n"
     "            # (review, 2026-08-25). The sentence says what to rename; this verb does nothing "
     "else.\n"
     "            out.detail = str(exc)\n"
     "            return out\n"
     "        except FileNotFoundError:\n",
     "        except FileNotFoundError:\n",
     ONBOARD),
    ("the doctor's rename-only arm is deleted: the refusal is routed into onboarding",
     "openfactory/doctor.py",
     "    except namespace.RetiredNamespace as exc:\n"
     "        # A REPOSITORY STILL ON THE DIRECTORY'S RETIRED NAME. The loader's sentence already\n"
     "        # says what to rename; the remedy must say NOTHING ELSE. The missing-manifest arm\n"
     "        # below sends the reader to `openfactory onboard`, which reads a repository and\n"
     "        # proposes a manifest for it — for THIS repository that is a second manifest beside\n"
     "        # the one it has (review, 2026-08-25: two doors, two contradictory remedies for one\n"
     "        # repository). Onboarding refuses it by the same sentence; the doctor points at the\n"
     "        # rename and at nothing that infers or writes.\n"
     "        return Finding(\n"
     "            \"manifest\", False, str(exc),\n"
     "            f\"rename the directory `{namespace.RETIRED_DIR}/` to `{namespace.DIR}/` "
     "in that \"\n"
     "            f\"repository and re-run this check. Nothing needs proposing: the manifest "
     "is \"\n"
     "            f\"there, under the platform's former name, and nothing under \"\n"
     "            f\"`{namespace.RETIRED_DIR}/` is read\",\n"
     "            next_step=f\"rename `{namespace.RETIRED_DIR}/` to `{namespace.DIR}/` in the \"\n"
     "                      f\"repository — the file itself is right where it is; only the "
     "directory \"\n"
     "                      f\"carries the former name\")\n"
     "    except FileNotFoundError as exc:\n",
     "    except FileNotFoundError as exc:\n",
     DOCTOR),
    ("the doctor's rename arm swallows a plainly MISSING manifest too (the twin)",
     "openfactory/doctor.py",
     "    except namespace.RetiredNamespace as exc:\n",
     "    except FileNotFoundError as exc:\n",
     DOCTOR),
    ("the doctor's rename remedy also routes into onboarding",
     "openfactory/doctor.py",
     "            f\"rename the directory `{namespace.RETIRED_DIR}/` to `{namespace.DIR}/` "
     "in that \"\n",
     "            f\"run `openfactory onboard <project> --yes`, or rename the directory "
     "`{namespace.RETIRED_DIR}/` to `{namespace.DIR}/` in that \"\n",
     DOCTOR),
    ("the freshness check rewrites the refusal as 'not on the base branch yet'",
     "openfactory/box_prove.py",
     "    except namespace.RetiredNamespace as exc:\n"
     "        # A REPOSITORY STILL ON THE DIRECTORY'S RETIRED NAME. The arm below REWRITES the\n"
     "        # message — \"not on the base branch yet\" — and for this repository that is a "
     "false\n"
     "        # cause: the manifest IS on the base branch, under a directory the platform does "
     "not\n"
     "        # read, and the sentence saying what to rename was the one thing dropped (review,\n"
     "        # 2026-08-25). The gate holds, and it holds with the rename in the reason.\n"
     "        return str(exc)\n"
     "    except FileNotFoundError:\n",
     "    except FileNotFoundError:\n",
     GATE),
    ("the client-visible knowledge branch is renamed",
     "openfactory/knowledge/pipeline.py",
     "KNOWLEDGE_BRANCH = \"openfactory-knowledge\"",
     "KNOWLEDGE_BRANCH = \"openfactory-knowledge-2\"",
     KNOWLEDGE),
    # ── the shipped files that are not Python ──────────────────────────────────────────────────
    ("the panel adopts the old token name again",
     "openfactory/api/panel.html",
     "",
     "\n<script>const legacyToken = localStorage.getItem('sdlc_token');</script>\n"),
    ("the shipped-file scan loses its subject",
     NS,
     "SHIPPED_NOT_PYTHON = (\".html\", \".yaml\", \".yml\", \".md\", \".json\")",
     "SHIPPED_NOT_PYTHON = (\".never\",)"),
    # the two cuts the count floor could not see (review, 2026-08-26): eleven of sixteen shipped
    # files are Markdown, so the ONLY .html and the four .yaml files leave and ten still clear
    ("the shipped-file scan stops reading the panel — the only .html the package ships",
     NS,
     "SHIPPED_NOT_PYTHON = (\".html\", \".yaml\", \".yml\", \".md\", \".json\")",
     "SHIPPED_NOT_PYTHON = (\".yaml\", \".yml\", \".md\", \".json\")"),
    ("the shipped-file scan stops reading the deployment's floor and the presets",
     NS,
     "SHIPPED_NOT_PYTHON = (\".html\", \".yaml\", \".yml\", \".md\", \".json\")",
     "SHIPPED_NOT_PYTHON = (\".html\", \".yml\", \".md\", \".json\")"),
    # ── every door asks the one reader ─────────────────────────────────────────────────────────
    ("`env read` decides 'existing' by the current name alone again",
     "openfactory/actions/catalog.py",
     "        destination = namespace.resolve(\n"
     "            checkout, manifest_path, project=getattr(project, \"name\", \"\") or "
     "checkout.name)\n",
     "        destination = checkout / manifest_path\n",
     DOORS),
    ("`env apply` decides 'existing' by the current name alone again — and writes",
     "openfactory/actions/catalog.py",
     "        namespace.resolve(checkout, str(found.manifest_path), project=found.name)\n"
     "    except namespace.RetiredNamespace as exc:\n",
     "        pass\n"
     "    except namespace.RetiredNamespace as exc:\n",
     DOORS),
    ("`env apply` refuses without saying what to rename",
     "openfactory/actions/catalog.py",
     "        return refused(CONFLICT, str(exc), verb=\"apply\", measured_on=where, wrote=None,\n"
     "                       project=found.name)\n",
     "        return refused(CONFLICT, \"the manifest already exists\", verb=\"apply\",\n"
     "                       measured_on=where, wrote=None, project=found.name)\n",
     DOORS),
    ("`env apply` skips the question when the file lands elsewhere",
     "openfactory/actions/catalog.py",
     "        namespace.resolve(checkout, str(found.manifest_path), project=found.name)\n",
     "        if not out:\n"
     "            namespace.resolve(checkout, str(found.manifest_path), project=found.name)\n",
     DOORS),
    # the review's two survivors (2026-08-26): each flag is a road around the resolve call
    ("`env apply --force` walks around the refusal",
     "openfactory/actions/catalog.py",
     "        namespace.resolve(checkout, str(found.manifest_path), project=found.name)\n",
     "        if not replace:\n"
     "            namespace.resolve(checkout, str(found.manifest_path), project=found.name)\n",
     DOORS),
    ("`env apply --pr` proposes the second manifest as a pull request",
     "openfactory/actions/catalog.py",
     "        namespace.resolve(checkout, str(found.manifest_path), project=found.name)\n",
     "        if clone_to_discard is None:\n"
     "            namespace.resolve(checkout, str(found.manifest_path), project=found.name)\n",
     DOORS),
    ("the product plan decides 'declared' by the current name alone again",
     "openfactory/product/onboard.py",
     "        declared = namespace.resolve(docs_root, PRODUCT_YAML, project=project.name)\n",
     "        declared = docs_root / PRODUCT_YAML\n",
     DOORS),
    ("`product init --write` prints the plan's refusal and writes anyway",
     "openfactory/cli.py",
     "        if result.refusal:\n"
     "            typer.echo(f\"✗ {result.refusal}\")\n"
     "            raise typer.Exit(1)\n",
     "        if result.refusal:\n"
     "            typer.echo(f\"✗ {result.refusal}\")\n",
     DOORS),
    ("`project init` scaffolds over the retired name again",
     "openfactory/cli.py",
     "            dest = namespace.resolve(Path(project.repo_path).expanduser(),\n"
     "                                     project.manifest_path, project=name)\n",
     "            dest = Path(project.repo_path).expanduser() / project.manifest_path\n",
     DOORS),
    ("`project init` refuses the scaffold and exits zero",
     "openfactory/cli.py",
     "    if board_failed or manifest_refused:\n",
     "    if board_failed:\n",
     DOORS),
    # ── the guard file's own hygiene (review, 2026-08-26) ──────────────────────────────────────
    # the CLI imported lazily, i.e. for the first time UNDER the fixture's registry patch: its
    # import-time `ProjectRegistry` binds to the double, and the fixture's teardown must see it.
    # THE TARGET IS ONE `product init` TEST, so that it is the process's first import of the
    # CLI — the shape the review measured (the file alone, `-k`, or a random order that puts
    # this door first); in the file's own order the `--pr` tests import the CLI cleanly first,
    # so the whole file would pass over this cut and prove nothing about it. The stand-in
    # ignores dunder probes because collection asks every module-level object for `__test__`,
    # and a stand-in that imported on that probe would load the CLI before any patch — a cut
    # that survived by accident when first written (measured: `LAZY IMPORT of __test__`).
    ("the guard file imports the door lazily again — after the registry is patched",
     DOORS,
     "from openfactory import cli, namespace\n",
     "import importlib\n\n"
     "from openfactory import namespace\n\n\n"
     "class _LazyDoor:\n"
     "    def __getattr__(self, name):\n"
     "        if name.startswith(\"__\"):\n"
     "            raise AttributeError(name)\n"
     "        return getattr(importlib.import_module(\"openfactory.cli\"), name)\n\n\n"
     "cli = _LazyDoor()\n",
     DOORS + "::test_product_init_write_stops_at_the_refusal_and_pushes_nothing"),
]
