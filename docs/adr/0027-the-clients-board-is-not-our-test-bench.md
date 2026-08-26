# ADR 0027 — The client's board is not our test bench

- **Status:** **Accepted** (2026-07-29)
- **Date:** 2026-07-29
- **Related:** ADR-0019 (the product role), ADR-0026 (what the client reads), ADR-0005 (the
  post-merge cycle).

## Context

The product agent recommended closing 11 diagnostic-endpoint cards, saying it had counted twelve
equivalents already shipped. The product owner asked for verification before authorising. The
verification confirmed the number — and found something larger than the decision that prompted it.

### What is shipped in the client's product

The production client's `app/main.py` has **twelve** diagnostic endpoints. **Eleven return a
constant and check nothing**:

```python
@app.get("/heartbeat")      def heartbeat():      return {"beat": True}
@app.get("/pulse")          def pulse():          return {"pulse": "ok"}
@app.get("/beacon")         def beacon():         return {"beacon": "ok"}
@app.get("/healthz/ready")  def healthz_ready():  return {"ready": True}
…
```

`/healthz/ready` answers `{"ready": true}` without touching a database, S3 or any dependency. It is
a readiness probe that lies by construction.

### Where they came from — the titles say so

| closed card | endpoint | title |
|---|---|---|
| #209 | `/heartbeat` | Add GET /heartbeat endpoint **(live autonomy demo)** |
| #212 | `/pulse` | Add GET /pulse endpoint **(panel e2e test)** |
| #215 | `/beacon` | Add GET /beacon endpoint **(panel e2e test)** |
| #220 | `/healthz/build` | Add GET /healthz/build endpoint **(two-stage local test)** |
| #200 | `/ping2` | Add GET /ping2 endpoint **(cleanup demo)** |

And the 11 still open were more of the same — **#207 "Add GET /autonomy endpoint (autonomy
proof)"**, **#222 "Add GET /healthz/ping2 (per-role model check)"**.

**These are tests of the PLATFORM.** They were written as the client's product tickets, went through
the entire pipeline — planning, execution, review, merge — and **landed in the production code of an
accounting product**. Eleven files of debt somebody will have to remove, in a repository that is not
ours.

Only `/healthz` has a legitimate origin (#51, *"[Infra] Real health/readiness endpoint
(dependency-aware /healthz)"*). And even that one **did not deliver what the card asked for**: the
card asked for dependency awareness, what exists is a fixed `{"status": "ok"}`. The card was closed
anyway — which is the same class of defect as ADR-0025: closed because the board agreed with itself.

### Why it happened

There was no bad decision; there was an **absent boundary**. Proving the factory works needs a real
ticket, in a real repository, crossing the real pipeline. The only repository to hand was the
pilot's. Every test became a ticket, every ticket became code, and nobody asked whose product was
receiving it.

It is the same root as several defects already catalogued here: **the platform had the information
and did not use it.** We knew perfectly well that `/autonomy (autonomy proof)` was nobody's request.
Nothing in the system asked.

## Decision

### 1. A test-bench project, separate, with its own repository

The factory's smoke tests run against a dedicated project in the registry — our repository, our
board, our channel. It exists to be dirty: trivial endpoints, disposable tickets, a polluted
history. None of that is a problem **in the right place**.

The pilot becomes what it should have been from the start: **a client**, not a bench.

### 2. A project declares whether it accepts test work

`registry.yaml` gains `accepts_test_work: false` as the **default**. A project without the key
receives no test ticket, and the factory refuses loudly instead of degrading in silence.

A safe default, because the failure being corrected is exactly that of assuming permission.

### 3. The refusal happens at CREATION, not at review

Failing early is cheap: a test ticket in a project that does not accept them is refused when it is
created, not after spending a whole pipeline and a merge. A test that only fails after the merge is
not a stop, it is a report.

### 4. Cleaning up what already leaked

- **11 cards closed** on 2026-07-29 (#168, #175, #179, #189, #192, #194, #198, #202, #205, #207,
  #222), each with a comment explaining its origin and the overlap. The trail is left on the board,
  not here — whoever opens the card a year from now needs the reason next to it.
- **Pending and declared:** remove the eleven published stub endpoints from the product, leaving
  only `/healthz`; and give **#51** the *dependency-aware* health check it specified. That is work
  in the client's product, so **it enters through the product role's door** (requirement → approval
  → card) and not by a decision of ours — which is exactly the boundary this ADR exists to
  establish.

## Consequences

**Good.** The client's board holds only their product again. The factory gains a place where it can
be tested without embarrassing anybody, and testing stops carrying a reputational cost. And the
pilot starts showing honest numbers: 11 of the "delivered" cards were not product work.

**Costs and risks, declared.**
- **One more project to maintain** — repository, registry, credentials. That is the price, and it is
  low next to dead code in a client's product.
- **Testing against a toy repository proves less.** A bench project does not have the complexity of
  the real thing, so some failures will only appear at a real client. The honest mitigation: the
  bench is there to prove the *pipeline*; behaviour in real code is still proved by real product
  work — which is now the only kind that gets there.
- **The boundary depends on configuration.** If somebody sets `accepts_test_work: true` on a client
  board, all of it comes back. The default protects; the discipline is not automatic.
- **Eleven endpoints stay live** until the cleanup goes through the product process. Declared
  deliberately: a shortcut here would repeat the very mistake this ADR corrects.
