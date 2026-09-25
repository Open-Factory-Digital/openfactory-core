"""The configuration keys a vendor named, read for one more minor version (#266 slice 6, D16).

THE TRANSPORT LEFT THE CORE AND ITS SHAPE STAYED IN THE CONTRACT. ADR-0038 moved the chat vendor
out as code; its keys stayed in `Project` and `ProductConfig` as the core's own vocabulary — a
channel id aliased to the vendor's spelling and read as "this project is on that vendor", admin
lists documented as the vendor's user ids, and the vendor's two bot tokens as fields of their own.
ADR-0051 D16 takes them out: an admin is a person of the platform, where a chat add-on posts is
that add-on's own option, and which add-on carries a project is said by `channel:` and never
inferred. Decision 6 keeps an existing configuration loading while it is renamed: the old keys are
read as ALIASES, with a deprecation warning, for one minor version (`READ_UNTIL`).

THIS FILE IS WHERE THOSE KEYS ARE DATA, and the only file in the core where they are. The vendor
guard (`tests/test_the_core_names_no_vendor.py`) allows a vendor's name here and says why: these are
the spellings a deployment's registry may still hold, not a vendor the core talks to.

WHAT AN ALIAS MAY DO, AND WHAT IT MAY NOT — it never grants more than its old key did:

  - its value is moved, as it is, to where it lives now, and only when that place is EMPTY;
  - the new spelling WINS when both are present, and the old one is then ignored — the two are
    never merged, because a merge would let an old admin list widen a new one;
  - an old channel coordinate becomes the add-on's option and nothing more: it no longer says
    which channel carries the project (the inference `adapters/channel/registry.py` used to make),
    so a project that declared no `channel:` talks through the panel and the warning says how to
    keep it on its add-on.

PURE, like the rest of the kernel: `fold` returns a new mapping and what it folded, and never logs.
The registry says it, once per registry, project and key, by name (`registry.py::_report_keys`).
"""

from __future__ import annotations

from dataclasses import dataclass

#: The minor version from which the old keys are no longer read: until then each one is folded
#: into its new place and named in a warning; from then it is an unknown key, which the registry
#: ignores and names like any other.
READ_UNTIL = "0.5.0"

#: Where a chat add-on's own coordinate for a project — the room it posts to — now lives: an
#: option of the section that carried it, read by the add-on and handed back to it by the core
#: (`adapters/channel/registry.py::channel_destination`), never interpreted.
ADDRESS = "channel"

#: The old keys of a registry project (`Project`) → where each value lives now, as a path under the
#: project. IN PRECEDENCE ORDER: `channel_id` was the newer spelling of the coordinate and won when
#: both were present (the `AliasChoices` order these replace), so it is folded first.
PROJECT_KEYS: dict[str, str] = {
    "channel_id": f"channel_options.{ADDRESS}",
    "slack_channel": f"channel_options.{ADDRESS}",
    "slack_admins": "admins",
    "slack_bot_token_env": "channel_options.bot_token_env",
    "slack_app_token_env": "channel_options.app_token_env",
}

#: The old keys of a project's `product:` section (`ProductConfig`), in the same order.
PRODUCT_KEYS: dict[str, str] = {
    "channel_id": f"channel_options.{ADDRESS}",
    "slack_channel": f"channel_options.{ADDRESS}",
    "slack_admins": "admins",
}

#: The old keys that named a chat coordinate — the ones that also used to decide the channel.
COORDINATES = frozenset({"channel_id", "slack_channel"})


@dataclass(frozen=True)
class Folded:
    """One old key found in a section: its spelling, where its value lives now, and whether it was
    IGNORED because the new spelling was already set there."""

    old: str
    new: str
    ignored: bool = False


def fold(data, keys: dict[str, str]):
    """`data` with every old key in `keys` moved to where it lives now, and what was folded.

    Returns `(data, [])` untouched for anything that is not a mapping (pydantic's own error then
    names it), and a NEW mapping otherwise — the caller's is never changed, because the registry
    reads the raw entry again to say what it found."""
    if not isinstance(data, dict):
        return data, []
    out = dict(data)
    folded: list[Folded] = []
    for old, new in keys.items():
        if old not in out:
            continue
        value = out.pop(old)
        head, _, leaf = new.partition(".")
        if leaf:
            bag = dict(out.get(head) or {})
            taken = leaf in bag and bag[leaf] not in (None, "")
            if not taken and value not in (None, ""):
                bag[leaf] = str(value)
                out[head] = bag
        else:
            taken = head in out and out[head] is not None
            if not taken and value is not None:
                out[head] = value
        folded.append(Folded(old=old, new=new, ignored=taken))
    return out, folded


__all__ = ["ADDRESS", "COORDINATES", "PRODUCT_KEYS", "PROJECT_KEYS", "READ_UNTIL", "Folded",
           "fold"]
