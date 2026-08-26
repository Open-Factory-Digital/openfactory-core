"""The adapter conformance suite (C-22) — hand it your adapter, show a green run."""

from openfactory.conformance.adapters import (
           CHECKS,
           Finding,
           check_board,
           check_box,
           check_channel,
           check_forge,
           check_harness,
           check_identity,
           check_notifier,
           check_observer,
           check_tracker,
)

__all__ = ["CHECKS", "Finding", "check_board", "check_box", "check_channel", "check_forge",
           "check_harness", "check_identity", "check_notifier", "check_observer",
           "check_tracker"]
