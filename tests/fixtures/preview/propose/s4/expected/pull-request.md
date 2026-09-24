A preview of `acme/shop`: a compose file drafted from its Dockerfiles, and the `preview:` block. **It was read from this repository, not invented** — every line below cites the file it came from, and the fields nothing could answer were left out rather than guessed.

**Not built.** Nothing in this pull request was built or run, on any machine. `openfactory preview propose acme-shop --prove`, run where the deployment's preview runtime is, builds the base branch with this draft applied, once, on the deployment's own daemon — and takes it down.

## What merging this lets the factory do

Anyone the panel lets into this project can start this on the factory's daemon, on demand, and open it under the preview domain.

### `api`
- built from this repository: `api/`, with `Dockerfile`
  - `FROM python:3.12-slim` — api/Dockerfile:1
  - `CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]` — api/Dockerfile:7
- opened on port 8000, as `api--acme-shop--<n>.<preview domain>`
- bind mounts: none
- data: not declared — asked below

### `web`
- built from this repository: `web/`, with `Dockerfile`
  - `FROM node:20-slim` — web/Dockerfile:1
  - `CMD ["npm", "start"]` — web/Dockerfile:9
- opened on port 3000, as `web--acme-shop--<n>.<preview domain>`
- bind mounts: none

### `db`
- pulls `postgres:16`, healthchecked with `pg_isready -U app -d app`; its data is a volume that is fresh for every preview
- not opened: only the other services reach it
- bind mounts: none

### `redis`
- pulls `redis:7`, healthchecked with `redis-cli ping`; its data is a volume that is fresh for every preview
- not opened: only the other services reach it
- bind mounts: none

## Each line, and where it was read

| what | tier | read from |
|---|---|---|
| `preview.compose` = .openfactory/preview.compose.yml | inferred | api/Dockerfile:1, web/Dockerfile:1 |
| `preview.expose.api` = 8000 | observed | api/Dockerfile:6 |
| `preview.expose.web` = 3000 | observed | web/Dockerfile:8 |
| service `api`: built from `api/` with `Dockerfile` | observed | api/Dockerfile:1 |
| `api` receives `DATABASE_URL` | inferred | api/.env.example:1 |
| `api` receives `REDIS_URL` | inferred | api/.env.example:2 |
| service `web`: built from `web/` with `Dockerfile` | observed | web/Dockerfile:1 |
| `web` receives `NEXT_PUBLIC_API_URL` (and as a build argument) | inferred | web/.env.example:2 |
| `web` receives `API_INTERNAL_URL` | inferred | web/.env.example:3, web/next.config.js |
| service `db`: `postgres:16`, healthchecked, a fresh volume for every preview | inferred | api/requirements.txt:3 |
| service `redis`: `redis:7`, healthchecked, a fresh volume for every preview | inferred | api/requirements.txt:4 |

## Questions only your team can answer

- `tools/loadtest/Dockerfile` is deeper than one directory, so it is not drafted as a service — is it part of the product a person opens, or tooling? If it is the product, add it to `.openfactory/preview.compose.yml`.
- which Dockerfile runs `worker` in a preview: `worker/Dockerfile` or `worker/Dockerfile.dev`? Two in one directory are the team's to choose between — add the one to `.openfactory/preview.compose.yml`.
- how is `api`'s data migrated and seeded? A preview starts every store empty. Answer with `--set preview.data.api="<command>"` (a command run inside `api` once it is up).

## For the registry, not this file

The application reads these names and their values are secrets or per-environment, so they are never written into a file. The operator names them for previews:

- `JWT_SECRET` (api/.env.example:3) — `JWT_SECRET` looks like a secret (its name says it holds a secret): `openfactory project set-preview acme-shop --env api=JWT_SECRET=<WORKER_NAME>`

## Notes

- `db` and `redis` are drafted with throwaway values (`app`/`app`) for a store only its own preview can reach; the address each service receives is written beside it — confirm your application reads that name.

---

These files live under `.openfactory/` so they never collide with your own; move them and repoint `preview.compose` if you prefer. Nothing here is in effect until a person merges it, and the factory never merges it.
