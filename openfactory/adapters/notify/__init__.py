from openfactory.adapters.notify.base import Level, Notifier, NullNotifier
from openfactory.adapters.notify.registry import NOTIFIERS, build_notifier

__all__ = ["NOTIFIERS", "Level", "Notifier", "NullNotifier", "build_notifier"]

# NO VENDOR NAME IS EXPORTED FROM HERE, lazily or otherwise. `SlackNotifier` and
# `TelegramNotifier` were PEP 562 lazy exports of this package until 2026-08-26 — resolved on
# first use, so the port did not load them, which was the right contract while they lived in
# this tree. They ship in `openfactory-slack` now, and a package `__init__` that advertises two
# names its own distribution does not contain is a promise that raises `ModuleNotFoundError` the
# first time somebody believes it. Import a chat notifier from its own module, as its package's
# entry point does.
