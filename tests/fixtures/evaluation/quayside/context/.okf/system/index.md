# The system, across the product's sources

> Derived without a model from what the product's repositories declare — OpenAPI, AsyncAPI, proto, migrations, compose, Kubernetes and Terraform — read as text; nothing in them was run. Every entry cites the file and the commit it came from. What a repository does not declare (an address chosen at run time, a call made through code no description names) is not here, and what could not be derived is listed. Test, example, vendored and build directories are not read. It says where to look; the code says what is true.

## What this map could not derive

- **not-declared** — `quayside-billing` `asyncapi.yaml`: `billing` receives `payment.settled`, and no source declares who sends it
- **not-declared** — `quayside-platform` `docker-compose.yml`: `billing` names `notifications` in `NOTIFICATIONS_URL`, and no source declares a component `notifications`
- **not-followed** — `quayside-platform` `infra/main.tf`: module `network` (line 21) comes from outside this repository and is not fetched; what it declares is not derived
- **not-read** — `quayside-platform` `k8s/orders.yaml`: `orders` takes `DATABASE_URL` from a secret; a secret's value is never read, so where it points is not derived
- **unknown-format** — `quayside-platform` `charts/quayside/Chart.yaml`: is a Helm chart: its manifests exist only when helm renders the templates, which runs the chart and is never done here; the services it deploys are not derived

## Sources

- `quayside-billing` @ `fixture` — 5 declaration file(s) read
- `quayside-freight` @ `fixture` — 1 declaration file(s) read
- `quayside-orders` @ `fixture` — 7 declaration file(s) read
- `quayside-platform` @ `fixture` — 3 declaration file(s) read

## Components

- **billing** (service) — code in `quayside-billing` `.`
  - talks to **billing-db** (database, env DATABASE_URL)
  - talks to **kafka** (broker, env KAFKA_BROKERS)
  - talks to **orders** (http, env ORDERS_URL)
- **billing-db** (database)
- **freight** (service) — code in `quayside-freight` `.`
- **kafka** (broker)
- **orders** (service) — code in `quayside-orders` `.`
  - talks to **billing** (event, channel order.placed)
  - talks to **freight** (grpc, env FREIGHT_ADDR)
  - talks to **kafka** (broker, env KAFKA_BROKERS)
  - talks to **orders-db** (database, env DATABASE_URL)
- **orders-db** (database)

## Interfaces

7 in [`api.yaml`](api.yaml).

## Databases

2 in [`schema.yaml`](schema.yaml).

## Decision records

3 in [`adr-index.yaml`](adr-index.yaml).

- HTTP API of **billing** — 2 operation(s), `quayside-billing` `openapi.yaml`
- HTTP API of **orders** — 4 operation(s), `quayside-orders` `api/openapi.yaml`

- event `invoice.issued` — sent by billing; received by nobody declared
- event `order.cancelled` — sent by orders; received by nobody declared
- event `order.placed` — sent by orders; received by billing
- event `payment.settled` — sent by nobody declared; received by billing

- database **billing-db** — 2 table(s), owned by billing
- database **orders-db** — 2 table(s), owned by orders
