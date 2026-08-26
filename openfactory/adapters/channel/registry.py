"""Which channel a deployment talks through — from config, never from an import.

THE TABLE HOLDS THE PANEL AND NOTHING ELSE. A chat channel is an add-on: its row arrives through
the `openfactory.adapters` entry-point group (`channel.<kind>`), the way a stranger's would, and
the package that ships the maintainers' own (`openfactory-slack`) is named by the refusal when a
project declares a kind nobody installed. Until 2026-08-26 `slack` was a built-in row importing
its module lazily, so with the chat modules absent `channel: slack` raised a `ModuleNotFoundError`
out of the row instead of being refused by name — the seam the public cut would have shown.
`tests/test_the_chat_is_a_directory_delete.py` holds this table to one row and the refusal to the
package's name.
"""

from __future__ import annotations

from collections.abc import Callable

from openfactory import plugins

#: What a deployment gets when it says nothing AND has no third-party coordinates. The panel is
#: the reference surface (ADR-0038) and the only one that always exists.
DEFAULT_KIND = "panel"

#: The entry-point axis name: `channel.<kind>` — a builder `build(**kw) -> ChannelAdapter`.
AXIS = "channel"


def _panel(**kw):
    from openfactory.adapters.channel.panel import PanelChannel

    return PanelChannel()


#: kind → builder. A chat channel joins through the `channel.<kind>` entry point, never here.
#:
#: `panel` WAS THE SECOND IMPLEMENTATION OF THIS AXIS (C-25), and until it existed this dict was a
#: hypothesis: a registry with one row cannot tell you whether the contract describes a CHANNEL or
#: describes Slack. It is the only provider whose behaviour is provable without a third-party
#: account, which is why the channel tests can assert what a channel owes instead of mocking it —
#: and now the only one the core ships: the second implementation lives in its own package and
#: is held to the same contract by `openfactory conformance-adapter channel`.
CHANNELS: dict[str, Callable[..., object]] = {
    "panel": _panel,
}


def channel_kind(project=None) -> str:
    """Which channel this project talks through — declared, else INFERRED from what it has.

    The default was `slack`, and `Project.channel` defaults to `""`, so a deployment that declared
    nothing resolved to Slack. Verified by loading the shipped `registry.yaml.example` through
    this code: `channel='' → 'slack' → SlackChannel`. Meanwhile `.env.compose.example` tells the
    reader the opposite — "leave it empty and the factory still works: it reports on the ticket,
    and you drive it from the panel" — and `PanelChannel` sat registered, tested and unreachable
    in the default configuration of the artefact being open-sourced. The codebase's signature
    defect, in the shape being handed to strangers.

    Flipping the constant alone would have been the other failure: the live client declares no
    `channel:` either — it carries `channel_id` — so a bare default of `panel` would have silenced
    a working Slack deployment. The discriminator is what the project actually HAS, which is the
    same question `notifier_for_project` already asks one layer up:

        channel: <kind>   an explicit choice always wins
        channel_id set    Slack coordinates exist, so Slack is what was meant
        neither           the panel — the surface that is always there
    """
    explicit = str(getattr(project, "channel", "") or "").strip().lower()
    if explicit:
        return explicit
    if project is not None and str(getattr(project, "channel_id", "") or "").strip():
        return "slack"
    return DEFAULT_KIND


def build_channel(project=None):
    """The deployment's channel. Raises on an unknown kind rather than posting nowhere.

    Silence is this axis's failure mode, and it is indistinguishable from a quiet factory — which
    is the exact confusion the whole tech-lead layer exists to remove."""
    kind = channel_kind(project)
    builder = CHANNELS.get(kind) or plugins.builder(AXIS, kind, builtin=CHANNELS)
    if builder is None:
        raise ValueError(refusal(kind))
    return builder()


def refusal(kind: str) -> str:
    """The sentence for a kind this deployment cannot build: what IS installed, and — for a kind
    the platform's own packages ship — which package to install. One function so the worker's
    listener start and `build_channel` refuse with the same words."""
    _known = ', '.join(plugins.known(AXIS, CHANNELS))
    return (
        f"unknown channel {kind!r} — known: {_known}{plugins.install_hint(AXIS, kind)}. "
        f"Refusing to fall back: a deployment posting into a provider nobody reads is "
        f"indistinguishable from a factory with nothing to say."
    )


def channel_destination(project, configured: str = "") -> str:
    """Where this project's provider posts — or "" when it has nowhere to post.

    THE GATE THE PANEL PROVIDER KEPT FAILING (adversarial review of C-25). Every production
    say-path guarded itself with `if cfg.channel_id:` — a Slack rule, because Slack genuinely
    cannot post without a channel id. A `channel: panel` project has no Slack channel id and
    NEEDS none (its messages file under the project's own name), so each of those guards read
    the panel deployment as "nothing configured" and stayed silent: the provider shipped, its
    tests passed, and the paths that speak never reached it — the house defect class, again.

    One rule, here, beside the registry that knows the kinds: Slack-shaped providers need the
    configured id; the panel falls back to the project's name."""
    if channel_kind(project) == "panel":
        return configured or str(getattr(project, "name", "") or "")
    return configured
