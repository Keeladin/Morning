# Morning three-shift day-one cutover — 10 September 2026

## Decision

Morning now starts a fresh operational database under a native three-shift model. The previous two-shift operational database is archived and is not imported into the new live database.

## Shift identity

- **Morning Shift:** 06:00–14:00
- **Afternoon Shift:** 14:00–22:00
- **Night Shift:** 22:00–06:00 the following calendar day
- A Night Shift belongs to the date on which it **finishes**. Example: 22:00 on 10 September through 06:00 on 11 September is the **11 September Night Shift**.

The canonical `shift_kind` values are `morning`, `afternoon`, and `night`. There is no `day` shift in the new live database.

## Reporting day

One management reporting day remains 06:00 through 06:00 the following day. A complete TMM reporting day therefore expects a submitted Morning, Afternoon, and Night report, plus Control Room input when that completeness requirement is enabled.

## Data cutover

Before cutover, writes to the old API were stopped and a final PostgreSQL custom-format dump and compressed SQL backups were created under `backups/two-shift-archive/`. The old PostgreSQL database named `morning` is also left frozen in the database volume as an additional recovery source.

The new production database retains the standard name `morning`. It begins with no operational records: no supervisors, crews, personnel, machines, reports, messages, notices, or Control Room observations. A new administrator is bootstrapped separately so operational history remains genuinely clean.

## Product surfaces covered

The three-shift identity is used by automatic shift detection, Start Report, offline report creation/synchronization, Home report history, active report headers, Review/Submit, WhatsApp rendering, detailed and compact management reports, 24-hour completeness checks, Construction reporting, and Morning Control Centre shift policy.

## Verification

The schema migrates successfully from an empty PostgreSQL database through Alembic revision `0008_three_shift_system`. Backend tests include exact 06:00, 14:00 and 22:00 boundaries and Night Shift rollover after midnight. The rollout smoke gate submits all three shift types before declaring a reporting day complete.


## TMM crew selection and Demo Mode

From revision `0009_tmm_multicrew_demo`, TMM crew responsibility belongs to each shift report rather than being inferred from a supervisor's personnel record. A supervisor must select at least one active TMM crew when starting a report and may select multiple crews when covering more than one team. Attendance is derived from the combined active personnel assigned to the selected crews, while the selected crew ids are snapshotted against the report. Construction retains its existing single-crew workflow.

Morning Control Centre supports renaming and safe deletion of TMM crews. A crew cannot be deleted while personnel, report history, or Construction configuration still reference it. Supervisor accounts can also be marked as Demo Mode. Demo users can walk through the live TMM workflow with current crew, personnel, and machine reference data, but report mutations stay local to the browser and are excluded from synchronization, production history, management reporting, notices, and private messages.
