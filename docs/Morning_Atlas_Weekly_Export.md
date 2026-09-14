# Morning Atlas Weekly Export v1

Morning owns the operational truth. Atlas receives a disposable read-only evidence package generated from submitted Morning reports.

## Trigger

The `atlas-export` service polls for completed reporting weeks. A new week becomes exportable at 04:30 Monday in the Morning timezone. The service checks the previous four completed weeks every 15 minutes by default and republishes a week only when its source fingerprint changes, so late submitted reports are picked up without rewriting unchanged packages.

## Output

The host export root defaults to `/home/jaco/Workspace/Morning/Atlas`. Atlas should start with the root `manifest.json`, then inspect the selected weekly package under `weekly/YYYY-Www/`.

Each weekly package contains raw, traceable evidence:

- report metadata and shift identity
- attendance observations with person context
- Brothers Keeper contributions verbatim
- Stop & Fix and card records
- machine events with machine and assignee context
- machine-state declarations
- Construction work items
- other activities
- referenced people, machines, crews and supervisors
- deterministic `metrics.json`
- `data-quality.json` with coverage signals and observability gaps
- a deterministic `summary.md`

The export contains no AI conclusions and no account credentials, password hashes, session material or direct messages.

## Interpretation boundary

Machine-event intervals remain engineering event intervals. They are not promoted to downtime, wrench time, availability, MTBF or MTTR. `data-quality.json` states this explicitly so Atlas can distinguish evidence from inference.

The TMM missing-shift list assumes 3 shifts x 7 days only as a coverage signal. Until Morning models planned non-reporting shifts, missing slots are not proof that a report was required.

## Manual generation

```bash
morning atlas-export --week-start 2026-09-07 --output /path/to/export
```

The week start must be a Monday.
