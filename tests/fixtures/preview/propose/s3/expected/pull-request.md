A preview of `acme/api`: a compose file drafted from its Dockerfile, and the `preview:` block. **It was read from this repository, not invented** — every line below cites the file it came from, and the fields nothing could answer were left out rather than guessed.

**Not built.** Nothing in this pull request was built or run, on any machine. `openfactory preview propose acme-api --prove`, run where the deployment's preview runtime is, builds the base branch with this draft applied, once, on the deployment's own daemon — and takes it down.

## What merging this lets the factory do

Anyone the panel lets into this project can start this on the factory's daemon, on demand, and open it under the preview domain.

### `api`
- built from this repository: the whole repository (`.`), with `Dockerfile`
  - `FROM python:3.12-slim` — Dockerfile:1
  - `CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]` — Dockerfile:7
- opened on port 8000, as `api--acme-api--<n>.<preview domain>`
- bind mounts: none
- data: not declared — asked below

### `db`
- pulls `postgres:16`, healthchecked with `pg_isready -U app -d app`; its data is a volume that is fresh for every preview
- not opened: only the other services reach it
- bind mounts: none

## Each line, and where it was read

| what | tier | read from |
|---|---|---|
| `preview.compose` = .openfactory/preview.compose.yml | inferred | Dockerfile:1 |
| `preview.expose.api` = 8000 | observed | Dockerfile:6 |
| service `api`: built from the whole repository (`.`) with `Dockerfile` | observed | Dockerfile:1 |
| `api` receives `DATABASE_URL` | inferred | .env.example:2 |
| `api` receives `LOG_LEVEL` | observed | .env.example:4 |
| service `db`: `postgres:16`, healthchecked, a fresh volume for every preview | inferred | requirements.txt:3 |

## Questions only your team can answer

- how is `api`'s data migrated and seeded? A preview starts every store empty. Answer with `--set preview.data.api="<command>"` (a command run inside `api` once it is up).

## For the registry, not this file

The application reads these names and their values are secrets or per-environment, so they are never written into a file. The operator names them for previews:

- `SECRET_KEY` (.env.example:3) — `SECRET_KEY` looks like a secret (its name says it holds a secret): `openfactory project set-preview acme-api --env api=SECRET_KEY=<WORKER_NAME>`

## Notes

- `api` builds from the whole repository (context `.`), so any change to it rebuilds `api`
- `db` is drafted with throwaway values (`app`/`app`) for a store only its own preview can reach; the address each service receives is written beside it — confirm your application reads that name.

---

These files live under `.openfactory/` so they never collide with your own; move them and repoint `preview.compose` if you prefer. Nothing here is in effect until a person merges it, and the factory never merges it.
