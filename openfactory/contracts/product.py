"""The product module's data shapes (ADR-0019) — the registry section and the docs-repo manifest.

They live in `contracts` because they are vocabulary, not behaviour: `Project` embeds one, and the
reconciliation that decides whether the module may run reads both. The logic that USES them is in
`openfactory/product/config.py` — keeping it out of here is what stops every importer of `contracts`
from
dragging the product package in behind it.
"""

from __future__ import annotations

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    PrivateAttr,
    ValidationError,
    field_validator,
    model_validator,
)

from openfactory.contracts import aliases


class ProductConfig(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    """The `product:` section of a project's registry entry. Its PRESENCE enables the module.

    Deployment-level, like `harness` and the channel's own options: which repository holds a
    client's requirements, and who may act on them, is the operator's call and involves credentials
    and isolation the client's own `.openfactory/project.yaml` has no business naming."""

    #: the documentation repository, `owner/name`. Required — a product module with nowhere to
    #: write requirements is not a configuration, it is a mistake.
    docs_repo: str

    #: WHERE THE PRODUCT'S OWN ROOM IS ON A CHAT ADD-ON, in that add-on's own terms — the room it
    #: posts to, under `channel` (`aliases.ADDRESS`), and whatever else it reads. Requirements
    #: discussion does not belong in the channel where parked jobs and impediments arrive, and the
    #: two usually have different people in them. OPAQUE TO THE CORE (#266 slice 6, ADR-0051 D16):
    #: it is handed back to the add-on and never read as which channel this is — `Project.channel`
    #: says that. Empty on a core deployment: the product's room is the panel's, keyed by the
    #: project's name. This replaced a first-class channel id the vendor had shaped, which is still
    #: read as an alias until `aliases.READ_UNTIL`.
    channel_options: dict[str, str] = Field(default_factory=dict)

    #: THE PEOPLE WHO MAY MAKE THE PRODUCT ROLE ACT (ADR-0016's model), by the id the platform
    #: knows them by — the identity provider's (a panel credential, an invitation, an SSO login),
    #: never a chat vendor's user id (#266 slice 6, ADR-0051 D16). A chat add-on maps its own users
    #: to these people before it hands a message to the door (`adapters/channel/base.py::
    #: PeopleOfAChannel`). Empty = read-only for everyone: it can answer and draft, but not write a
    #: requirement or file an issue. The safe default — enabling the module never silently hands
    #: out authoring rights.
    admins: list[str] = Field(default_factory=list)

    #: What this agent calls itself to the client. A name, not a product: people talk to a named
    #: colleague differently from how they talk to "the product agent", and the whole point of this
    #: role is that a non-technical owner treats it as someone they can argue with.
    #:
    #: Empty → it introduces itself by function. Every phrase that uses this is written to work with
    #: ANY name ("meu nome é X"), never with a gendered article, so a client naming theirs Bruno
    #: does not get sentences written for a Nina.
    agent_name: str = ""

    #: THE ZONE THE PRODUCT'S PEOPLE COUNT THEIR DAYS IN, an IANA name (`America/Sao_Paulo`). The
    #: role is told what day it is and when each line of a conversation was said
    #: (`product/clock.py`), and "ontem" is only true in somebody's zone: at 22:00 in São Paulo it
    #: is already tomorrow in UTC. Empty → UTC, and the role is told it is UTC.
    timezone: str = ""

    #: branch the requirements live on
    docs_branch: str = "main"

    #: ADR-0047 §4: both yeses belong to the person who asked. The FIRST — the one that confirms
    #: something staged in the conversation (a draft, a card, a fact, a decision, a queue) — and
    #: the SECOND, the one that turns a requirement into a promise. An admin who did not ask may
    #: give either on the requester's behalf ONLY when this says so; off by default, because a
    #: confirmation given for somebody else is the exact thing the two yeses exist to prevent, and
    #: a deployment that wants it says it here, where the operator can see it, rather than in a
    #: chat one afternoon. Until #266 slice 4 this governed the second yes alone, and any admin's
    #: yes confirmed whatever was staged in a room; ADR-0051 D11 extends it to the first, so one
    #: key gives one answer to whether an admin may speak for the requester. Either way the yes
    #: still has to come from somebody on `admins`: a requester off that list confirms nothing.
    accept_on_behalf: bool = False

    #: The people who BUILD this product, by the ids the platform identifies them with (panel
    #: identities on a core deployment; a chat add-on maps its users to the same people). #266
    #: slice 4, ADR-0051 decision 8: every person
    #: speaking to the product role has one of three roles in it — client, product admin, engineer
    #: — and client is the default. An admin is on `admins`; an engineer is listed here; everybody
    #: else is a client. It shapes how the role speaks to them (`product/speaker.py`) and grants
    #: nothing: whose yes records anything is still `admins` alone.
    engineers: list[str] = Field(default_factory=list)

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

    @model_validator(mode="before")
    @classmethod
    def _read_the_old_keys(cls, data):
        """The keys a vendor named, folded into where they live now (`contracts/aliases.py`): read
        for one minor version, the new spelling winning, never merged. The registry names each one
        it finds."""
        return aliases.fold(data, aliases.PRODUCT_KEYS)[0]


def _inside(path: str, what: str) -> str:
    """`path` when it names a place INSIDE a repository — relative, no `..`, no `~`, no `$`."""
    p = (path or "").strip()
    if not p or p.startswith(("/", "~")) or "$" in p or ".." in p.split("/"):
        raise ValueError(f"{what} {path!r} must be a path inside the repository (relative, no "
                         f"`..`, no `~`, no `$`)")
    return p


class ComposeRef(BaseModel):
    """Where a PRODUCT's compose file lives (ADR-0050 D3/D5; the design on #265, §2.2).

    `repository` is `""` for the context repository itself, else `owner/name` — which must be one
    of the product's `sources:`: the shape of a product is read from a repository of that product,
    never from one a line in this file could point anywhere. `paths` are relative to that
    repository's root, merged the way the compose CLI merges them."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    repository: str = ""
    paths: list[str] = Field(min_length=1)

    @field_validator("paths", mode="before")
    @classmethod
    def _one_file_is_a_list_of_one(cls, v):
        return [v] if isinstance(v, str) else v

    @field_validator("paths")
    @classmethod
    def _relative_and_inside(cls, v: list[str]) -> list[str]:
        return [_inside(p, "preview.compose.paths") for p in v]


class ProductPreview(BaseModel):
    """`preview:` in `.openfactory/product.yaml` — how a product of SEVERAL repositories is
    previewed (the design on #265, §2.2 and §6).

    The same four fields a repository's own `preview:` block carries, plus the two things only a
    product has to say: which repository the compose file lives in (`compose`), and which
    repository a sibling directory the file reaches (`../web`) is when that directory is not the
    repository's short name (`dirs`). Every repository either names must be a member of
    `sources:` — checked where it is read, against the membership set the same file declares.

    STRICT, UNLIKE THE FILE AROUND IT. `ProductDocs` stays lenient so a file written before this
    block loads; the block itself forbids a key it does not know, because a misspelt `expose` in
    a preview is a service nobody can open, and a quiet one."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    compose: ComposeRef
    #: sibling directory name → `owner/name`, when a compose file's `../<dir>` differs from the
    #: repository's short name
    dirs: dict[str, str] = Field(default_factory=dict)
    expose: dict[str, int] = Field(min_length=1)
    data: dict[str, str | list[str]] = Field(default_factory=dict)
    exclude: list[str] = Field(default_factory=list)

    @field_validator("compose", mode="before")
    @classmethod
    def _paths_alone_are_the_context_repository(cls, v):
        # `compose: .openfactory/preview.compose.yml` (or a list) is the context repository's own
        # file — the shape `preview propose --product` drafts
        return {"paths": v} if isinstance(v, str | list) else v

    @field_validator("dirs")
    @classmethod
    def _one_directory_each(cls, v: dict[str, str]) -> dict[str, str]:
        for name in v:
            if not name or "/" in name or name in (".", "..") or name.startswith(("~", "$")):
                raise ValueError(f"preview.dirs key {name!r} must be one directory name — the "
                                 f"`<dir>` of a `../<dir>` in the compose file")
        return v

    @model_validator(mode="after")
    def _consistent(self) -> ProductPreview:
        bad = {k: v for k, v in self.expose.items() if not 1 <= int(v) <= 65535}
        if bad:
            raise ValueError(f"preview.expose ports must be 1–65535, got {bad}")
        both = sorted(set(self.expose) & set(self.exclude))
        if both:
            raise ValueError(f"preview.expose and preview.exclude both name {both}")
        excluded_data = sorted(set(self.data) & set(self.exclude))
        if excluded_data:
            raise ValueError(f"preview.data names excluded services {excluded_data}")
        return self


class ProductDocs(BaseModel):
    """`.openfactory/product.yaml`, at the root of the documentation repository."""

    #: which product these requirements describe — must match the project's name
    product: str
    #: EVERY source repository implementing this product. A product spans N repos (back end, front
    #: end, a fleet of services) while a job still targets exactly one.
    sources: list[str] = Field(default_factory=list)
    #: where the requirement files live, relative to the repo root
    requirements_dir: str = "requirements"
    #: how the product is previewed across its repositories (#265 slice 5), or None
    preview: ProductPreview | None = None

    #: why a declared `preview:` could not be read — kept here, never raised: a typo in the
    #: preview block must not turn the whole product module off (the requirements, the board,
    #: the conversation), so the file loads without it and the PREVIEW says why it will not run.
    _preview_error: str = PrivateAttr(default="")

    @property
    def preview_error(self) -> str:
        return self._preview_error

    @model_validator(mode="wrap")
    @classmethod
    def _a_bad_preview_block_never_turns_the_module_off(cls, data, handler):
        block = data.get("preview") if isinstance(data, dict) else None
        if block is None:
            return handler(data)
        try:
            ProductPreview.model_validate(block)
        except ValidationError as exc:
            first = exc.errors()[0] if exc.errors() else {}
            where = ".".join(str(p) for p in first.get("loc", ()))
            docs = handler({**data, "preview": None})
            docs._preview_error = ("`preview:` in `.openfactory/product.yaml` is invalid"
                                   + (f" at `preview.{where}`" if where else "")
                                   + f": {first.get('msg', 'unknown')}")
            return docs
        return handler(data)
