"""A provider that refused the CLI is a sentence, not a traceback (#111).

Measured in the pre-pilot review (2026-08-09) and reproduced end to end with no network:
`openfactory run <project> <n>` against a repository that does not exist, or with `gh` not
authenticated, or against a private repository the credential cannot see, ended in a raw Rich
traceback — `RuntimeError: gh issue view failed: …` — instead of the one-cause-one-remedy sentence
this platform's own rule demands of every other surface.

The commonest case, the `gh` binary missing, already refuses by name from inside the adapter. What
was missing is the general class: the provider ANSWERED, and its answer was no.

THE CATCH BELONGS AT THE EDGE, NOT IN THE ADAPTERS, and that is the whole method note on the card.
The durable worker needs the real exception: `techlead/classify.py` reads it to decide whether the
job parks as a credential problem, a policy problem or a transient one, and an adapter that
flattened every failure into prose would take that away — the platform would stop being able to
tell a revoked token from a repository somebody renamed. So the exception travels intact
everywhere, and exactly one place — the command line, where a person is reading — turns it into a
sentence.

WHAT IT MUST NEVER DO IS GUESS. A cause it does not recognise is printed as itself, with the
provider's own words, because a wrong remedy costs more than an unhelpful one: somebody who is
told to run `gh auth login` about a repository that was renamed spends the afternoon on the
credential.
"""

from __future__ import annotations

import re

#: Each entry: (what it is, what to do about it, patterns that identify it in the provider's own
#: words). Ordered — the FIRST match wins, so the narrow readings come before the broad ones.
#:
#: PATTERNS OVER THE PROVIDER'S TEXT, which is the honest shape and also the fragile one. They are
#: matched case-insensitively against the whole error chain, and anything unmatched falls through
#: to the provider's words verbatim rather than to a guess.
_CAUSES: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    (
        "this deployment is not authenticated to the forge",
        "run `gh auth login`, or set OPENFACTORY_BOT_TOKEN / the GitHub App variables "
        "(docs/setup/github.md). `openfactory doctor <project>` reports which one this "
        "deployment is using.",
        ("gh auth login", "not logged into", "authentication token", "no authentication",
         "requires authentication", "bad credentials", "401", "tf400813", "unauthorized"),
    ),
    (
        "the credential is authenticated but not allowed on this repository",
        "check the App's installation covers it (Settings → GitHub Apps → this app → Repository "
        "access), or that the token's scopes include it. On Azure DevOps, check the PAT's scopes "
        "and that it belongs to the right organisation.",
        ("403", "forbidden", "resource not accessible", "must have admin rights",
         "insufficient", "does not have permission", "saml enforcement"),
    ),
    (
        "the repository or the ticket is not there — under that name, for this credential",
        "check the project's `repo` in the registry (`openfactory project list`) and the ticket "
        "number. A PRIVATE repository the credential cannot see answers exactly like one that "
        "does not exist, so this is the same sentence for both.",
        ("could not resolve to a repository", "not found", "404", "no such", "does not exist",
         "tf401019", "unknown repository"),
    ),
    (
        "the forge is rate-limiting this deployment",
        "wait for the window to refill — `openfactory doctor <project>` prints when. A personal "
        "account board is read with YOUR token, so that quota is yours, not the App's "
        "(docs/setup/github.md §6).",
        ("rate limit", "abuse detection", "submitted too quickly", "secondary rate"),
    ),
    (
        "the provider did not answer in time",
        "try again; if it repeats, check the provider's status page and this machine's network. "
        "Nothing was changed by a call that never completed.",
        ("timed out", "timeout", "connection reset", "temporary failure in name resolution",
         "could not resolve host", "connection refused"),
    ),
)

#: What a subprocess-shaped failure looks like when it reaches here. Matched on the message rather
#: than the type, because every adapter raises `RuntimeError` with the provider's stderr in it —
#: which is the shape this exists to translate.
_PROVIDER_SHAPED = re.compile(
    r"\b(gh|git|az|glab)\b.*\bfailed\b|azuredevops|\bapi\b.*\bfailed\b", re.I)


def _all_the_words(exc: BaseException) -> str:
    """Every message in the chain, joined. A `gh` failure often arrives wrapped, and the sentence
    that identifies the cause is rarely the outermost one."""
    seen: list[str] = []
    cursor: BaseException | None = exc
    while cursor is not None and len(seen) < 8:
        seen.append(str(cursor))
        cursor = cursor.__cause__ or cursor.__context__
    return " ".join(seen)


def name_the_cause(exc: BaseException) -> tuple[str, str] | None:
    """`(what happened, what to do)` — or None when nothing here recognises it.

    None is a real answer and the caller prints the provider's own words for it. Inventing a
    remedy for an unrecognised failure is worse than admitting the failure: somebody told to run
    `gh auth login` about a renamed repository spends the afternoon on the credential."""
    words = _all_the_words(exc).lower()
    if not words.strip():
        return None
    for what, remedy, markers in _CAUSES:
        if any(m in words for m in markers):
            return what, remedy
    return None


def looks_like_a_provider(exc: BaseException) -> bool:
    """Is this a provider refusing, rather than a bug in this codebase?

    THE LINE MATTERS BOTH WAYS. Swallowing a genuine `TypeError` into a friendly sentence about
    credentials is how `_waiting_on_a_human` swallowed the pilot's merge — a real defect wearing
    an explanation. So only failures that carry a provider's own vocabulary are translated;
    everything else keeps its traceback, which is what a traceback is for."""
    if isinstance(exc, KeyboardInterrupt | SystemExit):
        return False
    return bool(_PROVIDER_SHAPED.search(_all_the_words(exc)))


def speaks_plainly(doing: str):
    """Wrap a CLI command so a PROVIDER's refusal prints as a sentence and exits 1.

    A DECORATOR RATHER THAN A TRY IN EACH BODY, for the reason this codebase keeps re-learning: a
    rule that has to be remembered at four call sites is a rule three of them will eventually
    forget. Typer reads the wrapped function's signature through `functools.wraps`, so every
    option and its help text survive.

    ANYTHING THAT IS NOT A PROVIDER KEEPS ITS TRACEBACK. A `TypeError` in this codebase dressed up
    as a friendly note about credentials is how `_waiting_on_a_human` swallowed the pilot's merge —
    the defect wearing an explanation. `looks_like_a_provider` draws that line and errs toward the
    traceback.
    """
    import functools

    def decorate(fn):
        @functools.wraps(fn)
        def inner(*args, **kwargs):
            import typer

            try:
                return fn(*args, **kwargs)
            except (typer.Exit, typer.Abort, KeyboardInterrupt):
                raise
            except Exception as exc:  # noqa: BLE001 — re-raised below unless it is a provider
                if not looks_like_a_provider(exc):
                    raise
                typer.echo(as_a_sentence(exc, doing=doing), err=True)
                raise typer.Exit(1) from None

        return inner

    return decorate


def as_a_sentence(exc: BaseException, *, doing: str) -> str:
    """The whole refusal, ready to print. Always names what was being attempted."""
    named = name_the_cause(exc)
    words = str(exc).strip()
    if named is None:
        return (f"could not {doing} — the provider refused and this is what it said:\n\n"
                f"  {words[:400]}\n\n"
                f"That is the provider's own message, verbatim: nothing here recognised it well "
                f"enough to name a remedy, and guessing one would cost you more than this does.")
    what, remedy = named
    return (f"could not {doing}: {what}.\n\n"
            f"  {remedy}\n\n"
            f"The provider said: {words[:300]}")
