"""What people wrote on a pull request, as the words of one adjust pass (#330).

THE GAP. People read the pull request and comment on it, attached to the lines they are about, and
nothing in the platform could read those comments. The only verb that sent the work back was
`adjust`, which carries a person's own typing: the supported way to act on a thread was to read it,
compress it into one paragraph inside 2,000 characters, and paste it back.

WHAT THIS MODULE DOES, AND NOTHING MORE. It turns the comments a forge row listed
(`forge/base.py::review_comments_of`) into the words handed to the agent, and into the note the
pull request carries about what the pass took. PURE: comments in, text out.

THE COMMENTS ARE DATA. They are handed to the harness in the slot a person's words fill, which
every harness fences as data apart from the platform's instruction (`machine._Brief`, #205). A pull
request comment is written by anyone with access to the repository, and it must not be able to
redirect the agent any more than a person's typed instruction can.
"""

from __future__ import annotations

from dataclasses import dataclass

from openfactory.adapters.forge.base import ReviewComment

#: The most one pass carries. The words reach a remote box in an environment variable, and a text
#: that does not fit there is a job that fails (#326); a pass also answers better on a dozen
#: comments than on a hundred. What does not fit is counted and said.
MAX_CHARS = 12000
MAX_COMMENTS = 30
#: One comment's own ceiling, so a pasted log in a thread cannot crowd out every other comment.
MAX_ONE = 3000


@dataclass(frozen=True)
class Carried:
    """The words for the agent, the comments they carry, and how many were left out."""

    words: str
    carried: tuple[ReviewComment, ...]
    left_out: int


def where(comment: ReviewComment) -> str:
    """Where a comment was written, as a reader names it."""
    if not comment.path:
        return "on the pull request"
    return f"on {comment.path}" + (f" line {comment.line}" if comment.line else "")


def brief_of(comments: list[ReviewComment]) -> Carried:
    """The comments, in the order the forge listed them, up to what one pass carries."""
    blocks: list[str] = []
    carried: list[ReviewComment] = []
    used = 0
    for c in comments:
        body = c.body.strip()
        if len(body) > MAX_ONE:
            body = body[:MAX_ONE] + " … (cut here: the rest of this comment is on the pull request)"
        block = f"Comment {len(carried) + 1}, by {c.author} {where(c)}:\n{body}\n"
        if len(carried) >= MAX_COMMENTS or used + len(block) > MAX_CHARS:
            break
        blocks.append(block)
        carried.append(c)
        used += len(block)
    left_out = len(comments) - len(carried)
    head = (f"{len(carried)} review comment{'s' if len(carried) != 1 else ''} that people left "
            f"on this pull request and that still stand"
            + (f" ({left_out} more were not carried by this pass)" if left_out else "") + ":\n\n")
    return Carried(words=head + "\n".join(blocks), carried=tuple(carried), left_out=left_out)


def what_was_carried(carried: Carried, *, by: str, pass_number: int) -> str:
    """The note the pull request carries before the pass runs: what it took, by author and line.

    WRITTEN BEFORE THE PASS, so the race with a comment that lands while it runs has a documented
    answer: what is not listed here is not in this pass."""
    lines = [f"{by or 'Somebody'} asked for the review comments to be addressed. "
             f"Adjust pass {pass_number} carries {len(carried.carried)}:", ""]
    lines += [f"- {c.author} {where(c)}" + (f" ({c.url})" if c.url else "")
              for c in carried.carried]
    if carried.left_out:
        lines += ["", f"{carried.left_out} more were not carried: one pass takes at most "
                      f"{MAX_COMMENTS} comments and {MAX_CHARS} characters. Ask again after it."]
    lines += ["", "A comment written after this note is not in this pass."]
    return "\n".join(lines)
