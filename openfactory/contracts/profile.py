"""What a project IS — the class, not the exception.

THE DIMENSION THIS ADDS, and the measurement that says it was missing. Ask what the platform can
say about the nature of a project and the entire vocabulary is two booleans: `components[].risk`
(`normal | high`, read by exactly one caller) and `merge_policy` (`human | auto`). Meanwhile
`orchestrator/context.py::_org_defaults` injects every framework guideline *"into EVERY job
regardless of project"*. Put the two together and the platform's position is:

    A throwaway proof-of-concept and a regulated bank's legacy monolith receive the same executor
    prompt, the same twelve engineering rules, and the same TDD mandate.

That is not a gap in customisation. It is a statement that the factory holds one opinion about how
software is built and applies it to everything — and it leaves an operator with nothing to tune
*toward*. Publishing all seven role prompts tomorrow would not help, because the platform never
asked what the project IS.

A PROFILE IS NOT A WAIVER, and giving them one mechanism would be the mistake. The distinction:

    waiver      this project is like the others, EXCEPT here — costs a named reason, an approver
                and an expiry; it is reviewed, stamped on the PR, and it comes back
    profile     this project is NOT like the others — costs a declaration, and the set that
                follows is coherent by construction

A proof-of-concept does not want to waive TDD with a written reason, a named approver and an
expiry date. That is bureaucracy applied to something that is not an exception: it is what the POC
*is*. Twelve signed waivers are paperwork; declaring what the project is and having a coherent set
follow is engineering.

THE NAME IS AN OPEN SET AND THAT IS LOAD-BEARING. `poc | legacy | greenfield | mobile` as an enum
is wrong at the first client with a nature nobody anticipated — the identical mistake the OKF port
plan refuses for the concept taxonomy (*"every company will have its own"*). So `name` is a plain
string, a profile composes through `extends` like any other layer, and the core ships two worked
examples rather than a vocabulary. What a profile authorises is company policy; the mechanism is
what ships.

WHICH DIRECTION A PROFILE MAY MOVE, because this is where a customisation surface becomes a hole.
The codebase's rule is ADR-0001 D-2: a project may tighten, never loosen. A profile keeps it, with
one deliberate exception that is not an exception to the rule but a consequence of what the rule
is about:

    guidelines  MAY be waived and replaced. These are prose the agent reads — the weak form of a
                rule, by this platform's own thesis. Dropping `tdd.md` for a prototype is the
                declaration doing its job, and demanding a signed waiver for it is the bureaucracy
                above.
    gates       MAY ONLY EVER BE ADDED, WHEN THEY ARRIVE. A gate is the strong form, the floor
                stays unconditional, and removing one is an EXCEPTION to the platform's opinion —
                a waiver, with a name and an expiry. No field expresses this yet: see `RiskPolicy`
                for why a `gates:` that nothing honours was worse than no `gates:` at all.
    merge       MAY ONLY BE STRENGTHENED. A profile can send a risk level to a human that the
                manifest would have auto-merged. It cannot do the reverse.

WHAT IS NOT FIXED HERE, stated so it is not mistaken for done. `RiskLevel.LOW` is still read by
nothing. `orchestrator/risk.py` says making `low` mean something is LOOSENING and needs *"a
waiver or a profile"* — this module is half of that sentence, and the half that arrived cannot
loosen. `low` becomes meaningful when the waiver object exists to carry the name and the expiry;
until then a profile can only make `low` stricter, which nobody wants and which is the honest
shape rather than a gradient this does not have.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator

from openfactory.contracts.state import RiskLevel

_STRICT = ConfigDict(extra="forbid")

#: How deep `extends` may go before we call it a cycle we are not going to untangle. A profile
#: chain is a human-authored declaration, not a graph — four layers is already more nesting than
#: the four-layer cascade itself has, and a longer one is a mistake rather than a use case.
MAX_EXTENDS_DEPTH = 4


class GuidelinePolicy(BaseModel):
    """Which prose the agent reads — the one thing a profile may take away.

    The framework's baseline lives in `openfactory/org_defaults/*.md` and is injected into every
    job. A profile addresses those files BY NAME (`tdd.md`), not by path: the caller resolves
    where they live, and a profile that named a path would break the moment the cascade grew the
    deployment overlay layer it is designed to sit in.
    """

    model_config = _STRICT

    #: paths, relative to the project checkout, appended AFTER the framework baseline — last
    #: WITHIN that baseline, and not last in the prompt: `build_context` goes on to append
    #: `docs.guidelines` and every component's, which are also the project's own content and
    #: which rightly keep the final position. Order is weight in a prompt, and what this buys is
    #: that a class outranks the framework, not that it outranks the project's own manual.
    extend: list[str] = Field(default_factory=list)

    #: framework baseline filenames this class of project does not operate under, e.g. `tdd.md`.
    #: Not a waiver: no approver, no expiry, because this is what the project IS. It still shows —
    #: `waived_guidelines` travels to the panel and the PR body, so "this project has no test-first
    #: discipline" is a fact a reader is told rather than one they infer from silence.
    waive: list[str] = Field(default_factory=list)

    #: `{framework filename: path in the checkout}` — the project's file stands in for the
    #: framework's. Content only, never policy, and the substitution is whole rather than merged:
    #: a half-replaced rule is a rule nobody can predict.
    replace: dict[str, str] = Field(default_factory=dict)

    @field_validator("waive", "extend")
    @classmethod
    def _no_blanks(cls, v: list[str]) -> list[str]:
        # A blank entry is a YAML editing accident (`waive:` followed by a stray `-`), and it would
        # otherwise waive nothing while reading as though it waived something.
        return [s for s in (x.strip() for x in v) if s]

    @field_validator("replace")
    @classmethod
    def _replacements_point_somewhere(cls, v: dict[str, str]) -> dict[str, str]:
        # A blank REPLACEMENT is the same accident with a worse symptom than a blank waive. It
        # lands in the "replacement is not in the checkout" branch — the right outcome — but the
        # warning then reads `replaces 'tdd.md' with ''`, which looks like a defect in the
        # platform rather than in the profile, and sends somebody to read our code.
        blank = sorted(k for k, path in v.items() if not (path or "").strip())
        if blank:
            raise ValueError(
                "a profile `replace:` entry must name a path in the checkout; these name nothing: "
                + ", ".join(blank))
        return {k: path.strip() for k, path in v.items()}


class RiskPolicy(BaseModel):
    """What a risk level COSTS in this class of project — the axis, rather than the flag.

    `risk` is already declared in client manifests in the field and moves exactly one thing today.
    Making it select what a change must survive reuses a field clients have already written, which
    is the cheapest possible route to the dimension.
    """

    model_config = _STRICT

    # THERE IS NO `gates:` FIELD YET, AND ITS ABSENCE IS DELIBERATE. An earlier draft of this
    # model carried one, accumulated it, and no validation runner, floor merge or conformance
    # check ever read it — so `regulated.yaml` promised "every risk level carries more evidence"
    # and a client adopting it got exactly zero extra gates, while `gates: [scurity]` validated,
    # resolved and was silently discarded. A field that cannot be honoured is worse than an
    # absent one: somebody writes it, reads the docstring, and believes their high-risk changes
    # are running a security gate. It arrives with its consumer or not at all.

    #: `human` sends this risk level to a person even where the manifest says `auto`. The only
    #: accepted value is `human`, and that asymmetry is the point: a profile may strengthen the
    #: gate and may not weaken it, so there is nothing for `auto` to mean here that would not be a
    #: loosening wearing a class's clothes.
    merge: str | None = None

    @field_validator("merge")
    @classmethod
    def _only_strengthens(cls, v: str | None) -> str | None:
        if v is not None and v != "human":
            raise ValueError(
                "profile risk.merge accepts only 'human' — a profile may strengthen the human "
                "gate, never weaken it. To auto-merge more, change `merge_policy` in the manifest, "
                "where the decision is the project's and a reader can see it.")
        return v


class Profile(BaseModel):
    """A named class of project, resolved as a cascade layer that composes.

    It is a layer and not a label because a label switches and a layer stacks: `extends` lets a
    client write `bank-legacy` on top of the core's `legacy` without restating it, which is what
    keeps the set open in practice rather than only in principle.
    """

    model_config = _STRICT

    #: free-form, and deliberately not an enum. See the module docstring.
    name: str

    #: the profile this one is layered on. Resolution accumulates outermost-last, so a profile
    #: always wins over what it extends — the same direction as every other cascade in the tree.
    extends: str | None = None

    #: one line, shown wherever the profile is named to a human. A class nobody can read the
    #: purpose of gets cargo-culted onto the next project.
    summary: str = ""

    guidelines: GuidelinePolicy = Field(default_factory=GuidelinePolicy)

    #: per `RiskLevel`. A level absent here costs what it costs today — absence is "this class has
    #: no opinion at this level", never "this class permits everything at this level".
    risk: dict[RiskLevel, RiskPolicy] = Field(default_factory=dict)

    @field_validator("name")
    @classmethod
    def _named(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("a profile must have a name — it is the thing the manifest points at")
        return v
