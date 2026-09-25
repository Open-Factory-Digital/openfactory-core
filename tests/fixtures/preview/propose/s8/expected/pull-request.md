A preview of `acme/orders`: a compose file drafted from its Dockerfile, and the `preview:` block. **It was read from this repository, not invented** — every line below cites the file it came from, and the fields nothing could answer were left out rather than guessed.

**Not built.** Nothing in this pull request was built or run, on any machine. `openfactory preview propose acme-orders --prove`, run where the deployment's preview runtime is, builds the base branch with this draft applied, once, on the deployment's own daemon — and takes it down.

## What merging this lets the factory do

Anyone the panel lets into this project can start this on the factory's daemon, on demand, and open it under the preview domain.

### `orders`
- built from this repository: the whole repository (`.`), with `Dockerfile`
  - `FROM golang:1.22 AS build` — Dockerfile:1
  - `FROM gcr.io/distroless/static-debian12` — Dockerfile:6
  - `ENTRYPOINT ["/orders"]` — Dockerfile:9
- opened on port 8080, as `orders--acme-orders--<n>.<preview domain>`
- bind mounts: none

## Each line, and where it was read

| what | tier | read from |
|---|---|---|
| `preview.compose` = .openfactory/preview.compose.yml | observed | Dockerfile:1 |
| `preview.expose.orders` = 8080 | observed | Dockerfile:8 |
| service `orders`: built from the whole repository (`.`) with `Dockerfile` | observed | Dockerfile:1 |

## Notes

- `chart/` exists; the core reads no chart — this draft is a development shape for the deployment's own daemon.
- `orders` builds from the whole repository (context `.`), so any change to it rebuilds `orders`

---

These files live under `.openfactory/` so they never collide with your own; move them and repoint `preview.compose` if you prefer. Nothing here is in effect until a person merges it, and the factory never merges it.
