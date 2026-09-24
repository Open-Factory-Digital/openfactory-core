A preview of `acme/shop`: a Dockerfile and a compose file drafted from what it says it runs, and the `preview:` block. **It was read from this repository, not invented** — every line below cites the file it came from, and the fields nothing could answer were left out rather than guessed.

**Not built.** Nothing in this pull request was built or run, on any machine. `openfactory preview propose acme-shop --prove`, run where the deployment's preview runtime is, builds the base branch with this draft applied, once, on the deployment's own daemon — and takes it down.

## What merging this lets the factory do

Anyone the panel lets into this project can start this on the factory's daemon, on demand, and open it under the preview domain.

### `shop`
- built from this repository: the whole repository (`.`), with `.openfactory/preview/shop.Dockerfile`
  - `FROM python:3.12-slim` — drafted, .python-version:1
  - `CMD python manage.py runserver 0.0.0.0:8000` — drafted, manage.py
- opened on port 8000, as `shop--acme-shop--<n>.<preview domain>`
- bind mounts: none
- data: `python manage.py migrate`, run inside `shop` once it is up

### `db`
- pulls `postgres:16`, healthchecked with `pg_isready -U app -d app`; its data is a volume that is fresh for every preview
- not opened: only the other services reach it
- bind mounts: none

## Each line, and where it was read

| what | tier | read from |
|---|---|---|
| `preview.compose` = .openfactory/preview.compose.yml | inferred | manage.py, .python-version:1 |
| `preview.expose.shop` = 8000 | inferred | manage.py |
| `preview.data.shop` = `python manage.py migrate` | inferred | manage.py |
| service `shop`: built with the drafted `.openfactory/preview/shop.Dockerfile` | inferred | manage.py, .python-version:1 |
| `shop` receives `DJANGO_DEBUG` | observed | .env.example:2 |
| `shop` receives `DATABASE_URL` | inferred | requirements.txt:2 |
| service `db`: `postgres:16`, healthchecked, a fresh volume for every preview | inferred | requirements.txt:2 |
| `.openfactory/preview/shop.Dockerfile`: `FROM python:3.12-slim` | inferred | .python-version:1 |
| `.openfactory/preview/shop.Dockerfile`: installs with `pip install -r requirements.txt` | observed | .openfactory/project.yaml:3 |
| `.openfactory/preview/shop.Dockerfile`: starts `python manage.py runserver 0.0.0.0:8000` | inferred | manage.py |

## Questions only your team can answer

- how is `shop` seeded with data a person can look at? `python manage.py migrate` makes the tables and leaves them empty.

## For the registry, not this file

The application reads these names and their values are secrets or per-environment, so they are never written into a file. The operator names them for previews:

- `DJANGO_SECRET_KEY` (.env.example:1) — `DJANGO_SECRET_KEY` looks like a secret (its name says it holds a secret): `openfactory project set-preview acme-shop --env shop=DJANGO_SECRET_KEY=<WORKER_NAME>`

## Notes

- `shop` builds from the whole repository (context `.`), so any change to it rebuilds `shop`
- Django (`ALLOWED_HOSTS`): for a named preview domain, add it to the application's allowed hosts — a preview forwards the browser's own `Host`, `shop--acme-shop--<n>.<preview domain>`.
- `db` is drafted with throwaway values (`app`/`app`) for a store only its own preview can reach; the address each service receives is written beside it — confirm your application reads that name.

---

These files live under `.openfactory/` so they never collide with your own; move them and repoint `preview.compose` if you prefer. Nothing here is in effect until a person merges it, and the factory never merges it.
