# ADR 0043 — The distribution is a published image, and one compose file both installs and builds

- **Status:** **Accepted** for the shape (published images on GHCR, one compose file carrying both `image:` and `build:`, the tracked default `main` against a pinned install) (addendum 2026-08-31: the base layer is a FOURTH published image — the v0.1.0 run proved that the release itself pulls it, so "nothing pulls it" was false)
- **Date:** 2026-08-30
- **Relates to:** ADR-0040 (the core runs on the client's own machines — this is how it *arrives*
  there), ADR-0037 (the box: the image the worker launches on the host daemon is one of the three
  published here), ADR-0022 (provider seams — nothing on this path widens a port for a registry).

## Context

Measured 2026-08-30, against `main`:

- GHCR carried **nothing** for this organisation; `releases` was `[]`; PyPI `openfactory` was a
  **404**; npm `openfactory` was a **404**.
- Every service in `docker-compose.yml` declared `build:` and no `image:`.
- `README.md` §Quickstart was **eight commands**, of which three were traps: pick a 3.12+
  interpreter (`docs/ONBOARDING.md` §0 spends a full page on that alone, because stock
  Debian/Ubuntu and Homebrew macOS ship an older `python3`, and the venv builds happily and dies
  four commands later at `pip install`); one `sudo` line, Linux-only, silently absent from the
  macOS path; and `docker compose up -d --build`, which builds three images from source.

That last one is the expensive one and it is not an installer problem. `docker/worker.Dockerfile`
runs a `node:20-slim` stage that `npm install -g`s four agent CLIs before Python is reached.
Multi-minute and multi-gigabyte, on the first command a stranger types. **No script can make
`--build` fast.** A one-line install is not reachable by writing a better script; it is reachable
only by having something to pull.

The obvious way to arrange a pull is a second, "release" compose file that names images while the
tracked one builds. That is the defect this codebase names most often — the truth about one stack
living in two places — and it has a specific cost here: two guards read the literal path
`docker-compose.yml` (`test_two_projects_do_not_share_a_box.py` and `test_the_docs_do_not_drift.py`),
so a second file would be judged by nothing and would drift first.

## Decision

**1. The distribution is three images on GHCR**, multi-arch `linux/amd64` + `linux/arm64`:

| image | from | why it exists |
|---|---|---|
| `openfactory-worker` | `docker/worker.Dockerfile` | the worker **and** the panel run this |
| `openfactory-sandbox` | `docker/sandbox.Dockerfile` | the worker spawns it through the host's Docker socket and **never builds it** |
| `openfactory-cli` | `docker/cli.Dockerfile` | `python:3.12-slim` + the wheel, no Node. Runs `preflight` and `init` in seconds *while the worker image downloads behind the interview* |

GHCR rather than Docker Hub: public images cost nothing, are not rate-limited for anonymous pulls
the way Docker Hub is, live beside the source, authenticate with the token the workflow already
has — and are plain OCI, so moving off it is a tag prefix rather than a migration.

`base-python` was built and **deliberately not published**, on the argument that nothing pulls
it — it is the layer `docker/sandbox.Dockerfile` is built `FROM`, a build stage spelled as a
compose service because Compose has no other way to order one build before another. **That
argument was wrong and the addendum below records what disproved it.**

**2. One compose file carries both `image:` and `build:` on every service it builds.**

```
docker compose up -d                          → pulls the published image (the installer's path)
docker compose --profile build up -d --build  → builds and tags it as that same image:
```

The tracked file **is** the release asset, verbatim — not generated, not rewritten with a version
substituted in. `base-image`, `sandbox-image` and `cli` sit behind `profiles: ["build"]` so `up -d`
does not build a multi-gigabyte box image it could have pulled.

**3. The tracked default is `main`; every install is pinned.**
`image: ghcr.io/open-factory-digital/openfactory-worker:${OPENFACTORY_VERSION:-main}`. `main` is
rebuilt on every push to `main`, so a contributor who has written no `.env.compose` gets the branch
they are working on. `install.sh` writes an explicit `OPENFACTORY_VERSION=vX.Y.Z`, so **no user is
ever on a floating tag**, and no `latest` tag is published at all — `latest` is the one moving tag
somebody can pin to while believing they have pinned.

**4. Pinned assets come from the GitHub Release, never from the domain.** `docker-compose.yml`,
`.env.compose.example` and a `SHA256SUMS` over them are attached to the release; `install.sh`
fetches from `releases/download/<tag>/` and verifies. A static host can serve a file and can
checksum nothing.

## Consequences

**The venv leaves the first-run path.** Steps 2–4 of the old quickstart existed to run step 5,
whose entire output is a text file. `openfactory init` now runs in `openfactory-cli` with
`-u "$(id -u):$(id -g)"`, so the 0600 `.env.compose` belongs to the person who ran the installer.
`docs/ONBOARDING.md` §0's interpreter page becomes the **contributor's** path, which is what it
always was.

**`worker` lost `depends_on: sandbox-image`, and that is forced rather than chosen.** Measured
2026-08-30: Compose refuses a project outright when a profile-less service depends on a profiled
one — `service "app" depends on undefined service "builder": invalid compose project` — so
`docker compose up -d` would exit non-zero before starting anything. What that row bought (a
missing box image is an error at `up`, not a job that parks an hour later) moves to `openfactory
preflight`, which asks the **host** daemon whether the image is present and answers `docker pull
…`. That is wider than the row it replaces: the row could only protect somebody who typed
`--build`.

**A contributor who runs `docker compose up -d --build` without `--profile build` now gets a stack
with no box image.** This is the one regression this decision accepts. It is named by `preflight`
with its remedy, and `make build` exists so the documented path carries the profile.

**Two sets must stay equal.** Every image the compose file names must be one the release publishes
and vice versa — a published image nothing references is as wrong as a referenced image nothing
publishes, and the second fails silently for months.
`tests/test_every_image_the_compose_file_names_is_one_the_release_builds.py` holds both directions.

**A security team can enumerate what they are running.** The worker mounts the host's Docker
socket, which is root-equivalent on the host; that trade is stated in the README. It is only a fair
trade if "what is in this image" has an answer that is not "read our Dockerfile and trust us", so
every image ships an SBOM and a build-provenance attestation.

## What would reverse this

- **A registry that stops being free or plain.** The images are plain OCI and no code names GHCR
  outside `docker-compose.yml` and `release.yml`; a move is a tag prefix. If GHCR added a pull
  limit that a first-run install could hit, that alone would justify a mirror.
- **A pull that stops being faster than a build.** The premise is measured, not assumed. If the
  worker image ever lost its Node toolbox — the thing that makes the build multi-minute — the
  build path would be cheap again and the second half of this decision (published images at all)
  would be worth re-deciding, though the first half (one file, two behaviours) would not.
- **Compose gaining the ability to enable a dependency's profile.** The `depends_on` removal above
  is a workaround for a refusal measured on 2026-08-30. If Compose changes that, the row should
  come back — it catches at `up` what `preflight` catches only when somebody runs it.
- **A second architecture that `TARGETARCH` cannot cover.** The multi-arch build is cheap because
  `worker.Dockerfile` already branches. An architecture needing a separate Dockerfile would make
  the matrix a maintenance surface rather than a row.


## Addendum (2026-08-31): the base layer is a fourth published image

**MEASURED, BY A FAILED RELEASE.** The v0.1.0 run (33396474816) published `openfactory-worker` and
`openfactory-cli` and failed on `openfactory-sandbox`:

```
ERROR: failed to solve: openfactory-python:latest: failed to resolve source metadata for
docker.io/library/openfactory-python:latest: pull access denied, repository does not exist
or may require authorization
```

`release` needs `images`, so no GitHub Release was created and no assets were published — which
means `install.sh`, whose whole job is resolving a pinned tag out of that Release, was broken end
to end by an image nobody thought was part of the distribution.

**THE DECISION ABOVE SAID "NOTHING PULLS IT". Something does: the release's own sandbox build.**
The original text is left standing rather than edited, because it is the reasoning that was
actually used and this is what it cost.

**THE MECHANISM IS THE BUILDER, NOT THE ORDER OF THE STEPS.** The workflow already built the base
and `--load`ed it into the runner's daemon, and that step reported success.
`docker/setup-buildx-action` creates a **docker-container** driver builder: BuildKit runs in its
own container, with its own content store, and cannot read the host daemon's image store at all.
An unqualified `FROM` is then resolved as `docker.io/library/…`. Reproduced on a laptop the same
day — byte-identical error on the docker-container driver, exit 0 on the `docker` driver, which is
exactly why Compose had never hit it.

**WHAT CHANGED.** The base is published as `ghcr.io/open-factory-digital/openfactory-base` in a job
the image matrix waits for, and `docker/sandbox.Dockerfile` names it through an
`ARG OPENFACTORY_BASE_IMAGE` whose default is that registry reference. One file still serves both
readers: the release passes the tag it is building, and `docker-compose.yml` overrides the ARG with
a **named build context** (`service:base-image`) so a contributor builds base-then-sandbox with no
registry, no tag and no daemon store in between.

**A SECOND DEFECT THIS FIXED ON THE WAY, and it would have shipped a wrong image rather than
failing.** `docker compose build` compiles the file into ONE bake plan and builds every target
concurrently — `depends_on` orders container startup and says nothing about builds. The sandbox was
resolving its `FROM` while the base was still building, and only ever succeeded because an earlier
run had left the tag in the local store. The named context is a dependency bake understands, so the
contributor path is now ordered by construction rather than by luck. Measured on a daemon holding
neither image: `docker compose --profile build build base-image sandbox-image` exits 0.

**WHAT WOULD REVERSE THE ADDENDUM.** A builder that can read the local image store — the `docker`
driver — would make the publication unnecessary again, and it is what Compose already uses. It
cannot build multi-arch, which is why the release does not use it; if that changed, the base could
go back to being a private layer.
