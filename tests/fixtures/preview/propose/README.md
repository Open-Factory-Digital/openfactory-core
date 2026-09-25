# Preview proposals: repositories, what the factory drafts for each, and what the pinned compose CLI makes of it

Each scenario directory holds a repository as the factory finds it (`tree/`), the files
`openfactory preview propose` writes into it (`expected/`, byte for byte, beside the pull
request's body as `expected/pull-request.md`), and the canonical document `docker compose config`
wrote for the tree WITH the draft applied (`canonical.json`) — recorded, so
`tests/test_a_preview_is_proposed_from_what_the_repository_says.py` round-trips every draft through
the reader and admission without needing Docker.

| scenario | tree | proposed with | expected |
|---|---|---|---|
| `s2` | a compose file of published images only; a root `Dockerfile` that `EXPOSE`s the port `api` publishes | `--accept` | the block, and an override adding `build:` to `api` (context `.`) |
| `s3` | one `Dockerfile` (`EXPOSE 8000`), `psycopg` in `requirements.txt`, a `.env.example` with a secret | `--accept` | a compose file (`api` from `..`, `db` healthchecked), the block |
| `s4` | `api/` and `web/` Dockerfiles; two Dockerfiles in `worker/`; one two levels deep; a Next.js `web` whose `.env.example` names the API twice | `--accept` | `api`, `web`, `db`, `redis`; both URL names; the other Dockerfiles asked about |
| `s5` | Django with no Dockerfile: `manage.py`, `.python-version`, the manifest's `setup:` | `--accept` | a Dockerfile anchored to `manage.py`, its `.dockerignore`, a compose file, the block with `data:` |
| `s8` | one `Dockerfile` and a Helm chart | nothing (every line is observed) | a compose file and the block; the chart noted, never read |
| `s9` | a compose file whose `api` reaches a managed database | `--accept` | the block, and an override with a fresh `db` standing in for it |

The scenario names are the design's (#265, §9) and name nothing else. What runs a merged draft is
the deployment's preview runtime — an adapter on the `preview` axis, the compose row by default —
and nothing in this directory is ever built by the tests.

The project name is `acme-api` (S2, S3, S9), `acme-shop` (S4, S5) or `acme-orders` (S8), and the
repository `acme/<the same last word>`. `OPENFACTORY_PREVIEW_DOMAIN` is unset, so a host reads
`<service>--<project>--<n>.<preview domain>`.

## Recorded with the pinned plugin, v2.32.4

The version `docker/cli.Dockerfile` copies. The tree, with `expected/` copied over it, is mounted
where a preview's base checkout would be, `/pv/base/app`, and read with the files the expected
block's `preview.compose` names, in that order:

```sh
docker run --rm -v "$TREE:/pv/base/app:ro" --entrypoint /docker-compose \
  docker/compose-bin:v2.32.4 -f /pv/base/app/.openfactory/preview.compose.yml \
  --project-directory /pv/base/app/.openfactory --env-file /dev/null \
  config --no-interpolate --format json > canonical.json
```

S2 and S9 name the client's own file first (`-f /pv/base/app/compose.yaml -f
/pv/base/app/.openfactory/preview.compose.yml`, `--project-directory /pv/base/app`).

What the recordings showed on v2.32.4, and the drafter relies on:

- An override's relative paths resolve against the FIRST file's directory, so S2's override says
  `context: .` for the repository root; a drafted file that is the only one resolves against its
  own directory, `.openfactory/`, so the root is `..` there.
- Every draft is accepted by the CLI as written: no key it does not know, no path it refuses.
- The project's name is the first file's directory, so a draft under `.openfactory/` is the
  project `openfactory`, and its volume `db-data` is written as `openfactory_db-data` — compose's
  own name, which admission tells apart from a name the client gave.

The expected files and the recordings move together: change what the drafter writes, and rewrite
`expected/` from the drafter and re-record `canonical.json` from it, saying which line changed.
