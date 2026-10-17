# ADR 0057 — Who may act is one decision the core's policy makes, and a production approval is a person, not a password

- **Status:** Proposed (design only — no code changes with this ADR; a maintainer accepts it in review)
- **Date:** 2026-10-13
- **Implements:** #690. Finishes C-26 (#55), which moved *who is asking* into the core and left
  *may they* half-moved.
- **Relates to:**
  - ADR-0016, acting from Slack: **amended**. Its allowlist becomes a role grant (D3), and its
    "identity + password" production boundary becomes D4's identity-backed approval.
  - ADR-0038, the platform is complete: **amended**. "The prod gate stays the panel with a
    password" becomes "the prod gate is a named person holding the approver role, with a fresh
    proof of who they are" (D4).
  - ADR-0039 §2, every action takes who asked: **completed**. `Actor.admin` stops being the
    transport's answer (D1).
  - ADR-0025, delivery closes with the client: the client's release is answered by the same
    decision (D4, "the client's yes").
  - ADR-0001 D-12, production requires a human action: unchanged in intent, changed in mechanism.

## Context

C-26 (#55) built the identity axis (`openfactory/identity/`) and a policy module
(`openfactory/policy/authz.py`) whose docstring says *"May this person do this — decided once, in
the Core"*. The identity half is done. The policy half is not: today the answer to *may they* is
assembled in five places, and they disagree.

The facts this record rests on, read from the code at `da345623`:

| where | what it decides | how |
|---|---|---|
| `api/app.py::_actor_of` | `Actor.admin` for the panel | `admin=True` for every caller that got past `require_auth` — the panel token, a person's token, a board token, a product token, an OIDC login, an invitation's session |
| `api/app.py::_scopes_of` | `Actor.scopes` for the panel | the subject's groups intersected with `actions.SCOPES = {floor, product}`; no recognised group means **unscoped**, i.e. everywhere |
| `cli.py` | `Actor.admin` for the CLI | `admin=True`: a shell on the host outranks every gate |
| `policy/authz.py::may` | Slack's floor allowlist and the product role's writers | `project.admins` for scope `factory`, `project.product.admins` for scope `product`; empty means nobody |
| `actions/catalog.py`, rows that re-check | the product rows that write (`may_act` at four sites) and `baseline` | a second check *inside* the row, because `needs_admin` is true for everybody on the panel |
| `actions/catalog.py::_approve_prod`, `_promote` | production | a login and a password typed into a form, checked by `approvals.verify_approver` against `~/.openfactory/approvers.json` (or `OPENFACTORY_APPROVERS`), and an allowlist from `OPENFACTORY_PROD_APPROVERS`, else the manifest's `prod_approvers`, else, for a project with no manifest on disk, **every login in the password store** |

Four consequences follow, each one a defect somebody already hit or wrote down:

1. **Two scope vocabularies.** `policy/authz.py` calls the operator's area `factory`;
   `actions/base.py` and `identity/local.py::BOARD_GROUP` call it `floor`. They have not collided
   only because nothing calls `authz.may` with the action layer's scope.
2. **`admin` means "got in".** On the panel it is true for everyone, so every row that genuinely
   needs a narrower answer re-asks it inside the row (`catalog.py:2533` says so in as many words).
   A row that forgets is open to every credential the panel admits.
3. **The production approver is not the person who is signed in.** The panel knows who is asking
   (a token row, an invitation, an OIDC login) and then asks for a *second* identity — a login
   and a password from a separate store — that nothing ties to the first. An operator signed in
   as Ana can approve as Bruno with Bruno's password, and the audit line records Bruno.
4. **The password store is an identity provider nobody declared.** `approvers.json` holds
   scrypt hashes (and legacy unsalted SHA-256) for logins, has its own CLI verbs, its own env
   override, its own failure sentences and its own certify control (`C-APPROVERS`) — a third
   identity mechanism beside `local` and `oidc`, with no single sign-on, no MFA, no revocation
   beyond editing a file, and a fallback that makes every login in it an approver of every project whose manifest is not
   on disk while `OPENFACTORY_PROD_APPROVERS` is empty.

## Decision

**What this record decides, and what decides the rest.** This record decides the rules in D1–D6.
It does not restate, row by row, what each catalog action allows today: the parity test in the
implementation does (D6). Where a sentence here and today's behaviour disagree on something D6
does not list as a change, today's behaviour stands and the sentence is the defect. Row-level cases
found in review become cases of that test, not amendments to this record.

### D1 — The decision point: `policy.may(subject, action, project, on=card)`, asked once, by `perform`

**One function answers *may they*, and the action layer's `perform` is its only caller on the
request path.**

```python
policy.may(subject: Subject, *, action: ActionSpec, project, on: Card | None = None) -> Decision   # Decision(allowed, why)
```

- **Transports hand over a `Subject`, never a decision.** The panel, the CLI and every channel
  add-on resolve a `Subject` through the identity axis (or, for the CLI,
  `Subject(id=<shell login>, via="cli")`, D3) and stop there. `Actor.admin` and `Actor.scopes` are removed from what a transport may set;
  `Actor` carries the `Subject` and `perform` asks the policy. This is the rename ADR-0039 §2
  promised: the parameter was carried from the start so this would not be a migration.
- **`perform` asks before it runs, every time.** The current ordering is kept — scope first, then
  authority — but both answers come from `policy.may`, and a refusal carries the policy's `why`
  as today's `DENIED_SCOPE` sentences do.
- **No row re-checks.** `may_act` inside product rows, `baseline`'s re-check and
  `_prod_allowlist` become declarations on the row (D3's `needs`), and a guard test fails the suite
  if a catalog row imports `policy` or `may_act`. The re-checks exist because `admin` lied; once it
  does not, a second check is a second answer, and a second answer is how this record became
  necessary.
- **The card is a fact the policy is given, not one a row looks up.** The product area has always
  had one answer that depends on *which card*: the person who asked for a card may send it back,
  withdraw it, correct it at the gate and accept its change (`module.py::may_send_back`,
  `withdraw_card`, `correct_card`, `accept_change`; in the conversation `engine.py` and
  `confirm.py::_may_say_yes`), and when they say a delivery did not work, the defect staged on it
  is theirs to confirm (`confirm.py::_their_delivery_did_not_work`). Those checks sit below the
  row today, beside `may_act`. Under
  this record they move into the policy as a relation: a row that acts on a card passes it
  (`on=card`), D3 names *the requester of this card*, and the policy answers from the card's
  recorded requester. A row that acts on no card passes nothing, and a relation asked without its
  card refuses. The guard test that forbids a row importing `policy` therefore also forbids it
  comparing a card's requester itself.
- **The policy reads grants; it does not store them.** `authz.py`'s rule stands: *who may act on a
  project is that project's business*. Grants live on the project in the registry, and
  deployment-wide grants live with the deployment's identity configuration (D3).
- **Unchanged rules, now stated once:** an unknown scope or role is refused, never defaulted; an
  anonymous subject (`Subject.known` is false) holds exactly the role its credential's own row
  grants in D6 (the shared panel token `admin`, the shared board token `operator`, the shared
  product token `requester`) and nothing else: no grant that names a subject id or a group can
  match it, because it has neither. It never approves (D4), never invites a person and never
  grants a role: each of those acts records who did it, and an anonymous subject has no one to
  record. An anonymous subject whose
  credential grants no role is refused anything above `viewer`; empty grants
  mean nobody; the policy never raises and a grant source it cannot read refuses with
  `unavailable` (a 503 on the panel), never with "you are nobody".

`SYSTEM` (the platform acting on nobody's behalf) is the one actor that does not pass through the
policy, and it is not reachable from a transport — as today.

### D2 — The scope names: `floor` and `product`, defined once, in `policy`

**There are two areas, and their names are `floor` and `product`.**

- `floor` — jobs, the board, merges, the engine, the release gate: the operator's console.
- `product` — the product role: requirements, their drafting, sign-off, withdrawal and queuing.

`floor` wins over `factory` because it is the name on the wire: it is the group a board
credential already asserts (`BOARD_GROUP`), the group an OIDC map already targets, and the value
`docs/reference/the-front-end-api.md` publishes per route. Renaming the policy's private constant
breaks nobody; renaming the published one breaks every deployment's group map.

`SCOPES` is defined in `openfactory/policy/` and imported by `actions` and `identity` — the policy
owns the vocabulary because it is the module that must refuse an unknown word. `authz.FACTORY` is
kept one release as an alias of `floor` that logs `OPENFACTORY_AUTHZ_SCOPE_RENAMED` when read.

**Production is not a third scope.** A scope answers *which area may this credential enter*; a
production release happens in both areas (`approve_prod` on the floor, the client's yes in the
product) and is a level of authority within them, which is what a role is.

### D3 — The role vocabulary: six roles, a closed set, granted per project or per deployment

**A role is a named bundle of (area, authority). The set is closed and lives in the core.** A
deployment grants roles; it cannot invent one, for the same reason it cannot invent a scope.

| role | area | may | today's nearest equivalent |
|---|---|---|---|
| `viewer` | both, read only | read every page and stream its area serves; act on nothing | the reads ADR-0016 leaves open to a channel |
| `requester` | `product` | every read a viewer has in `product`, plus talk to the product role, file a ticket or a defect, note a fact (`product_file_ticket`, `product_file_defect`, `product_note_fact`), start, stop and rebuild previews (`preview_start`, `preview_stop`, `preview_rebuild`); and, **on a card they asked for**, send it back (`product_adjust`), withdraw it, correct it at the gate and accept its change; and discard an attachment in their own conversation — as today | a product token / product invitation whose holder is not on `product.admins` |
| `product-owner` | `product` | everything a requester may, on every card, plus every product row that re-checks `may_act` today — accept, drop, close, queue, reorder, break down, propose, baseline, confirm a capability, record a decision, file or discard an attachment for the room, promote, release a card the client has said works (ADR-0025) — and let a preview run its change's own shape (`preview_own_shape`) | `project.product.admins` |
| `operator` | `floor` | resume, skip, ack, merge, adjust, discard, enable, scan, diagnose | `project.admins` (Slack), a board token / `people invite --board` |
| `approver` | `floor` | approve a production release (`approve_prod`, `promote`) — and nothing else | `prod_approvers`, `OPENFACTORY_PROD_APPROVERS`, `approvers.json` |
| `admin` | both, plus the deployment's people, roles and installation | everything an operator **and** a requester may, every read a viewer has in both areas, and the vouched powers below on any card; plus invite people, grant `viewer`, `requester`, `operator` and `admin`, and change the installation — **never what only a product-owner may, never grant `approver` or `product-owner`, and never approve production** | the panel token and its per-person rows, an invitation with no group, the OIDC catch-all, the CLI |

- **The product rows are divided by a rule, not by a list.** `product-owner` is every product row
  that re-checks `may_act` today; `requester` is every product row that does not; the rows that
  combine `may_act` with *the card's requester* are the third case, answered by the relation below;
  and a row whose answer depends on one of its parameters is the fourth, declaring its need per
  value. `product_discard_attachment` is that fourth case, and its need follows the conversation
  the row resolves to, not the parameter that asked for it: a private conversation needs
  `requester`, the room needs `product-owner`, so a caller with no conversation of its own, which
  resolves to the room, needs `product-owner`. (Today the row decides by the parameter, which lets
  such a caller discard from the room; that is a defect on `main`, fixed outside this record, and
  the parity test takes the fixed behaviour.) The parity test reads the four cases from the code,
  so a row added later falls into one of them without anybody editing this table.
- **Vouched, as today.** A row that vouches answers yes, on any card, to a subject that holds
  `operator` and may enter `product`: an `admin`, or an `operator` who is also a `requester` — a
  subject in both a floor group and a product group (`api/app.py::_scopes_of`). A vouched subject
  may send back, withdraw, correct at the gate and accept the change on any card
  (`catalog.py::_product_accept_change` and its siblings compute `vouched` this way today). The
  conversation's own yes stays the requester's: `confirm.py::_may_say_yes` asks without `vouched`,
  and so does the policy there.
- **The requester of a card is a relation, not a role.** It is granted by asking for the card, holds
  on that card alone, and is checked by the policy from the card's recorded requester (D1). On a
  project that sets `release_by_requester` (`contracts/project.py:467`,
  `docs/configuration.md:950`), the relation extends to releasing that card through the
  conversation, exactly as `engine.py:2501` allows today; the setting stays the operator's and off
  by default.
- **Each catalog row declares the least role it needs** (`needs="operator"`), replacing the
  boolean `needs_admin`. `scope` stays on the row and must agree with the role's area — a test
  asserts every row's pair is one the table above can satisfy, so a row cannot be unreachable by
  construction.
- **`admin` is a requester, not a product-owner.** It keeps the product-area access every panel
  credential has today — previews, filing, notes, adjustments, reads — because those rows never
  re-checked and the panel let every `admin=True` caller through. Accepting, dropping, closing,
  queuing and releasing a client's requirements, and letting a preview run its change's own shape,
  stay with `product-owner` grants, exactly as `product.admins` guards them today:
  `product/module.py::may_act` keeps the product scope "deliberately separate from the factory
  floor's, because the client who may approve a requirement and the operator who may skip a job are
  different trusts and always were". Holding `admin` never implies `product-owner`, and an admin
  cannot grant it (below).
- **`approver` is never implied.** Not by `admin`, not by `operator`. Releasing production is the
  one act whose blast radius the floor cannot bound (ADR-0016), and separation of duties is the
  first question an enterprise security review asks.
- **No grant is self-issued, for any role, and none comes from an anonymous subject.** A grant
  whose grantee is the granter's own `Subject.id` is refused with a sentence naming the rule;
  an anonymous subject never grants (D1). The CLI is not an exception: its granter is its shell
  login, held to the same rules as anyone's.
- **No verb grants `approver` or `product-owner`, under any identity kind.** A rule over who
  grants whom stops one hop and never more: under `local` an admin who may invite can mint
  identities, so an invitee can grant their inviter and two invitees each other; under an identity
  provider, which decides who a person is but not who is an `admin`, two admins can grant each
  other, and on an upgraded install every subject no group map covers is an `admin` (D6). Those two
  roles therefore come only from places the deployment's admins do not control: the registry's
  `roles:`, written by whoever owns the host, and the identity provider's group map
  (`OPENFACTORY_OIDC_GROUPS`), written in the deployment's environment by whoever owns the host,
  over groups whose members the directory's owner decides. Both are shown with their source. The grant verb refuses the two
  roles under every kind, naming those two paths.
- **No catalog row writes a grant.** A guard test asserts that no row writes `roles:`,
  `product.admins`, `project.admins`, a manifest's `prod_approvers`, `OPENFACTORY_OIDC_GROUPS` or
  `OPENFACTORY_PROD_APPROVERS`, so the barrier still holds once the installation verbs become rows
  that `admin` reaches (#741).
- **The CLI's `people invite --by` goes** (`cli.py::people_invite`): it vouched as whatever it was
  typed. The CLI vouches as its shell login, like every other inviter. `env rehearse --by` stays:
  it records who approved a spend (ADR-0048), which is not a grant.
- **Grants name subject ids or groups.** `authz.may` already matches either; that stays, so an
  OIDC deployment grants a role to a directory group and never lists a person.
- **Where grants live.** Per project, a `roles:` map on the registry entry
  (`roles: {operator: [...], product-owner: [...], approver: [...]}`). Per deployment, the
  identity configuration: a token row's role (`OPENFACTORY_PANEL_TOKENS` keeps meaning `admin`,
  `OPENFACTORY_BOARD_TOKENS` `operator`, `OPENFACTORY_PRODUCT_TOKENS` `requester`), an invitation's
  role, and the OIDC group map, whose right-hand side accepts a role name
  (`OPENFACTORY_OIDC_GROUPS="eng-leads=operator,release-board=approver"`). A per-deployment grant
  holds on every project; a per-project grant holds on that project alone.
- **The CLI is `Subject(id=<shell login>, via="cli")`**, holding `admin` on every project — written
  in the table rather than implied by `admin=True` at three call sites — and `product-owner` only
  where its login is granted, as `may_act` decides today: the product rows that write already ask
  `may_act` with the shell login, and refuse it unless `product.admins` lists that login. The one
  row that lets the CLI past that check today, `preview_own_shape` (`catalog.py::_a_product_admin`),
  is a narrowing D6 names. It does not hold `approver` (D4); its old-way approval lasts through D5
  release 1, like the panel's.

### D4 — Production approval is identity-backed, with a step-up hook

**The person who approves a production release is the person the identity axis says is asking,
they must hold `approver` on that project, and they must have proved who they are recently.**

- **The manifest narrows, never grants.** A project's `prod_approvers`, in its own repository,
  grants nothing: an approver of that project holds `approver` from `roles:`,
  `OPENFACTORY_PROD_APPROVERS` or the group map, and, when the manifest names anyone, is one of
  them. That is today's two-party shape: the repository says who, the host proves it. As today,
  while `OPENFACTORY_PROD_APPROVERS` is set the manifest is not read (`catalog.py::_prod_allowlist`).
- **No second identity.** `approve_prod` and `promote` lose their `approver` and `password`
  parameters. The approver recorded on the card, the tag and the audit line is `Subject.id` —
  the signed-in person — and nothing a caller types can change it.
- **Anonymous never approves, nor, in the end, does the CLI.** The shared panel token (`UNKNOWN`)
  and the shared product and board tokens cannot approve, whatever they hold; each refusal names the
  fix: *"a production release is approved by a named person — sign in with your own credential"*.
  The CLI cannot approve as itself either, since no identity provider can step a shell login up.
  Today it approves with a store login and that login's password
  (`openfactory act approve_prod -P approver=… -P password=…`); that path is the panel form's twin
  and retires with it (D5): accepted with the deprecation line in release 1, refused from release 2
  with *"production is approved by a named, signed-in person — approve from the panel with your
  own credential"*.
- **The step-up hook.** The identity axis gains one optional declaration, asked by `getattr` like
  the others `IdentityProvider` lists:

  ```python
  step_up(subject: Subject, *, credential: str, max_age_s: int) -> StepUp   # fresh | needed(how) | unavailable(why)
  ```

  - `oidc` answers from the id_token's `auth_time` (and, when a deployment asks for it, `acr` /
    `amr`), and `needed` carries a login URL with `max_age` / `prompt=login`, so the buyer's own
    provider performs the re-authentication and its own MFA.
  - `local` answers `needed` with a password prompt, checked against the person's own entry in
    the people store (`identity/people.py`, salted scrypt, `hmac.compare_digest`) — the person's
    password, not a second one.
  - A provider that declares no `step_up` answers `unavailable`, and **an approval that needs a
    step-up and gets `unavailable` is refused**, never waved through.
  - The window is a deployment setting, five minutes by default. A project may set it to `0`
    (no step-up) explicitly; the panel shows that choice beside the approve button, so a
    deployment that turned it off has said so where the approver can see it.
- **A channel carries the question, never the answer.** As ADR-0016 and ADR-0038 already say: a
  channel may post *"#87 is ready for production"* with a link; the approval happens where the
  step-up can be performed. A channel add-on cannot step a person up, so it cannot approve.
- **The client's yes (ADR-0025)** is the same decision, not an exception to it: the product
  role's release asks `policy.may` for a `product-owner` on that project, and the step-up window
  for that path defaults to *the staged confirmation the person types*, which ADR-0025 already
  requires. A project that wants the client to step up too sets it, and the channel then answers
  with a link to the panel instead of releasing.

### D5 — The approver store retires, in three releases, and says so at each

**`approvers.json`, `OPENFACTORY_APPROVERS`, `OPENFACTORY_APPROVERS_FILE` and `openfactory approver
add|remove` are retired.** An approver is a person the identity axis knows, holding a role.

1. **The release that ships D1–D4.** The store is read for two things only: its logins seed
   `approver` grants (D6), and an approval presented the old way — a login and a password in the
   form or on the CLI — is still accepted **only when the login is an approver grant and the
   password matches**,
   recorded with `via=approvers-store` and logged `OPENFACTORY_APPROVERS_DEPRECATED` with the
   remedy. The fallback that made every store login an approver of every project is removed;
   the seed in D6 replaces it with explicit, visible grants. `openfactory doctor` warns while the
   store is set.
2. **The next minor release.** The login/password path, in the form and on the CLI, is refused
   with the remedy
   (*"production is approved by a named, signed-in person: sign in with your own credential;
   `approver` is granted in the registry's `roles:` by whoever owns the host, or through your
   identity provider's group map"*). The verbs print the equivalent `roles:` line and change
   nothing.
   `doctor` fails while the store is set.
3. **The one after.** The module, the verbs and the variables are deleted. `certify`'s
   `C-APPROVERS` reads the `approver` grants instead of the store and keeps its id.

### D6 — Upgrade: every existing credential maps onto a role, and nobody loses access silently

**On first start after the upgrade, the policy computes every grant from the legacy sources
below, logs the table once (`OPENFACTORY_ROLES_DERIVED`), and `openfactory roles` prints it with
the source of each line.** The legacy fields keep working as aliases — nothing has to be edited
for the upgrade to keep the doors it had open — and an explicit `roles:` entry wins over its alias.

| existing credential | becomes | scope of the grant | note |
|---|---|---|---|
| `OPENFACTORY_PANEL_TOKEN` (shared) | `admin`, anonymous | deployment | everything it did, its product-area access included (previews, `product_file_ticket`, `product_file_defect`, `product_note_fact`, `product_adjust`, reads), and no product-owner write, which it never had; it never approved production in its own name either (the approver was always the store login). Inviting a person narrows, below |
| `OPENFACTORY_PANEL_TOKENS` rows | `admin` | deployment | named; the same product-area access, and no product-owner write |
| `OPENFACTORY_BOARD_TOKEN` / `_TOKENS`, `people invite --board` | `operator` | deployment | the `floor` group, unchanged on the wire |
| `OPENFACTORY_PRODUCT_TOKEN` / `_TOKENS`, a product invitation | `requester` | deployment | the `product` group, unchanged on the wire; acts on a card only as that card's requester, as today |
| an invitation with no group | `admin` | deployment | what its session is today: unscoped, `admin=True`; the same product-area access, and no product-owner write |
| `project.admins` | `operator` | that project | ADR-0016's allowlist |
| `project.product.admins` | `product-owner` | that project | |
| manifest `prod_approvers` | no grant: it narrows who of the project's approvers may approve (D4) | that project | as today; not read while `OPENFACTORY_PROD_APPROVERS` is set, as today |
| `OPENFACTORY_PROD_APPROVERS` | `approver` | deployment | |
| `approvers.json` / `OPENFACTORY_APPROVERS` logins that today's allowlist admits for a project (the env list, else the manifest's, else every login when no manifest is on disk) | `approver` | each such project | today's fallback, made explicit and visible; release 1 of D5 only |
| OIDC: a group mapped to `product` | `requester` | deployment | |
| OIDC: a group mapped to `floor` | `operator` | deployment | |
| OIDC: a group mapped to a role name | that role | deployment | new |
| OIDC: a subject no mapped group covers | `admin` | deployment | today's panel answer, with the same product-area access and no product-owner write; the derived table flags every person who holds `admin` only through this line, `openfactory doctor` warns while any does, and `openfactory init` writes `OPENFACTORY_OIDC_DEFAULT_ROLE=viewer` for a new install |
| the CLI | `admin`; `product-owner` where its login is granted | deployment; that project | `Subject(id=<shell login>, via="cli")`: `product.admins` lists the login, as `may_act` reads it today |

**How a seeded name meets a signed-in person.** A grant matches a subject by exact equality of
`Subject.id` (or of a group name), and by nothing else: the people store's id for `local`, the
configured `OPENFACTORY_OIDC_ID_CLAIM` (a verified email by default) for `oidc`. The names D6 seeds
`approver` from (store logins, `OPENFACTORY_PROD_APPROVERS`) were never subject ids,
so some will match nobody: a store login `ana` is not the subject `ana@acme.example`. Matching on
a second claim, or loosely, would widen who counts as an approver, so it is not done. Instead
every seeded name that matches no person the identity axis knows is listed as *unmatched* in
`OPENFACTORY_ROLES_DERIVED`, in `openfactory roles` and as an `openfactory doctor` warning, each
with the fix: an `approver` line naming the subject id in the registry's `roles:`, or the
identity provider's group map.

**What narrows, and how each narrowing is said.** Exactly the narrowings below are deliberate,
each with its remedy, and none is silent; the last looks like one and is not:

- *A panel admin, or the CLI, who approved production with a store login and password*: still
  works in D5 release 1, with a deprecation line in the log, the panel and the CLI's output;
  refused with a named remedy from release 2 (the CLI's: approve from the panel with your own
  credential).
- *An approver whose seeded name is not their subject id*: still approves the old way in D5
  release 1, while `doctor`, `openfactory roles` and the derived table name them as unmatched with
  the grant that fixes it; from release 2 they approve only once that grant exists.
- *An anonymous subject inviting a person*: the shared panel token can reach `people_invite` on
  main today; from D1 it is refused, with the remedy *"an invitation records who vouched — sign in
  with your own credential (an `OPENFACTORY_PANEL_TOKENS` row, an invitation, an OIDC login)"*.
- *An anonymous subject granting a role*: no grant verb exists today, so nothing an existing
  deployment does stops; the verb is born refusing it, with the same remedy.
- *A grant to oneself, of any role*: refused with the rule's sentence; the remedy is a grant by
  another person, or a `roles:` line the host's owner writes in the registry, which
  `OPENFACTORY_ROLES_DERIVED` and `openfactory roles` show with its source.
- *A grant of `approver` or `product-owner` by a verb*: no grant verb exists today, so nothing an
  existing deployment does stops; the verb is born refusing those two roles under every identity
  kind, with the remedy *"approver and product-owner are granted in the registry's `roles:` by
  whoever owns the host, or through the identity provider's group map"*. The store's
  `openfactory approver add` (`cli.py::approver_add`) keeps writing logins through D5 release 1;
  it is a host owner's verb, so the barrier is the same.
- *`openfactory people invite --by`* (`cli.py::people_invite`): today it vouches as whatever name it is given; from D1 the
  option is gone and the CLI vouches as its shell login. The remedy, named in the error: run the
  command as the person who vouches.
- *The CLI letting a preview run its change's own shape* (`preview_own_shape`): passed today by
  `_a_product_admin`'s CLI exception; from D1 it needs `product-owner`, so the shell login needs a
  grant on that project. The remedy, named in the refusal: list the login in `product.admins`, as
  every product-owner row already requires.
- *A store login that approves through a manifest's list*: in D5 release 1 it is seeded as an
  `approver` of that project from the store, the host's, while the manifest keeps narrowing, so
  nothing changes; from release 2 the store is gone and the grant must be in `roles:` or the group
  map. `doctor` lists each such login from release 1, with that fix.
- *A store login that approved a project whose manifest names other approvers*: it never could —
  `_prod_allowlist` read the manifest first — so nothing changes.

Every other credential keeps exactly the access it had — the shared panel token,
`OPENFACTORY_PANEL_TOKENS` rows, a group-less invitation and the OIDC catch-all keep their
product-area access and gain no product-owner write. **This is a test, not a promise**: a
table-driven test builds each legacy credential above, a subject carrying both a floor group and a
product group, and a card each of them asked for and one somebody else asked for, on a project
with `release_by_requester` off and one with it on; it asks
today's code and the new policy the same question for every catalog row on each card, and fails if
the new answer differs, narrower **or wider**,
anywhere the list above does not name. A credential that gained a power it did not have is as much
a defect of the upgrade as one that lost a power it had.

## Consequences

- **One answer, one place to audit.** *Who may merge on project X* is `openfactory roles` and a
  line of code, not five front ends and four re-checks. The audit line every action already writes
  gains the role that allowed it.
- **The production approver is the signed-in person**, with the buyer's own MFA when the
  deployment uses OIDC. *"Who approved that production release"* — the question C-26 opened with —
  has a provider-backed answer, not a login somebody typed.
- **Separation of duties is a barrier the deployment's admins do not control.** No grant is
  self-issued, of any role, and no panel or CLI verb grants `approver` or `product-owner` at all,
  under any identity kind: those come only from the registry's `roles:`, written by whoever owns
  the host, or from the identity provider's group map, written in the deployment's environment by
  whoever owns the host over groups the directory's owner fills, each shown with its source; a
  project's manifest only narrows who of them may approve it. In D5 release 1 the store's `openfactory approver add` still writes logins
  D6 seeds; it is a host owner's verb, so the barrier is the same, and from release 2 it is gone.
- **A third identity store disappears**, with its hashing, its env override, its CLI verbs and the
  failure sentences of `catalog.py::_approval_denied`.
- **Costs.** The catalog's ~40 rows each change `needs_admin` to `needs`; the panel's approval
  dialog changes shape; every channel add-on that set `admin` stops compiling against the new
  `Actor` — deliberately, since an add-on that decided `admin` was the defect. Three releases of
  deprecation for the store is a real carrying cost, chosen over a release that would lock an
  existing deployment's approvers out.
- **What this does not do.** It does not add a role a deployment can define, a per-action grant,
  or time-boxed grants; it does not change *who is asking* (the identity axis is untouched apart
  from the optional `step_up`); and it does not move a capability between areas. It does not fix
  the anonymous `people_invite` that a review reproduced on main — the shared panel token can
  invite a person today — which is tracked separately; this record only decides that, once D1
  ships, an anonymous subject never invites.
