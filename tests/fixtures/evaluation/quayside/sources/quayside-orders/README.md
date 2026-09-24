# Quayside Orders

Takes a customer's order, fixes the freight quoted for it, stores it and announces it.

- `api/openapi.yaml` — the HTTP API
- `api/asyncapi.yaml` — the events it sends
- `db/migrations/` — its database, in golang-migrate's layout
- `orders/placing.py` — placing an order: the freight quote, then the event
