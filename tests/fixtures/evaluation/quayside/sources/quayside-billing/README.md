# Quayside Billing

Invoices an order the moment it is placed: listens to `order.placed`, reads the order's lines from
the orders service, and issues the invoice with the freight fixed on the order.

- `openapi.yaml` — the HTTP API
- `asyncapi.yaml` — the events it receives and sends
- `db/migration/` — its database, in Flyway's layout
- `billing/invoicing.py` — issuing an invoice
