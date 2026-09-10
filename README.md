# Morning

Morning is a standalone operational reporting product for shift-based engineering and mining operations.

The current development phase is focused on moving the proven Morning supervisor workflow into an independently deployable production system with its own persistence, authentication, configuration, reporting and operational history.

This is not a disposable prototype. The current implementation is the production foundation of Morning.

## Established supervisor workflow

Operational use has evolved the TMM supervisor workflow. The current TMM sequence is:

```text
Home
    ↓
Start / continue report
    ↓
Attendance
    ↓
Brothers Keeper
    ↓
Safety
    ↓
Machine activity
    ↓
Other activities
    ↓
Review & submit
```

Home is the supervisor landing page and sits outside the report-capture stages. It provides access to the five most recent submitted TMM reports, private supervisor messaging and a shared Notice Board for broadcast notices.

Attendance remains crew-scoped. Machine-activity personnel assignment is TMM-scoped and may select any active registered TMM person.

Brothers Keeper is a mandatory report stage. Its contribution is captured once and must be projected into the review/summary, submitted historical report and WhatsApp-ready report output.

See `docs/Morning_TMM_Supervisor_Workflow_Change_2026-09-10.md` for the agreed implementation and acceptance criteria.

## Production direction

Morning will launch as a standalone modular monolith with:

- Morning-owned application/runtime
- PostgreSQL as the production database
- Alembic-managed schema migrations
- Morning-owned users, roles and authorization
- supervisor and administration interfaces
- structured shift capture
- deterministic reporting and projections
- operational history
- machine-state continuity
- reliability and KPI views derived from source records
- independent deployment, backup, restore and upgrade lifecycle

Morning must be able to operate without Atlas. External systems may later integrate with Morning through defined interfaces, but Morning's runtime and operational data remain self-contained.

## Green launch decision

Morning will launch with a **fresh production database**.

The existing Morning database is not being migrated into the standalone product. The current implementation is the reference for proven behaviour, domain rules, terminology, validation and workflow — not a source database that must be carried forward.

The production database therefore starts with a clean schema and fresh configuration for users, crews, personnel, machines and shift policy. Operational history begins at production cutover.

**Migrate the product, not the data.**

## Capture once; derive everything else

Morning's core data principle is:

> Capture operational truth once, then derive reports, history, reliability views and KPIs from that structured record.

Authoritative typed source records remain the canonical truth. Reports, summaries and analytical views are projections of those records rather than independent sources of truth.

## Machine activity and machine state

Morning keeps two concepts separate:

- **Work interval** — when engineering activity occurred and what work was performed.
- **Machine state** — the declared operating condition of the machine at a point in time and across handovers.

A work interval is not automatically downtime. Genuine downtime, availability and reliability calculations must be based on explicit machine-state truth rather than inferred from engineering activity duration.

## Initial production scope

TMM is the first production scope.

Construction and Mining remain validation scopes used to test that Morning's core operational-reporting model is not accidentally hard-coded around fleet maintenance. They do not block the first production rollout, and Morning will not build a generic cross-domain configuration engine before those scopes earn the abstraction.

The organisational model should retain a clean hierarchy seam so operational units can later contribute upward into appropriate management views without requiring the first release to solve every cross-domain aggregation rule.

## Product principles

- Capture once; use many times.
- Preserve the established supervisor workflow while allowing deliberate operationally-driven evolution.
- Structured source records are authoritative.
- Reports and KPIs are deterministic projections where the truth can be calculated.
- Work intervals and machine state are separate concepts.
- Standing is not automatically engineering downtime.
- Historical records remain traceable to their source.
- Deactivation does not erase historical identity.
- Personnel utilization is a resource-planning measure, not a performance score.
- Morning remains independently deployable and recoverable.
- Complexity must earn its place.

## Delivery posture

The immediate goal is a controlled operational rollout, followed by normal production use and refinement.

The implementation priority is therefore:

1. standalone persistence and migrations;
2. Morning-owned identity, roles and authentication;
3. extraction of the proven runtime/API/workflow;
4. machine-state capture and cross-shift continuity;
5. deterministic 24-hour reporting;
6. reliability/KPI projections and drill-down;
7. further operational scopes once the production foundation is proven.

## Run the current frontend

```bash
npm install
npm run dev
```

Production-style build check:

```bash
npm run build
```

## Authoritative implementation contract

See:

- `docs/Morning_Extraction_Contract_2026-08-28.md`
- `docs/Morning_TMM_Supervisor_Workflow_Change_2026-09-10.md`

The 28 August extraction contract governs the standalone foundation. The 10 September TMM workflow change records later operationally-driven product evolution and supersedes the older staged-workflow description where the two differ.

Additional product-direction material remains under `docs/` as historical design context.
