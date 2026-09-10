# Morning — TMM Supervisor Workflow Change

**Date:** 10 September 2026  
**Status:** Agreed implementation scope  
**Scope:** TMM supervisor application and Morning Control Centre

## 1. Purpose

This document records operational changes requested after use of the current Morning TMM workflow.

These requirements are intentional product evolution based on operational use. Where this document changes the staged supervisor workflow described in the 28 August 2026 extraction contract, this document governs the TMM implementation for these features.

The core principle remains:

> Capture once; derive and display everywhere else.

## 2. Revised supervisor workflow

The TMM supervisor experience becomes:

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
Review / Summary
  ↓
Submit
```

The Home page is outside the report itself. Attendance remains the first report-capture stage.

## 3. Home landing page

After login, a supervisor lands on **Home** rather than directly on Attendance.

Home must provide:

- a clear action to start a new report or continue the current draft;
- the five most recently submitted TMM reports, newest first;
- enough report metadata to identify date, shift and supervisor;
- the ability to open/view each recent submitted report;
- a private-message area for supervisor-to-supervisor messages;
- a shared Notice Board for broadcast notices.

### Recent reports

The five most recent reports are a read-only history projection over submitted report truth. Opening a submitted report must not return it to the normal draft edit path.

### Private messages

A registered TMM supervisor can send a direct message to one other registered TMM supervisor.

A direct message:

- is visible to the sender and selected recipient only;
- is not posted to the shared Notice Board;
- records sender, recipient, timestamp, body and read/unread state;
- may be surfaced on Home using an unread-message indicator or inbox summary.

Messaging V1 is deliberately small. It is not intended to reproduce WhatsApp, channels, group chat or general social messaging.

### Notice Board / broadcast

A supervisor or authorized user can create a broadcast notice.

A broadcast:

- is displayed on the shared TMM Home Notice Board;
- is visible to all registered TMM supervisors;
- is not copied into every supervisor's private inbox;
- records author, timestamp and notice body.

Pinning, expiry, acknowledgement and richer notice lifecycle may be added later only if operational use requires them.

## 4. Attendance remains crew-scoped

Attendance must continue to show only personnel assigned to the current supervisor's crew/report crew.

The attendance roster and the work-assignment roster serve different operational purposes and must not be coupled.

Crew identity remains frozen onto the report when the report starts, preserving the established report-history semantics.

## 5. Mandatory Brothers Keeper stage

A new mandatory stage named **Brothers Keeper** must appear immediately after Attendance and before Safety.

The page contains:

- heading: `Brothers Keeper`;
- short guidance that the contribution may be a workforce safety concern, suggestion, improvement or other safety-related issue raised toward management;
- one text-entry field for the Brothers Keeper contribution.

The contribution field is mandatory.

A blank value or whitespace-only value is invalid. The supervisor cannot advance to Safety until a valid contribution is present.

The Brothers Keeper contribution is structured shift-report data and must be persisted with the report rather than stored only in rendered text.

## 6. Brothers Keeper projection and rendering

The contribution is captured once and reused automatically.

It must appear in:

1. the Review / Summary stage before submission;
2. the submitted historical shift report;
3. the deterministic WhatsApp-ready shift report / summary.

The WhatsApp-ready output should present **Brothers Keeper** as its own clearly labelled section, normally between Attendance and Safety.

No second manual entry is permitted for summary or WhatsApp rendering.

## 7. Machine activity personnel assignment

The personnel selector used when assigning a person/artisan to a machine activity must no longer be limited to the current supervisor's crew.

The selector must show **all active personnel registered under TMM**, regardless of crew assignment.

This supports actual operational practice where personnel from another crew, dayshift or another TMM grouping may assist with work.

The rule is therefore:

```text
Attendance roster        = current report crew
Machine-work assignees   = all active TMM personnel
```

If useful for readability, the TMM-wide assignment list may be grouped by crew/trade, but grouping must not restrict selection.

Historical assignment must resolve to a stable personnel identity, not merely the person's current display name.

## 8. Morning Control Centre — edit capability

Machines, personnel and supervisors must be editable after creation.

### Machines

Authorized Control users must be able to:

- edit machine-identifying/configuration details that are safe to change;
- activate or deactivate a machine;
- request permanent deletion subject to historical-reference protection.

### Personnel

Authorized Control users must be able to edit existing personnel details, including where applicable:

- name/display details;
- trade;
- position / job title / job description;
- crew assignment;
- active/inactive status;
- other existing profile fields exposed by Morning.

A field omitted during initial profile creation must be editable later. Profile creation is not a one-time lock on job details.

### Supervisors

Authorized Control users must be able to edit existing supervisor details, including relevant person linkage, crew assignment and status/configuration fields.

Supervisors can be activated/deactivated and may be permanently deleted only when historical-reference rules permit it.

## 9. Delete versus deactivate

Morning must distinguish correcting unused setup data from destroying operational history.

Permanent hard deletion is allowed only when the machine/person/supervisor has **never been referenced by submitted operational history or another protected historical record**.

If historical references exist:

- hard deletion must be refused;
- the entity may be deactivated so it no longer appears in normal active selectors;
- historical reports must continue resolving the identity correctly.

This preserves the established Morning principle that deactivation must not erase historical identity.

The delete action must be deliberate and clearly distinguishable from deactivation.

## 10. Data-model expectations

Implementation should provide durable source records or equivalent domain fields for:

- Brothers Keeper contribution on the shift report;
- private supervisor messages;
- shared TMM broadcast notices;
- read/unread state for private messages;
- existing report-history projection needed for the Home recent-reports list.

Do not make the Home page, Review page or WhatsApp message independent sources of truth. They are projections over canonical report/message records.

## 11. Authorization expectations

At minimum:

- supervisors can read TMM Home content appropriate to their role;
- supervisors can read/send their own direct messages;
- one supervisor cannot read another pair's private conversation merely because they share TMM membership;
- broadcast notices are visible to all registered TMM supervisors;
- destructive configuration actions remain restricted to authorized Morning Control users.

## 12. Acceptance criteria

The change is complete when all of the following are verified:

1. Login lands a TMM supervisor on Home.
2. Home shows the five latest submitted TMM reports in newest-first order.
3. A supervisor can open a listed historical report without mutating it.
4. A supervisor can send a private message to another registered supervisor and no unrelated supervisor can read it.
5. A broadcast notice appears on the shared Home Notice Board rather than being copied to private inboxes.
6. Attendance shows only the current report crew.
7. Brothers Keeper appears directly after Attendance and cannot be skipped with an empty contribution.
8. The Brothers Keeper contribution appears unchanged in Review, submitted history and WhatsApp-ready output.
9. Machine-activity assignment can select any active registered TMM person, not only the current crew.
10. Existing machine, personnel and supervisor records can be edited after creation.
11. Personnel job/trade/position details can be added or corrected after initial creation.
12. Unused entities can be permanently deleted.
13. Historically referenced entities cannot be hard-deleted and can instead be deactivated.
14. Historical reports still resolve deactivated entity identities correctly.

## 13. Implementation posture

Keep this feature set inside Morning's existing modular-monolith boundary.

Do not introduce a separate messaging service or generic workflow engine for these requirements. The messaging and Notice Board requirements are small domain capabilities owned by Morning.

TMM remains the first production scope. The implementation should preserve clean seams for future departments without prematurely generalizing every rule.