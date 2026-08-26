"""`openfactory init` — generate this deployment's environment instead of asking for it (#116).

THE DEFECT THIS CLOSES, raised by the pilot operator unprompted while filling `.env.compose` in:
*"não deveria ser o CLI da openfactory a gerar este .env.compose com base em definições da stack?
[…] é normal estas fases de config nos CLI, como AWS por exemplo."*

He was right, and the strongest argument is not the industry's (`aws configure`, `gh auth login`,
`terraform init`) — it is this platform's own. `env read` reads a repository and PROPOSES its
manifest; `project init` converges the registry, the board and the scaffold. The deployment's own
environment was the last thing still hand-written, and it is the FIRST file an adopter opens.

THE ORDER WAS BACKWARDS, which is what made it feel generic: an adopter was asked to fill in
credentials BEFORE declaring which vendors they use, so they filled blanks for systems they will
never touch and left blanks whose consequence they could not evaluate. The cure is not a longer
comment — it is a file that contains only the variables this deployment's answers actually use.

WHAT THIS MODULE IS AND IS NOT. It is pure: answers in, file text out, plus two lists (what was
obtained without asking, and what a human must still do). Every credential it cannot generate is
NAMED with the exact page or command that produces it — never left as an empty line the reader
has to interpret. The I/O — prompting, reading `gh`, writing the file at 0600 — belongs to the
CLI, so every branch here is reachable in a test with no TTY, no network and no `gh`. (The one
read it does make is of the installed entry points, below, and that read never raises.)

WHAT IT DELIBERATELY DOES NOT ASK. Anything the registry already knows or `env read` discovers on
its own: repositories, board coordinates, the client's stack, the box image. This step is about
the DEPLOYMENT — the secrets and the ports — and a question whose answer already lives somewhere
is a question that will disagree with that somewhere.

THE VOCABULARY IS THE REGISTRIES', READ WHEN THE COMMAND RUNS. Four literal tuples used to sit
here — `FORGES = ("github", "azure_devops")` and its three siblings — a hand copy of the axes'
tables that was equal to them by luck and refused every add-on by construction: a stranger who
had installed `forge.gitea` and could build it through the registry was told by the FIRST command
an adopter runs that `'gitea' is not one of github, azure_devops` (measured 2026-08-26, with a
real dist-info on the path). The choices are now `plugins.known(axis, TABLE)`, resolved when a
question is read rather than at import, so a broken add-on cannot break `openfactory --help`.

AN ADD-ON KIND IS NEVER RENDERED SILENTLY. Widening the vocabulary alone would have produced a
worse file than the refusal: `render(Answers(forge="gitea"))` wrote a file with no forge row at
all and a to-do list with no line for its credential — a file that looks configured and
authenticates nothing, the exact class `HARNESS_ENV_CREDENTIAL` refuses below. So a kind this
generator carries no rows for gets a commented section naming it and a `remaining` line saying
the add-on owns its credential and its package documents the variables.
"""

from __future__ import annotations

import secrets
from collections.abc import Callable
from dataclasses import dataclass, field

from openfactory import plugins

#: The fixed vocabularies — questions whose answers are this platform's, not a provider's.
GITHUB_AUTH = ("token", "app")
GITHUB_ACCOUNTS = ("org", "personal")
CLAUDE_AUTH = ("subscription", "api_key")


def _table(axis: str) -> dict[str, object]:
    """The registry's OWN table for `axis` — the shipped rows, imported when asked so a broken
    add-on or a heavy adapter module never sits on `openfactory --help`."""
    from openfactory.adapters.agent.registry import HARNESSES
    from openfactory.adapters.channel.registry import CHANNELS
    from openfactory.adapters.forge.registry import FORGES
    from openfactory.adapters.tracker.registry import TRACKERS

    return {"forge": FORGES, "tracker": TRACKERS, "harness": HARNESSES,
            "channel": CHANNELS}[axis]


def _forges() -> tuple[str, ...]:
    return tuple(plugins.known("forge", _table("forge")))


def _trackers() -> tuple[str, ...]:
    return tuple(plugins.known("tracker", _table("tracker")))


def _harnesses() -> tuple[str, ...]:
    return tuple(plugins.known("harness", _table("harness")))


def _channels() -> tuple[str, ...]:
    return tuple(plugins.known("channel", _table("channel")))


#: axis → the kinds this deployment can build, shipped plus installed, read when asked.
CHOICES: dict[str, Callable[[], tuple[str, ...]]] = {
    "forge": _forges,
    "tracker": _trackers,
    "harness": _harnesses,
    "channel": _channels,
}


def choices(axis: str) -> tuple[str, ...]:
    """Every kind `axis` can name in an answer — the registry's table plus the installed add-ons,
    sorted. The one vocabulary the prompt, the refusal and `validate()` all read."""
    return CHOICES[axis]()


def shipped(axis: str) -> tuple[str, ...]:
    """The kinds this generator carries a credential block for: the registry's OWN rows for
    `axis`, read when asked. Anything else the registry knows arrived through an entry point and
    is an ADD-ON to this file — rendered as a named section with no rows, plus a to-do line
    that says whose variables go there.

    NOT A LIST KEPT HERE. A literal copy of the four tables sat in this slot, equal to them by
    luck and read by no test (measured 2026-08-26): a row added to a registry without a name in
    the copy would have rendered as "an add-on this generator carries no rows for" — a false
    sentence in the operator's own `.env`. The tables are the truth; what this module still owes
    is a BLOCK for every row in them, and the guard holds that each shipped kind names itself in
    the file rendered for it — a shipped row this module forgot would otherwise render nothing,
    and nothing looks configured."""
    return tuple(_table(axis))

#: Harnesses whose credential is a variable this file can carry. The others authenticate through
#: their own CLI's login state inside the box (`codex login`, `kimi login`, and OpenCode's
#: provider registration) — MEASURED, not assumed: `_AUTH_ENV_VARS` in the container sandbox is
#: exactly `("CLAUDE_CODE_OAUTH_TOKEN", "ANTHROPIC_API_KEY")`. Inventing a variable for the other
#: three would produce a file that looks configured and authenticates nothing.
HARNESS_ENV_CREDENTIAL = ("claude_code",)


@dataclass(frozen=True)
class Question:
    """One question, in the READER's words, with what their answer changes.

    THE PROMPTS INHERITED THE DEFECT THE FILE JUST LOST. `.env.compose` used "forge" and
    "tracker" as though they were English and never said what a row was for; the fix was to
    define them at the point of use. Then the prompts asked `channel (panel/slack)` — the same
    mistake, one layer up — and the pilot operator asked the same question again: *"não entendi
    essa pergunta e o que ela influenciaria"*.

    So a question is a STRUCTURE, not a string: `ask` is plain language, `effect` says what
    changes, and a guard holds both — `ask` may not contain this platform's own vocabulary,
    because those are precisely the words the person answering does not have yet.

    `options` is READ, not stored: a question about a provider axis answers with the registry's
    vocabulary at the moment it is asked, so an add-on installed after this module was imported
    is offered too. The fixed vocabularies are closed over the same way, for one shape.
    """

    flag: str          # what the scripted form is called: --forge, --channel…
    ask: str           # the question, in words somebody who has never seen this product has
    effect: str        # what their answer changes about the file this writes
    choose: Callable[[], tuple[str, ...]]
    default: str

    @property
    def options(self) -> tuple[str, ...]:
        return self.choose()


def _fixed(values: tuple[str, ...]) -> Callable[[], tuple[str, ...]]:
    return lambda: values


#: Asked in this order. Each one is skipped when its answer cannot matter (the GitHub question
#: for a deployment with no GitHub, the Claude question for another harness) — a question whose
#: answer is discarded teaches the reader that the answers do not matter.
QUESTIONS: tuple[Question, ...] = (
    Question("forge", "Where does your CODE live — the branches and the pull requests?",
             "decides which credential this file asks you for", _forges, "github"),
    Question("tracker", "Where do your TICKETS live — the issues and the board?",
             "the two can differ: tickets in Jira with code on GitHub is ordinary",
             _trackers, "github"),
    Question("github-auth", "How should the factory sign in to GitHub?",
             "`token` is fastest and every commit reads as YOU; `app` gives the factory its own "
             "identity and audit trail — what a team should use", _fixed(GITHUB_AUTH), "token"),
    Question("github-account", "Is that GitHub account an organisation or a personal account?",
             "`personal` adds one extra line to fill in: a personal account's project board "
             "cannot be driven with the App's own sign-in, so the board needs a classic token "
             "beside it; `org` needs nothing extra", _fixed(GITHUB_ACCOUNTS), "org"),
    Question("harness", "Which coding agent should write the code?",
             "the platform orchestrates it; you pay for it", _harnesses, "claude_code"),
    Question("claude-auth", "How do you pay for Claude?",
             "`subscription` uses a token from `claude setup-token`; `api_key` bills per token",
             _fixed(CLAUDE_AUTH), "subscription"),
    Question("channel", "Where should the factory talk to your team?",
             "`panel` = the web panel only (it still comments on every ticket); any other kind = "
             "ALSO a chat channel an installed add-on package provides, which adds that package's "
             "variables to fill in", _channels, "panel"),
    Question("panel-exposed", "Will anyone open the panel from another machine?",
             "`yes` generates a password for the panel; `no` leaves it OPEN to anyone who can "
             "reach the port — fine on a laptop, wrong for anything else",
             _fixed(("yes", "no")), "no"),
)


class UnknownAnswer(ValueError):
    """An answer outside the vocabulary — refused by name, with the alternatives listed."""


@dataclass
class Answers:
    """The four decisions that cannot be inferred, plus how each one is authenticated."""

    forge: str = "github"
    tracker: str = "github"
    harness: str = "claude_code"
    github_auth: str = "token"        # only read when github is on one of the two axes
    github_account: str = "org"       # only read on the App path — `personal` boards need a PAT
    claude_auth: str = "subscription"  # only read when the harness is claude_code
    channel: str = "panel"
    panel_exposed: bool = False

    def validate(self) -> None:
        for value, allowed, what in (
            (self.forge, choices("forge"), "forge"),
            (self.tracker, choices("tracker"), "tracker"),
            (self.harness, choices("harness"), "harness"),
            (self.github_auth, GITHUB_AUTH, "github-auth"),
            (self.github_account, GITHUB_ACCOUNTS, "github-account"),
            (self.claude_auth, CLAUDE_AUTH, "claude-auth"),
            (self.channel, choices("channel"), "channel"),
        ):
            if value not in allowed:
                raise UnknownAnswer(
                    f"{what}: {value!r} is not one of {', '.join(allowed)}")

    @property
    def uses_github(self) -> bool:
        return "github" in (self.forge, self.tracker)

    @property
    def uses_azure(self) -> bool:
        return "azure_devops" in (self.forge, self.tracker)

    @property
    def uses_jira(self) -> bool:
        return self.tracker == "jira"

    def add_ons(self) -> list[tuple[str, str]]:
        """`(axis, kind)` for every answer this generator carries no block for — the kinds a
        registry knows only because a package outside this repository declared them."""
        chosen = (("forge", self.forge), ("tracker", self.tracker),
                  ("harness", self.harness), ("channel", self.channel))
        return [(axis, kind) for axis, kind in chosen if kind not in shipped(axis)]


@dataclass
class Probes:
    """What the generator can obtain WITHOUT asking a human. Injected, so a test needs no `gh`.

    `forge_token` returns a token or None — never raises: an unavailable helper is an ordinary
    state (no `gh`, not logged in, a different vendor), and the file is still generated with the
    line left empty and the recipe beside it."""

    forge_token: Callable[[], str | None] = lambda: None
    secret: Callable[[], str] = lambda: secrets.token_hex(32)


@dataclass
class Rendered:
    text: str
    #: NAMES of the variables filled without asking. Never values — a generator that echoes a
    #: secret to a terminal has put it in a scrollback buffer, a screen recording and a CI log.
    obtained: list[str] = field(default_factory=list)
    #: What a human must still do, in the order they should do it, each with its page or command.
    remaining: list[str] = field(default_factory=list)


_HEADER = """\
# OpenFactory — this deployment's environment, generated by `openfactory init`.
#
# ONLY the variables THIS deployment's answers use are here. That is the point: a file with rows
# for vendors you do not run is a file you cannot tell apart from one you filled in wrong.
# Re-run `openfactory init` to change an answer; `--force` to overwrite what is already here.
#
# What is NOT here, and where it lives instead:
#   your code's stack ..... `.openfactory/project.yaml` in YOUR repository (`openfactory env read`)
#   the box that runs it .. the registry, per project (`box.image`)
#   which vendors ......... the registry, per project (`tracker/forge: {kind: …}`)
#   secrets ............... this file, because one deployment serves many projects
"""


def _github_block(a: Answers, p: Probes, out: Rendered) -> str:
    if a.github_auth == "app":
        out.remaining.append(
            "create the GitHub App and INSTALL it (two separate pages — finishing the first "
            "looks like finishing): the whole walkthrough, permission table included, is "
            "docs/setup/github.md. Then fill OPENFACTORY_GH_APP_ID (the App's General page), "
            "OPENFACTORY_GH_APP_INSTALLATION_ID (the NUMBER AT THE END OF THE URL after "
            "Settings → GitHub Apps → Configure — it appears nowhere on the page itself) and "
            "OPENFACTORY_GH_APP_KEY_CONTENT (the whole PEM in DOUBLE QUOTES, not a path — "
            "unquoted, its line breaks corrupt the parse of this entire file)")
        if a.github_account == "personal":
            # The trap the first pilot funnel hit (2026-08-10): the App path on a personal
            # account emitted only the trio, the board needs a classic PAT beside it, and that
            # fact lived in prose nobody re-reads. Now the ANSWER writes the row.
            out.remaining.append(
                "fill OPENFACTORY_TRACKER_TOKEN — a personal account's project board cannot be "
                "driven with the App's sign-in, so the board uses this instead: "
                "github.com/settings/tokens → classic token, scopes `repo` and `project`, "
                "NEVER `workflow` (docs/setup/github.md §6)")
            return """
# ── GitHub, as an App: its own identity, its own audit trail, a token that expires ──
# The walkthrough (both creation pages, the permission table, the traps): docs/setup/github.md
#   APP ID ............. the "About" block at the top of the App's General settings page
#   INSTALLATION ID .... the number at the END OF THE URL after Settings → GitHub Apps →
#                        Configure (…/settings/installations/<id>) — it is printed nowhere on
#                        the page itself
#   KEY CONTENT ........ the whole -----BEGIN…END----- block, wrapped in DOUBLE QUOTES. Unquoted,
#                        the line breaks corrupt the parse of this ENTIRE file — every other
#                        credential in it silently stops arriving.
# Leave OPENFACTORY_BOT_TOKEN out of this file: a filled PAT beats the App everywhere.
OPENFACTORY_GH_APP_ID=
OPENFACTORY_GH_APP_INSTALLATION_ID=
OPENFACTORY_GH_APP_KEY_CONTENT=""

# ── The board, because this is a PERSONAL account ──
# A user-owned project board cannot be driven with the App's sign-in (GitHub's limitation, not
# a permission you forgot) — the App keeps the code, this classic token carries the board:
# github.com/settings/tokens → classic, scopes `repo` + `project`, NEVER `workflow`.
OPENFACTORY_TRACKER_TOKEN=
"""
        return """
# ── GitHub, as an App: its own identity, its own audit trail, a token that expires ──
# The walkthrough (both creation pages, the permission table, the traps): docs/setup/github.md
#   APP ID ............. the "About" block at the top of the App's General settings page
#   INSTALLATION ID .... the number at the END OF THE URL after Settings → GitHub Apps →
#                        Configure (…/settings/installations/<id>) — it is printed nowhere on
#                        the page itself
#   KEY CONTENT ........ the whole -----BEGIN…END----- block, wrapped in DOUBLE QUOTES. Unquoted,
#                        the line breaks corrupt the parse of this ENTIRE file — every other
#                        credential in it silently stops arriving.
# Leave OPENFACTORY_BOT_TOKEN out of this file: a filled PAT beats the App everywhere.
OPENFACTORY_GH_APP_ID=
OPENFACTORY_GH_APP_INSTALLATION_ID=
OPENFACTORY_GH_APP_KEY_CONTENT=""
"""
    token = p.forge_token()
    if token:
        out.obtained.append("OPENFACTORY_BOT_TOKEN")
        out.remaining.append(
            "OPENFACTORY_BOT_TOKEN was taken from your `gh` login, so the factory will commit and "
            "open pull requests AS YOU. Fine for trying it out; before anybody depends on it, "
            "re-run with --github-auth app so the factory has an identity of its own")
        return f"""
# ── GitHub, as a personal access token ──
# Taken from your `gh` login: this is YOUR credential, so every commit and PR reads as you.
# For a real deployment use a GitHub App instead (`openfactory init --github-auth app`).
OPENFACTORY_BOT_TOKEN={token}
"""
    out.remaining.append(
        "fill OPENFACTORY_BOT_TOKEN — github.com/settings/tokens → classic token with scopes "
        "`repo` and `project` (plus `read:org` for an organisation board), and NEVER `workflow`: "
        "its absence is what keeps the factory out of your CI/CD definitions")
    return """
# ── GitHub, as a personal access token ──
# github.com/settings/tokens → classic token, scopes `repo` + `project` (+ `read:org` for an
# organisation board). NEVER `workflow` — its absence is the guardrail that keeps the factory out
# of your CI/CD definitions.
OPENFACTORY_BOT_TOKEN=
"""


def _harness_block(a: Answers, out: Rendered) -> str:
    """The harness section's text — and, first, its to-do line (the un-postponable one)."""
    if a.harness in HARNESS_ENV_CREDENTIAL:
        if a.claude_auth == "subscription":
            out.remaining.append(
                "fill CLAUDE_CODE_OAUTH_TOKEN — run `claude setup-token` on this machine and "
                "paste the result. THIS IS THE ONE CREDENTIAL YOU CANNOT POSTPONE: the stack "
                "boots without it and no ticket can run")
            return """
# ── The harness: Claude Code on a subscription ──
# Run `claude setup-token` on this machine and paste the result. The CLI has to authenticate
# INSIDE the box, with no human at a browser — which is why a token and not a login.
CLAUDE_CODE_OAUTH_TOKEN=
"""
        out.remaining.append(
            "fill ANTHROPIC_API_KEY — console.anthropic.com → API keys. THIS IS THE ONE "
            "CREDENTIAL YOU CANNOT POSTPONE: the stack boots without it and no ticket can run")
        return """
# ── The harness: Claude Code on an API key ──
# console.anthropic.com → API keys. Billed per token rather than by subscription.
ANTHROPIC_API_KEY=
"""
    if a.harness not in shipped("harness"):
        return _add_on_block("harness", a.harness, out)
    out.remaining.append(
        f"authenticate the {a.harness} CLI — it logs in through its own command rather "
        f"than an environment variable, and it must be authenticated INSIDE the box. "
        f"`openfactory box prove <project>` is what proves it actually is, before any ticket "
        f"spends money")
    return f"""
# ── The harness: {a.harness} ──
# No credential variable: this harness authenticates through its own CLI's login, inside the box.
# `openfactory box prove <project>` is what proves that it did — before a ticket spends anything.
"""


def _add_on_block(axis: str, kind: str, out: Rendered) -> str:
    """The section for a kind this generator carries no rows for, and its to-do line.

    NAMED, NEVER SILENT. The alternative — a file with no mention of the kind and a to-do list
    with no line for its credential — looks complete and authenticates nothing; that is the
    shape this whole module exists to refuse. The add-on owns its credential: its package says
    which variables belong here, and `openfactory doctor` says which are still missing."""
    out.remaining.append(
        f"add the variables the `{kind}` {axis} add-on documents — this generator carries no rows "
        f"for it, its package names the variables to put in this file, and `openfactory doctor` "
        f"reports which are still missing")
    return f"""
# ── {axis}: {kind} — an add-on this generator carries no rows for ──
# The package that provides `{kind}` documents which variables belong here; add them below.
# `openfactory doctor` reports which of them are still missing.
"""


def _channel_block(kind: str, out: Rendered) -> str:
    """The section for an add-on channel: the variables ITS row declares it reads
    (`plugins.environment`), written as rows under the package's own comment — never spelled here.

    THE CORE CARRIED THE CHAT PACKAGE'S TWO VARIABLES BY NAME until 2026-08-26 (`if
    answers.channel == "slack": …` with the two rows spelled out) — reached only with that
    package's row installed, and still the one place the core spelled a vendor's variable after
    the chat cut. A row that declares nothing gets the generic add-on section, which says whose
    variables go there."""
    from openfactory.adapters.channel.registry import AXIS, CHANNELS

    builder = plugins.builder(AXIS, kind, builtin=CHANNELS)
    names = plugins.environment(builder)
    if not names:
        return _add_on_block("channel", kind, out)
    listed = names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1]
    out.remaining.append(
        f"fill {listed} — the variables the `{kind}` channel add-on reads; its package says where "
        f"each comes from, and `openfactory doctor` reports which are still missing")
    how_to = plugins.how_to(builder)
    comment = ("".join(f"# {line}\n" for line in how_to.splitlines()) if how_to else
               f"# The package that provides `{kind}` says where each of these comes from.\n")
    rows = "".join(f"{name}=\n" for name in names)
    return (f"\n# ── The channel: where the tech-lead speaks when nobody is watching the panel ──\n"
            f"# `{kind}` is an add-on channel; these are the variables its rows read.\n"
            f"{comment}{rows}")


def render(answers: Answers, probes: Probes | None = None) -> Rendered:
    """The `.env.compose` this deployment needs, and nothing else."""
    answers.validate()
    p = probes or Probes()
    out = Rendered(text="")
    parts = [_HEADER]

    # THE HARNESS BLOCK RUNS FIRST so its to-do line is literally item 1: the docs call it "the
    # one credential you cannot postpone", and the funnel walkers caught the list disagreeing —
    # the forge rows landed first and the un-postponable credential read as an afterthought. Its
    # TEXT still renders after the forge sections; only the to-do order moved.
    harness_part = _harness_block(answers, out)

    if answers.uses_github:
        parts.append(_github_block(answers, p, out))

    if answers.uses_azure:
        out.remaining.append(
            "fill AZURE_DEVOPS_PAT — dev.azure.com → User settings → Personal access tokens, with "
            "the scopes docs/setup/azure-devops.md §1 lists (work items, code, builds; an "
            "`az account get-access-token --resource 499b84ac-1321-427f-aa17-267ca6975798` "
            "token works too). Then register the project with its dev.azure.com clone URL — "
            "`openfactory project add` reads the organisation/project/repository out of it; "
            "docs/setup/azure-devops.md walks the whole path to the first ticket")
        parts.append("""
# ── Azure DevOps — work items → Azure Repos pull requests ──
# dev.azure.com → User settings → Personal access tokens; the scope list, the board states and
# the registration command are docs/setup/azure-devops.md. The organisation, project and
# repository are coordinates, not secrets: `openfactory project add` reads them out of your
# dev.azure.com clone URL. A project may name its own variable with `options.token_env`; this
# is the default.
AZURE_DEVOPS_PAT=
""")

    if answers.uses_jira:
        out.remaining.append(
            "fill JIRA_API_TOKEN — id.atlassian.com → Security → API tokens (the email and the "
            "site are coordinates and belong in the project's registry entry)")
        parts.append("""
# ── Jira — tickets and board ──
# id.atlassian.com → Security → API tokens. The account's EMAIL and the site live in the
# project's registry entry: they are coordinates, not secrets.
JIRA_API_TOKEN=
""")

    # The forge and tracker add-ons, each a named section — the harness one is rendered by
    # `_harness_block` (it owns the to-do order) and the channel one below.
    for axis, kind in answers.add_ons():
        if axis in ("forge", "tracker"):
            parts.append(_add_on_block(axis, kind, out))

    parts.append(harness_part)

    if answers.channel not in shipped("channel"):
        parts.append(_channel_block(answers.channel, out))

    if answers.panel_exposed:
        out.obtained.append("OPENFACTORY_PANEL_TOKEN")
        parts.append(f"""
# ── The panel ──
# Generated here, because a panel reachable beyond localhost with no token is open to anyone who
# can reach the port. Rotate it by re-running with --force.
OPENFACTORY_PANEL_TOKEN={p.secret()}
""")
    else:
        parts.append("""
# ── The panel ──
# EMPTY MEANS OPEN — every /api/* route is reachable by anyone who can reach the port. That is
# deliberate for a laptop and wrong for anything else: re-run `openfactory init --panel-exposed`
# (it generates one) before this is reachable by anybody but you.
OPENFACTORY_PANEL_TOKEN=
""")

    parts.append("""
# ── How the factory signs its work in YOUR repository ──
# These are the git author on every commit it makes, so they appear in your history and your
# blame view for as long as the code lives.
OPENFACTORY_PLATFORM_NAME=OpenFactory
OPENFACTORY_BOT_NAME=OpenFactory Bot
OPENFACTORY_BOT_EMAIL=bot@openfactory.local

# ── Published ports — override any that collide with something already running ──
PANEL_PORT=8787
TEMPORAL_UI_PORT=8080
TEMPORAL_PORT=7233
""")

    out.text = "".join(parts)
    return out
