"""Payment reminders: by e-mail, seven days after the due date (REQ-0010, since April 2023)."""

from datetime import date, timedelta

REMINDER_AFTER = timedelta(days=7)


def reminder_day(due: date) -> date:
    return due + REMINDER_AFTER


def channel() -> str:
    return "email"
