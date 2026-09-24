A preview of the product `shop`, across `acme/api` and `acme/web`: a compose file in this context repository drafted from their Dockerfiles, and the `preview:` block of `.openfactory/product.yaml`. **It was read from those repositories, not invented** — every line below cites the file it came from, as `<directory>/<path>` with each repository under its short name, and the fields nothing could answer were left out rather than guessed.

**Not built.** Nothing in this pull request was built or run, on any machine: a product's draft is built by its first preview, from the base branches, once a person has merged this.

## What merging this lets the factory do

Anyone the panel lets into this project can start this on the factory's daemon, on demand, and open it under the preview domain.

### `api`
- built from `acme/api` (the whole repository), with `Dockerfile`
  - `FROM python:3.12-slim` — api/Dockerfile:1
  - `CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]` — api/Dockerfile:7
- opened on port 8000, as `api--shop--<n>.<preview domain>`
- bind mounts: none
- data: not declared — asked below

### `db`
- pulls `postgres:16`, healthchecked with `pg_isready -U app -d app`; its data is a volume that is fresh for every preview
- not opened: only the other services reach it
- bind mounts: none

### `web`
- built from `acme/web` (the whole repository), with `Dockerfile`
  - `FROM node:20-slim` — web/Dockerfile:1
  - `CMD ["node", "src/index.js"]` — web/Dockerfile:7
- opened on port 3000, as `web--shop--<n>.<preview domain>`
- bind mounts: none

## Each line, and where it was read

| what | tier | read from |
|---|---|---|
| `preview.compose` = .openfactory/preview.compose.yml | inferred | api/Dockerfile:1 |
| `preview.expose.api` = 8000 | observed | api/Dockerfile:6 |
| `preview.expose.web` = 3000 | observed | web/Dockerfile:6 |
| service `api`: built from `acme/api` (the whole repository) with `Dockerfile` | observed | api/Dockerfile:1 |
| `api` receives `DATABASE_URL` | inferred | api/requirements.txt:3 |
| service `db`: `postgres:16`, healthchecked, a fresh volume for every preview | inferred | api/requirements.txt:3 |
| service `web`: built from `acme/web` (the whole repository) with `Dockerfile` | observed | web/Dockerfile:1 |

## Questions only your team can answer

- `acme/api`: how is `api`'s data migrated and seeded? A preview starts every store empty. Answer with `--set preview.data.api="<command>"` (a command run inside `api` once it is up).

## Notes

- `api` builds from the whole repository (context `.`), so any change to it rebuilds `api`
- `web` builds from the whole repository (context `.`), so any change to it rebuilds `web`
- `db` is drafted with throwaway values (`app`/`app`) for a store only its own preview can reach; the address each service receives is written beside it — confirm your application reads that name.

---

These files live under `.openfactory/` so they never collide with your own; move them and repoint `preview.compose` if you prefer. Nothing here is in effect until a person merges it, and the factory never merges it.
