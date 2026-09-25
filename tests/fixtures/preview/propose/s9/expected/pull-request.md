A preview of `acme/api`: the `preview:` block for the team's own `docker-compose.yml` and an override beside it. **It was read from this repository, not invented** — every line below cites the file it came from, and the fields nothing could answer were left out rather than guessed.

**Not built.** Nothing in this pull request was built or run, on any machine. `openfactory preview propose acme-api --prove`, run where the deployment's preview runtime is, builds the base branch with this draft applied, once, on the deployment's own daemon — and takes it down.

## What merging this lets the factory do

Anyone the panel lets into this project can start this on the factory's daemon, on demand, and open it under the preview domain.

### `api`
- built from this repository: the whole repository (`.`), with `Dockerfile`
  - `FROM python:3.12-slim` — Dockerfile:1
  - `CMD ["python", "-m", "src.app"]` — Dockerfile:5
- opened on port 8000, as `api--acme-api--<n>.<preview domain>`
- bind mounts: none
- data: not declared — asked below
- `DATABASE_URL` re-pointed at `db`

### `web`
- pulls `ghcr.io/acme/web:latest`, every time a preview starts
- opened on port 3000, as `web--acme-api--<n>.<preview domain>`
- bind mounts: none

### `db`
- pulls `postgres:16`, healthchecked with `pg_isready -U app -d app`; its data is a volume that is fresh for every preview
- not opened: only the other services reach it
- bind mounts: none

## Each line, and where it was read

| what | tier | read from |
|---|---|---|
| `preview.compose` = docker-compose.yml, .openfactory/preview.compose.yml | observed | docker-compose.yml |
| `preview.expose.api` = 8000 | inferred | docker-compose.yml:6 |
| `preview.expose.web` = 3000 | inferred | docker-compose.yml:16 |
| service `api`: re-pointed at a drafted stand-in | inferred | docker-compose.yml:3 |
| `api` receives `DATABASE_URL` | inferred | docker-compose.yml:8 |
| service `db`: `postgres:16`, healthchecked, a fresh volume for every preview | inferred | docker-compose.yml:8 |

## Questions only your team can answer

- which service stands in for `search.internal.example.com` (docker-compose.yml:10, `api`'s `SEARCH_HOST`)? A preview reaches nothing outside itself — add one to `.openfactory/preview.compose.yml`, or have the operator name a non-production value and open egress: `openfactory project set-preview acme-api --env api=SEARCH_HOST=<WORKER_NAME> --network <network>`.
- how is `api`'s data migrated and seeded? A preview starts every store empty. Answer with `--set preview.data.api="<command>"` (a command run inside `api` once it is up).

## Notes

- `api` reaches `db.prod.example.com` (docker-compose.yml:8), which a preview cannot: it reaches nothing outside itself. Drafted here: a fresh `db` (postgres:16) with `DATABASE_URL` pointed at it. The other way is the operator's: name a NON-PRODUCTION value and open egress — `openfactory project set-preview acme-api --env api=DATABASE_URL=<WORKER_NAME> --network <network>`.
- `db` is drafted with throwaway values (`app`/`app`) for a store only its own preview can reach; the address each service receives is written beside it — confirm your application reads that name.

---

These files live under `.openfactory/` so they never collide with your own; move them and repoint `preview.compose` if you prefer. Nothing here is in effect until a person merges it, and the factory never merges it.
