# Preview fixtures: compose files and what the pinned compose CLI makes of them

Each scenario directory holds a repository's files (`tree/`), the change's own diff (`diff.txt`,
merge base to head), and the canonical document `docker compose config` wrote for the tree —
recorded, so `tests/test_the_shape_is_read_and_admitted.py` runs admission and assembly on exactly
what the worker's compose plugin produces without needing Docker.

| scenario | tree | recorded |
|---|---|---|
| `s1` | a dev compose: web and api built here with bind mounts, db, a git-ignored `.env`, a `migrate` one-shot, `ports`, `restart`, `extra_hosts`, `labels` | `canonical.json` |
| `s2` | every service a published image; `.openfactory/preview.compose.yml` adds a `build:` for `api` | `canonical.json` (the image-only file), `canonical.override.json` (both files, merged) |
| `s9` | `api` reaches a managed database outside the preview | `canonical.json` |
| `s10` | the base's compose; `change/` holds what the change's branch says (a new privileged service, an edited Dockerfile) | `canonical.json` (the BASE only — the change's file is never read) |

## Recorded with the pinned plugin, v2.32.4

The version `docker/cli.Dockerfile` copies (`FROM docker/compose-bin:v2.32.4`). That image holds
the plugin as a static binary at `/docker-compose`, which runs on its own as the entrypoint. Each
tree is mounted where a preview's base checkout would be, `/pv/base/app`, so every absolute path in
the recordings starts `/pv/base/app/`; the tests replace `/pv` with a work directory of their own.

```sh
cd tests/fixtures/preview
docker run --rm -v "$PWD/s1/tree:/pv/base/app:ro" --entrypoint /docker-compose \
  docker/compose-bin:v2.32.4 -f /pv/base/app/docker-compose.yml \
  --project-directory /pv/base/app --env-file /dev/null \
  config --no-interpolate --format json > s1/canonical.json
```

`s2/canonical.override.json` adds `-f /pv/base/app/.openfactory/preview.compose.yml` after the
first file; `s2` and `s10` name `compose.yaml`, `s9` `docker-compose.yml`.

What the recordings showed on v2.32.4, and the code relies on:

- `--no-env-resolution` does not exist on this version ("unknown flag"), so the reader does not
  pass it; without it the output reads no env file into `environment` (2.40 measured the same).
- Relative paths in EVERY file resolve against the first file's directory, overrides included — an
  override under `.openfactory/` that says `context: ..` means the directory above the repository.
- `environment` keeps the form it was written in (a list stays a list); a bare build argument is
  dropped, a bare environment entry stays bare; `$$` stays `$$`.
- An un-named volume is written with compose's own name, `<project>_<volume>`; a named one keeps
  its name un-prefixed. A service gated by `profiles:` is written with its profiles.
- `build.dockerfile` stays relative to the context; `bind.create_host_path: true` is added to
  every short-syntax bind mount.

The fixtures move only when the pin moves: re-record every scenario with the new version and say
which of the lines above changed.
