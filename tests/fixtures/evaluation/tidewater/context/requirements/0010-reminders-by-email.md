# REQ-0010 — Payment reminders are sent by e-mail

- **Status:** accepted
- **Asked by:** helena
- **Date:** 2023-03-12
- **Supersedes:** 0005

## Why

Registered letters cost more than most overdue amounts, and every customer now has a billing
address for e-mail on their account.

## What must be true

- [ ] a reminder about an unpaid invoice is sent by e-mail to the account's billing address
- [ ] it is sent seven days after the due date

## Out of scope

- reminders by registered post

## Affects

- `tidewater/reminders.py`

## Open questions

## Decisions taken during execution

| date | decision | who decided, and where |
|---|---|---|
| 2023-03-12 | payment reminders go by e-mail; registered post is no longer used | helena — billing review |
