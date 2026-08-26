---
name: Bug report
about: Something the factory did, that it should not have done
labels: bug
---

## What happened

The behaviour you saw. If a job was involved, its ticket and the state it ended in.

## What you expected instead

## How to reproduce it

The smallest sequence that produces it. If it needs a project, say which axes it uses
(tracker / board / forge / agent / sandbox) — most defects in this codebase turn out to be
about one axis and are invisible on the others.

## What the platform said

```
the panel's card, the job's note, or `openfactory doctor <project>` — whichever is closest
```

## Environment

- OpenFactory: commit or version
- How it runs: `docker compose` / installed package
- Coding agent: Claude Code / Codex / Kimi / OpenCode
- Vendors: e.g. GitHub Issues + Projects, or Azure DevOps end to end
