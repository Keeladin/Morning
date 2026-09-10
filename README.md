# Morning

Morning is a standalone operational reporting product for shift-based engineering and mining operations.

It takes the established supervisor reporting workflow and turns the captured shift record into deterministic management reporting, operational history and later reliability/KPI views. Morning owns its application runtime, database, identity, configuration, reporting and recovery lifecycle.

Morning does not require Atlas to run.

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

Home is the supervisor landing page and sits outside the report-capture stages. It provides access to recent submitted TMM reports, private supervisor messaging and a shared Notice Board for broadcast notices.

When starting a TMM report, the supervisor selects one or more active crews for that shift. Attendance combines the active personnel assigned to those selected crews. Machine-activity personnel assignment remains TMM-scoped and may select any active registered TMM person.

Brothers Keeper is a mandatory report stage. Its contribution is captured once and projected into the review/summary, submitted historical report and WhatsApp-ready report output. Demo Mode provides the same guided workflow without creating operational reports.

Supervisors capture once at source. Submitted structured records then drive the downstream reporting views. See `docs/Morning_TMM_Supervisor_Workflow_Change_2026-09-10.md` for the workflow-change record and acceptance criteria.

## Current implementation status

The `main` branch contains the current standalone product implementation:

- React supervisor application under `src/morning/`;
- Morning administration console for machines, personnel, crews, supervisor approval/linking, three-shift policy and daily reporting;
- standalone Starlette API under `backend/morning/`;
- Morning-owned accounts, principals, roles, signed sessions and CSRF protection;
- PostgreSQL persistence with Alembic migrations;
- the established draft → staged capture → submit workflow;
- three-shift operating model: Morning 06:00–14:00, Afternoon 14:00–22:00, Night 22:00–06:00;
- deterministic WhatsApp, detailed 24-hour and compact meeting reports;
- explicit machine-state declarations separate from engineering work intervals;
- control-room Production Delays ingestion from pasted text or PDF text-layer extraction;
- deterministic Teams-workbook cell projection;
- Docker deployment for web, API and PostgreSQL;
- backup/restore scripts and an automated rollout smoke gate in CI.

The previous `src/` fake-data design surface has been replaced as the application entry point. It is no longer the production frontend description.

## Architecture

Morning launches as a modular monolith:

```text
Browser / installable web app
            │
            ▼
      Morning web
      (nginx / SPA)
            │ same origin
            ▼
       Morning API
   (Starlette runtime)
            │
            ▼
       PostgreSQL
```

The production Compose topology is three containers:

- `web` — browser/PWA surface plus same-origin reverse proxy;
- `api` — Morning application/runtime;
- `db` — Morning-owned PostgreSQL 17.

External systems may later consume Morning through defined interfaces, but Morning remains independently deployable, operable, upgradeable and recoverable.

## Canonical data model

Morning follows one rule:

> Capture operational truth once, then derive reports, history, reliability views and KPIs from that structured record.

Authoritative typed source records are canonical. Rendered reports and workbook mappings are reproducible projections, not second sources of truth.

### Work interval vs machine state

Morning deliberately keeps these separate:

- **Engineering work interval** — when work occurred and what was done.
- **Machine state declaration** — the declared operating condition of the machine at a point in time, including carried state across handovers.
- **Control-room delay interval** — evidence taken from the Production Delays source.

A work interval is not automatically downtime.

The Teams workbook duration cells are therefore populated from control-room Production Delays intervals, not from supervisor engineering-work duration. Availability/reliability calculations remain blocked from inventing downtime until the explicit state history and denominator support them.

## Fresh production database

Morning will launch with a fresh production database.

The embedded/reference Morning database is not migrated into this product. The existing implementation is the reference for proven behaviour, workflow, terminology and validation — not a data source that must be carried forward.

**Migrate the product, not the data.**

## Run the frontend during development

```bash
npm install
npm run dev
```

Production build check:

```bash
npm run build
```

## Run the backend during development

A PostgreSQL database and the two required environment variables are needed for the full application:

```bash
python -m pip install -e ".[dev]"
export MORNING_DATABASE_URL='postgresql+psycopg://morning:password@localhost:5432/morning'
export MORNING_SESSION_SECRET='replace-with-a-long-random-secret'
alembic upgrade head
uvicorn morning.app:app --reload
```

`/healthz` remains available without the database so configuration/readiness failures can be diagnosed cleanly.

## Run the production-shaped Compose stack

Copy the example environment file and replace the placeholders:

```bash
cp .env.example .env
```

Then start Morning:

```bash
docker compose up -d --build
```

Bootstrap the first administrator:

```bash
docker compose exec api morning bootstrap-admin \
  --username admin \
  --display-name "Morning Administrator"
```

For controlled automation the CLI can read one password line from stdin:

```bash
printf '%s\n' "$ADMIN_PASSWORD" | docker compose exec -T api morning bootstrap-admin \
  --username admin \
  --display-name "Morning Administrator" \
  --password-stdin
```

The API container applies `alembic upgrade head` before starting.

For production, set `MORNING_ENV=production` and publish the web service through HTTPS. Production sessions use Secure cookies. PostgreSQL should not be exposed to the public network.

See `docs/deployment.md`.

## Reporting projections

Morning currently exposes:

- per-shift WhatsApp-ready text;
- detailed 24-hour departmental report;
- compact department-meeting summary;
- Teams workbook cell projection at:

```text
GET /api/morning/admin/reports/{reporting_date}/teams
```

The Teams projection preserves the established workbook coordinates while keeping the workbook downstream of canonical Morning data.

## Control-room ingestion

The standalone admin API supports manual ingestion without depending on an external mail service:

```text
POST /api/morning/admin/control-room/ingest
GET  /api/morning/admin/control-room/observations?reporting_date=YYYY-MM-DD
```

The ingestion path accepts pasted extracted text or a base64 PDF payload, applies the configured control-room machine allowlist, and stores the resulting observations as their own evidence source.

Mailbox automation can be added later around the same deterministic extractor; it is not required for Morning to operate.

## Backup and restore

Two backup paths are provided:

- `scripts/backup.sh` / `scripts/restore.sh` for hosts with matching PostgreSQL client tools;
- `scripts/compose-backup.sh` / `scripts/compose-restore.sh` for the standard Docker Compose deployment, using the PostgreSQL 17 tools inside the database container.

Example for the Compose deployment:

```bash
BACKUP="$(scripts/compose-backup.sh)"
scripts/compose-restore.sh "$BACKUP"
```

The restore path performs a clean restore and reapplies Alembic to head. See `docs/backup-restore.md` before using it against operational data.

## Rollout gate

`scripts/rollout_smoke.py` walks the real HTTP boundary through a clean CI/staging deployment:

1. administrator login;
2. machine, crew and personnel configuration;
3. supervisor registration, approval and personnel link;
4. Morning (06:00–14:00), Afternoon (14:00–22:00) and Night (22:00–06:00) shift capture;
5. attendance, safety, machine work, machine state and other activity;
6. submission and WhatsApp projection;
7. control-room Production Delays ingestion;
8. complete 24-hour management report;
9. Teams workbook projection;
10. backup → deliberate database mutation → restore verification.

The smoke script refuses to mutate data unless `MORNING_SMOKE_ALLOW_MUTATION=1` is explicitly set. It is intended for a clean CI or staging database, **not for an operational production database**.

## CI gates

GitHub Actions currently checks four independent surfaces:

- backend lint + tests against PostgreSQL 17;
- frontend production build;
- production Docker image builds;
- full production-shaped Compose rollout smoke plus backup/restore drill.

A change that passes unit tests but breaks the actual deployment path should therefore fail the rollout job.

## Initial production scope

TMM is the first rollout scope.

Construction and Mining remain validation scopes so the core model does not accidentally become hard-coded around one fleet-maintenance use case. They do not block the first release and Morning will not build a generic cross-domain workflow engine before operational need earns it.

## Product principles

- Capture once; use many times.
- Preserve the established supervisor workflow while allowing deliberate operationally-driven evolution.
- Structured source records are authoritative.
- Reports and KPIs are deterministic projections where the truth can be calculated.
- Work intervals, machine state and control-room delay evidence are separate concepts.
- Standing is not automatically engineering downtime.
- Historical records remain traceable to their source.
- Deactivation does not erase historical identity.
- Personnel utilization is a resource-planning measure, not a performance score.
- Morning remains independently deployable and recoverable.
- Complexity must earn its place.

## Delivery posture

The immediate target is controlled operational rollout, followed by normal production use and refinement.

The remaining work should therefore be judged against rollout value: operational configuration, complete supervisor-to-management behaviour, reporting correctness, recovery, observability and the reliability/KPI projections that can be supported by trustworthy source data.

## Authoritative implementation contract

See:

- `docs/Morning_Extraction_Contract_2026-08-28.md`
- `docs/ADR-000-extraction-classification.md`
- `docs/Morning_TMM_Supervisor_Workflow_Change_2026-09-10.md`
- `docs/Morning_Three_Shift_Day_One_2026-09-10.md`

The 28 August extraction contract governs the standalone foundation. The 10 September workflow and three-shift records document later operationally-driven evolution and supersede older staged-workflow or two-shift descriptions where they differ. Additional product-direction material remains under `docs/` as historical design context.
