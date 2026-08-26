"""Onboarding — arriving at a repository that already exists.

Everything else in this platform VERIFIES what a client has already declared: `doctor` checks the
manifest they wrote, `conformance` grades it, `box prove` runs its commands. That is the right
shape for a greenfield project and the wrong half of the problem for the client base card #99
names — *"grande parte dos nossos clientes será para continuação de LEGADO"*. On fifteen years of
code the hard part is not verifying `validate.test`; it is FINDING it.

This package PROPOSES. `infer` reads a repository and returns a proposal in which every field
carries its evidence (`file:line`) and its tier — `observed`, `inferred`, or an `unknown` that
says so out loud instead of guessing. It runs nothing, writes nothing and reaches no network.

ONE NAME, TWO THINGS, AND IT IS DELIBERATE. The `infer` re-exported below is the FUNCTION, and it
shadows the submodule `openfactory.onboarding.infer` on this package: after this import,
`from openfactory.onboarding import infer` hands back a callable, not a module. That is
load-bearing.
`openfactory/actions/catalog.py::_entry_point` resolves an entry point by trying `propose`, then
`infer`,
then "is the thing itself callable?" — with the function bound here it lands on `infer()` and
`openfactory env read` gets the rich `ManifestProposal`, which is the only shape carrying
`cannot_express`, `questions`, `stacks` and `unreadable_dirs`. Drop this re-export to
"disambiguate" the name and the resolver falls through to `propose()`, whose flat
`{field: {...}}` shape cannot express any of them — the client-2 block would disappear from the
report with every test still green. Import the submodule explicitly
(`from openfactory.onboarding.infer import propose`) when you want the flat view.
"""

from openfactory.onboarding.infer import (
    INFERRED,
    OBSERVED,
    TIERS,
    UNKNOWN,
    Candidate,
    Evidence,
    ManifestProposal,
    Proposal,
    StackSighting,
    classify,
    infer,
    propose,
    render_report,
    render_yaml,
    split_commands,
    to_manifest_dict,
)

__all__ = [
    "INFERRED",
    "OBSERVED",
    "TIERS",
    "UNKNOWN",
    "Candidate",
    "Evidence",
    "ManifestProposal",
    "Proposal",
    "StackSighting",
    "classify",
    "infer",
    "propose",
    "render_report",
    "render_yaml",
    "split_commands",
    "to_manifest_dict",
]
