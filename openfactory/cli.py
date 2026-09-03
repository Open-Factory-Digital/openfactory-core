"""`openfactory` — the CLI. Project-first: the framework drives many projects, and every
command takes a project handle. Adding a project is data, not code.

    openfactory project add myapp ~/Projects/myapp --repo owner/myapp
    openfactory project add web   ~/Projects/web   --repo owner/web
    openfactory project init myapp      # scaffold .openfactory/project.yaml in the repo
    openfactory conformance myapp       # is it runnable?
    openfactory run myapp 142           # drive issue #142 (walking skeleton)
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

import typer
from dotenv import load_dotenv

from openfactory import namespace
from openfactory.cli_refusals import speaks_plainly
from openfactory.contracts import JobState
from openfactory.contracts.project import Project, ProviderRef
from openfactory.factory import build_runner, resolve_box_image
from openfactory.loader import load_manifest
from openfactory.policy import check
from openfactory.registry import ProjectRegistry

log = logging.getLogger("openfactory.cli")

app = typer.Typer(help="Run software tickets autonomously with coding agents.")
project_app = typer.Typer(help="Register and manage projects.")
app.add_typer(project_app, name="project")


def _load_environment() -> None:
    """Pick up `.env` (bot credentials) — WHEN THE CLI RUNS, never when it is imported.

    This used to be a bare `load_dotenv()` at module scope, and importing a module then mutated
    the whole process's environment. The test suite is what found it: `pytest-randomly` put a test
    that imports this module ahead of the product-module tests, and those then held live
    `OPENFACTORY_GH_APP_*` credentials and made a real authenticated call to GitHub. It surfaced as
    a
    `ReadTimeout` and passed in isolation, which is the shape of the bug that never gets fixed.

    The timeout was the mild symptom. Those are write-capable credentials for a real client's
    repository, and the same import would have armed any test that reaches a write path — on some
    seeds and not others.

    A library module must not have side effects on import. The CLI is an entry point and may load
    its environment; it does so here, from a callback that runs before any command.
    """
    load_dotenv()


@app.callback()
def _main() -> None:
    """Runs before every command (including subcommands), so every entry loads the same way."""
    _load_environment()

_MANIFEST_TEMPLATE = """\
# .openfactory/project.yaml — this project's plug into the platform contract.
# The framework knows nothing about this project except what is declared here.
# This is a STARTER — see docs/project.yaml.example for the full annotated reference.
version: 1
base_branch: main

# Autonomy at merge: "human" = bot opens the PR, a human merges; "auto" = merges itself when
# gates are green + review didn't reject + no high-risk component touched.
merge_policy: human

# ADR-0014 (defaults shown — omit to accept). planner_stage false = single agent (plan+code in
# one pass). review_mode advisory = the review comments on the PR but never blocks/repairs.
# planner_stage: false
# review_mode: advisory

setup:
  - "pip install -e '.[dev]'"   # how to install deps in the ephemeral workspace
  # - "npm ci"

# Repo-wide validation — the REAL quality floor. The platform runs these and reads the exit
# codes; it does NOT trust the agent to have run them. Map them to YOUR repo's commands.
validate:
  test: "pytest -q"
  # THE FLOOR REQUIRES A `security` ROLE AND THIS TEMPLATE DID NOT DECLARE ONE. `openfactory project
  # init`
  # therefore wrote a manifest that `openfactory conformance` — the very next step in ONBOARDING.md
  # —
  # refused. A client following our own script, with our own file, was told they had done it wrong,
  # and there was nothing they could have done differently.
  #
  # ADVISORY, so a starter project passes its floor on day one without anything being imposed: it
  # reports findings and never blocks a merge. A first scan of any real codebase reports the
  # accumulated debt of its whole history, and none of that is the first ticket's fault. A client
  # who wants it blocking sets `advisory: false`, deliberately.
  #
  # semgrep because it is free, offline-installable and needs no licence conversation — the same
  # reasoning as the `security-oss` preset, inlined here because presets attach to a COMPONENT's
  # stack (`components[].stack`) and a starter project declares no components.
  security:
    command: "semgrep --config=auto --error --quiet ."
    advisory: true
    timeout_minutes: 20
  # lint: "ruff check ."
  # type: "mypy ."

docs:
  constraints: docs/adr/**        # ADRs — always loaded (the constitution)
  # architecture: docs/architecture/**
  # guidelines: [.openfactory/guidelines/execution.md]

# Declare components only if the repo is polyglot / has risk zones; each maps a diff area to a
# stack (preset) + risk. A risk: high component always stays human-gated, even on auto.
components: {}
  # backend:
  #   path: app/
  #   stack: python
  #   risk: normal
  # infra:
  #   path: terraform/
  #   stack: terraform
  #   risk: high

# Post-merge deploy watch (optional — ADR-0005): observe your repo's CI deploy after merge.
# post_merge_deploy: { workflow: deploy.yml, env: dev, timeout_minutes: 30 }
"""


@project_app.command("add")
def project_add(
    name: str,
    repo_path: str = typer.Argument(..., help="Local path or clone URL of the repo"),
    provider: str = typer.Option(None, help="Vendor for all axes: github | azure_devops | jira. "
                                            "Inferred from a dev.azure.com clone URL; "
                                            "otherwise github"),
    repo: str = typer.Option(None, help="Repo/board ref, e.g. owner/name (GitHub: inferred from "
                                        "a clone URL when omitted)"),
    board_owner: str = typer.Option(None, help="Board owner (GitHub Projects org/user)"),
    board_number: str = typer.Option(None, help="Board number (GitHub Projects v2)"),
    organization: str = typer.Option(None, help="Azure DevOps organisation (read from the clone "
                                                "URL when it is a dev.azure.com one)"),
    ado_project: str = typer.Option(None, "--ado-project",
                                    help="Azure DevOps project (read from the clone URL)"),
    repository: str = typer.Option(None, help="Azure Repos repository name (read from the "
                                              "clone URL)"),
    work_item_type: str = typer.Option(
        None, "--work-item-type",
        help="Azure Boards work item type the factory writes. Basic process: Issue (the "
             "default); Agile: 'User Story'; Scrum: 'Product Backlog Item' — the wrong one is "
             "a 400 at the first ticket"),
    token_env: str = typer.Option(
        None, help="Name of the env var holding THIS project's credential — the registry names "
                   "the variable, the environment holds the value. Unset: the vendor's default "
                   "(AZURE_DEVOPS_PAT, JIRA_API_TOKEN, OPENFACTORY_BOT_TOKEN)"),
    model: str = typer.Option(
        None, help="Which model the coding agent runs for this project, in the harness's own "
                   "naming (e.g. claude-fable-5, a Bedrock profile ARN). Unset: the harness's "
                   "default. Per-role values: `openfactory project set-model`"),
    # DEFAULTS TO UNSET, not to "pt-BR" — the same reason `openfactory run --image` defaults to
    # unset
    # (ADR-0037 D4): a flag that always carries a value can never let the model's OWN default win,
    # so passing nothing here and passing --language pt-BR would become indistinguishable.
    language: str = typer.Option(
        None, help="Language for the tech-lead/product role's unprompted messages — English "
             "unless you say otherwise (e.g. `--language pt-BR`) "
                   "(announcements, diagnoses) — a reply always mirrors what the human wrote in, "
                   "regardless of this. Default: en."),
) -> None:
    """Register a project. GitHub: `--repo owner/name` (inferred from a clone URL) and a board
    via --board-owner/--board-number — or let `openfactory project init` create one. Azure
    DevOps: the dev.azure.com clone URL carries the organisation, project and repository, so
    registering with it needs no coordinate flags (docs/setup/azure-devops.md is the whole
    walkthrough). Split setups (e.g. Jira tickets + GitHub code) are edited in the registry."""
    ado = _ado_coordinates(repo_path)
    kind = (provider or "").strip().lower() or ("azure_devops" if ado[0] else "github")
    reg = ProjectRegistry()
    kwargs: dict = {"name": name, "repo_path": repo_path}

    if kind == "azure_devops":
        # THE URL IS THE DECLARATION. `https://dev.azure.com/<org>/<project>/_git/<repo>` names
        # all three coordinates, so asking for them again is asking the operator to re-type what
        # they just pasted — the funnel review measured that NO flag combination could produce a
        # valid ADO entry at all, which hard-stopped scenario B at registration.
        org = organization or ado[0]
        proj = ado_project or ado[1]
        repo_name = repository or repo or ado[2]
        missing = [flag for flag, value in (("--organization", org), ("--ado-project", proj),
                                            ("--repository", repo_name)) if not value]
        if missing:
            typer.echo(f"✗ an Azure DevOps project needs its coordinates and {', '.join(missing)} "
                       f"could not be read from {repo_path!r}")
            # vendor-url-ok: this is help text SHOWING A HUMAN the shape to paste, not a URL this
            # platform builds and sends anybody to.
            typer.echo("  a dev.azure.com clone URL carries all three: "
                       "https://dev.azure.com/<organization>/<project>/_git/<repository>")
            raise typer.Exit(2)
        tracker_options: dict[str, str] = {"organization": org}
        forge_options: dict[str, str] = {"organization": org, "project": proj}
        if work_item_type:
            tracker_options["work_item_type"] = work_item_type
        if token_env:
            tracker_options["token_env"] = token_env
            forge_options["token_env"] = token_env
        # The tracker's `repo` is the ADO PROJECT (work items live in a project, not a repo); the
        # forge's is the git repository inside it. Collapsing the two is how a three-repo product
        # sends the agent to the wrong tree — the axes really do name different things here.
        kwargs["tracker"] = ProviderRef(kind="azure_devops", repo=proj, options=tracker_options)
        kwargs["forge"] = ProviderRef(kind="azure_devops", repo=repo_name, options=forge_options)
    else:
        options: dict[str, str] = {}
        if board_owner and board_number:
            options = {"board_owner": board_owner, "board_number": board_number}
        if token_env:
            options["token_env"] = token_env
        inferred = repo or (_infer_repo(repo_path) or None if kind == "github" else None)
        kwargs["tracker"] = ProviderRef(kind=kind, repo=inferred, options=options)

    if language:
        kwargs["language"] = language
    if model:
        kwargs["model"] = model
    reg.add(Project(**kwargs))
    typer.echo(f"registered project {name!r}")


def _model_recognition_note(project: str, model: str) -> str:
    """A line under `set-model` when the harness does not carry this name in its own catalogue.

    A WARNING AND NEVER A REFUSAL, because the two cases are indistinguishable from here and
    measured to be so: `claude-fiofo2` (a typo) and a real Bedrock inference-profile ARN both make
    the CLI say it does not recognise the name, and refusing would block the enterprise routes
    this platform exists to serve. What it buys is the typo — caught the second it is typed
    instead of by a failed ticket an hour later, which is how this was found (pilot, 2026-08-15:
    `set-model podbeam claude-fiofo2` was accepted in silence and the panel showed it as if it
    were a setting).

    The harness is asked through its OPTIONAL capability (`recognises_model`); a harness without
    one, or without a CLI on this machine, simply says nothing here."""
    try:
        from openfactory.adapters.agent.registry import build_executor, harness_kind

        proj = ProjectRegistry().get(project)
        kind = harness_kind(proj, "executor")
        agent = build_executor(proj)
        probe = getattr(agent, "recognises_model", None)
        if not callable(probe):
            # SILENCE IS THE ONE ANSWER THIS MAY NOT GIVE. Claude is ONE harness of several and
            # the model string is whatever that harness names its own way — so a deployment on
            # `codex`, `kimi` or `opencode` has no recognition capability to probe, and returning
            # "" would hand it the same blank line that means "checked, fine" (pilot, 2026-08-15:
            # "the claude harness is one of the options, like the anthropic models — this tool
            # will have to serve several harnesses x models").
            verdict, detail = "unchecked", (
                f"the {kind!r} harness has no way to check a model name before it is used")
        else:
            verdict, detail = probe(model)
    except Exception as exc:  # noqa: BLE001 — a note is never worth failing the command for
        verdict, detail = "unchecked", str(exc)[:120]
    if verdict == "known":
        return ""
    if verdict == "unchecked":
        # NOT SILENCE. "I could not ask" and "the harness approved it" produced the same blank
        # line in the first cut, so an operator on a machine where the probe cannot run would
        # read the absence of a warning as confirmation (pilot, 2026-08-15).
        return (f"· the model was not checked against the harness ({detail}) — the first job "
                "proves it, and fails naming this model if the harness will not run it")
    return (f"⚠ the harness does not recognise {model!r} — {detail}\n"
            "  That is EXPECTED for a Bedrock inference-profile ARN or a gateway alias, and it "
            "looks exactly the same as a typo.\n"
            "  Nothing is blocked: the first job proves it, and fails naming this model if the "
            "harness will not run it.")


@project_app.command("set-model")
def project_set_model(
    name: str,
    model: str = typer.Argument(..., help="The harness's own model string — claude-fable-5, "
                                          "gpt-5, a Bedrock inference profile ARN…"),
    role: str = typer.Option(None, help="Set it for ONE role (executor | reviewer | techlead | "
                                        "product) instead of every role"),
) -> None:
    """Which model writes this project's code — a registry value, changed here instead of by
    editing YAML inside the worker. One string covers every role; `--role` builds the per-role
    shape (one call per role). The string is passed to the harness verbatim: each CLI names
    models its own way, and policing it here would reject the exact strings the enterprise
    routes need."""
    reg = ProjectRegistry()
    try:
        reg.set_model(name, model, role=role)
    except KeyError:
        typer.echo(f"✗ no project named {name!r} — `openfactory project list` shows what this "
                   f"deployment drives (and remember the worker has its own registry)")
        raise typer.Exit(2) from None
    except ValueError as exc:
        typer.echo(f"✗ {exc}")
        raise typer.Exit(2) from None
    scope = f"role {role!r}" if role else "every role"
    typer.echo(f"✓ {name}: model {model!r} for {scope} — takes effect on the next job, no "
               f"restart needed (the registry is read per run)")
    if note := _model_recognition_note(name, model):
        typer.echo(note)


@project_app.command("set-language")
def project_set_language(
    name: str,
    language: str = typer.Argument(..., help="`en`, `pt-BR`, or any tag your agents understand"),
) -> None:
    """Which language this project SPEAKS FIRST — its park alerts, its scheduled rounds, the
    comments it writes on a ticket nobody asked it to write.

    A REPLY IS NOT GOVERNED BY THIS. When somebody asks the tech-lead or the product role a
    question, the answer follows the language of the QUESTION — someone who writes in English
    wants an answer in English, whatever a project is configured for. That rule is the harness's
    own (`adapters/agent/roles.py::language_directive`) and this setting is the other half of it:
    the default for when the factory speaks first and has no incoming language to copy.

    `--language` existed on `project add` and `project init` and nowhere else, so changing it
    later meant editing YAML inside the worker image and rebuilding.
    """
    reg = ProjectRegistry()
    try:
        reg.set_language(name, language)
    except KeyError:
        typer.echo(f"✗ no project named {name!r} — `openfactory project list` shows what this "
                   f"deployment drives (and remember the worker has its own registry)")
        raise typer.Exit(2) from None
    except ValueError as exc:
        typer.echo(f"✗ {exc}")
        raise typer.Exit(2) from None
    typer.echo(f"✓ {name}: unprompted messages in {language!r} — takes effect on the next one, "
               f"no restart needed (the registry is read per run).")
    typer.echo("  A reply still follows whoever asked: someone who writes in English gets English.")


@project_app.command("list")
def project_list() -> None:
    for p in ProjectRegistry().list():
        flag = "" if p.enabled else " (disabled)"
        axes = f"tracker:{p.tracker.kind} forge:{p.forge.kind} ci:{p.ci.kind}"
        typer.echo(f"{p.name}\t{p.repo_path}\t[{axes}]{flag}")


@project_app.command("forget-conversations")
def project_forget_conversations(
    name: str,
    yes: bool = typer.Option(False, "--yes", help="skip the confirmation"),
) -> None:
    """Delete every recorded conversation turn for a project (a data-deletion request).

    Irreversible and deliberately awkward: it asks first, prints the count, and touches ONLY the
    client's conversation — never the platform's operational memory for that project.
    """
    from openfactory.memory.transcript import forget_project

    if not yes:
        typer.echo(f"This permanently deletes ALL recorded conversation for '{name}'.")
        typer.confirm("Proceed?", abort=True)
    gone = forget_project(name)
    typer.echo(f"deleted {gone} conversation row(s) for {name}")


@project_app.command("remove")
def project_remove(name: str) -> None:
    ProjectRegistry().remove(name)
    typer.echo(f"removed {name!r}")


@project_app.command("init")
def project_init(
    name: str,
    repo_path: str = typer.Argument(None, help="Local path or clone URL (only needed when the "
                                               "project is not registered yet)"),
    repo: str = typer.Option(None, help="owner/name on the forge (defaults from repo_path)"),
    board_owner: str = typer.Option(None, help="Where the board is created (defaults to the "
                                               "repo's owner)"),
    language: str = typer.Option(None, help="Language for unprompted messages (default: en)"),
    provider: str = typer.Option(None, help="The forge kind that owns this URL's host — needed "
                                            "when the host belongs to an installed add-on, "
                                            "which this build cannot recognise by name. A kind "
                                            "this build ships claims nothing: its hosts are "
                                            "known, and a URL outside them stays refused"),
) -> None:
    """From nothing to a project that can move a ticket — everything an API can do, done.

    CONVERGES rather than performs a fixed script: each step runs only if its result is missing,
    so a failed board creation is retried by running init again — never by hand-assembling the
    remaining half. Registers the project (runtime state, no rebuild), CREATES the Projects v2
    board with the platform's columns, attaches it, and scaffolds the manifest.

    What stays manual is irreducible: authorising the GitHub App on the repository (an OAuth
    grant) and authenticating the harness (it is your subscription). `openfactory doctor` names
    anything still missing."""
    reg = ProjectRegistry()
    try:
        project = reg.get(name)
        typer.echo(f"· {name} is already registered")
    except KeyError:
        if not repo_path:
            typer.echo(f"{name} is not registered — pass REPO_PATH (and --repo owner/name)")
            raise typer.Exit(1) from None
        if _ado_coordinates(repo_path)[0]:
            # Registering here would mint a GitHub-shaped entry over Azure DevOps coordinates.
            typer.echo(f"✗ that is an Azure DevOps URL — register with `openfactory project add "
                       f"{name} {repo_path}` (the URL carries the coordinates), then re-run this "
                       f"for the manifest scaffold. The walkthrough: docs/setup/azure-devops.md")
            raise typer.Exit(2) from None
        # WHOSE HOST IS IT — asked, and refused when the answer is nobody this build implements
        # (#162). The Azure branch above refuses by NAME; everything else fell through to
        # `kind="github"`, so a GitLab, Bitbucket or self-hosted URL was registered as GitHub. It
        # is not a label that stays put: `factory._authenticated` then reads the row and offers a
        # `github.com` credential to whatever host the URL actually names, and the doctor reports
        # a GitHub remedy over a perfectly good PAT. Every other registry in this platform refuses
        # to guess a provider; this is the door they were all guessing behind.
        try:
            foreign = _foreign_host(repo_path, provider=provider or "")
        except ValueError as exc:
            typer.echo(f"✗ {exc}")
            raise typer.Exit(2) from None
        if foreign:
            installed = _installed_forges()
            named = (provider or "").strip().lower()
            typer.echo(f"✗ {foreign} is not a forge this build implements — known: "
                       f"{', '.join(_known_forges())}. Registering it as GitHub is how a "
                       f"credential for one system reaches another.\n"
                       + (f"  · `--provider {named}` claims nothing: {named} is a kind this build "
                          f"ships, and {foreign} is not a host it answers for\n"
                          if named else "")
                       + f"  · a GitHub ENTERPRISE host: set GH_HOST={foreign} and re-run — this "
                       f"platform honours it everywhere it builds a URL\n"
                       + (f"  · an installed add-on's host: re-run with --provider "
                          f"<{'|'.join(installed)}> — the add-on claims the host by name\n"
                          if installed else "")
                       + "  · another vendor: see docs/setup/ for the ones that are supported")
            raise typer.Exit(2) from None
        inferred = repo or _infer_repo(repo_path)
        if not inferred:
            typer.echo("cannot infer owner/name — pass --repo explicitly")
            raise typer.Exit(1) from None
        # THE KIND THE OPERATOR NAMED, or GitHub — the only built-in this door registers without a
        # coordinate flag. An add-on's kind goes on BOTH axes: its board, if it has one, is keyed
        # by the tracker kind (`board/factory.py`), and the board step below already leaves a
        # non-GitHub tracker to bring its own.
        kind = (provider or "").strip().lower() or "github"
        kwargs = {"name": name, "repo_path": repo_path,
                  "tracker": ProviderRef(kind=kind, repo=inferred, options={})}
        if kind != "github":
            kwargs["forge"] = ProviderRef(kind=kind, repo=inferred, options={})
        if language:
            kwargs["language"] = language
        reg.add(Project(**kwargs))
        typer.echo(f"✓ registered {name} ({inferred})")
        project = reg.get(name)

    board_failed = False
    options = (project.tracker.options or {}) if project.tracker else {}
    tracker_kind = ((project.tracker.kind or "") if project.tracker else "github").strip().lower()
    from openfactory.adapters.board_setup.base import BoardSetupError
    from openfactory.adapters.board_setup.registry import board_creator

    # WHETHER THERE IS A BOARD TO CREATE IS THE TRACKER'S DECLARATION, asked of the board-setup
    # registry — this command used to import one vendor's module by name and gate it on the
    # vendor's name. On Jira the project's workflow IS the board; on Azure Boards the board
    # exists with the project and what needs setting up is its states — a recipe, not an API
    # call (docs/setup/azure-devops.md §3). A tracker that declares no act brings its own.
    create_board = board_creator(tracker_kind or "github")
    if create_board is None:
        typer.echo(f"· board: the {tracker_kind} tracker brings its own — nothing to create "
                   f"(azure_devops states: docs/setup/azure-devops.md §3)")
    elif options.get("board_owner") and options.get("board_number"):
        typer.echo(f"· board already attached "
                   f"({options['board_owner']}/#{options['board_number']})")
    else:
        from openfactory.credentials import deployment_tracker_token, tracker_token

        owner = board_owner or (project.tracker.repo or "").split("/")[0]
        if not owner:
            typer.echo("cannot tell where to create the board — pass --board-owner")
            raise typer.Exit(1)
        try:
            # the static token first (a PERSONAL account's board needs it — the App token
            # cannot drive user-owned Projects v2), then what this deployment can mint for THIS
            # tracker's vendor, which an ORG-only-App deployment legitimately creates boards
            # with. tracker_token() alone sent an App-only org deployment to the same dead end
            # the pilot hit (2026-08-10).
            number, url = create_board(owner=owner, title=name,
                                       token=tracker_token() or deployment_tracker_token(project))
        except BoardSetupError as exc:
            # the project stays registered (tickets-only is legitimate) AND init keeps its own
            # docstring's promise — CONVERGES — by continuing to the manifest scaffold instead of
            # dying here. Measured in the pre-pilot review: exiting left a boardless project
            # unable to ever COMPLETE init, since the scaffold below was unreachable.
            typer.echo(f"✗ board: {exc}")
            typer.echo("  the project is registered without a board — fix the above and re-run "
                       f"`openfactory project init {name}` (the board step is idempotent)")
            board_failed = True
        else:
            reg.attach_board(name, board_owner=owner, board_number=number)
            typer.echo(f"✓ board created with the platform's columns — {url}")

    manifest_refused = False
    if "://" in project.repo_path or project.repo_path.startswith("git@"):
        # NEVER POINT AT OUR OWN SOURCE. This said "(template: openfactory/cli.py
        # _MANIFEST_TEMPLATE)" — our filing system handed to somebody at a terminal inside a
        # container, where that file is neither open nor readable in any useful way (pilot,
        # 2026-08-12). The manifest is WRITTEN FOR THEM by the environment session; that is the
        # answer, and the annotated reference is a document, not a Python constant.
        typer.echo(f"· {name} is registered by its clone URL — the factory fetches the code "
                   f"itself, so there is no checkout here to write a manifest into")
        typer.echo(f"  `openfactory onboard {name} --yes` proposes it as a pull request, "
                   "PROVEN in the box first (ONBOARDING §3); with a local checkout, "
                   "`openfactory env read <path>` is the session form. Annotated reference: "
                   "docs/project.yaml.example")
    else:
        try:
            # THE ONE READER DECIDES WHETHER THIS CHECKOUT HAS A MANIFEST. `dest.exists()` on the
            # current name alone read a checkout still on the directory's retired name as "no
            # manifest" and scaffolded the template beside the one it has — the second manifest
            # every other door now refuses, minted by the first command a new operator runs
            # (review, 2026-08-25). The sentence says what to rename; nothing is written.
            dest = namespace.resolve(Path(project.repo_path).expanduser(),
                                     project.manifest_path, project=name)
        except namespace.RetiredNamespace as exc:
            typer.echo(f"✗ {exc}")
            manifest_refused = True
        else:
            if dest.exists():
                typer.echo(f"· manifest already exists: {dest}")
            else:
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_text(_MANIFEST_TEMPLATE)
                typer.echo(f"✓ wrote {dest}")

    typer.echo("")
    # A CHECKLIST OF WHAT THIS COMMAND CANNOT DO — not a list of things still undone. Printed
    # unconditionally, "what remains" told an operator who had just installed the App and
    # pasted the harness token that both were still pending (pilot, 2026-08-12). The command
    # cannot know; `doctor` can, and it is the next line either way.
    typer.echo("two things no command can do for you — grant the forge credential access to "
               "this repository, and authenticate the coding agent (it is your subscription):")
    typer.echo(f"  `openfactory doctor {name}` says whether they are already done, and names "
               f"anything else missing. When it is green, a card in TO-DO starts on its own.")
    if board_failed or manifest_refused:
        # non-zero AFTER converging: scripts must notice the board step failed, and a human
        # already read the remedy above — the scaffold still happened, which is the promise.
        # A refused scaffold (the checkout is on the retired directory name) is the same shape:
        # the project is registered, the sentence above says what to rename, and re-running this
        # after the rename finds the manifest already there.
        raise typer.Exit(1)


def _ado_coordinates(repo_path: str) -> tuple[str, str, str]:
    """`(organization, project, repository)` out of an Azure DevOps clone URL, or `("", "", "")`.

    Three shapes carry the coordinates, and they are the three ADO itself hands out:

        https://dev.azure.com/<org>/<project>/_git/<repo>       (Clone → HTTPS; may carry user@)
        git@ssh.dev.azure.com:v3/<org>/<project>/<repo>         (Clone → SSH)
        https://<org>.visualstudio.com/<project>/_git/<repo>    (legacy hosts, ± DefaultCollection)

    Segments are URL-decoded because an ADO project name may contain spaces — `%20` in the URL,
    a real space in every API route. Anything else answers empty triple, never a guess: a wrong
    coordinate aims a working credential at somebody else's project."""
    import urllib.parse

    raw = (repo_path or "").strip().rstrip("/")
    if raw.endswith(".git"):
        raw = raw[:-4]
    unquote = urllib.parse.unquote
    if raw.startswith("git@ssh.dev.azure.com:v3/"):
        parts = [unquote(p) for p in raw.split(":v3/", 1)[1].split("/") if p]
        return (parts[0], parts[1], parts[2]) if len(parts) == 3 else ("", "", "")
    if "://" not in raw:
        return "", "", ""
    host, _, path = raw.split("://", 1)[1].partition("/")
    host = host.rsplit("@", 1)[-1].lower()  # a browser-copied URL carries <org>@ before the host
    parts = [unquote(p) for p in path.split("/") if p]
    if len(parts) >= 3 and parts[-2] == "_git":
        if host == "dev.azure.com" and len(parts) >= 4:
            return parts[0], parts[-3], parts[-1]
        if host.endswith(".visualstudio.com"):
            return host.split(".", 1)[0], parts[-3], parts[-1]
    return "", "", ""


def _known_forges() -> list[str]:
    """Which forges this build actually implements — the registry's rows PLUS the installed
    add-ons, never listed here. `sorted(FORGES)` alone told an operator who had just installed
    `forge.gitea` that the platform did not support it (measured 2026-08-26)."""
    from openfactory import plugins
    from openfactory.adapters.forge.registry import FORGES

    return plugins.known("forge", FORGES)


def _installed_forges() -> list[str]:
    """The forge kinds an add-on brought — the ones whose hosts this build cannot recognise."""
    from openfactory.adapters.forge.registry import FORGES

    return [k for k in _known_forges() if k not in FORGES]


def _shipped_hosts() -> dict[str, set[str]]:
    """Host names per SHIPPED forge kind — the hosts this build recognises without being told.

    GitHub's is the deployment's own (`GH_HOST`, honoured everywhere a URL is built) and github.com
    always; Azure DevOps's are the three shapes `_ado_coordinates` reads. Keyed by the forge
    table's rows, and a guard holds the keys equal to that table: a shipped kind with no entry here
    would be refused as foreign on its own host."""
    import os

    github = {(os.environ.get("GH_HOST") or os.environ.get("GITHUB_HOST") or "github.com")
              .strip().lower(), "github.com"}
    return {"github": github,
            "azure_devops": {"dev.azure.com", "ssh.dev.azure.com", "visualstudio.com"}}


def _foreign_host(repo_path: str, *, provider: str = "") -> str:
    """The host in `repo_path` when it belongs to no forge this build implements, else `""`.

    A LOCAL PATH IS NOT FOREIGN: it names no host at all, and an operator registering a working
    copy is the ordinary local case this command was written for. Neither is an ssh remote whose
    host we know.

    AN INSTALLED ADD-ON CLAIMS ITS HOST THROUGH `provider`. The platform cannot know which hosts
    `forge.gitea` answers for — a self-hosted forge lives on whatever name the client gave it —
    so the operator names the kind (`--provider gitea`) and a kind an add-on brought is not
    foreign, whatever its host. A kind nobody implements is refused by name, listing what is
    installed; a host with no kind named keeps the refusal, because the alternative is the label
    that does not stay put (#162: a GitLab URL registered as GitHub).

    A SHIPPED KIND CLAIMS NOTHING. This build knows GitHub's and Azure DevOps's hosts, so
    `--provider github` on a GitLab URL is the #162 door reopened by flag — measured 2026-08-26:
    the first version of the flag let any KNOWN kind claim, and `gitlab.com` was written as a
    GitHub row again. With a shipped kind named, the host must be one that kind answers for: a
    foreign host keeps the refusal, and another shipped kind's host is refused by name too — a
    github.com URL under `--provider azure_devops` wrote an Azure row with `owner/name` for a
    repository and no organisation, which fails at pickup rather than here.
    """
    import re as _re

    chosen = (provider or "").strip().lower()
    if chosen and chosen not in _known_forges():
        raise ValueError(
            f"{chosen!r} is not a forge this build implements — known: "
            f"{', '.join(_known_forges())}. An add-on's kind counts once its package is installed "
            f"where this command runs.")
    raw = (repo_path or "").strip()
    host = ""
    if "://" in raw:
        from openfactory.adapters.forge.base import host_of

        host = host_of(raw) or (_re.sub(r"^[a-z+]+://", "", raw).split("/")[0].split("@")[-1])
    elif raw.startswith("git@") and ":" in raw:
        host = raw.split("@", 1)[1].split(":", 1)[0]
    if not host:
        return ""
    host = host.lower()
    if chosen and chosen in _installed_forges():
        return ""  # an add-on's host is whatever the client named; the kind claims it

    def _answers_for(owned: set[str]) -> bool:
        return any(host == o or host.endswith("." + o) for o in owned)

    shipped = _shipped_hosts()
    owner = next((kind for kind, owned in shipped.items() if _answers_for(owned)), "")
    if not chosen:
        return "" if owner else host
    if owner == chosen:
        return ""
    if owner:
        raise ValueError(
            f"{host} is not a host the {chosen!r} forge answers for — it is {owner!r}'s. Drop "
            f"--provider, or name {owner!r}.")
    return host  # foreign, and a shipped kind cannot claim it


def _infer_repo(repo_path: str) -> str:
    """`owner/name` out of a clone URL, or "" — a local path carries no owner to infer."""
    raw = repo_path.strip().rstrip("/")
    if raw.endswith(".git"):
        raw = raw[:-4]
    if "://" in raw:
        parts = raw.split("/")
        return "/".join(parts[-2:]) if len(parts) >= 2 else ""
    if raw.startswith("git@") and ":" in raw:
        return raw.split(":", 1)[1]
    return ""


@app.command("init")
def init_deployment(
    # NO LITERAL LIST IN THE HELP. These four vocabularies are the registries' — shipped rows plus
    # whatever add-on is installed — and a list written here was a third hand copy (the generator
    # had two) that named vendors an installed add-on had already outgrown. The prompt and the
    # non-tty refusal print the live list; `--help` says where it comes from.
    forge: str = typer.Option(None, help="Where the CODE lives — a forge kind this build "
                                         "implements (shipped or installed as an add-on); the "
                                         "prompt lists them"),
    tracker: str = typer.Option(None, help="Where the TICKETS live — a tracker kind this build "
                                           "implements; the prompt lists them"),
    harness: str = typer.Option(None, help="Which coding agent writes the code — a harness kind "
                                           "this build implements; the prompt lists them"),
    github_auth: str = typer.Option(None, "--github-auth", help="token | app"),
    github_account: str = typer.Option(None, "--github-account",
                                       help="org | personal — asked on the App path only: a "
                                            "personal account's board needs a classic PAT "
                                            "beside the App"),
    claude_auth: str = typer.Option(None, "--claude-auth", help="subscription | api_key"),
    channel: str = typer.Option(None, help="Where the factory talks to your team — a channel "
                                           "kind this build implements; the prompt lists them"),
    panel_exposed: bool = typer.Option(
        None, "--panel-exposed/--panel-local",
        help="Exposed generates a panel token; local leaves it OPEN (fine on a laptop)"),
    out: str = typer.Option(".env.compose", help="Where to write it"),
    force: bool = typer.Option(False, "--force", help="Overwrite an existing file"),
) -> None:
    """Generate this DEPLOYMENT's environment from a few answers, instead of asking you to fill
    in a template.

    THE ORDER THIS FIXES. The template asked for credentials before you had said which vendors you
    use, so you filled blanks for systems you will never touch and left blanks whose consequence
    you could not evaluate. Answer the questions and the file contains your rows and nothing else.

    It configures the DEPLOYMENT, never a project: no repository, no board, no stack. Those are
    `openfactory project init` and `openfactory env read`, which read your repository rather than
    interrogate you — this command exists because the deployment's own environment was the last
    thing with no such step.
    """
    import os
    import stat

    from openfactory.onboarding.deployment import (
        QUESTIONS,
        Answers,
        Probes,
        UnknownAnswer,
        UnusableHome,
        default_work_dir,
        render,
    )

    q = {entry.flag: entry for entry in QUESTIONS}

    dest = Path(out).expanduser()
    if dest.exists() and not force:
        # THE `env apply` RULE. This file holds credentials somebody pasted by hand; silently
        # rewriting it is the one mistake that costs more than the whole command saves.
        typer.echo(f"✗ {dest} already exists — re-run with --force to overwrite it "
                   f"(or --out <path> to write somewhere else). Nothing was changed.")
        raise typer.Exit(2)

    interactive = sys.stdin.isatty()

    def ask(value: str | None, flag: str, default: str | None = None) -> str:
        entry = q[flag]
        chosen_default = default or entry.default
        if value is not None:
            return value
        if not interactive:
            # NEVER BLOCK ON A PROMPT NOBODY CAN ANSWER. Piped into a script or a CI job, a
            # `typer.prompt` waits for input that will never come — the silent forever-wait this
            # platform treats as its own defect class. Refuse, naming the flag instead.
            typer.echo(f"✗ --{flag} is required when this does not run in a terminal "
                       f"(one of: {', '.join(entry.options)})")
            raise typer.Exit(2)
        # THE QUESTION, THEN WHAT IT CHANGES, THEN THE CHOICES. The first version asked
        # `channel (panel/slack)` and the pilot operator had to ask what it influenced — the
        # platform's vocabulary is not the reader's, and an option list is not an explanation.
        typer.echo("")
        typer.echo(entry.ask)
        typer.echo(f"  → {entry.effect}")
        return typer.prompt(f"  {'/'.join(entry.options)}", default=chosen_default)

    typer.echo("A few questions about THIS DEPLOYMENT — not about a project. The file it writes "
               "carries\nonly the rows your answers use; anything you skip has a flag "
               "(--forge, --harness, …).")

    answers = Answers()
    answers.forge = ask(forge, "forge")
    answers.tracker = ask(tracker, "tracker",
                          default=answers.forge if answers.forge in q["tracker"].options else None)
    if "github" in (answers.forge, answers.tracker):
        answers.github_auth = ask(github_auth, "github-auth")
        if answers.github_auth == "app":
            # only the App path forks on account type: on the token path one classic PAT
            # already carries code AND board, whichever kind of account owns them
            answers.github_account = ask(github_account, "github-account")
    answers.harness = ask(harness, "harness")
    if answers.harness == "claude_code":
        answers.claude_auth = ask(claude_auth, "claude-auth")
    answers.channel = ask(channel, "channel")
    if panel_exposed is None:
        if not interactive:
            # The one question that silently DEFAULTED when nobody could answer — to an OPEN
            # panel. A default is the product: a scripted install that never said whether the
            # panel is reachable must be refused, not quietly left open (v2 verification pass,
            # 2026-08-10 — every other question already refused through ask()).
            typer.echo("✗ --panel-exposed or --panel-local is required when this does not run "
                       "in a terminal — an unstated answer would leave the panel OPEN to "
                       "anyone who can reach the port")
            raise typer.Exit(2)
        answers.panel_exposed = (
            ask(None, "panel-exposed").strip().lower() in ("y", "yes", "true", "1"))
    else:
        answers.panel_exposed = panel_exposed

    from openfactory.credentials import discover_forge_token

    # RESOLVED ONCE, HERE, AND HANDED TO THE GENERATOR. The file must name the same directory this
    # command creates: deriving it twice is how a value ends up written in one place and made in
    # another, and the symptom of a disagreement here is a job that runs in an empty workspace.
    # REFUSED BY NAME RATHER THAN ROOTED AT `/`. Docker gives a uid with no `/etc/passwd` entry
    # `HOME=/`, which is exactly what `install.sh` produces with `-u "$(id -u):$(id -g)"` — so this
    # used to compute `/.local/share/openfactory/work` and die on `Permission denied` for a
    # directory nobody asked for, on every Linux install (measured on openfactory-cli:v0.1.3).
    try:
        work_dir = default_work_dir()
    except UnusableHome as exc:
        typer.echo(f"✗ {exc}")
        raise typer.Exit(2) from None

    try:
        # THE CHOSEN FORGE'S OWN LOGIN, asked through the credential registry — a vendor with no
        # such thing answers None and the line is left for the person. This was `gh auth token`
        # spawned here by name, one line after asking which forge the deployment uses.
        rendered = render(answers,
                          Probes(forge_token=lambda: discover_forge_token(answers.forge),
                                 work_dir=lambda: work_dir))
    except UnknownAnswer as exc:
        typer.echo(f"✗ {exc}")
        raise typer.Exit(2) from None

    # CREATED HERE RATHER THAN LEFT TO DOCKER, and that is the whole point of moving it out of
    # /var/lib. An absent bind source is not an error to Docker: the daemon creates it, owned by
    # ROOT, and the stack comes up looking healthy — the ownership surprises the operator later,
    # at a `git clone` inside a box that cannot write. Under rootless Docker it cannot be created
    # at all. Making it now, as the invoking user, is what removes the `sudo` line from the
    # first-run path instead of merely moving it.
    try:
        Path(work_dir).mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        # ONE SENTENCE, THE CAUSE AND THE REMEDY — never the traceback. `strerror` is the
        # operating system's own reason ("Permission denied", "Read-only file system"), which is
        # the half a person cannot guess.
        typer.echo(f"✗ could not create the job workspace directory {work_dir} "
                   f"({exc.strerror or exc}) — make it yourself and re-run, or point "
                   f"OPENFACTORY_WORK_DIR in {dest} at a directory you own")
        raise typer.Exit(2) from None

    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(rendered.text, encoding="utf-8")
    # 0600 BEFORE anybody can read it. The file carries credentials; the default umask on a
    # shared machine does not.
    os.chmod(dest, stat.S_IRUSR | stat.S_IWUSR)

    typer.echo(f"✓ wrote {dest} (0600)")
    if rendered.obtained:
        # NAMES, NEVER VALUES. Echoing a secret puts it in a scrollback buffer, a screen recording
        # and a CI log — three places nobody remembers to clear.
        typer.echo(f"  filled without asking: {', '.join(rendered.obtained)}")
    if rendered.remaining:
        typer.echo("\nwhat is still yours to do:")
        for i, line in enumerate(rendered.remaining, 1):
            typer.echo(f"  {i}. {line}")
    typer.echo(f"\nthen: `docker compose --env-file {dest} up -d --build`")


def _conformance_kinds() -> str:
    """The published kinds, read off the table — the help text used to be a hand copy that
    omitted `tracker` while `tracker` worked, and named nothing that was added afterwards."""
    from openfactory.conformance import CHECKS

    return " | ".join(CHECKS)


@app.command("conformance-adapter")
def conformance_adapter(
    kind: str = typer.Argument(..., help=f"one of: {_conformance_kinds()}"),
    factory: str = typer.Argument(..., help="Import path `pkg.module:attr` — an adapter "
                                            "INSTANCE, its CLASS, or a zero-arg FUNCTION "
                                            "returning an instance (an object that merely "
                                            "has __call__ is judged as the instance, never "
                                            "called)"),
) -> None:
    """Run YOUR adapter against the platform's conformance suite.

    Every rule in it was learned from a live incident on this platform; a green run means your
    provider does not re-pay any of them. The checks exercise the LOCAL contract only — nothing
    remote is created or mutated — so point board adapters at a sandbox of yours anyway."""
    import importlib
    import inspect

    from openfactory.conformance import CHECKS

    row = CHECKS.get(kind)
    if row is None:
        typer.echo(f"unknown kind {kind!r} — one of: {', '.join(CHECKS)}")
        raise typer.Exit(2)
    check, protocol = row
    module_name, _, attr = factory.partition(":")
    if not attr:
        typer.echo("factory must be `pkg.module:attr`")
        raise typer.Exit(2)
    try:
        target = getattr(importlib.import_module(module_name), attr)
    except Exception as exc:  # noqa: BLE001 — the import error IS the answer
        typer.echo(f"could not import {factory!r}: {exc}")
        raise typer.Exit(2) from None
    # INSTANCE-VERSUS-FACTORY IS DECIDED BY THE PORT, AND AN INSTANCE IS NEVER CALLED. Four
    # shapes, judged in this order:
    #   a CLASS is constructed — its unbound methods satisfy any runtime Protocol by `hasattr`,
    #     which is how the very first version judged every class an instance and never
    #     constructed one;
    #   an object that satisfies the kind's Protocol IS the adapter (every port is
    #     `runtime_checkable`);
    #   a plain function — or a builtin, or a bound method — is a zero-arg factory: a function
    #     never carries a multi-method port's surface, so it is called ONCE and its result is
    #     judged;
    #   anything else is an INSTANCE that fails the port, handed to the check as it is, which
    #     names the methods it lacks.
    # The version before this one folded the last two into `not isinstance(target, protocol)`
    # and CALLED the result, so a half-implemented channel instance — the exact input this
    # command exists to judge, and the first form its help lists — died as `TypeError:
    # 'HalfChannel' object is not callable` (measured 2026-08-26) and no `<kind>.protocol`
    # finding was reachable for it. The version before THAT probed one method per kind from a
    # hand-kept map and read a factory FUNCTION as the instance: absence read as a verdict. An
    # instance that happens to define `__call__` is still an instance; `inspect.isroutine` is
    # what separates a function from an object, `callable` does not.
    if isinstance(target, type):
        adapter = target()
    elif isinstance(target, protocol):
        adapter = target
    elif inspect.isroutine(target):
        adapter = target()
    else:
        adapter = target
    findings = check(adapter)
    for f in findings:
        typer.echo(f"FAIL  {f.rule}")
        typer.echo(f"      {f.detail}")
        if f.taught_by:
            typer.echo(f"      taught by: {f.taught_by}")
    if findings:
        typer.echo(f"\nNOT CONFORMANT — {len(findings)} rule(s) broken")
        raise typer.Exit(1)
    typer.echo(f"CONFORMANT — {kind} adapter holds every rule this platform has paid for")


box_app = typer.Typer(help="The ephemeral environment a job runs in.")
app.add_typer(box_app, name="box")


@box_app.command("prove")
def box_prove_cmd(
    name: str,
    image: str = typer.Option(None, help="Override the image for this proof only"),
    sandbox: str = typer.Option("container", help="Which box to prove"),
    repo: str = typer.Option(None, help="owner/name — prove ANOTHER of this product's "
                                        "repositories (a product may span several, and each "
                                        "repo's box is proven on its own manifest)"),
) -> None:
    """Prove this project's box BEFORE a ticket runs — no agent, no tokens spent.

    Resolves the image to a digest, checks the image contract by name, checks the harness toolbox
    can execute in it, then runs the project's OWN `setup:` and `validate:` against untouched
    `main`. Green means your tests passed inside the factory (ADR-0037 D3).
    """
    from openfactory.box_prove import PROOF_DIR, box_probes, load, prove, save

    project = _get_project(name)
    proof_key = name
    view = project
    if repo:
        # C-18: the card's-eye view of the project — forge/ci swapped to that repository, the
        # checkout and the proof keyed so two repos never share either. THE KEY COMES FROM THE
        # VIEW, never recomputed from the raw flag: a bare name (`--repo dsk-ui`, the natural
        # ADO spelling) resolves to the DEFAULT repository, and hashing the raw string keyed
        # the default repo's proof under a foreign name (adversarial review, 2026-08-13).
        from openfactory.runtime.card_repo import _runner_view

        view, proof_key = _runner_view(project, f"{repo}#0")
        if proof_key == name:
            typer.echo(f"· --repo {repo} names the project's default repository — proving it "
                       f"under its own key")
    resolved = resolve_box_image(view, explicit=image, sandbox=sandbox)
    typer.echo(f"proving {proof_key} on {resolved}…\n")

    # WHAT THE ROOM SEES WHILE IT HAPPENS. This command pulls an image, installs the client's
    # dependencies and runs their whole suite — and until now it printed nothing until every
    # station had finished, which on a real repository is minutes of a blank terminal in front of
    # the people deciding whether to buy. A screen that has not moved is indistinguishable from
    # one that has hung, and somebody reaches for Ctrl-C.
    #
    # PROGRESS ON STDERR, RESULTS ON STDOUT. `openfactory box prove x > proof.txt` still captures
    # exactly
    # the findings and the verdict; the live half goes to the terminal, where it is for.
    def _stage(kind: str, text: str) -> None:
        if kind == "start":
            typer.echo(f"  … {text}", err=True)
        elif kind == "line":
            typer.echo(f"      {text.rstrip()}", err=True)

    # ONE box for the whole proof — setup and validate must share a container or the install is
    # thrown away between them, which is what the first real run of this command discovered.
    with box_probes(view, resolved, key=proof_key) as probes:
        proof = prove(proof_key, resolved, probes, on_stage=_stage)
    for f in proof.findings:
        typer.echo(f"  {f.mark:<4}  {f.check:<9} {f.message}")
        if not f.ok and f.remedy:
            typer.echo(f"          → {f.remedy}")

    where = save(proof)
    typer.echo("")
    if proof.ok:
        if where is None:
            # PROVEN AND NOT RECORDED IS A THIRD OUTCOME, and the one that used to read as success.
            # The proof is real; the record is what the poller consults, so without it the very
            # next pickup is held with "the box has never been proven" — while the person who just
            # ran this was told it worked. Two sentences, because they need two different actions.
            typer.echo(f"PROVEN — {name} can build and test in this box, but the proof could NOT "
                       f"be recorded, so the next pickup will be held as if it never ran.")
            typer.echo(f"  → the proof directory is not writable by this process ({PROOF_DIR}). "
                       f"Run where the deployment runs, or point OPENFACTORY_PROOFS somewhere this "
                       f"user can write.")
            raise typer.Exit(1)
        typer.echo(f"PROVEN — {name} can build and test in this box (recorded at {where})")
        # The number that makes the proof worth taking: this is what a client sees first.
        gates = next((f for f in proof.findings if f.check == "validate"), None)
        if gates:
            typer.echo(f"  {gates.message}")
        return
    typer.echo("NOT PROVEN — fix the FAIL lines above, then re-run (nothing recorded as valid).")
    typer.echo("  Changing a declared command is a normal step, not a detour: edit "
               f"{namespace.MANIFEST} in your repository, commit, re-run this — the proof "
               "notices the new commands by their hash (ONBOARDING §5, 'When the proof fails "
               "on a command you need to CHANGE').")
    if load(proof_key) is None:
        typer.echo("  no previous proof exists, so this repository cannot be picked up yet")
    raise typer.Exit(1)


def _exit_expired():
    """`box status` answers with its exit code too — a script asks this question."""
    raise typer.Exit(1)


@box_app.command("status")
def box_status_cmd(
    name: str,
    repo: str = typer.Option(None, help="owner/name — another of this product's repositories"),
) -> None:
    """Whether this project's box has a VALID proof — and if not, exactly what moved."""
    from openfactory.box_prove import (
        _current_digest,
        _hash_commands,
        component_gates,
        load,
    )
    from openfactory.loader import load_manifest
    from openfactory.runtime import toolbox as tb

    project = _get_project(name)
    proof_key, view = name, project
    if repo:
        # the key comes from the view — box prove's rule, for the same bare-name reason
        from openfactory.runtime.card_repo import _runner_view

        view, proof_key = _runner_view(project, f"{repo}#0")
    proof = load(proof_key)
    if proof is None:
        run_it = f"openfactory box prove {name}" + (f" --repo {repo}" if repo else "")
        typer.echo(f"{proof_key}: no proof — run `{run_it}`")
        raise typer.Exit(1)

    if repo:
        from openfactory.factory import resolve_repo_path

        manifest = load_manifest(view, repo_root=resolve_repo_path(view, cache_key=proof_key))
    else:
        manifest = load_manifest(view)
    from openfactory.orchestrator.validation import gate_commands

    # BOTH HALVES OF FRESHNESS, the two bugs this command shipped with (found by the onboard
    # fact-finding pass, 2026-08-13): it hashed WITHOUT the per-component gates — so a component
    # gaining a gate never expired the proof here while `gate_reason` held pickup, two answers
    # for one question — and it compared the proof's digest AGAINST ITSELF, which can never
    # detect an image change (firstrun.py had already named it "cli.py's bug").
    current = _hash_commands(list(manifest.setup), gate_commands(manifest.validation),
                             component_gates(manifest))
    variant = (tb.read_stamp() or {}).get("variant", "")
    live_digest = _current_digest(proof.image) or proof.digest

    # THE SAME FUNCTION THE POLLER ASKS, not a second opinion assembled here. This command used
    # to reproduce the freshness rules — and the moment the gate learned that a REBUILD with the
    # same toolchain is not a change, the two would have disagreed: `box status` saying EXPIRED
    # about a proof the factory was happily picking cards up on. Two answers to one question is
    # the bug this file's own comment above records paying for twice already (2026-08-15).
    from openfactory.box_prove import _freshness_reason

    run_it = f"run `openfactory box prove {name}" + (f" --repo {repo}`" if repo else "`")
    why = (None if not proof.ok else
           _freshness_reason(proof, digest=live_digest, variant=variant, commands=current,
                             run_it=run_it))
    if proof.ok and why is None:
        typer.echo(f"{proof_key}: proven at {proof.at} on {proof.image} ({proof.digest[:19]}…)")
        # WHAT IT IS PINNED TO, because that is what decides whether the next rebuild expires it
        # — and an operator who cannot see it cannot tell a proof that will survive an update
        # from one that will not.
        if proof.toolchain:
            typer.echo("  toolchain " + " · ".join(proof.toolchain.split("\n")))
            typer.echo("  a rebuild that leaves these unchanged does NOT expire this proof")
        else:
            typer.echo("  this image carries no toolchain line, so any rebuild expires the proof "
                       "— rebuild the box image to get one (`up -d --build`)")
        if proof.findings is None:
            typer.echo("  advisory findings were not recorded for this proof — "
                       "re-prove to record them")
        else:
            for adv in proof.advisories():
                typer.echo(f"  warn  {adv.check}  {adv.message}")
        return
    typer.echo(f"{proof_key}: the proof has EXPIRED — "
               f"{'the last proof FAILED' if not proof.ok else why}")
    if proof.ok:
        return _exit_expired()
    typer.echo(f"  {run_it}")
    raise typer.Exit(1)


knowledge_app = typer.Typer(help="Build and inspect the Knowledge Layer bundle (module map).")
app.add_typer(knowledge_app, name="knowledge")


def _git_head(repo: Path) -> str:
    """The repo's HEAD commit, stamped into the bundle's source links. Best-effort: a
    non-git checkout (or missing git) yields '' — the bundle still builds, just without a
    commit to pin (checksums still detect drift)."""
    import subprocess

    try:
        out = subprocess.run(
            ["git", "-C", str(repo), "rev-parse", "HEAD"],
            capture_output=True, text=True, timeout=10, check=False,
        )
        return out.stdout.strip() if out.returncode == 0 else ""
    except (OSError, subprocess.SubprocessError):
        return ""


@knowledge_app.command("build")
def knowledge_build(
    name: str,
    repo_flag: str = typer.Option(None, "--repo", help="owner/name — another of this product's "
                                                       "repositories (each repo carries its own "
                                                       "map)"),
    publish: bool = typer.Option(False, "--publish",
                                 help="For a project the factory cloned itself: also push the "
                                      "map to the repository's knowledge branch, where the next "
                                      "job reads it. Writes to YOUR repository, hence a flag"),
) -> None:
    """Generate the deterministic module map into the project's `knowledge/` bundle.

    Parses the repo (structure + Python AST + JS/TS imports) with NO LLM calls, writes
    `knowledge/modules.yaml` + `knowledge/manifest.yaml`, and reports the module count.

    THE REPOSITORY RESOLVES LIKE EVERYWHERE ELSE (the third sighting of the same bug,
    2026-08-13 — the refresh activity's comment records the first two). This did
    `Path(project.repo_path)`, which for a project the factory cloned itself (registered by its
    clone URL) is not a directory at all: the command walked a nonexistent path and reported a
    map of nothing. Now: a local checkout is used as before; a factory-cloned project resolves
    through the worker's own cache, and `--publish` pushes the result to the repository's
    knowledge branch — which is where the next job actually reads it, since the cache clone is
    disposable."""
    from datetime import UTC, datetime

    from openfactory.factory import resolve_repo_path
    from openfactory.knowledge import build_bundle, write_bundle
    from openfactory.runtime.card_repo import _runner_view

    project = _get_project(name)
    view, cache_key = (project, name)
    if repo_flag:
        # the cache key comes from the view — box prove's rule, for the same bare-name reason
        view, cache_key = _runner_view(project, f"{repo_flag}#0")
    raw = str(view.repo_path)
    cloned_by_us = "://" in raw or raw.startswith("git@")
    repo = resolve_repo_path(view, cache_key=cache_key)
    commit = _git_head(repo)
    generated_at = datetime.now(UTC).isoformat()
    bundle = build_bundle(repo, commit=commit, generated_at=generated_at)
    dest = write_bundle(bundle, repo)
    if dest is None:
        # Sources unchanged → the bundle on disk already describes reality. Writing anyway would
        # only churn the provenance stamps, and in the post-merge pipeline that churn is a commit
        # that re-triggers the pipeline forever (docs/knowledge-layer.md §22).
        typer.echo(
            f"unchanged — {len(bundle.module_map.modules)} modules already current; nothing "
            "written (nothing to commit)"
        )
        return
    typer.echo(
        f"wrote {dest}/modules.yaml + manifest.yaml — {len(bundle.module_map.modules)} modules, "
        f"{len(bundle.manifest.checksums)} sources @ {commit[:8] or '(no commit)'}"
    )
    if cloned_by_us and not publish:
        # The cache clone is DISPOSABLE — the next fetch replaces it, so a map written only
        # there quietly evaporates. Saying so beats a command that reports success into a
        # directory nobody will ever read.
        typer.echo("  ⚠ this map lives in the factory's own clone, which the next fetch "
                   "replaces — re-run with --publish to push it to the repository's knowledge "
                   "branch, where jobs read it (it also refreshes itself after every merge)")
    if publish:
        if not cloned_by_us:
            typer.echo("  · --publish is for a project the factory cloned itself; this one is "
                       "a local checkout — commit knowledge/ like any other file")
            return
        from openfactory.adapters.forge.registry import clone_url_for, repo_of
        from openfactory.credentials import (
            bot_identity,
            deployment_forge_token,
            forge_token_for,
        )
        from openfactory.knowledge.pipeline import publish_bundle

        bot = bot_identity()
        # the deployment's own credential last: App-only deployments hold no static token, and a
        # tokenless push here failed with a remedy pointing at a credential that IS configured
        url = clone_url_for(view, repo_of(view),
                            token=forge_token_for(view) or deployment_forge_token(view))
        from openfactory.knowledge.pipeline import discard_fetched_bundle, fetch_published_bundle

        # The cache clone is reset on every sync, so the freshly built bundle ALWAYS looks new
        # here — but only its provenance stamp may differ from what is already published, and a
        # stamp-only commit on the client's knowledge branch per re-run is churn, not knowledge.
        # The MAP decides, not the stamp.
        published = fetch_published_bundle(url)
        if published is not None:
            try:
                same = ((published / "modules.yaml").read_bytes()
                        == (dest / "modules.yaml").read_bytes())
            except OSError:
                same = False
            finally:
                discard_fetched_bundle(published)
            if same:
                typer.echo("  · already published — the knowledge branch carries this exact map")
                return
        if publish_bundle(dest, url, source_commit=commit, author=(bot.name, bot.email)):
            typer.echo("  ✓ published to the repository's knowledge branch — the next job "
                       "reads it from there")
        else:
            typer.echo("  ✗ the map was built and NOT published — check the forge credential; "
                       "the post-merge refresh will retry after the next merge")
            raise typer.Exit(1)


@knowledge_app.command("check")
def knowledge_check(name: str) -> None:
    """Report whether a project's bundle is fresh and consistent (§12): staleness vs the
    working tree + any orphan `source:` links. Exits non-zero if the bundle is missing,
    stale, or has orphans — so CI/regeneration can gate on it."""
    from openfactory.factory import resolve_repo_path
    from openfactory.knowledge import is_stale, orphan_links, read_bundle

    project = _get_project(name)
    # the same resolution `build` uses — a factory-cloned project's repo_path is a URL,
    # and Path(url) is a directory precisely nowhere
    repo = resolve_repo_path(project)
    bundle = read_bundle(repo)
    if bundle is None:
        typer.echo("no bundle — run `openfactory knowledge build` first")
        raise typer.Exit(1)
    stale = is_stale(bundle, repo)
    orphans = orphan_links(bundle, repo)
    commit = bundle.manifest.source_commit[:8] or "(none)"
    typer.echo(f"modules: {len(bundle.module_map.modules)}  commit: {commit}")
    typer.echo(f"stale: {stale}")
    if orphans:
        typer.echo(f"orphan links ({len(orphans)}): " + ", ".join(orphans[:10]))
    if stale or orphans:
        typer.echo("NOT fresh — regenerate with `openfactory knowledge build`")
        raise typer.Exit(1)
    typer.echo("OK — bundle is fresh and consistent")


@app.command("conformance")
def conformance(name: str) -> None:
    """Check whether a project is runnable (required slots filled)."""
    project = _get_project(name)
    manifest = load_manifest(project)
    report = check(manifest, Path(project.repo_path).expanduser())
    for issue in report.issues:
        typer.echo(f"[{issue.level}] {issue.message}")
    if report.ok:
        typer.echo(f"OK — {name!r} is runnable")
    else:
        typer.echo("NOT runnable — fix the errors above")
        raise typer.Exit(1)


@app.command("onboard")
@speaks_plainly("onboard that repository")
def onboard_cmd(
    name: str,
    source: list[str] = typer.Option(None, "--source",  # noqa: B008 — typer's own idiom
                                     help="Another repository of this product, owner/name "
                                          "(repeatable). The registry's own repo is always "
                                          "included"),
    sandbox: str = typer.Option("container", help="Which box proves each repository"),
    skip_context: bool = typer.Option(False, "--skip-context",
                                      help="Only the source repositories — leave the context "
                                           "repository and the backfill for later (§9)"),
    yes: bool = typer.Option(False, "--yes",
                             help="Required: this opens pull requests on YOUR repositories"),
) -> None:
    """First-time setup, done where the factory lives — one command, every repository.

    Per repository of the product: clone, READ the manifest out of the code, PROVE it in the
    real box (your own setup:/validate:, streamed live), generate the module map, and open ONE
    pull request carrying all of it — the proof verdict and the questions only your team can
    answer are in the PR body. A repository that already declares its manifest is proven as-is
    and only what is missing is proposed.

    A product that spans repositories (front + back) names them with --source; each gets its
    own manifest, its own proof and its own pull request, which is exactly how the runtime
    treats them (a card runs against ITS repository's box)."""
    from openfactory.onboarding.onboard import onboard_source_repo

    project = _get_project(name)
    # THE FORGE AXIS NAMES THE CODE, with the tracker as fallback — the same precedence
    # _ref_repo uses everywhere. Never BOTH: an ADO tracker.repo is the ADO *project* (work
    # items), and a GitHub deployment may track issues in a separate repository — sweeping the
    # tracker axis in onboarded a repository that holds no code. And no `"/" in r` filter: an
    # ADO registry row carries the BARE repository name, and the filter made the recommended
    # path silently dead on Azure DevOps (adversarial review, 2026-08-13).
    default_repo = (project.forge.repo if project.forge else None) or project.tracker.repo or ""
    repos = sorted({r for r in [default_repo, *(source or [])] if r})
    if not repos:
        typer.echo(f"✗ {name} names no repository in its registry entry and no --source was "
                   f"given — there is nothing to onboard")
        raise typer.Exit(2)
    if not yes:
        typer.echo(f"This will open a pull request on: {', '.join(repos)} — re-run with --yes.")
        raise typer.Exit(2)

    def _stage(kind: str, text: str) -> None:
        if kind == "start":
            typer.echo(f"  … {text}", err=True)
        elif kind == "line":
            typer.echo(f"      {text.rstrip()}", err=True)

    outcomes = []
    for repo in repos:
        typer.echo(f"\n── {repo}")
        outcome = onboard_source_repo(project, repo, sandbox=sandbox, stream=_stage)
        outcomes.append(outcome)
        mark = "✓" if outcome.ok else "✗"
        typer.echo(f"{mark} {outcome.detail or outcome.pr or outcome.proof}")

    context_outcome = None
    if not skip_context:
        from openfactory.onboarding.onboard import onboard_product_context

        typer.echo("\n── the context repository")
        context_outcome = onboard_product_context(project, sources=repos, stream=_stage)
        mark = "✓" if context_outcome.ok else "✗"
        made = " (created)" if context_outcome.created else ""
        typer.echo(f"{mark} {context_outcome.docs_repo or 'context'}{made} — "
                   f"{context_outcome.detail}")
        if context_outcome.backfill:
            typer.echo(f"  backfill: {context_outcome.backfill}")
        elif context_outcome.ok:
            typer.echo("  backfill: not reached")
        for t in context_outcome.todo:
            typer.echo(f"  · still yours: {t}")

    typer.echo("\n── the product, repository by repository")
    failed = False
    for o in outcomes:
        if o.ok and o.pr:
            line = f"  ✓ {o.repo:<30} proof: {o.proof:<8} → {o.pr}"
        elif o.ok:
            # THE DETAIL, not a summary of it: ok-without-a-URL covers both "nothing new to
            # propose" and "pushed but the review request did not open — open it by hand",
            # and collapsing the second into the first told the operator a repository was
            # done when a step of it still needs a hand (adversarial review, 2026-08-13)
            line = f"  · {o.repo:<30} proof: {o.proof:<8} {o.detail}"
        else:
            line = f"  ✗ {o.repo:<30} {o.detail}"
            failed = True
        typer.echo(line)
        for q in o.questions[:4]:
            typer.echo(f"        ? {q}")
    if context_outcome is not None:
        if context_outcome.ok and context_outcome.pr:
            typer.echo(f"  ✓ {context_outcome.docs_repo:<30} context → {context_outcome.pr}")
        elif context_outcome.ok:
            typer.echo(f"  · {context_outcome.docs_repo:<30} {context_outcome.detail}")
        else:
            typer.echo(f"  ✗ {context_outcome.docs_repo or 'context':<30} "
                       f"{context_outcome.detail}")
            failed = True
    # THE HANDOVER, said as an instruction rather than as a closing pleasantry. Everything above
    # is a PROPOSAL; the factory does not merge its own declaration of what it will run against
    # somebody's repository, so this is the step that is deliberately the operator's — and it
    # has to read like one (pilot, 2026-08-14: he merged only because I said so in chat, which
    # is assistance a normal installation does not have).
    typer.echo("\n── YOUR STEP: review and merge the pull request(s) above")
    typer.echo("   Nothing here is in effect until you do: the manifest declares what this "
               "platform will run against your code, so a person reads it before it is true.")
    typer.echo(f"   Then run `openfactory doctor {name}` — until the merge it reports the "
               f"manifest as PROPOSED and names that pull request; after it, it is what says "
               f"when a ticket can run.")
    if failed:
        raise typer.Exit(1)


@app.command("floor")
def floor_cmd(
    project: str = typer.Argument("", help="one project, or nothing for the whole deployment"),
    as_json: bool = typer.Option(False, "--json", help="the raw struct, for a script"),
) -> None:
    """Is the factory working? — the same answer the panel shows, on a terminal.

    THE SECOND TRANSPORT, and that is the point rather than a convenience. The house rule is that
    every capability is reachable from at least two front ends and implemented by none of them
    (`openfactory/actions/__init__.py`); a verdict that only a web page can obtain is a verdict
    that lives in the web page. This command and `GET /api/floor` are two mappings onto one
    module — if they ever disagree, one of them derived something, which is the defect the whole
    ladder exists to prevent.
    """
    import asyncio
    import json as _json

    from openfactory import floor

    got = floor.state(asyncio.run(floor.gather(want=floor.EVERYTHING)), project)
    if as_json:
        typer.echo(_json.dumps(got.as_dict(), indent=2))
        return
    typer.echo(got.line)
    for line in (got.meta, got.detail):
        if line:
            typer.echo(f"  {line}")
    if got.cmd:
        typer.echo(f"  → {got.cmd}")
    for row in got.also:
        typer.echo(f"  Also — {row['clause']}")
    if got.also_more:
        typer.echo(f"  +{got.also_more} more")
    if got.census_line:
        typer.echo(f"  {got.census_line}")


@app.command("preflight")
def preflight_cmd(
    as_json: bool = typer.Option(
        False, "--json",
        help="Emit the state document the agent lane reads, instead of the human report."),
) -> None:
    """Say what about THIS machine will stop the stack, before anything starts.

    `doctor` asks whether a PROJECT can run a ticket — credentials, board, manifest, floor — and
    needs a running deployment to ask it in. This asks the question that comes before that one,
    and it is the only interesting question during an install: the user has typed one command,
    nothing is up yet, and what they need is every remaining obstacle at once, each with its
    remedy.

    NO PROJECT ARGUMENT, and that is the whole difference. Every finding here is about the host.
    """
    from openfactory import preflight

    report = preflight.check(preflight.probes_for_this_machine())

    if as_json:
        typer.echo(preflight.as_json(report))
    else:
        for f in report.findings:
            # THREE STATES, THREE MARKS. `----` is not a pass and not a failure: it is "no answer
            # exists on this machine", and collapsing it into either is how a diagnostic reports a
            # permissions failure as a clean bill of health (`readiness.Finding.answered`, and
            # `doctor.BoardUnreadable` at length before it).
            mark = "  ok  " if f.ok and f.answered else (" ---- " if not f.answered else " FAIL ")
            typer.echo(f"{mark} {f.check:<17} {f.message}")
            if not f.ok and f.remedy:
                typer.echo(f"        {'':<17} → {f.remedy}")
        typer.echo(f"\n{report.verdict}")

    # NON-ZERO WHEN ANYTHING IS MISSING, because `install.sh` reads the exit code to decide whether
    # to go on — and an UNANSWERED check must not make it non-zero, or a machine whose daemon is
    # simply not up yet would look like a machine with a broken install. `Report.ok` counts only
    # answered failures, which is the same rule `readiness.Report.missing` holds.
    if not report.ok:
        raise typer.Exit(1)


@app.command("doctor")
def doctor_cmd(name: str) -> None:
    """Check every prerequisite and say which one is missing.

    `conformance` asks whether the MANIFEST is complete. This asks whether the machine, the
    credentials and the board can actually run a ticket — the things whose absence otherwise looks
    identical to a factory that is simply quiet."""
    import logging

    from openfactory import doctor as doc

    project = _get_project(name)
    # EVERY PROBE FAILURE IS REPORTED BELOW, AS A LINE WITH A REMEDY — so the adapters' own
    # warnings, printed to stderr by the root logger, arrive as a second copy in OUR internal
    # vocabulary, above the table, before the reader knows there is a table. The pilot saw
    # "the caller must treat this as UNREADABLE, never as a board without columns" as the FIRST
    # thing doctor said (2026-08-14). Quieted for this command only; ERROR still speaks.
    quieted = logging.getLogger("openfactory")
    was = quieted.level
    quieted.setLevel(logging.ERROR)
    try:
        report = doc.diagnose(doc.probes_for(project))
    finally:
        quieted.setLevel(was)

    # WHICH CODE ANSWERED. First line, before any finding, because it is the first thing to
    # doubt when a fix that was pulled does not appear: the worker runs a BAKED package, so a
    # restart without `--build` re-runs the previous one and every line below is that build's
    # opinion (measured on the pilot, three identical outputs across two fixes, 2026-08-14).
    code, built = namespace.build_stamp()
    if code:
        typer.echo(f"· this worker runs build {code}, from {built} — `docker compose "
                   f"--env-file .env.compose up -d --build` is what replaces it after a pull")
        # AND WHETHER THE OTHER HALVES AGREE (#135). This command runs INSIDE the worker, so
        # everything above is the worker's opinion of itself — which is exactly what was true on
        # 2026-08-17, when the worker was two minutes old, the panel was twenty-eight hours old,
        # and the operator read a doctor report that was entirely accurate about the half he was
        # not looking at.
        from openfactory.runtime.temporal.worker import WORKER_ROLE

        for role, (stamp, when) in sorted(namespace.build_disagreement(WORKER_ROLE).items()):
            typer.echo(f"· WARNING the {role} runs a DIFFERENT build: {stamp}, from {when}. "
                       f"Rebuild both — `up -d --build` with no service name after it.")
        typer.echo("")
    # WHERE PROJECT-LESS SPEECH GOES, as one line — because its absence was silent (2026-08-26:
    # a fallback row's two variables set, no declaration, `NullNotifier` built and nothing in
    # any log). Derived from the notifier registry; the doctor names no vendor.
    typer.echo(f"· {doc.notifier_fallback_line()}")
    typer.echo("")
    for f in report.findings:
        # NOT `f.mark`: this renders the DOCTOR's report, whose `Finding` is a different class in
        # `openfactory/doctor.py` and has two states, not three. The two loops look identical and
        # are about different objects — changing this one raised `AttributeError` inside the CLI
        # runner and turned fourteen doctor guards into a blank page (2026-08-30).
        typer.echo(f"{'  ok  ' if f.ok else ' FAIL '} {f.check:<14} {f.message}")
        if not f.ok and f.remedy:
            typer.echo(f"        {'':<14} → {f.remedy}")
    if report.ok:
        typer.echo(f"\nOK — {name!r} can run a ticket")
        # A PASS IS NOT ALWAYS THE END OF THE SENTENCE. "OK — can run a ticket" is true about the
        # CODE and silent about everything a healthy-but-off half means; the operator caught it
        # on exactly the screen that says so (2026-08-14): a project with no context repository
        # runs tickets and has no client-facing half at all, and the verdict said neither.
        for f in report.findings:
            if f.ok and f.note:
                typer.echo(f"  · {f.note}")
        return
    # "NOT READY" AND "SOMETHING IS BROKEN" ARE DIFFERENT SENTENCES, and printing the second when
    # the first is true sends somebody to fix what is merely not written yet. Registering a
    # project (ONBOARDING §2) cannot produce a manifest — the environment session in §3 does —
    # so at that exact point three checks are red BY CONSTRUCTION, and the pilot operator quite
    # reasonably went looking for the defect (2026-08-13).
    # EXPECTED means every red line is answered by a step the SEQUENCE still has ahead of it —
    # the manifest by §3, the box proof by §5 — not that the deployment is fine. Adding the box
    # gate to doctor (2026-08-14) would otherwise have taken this sentence away from every
    # operator at §2, where nothing has been proven yet BY CONSTRUCTION, which is the exact
    # confusion it was written to end.
    # DERIVED FROM THE FINDINGS, not from a list of names. The list was
    # `{"manifest", "quality_floor", "merge_policy", "box_proof"}`, and the next manifest-derived
    # check added anywhere in `doctor.py` — `post_merge`, 2026-08-16 — dropped straight out of it
    # and turned an operator's §2 report back into "fix the FAIL lines above", which is the exact
    # sentence this branch exists to stop. A check that could not run because the manifest is not
    # written yet SAYS so in its remedy; that is the fact, and the fact is what to read.
    # TWO WAYS A RED LINE IS ANSWERED BY A STEP AHEAD, and they are different facts (see
    # `doctor.Finding`): `awaiting` is downstream — it clears when the check it names clears —
    # while `not_yet` is a line that is true, will stay true after that step, and describes a
    # guarantee nothing needs until then. Reading only the first told a stranger at §2 to "fix
    # the FAIL lines above" about an API budget his machine cannot read and nothing is spending
    # (2026-08-24, the same accident `post_merge` produced in 2026-08-16).
    answered_later = {f.check for f in report.findings
                      if not f.ok and (f.awaiting or f.not_yet
                                       or f.check in ("manifest", "box_proof"))}
    failed = {f.check for f in report.findings if not f.ok}
    if failed <= answered_later and failed & {"manifest", "box_proof"}:
        # THE STEP COMES FROM THE FINDING, never composed here: this line hedged ("if onboard
        # already proposed it…") about a fact `doctor` had just looked up one screen away.
        nxt = next((f.next_step for f in report.findings if not f.ok and f.next_step),
                   f"see the FAIL lines above, then re-run `openfactory doctor {name}`")
        typer.echo("\nNOT ready — and at this point in the sequence that is EXPECTED: "
                   "everything the previous steps can settle is green, and the rest is what the "
                   "steps ahead answer.\n"
                   f"Next: {nxt}. Then run this again; it is the same command that says when "
                   "you are ready.")
    else:
        typer.echo("\nNOT ready — fix the FAIL lines above")
    raise typer.Exit(1)


approver_app = typer.Typer(help="Manage prod-release approvers (identity + password).")
app.add_typer(approver_app, name="approver")


@approver_app.command("add")
def approver_add(login: str) -> None:
    """Add/update an approver; prompts for a password (stored only as a hash)."""
    from openfactory.approvals import add_approver

    pw = typer.prompt(f"password for {login}", hide_input=True, confirmation_prompt=True)
    add_approver(login, pw)
    typer.echo(f"approver {login!r} saved. Add them to a project's `prod_approvers` to allow.")


@approver_app.command("list")
def approver_list() -> None:
    from openfactory.approvals import list_approvers

    for x in list_approvers():
        typer.echo(x)


@approver_app.command("remove")
def approver_remove(login: str) -> None:
    from openfactory.approvals import remove_approver

    remove_approver(login)
    typer.echo(f"removed {login!r}")


@app.command("serve")
def serve(
    host: str = typer.Option("127.0.0.1", help="Bind host"),
    port: int = typer.Option(8787, help="Bind port"),
) -> None:
    """Serve the web panel (observability + management) at http://host:port."""
    import uvicorn

    typer.echo(f"panel: http://{host}:{port}")
    # The panel module no longer loads `.env` on import (a library must not mutate the process's
    # environment), so the entry point does it — here, where a human asked for a server.
    from openfactory.api.app import PANEL_ROLE
    from openfactory.api.app import _load_environment as _panel_env

    _panel_env()
    # SAY WHICH BUILD SERVES THIS PAGE, where the other halves can read it (#135). Symmetric with
    # the worker: whichever half was not rebuilt is the stale one, and the deployment can only name
    # it if both announce. Here rather than at import — a library that writes files when it is
    # merely imported has bitten this project before — and before uvicorn takes the process.
    from openfactory import namespace

    namespace.announce_build(PANEL_ROLE)
    uvicorn.run("openfactory.api.app:app", host=host, port=port)


@app.command("bot-token")
def bot_token(
    app_id: str = typer.Option(None, help="GitHub App ID (default: OPENFACTORY_GH_APP_ID)"),
    key_path: str = typer.Option(
        None, envvar="OPENFACTORY_GH_APP_KEY",
        help="Path to the App .pem (or set OPENFACTORY_GH_APP_KEY_CONTENT with the PEM itself)",
    ),
    installation_id: str = typer.Option(
        None, help="Installation ID (default: OPENFACTORY_GH_APP_INSTALLATION_ID)"
    ),
) -> None:
    """Mint a GitHub App installation token (~1h) — and, on the onboarding path, PROVE the trio.

    Printing a `ghs_…` is the whole point there: it means App ID, private key and Installation
    ID agree and GitHub accepted them. There is nothing to save — the token expires in about an
    hour and the factory mints its own for every job. The pilot operator asked what to do with
    it (2026-08-12), which is fair: `--help` showed only the export form below, so the command
    read as something that produces a credential you keep.

    The export form is for a SHELL that needs a token for a one-off `gh` command:

        export OPENFACTORY_BOT_TOKEN=$(openfactory bot-token)
    """
    from openfactory.credentials import app_id as env_app_id
    from openfactory.credentials import app_installation_id, app_private_key

    # THE FLAGS FALL BACK TO THE COMPOSITION ROOT rather than reading the environment themselves
    # (#64). These carried `envvar=`, which made typer the FOURTH independent reader of
    # `OPENFACTORY_GH_APP_ID` / `OPENFACTORY_GH_APP_INSTALLATION_ID` — and the one place a future
    # per-project
    # override could never reach, since typer resolves it before any of our code runs. The
    # explicit flag still wins; `--help` now names the variable in prose instead.
    #
    # `key_path` stays as the flag — a path is what somebody types — but the KEY is resolved by the
    # composition root, which also accepts the content form a container is handed. This command run
    # inside the compose worker used to report a missing option while the PEM sat in its
    # environment.
    app_id = app_id or env_app_id()
    installation_id = installation_id or app_installation_id()
    key = app_private_key()
    if not (app_id and key and installation_id):
        typer.echo(
            "need OPENFACTORY_GH_APP_ID, OPENFACTORY_GH_APP_INSTALLATION_ID, and the App key as "
            "either "
            "OPENFACTORY_GH_APP_KEY (a path) or OPENFACTORY_GH_APP_KEY_CONTENT (the PEM itself)",
            err=True,
        )
        raise typer.Exit(1)
    from openfactory.adapters.github_app import mint_installation_token

    token, _expires = mint_installation_token(
        app_id=app_id, private_key=key, installation_id=installation_id
    )
    # THE TOKEN ON STDOUT, THE MEANING ON STDERR — so `$(openfactory bot-token)` still captures
    # exactly the token while a human at a terminal is told what they are looking at. Without
    # this the printed value reads as a fourth credential to paste somewhere.
    typer.echo("✓ the App trio works — this token was minted from it just now. Nothing to "
               "save: it expires in about an hour and the factory mints its own per job.",
               err=True)
    typer.echo(token)


_DONE_STATES = {JobState.PR_OPEN, JobState.MERGED, JobState.DONE}


def _box_kind(explicit: str | None) -> str:
    """Which box these commands run a job in — the flag, else what the DEPLOYMENT configured.

    ONE RESOLUTION FOR THE TWO COMMANDS THAT SPEND MONEY, and it exists because they both carried
    the literal `"worktree"` as a typer default. `default_sandbox()` was written for exactly this
    (`OPENFACTORY_SANDBOX` wins; absent it, the local container — nothing is inferred from a
    vendor's cluster variable) and the durable path has read it since C-13 — the CLI never did.

    WHAT THAT COST, found by running a real ticket rather than by reading: the OSS compose file
    sets `OPENFACTORY_SANDBOX: container` under a comment calling the container "the real,
    production
    path", and `poll` is the command its own docstring tells you to put on a cron. So every job on
    a compose install ran in the worker's own filesystem — the agent's arbitrary code beside the
    scheduler that launched it — while the file said otherwise.

    And it made a PROOF point at the wrong thing. `box prove` holds pickup until the CONTAINER box
    has run the project's gates (ADR-0037 D5); the job then ran in a worktree. A proof about a box
    nothing uses is the shape of defect this repository names most often.

    `None` rather than a default string, like `--image` one line below: a flag that always carries
    a value can never let the deployment's own answer win, because the override is indistinguishable
    from the default.
    """
    from openfactory.runtime.temporal.io import default_sandbox

    return (explicit or "").strip().lower() or default_sandbox()


@app.command("run")
@speaks_plainly("run that ticket")
def run(
    name: str,
    issue: str,
    # UNSET MEANS THE DEPLOYMENT'S BOX, not a hardcoded one — the same rule `--image` states two
    # lines down, for the same reason. It said `"worktree"`, so `OPENFACTORY_SANDBOX` was read by
    # the
    # durable path and ignored here, and the OSS compose file declares `container` out loud.
    sandbox: str = typer.Option(None, help="Sandbox: worktree|container "
                                           "(default: OPENFACTORY_SANDBOX, else container)"),
    # DEFAULTS TO UNSET, not to the framework's image. A flag that always carries a value can never
    # let the project's own `box.image` win — the operator override would be indistinguishable from
    # the default (ADR-0037 D4).
    image: str = typer.Option(None, help="Base image for --sandbox container (default: the "
                                         "project's box.image, else OPENFACTORY_SANDBOX_IMAGE)"),
    review: bool = typer.Option(True, help="Run the independent reviewer (D-5)"),
) -> None:
    """Drive one ticket through the state machine."""
    project = _get_project(name)
    # C-18 HERE TOO. This called `build_runner(project, …)` with the raw registry entry, so a card
    # naming its own repository was edited in the DEFAULT one. The durable path applied the view;
    # the CLI did not — and the CLI is what an operator uses to try the platform, and what an
    # onboarding session runs in front of a client's developers.
    #
    # Found on the first real multi-repo ticket: `Deskline/fx-dsk-ui#15`, a card about the
    # TypeScript UI, produced a PR against `fx-dsk-flows` editing `src/Admissao.cs` — the .NET
    # backend. The independent review rejected it (score 10, "the diff only modifies the .NET
    # backend but the ticket's entire premise is the UI"), which is the guard working. This is the
    # routing that put it there.
    from openfactory.runtime.card_repo import _runner_view

    view, _ = _runner_view(project, issue)
    box = _box_kind(sandbox)
    resolved = resolve_box_image(view, explicit=image, sandbox=box)
    result = build_runner(view, issue, sandbox=box, image=resolved,
                          review=review).run(issue)
    typer.echo(result.model_dump_json(indent=2))
    if result.state not in _DONE_STATES:
        raise typer.Exit(1)


@app.command("poll")
@speaks_plainly("read this project's board")
def poll(
    name: str,
    # UNSET MEANS THE DEPLOYMENT'S BOX. `"worktree"` here was the sharpest instance of it: this
    # command IS the scheduler ("run this on a cron/loop"), so every job on a compose install ran
    # in the worker's own filesystem while `OPENFACTORY_SANDBOX: container` sat in the file two
    # lines
    # under a comment calling the container "the real, production path". Worse, `box prove` holds
    # pickup until the CONTAINER box is proven (ADR-0037 D5) — so the box that was proven and the
    # box that ran were different ones, which makes the proof an assertion about somewhere else.
    sandbox: str = typer.Option(None, help="Sandbox: worktree|container "
                                           "(default: OPENFACTORY_SANDBOX, else container)"),
    image: str = typer.Option(None, help="Base image for --sandbox container (default: the "
                                         "project's box.image, else OPENFACTORY_SANDBOX_IMAGE)"),
) -> None:
    """For an ENABLED project: resume any rate-limit-paused tickets whose reset has
    passed, then pick up the board's TODO column — one at a time, stopping when one
    pauses or goes on hold (no parallelism). Run this on a cron/loop as the scheduler."""
    import time

    from openfactory.credentials import deployment_tracker_token, tracker_token_for
    from openfactory.scheduler import ready_to_resume

    project = _get_project(name)
    if not project.enabled:
        typer.echo(f"{name}: framework OFF — nothing picked up")
        return
    from openfactory.adapters.board import build_board

    # ASK THE FACTORY WHETHER THERE IS A BOARD; do not infer it from GitHub's option names. This
    # gated on `board_owner`/`board_number` and therefore told every JIRA project "no board
    # configured" while `build_board` was building one perfectly well — a live defect, not one
    # Azure introduced; ADO only made it a second victim. Both providers put the board WHERE THE
    # WORK ITEM ALREADY IS (a status is a column), so there is no second object to name, and a
    # caller that demands coordinates for one is demanding configuration the vendor cannot supply.
    # `None` is build_board's own first-class answer for "no board", so it is the right question.
    board = build_board(project, token=tracker_token_for(project)
                        or deployment_tracker_token(project))
    if board is None:
        typer.echo(f"{name}: no board configured")
        raise typer.Exit(1)
    # THE BOARD NAMES ITS OWN PICKUP COLUMN. A literal "TO-DO" here asked an Azure board for a
    # column it does not have and printed "0 in 'TO-DO'" — a correct-looking report of an empty
    # queue with six cards waiting in it.
    status = project.tracker.options.get("pickup_status") or board.pickup_column()

    resume = ready_to_resume(project, time.time())
    todo = [str(n) for n in board.items_in_status(status)]
    queue = resume + [t for t in todo if t not in resume]
    typer.echo(f"{name}: {len(resume)} to resume + {len(todo)} in '{status}'")
    # Resolved ONCE, before the loop, so a fargate deployment that declares box.image refuses
    # before any ticket is picked up rather than halfway through the queue.
    box = _box_kind(sandbox)
    resolved = resolve_box_image(project, explicit=image, sandbox=box)
    for num in queue:
        typer.echo(f"→ #{num}")
        result = build_runner(project, str(num), sandbox=box, image=resolved, review=True).run(
            str(num)
        )
        typer.echo(f"  {result.state.value}")
        if result.state is JobState.PAUSED:
            typer.echo(f"  agent paused ({result.note}) — stopping the board.")
            break
        if result.state in (JobState.ON_HOLD, JobState.BLOCKED):
            typer.echo("  impediment — stopping (no parallelism).")
            break


# ── the action layer, from a shell (C-23) ────────────────────────────────────────────────────────
#
# THE SECOND UNIVERSAL TRANSPORT, and the cheap one. `POST /api/act/{name}` needs a running panel
# and a token; this needs a shell on the host, which is where an operator already is when something
# has gone wrong at 2am. Together they are what makes "every action is reachable from at least two
# transports" true BY CONSTRUCTION rather than by somebody remembering to add a route and a verb
# for each new action — which is the exact discipline that failed and produced #51.
#
# It is also how the actions blocked on other cards stay honest: `openfactory act ask` prints the
# sentence saying where that capability still lives, instead of the command not existing at all.

def _get_project(name: str):
    """The registered project, or the one-line refusal the first hour is owed.

    `openfactory doctor myapp` before `project add` — the literal order a reader might take from
    the docs — used to end in a raw KeyError traceback. A stranger's first failure must name the
    fix, not the stack (measured in the pre-pilot review, 2026-08-09)."""
    # resolved from the MODULE at call time, not from this file's import-time binding — the
    # onboarding tests substitute the registry at that seam, and `cmd_onboard` always honoured it
    from openfactory import registry as _registry_module

    reg = _registry_module.ProjectRegistry()
    try:
        return reg.get(name)
    except KeyError:
        try:
            names = sorted(p.name for p in reg.list())
        except Exception as exc:  # noqa: BLE001 — the refusal must not fail while refusing
            log.warning("could not list the registered projects while refusing %r (%s) — the "
                        "refusal stands, just without the roster", name, exc)
            names = []
        listed = ", ".join(names) if names else "none yet"
        typer.echo(f"✗ project {name!r} is not registered — run "
                   f"`openfactory project add {name} <path-or-clone-url> --repo <org>/<repo>` "
                   f"first. Registered here: {listed}.")
        raise typer.Exit(2) from None


def _parse_params(pairs: list[str], *, flag: str = "--param") -> dict[str, object]:
    """`k=v` strings → a params dict, with `true`/`false` becoming booleans.

    ONLY BOOLEANS ARE COERCED. Numbers deliberately stay strings: a ticket ref is a provider-owned
    opaque string (`189`, `CONT-412`) and turning `189` into an int here would hand the layer a
    type no tracker uses and reintroduce the `int(ref)` class C-04 spent a card killing.

    `flag` EXISTS BECAUSE THE ERROR NAMES IT. A second caller arrived (`env apply --set`) and the
    message still read "--param takes key=value" — a remedy pointing at an option that command does
    not have, which is the same defect as `conformance` printing `stack: security-oss` at a schema
    that forbids it, only smaller. The caller says which flag it is."""
    out: dict[str, object] = {}
    for pair in pairs:
        key, sep, value = pair.partition("=")
        if not sep:
            raise typer.BadParameter(f"{flag} takes key=value, got {pair!r}")
        text = value.strip()
        low = text.lower()
        out[key.strip()] = True if low == "true" else False if low == "false" else text
    return out


@app.command("actions")
def actions_list() -> None:
    """List everything this deployment can be asked to DO, and what each one takes."""
    from openfactory import actions as act_layer

    for entry in act_layer.CATALOG.values():
        takes = " ".join(f"<{p}>" for p in entry.required)
        takes += "".join(f" [{p}]" for p in entry.optional)
        mark = "" if not entry.pending else "  (not moved yet)"
        typer.echo(f"{entry.name:<14}{takes:<44}{entry.summary}{mark}")


@app.command("act")
def act_cmd(
    name: str = typer.Argument(..., help="Which action — see `openfactory actions`"),
    project: str = typer.Option(None, "--project", "-p", help="Shorthand for --param project=…"),
    issue: str = typer.Option(None, "--issue", "-i", help="Shorthand for --param issue=…"),
    # noqa: B008 — every typer option in this file is a call in a default; ruff lets the scalar
    # ones pass and flags this one only because the ANNOTATION is a list. Typer's whole surface is
    # declarative defaults, and rewriting this one as a module singleton would make it the odd one.
    param: list[str] = typer.Option(None, "--param", "-P", help="key=value, repeatable"),  # noqa: B008
    as_json: bool = typer.Option(False, "--json", help="Print the whole Outcome as JSON"),
) -> None:
    """Run one action — `openfactory act resume -p acme -i 412`.

    Exits non-zero when the action did not do what was asked, so this composes in a script. The
    actor is the shell's own user, recorded as an admin: somebody with a shell where the factory
    runs already outranks every gate in this layer, and pretending otherwise would be theatre."""
    import asyncio
    import getpass
    import json as _json

    from openfactory import actions as act_layer

    params = _parse_params(list(param or []))
    if project:
        params["project"] = project
    if issue:
        params["issue"] = issue
    try:
        who = getpass.getuser()
    except (KeyError, OSError):
        # A container with no passwd entry and no LOGNAME/USER — the documented failure of
        # `getpass.getuser`, and it must not stop the action: the identity here is a label for the
        # audit line, not the authority. Named rather than a catch-all, so this stays a defined
        # branch instead of a swallow (`tests/test_no_silent_failures.py`).
        who = "unknown"
    outcome = asyncio.run(act_layer.perform(
        name, by=act_layer.Actor(id=who, display=who, via="cli", admin=True), **params))
    if as_json:
        typer.echo(_json.dumps({"ok": outcome.ok, "code": outcome.code,
                                "message": outcome.message, "data": dict(outcome.data)}, indent=2))
    else:
        typer.echo(("" if outcome.ok else f"{outcome.code}: ") + outcome.message)
    if not outcome.ok:
        raise typer.Exit(1)




# ── `openfactory env` — the environment round (#99)
# ─────────────────────────────────────────────────────
#
# THE DOOR TO THE ONLY VERBS IN THIS PLATFORM THAT PROPOSE. `doctor`, `conformance` and `box prove`
# above all VERIFY what a client already declared; on a legacy codebase the hard part is not
# verifying the test command, it is finding it among four candidates, three of which only work on
# one developer's laptop. These three read the repository and say what they think, with the file and
# line they read it from and how sure they are.
#
# THIS SUB-APP HOLDS NO LOGIC. Every command below is a mapping onto one row of `actions/catalog.py`
# (ADR-0039: one action, one implementation, N transports), so the panel — the reference surface,
# ADR-0038 — gets the same three verbs on the same day rather than in a card nobody opens. What
# lives here is the RENDERING, which is the one part that is genuinely a transport's: how the
# proposal prints is the product, because it is read aloud in a room with the client's developers
# and it has about ten seconds to make one of them say "no, the real test command is X".
#
# DELIBERATELY NO COLOUR. This is screen-shared, pasted into chat and read by `grep`; ANSI codes
# survive none of those well, and the one place this repository scraped coloured output for a word
# it matched nothing at all.

env_app = typer.Typer(help="The environment round: propose a project's setup, then prove it.")
app.add_typer(env_app, name="env")

#: How wide the field-name column may grow before the value moves to its own line.
_NAME_COL = 26
#: How wide a line may be before a value is wrapped onto continuation lines.
_WIDTH = 96


def _perform(name: str, **params: object):
    """Run one catalogued action as the shell's own user. The CLI's whole job in this sub-app.

    The actor is an admin for the same reason `openfactory act` says so: somebody with a shell
    where the factory runs already outranks every gate in this layer, and pretending otherwise is
    theatre."""
    import asyncio
    import getpass

    from openfactory import actions as act_layer

    try:
        who = getpass.getuser()
    except (KeyError, OSError):
        who = "unknown"
    return asyncio.run(act_layer.perform(
        name, by=act_layer.Actor(id=who, display=who, via="cli", admin=True), **params))


def _show(value: object) -> list[str]:
    """A proposed value as the lines a human reads — the SHAPE it will have in the file.

    A list of setup commands prints as one command per line and a mapping prints as `key: value`,
    because that is what `.openfactory/project.yaml` will look like and because a client scanning
    this is
    checking their commands, not admiring a data structure. `None` prints as `?`, never as an empty
    string: the difference between *the platform could not read this* and *this is empty* is the
    most expensive one in this codebase, and it must survive to the screen."""
    if value is None:
        return ["?"]
    if isinstance(value, list | tuple):
        return [str(v) for v in value] or ["(nothing)"]
    if isinstance(value, dict):
        return [f"{k}: {v}" for k, v in value.items()] or ["(nothing)"]
    text = str(value)
    return [text] if text.strip() == text else [repr(text)]  # padding is invisible; show it


def _field_block(row: dict, *, width: int) -> None:
    """One proposed field: what it is, what it says, and — indented under it — where that came
    from. Two lines rather than a table because the provenance is the part being sold, and a
    provenance squeezed into a fourth column is a provenance nobody reads."""
    name = row.get("name", "?")
    # AN `unknown` FIELD HAS NO VALUE TO SHOW, whatever happens to be sitting in `value`. A
    # proposal may carry `{}` there and mean "we looked and found none" — but the tier already
    # said the platform is not asserting anything, and printing `(nothing)` beside the word
    # `unknown` invites the reader to take the empty mapping as our answer. `?` is the answer, and
    # it is the one a developer can respond to out loud.
    lines = ["?"] if row.get("confidence") == "unknown" else _show(row.get("value"))
    head, rest = lines[0], lines[1:]
    if len(name) <= width and len(name) + len(head) + 4 <= _WIDTH:
        typer.echo(f"  {name:<{width}}  {head}")
    else:
        typer.echo(f"  {name}")
        typer.echo(f"  {'':<{width}}  {head}")
    for extra in rest:
        typer.echo(f"  {'':<{width}}  {extra}")
    confidence = row.get("confidence", "?")
    # A CLAIM WITH NO CITATION IS SHOWN AS ONE. `observed` means somebody can go and look; if the
    # inference could not say where, the reader sees `(no source recorded)` rather than a blank
    # that reads like modesty.
    source = row.get("source") or ("(no source recorded)" if confidence != "unknown" else "")
    tail = f"    {confidence} · {source}" if source else f"    {confidence}"
    typer.echo(tail)
    for line in _wrap(str(row.get("note") or ""), indent=6):
        typer.echo(line)
    # THE RUNNERS-UP, because on a legacy repository there are four candidate test commands and a
    # developer recognises theirs faster from a list of four than from one confident wrong line.
    for alt in row.get("candidates") or []:
        why = f"  ({alt['why']})" if alt.get("why") else ""
        typer.echo(f"      or: {_show(alt.get('value'))[0]}   [{alt.get('source') or '?'}]{why}")


def _wrap(text: str, *, indent: int) -> list[str]:
    """Prose wrapped to the terminal, or nothing at all for an empty string.

    Empty in, empty out — a blank indented line under every field would double the length of the
    report, and length is the enemy of the ten seconds this has to be read in."""
    import textwrap

    if not text.strip():
        return []
    pad = " " * indent
    return textwrap.wrap(text.strip(), width=_WIDTH - indent,
                         initial_indent=pad, subsequent_indent=pad)


@env_app.command("read")
def env_read_cmd(
    target: str = typer.Argument(..., help="A path to a checkout, or a registered project name"),
) -> None:
    """Read a repository and PROPOSE what its `.openfactory/project.yaml` should say. Writes
    nothing.

    Every field comes back with the value, the file and line it was read from, and how sure the
    platform is. The `unknown` block is not the leftovers — it is the agenda: those are the
    questions a developer answers out loud while this is on the screen.
    """
    outcome = _perform("env_read", target=target)
    data = dict(outcome.data)
    if not outcome.ok:
        typer.echo(f"{outcome.code}: {outcome.message}")
        raise typer.Exit(1)

    rows = list(data.get("fields") or [])
    name = data.get("project") or Path(str(data.get("repo", target))).name
    typer.echo(f"env read · {name}")
    typer.echo(f"  repository   {data.get('repo')}"
               f"  ({'registered project' if data.get('read_as') == 'project' else 'a path'})")
    # A REPOSITORY READ IS THE SAME ON ANY MACHINE, and saying so here is not padding: `env check`
    # below is NOT, and a reader who has seen one provenance line has to be told which of the two
    # they are looking at.
    typer.echo(f"  measured on  {data.get('measured_on')} — a repository read is the same "
               f"anywhere; `env check` is not.")
    if data.get("unreadable"):
        typer.echo(f"  ! {data['unreadable']} entr(y/ies) in the proposal carried no confidence "
                   f"and were skipped — they are NOT in the report below.")

    width = min(_NAME_COL, max((len(str(r.get('name', ''))) for r in rows), default=0))
    for tier, title in (
        ("observed", "PROPOSED — read out of the repository"),
        ("inferred", "INFERRED — a guess from your CI file. Right, or what is the real one?"),
        ("unknown", "ONLY YOUR DEVELOPERS CAN ANSWER — nothing in the repository decides these"),
    ):
        mine = [r for r in rows if r.get("confidence") == tier]
        if not mine:
            continue
        typer.echo("")
        typer.echo(f"{title} ({len(mine)})")
        for row in mine:
            typer.echo("")
            _field_block(row, width=width)

    # WHAT THE SCHEMA CANNOT SAY ABOUT THIS REPOSITORY — the block that is client 2 in its
    # entirety. `available_stacks()` is node/python/security-oss/terraform and a `Component`
    # requires BOTH `path` and `stack`, so a .NET 8 + SPFx client cannot declare a component at
    # all. Emitting one anyway produces YAML `conformance` refuses; staying quiet lets a client
    # discover it three days later. It is neither a proposal nor a failure, so it gets its own
    # heading.
    # …minus anything a field above already said in the same words. A question printed twice is
    # twenty seconds of a room re-reading something it has read, and the ten seconds this report
    # gets are the whole product.
    already = {str(r.get("note") or "").strip() for r in rows}
    for key, title in (
        ("cannot_express", "THE PLATFORM CANNOT EXPRESS THIS, and that is ours, not yours"),
        ("questions", "QUESTIONS THE REPOSITORY CANNOT ANSWER"),
        ("unreadable_dirs", "NOT READ AT ALL — a stack living under these is invisible above"),
    ):
        fresh = [x for x in (data.get(key) or []) if str(x).strip() not in already]
        for i, line in enumerate(fresh):
            if i == 0:
                typer.echo("")
                typer.echo(f"{title} ({len(fresh)})")
            for wrapped in _wrap(str(line), indent=2):
                typer.echo(wrapped)

    if data.get("ci_files_seen"):
        typer.echo("")
        typer.echo(f"  ! CI files found and NOT parsed: {', '.join(data['ci_files_seen'])} — "
                   f"'no CI' and 'a CI we could not read' have opposite remedies.")
    if data.get("truncated"):
        typer.echo(f"  ! the walk stopped at its own ceiling after {data.get('files_walked')} "
                   f"paths — this proposal does not cover the whole repository.")

    typer.echo("")
    if not rows:
        # READ, AND NOTHING THERE. Distinct from "could not read" — which is a refusal above, with
        # a different sentence and a non-zero exit.
        typer.echo("nothing proposed: the repository was read and no build file, CI file or "
                   "default branch was found. The whole manifest is a question.")
    typer.echo(outcome.message)
    handle = data.get("project")
    if data.get("destination_exists"):
        typer.echo(f"  {data.get('destination')} ALREADY EXISTS — `env apply` refuses to touch it "
                   f"without --force, and that is the right default.")
    if not handle:
        # EVERY REMEDY THIS PLATFORM PRINTS HAS TO BE RUNNABLE. `env apply` takes a registered
        # project (it writes, and the file records which project accepted what), so suggesting
        # `openfactory env apply <a path>` here would be the same defect as `conformance`
        # recommending
        # `stack: security-oss` to a schema that forbids it — a remedy that cannot be typed.
        typer.echo("  `env apply` writes for a REGISTERED project. Register this one first:")
        typer.echo(f"    openfactory project add <name> {data.get('repo')} --repo <owner/name>")
        return
    typer.echo(f"  write the observed fields:  openfactory env apply {handle} --yes")
    typer.echo(f"  accept an inferred one:     openfactory env apply {handle} --yes "
               f"--accept <field>")
    typer.echo(f"  correct one out loud:       openfactory env apply {handle} --yes "
               f"--set <field>=<the real command>")


@env_app.command("context")
def env_context_cmd(
    target: str = typer.Argument(..., help="A path to a checkout, or a registered project name"),
    ask: bool = typer.Option(False, "--ask", help="ONE read-only agent pass for the semantic "
                                                  "layer. Costs tokens. Off by default."),
    write: str = typer.Option(None, "--write", help="A CHECKOUT of the context repository to "
                                                    "write the documents into"),
    yes: bool = typer.Option(False, "--yes", help="Required by --write. Nothing is written "
                                                  "without it, and nothing is ever overwritten."),
) -> None:
    """Survey a repository and PROPOSE the context an agent will read from then on.

    THE OTHER HALF OF `env read`, AND THE BIGGER ONE. `env read` proposes how to BUILD the project.
    This proposes what the project IS — what it does, its vocabulary, its entry points, and the
    questions only a developer who worked there can answer. On the legacy codebase most clients
    actually bring, that is the real work of onboarding.

    `--ask` RUNS WHEREVER YOU TYPE THIS, and the action checks that rather than assuming it: the
    harness has to be on this machine's PATH, which is true in a terminal beside the client's
    developers and false in the panel's own image. Without it nothing is spent.

    `--write` needs `--yes`, and never overwrites a file that is already there.
    """
    outcome = _perform("env_context", target=target, ask=ask, write=write or "", yes=yes)
    data = dict(outcome.data)
    # THE REPORT TRAVELS WITH THE REFUSAL. A failed agent pass still surveyed the repository, and
    # throwing that away because the semantic half did not land would make the room re-run a walk
    # that already succeeded.
    if data.get("report"):
        typer.echo(data["report"])
        typer.echo("")
    for path in data.get("wrote") or []:
        typer.echo(f"  wrote    {Path(write) / path}")
    for path in data.get("skipped") or []:
        typer.echo(f"  kept     {Path(write) / path} — already there, never overwritten")
    for line in data.get("failed") or []:
        typer.echo(f"  FAILED   {line}")
    if not outcome.ok:
        typer.echo(f"{outcome.code}: {outcome.message}")
        raise typer.Exit(1)
    typer.echo(outcome.message)
    if not data.get("semantic"):
        typer.echo(f"  add the semantic layer (one agent pass):  openfactory env context {target} "
                   f"--ask")
    if not write:
        typer.echo(f"  write them into a context repository:     openfactory env context {target} "
                   f"--write <checkout> --yes")


@env_app.command("rehearse")
def env_rehearse_cmd(
    name: str = typer.Argument(..., help="A registered project"),
    yes: bool = typer.Option(False, "--yes", help="Approve the spend. Without it this prints the "
                                                  "estimate and calls no harness at all."),
    gates: bool = typer.Option(None, "--gates/--no-gates",
                               help="May the client's OWN test suite run here? Unset = only if a "
                                    "valid box proof already covers those exact commands."),
    by: str = typer.Option(None, "--by",
                           help="Who approved the spend (default: this shell's user)"),
    image: str = typer.Option(None, "--image", help="Override the box image for this round only"),
    turn_cap: int = typer.Option(None, "--turn-cap", help="Ceiling on the agent's turns"),
) -> None:
    """The ENVIRONMENT's first round — prove the loop before a real ticket is ever picked up.

    A box, a harness pass, a diff, the project's own gates and a reviewer, on a synthetic ticket
    the platform owns, in a throwaway clone with every git remote removed. It answers the one
    question a client asks in the room — *does the factory work here?* — and, when it does not,
    WHERE a real ticket would have died.

    NOT A PRE-FLIGHT. A pre-flight sizes a CARD; this measures the ENVIRONMENT, and it runs before
    there is a card at all.

    NOTHING IS SPENT WITHOUT `--yes`. The default prints what the round will cost, measured from
    what this deployment has already spent, and stops before the harness is constructed.

    IT TOUCHES NO TRACKER, NO BRANCH, NO PR AND NO BOARD. That is structural, not a promise: there
    is no tracker and no forge in the module at all.
    """
    import getpass

    from openfactory.onboarding.firstrun import (
        DEFAULT_TURN_CAP,
        Consent,
        Rehearsal,
        estimate_cost,
        probes_for,
        rehearse,
    )

    project = _get_project(name)
    probes = probes_for(project, image=image,
                        turn_cap=turn_cap if turn_cap is not None else DEFAULT_TURN_CAP)
    # A CONSENT WITH NO NAME IS A CONSENT NOBODY GAVE, and this line lands in the report a client
    # reads. The shell's own user is honest provenance and needs no flag; `--by` is for the case
    # where the person who typed it is not the person who approved it.
    consent = Consent(spend_approved=yes, gates_may_run=gates,
                      by=(by or getpass.getuser()) if yes else "")

    # THE HEADER BEFORE THE ROUND, not after. It carries the machine, the box and the estimate, and
    # each of those changes what every line under it means — a room watching stages appear needs it
    # first. `render()` prints it again at the end for whoever only keeps the tail.
    # ONLY WHEN THE ROUND ACTUALLY RUNS. Without `--yes` nothing streams between the header and
    # the report, so printing it here would print it twice — and a client reading two identical
    # provenance blocks reasonably wonders whether they are two different measurements.
    if yes:
        preview = Rehearsal(project=name, measured_on=probes.measured_on(),
                            sandbox_kind=probes.sandbox_kind(), estimate=estimate_cost(probes),
                            consent=consent)
        for line in preview.header():
            typer.echo(line)
        typer.echo("")

    # PROGRESS GOES TO STDERR. A round with two agent passes takes minutes and a silent terminal in
    # front of a client is the one thing this platform refuses everywhere else; keeping it off
    # stdout means `openfactory env rehearse x > report.txt` still captures exactly the report.
    run = rehearse(probes, consent=consent,
                   on_start=lambda stage: typer.echo(f"  … {stage}", err=True))
    typer.echo("\n".join(run.render()))
    if not yes:
        typer.echo("")
        typer.echo(f"  approve it and run for real:  openfactory env rehearse {name} --yes")
        typer.echo(f"  and if their suite must NOT run here:  openfactory env rehearse {name} "
                   f"--yes --no-gates")
    raise typer.Exit(run.exit_code)


@env_app.command("check")
def env_check_cmd(
    name: str = typer.Argument(..., help="A registered project"),
) -> None:
    """ONE verdict on whether this project can be picked up — and WHERE it was measured.

    `doctor`, `conformance` and `box status` answer three different questions in three different
    scopes and none of them knows about the others; this is the composition. Exits non-zero unless
    pickup is genuinely unblocked — including when the verdict is one this CLI does not recognise,
    because an unrecognised verdict must never read as a green one.
    """
    outcome = _perform("env_check", project=name)
    data = dict(outcome.data)
    if not outcome.ok:
        typer.echo(f"{outcome.code}: {outcome.message}")
        raise typer.Exit(1)

    where = data.get("measured_on")
    typer.echo(f"env check · {name}")
    typer.echo(f"  measured on  {where}")
    if where != "worker":
        typer.echo("  ! this is the machine you typed on, not the one that runs your tickets. A "
                   "docker, a PATH or a credential can differ there.")
    typer.echo("")
    findings = list(data.get("findings") or [])
    width = min(18, max((len(str(f.get("check", ""))) for f in findings), default=0))
    for f in findings:
        # THREE MARKERS, NOT TWO. `----` is a check nothing on this machine could answer, and it is
        # deliberately not a shade of `ok`: a reader must be unable to mistake "nobody asked that
        # here" for "that is fine", which is how a report that measured nothing reads as green.
        mark = "  ok  " if f.get("ok") else " FAIL "
        if not f.get("answered", True):
            mark = " ---- "
        # `?` RATHER THAN THE RUN'S OWN PROVENANCE. Lending this line the header's `measured_on`
        # would present a finding measured on a laptop as measured in the factory, which is the
        # one substitution the whole field exists to prevent.
        typer.echo(f"{mark} {str(f.get('check', '?')):<{width}}  {f.get('message', '')}"
                   f"   [{f.get('measured_on') or '?'}]")
        if not f.get("ok") and f.get("remedy"):
            typer.echo(f"        {'':<{width}}  → {f['remedy']}")
    for extra in (data.get("holds") or [])[1:]:
        typer.echo(f"  also holding: {extra}")
    if data.get("unattributed"):
        typer.echo("")
        typer.echo(f"  ! {len(data['unattributed'])} finding(s) did not say where they were "
                   f"measured: {', '.join(data['unattributed'])}")
    typer.echo("")
    typer.echo(outcome.message)
    if data.get("ready") is not True:
        # `is not True` AND NOT `not data.get(...)`: a MISSING key must not read as ready. A
        # negative guard cannot see an absent value, which is how absence comes to read as
        # compliance — the exact defect this platform has shipped and written down.
        raise typer.Exit(1)


@env_app.command("apply")
def env_apply_cmd(
    name: str = typer.Argument(..., help="A path to your checkout, or a registered project name "
                                         "— the same two forms `env read` takes"),
    yes: bool = typer.Option(False, "--yes", help="Actually write. Without it, this only SHOWS "
                                                  "the file it would write, and exits 2."),
    force: bool = typer.Option(False, "--force", help="Replace an existing manifest (the current "
                                                      "one is copied to .bak first)"),
    accept: list[str] = typer.Option(None, "--accept",  # noqa: B008 — typer's own idiom
                                     help="Also write this INFERRED field (repeatable, or `all`)"),
    set_: list[str] = typer.Option(None, "--set",  # noqa: B008 — typer's own idiom
                                   help="field=value — your own answer, which outranks anything "
                                        "the platform inferred (repeatable)"),
    out: str = typer.Option(None, "--out", help="Write somewhere else than the repo's manifest "
                                                "path — for reviewing before committing"),
    pr: bool = typer.Option(False, "--pr",
                            help="No checkout here? Have the factory clone the repository and "
                                 "propose the manifest as a PULL REQUEST for you to review. "
                                 "This is how a deployment with no laptop anywhere onboards a "
                                 "project registered by clone URL"),
) -> None:
    """Write the proposed `.openfactory/project.yaml` — only what a human accepted, only with
    `--yes`.

    `observed` fields are written; `inferred` ones need `--accept <field>`; `unknown` ones are
    never written at all unless you answer them with `--set`, because an empty value is not an
    absence — it is a declaration that this project has no such thing, and a manifest that declares
    nothing loads perfectly and is then reported healthy.

    An existing manifest is never replaced without `--force`, and even then the previous file is
    copied to `<name>.bak` first.
    """
    answers = _parse_params(list(set_ or []), flag="--set")
    outcome = _perform("env_apply", project=name, yes=yes, force=force,
                       accept=list(accept or []), answers=answers, out=out or "", pr=pr)
    data = dict(outcome.data)

    if data.get("content") and not data.get("wrote"):
        typer.echo(f"— {data.get('destination')} would read:\n")
        typer.echo(data["content"])
    for row in data.get("written") or []:
        if data.get("wrote"):
            typer.echo(f"  ✓ {row.get('name')}  ({row.get('confidence')})")
    for row in data.get("skipped") or []:
        if row.get("empty"):
            # READ, AND NOTHING THERE. There is no flag to offer: `--accept` only reaches an
            # `inferred` field and would silently do nothing here, and `--set` would be inviting a
            # human to invent a value the repository already answered. The line says what happened
            # and stops, which is the honest end of that sentence.
            typer.echo(f"  · left out: {row.get('name')} ({row.get('confidence')}) — read, and "
                       f"empty. Writing it would only repeat the default and make the file look "
                       f"filled in; `--set {row.get('name')}=…` if that reading is wrong.")
            continue
        # AN UNKNOWN FIELD HAS NO VALUE TO ACCEPT, so its flag is `--set … =` and not `--accept`.
        # Printing the wrong one would be a remedy that runs and does nothing, which is worse than
        # one that does not run.
        flag = (f"--set {row.get('name')}=<the answer>" if row.get("confidence") == "unknown"
                else f"--accept {row.get('name')}")
        typer.echo(f"  · left out: {row.get('name')} ({row.get('confidence')}) — include it with "
                   f"{flag}")

    typer.echo("")
    typer.echo(("" if outcome.ok else f"{outcome.code}: ") + outcome.message)
    if outcome.ok:
        return
    # EXIT 2 FOR "YOU HAVE TO SAY YES", 1 FOR EVERYTHING ELSE. A missing confirmation is a usage
    # answer and the operator's next move is to retype the command; a refusal is a state answer and
    # their next move is somewhere else entirely. Collapsing them into one code makes a script
    # unable to tell "not confirmed" from "would have destroyed their file".
    raise typer.Exit(2 if data.get("confirm") else 1)


product_app = typer.Typer(help="The product role's own repository: requirements and context.")
app.add_typer(product_app, name="product")


@product_app.command("status")
def product_status_cmd(name: str = typer.Argument(..., help="A registered project")) -> None:
    """Whether the product role can see its corpus at all — the first thing to ask.

    Its failure is silent everywhere else: the documentation repository is private, so a missing
    credential makes every other verb answer "I can't see the requirements" while every test in
    this repository passes, because the tests hand it a checkout directly."""
    outcome = _perform("product_status", project=name)
    typer.echo(outcome.message)
    if not outcome.ok:
        raise typer.Exit(1)
    typer.echo(f"  measured on  {outcome.data.get('measured_on')}")
    if not outcome.data.get("available"):
        raise typer.Exit(1)


@product_app.command("ask")
def product_ask_cmd(
    name: str = typer.Argument(..., help="A registered project"),
    question: str = typer.Argument(..., help="What you want to ask the product role"),
    propose: bool = typer.Option(False, "--propose", help="Record the draft it produces as a "
                                                          "pull request — the sign-off surface"),
    yes: bool = typer.Option(False, "--yes", help="Required by --propose"),
) -> None:
    """Talk to the product role WITHOUT SLACK — proposing a requirement, or just asking.

    Two calls rather than one, and that is the point: `product_ask` returns the draft, `--propose`
    hands THAT DRAFT BACK to be committed. `ProductModule.propose` takes the answer `draft`
    produced rather than re-deriving one — *"so what a human saw in the conversation is exactly
    what gets committed"* — and a second draft from the same words is a different text. Re-drafting
    inside one command would break that promise in the one artefact a client signs off.
    """
    outcome = _perform("product_ask", project=name, question=question)
    typer.echo(outcome.message)
    if not outcome.ok:
        raise typer.Exit(1)
    data = dict(outcome.data)
    for line in data.get("decisions") or []:
        typer.echo(f"  ? it needs a human decision: {line}")
    if not propose:
        if data.get("proposes_a_requirement"):
            typer.echo("")
            typer.echo("  record it as a pull request:  add --propose --yes")
        return

    written = _perform("product_propose", project=name, answer=data.get("answer"),
                       question=question, yes=yes)
    typer.echo("")
    typer.echo(written.message if written.ok else f"{written.code}: {written.message}")
    if not written.ok:
        raise typer.Exit(1)
    typer.echo(f"  accept it (the factory then argues FROM it):  openfactory product accept {name} "
               f"{written.data.get('number') or '<n>'} --yes")


@product_app.command("accept")
def product_accept_cmd(
    name: str = typer.Argument(..., help="A registered project"),
    number: str = typer.Argument(..., help="A requirement — `7`, `#7` or `REQ-0007`"),
    yes: bool = typer.Option(False, "--yes", help="Required. After this the factory argues FROM "
                                                  "the requirement and refuses work against it."),
) -> None:
    """Turn a written requirement into a PROMISE the factory defends (ADR-0032)."""
    outcome = _perform("product_accept", project=name, number=number, yes=yes)
    typer.echo(outcome.message if outcome.ok else f"{outcome.code}: {outcome.message}")
    if not outcome.ok:
        raise typer.Exit(1)


@product_app.command("drop")
def product_drop_cmd(
    name: str = typer.Argument(..., help="A registered project"),
    number: str = typer.Argument(..., help="A requirement — `7`, `#7` or `REQ-0007`"),
    reason: str = typer.Option("", "--reason", help="Recorded beside it, for whoever reads later"),
    yes: bool = typer.Option(False, "--yes", help="Required"),
) -> None:
    """Drop a proposed requirement, with the reason recorded beside it."""
    outcome = _perform("product_drop", project=name, number=number, reason=reason, yes=yes)
    typer.echo(outcome.message if outcome.ok else f"{outcome.code}: {outcome.message}")
    if not outcome.ok:
        raise typer.Exit(1)


@product_app.command("requirements")
def product_requirements_cmd(
    name: str = typer.Argument(..., help="A registered project"),
) -> None:
    """Every requirement in the corpus — number, title and status.

    The read `accept` and `drop` always assumed: both take a NUMBER, and before this the only
    instruction any surface could give was "type one you got from somewhere else"."""
    outcome = _perform("product_requirements", project=name)
    typer.echo(outcome.message if outcome.ok else f"{outcome.code}: {outcome.message}")
    for row in (outcome.data.get("requirements") or []):
        typer.echo(f"  {row.get('number'):>4}  {row.get('status',''):<10} {row.get('title','')}")
    if not outcome.ok:
        raise typer.Exit(1)


@product_app.command("pending")
def product_pending_cmd(
    name: str = typer.Argument(..., help="A registered project"),
) -> None:
    """What the product role has staged and is waiting on a person for.

    THE QUESTION A TERMINAL IS THE RIGHT PLACE TO ASK. Until this row existed the only surface
    that could see a waiting proposal was the panel's inbox, so a client working from a shell had
    one staged in their name, addressed to them, and no way to discover it."""
    outcome = _perform("product_pending", project=name)
    typer.echo(outcome.message if outcome.ok else f"{outcome.code}: {outcome.message}")
    for row in (outcome.data.get("pending") or []):
        number = row.get("number")
        typer.echo(f"  {row.get('kind',''):<10} {('#' + str(number)) if number else '':<7} "
                   f"{row.get('text','')}")
        # THE TOKEN IS WHAT AN ANSWER MUST CARRY, so it is printed rather than left to be guessed:
        # it identifies the proposal that was SHOWN, and a reply naming a position in this list
        # would land on its replacement.
        typer.echo(f"             {row.get('token','')}")
    if not outcome.ok:
        raise typer.Exit(1)


@product_app.command("parked")
def product_parked_cmd(
    name: str = typer.Argument(..., help="A registered project"),
    limit: int = typer.Option(10, "--limit", help="How many parked tickets to classify"),
) -> None:
    """What is parked, and whose problem each one is. Writes nothing.

    A TERMINAL VERB AND NOT A BUTTON, deliberately: this spends one model call per parked ticket,
    so it runs for minutes and an HTTP request does not live that long. The panel would show a
    timeout while the worker kept spending and threw the answer away."""
    outcome = _perform("product_needs_action", project=name, limit=str(limit))
    typer.echo(outcome.message if outcome.ok else f"{outcome.code}: {outcome.message}")
    if not outcome.ok:
        raise typer.Exit(1)


@product_app.command("baseline")
def product_baseline_cmd(
    name: str = typer.Argument(..., help="A registered project"),
    yes: bool = typer.Option(False, "--yes", help="Confirm: this spends real money and writes"),
) -> None:
    """The first pass over a legacy codebase — read it all, write up what it OBSERVES, open a
    pull request on the documentation repo for a person to confirm.

    It reads an entire repository through an agent, so it runs for tens of minutes. `--yes` is
    required and the row asks again: nothing here should start by accident."""
    outcome = _perform("product_baseline", project=name, yes=yes)
    typer.echo(outcome.message if outcome.ok else f"{outcome.code}: {outcome.message}")
    if outcome.ok and outcome.data.get("url"):
        typer.echo(f"  {outcome.data['url']}")
    if not outcome.ok:
        raise typer.Exit(1)


@product_app.command("queue")
def product_queue_cmd(
    name: str = typer.Argument(..., help="A registered project"),
    limit: int = typer.Option(5, "--limit", help="How many to propose"),
) -> None:
    """What should start next, in order — and why not the others. Writes nothing."""
    outcome = _perform("product_queue", project=name, limit=limit)
    typer.echo(outcome.message if outcome.ok else f"{outcome.code}: {outcome.message}")
    if not outcome.ok:
        raise typer.Exit(1)


@product_app.command("promote")
def product_promote_cmd(
    name: str = typer.Argument(..., help="A registered project"),
    numbers: list[str] = typer.Argument(  # noqa: B008 — typer's own idiom, as `product init` uses
        ..., help="Ticket numbers, in the order to start them"),
    yes: bool = typer.Option(False, "--yes", help="Required. This is the one act here that "
                                                 "spends money."),
) -> None:
    """Move approved tickets into the queue — the ONE act here that spends money.

    Order is preserved because the poller pulls in board order: a sequence that arrives shuffled
    is not the sequence anybody approved."""
    outcome = _perform("product_promote", project=name, numbers=list(numbers), yes=yes)
    typer.echo(outcome.message if outcome.ok else f"{outcome.code}: {outcome.message}")
    if not outcome.ok:
        raise typer.Exit(1)


@product_app.command("release")
def product_release_cmd(
    name: str = typer.Argument(..., help="A registered project"),
    issue: str = typer.Argument(..., help="The delivery the client approved"),
    yes: bool = typer.Option(False, "--yes", help="Required. This puts software in front of the "
                                                  "client's own users."),
) -> None:
    """The client's approval putting a delivery in front of their own users."""
    outcome = _perform("product_release", project=name, issue=issue, yes=yes)
    typer.echo(outcome.message if outcome.ok else f"{outcome.code}: {outcome.message}")
    if not outcome.ok:
        raise typer.Exit(1)


def _create_context_repo(project, name: str) -> tuple[str, bool]:
    """The CLI's rendering of `product.onboard.create_context_repository` — same act, exit
    codes here, the mechanism there (extracted 2026-08-13 so `onboard` can drive it)."""
    from openfactory.product.onboard import create_context_repository

    try:
        return create_context_repository(project, name)
    except ValueError as exc:
        typer.echo(f"✗ {exc}")
        raise typer.Exit(1) from None
    except RuntimeError as exc:
        typer.echo(f"✗ could not create the context repository: {exc}")
        raise typer.Exit(1) from exc


def _context_forge(project):
    """DELEGATES to `product.onboard.context_forge` — one credential resolution for the
    context axis, not two drifting ones: this local copy lacked both the App-token fallback
    and the personal-account PAT borrow its sibling earned (pilot, 2026-08-13)."""
    from openfactory.product.onboard import context_forge

    return context_forge(project)


def _context_clone_url(project, docs_repo: str) -> str:
    """The context repository's clone URL — the right host AND the right credential.

    This was a `github.com` literal in two places. On an Azure DevOps deployment it produced a
    URL for a host the client does not use — a 404, or worse somebody else's repository of that
    name — which is the exact defect `clone_url` was added to the port to end.

    THE CREDENTIAL WAS THE OTHER HALF, and fixing only the host would have shipped the worse
    bug: the callers resolved `forge_token() or github_app_token_from_env()`, which is ALWAYS a
    GitHub credential, so an all-Azure deployment with a perfectly good PAT would have sent its
    GitHub App token to dev.azure.com. `clone_url_for` is the one place where the adapter's own
    credential wins over the caller's (`registry.py` records this exact defect being
    reintroduced by a convenience wrapper); `forge_token_for` is the per-project resolution the
    API call two lines up already used. Found by the pre-commit adversarial review, 2026-08-12.
    """
    from openfactory.product.onboard import context_clone_url

    return context_clone_url(project, docs_repo)


@product_app.command("declare")
def product_declare(name: str, docs_repo: str) -> None:
    """Declare this product's EXISTING context repository — the client already has one.

    The other half of `product init --create-context` — an enterprise organisation has both
    shapes at once, some projects with a documentation repository and some without. Until this
    verb existed, the only way to name a
    pre-existing repository was hand-editing the live registry inside the worker container —
    the exact "file edit by hand" this platform sells the absence of (pilot, 2026-08-13).

    GitHub: `owner/repo`. Azure DevOps: `repo`, or `Project/repo` when it lives in another
    project of the same organisation — every later step follows the qualifier.

    IT IS READ BACK, not just written down. "Declared" and "reachable" are different facts, and
    the distance between them is silent: a typo'd name, a qualifier pointing at another Azure
    project, or a repository outside a GitHub App installation's selection all record perfectly
    and then surface hours later as the product role answering "I cannot see the requirements".
    So both credentials that will ever read it are tried here, while somebody is watching."""
    from openfactory.product.onboard import context_reachability
    from openfactory.registry import ProjectRegistry

    _get_project(name)  # a clear "not registered" beats a registry write to a ghost
    repo = (docs_repo or "").strip().strip("/")
    if not repo:
        typer.echo("✗ name the repository: `openfactory product declare <project> <owner/repo>`")
        raise typer.Exit(2)
    ProjectRegistry().set_docs_repo(name, repo)
    typer.echo(f"✓ {name}'s context repository is {repo} — recorded")

    project = _get_project(name)  # RE-READ: the object above predates the record
    ok, why = context_reachability(project, repo)
    if ok:
        typer.echo("  ✓ reachable — `openfactory onboard " + name + "` proposes the declaration "
                   "and the backfill INTO it as a pull request")
        return
    typer.echo(f"  ⚠ RECORDED, BUT NOT READABLE: {why}")
    typer.echo("    The declaration stands — fix the access and nothing needs re-declaring. "
               "Usually the name or its qualifier is wrong, or the credential has no access "
               "to that repository.")
    # THE VENDOR'S OWN LIKELY CAUSE, and only to the operator who runs that vendor: telling an
    # Azure DevOps operator about GitHub App installation selections is noise that costs trust
    # (the operator, 2026-08-14: any change must serve the product, not one deployment).
    kinds = {axis.kind for axis in (project.forge, project.tracker) if axis is not None}
    if "github" in kinds:
        typer.echo("    On GitHub specifically: an App installed on 'Only select repositories' "
                   "cannot see one that is not in the selection (docs/setup/github.md §3).")
    if "azure_devops" in kinds:
        typer.echo("    On Azure DevOps specifically: a repository in ANOTHER project of the "
                   "organisation must be qualified `Project/repo`, and the PAT must cover that "
                   "project (docs/setup/azure-devops.md).")
    raise typer.Exit(1)


@product_app.command("init")
def product_init(
    name: str,
    source: list[str] = typer.Option(None, "--source",  # noqa: B008 — typer's own idiom
                                     help="Another repository implementing this product "
                                          "(repeatable). The registry names one; a product that "
                                          "spans several must say so."),
    write: bool = typer.Option(False, "--write",
                               help="Open a PR on the context repo instead of only showing it"),
    create_context: bool = typer.Option(
        False, "--create-context",
        help="When this project has no context repository, CREATE one in the client's "
             "organisation. Consequential and consented: it makes a new repository under their "
             "name. Without it, a project with none is refused and told what to do."),
) -> None:
    """Onboard a product's CONTEXT REPOSITORY — the one that already exists, or a new one.

    The factory requires a context repo of every project, and a client may well arrive with one —
    written before they met us, with their own structure. The module's gate was already right
    (it stays off, in a sentence, until the product manifest says who the product is and which
    repositories implement it); what was missing was any step that gets them there. Four files
    across three repositories, by hand, is where *no developer needed* leaks.

    SHOWS BEFORE IT WRITES. The default prints the file it would add and what each source repo
    still needs; `--write` opens a PR. It is the client's repository — the first thing this
    platform does to it should be reviewable."""
    import subprocess
    import tempfile
    from pathlib import Path as _Path

    from openfactory.credentials import bot_identity
    from openfactory.product.onboard import PRODUCT_YAML, plan

    project = _get_project(name)
    docs_repo = (getattr(getattr(project, "product", None), "docs_repo", "") or "").strip()
    # THE REGISTRY NAMES ONE REPOSITORY; A PRODUCT MAY SPAN SEVERAL. C-18 lets a card carry its
    # own repo, so the platform learns them one ticket at a time — but the product role needs the
    # COMPLETE set up front, and a member missing from `sources:` is invisible to it. Inferring
    # from the registry alone would quietly declare a multi-repo product as a single-repo one.
    sources = sorted({s for s in [
        (project.forge.repo if project.forge else None) or "",
        project.tracker.repo or "",
        *(source or []),
    ] if s and "/" in s})

    with tempfile.TemporaryDirectory() as tmp:
        root = _Path(tmp) / "docs"
        if docs_repo:
            url = _context_clone_url(project, docs_repo)
            rc = subprocess.run(["git", "clone", "--depth", "1", url, str(root)],
                                capture_output=True, text=True, timeout=180)
            if rc.returncode != 0:
                typer.echo(f"✗ could not clone {docs_repo}: {rc.stderr[-200:]}")
                raise typer.Exit(1)
        else:
            # NO CONTEXT REPOSITORY. Until now this planned against an empty temporary directory
            # with no git remote, so `--write` reached a `git push origin` that could not resolve
            # one — a confusing failure about a remote, for a project whose real problem is that
            # it has nowhere to keep requirements at all (#99 slice 2b).
            #
            # The product owner, 2026-08-07: *"sempre na org do cliente. Se o cliente não tiver um
            # repositório de contexto temos que criar um."*
            if not create_context:
                typer.echo(
                    f"✗ {name} has no context repository, and this is where its requirements "
                    f"would live.\n"
                    f"  Run again with --create-context to create one in the client's "
                    f"organisation, or declare the one they already have: "
                    f"`openfactory product declare {name} <owner/repo>`.")
                raise typer.Exit(1)
            docs_repo, made = _create_context_repo(project, name)
            typer.echo(f"{'✓ created' if made else '· found'} {docs_repo}")
            url = _context_clone_url(project, docs_repo)
            rc = subprocess.run(["git", "clone", url, str(root)],
                                capture_output=True, text=True, timeout=180)
            if rc.returncode != 0:
                typer.echo(f"✗ could not clone {docs_repo}: {rc.stderr[-200:]}")
                raise typer.Exit(1)
            # A REPOSITORY BORN EMPTY HAS NO BRANCH. `gh repo create` makes no commit, so the
            # clone lands on an unborn HEAD and the first `git checkout -b` would work while the
            # push had no upstream to be forced over. One empty commit gives it a base branch,
            # which is what every later step assumes exists.
            for args in (["-C", str(root), "checkout", "-B", "main"],):
                subprocess.run(["git", *args], capture_output=True, text=True, timeout=60)
            # RE-READ WHAT WAS JUST RECORDED. `set_docs_repo` wrote the registry; the `project`
            # in hand predates it, so `plan()` refused "no product: section" ON THE RUN THAT
            # CREATED THE REPOSITORY — created, recorded, exit 1, no todos, no PR. Reproduced by
            # the onboarding-v2 verification pass (2026-08-10); the suite never caught it because
            # every test's clone failed before plan() was reached.
            project = _get_project(name)

        result = plan(project, root, sources=sources)
        if result.refusal:
            typer.echo(f"✗ {result.refusal}")
            raise typer.Exit(1)
        if result.already_correct:
            typer.echo(f"· {result.docs_repo} already declares this product — nothing to write")
        else:
            typer.echo(f"— {PRODUCT_YAML} in {result.docs_repo} "
                       f"(requirements go in `{result.requirements_dir}/`):\n")
            typer.echo(result.product_yaml)
        for line in result.todo:
            typer.echo(f"· {line}")

        if not write or result.already_correct:
            if not write:
                typer.echo("\nRun again with --write to open a PR on the context repository.")
            return

        # THE BASE, READ FROM THE CLONE WHILE WE ARE STILL ON IT. `gh pr create` inferred the
        # repository's default branch; the port asks for it, and asking git here is more honest
        # than assuming `main` — a client whose context repository is on `master` or `develop`
        # would otherwise get a pull request against a branch that does not exist.
        head = subprocess.run(["git", "-C", str(root), "rev-parse", "--abbrev-ref", "HEAD"],
                              capture_output=True, text=True, timeout=60, check=False)
        # THE RETURN CODE DECIDES, NOT THE OUTPUT. On a repository this command just created
        # there is no commit yet, so HEAD is unborn: git exits 128 and prints the literal string
        # `HEAD` on stdout. Read blindly that becomes the pull request's base — a branch that
        # cannot exist — and the review request is refused after the branch is already pushed.
        # (Found by the pre-commit adversarial review, 2026-08-12; `checkout -B main` above is
        # what makes `main` the right answer in exactly that case.)
        named = (head.stdout or "").strip()
        base_branch = named if (head.returncode == 0 and named and named != "HEAD") else "main"

        target = root / PRODUCT_YAML
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(result.product_yaml, encoding="utf-8")
        from openfactory.product.onboard import proposal_branch
        branch = proposal_branch(project.name)
        bot = bot_identity()
        ident = ["-c", f"user.name={bot.name}", "-c", f"user.email={bot.email}"]
        for args in (["checkout", "-b", branch], ["add", "--", PRODUCT_YAML],
                     ["commit", "-m",
                      f"{project.name}: declare this product for OpenFactory"],
                     # --force: this is the bot's OWN dedicated onboarding branch, and a retry
                     # after a partial failure (pushed, then `gh pr create` had no token) must
                     # overwrite rather than dead-lock on a non-fast-forward. Same rule, and the
                     # same reason, as `publish_branch`.
                     ["push", "--force", "-u", "origin", branch]):
            done = subprocess.run(["git", "-C", str(root), *ident, *args],
                                  capture_output=True, text=True, timeout=180)
            if done.returncode != 0:
                typer.echo(f"✗ git {args[0]} failed: {(done.stderr or '')[-200:]}")
                raise typer.Exit(1)
        # THROUGH THE PORT, NOT THROUGH `gh` (#95's lesson, one command later). This shelled
        # out to `gh pr create`, so on Azure DevOps — where the whole point is that no GitHub
        # exists anywhere — the branch pushed and the review request was simply refused, with
        # the operator holding a pushed branch nobody would look at. `open_pr` is on the forge
        # contract and both vendors implement it; the product module made exactly this move for
        # requirement proposals and this command never followed.
        from openfactory.onboarding.propose_manifest import open_review_request

        url = open_review_request(
            _context_forge(project), repo=result.docs_repo, head=branch, base=base_branch,
            title=f"{project.name}: declare this product for OpenFactory",
            body=f"Adds `{PRODUCT_YAML}` so the platform can find this product's requirements. "
                 f"Nothing else in this repository is touched.")
        if url:
            typer.echo(f"✓ review request open — {url}")
        else:
            typer.echo(f"✗ the branch `{branch}` is pushed and the review request did not open — "
                       f"open it by hand against `{base_branch}` on {result.docs_repo}")
            raise typer.Exit(1)


if __name__ == "__main__":
    app()
