# Selected shift report state investigation — 12 October 2026

## Baseline and existing work

Investigated main at `72010f11f1d5e8e918ecf6e4fb384a9d23babd87` (4 October).
The prior changes already provide exact date/shift selection, server-confirmed
submission receipts, auditable corrections, and stale offline draft recovery.
No open pull requests were found at the start of this investigation.

The database identifies each report by supervisor, reporting model, date and
shift. Explicit selection already ignores the current clock, resumes that
slot's draft, and returns that slot's submission for correction. No database,
runtime, shift policy, or date conversion changes are required.

## Confirmed screen defects

1. While one shift is open, a successful background synchronization of a
   different date or shift displays “Received by Morning” in the open report's
   status strip. The report replacement was conditional, but the receipt text
   was unconditional. A stale receipt can also replace a newer correction.
2. A selected report shares the query for “latest draft”. Forcing a background
   refetch replaces an explicitly selected submission or older draft with the
   server's latest draft, or with no report. This is a reproducible query-state
   defect, **not evidence that an ordinary reconnect alone triggers it**:
   the application's `networkMode: 'always'` disables automatic reconnect
   refetching by default, and focus refetching is explicitly disabled.

Component tests exercise the real Workflow, StartReport and API/cache code with
mocked HTTP responses. Seven regression cases fail against the unmodified
baseline: TMM and Construction submission refetches, an older draft refetch,
unrelated shift/date/owner receipts, and an old receipt during correction.
The exact browser session underlying the original complaint was not available.

## Fix

- Pin report queries to the selected report ID, scoped to supervisor and model.
  Use latest-draft discovery only before a selection is established.
- Apply report callbacks and receipt messages only to the active supervisor,
  model, date and shift, rejecting receipts older than the active revision.
- Keep a pending local snapshot available while its server ID is unresolved.
- Scope form/review state to the report slot and revision, preserving unsaved
  form choices when an offline ID is replaced by its server ID.
- Preserve selection, correction/history, and pending submission behavior.

## Validation

- Backend suite: **122 passed**, including seven added clock-boundary cases.
  Executed from an isolated checkout against a newly created test database and
  restricted test role. Both were removed after the run. Production records
  were not used or modified.
- Frontend suite: **35 passed**, including date/shift selection for both models,
  background receipts/refetches, corrections, offline recovery and ID remapping.
- TypeScript and frontend/backend lint checks.
- Production frontend build and mobile Playwright checks: login/PWA manifest
  and offline cold-start/report creation. Browser checks run against an isolated
  preview with mocked API responses, not the production application.
- Existing night resolution, Sunday-night/Monday grouping, offline replay,
  correction version history and stale revision rejection are covered by the
  suites. Their production implementations are unchanged.

## Production evidence and deployment boundary

Read-only inspection on 12 October found the canonical checkout at
`/srv/morning/app` on `72010f1`, with an existing local compose-file modification
left untouched. The web container started on 4 October at 07:24:40 UTC; the API
container started at 07:21:52 UTC.

The public homepage references `index-By2Av4qt.js`. Its running-container SHA-256
is `f76e899e020b6dd4ac3439f7ee47f7b97f0f0a4fa9872057ecc57509cbd117c0`, identical
to a clean frontend build of the baseline checkout. The deployed
`routes/supervisor.py`, `store.py` and `runtime.py` also match the baseline
byte-for-byte. The API's internal `/healthz` reported `application_ready: true`.

This establishes that the inspected production code includes the prior
4 October fixes and the newly identified defects. It does not establish which
service-worker version an individual supervisor's phone has cached.

This investigation does **not** deploy the new patch, restart services, modify
production reports, or change the separate `/dev` design preview. The patch is
prepared for review and a subsequent deployment decision.
