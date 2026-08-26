"""The product module's data shapes (ADR-0019) — the registry section and the docs-repo manifest.

They live in `contracts` because they are vocabulary, not behaviour: `Project` embeds one, and the
reconciliation that decides whether the module may run reads both. The logic that USES them is in
`openfactory/product/config.py` — keeping it out of here is what stops every importer of `contracts`
from
dragging the product package in behind it.
"""

from __future__ import annotations

from pydantic import AliasChoices, BaseModel, ConfigDict, Field


class ProductConfig(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    """The `product:` section of a project's registry entry. Its PRESENCE enables the module.

    Deployment-level, like `harness` and the Slack coordinates: which repository holds a client's
    requirements, and who may act on them, is the operator's call and involves credentials and
    isolation the client's own `.openfactory/project.yaml` has no business naming."""

    #: the documentation repository, `owner/name`. Required — a product module with nowhere to
    #: write requirements is not a configuration, it is a mistake.
    docs_repo: str

    #: the product's own Slack channel. Requirements discussion does not belong in the channel
    #: where parked jobs and impediments arrive, and the two usually have different people in them.
    #: None → the module runs but stays silent on Slack (the issue/PR surfaces still work).
    channel_id: str | None = Field(
        default=None, validation_alias=AliasChoices("channel_id", "slack_channel"))

    #: Slack user ids allowed to make the product role ACT (ADR-0016's model). Empty = read-only
    #: for everyone: it can answer and draft, but not write a requirement or file an issue. The
    #: safe default — enabling the module never silently hands out authoring rights.
    admins: list[str] = Field(
        default_factory=list, validation_alias=AliasChoices("admins", "slack_admins"))

    #: What this agent calls itself to the client. A name, not a product: people talk to a named
    #: colleague differently from how they talk to "the product agent", and the whole point of this
    #: role is that a non-technical owner treats it as someone they can argue with.
    #:
    #: Empty → it introduces itself by function. Every phrase that uses this is written to work with
    #: ANY name ("meu nome é X"), never with a gendered article, so a client naming theirs Bruno
    #: does not get sentences written for a Nina.
    agent_name: str = ""

    #: branch the requirements live on
    docs_branch: str = "main"

    @property
    def declared_docs_branch(self) -> str:
        """The branch the REGISTRY names for the documentation repo, or `""` when it names none.

        Same collapse as `Manifest.declared_base_branch`, on the other contract, and the platform's
        own code contradicted the default: onboarding deliberately KEEPS a reused context
        repository's own default branch (`onboarding/onboard.py`, "a repository WITH history keeps
        ITS default branch"), and then this field said `main` about it. A `master` context repo was
        therefore cloned at a branch it does not have and every product question for that client
        was answered "I cannot see the requirements". Found by adversarial review, 2026-08-20.
        """
        return self.docs_branch if "docs_branch" in self.model_fields_set else ""

    #: kept configured but switched off, without deleting the section (an incident switch)
    enabled: bool = True

    #: WHERE THE CLIENT GOES TO TRY IT before it goes live (board #6). Named for them, not for the
    #: pipeline: the manifest already declares a staging environment for the platform to VERIFY,
    #: and that entry is a deploy ref and a health URL — machine coordinates, in the client's
    #: repository, describing something to check rather than somewhere to visit.
    #:
    #: Empty is allowed and costs only the address: the release is still offered and their answer
    #: still releases it, they are simply not told where to look. Refusing to ask because nobody
    #: configured a URL would hold the pipeline over a missing courtesy.
    staging_url: str = ""


class ProductDocs(BaseModel):
    """`.openfactory/product.yaml`, at the root of the documentation repository."""

    #: which product these requirements describe — must match the project's name
    product: str
    #: EVERY source repository implementing this product. A product spans N repos (back end, front
    #: end, a fleet of services) while a job still targets exactly one.
    sources: list[str] = Field(default_factory=list)
    #: where the requirement files live, relative to the repo root
    requirements_dir: str = "requirements"
