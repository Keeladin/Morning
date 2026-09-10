export type ShiftKind = 'morning' | 'afternoon' | 'night'
export type ReportingModel = 'tmm' | 'construction'
export type ConstructionWorkKind = 'core' | 'outstanding'
export type ConstructionWorkStatus = 'not_started' | 'in_progress' | 'held' | 'complete'
export type PrincipalRole = 'admin' | 'supervisor'
export type MachineState = 'running' | 'not_tested' | 'under_repair' | 'awaiting_parts' | 'other'
export type MachineStateProvenance = 'declared' | 'carried'

export type MorningPrincipal = { principal_id: string; display_name: string; role: PrincipalRole; admin_workspace?: string | null; demo_mode?: boolean }
export type MorningSession = { authenticated: boolean; principal?: MorningPrincipal; csrf_token?: string }
export type ShiftIdentity = { shift_date: string; shift_kind: ShiftKind; shift_id: string }
export type SupervisorContext = { principal_id: string; display_name: string; role: PrincipalRole; crew_id: string | null; crew_name: string | null }

export type Crew = { id: string; name: string; created_at?: string }

export type Machine = {
  id: string; machine_id: string; machine_type: string | null; section: string | null
  active: boolean; created_at: string; retired_at: string | null; control_room_scope: boolean
}
export type Person = { id: string; name: string; employee_number: string | null; role: string | null; active: boolean; crew_id: string | null; created_at: string }
export type AttendanceEntry = { person_id: string; present: boolean }
export type StopFixRecord = {
  id: string; number: string; issued_at: string; area_of_concern: string; location: string
  reason: string; instruction: string; status: 'open' | 'rectified'; rectified_at: string | null
}
export type CardObservation = { id: string; card_type: 'red' | 'green'; reason: string }
export type MachineEvent = { id: string; machine_id: string; start_time: string; end_time: string; issue: string; person_id: string | null }
export type MachineStateDeclaration = {
  id: string; machine_id: string; report_id: string; declared_at: string; state: MachineState
  provenance: MachineStateProvenance; state_note: string | null; source_state_id: string | null
  follow_up: string | null; created_at: string | null
}
export type ConstructionWorkItem = {
  id: string; kind: ConstructionWorkKind; level: string; location: string; task: string
  status: ConstructionWorkStatus; progress_percent: number | null; update_text: string
  constraint_text: string | null; next_action: string | null
}
export type OtherActivity = { id: string; category: string | null; description: string }
export type ShiftReport = {
  id: string; shift_date: string; shift_kind: ShiftKind; shift_id: string; supervisor_principal_id: string
  crew_id: string | null; crew_ids: string[]; reporting_model: ReportingModel; status: 'draft' | 'submitted' | 'abandoned'; attendance: AttendanceEntry[]
  stop_fix: StopFixRecord[]; cards: CardObservation[]; machine_events: MachineEvent[]
  construction_work: ConstructionWorkItem[]; other_activities: OtherActivity[]; created_at: string; updated_at: string; submitted_at: string | null
  brothers_keeper: string | null
  safety_reviewed_empty: boolean; machine_activity_reviewed_empty: boolean; other_activities_reviewed_empty: boolean
  construction_work_reviewed_empty: boolean; construction_outstanding_reviewed_empty: boolean
  offline_submit_pending?: boolean
}

export type HomeReport = { id: string; shift_date: string; shift_kind: ShiftKind; supervisor_name: string; submitted_at: string | null; brothers_keeper: string | null; summary_text: string }
export type SupervisorRecipient = { principal_id: string; display_name: string; username: string; status: string; person_id: string | null }
export type MorningMessage = { id: string; sender_principal_id: string; recipient_principal_id: string | null; kind: 'direct' | 'announcement'; body: string; created_at: string; read_at: string | null; sender_name: string; recipient_name?: string }
export type HomeData = { recent_reports: HomeReport[]; announcements: MorningMessage[]; messages: MorningMessage[]; unread_count: number; supervisors: SupervisorRecipient[] }

export type SyncState = { status: 'idle' | 'saving' | 'saved' | 'failed' | 'offline'; message?: string; retry?: () => void }

export const STOP_FIX_AREAS = ['Support','A Hazard','Working at height','Environmental/Ventilation','Transport and Tramming','De-energised/Lock out','Barring','Lifting','Guarding','Other'] as const
export const OTHER_ACTIVITY_CATEGORIES = ['Housekeeping','Inspections','Training','Workshop work','Recovery work','Assisting another team','Miscellaneous'] as const
export const MACHINE_STATES: { value: MachineState; label: string }[] = [
  { value: 'running', label: 'Running' },
  { value: 'not_tested', label: 'Not tested' },
  { value: 'under_repair', label: 'Under repair' },
  { value: 'awaiting_parts', label: 'Awaiting parts' },
  { value: 'other', label: 'Other' },
]

export const CONSTRUCTION_WORK_STATUSES: { value: ConstructionWorkStatus; label: string }[] = [
  { value: 'not_started', label: 'Not started' },
  { value: 'in_progress', label: 'In progress' },
  { value: 'held', label: 'Held' },
  { value: 'complete', label: 'Complete' },
]
