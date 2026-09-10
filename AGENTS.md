# Agent Instructions — Morning

This repository is Morning.

Canonical server path: `/srv/morning/app`

Atlas is a separate product at `/home/jaco/Projects/atlas-agent`.

- Work only inside Morning unless explicitly instructed otherwise.
- Do not modify Atlas as part of Morning work.
- Do not introduce runtime, database, deployment, or code dependencies on Atlas.
- Any future Atlas↔Morning integration must use an explicit API/MCP contract.
- Morning must remain independently deployable, operable, recoverable, and testable.

Follow `CLAUDE.md` for the full Morning product and architecture invariants.
