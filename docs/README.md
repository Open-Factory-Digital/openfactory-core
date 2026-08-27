# The documentation, and which page is for you

**One path, a set of references, and the design rationale behind them.** There used to be three
places that looked like a beginning — this README, a quickstart and an "onboarding a project"
page — and a reader had to guess which one was current. There is now exactly one.

## The path

| | |
|---|---|
| **[ONBOARDING.md](ONBOARDING.md)** | **start here.** The guided session: the deployment's environment, the project, your stack, your context, the box proof, the first ticket — and where the agents, the models and the multi-repo shape become yours |
| [setup/github.md](setup/github.md) | the GitHub side, when the path sends you there: the App screen by screen, a personal account's board token, a board by hand |
| [setup/azure-devops.md](setup/azure-devops.md) | the all-Microsoft side: the PAT, the board states, registration by clone URL |

## The references — read when you need one, not in order

| | |
|---|---|
| [STATUS.md](STATUS.md) | **what works today**, and what does not. Read before deciding anything |
| [reference/cli.md](reference/cli.md) | every command, what it does, when you need it |
| [reference/configuration.md](reference/configuration.md) | the manifest, the registry, the environment — who owns which setting |
| [reference/product-role.md](reference/product-role.md) | switching on the product owner: context repo, per-person tokens, the release gate |
| [project.yaml.example](project.yaml.example) | the annotated manifest |
| the `openfactory-aws` add-on package | putting this on a cloud: the reference deployment and its walkthrough ship with that package, outside this tree — [STATUS.md](STATUS.md) lists what it carries |
| [agents.md](agents.md) | the agent roles the platform runs — what each one can do, what it cannot, and where to change it |
| [adr/](adr/) | why it is built this way — 41 decision records |

## What is not in the core arrives as an add-on

The core ships GitHub, Azure DevOps and Jira. Anything else a deployment wants on a provider
axis — another forge, a cloud box, a chat channel — is a separate package that declares its rows
in the `openfactory.adapters` entry-point group (`<axis>.<kind> = package:builder`, the role axis
as `role.<name>`) and is `pip install`ed into the worker image before the rebuild; nothing in this
repository is edited, an unknown kind still refuses by name, and a built-in row wins a
collision. The two the maintainers build are `openfactory-aws` (a cloud box, its metrics table,
its session store and the reference deployment) and `openfactory-slack` (a chat channel).
**Neither is on a public index**: they are built as wheels from the private tree and installed
beside the core by whoever runs the deployment, so a refusal that names one is telling you which
wheel your deployment needs — not a command to type. Anyone may write the same row themselves;
the entry point is the whole contract. **[writing-an-addon.md](writing-an-addon.md) is the
walkthrough** — two files, four commands, and the traps; [core/07-extensibility.md](core/07-extensibility.md)
is the mechanism and the reasoning in full, and [STATUS.md](STATUS.md) lists which paths of this
tree leave with the two packages above.

## Everything else here is for whoever builds on it

[core/](core/) is the core's design rationale — what it is trying to become, where the
core/engine/application line falls, and how a running install gains a provider it did not ship
with. `operations.md`, `architecture.md` and `engineering-lessons.md` are how the platform is run
and why it is built the way it is. None of them is the path a first installation follows, which
is the only reason they are listed last; a contributor is better served by reading them than by
reading the path.
