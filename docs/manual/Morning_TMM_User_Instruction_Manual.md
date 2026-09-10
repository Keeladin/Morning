# Morning TMM User Instruction Manual

**Three-Shift and Multi-Crew Edition**
**Version:** 10 September 2026
**Application:** morningportal.co.za

This manual explains the current TMM supervisor workflow in Morning, including the three-shift reporting calendar, multi-crew selection, offline reporting, Demo Mode and the Morning Control Centre functions relevant to TMM.

## 1. Quick Start

1. Open `morningportal.co.za`.
2. Register a supervisor account using your full name, username and password.
3. Wait for approval from a Morning Control Centre administrator.
4. Sign in and open **Start new TMM report** from Home.
5. Confirm the suggested shift and reporting date.
6. Select every crew you will supervise for that shift. One or more crews may be selected.
7. Complete Attendance -> Brothers Keeper -> Safety -> Machine Activity -> Other Activities -> Review/Submit.
8. Review the report and submit it.

Morning is designed so information is captured once at source and then reused in report history, WhatsApp-ready output and management reporting.

## 2. Three-Shift Reporting Calendar

| Shift | Operating time | Reporting-date rule |
| --- | --- | --- |
| Morning | 06:00-14:00 | Belongs to that calendar date |
| Afternoon | 14:00-22:00 | Belongs to that calendar date |
| Night | 22:00-06:00 | Belongs to the day on which it finishes |

### Night Shift date rule

Night Shift is the important exception. The reporting date is the date on which the shift ends at 06:00.

- Sunday 22:00-Monday 06:00 = **Monday Night Shift**.
- Monday 22:00-Tuesday 06:00 = **Tuesday Night Shift**.
- Tuesday 22:00-Wednesday 06:00 = **Wednesday Night Shift**.
- Wednesday 22:00-Thursday 06:00 = **Thursday Night Shift**.
- Thursday 22:00-Friday 06:00 = **Friday Night Shift**.

For management reporting, a Monday operational day therefore runs from **Sunday 22:00 to Monday 22:00** and contains Monday Night, Monday Morning and Monday Afternoon.

Morning automatically suggests the current shift and reporting date. Check the suggestion before starting the report.

## 3. Registration and Sign-in

Open Morning and choose **Register**. Enter your full name, username and password. A new account cannot be used for normal reporting until it has been approved in Morning Control Centre.

Once approved, choose **Sign in** and use your registered username and password.

If the browser offers **Install** or **Add to Home Screen**, Morning may be installed as a PWA. After an application update, close and reopen the PWA or accept the update prompt so the newest version is loaded.

## 4. Home Screen

After sign-in, TMM supervisors land on Home. Home provides the main route into the shift-report workflow and shows recent reporting and communication information.

Use **Start new TMM report** when no draft exists. If a report is already in progress, use **Continue current report** to resume it.

Home also provides access to recent submitted TMM reports, the shared Notice Board and private supervisor messages. Submitted reports are read-only historical records.

## 5. Start Report and Crew Selection

For TMM, a crew is selected **for the report**, not permanently assigned to the supervisor.

1. Open **Start new TMM report**.
2. Confirm the reporting date and Morning, Afternoon or Night shift.
3. Under **Select crew(s) for this shift**, select every crew you will supervise.
4. Select one crew for a normal shift or multiple crews when covering more than one crew.
5. Choose **Start report**.

This supports stand-in supervision. If another supervisor is absent, the replacement supervisor simply selects the affected crew when starting the report.

The selected crew set is stored with that report. Later changes to crew configuration do not rewrite historical reports.

## 6. Attendance

Attendance is built automatically from the active personnel assigned to the crew or crews selected when the report started.

Mark each listed person **Present** or **Absent**. If two crews were selected, Morning combines the personnel from both crews into the attendance roster.

If somebody is missing from Attendance, first check that the correct crew was selected and that the person is active and assigned to that crew in Morning Control Centre.

Crew membership controls Attendance only. Machine Activity can still assign work to any active TMM person where operational assistance crosses crew boundaries.

## 7. Brothers Keeper

Brothers Keeper is a required TMM report stage. Enter the shift contribution, workforce safety concern, suggestion, improvement or other relevant safety issue raised toward management.

The contribution cannot be left blank. Morning carries it automatically into Review, the submitted historical report and the WhatsApp-ready summary. Do not re-enter the same information elsewhere.

## 8. Safety

Use the Safety stage to capture the applicable shift safety information.

- Record Stop & Fix items when applicable, including the concern, location, instruction and status.
- Capture Green Card and Red Card observations where required by the site reporting process.
- Rectify or update Stop & Fix records when their status changes.
- If a safety subsection genuinely has no events, explicitly confirm that it was reviewed rather than simply leaving it unresolved.

Review entries before continuing to make sure the report reflects what actually happened on shift.

## 9. Machine Activity

Use Machine Activity for engineering work performed on TMM equipment during the shift.

Select the machine, enter the start and end time, describe the issue/work performed and assign the person responsible where applicable.

The personnel selector is TMM-wide. It may select any active registered TMM person, even when that person belongs to a different crew from the Attendance roster.

Where the same machine has multiple related breakdown/work entries, Morning's reporting output should consolidate them into a readable machine summary while retaining the structured source records.

Machine work time is not automatically treated as machine downtime. Morning keeps engineering activity, machine-state declarations and control-room delay evidence as separate operational concepts.

## 10. Other Activities

Use Other Activities for meaningful shift work that does not belong under a machine event, such as support tasks, workshop activity, inspections, planning or other relevant engineering work.

Keep descriptions short, factual and useful to the next supervisor or management reader.

## 11. Review and Submit

The Review stage is the final check before the report becomes operational history.

Check the reporting date, shift, selected crews, Attendance, Brothers Keeper, Safety, Machine Activity and Other Activities. Correct anything that is incomplete or inaccurate before submission.

When satisfied, choose **Submit**. A submitted report becomes read-only operational history and feeds Morning's deterministic reporting projections.

Morning can generate a WhatsApp-ready summary from the same structured report. Use that output instead of manually recreating the shift report in a second format.

## 12. Offline Use

Morning is designed for underground and other intermittent-connectivity environments.

Connect successfully at least once so the current session and operational reference data can be cached on the device. When connectivity is lost, an in-progress or newly started report can continue locally using the cached information.

Offline report changes are stored on the device. When connectivity returns, Morning automatically attempts to synchronize pending operational reports to the server.

Pay attention to the sync indicator. **Saved locally - waiting to sync** means the information is safe on the device but has not yet reached the production server.

Do not clear browser/PWA storage while an offline report is waiting to synchronize.

## 13. Demo Mode

Demo Mode is intended for training and showcasing Morning without polluting production reporting.

A Morning Control Centre administrator can mark a supervisor account as a Demo user. Demo Mode displays a clear banner so it cannot easily be confused with normal operational reporting.

Demo users can walk through the real TMM workflow and use the current crews, personnel and machines, but demo report activity remains local to the device and is not synchronized into production.

Demo reports do not contribute to operational history, Attendance totals, 24-hour management reports or normal synchronization. Production Notice Board posting and private messaging are disabled in Demo Mode.

When the demonstration is finished, leave Demo Mode or sign out. Do not use a Demo account for real shift reporting.

## 14. Morning Control Centre

Morning Control Centre is the configuration and management layer for the application. Access is restricted to authorized Control users.

### Crews

Control users can create, rename and delete crews. Crew deletion is protected: Morning refuses hard deletion while personnel, report history or Construction configuration still references that crew.

If a crew cannot be deleted, reassign/remove the current personnel first where appropriate. Never delete or rewrite historical operational identity merely to tidy a current list.

### Personnel

Create and maintain personnel records, including name, employee number, role/trade, crew assignment and active status. Correct crew assignment here when Attendance does not show the expected person.

### Supervisors

Approve new supervisor registrations, maintain their account details, activate/deactivate accounts and enable or disable Demo Mode. A TMM supervisor does not require a permanent crew assignment for reporting; the crew is selected when each report starts.

### Machines

Maintain the active TMM machine list used by Machine Activity. Deactivate equipment that should no longer appear in normal selectors while preserving historical references.

### Shift policy

The standard cycle is Morning 06:00, Afternoon 14:00 and Night 22:00. Night Shift belongs to the reporting date on which it finishes.

## 15. Troubleshooting

**The crew I need is not listed:** Check that it exists as a TMM crew in Morning Control Centre and is not configured as a Construction crew.

**A person is missing from Attendance:** Check the selected crew(s), the person's active status and their crew assignment in Control.

**Start Report is disabled:** At least one TMM crew must be selected before a TMM report can start.

**The wrong Night Shift date appears:** Remember that the Night Shift is named for the day it finishes. Sunday 22:00-Monday 06:00 is Monday Night Shift.

**The phone still shows an older interface:** Refresh the browser, close and reopen the installed PWA, or accept Morning's update prompt.

**An offline report has not appeared on the server yet:** Keep the device storage intact, restore connectivity, reopen Morning and allow the pending report to synchronize.

**A crew cannot be deleted:** It is still referenced by personnel, report history or Construction configuration. Morning blocks deletion to protect operational integrity.

## 16. Daily Supervisor Checklist

Before starting:

- Verify the suggested reporting date and shift.
- Select every crew you are supervising.
- Confirm the Attendance roster looks correct.

Before submitting:

- Confirm Attendance is complete.
- Complete Brothers Keeper.
- Review Safety.
- Review Machine Activity.
- Review Other Activities.
- Check the final summary before submission.
- If working offline, confirm the report later synchronizes successfully.

---

**Morning**
Structured TMM shift reporting
`morningportal.co.za`
