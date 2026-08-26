"""Orchestrator control-flow exceptions."""

from __future__ import annotations


class SpecValidationError(Exception):
    """Raised by the deterministic SPEC_VALIDATION gate (ADR-0001 D-8). Its message
    is the specific reason the ticket goes back to NEEDS_REFINEMENT."""


class SetupFailed(Exception):
    """A `setup:` command from the manifest exited non-zero.

    Its own exception rather than a generic failure because the FAULT IS THE ENVIRONMENT, not the
    ticket and not the diff: `pip install` 404s, `dotnet restore` cannot authenticate to a private
    feed, `npm ci` meets a lockfile mismatch. Nothing about the work is wrong, and nothing about
    the work can fix it.

    Both call sites used to discard `sandbox.run`'s exit code entirely, so a broken environment was
    invisible: the agent was handed it anyway, spent real money, and the failure surfaced one layer
    later as a validation error pointing at the diff. For a client whose stack is not the box's,
    `setup:` is where the toolchain comes from — which makes this the first line every non-Python
    onboarding fails on, and it produced no message at all (ADR-0037 D3).

    The message carries the failing command and its output tail: the exit code says it broke, the
    output says why, and a private-feed 401 is diagnosable in one read and unguessable without it.
    """
