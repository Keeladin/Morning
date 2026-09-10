export function hhmm(iso: string): string {
  return /^\d{2}:\d{2}$/.test(iso) ? iso : iso.slice(11, 16)
}

const MONTHS = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec']
export function formatShiftDate(shiftDate: string): string {
  const [year, month, day] = shiftDate.split('-').map(Number)
  if (!year || !month || !day) return shiftDate
  return `${day} ${MONTHS[month - 1]} ${year}`
}

export function stateLabel(state: string): string {
  return state.split('_').map((part) => part.charAt(0).toUpperCase() + part.slice(1)).join(' ')
}

export function formatConstructionLevel(level: string): string {
  const match = level.toUpperCase().match(/^(\d+)([NS])?$/)
  if (!match) return level
  const side = match[2] === 'N' ? ' North' : match[2] === 'S' ? ' South' : ''
  return `${match[1]}L${side}`
}

export function shiftLabel(shiftKind: string): string {
  return ({ morning: 'Morning Shift', afternoon: 'Afternoon Shift', night: 'Night Shift' } as Record<string, string>)[shiftKind] || `${shiftKind.charAt(0).toUpperCase()}${shiftKind.slice(1)} Shift`
}

export function shiftShortLabel(shiftKind: string): string {
  return ({ morning: 'Morning', afternoon: 'Afternoon', night: 'Night' } as Record<string, string>)[shiftKind] || shiftKind
}
