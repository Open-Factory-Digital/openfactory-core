A preview of `acme/api`: the `preview:` block for the team's own `compose.yaml` and an override beside it. **It was read from this repository, not invented** — every line below cites the file it came from, and the fields nothing could answer were left out rather than guessed.

**Not built.** Nothing in this pull request was built or run, on any machine. `openfactory preview propose acme-api --prove`, run where the deployment's preview runtime is, builds the base branch with this draft applied, once, on the deployment's own daemon — and takes it down.

## What merging this lets the factory do

Anyone the panel lets into this project can start this on the factory's daemon, on demand, and open it under the preview domain.

### `web`
- pulls `ghcr.io/acme/web:latest`, every time a preview starts
- opened on port 3000, as `web--acme-api--<n>.<preview domain>`
- bind mounts: none

### `api`
- built from this repository: the whole repository (`.`), with `Dockerfile` — instead of pulling `ghcr.io/acme/api:latest`
  - `FROM python:3.12-slim` — Dockerfile:1
  - `CMD ["python", "-m", "app.main"]` — Dockerfile:5
- opened on port 8000, as `api--acme-api--<n>.<preview domain>`
- bind mounts: none
- data: not declared — asked below

### `db`
- pulls `postgres:16`, every time a preview starts
- not opened: only the other services reach it
- bind mounts: none

## Each line, and where it was read

| what | tier | read from |
|---|---|---|
| `preview.compose` = compose.yaml, .openfactory/preview.compose.yml | observed | compose.yaml |
| `preview.expose.api` = 8000 | inferred | compose.yaml:15 |
| `preview.expose.web` = 3000 | inferred | compose.yaml:6 |
| service `api`: built from the whole repository (`.`) with `Dockerfile` | inferred | Dockerfile:1, Dockerfile:4, compose.yaml:13 |

## Questions only your team can answer

- how is `api`'s data migrated and seeded? A preview starts every store empty. Answer with `--set preview.data.api="<command>"` (a command run inside `api` once it is up).

## Flagged

- compose.yaml:17 gives `api` a literal `DATABASE_URL` (a password inside the address). A preview reads it as it is; if it is a real credential, anyone who can read this repository can too. Name its value in the registry instead: `openfactory project set-preview acme-api --env api=DATABASE_URL=<WORKER_NAME>`.
- compose.yaml:24 gives `db` a literal `POSTGRES_PASSWORD` (its name says it holds a secret). A preview reads it as it is; if it is a real credential, anyone who can read this repository can too. Name its value in the registry instead: `openfactory project set-preview acme-api --env db=POSTGRES_PASSWORD=<WORKER_NAME>`.

---

These files live under `.openfactory/` so they never collide with your own; move them and repoint `preview.compose` if you prefer. Nothing here is in effect until a person merges it, and the factory never merges it.
