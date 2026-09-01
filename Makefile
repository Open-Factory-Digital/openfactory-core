# OpenFactory — convenience targets; `make help` lists them.
# The develop and onboard targets are the core's and run in any checkout. The four CLOUD targets
# (tfvars, secrets-help, deploy, panel-url) drive the reference deployment on ONE cloud, which
# ships in the `openfactory-aws` add-on package together with the `infra/` tree they read. Where
# that tree is present a NEW deployment goes `make tfvars` → edit it → put the secrets in SSM
# (the package's docs/DEPLOYMENT.md §4) → `make deploy`; where it is absent each of the four
# refuses BY NAME and says what to install, rather than half-running against paths that are not
# there.
.DEFAULT_GOAL := help
SHELL := /usr/bin/env bash

TFVARS ?= $(CURDIR)/infra/terraform/deployment.tfvars

# ── the cloud add-on's paths, and the refusal that stands in for them ─────────
# `infra/` and `addons/` are rows of docs/STATUS.md's excluded-paths table: the public repository
# has neither. Until 2026-08-26 the four recipes below simply ran against them, and the failures
# were the quiet kind — `make tfvars` printed `cp: infra/terraform/deployment.tfvars.example: No
# such file or directory`, echoed "created …" over that failure and exited 0; `make panel-url`
# printed a `cd` error and exited 0; `make deploy` sent the reader back to `make tfvars`. A recipe
# that reports success after a failed command is worse than one that is missing, and no recipe in
# this file does it any more: every command whose result is announced is chained to the
# announcement with `&&`.
#
# THEY STAY LISTED HERE rather than moving into the package, and that is a decision. `make help`
# is the map a reader of the public tree gets, and a target that silently vanished would leave a
# stranger with no way to learn that the reference deployment exists or where it lives — while a
# refusal that names the package is a signpost. `infra/` also sits at the repository ROOT, not
# inside the package, so a package-local Makefile would have to reach `../../infra/` and couple
# the package to its position in somebody else's tree. So each of the four refuses BY NAME with
# the package to install — the same answer `channel: slack` and `OPENFACTORY_SANDBOX=fargate`
# already give on a deployment that does not carry their add-on.
CLOUD_PACKAGE := openfactory-aws
CLOUD_TFVARS_EXAMPLE := infra/terraform/deployment.tfvars.example
CLOUD_TERRAFORM := infra/terraform
CLOUD_DEPLOY := infra/deploy.sh
CLOUD_GUIDE := addons/openfactory-aws/docs/DEPLOYMENT.md

# $(call cloud-or-refuse,<path>) — the FIRST line of every cloud recipe. Names the missing path
# and the package that carries it, and exits non-zero so nothing after it runs.
cloud-or-refuse = if [ ! -e "$(1)" ]; then \
	  echo "make $@: $(1) is not in this tree." >&2; \
	  echo "  The reference deployment on one cloud — its terraform, its deploy script and its" >&2; \
	  echo "  walkthrough — ships in the $(CLOUD_PACKAGE) add-on package." >&2; \
	  echo "  pip install $(CLOUD_PACKAGE)   (or use a checkout that carries $(1))" >&2; \
	  exit 1; fi

.PHONY: help
help: ## show these targets
	@grep -hE '^[a-zA-Z0-9_-]+:.*?## ' $(MAKEFILE_LIST) \
	  | awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-16s\033[0m %s\n", $$1, $$2}'

# ── develop ──────────────────────────────────────────────────────────────────
.PHONY: install test lint check
install: ## install the package + dev tools (+ the add-on packages under addons/, where they exist)
	pip install -e '.[dev]'
	@for d in addons/*/; do if [ -f "$$d/pyproject.toml" ]; then pip install -e "$$d"; fi; done

test: ## run the test suite
	python -m pytest -q

# ── shellcheck, and why it is not a CI-only step ─────────────────────────────
# `install.sh` is the first thing a stranger runs and the one artefact in this repository that no
# Python test can execute. It belongs in `make lint` rather than in a job of its own, because
# `tests/test_ci_runs_what_we_run.py` exists precisely to stop CI and the gate drifting apart —
# it derives the roots the suite covers and holds CI to them, after the two differed by one word
# (`ruff check openfactory/ tests/` here, `… addons/` there) and the add-on packages went unlinted
# where it counted. A CI-only shellcheck step would re-create that gap in a new place: green on
# every laptop, and the only machine that ever checked the script would be the one nobody runs
# locally.
#
# LOCAL FIRST, THEN THE CONTAINER, THEN A REFUSAL BY NAME. shellcheck is a Haskell binary, not a
# Python dependency, so `make install` cannot provide it and most machines do not have it —
# measured on this one, 2026-08-30: absent, with no sudo available to install it. Silently
# skipping would be the worst of the three outcomes: `make lint` would pass while checking
# nothing, which is the "absence read as compliance" shape this codebase has been bitten by more
# than once. So it runs whichever it can find and refuses BY NAME when it can find neither,
# naming both ways to fix it — the same shape the four cloud targets above use for `infra/`.
SHELLCHECK_IMAGE := koalaman/shellcheck:stable
SHELL_SCRIPTS := install.sh docker/install-addons.sh scripts/collect-release-assets.sh

shellcheck-or-refuse = \
	if command -v shellcheck >/dev/null 2>&1; then \
	  shellcheck -s sh $(1); \
	elif docker info >/dev/null 2>&1; then \
	  docker run --rm -v "$(CURDIR):/mnt" $(SHELLCHECK_IMAGE) -s sh $(addprefix /mnt/,$(1)); \
	else \
	  echo "make $@: shellcheck is not installed, and no Docker daemon is available to run it." >&2; \
	  echo "  These are POSIX sh and CI checks them either way — to check them here, do one of:" >&2; \
	  echo "    install shellcheck   (apt/brew/dnf install shellcheck, or https://www.shellcheck.net)" >&2; \
	  echo "    start Docker         (this then runs $(SHELLCHECK_IMAGE))" >&2; \
	  exit 1; \
	fi

lint: ## ruff over the package and the suite; shellcheck over the shell scripts that ship
	ruff check openfactory/ tests/ $(wildcard addons)
	@$(call shellcheck-or-refuse,$(SHELL_SCRIPTS))

check: test lint ## test + lint (what deploy runs first)

# ── run the code in THIS checkout instead of the published images ────────────
# `docker compose up -d` PULLS `ghcr.io/open-factory-digital/openfactory-*` — that is the
# installer's path and it is what almost every user wants (ADR-0043). A contributor wants the
# opposite, and the difference is one profile plus one flag, which is exactly the kind of
# incantation that ends up half-remembered in three documents.
#
# THE PROFILE IS NOT OPTIONAL AND THAT IS THE WHOLE REASON THIS TARGET EXISTS. `base-image` and
# `sandbox-image` sit behind `profiles: ["build"]` so the installer's `up` does not build a
# multi-GB box it could have pulled; without `--profile build` this command would quietly build
# the worker and the panel ALONE and leave the box image absent, which surfaces at the first
# ticket rather than here. `openfactory preflight` names that state, but a build command that
# creates it by omission is a trap this file can simply not set.
.PHONY: build
build: ## build the images from THIS checkout and run them (contributors; users just `up -d`)
	@if [ ! -f .env.compose ]; then \
	  echo "make $@: no .env.compose in this directory." >&2; \
	  echo "  The stack reads its environment from that file and compose refuses a missing" >&2; \
	  echo "  --env-file rather than starting with none." >&2; \
	  echo "  openfactory init            (or: cp .env.compose.example .env.compose)" >&2; \
	  exit 1; fi
	docker compose --env-file .env.compose --profile build up -d --build

# ── bootstrap a new deployment (the cloud add-on) ────────────────────────────
.PHONY: tfvars secrets-help
tfvars: ## create deployment.tfvars from the template (needs the openfactory-aws tree)
	@$(call cloud-or-refuse,$(CLOUD_TFVARS_EXAMPLE))
	@if [ -f "$(TFVARS)" ]; then echo "$(TFVARS) already exists — edit it, don't clobber."; \
	else cp "$(CLOUD_TFVARS_EXAMPLE)" "$(TFVARS)" \
	     && echo "created $(TFVARS) — fill it in (app id, installation, temporal, brand)."; fi

secrets-help: ## the SSM put-parameter commands for this deployment (needs the openfactory-aws tree)
	@$(call cloud-or-refuse,$(CLOUD_GUIDE))
	@echo "Put these in THIS account's SSM (see $(CLOUD_GUIDE) §4):"
	@echo "  /<prefix>/bot-app-private-key   (the GitHub App .pem)"
	@echo "  /<prefix>/temporal-api-key      (Temporal Cloud API key)"
	@echo "  /<prefix>/claude-oauth-token    (Claude Code token)  and/or  /<prefix>/agent-tokens"
	@echo "  /<prefix>/panel-token           (invent a long random string)"
	@echo "  /openfactory/slack-token-<project>     (Slack bot xoxb- token, ONE per project's workspace;"
	@echo "                                   OPTIONAL. Map it in slack_bot_tokens in deployment.tfvars,"
	@echo "                                   e.g. { SLACK_BOT_TOKEN = \"/openfactory/slack-token-<project>\" })"

# ── deploy (the OTA) ─────────────────────────────────────────────────────────
.PHONY: deploy panel-url
deploy: ## build + roll THIS deployment (AWS creds + a deployment.tfvars + the openfactory-aws tree)
	@$(call cloud-or-refuse,$(CLOUD_DEPLOY))
	@if [ ! -f "$(TFVARS)" ]; then echo "no $(TFVARS) — run 'make tfvars' and fill it in first." >&2; exit 1; fi
	OPENFACTORY_TFVARS="$(TFVARS)" $(CLOUD_DEPLOY)

# `terraform` is checked BY NAME too. `cd $(CLOUD_TERRAFORM) && terraform output …` failed
# identically whether the directory was missing, the binary was absent or nothing was deployed
# yet, and answered all three with "(deploy first)" — a remedy that sends two of those three
# readers to fix the wrong thing.
#
# That message names the PACKAGE and not its guide's path, deliberately: it prints on the way
# past the refusal above, and a path under `addons/` is one more thing a reader who got here
# without the add-on cannot open.
panel-url: ## print the panel URL, after a deploy (needs the openfactory-aws tree)
	@$(call cloud-or-refuse,$(CLOUD_TERRAFORM))
	@command -v terraform >/dev/null 2>&1 \
	  || { echo "make $@: terraform is not installed — the $(CLOUD_PACKAGE) walkthrough §1 lists what a deploy needs." >&2; exit 1; }
	@url=$$(cd "$(CLOUD_TERRAFORM)" && terraform output -raw panel_apprunner_url 2>/dev/null) \
	  && [ -n "$$url" ] && echo "$$url" \
	  || echo "no panel_apprunner_url in the terraform state — deploy first."

# ── onboard a project ────────────────────────────────────────────────────────
# usage: make onboard NAME=myapp DIR=~/Projects/myapp REPO=yourorg/myapp
.PHONY: onboard
onboard: ## register + scaffold a project (NAME=, DIR=, REPO=)
	@if [ -z "$(NAME)" ] || [ -z "$(DIR)" ] || [ -z "$(REPO)" ]; then \
	  echo "usage: make onboard NAME=myapp DIR=~/Projects/myapp REPO=yourorg/myapp"; exit 1; fi
	openfactory project add "$(NAME)" "$(DIR)" --repo "$(REPO)"
	openfactory project init "$(NAME)"
	openfactory conformance "$(NAME)"
