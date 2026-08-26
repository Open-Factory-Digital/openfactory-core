"""The role prompts, and the ONE primitive every judging role is built on.

`org_defaults/roles/*.md` were always harness-agnostic — plain instructions, no CLI in them. What
was NOT agnostic was the plumbing: each judging role (sizer, coordinator, tech-lead, reviewer) was
hand-written into the Claude adapter, so a second harness meant re-implementing four methods that
differ only in their prompt text.

They don't differ in anything else. Every one of them is the same operation:

    run this prompt READ-ONLY against a checkout, give me the text back

So that is the primitive — `ask()` — and each harness implements it once, in whatever way that CLI
makes read-only real:

    claude   `--tools Read,Grep,Glob` + an explicit deny of the mutating set
    codex    `-s read-only` (a sandbox POLICY: it cannot edit, it is not merely told not to)
    kimi     `--plan` (a MODE — weaker; see the Kimi adapter's docstring)

Everything else — the sizer, the tech-lead's diagnosis, the coordinator's advice, the Slack answer,
the independent review — is then one shared implementation over `ask()`, identical for every
harness. Parity by construction rather than by four more copies.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from pathlib import Path

from openfactory.environ import ENV_NAME_SHAPE

_ROLES_DIR = Path(__file__).resolve().parent.parent.parent / "org_defaults" / "roles"


log = logging.getLogger("openfactory.roles")

_ROLE_NAME = re.compile(r"^[a-z][a-z0-9_]*$")


@dataclass(frozen=True)
class RoleSpec:
    """What an ADD-ON role declares — the value a `role.<name>` entry point's builder returns.

    The four shipped roles are rows in `registry.ROLES` / `ROLE_MODELS` and read their prompts from
    `org_defaults/roles/`; they never take this shape. A stranger's role (the consultancy's QA
    agent, for one) has no file in our package and no row in our tables, so everything the registry
    needs to resolve it travels in the spec instead:

    EXPLICIT env names, never a `OPENFACTORY_HARNESS_<ROLE>` convention. The convention would land
    in an already-occupied namespace: `OPENFACTORY_HARNESS_ENDPOINT` is the auth-route override and
    `OPENFACTORY_PLANNER_MODEL` is read by every adapter, so an add-on role called `endpoint` or
    `planner` would silently bind an operator's variable that means something else — two facts in
    one name. A name the add-on writes down is a name it can be held to — and it is held OUT of
    the platform's namespace altogether (`environ.reserved`: anything under `OPENFACTORY_*`, the
    old prefix, and the foreign variables the platform reads — derived from the code's own reads,
    `environ.names_read`), because a list of the names read today is exactly the list that is
    wrong tomorrow.

    ITS OWN PROMPT, non-empty. `role_prompt()` warns that an empty prompt means an incomplete
    installation, which is true of a shipped file and a lie about an add-on; refusing the empty spec
    here is what lets that warning stay honest without a second branch of it.

    `human_facing` says WHO READS THE ANSWER, and it is read by `needs_language_directive`. True:
    a person reads what the role says, and every phase the role passes gets the project's
    language directive, like the tech-lead's and the product role's answers. False: code parses
    the answer and no person ever reads it — a one-word verdict — and the directive is withheld,
    exactly as it is for the two shipped verdict phases in `MACHINE_PHASES`: a translated token
    parses as "neither". (A JSON whose strings end up in somebody's comment is read by a person;
    the shipped `product_triage` and its siblings are localised for that reason.) A role's phases
    are ITS NAME and `<name>_<anything>`, the shipped product role's own convention
    (`product_confirm`); a phase spelled any other way belongs to nobody and is localised,
    because that is the safe direction for a person.

    `harness` is the kind the role runs on when neither its env var nor the project's `harness:`
    names one — None means the platform's `DEFAULT_KIND`, like every shipped role."""

    name: str
    prompt: str
    harness_env: str
    model_env: str
    human_facing: bool
    harness: str | None = None

    def __post_init__(self) -> None:
        if not _ROLE_NAME.match(self.name or ""):
            raise ValueError(f"a role name is a lowercase identifier, not {self.name!r}")
        if not (self.prompt or "").strip():
            raise ValueError(f"role {self.name!r} declares an EMPTY prompt — an add-on role "
                             f"carries its own instructions; there is no file of ours to fall "
                             f"back to")
        for label, env in (("harness_env", self.harness_env), ("model_env", self.model_env)):
            if not ENV_NAME_SHAPE.match(env or ""):
                # the shape carries a prefix: a bare word (`HOME`, `PATH`) is the operating
                # system's, read by the runtime itself where no scan of ours can see it — an
                # add-on whose model override were `HOME` would hand a directory to a harness
                raise ValueError(f"role {self.name!r}: {label} must be an environment variable "
                                 f"name carrying its own prefix (`ACME_QA_MODEL`), not {env!r}")
        if self.harness_env == self.model_env:
            raise ValueError(f"role {self.name!r}: harness_env and model_env are the same "
                             f"variable {self.harness_env!r} — one value cannot name both a "
                             f"harness and a model")
        if self.harness is not None and not (self.harness or "").strip():
            raise ValueError(f"role {self.name!r}: `harness` is None (the platform default) or a "
                             f"kind, never {self.harness!r}")


#: Roles already reported as missing — one line each, not one per call: this is read on
#: every job and a repeated warning would be noise that teaches people to filter it.
_MISSING_SAID: set[str] = set()


def shipped_prompt_names() -> frozenset[str]:
    """The role prompts this package ships, by file name — the names an add-on role may not take.

    A glob, and that is fine HERE because absence fails in the safe direction: on a broken install
    this returns fewer names, so fewer add-ons are refused, and every shipped role still resolves
    from its own table. `readiness.ROLE_PROMPTS` is the literal that catches the broken install."""
    return frozenset(p.stem for p in _ROLES_DIR.glob("*.md"))


def role_prompt(role: str) -> str:
    """The neutral role instructions (planner / executor / sizer / techlead / coordinator).

    Missing file → "" so the caller degrades to its own generic prompt rather than crashing. That
    degrade is right and stays — but it USED TO BE SILENT, and silence is what made a packaging bug
    invisible: `pyproject.toml` globbed `org_defaults/*.md` at one level, so none of these seven
    files reached the wheel. On a `pip`-installed deployment every role ran with no instructions and
    nothing said so. The agent still wrote code — just without the platform's opinion in it, which
    is precisely the failure nobody reports.

    An empty role prompt is not "no opinion configured". It is an installation missing a file it
    ships with, and it is said out loud once per role.

    SHIPPED FIRST, THEN AN ADD-ON'S OWN TEXT. The order is the supply-chain rule from `plugins.py`:
    a package that could hand `techlead.md` a different body would change what the tech-lead means
    for every project on the deployment. So an add-on's prompt is read only for a role this package
    has no file for — the registry refuses the add-on outright when the name collides, and logs
    it."""
    path = _ROLES_DIR / f"{role}.md"
    if path.exists():
        return path.read_text()
    from openfactory.adapters.agent.registry import addon_role

    spec = addon_role(role)
    if spec is not None:
        return spec.prompt
    if role not in _MISSING_SAID:
        _MISSING_SAID.add(role)
        log.warning(
            "OPENFACTORY_ROLE_PROMPT_MISSING: no instructions for the %r role at %s — this role "
            "will run "
            "on the caller's generic prompt alone. The file ships with the package, so its absence "
            "means an incomplete installation rather than a configuration choice.", role, path)
    return ""


def can_judge(agent: object) -> bool:
    """Whether this harness can serve the judging roles at all. A harness that cannot run a
    read-only prompt cannot be a tech-lead or a reviewer, and saying so early beats discovering
    it when a job parks and the diagnosis silently fails."""
    return callable(getattr(agent, "ask", None))


#: THE CODING PHASES — the closed set whose prompt is NOT localised. An executor's prompt language
#: is a different question from a person's, and changing it would move a path that is working in
#: production for no benefit anyone asked for. So this is the side that is enumerated, and every
#: adapter's `_localised` prepends the directive for any phase outside it that a PERSON reads
#: (`needs_language_directive`; the phases code parses are `MACHINE_PHASES`, below).
#:
#: Inverted from an allowlist of human phases on 2026-08-24, because an allowlist fails in the
#: wrong direction: a phase nobody listed — a QA verdict from an add-on role, `qa_verdict` — was
#: emitted in English regardless of `project.language`, and the phase is ALSO the metering label
#: (`role=phase` in the product role, the timeout impediment in codex), so a role wanting its own
#: telemetry row had to invent a phase and thereby lose its language. With the closed set on this
#: side an unknown phase is localised by default and stays usable as a label.
#:
#: The strings are the ones the adapters really pass: `plan`/`execute`/`repair` (claude_code, kimi,
#: opencode), `planner`/`executor` (codex labels its runs by role), `review` (the reviewer over
#: `ask()`). `continue` and `recover` reach every adapter as `execute` today and are listed so a
#: harness that labels them by their own name stays on the coding side.
CODING_PHASES: frozenset[str] = frozenset({
    "plan", "planner", "execute", "executor", "repair", "continue", "recover", "review",
})

#: THE MACHINE-PARSED PHASES — prompts whose answer CODE reads, never a person, and which therefore
#: get NO language directive. Both are one-word verdicts of the product role (`product/role.py`,
#: `audience="team"`): `approve`/`reject`/`neither` on a proposal, `worked`/`did-not-work`/`neither`
#: on a delivery. The parser accepts the English token alone and treats anything else as
#: `neither` — so a directive that asked for pt-BR would leave every proposal pending and every
#: acceptance open, silently, at the sign-off gate the product sells (ADR-0021). Measured on the
#: day the coding set was inverted (2026-08-25): both phases fell into neither set and all four
#: adapters prepended the directive. A third set rather than a widened `CODING_PHASES`, because a
#: coding set holding two product verdicts is two facts in one name; and the same fact for an
#: add-on role is its `RoleSpec.human_facing=False`, read by `needs_language_directive` below.
MACHINE_PHASES: frozenset[str] = frozenset({"product_confirm", "product_accept"})

#: THE CATALOGUE of phases whose output a HUMAN reads: the tech-lead's answers and diagnoses, the
#: sizer's verdict, and everything else the product role says. Documentation of what exists today,
#: and a guard's cross-check (it may never intersect the other two sets) — NOT the rule the
#: adapters apply. The rule is `needs_language_directive` below; a phase absent from all three
#: sets is localised.
HUMAN_PHASES: frozenset[str] = frozenset({
    "ask", "chat", "advise", "diagnose", "size",
    "product_answer", "product_draft", "product_issues", "product_survey",
    # its JSON carries `reason` and `fix`, which are pasted into a comment a person reads — so a
    # missing entry here produced an English sentence inside a Portuguese template
    "product_triage", "product_queue", "product_refine",
    # the acceptance criteria it derives are written onto a card the client opens, and the card
    # already carries the requirement's own words around them — an English block between two
    # Portuguese ones reads as two different people wrote the ticket
    "product_align",
})

def needs_language_directive(phase: str) -> bool:
    """Whether the prompt for `phase` gets the project's language directive — THE ONE RULE the
    four adapters' `_localised` apply, so the answer cannot differ by harness.

    No for a coding phase (`CODING_PHASES`: the production coding path, unchanged on purpose).
    No when code parses the answer: a shipped verdict phase (`MACHINE_PHASES`), or a phase of an
    add-on role that declared `human_facing=False`. Yes for everything else — including a phase
    this tree has never seen, because the failure that costs a person something is the English
    answer at a client who set `language:`, not the localised label nobody asked for."""
    if phase in CODING_PHASES or phase in MACHINE_PHASES:
        return False
    from openfactory.adapters.agent.registry import addon_for_phase

    spec = addon_for_phase(phase)
    return spec is None or spec.human_facing


#: ENGLISH, because a DEFAULT IS THE PRODUCT. This was `pt-BR` — the language of the deployment
#: that happened to be built first — so every client who never set `language:` got a factory
#: speaking Portuguese to their team: the announcements, the triage reports, the questions
#: nobody prompted. The operator, on the day a backfill came out in Portuguese for a repository
#: whose next client is a European exchange (2026-08-14): *"o default tem que ser EN"*. A
#: deployment that wants another language SAYS so (`project add --language pt-BR`, written into
#: the registry), which is a decision anybody can read.
DEFAULT_LANGUAGE = "en"


def language_directive(language: str | None) -> str:
    """How the agent chooses a language, as one instruction.

    A DEFAULT rather than a hard setting, because the two cases genuinely differ. When the agent
    speaks first — an announcement, a diagnosis, a question nobody prompted — there is no incoming
    language to copy, so it needs one chosen for it. When it replies, the language of the question
    is a better signal than any configuration: someone who writes in English wants an answer in
    English, whatever the project's default says.

    Getting this backwards in either direction is visible immediately. A hard setting answers an
    English question in Portuguese; no setting at all makes proactive messages default to whatever
    the model feels like, which for most models means English at a Brazilian client."""
    lang = (language or DEFAULT_LANGUAGE).strip() or DEFAULT_LANGUAGE
    return (
        f"# Language\n\n"
        f"Write in **{lang}** by default — that is this project's language, and it applies to "
        f"anything you say first: announcements, diagnoses, questions, summaries.\n\n"
        f"When you are REPLYING to somebody, answer in the language THEY wrote in, even if it "
        f"differs from the default. The person's own words are a better signal than a setting.\n\n"
        f"Keep identifiers exactly as they are in either case — file names, requirement numbers, "
        f"code, commands and error messages are not translated."
    )
