# Quayside Platform

How Quayside's services run.

- `docker-compose.yml` — everything on one machine, each service built from its repository
- `k8s/` — the orders service on the cluster
- `charts/quayside/` — the Helm chart the cluster is moving to
- `infra/` — the database and the queue in production
