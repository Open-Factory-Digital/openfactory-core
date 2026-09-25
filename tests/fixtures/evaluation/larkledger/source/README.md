# Lark Ledger

Invoices for small businesses: numbered without gaps, sent to customers, and chased when they are
not paid. The requirements live in the context repository, `larkledger-context`.

- `larkledger/invoices.py` — an invoice, its lines, its total and its due date
- `larkledger/numbering.py` — the number an invoice gets when it is issued
- `larkledger/reminders.py` — which reminder, if any, an unpaid invoice is due today
