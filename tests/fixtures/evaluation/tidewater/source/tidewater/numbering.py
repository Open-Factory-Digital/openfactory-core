"""Invoice numbers: one continuous sequence, no year prefix (REQ-0009, since April 2023)."""


def next_number(last: int) -> int:
    """The number after `last` — the sequence never restarts."""
    return last + 1


def spelled(number: int) -> str:
    return f"TW-{number:06d}"
