# Engineering baseline (framework-owned, non-negotiable)

These are the platform's standing coding standards, injected into every job's agent
context. They exist because each was a real production failure once — encoded here so
we never repeat it. They bind the coding agent AND the platform's own code.

## 1. Never crash silently — always produce the contract output
Any code that other code depends on for a result MUST return that result, even on
failure. Wrap fallible work in try/except and emit a well-formed result with an error
state — never exit with no output and never let an exception become the only signal.
(A worker that reads "no result" cannot tell "it failed" from "it never ran".)

## 2. Handle errors explicitly
try/except around every I/O, subprocess, network call, and parse. Check subprocess
return codes; distinguish "not found" from "the lookup itself failed" (a failed lookup
is unknown, not absence). Prefer a visible failed/held state **with a reason** over a
swallowed exception. A broad `except` must log the cause, never hide it.

## 3. Every side effect must be idempotent
Anything that can be retried — open a PR, push a branch, create a tag, post a comment,
launch a task — must be safe to repeat: find-or-create, `push --force-with-lease` on
your own dedicated branch, existence-check before a create, a guard/marker before a
non-idempotent notification. Assume every operation runs at least twice.

## 4. Credentials: mint at use, never cache; never bake
Short-lived tokens (e.g. GitHub App installation tokens ~1h) must be obtained at the
moment of use, not once at start — a long job outlives them. Read credentials from the
provider chain so they auto-refresh; never bake a secret into an image, commit, or log.

## 5. Redact secrets in all output
Every error message, log line, and exception string passes through a redactor before it
is printed or raised. Tokens in URLs, keys, passwords — never in the clear.

## 6. Validate and sanitize all external input
Path components (an issue number is `^\d+$`, never a path), URLs (check the scheme —
reject `javascript:`), sizes, and shapes. Data from a user, a board, or the agent is
untrusted at the boundary.

## 7. Escape everything rendered to a UI
Never inject untrusted or agent-produced text into HTML/`innerHTML`/`href` without
escaping. Use `textContent` or an escaper; validate URL schemes.

## 8. Bound everything — no unbounded loop, wait, or retry
Every loop and wait has a deadline (wall-clock, not an accumulator that a zero interval
defeats). Never busy-loop. When timeouts nest, the inner budget must be strictly less
than the outer, and long durable waits belong in the durable engine (a workflow
timer/signal), never in an external scheduler that might not be running.

## 9. Secrets at rest: salted KDF + constant-time compare
No unsalted hashes, no `==` on a secret. Use a salted KDF (argon2/bcrypt) and
`hmac.compare_digest`.

## 10. Identities must be collision-proof
Idempotency keys and resource tags: hash, don't truncate; include a run/attempt
discriminator so a reused number (e.g. a re-opened ticket) can never collide with an
old one.

## 11. Stay in scope — one ticket, one change
Implement exactly what the ticket's objective and acceptance criteria ask for, and
nothing else. Do not bundle in unrelated refactors or "while I'm here" fixes — they
escape review and hide real changes. If you hit friction that isn't the ticket (a flaky
environment, a boot error from ambient credentials, a pre-existing bug), **report it in
the PR body and leave it for its own ticket** — never silently weaken production
behavior (e.g. broadening an `except` to swallow a real error) to get your change
through. A test/CI environment problem is never fixed by making prod code less strict.

## 12. Never silence a quality gate to pass it
Do not add a suppression comment — `# pragma: no cover`, `# noqa`, `# type: ignore`,
`# nosec` — to make a gate go green. A silenced gate proves nothing. New code must be
genuinely covered, typed, and clean. If a line is truly untestable, that is a review
conversation, not a unilateral pragma: the platform detects suppressions added in a diff
and forces the change to human review regardless of the gates.

> When you touch code that violates one of these, fix it in passing. When you write new
> code, satisfy all of them by default — they are not optional.
