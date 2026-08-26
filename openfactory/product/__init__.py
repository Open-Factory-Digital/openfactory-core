"""The product module (ADR-0019) — the role that turns a conversation into a requirement.

OPT-IN PER CLIENT. A deployment enables it by giving a project a `product:` section in the
registry; a project without that section simply does not have the module, and nothing about the
rest of the factory changes. Enablement is the PRESENCE of the section rather than a boolean beside
it, so the module cannot be half-configured — "enabled: true" with no documentation repository is a
state that should not be expressible.

The pieces:

    config.py   who is authorized to hold whose requirements, and the reconciliation that decides
                whether the module may run at all for a project
    corpus.py   the requirements themselves — parsed, indexed, and checked for the specific ways a
                requirements repository rots
"""

from openfactory.contracts.product import ProductConfig, ProductDocs
from openfactory.product.brownfield import Baseline, Observation, milestone_files
from openfactory.product.config import (
    ProductLink,
    normalize_repo,
    repo_match,
    resolve_product_link,
)
from openfactory.product.corpus import Corpus, Finding, Requirement, load_corpus
from openfactory.product.loader import ProductContext, load_product_context
from openfactory.product.module import ProductModule, may_act
from openfactory.product.triage import TriageReport, triage
from openfactory.product.voice import announcement, jargon_in
from openfactory.product.workspace import ProductWorkspace, compose

__all__ = [
    "TriageReport",
    "ProductWorkspace",
    "Observation",
    "Baseline",
    "Corpus",
    "Finding",
    "ProductConfig",
    "ProductDocs",
    "ProductLink",
    "ProductContext",
    "ProductModule",
    "Requirement",
    "announcement",
    "compose",
    "jargon_in",
    "load_corpus",
    "milestone_files",
    "load_product_context",
    "may_act",
    "normalize_repo",
    "repo_match",
    "resolve_product_link",
    "triage",
]
