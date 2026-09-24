# REQ-0005 — Payment reminders are sent by registered post

- **Status:** superseded-by 0010
- **Asked by:** helena
- **Date:** 2021-06-02
- **Supersedes:** —

## Why

Some customers disputed having received a reminder; a registered letter is proof of delivery.

## What must be true

- [ ] a reminder about an unpaid invoice is printed and sent by registered post
- [ ] it is sent seven days after the due date

## Out of scope

- reminders by telephone

## Affects

- `tidewater/reminders.py`

## Open questions

## Decisions taken during execution

| date | decision | who decided, and where |
|---|---|---|
| 2021-06-02 | payment reminders go by registered post, seven days after the due date | helena — collections review |
