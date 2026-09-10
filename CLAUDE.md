# Morning

Morning is a standalone operational reporting product for shift-based engineering and mining operations.

## Repository boundary

Canonical server path: `/srv/morning/app`

Atlas is a separate product at `/home/jaco/Projects/atlas-agent`.

When working in this repository:
- Modify Morning only unless explicitly instructed otherwise.
- Do not edit Atlas as part of Morning work.
- Do not introduce runtime, database, deployment, or code dependencies on Atlas.
- Atlas may consume Morning later only through an explicit API/MCP boundary.
- Morning must remain independently deployable, operable, recoverable, and testable.

## Product invariants

- Capture operational information once; derive reporting, history, rollups, and KPIs from canonical typed records.
- Supervisors capture shift reports; management roles consume progressively wider rollups and drill-downs.
- Operational hierarchy and System Administration are separate concerns.
- System Admin is outside the operational hierarchy.
- Machine state is separate from engineering work intervals; engineering work is not automatically downtime.
- Preserve source provenance and auditable submission/correction semantics.
- Prefer deterministic extraction, calculations, validation, and verification where possible.
- The operational timeline is a projection of canonical records, not a substitute for them.

## Development discipline

Implement against Morning's own architecture, tests, database, deployment, and documentation. Keep the supervisor workflow simple and avoid adding steps unless the operational responsibility genuinely requires them.
