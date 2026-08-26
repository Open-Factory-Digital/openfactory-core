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

lint: ## ruff (lint) over the package, the suite and the add-on packages (where the tree has them)
	ruff check openfactory/ tests/ $(wildcard addons)

check: test lint ## test + lint (what deploy runs first)

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
