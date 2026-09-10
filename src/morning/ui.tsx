import type { ReactNode } from 'react'

export function MorningMark({ compact = false }: { compact?: boolean }) {
  return <span className={compact ? 'morning-mark compact' : 'morning-mark'} aria-hidden>
    <svg viewBox="0 0 52 36" role="img"><path d="M2 31 16 9l8 12 8-15 18 25H36L25 17 17 31Z" fill="currentColor"/><path d="m17 31 8-14 8 14Z" fill="#fff" opacity=".92"/></svg>
  </span>
}

type IconName = 'home'|'report'|'notice'|'message'|'people'|'shield'|'machine'|'activity'|'review'|'control'|'clock'|'check'|'plus'|'warning'
const paths: Record<IconName, ReactNode> = {
  home:<><path d="m3 11 9-8 9 8"/><path d="M5 10v10h14V10M9 20v-6h6v6"/></>, report:<><path d="M6 3h9l3 3v15H6z"/><path d="M9 11h6M9 15h6M9 7h3"/></>,
  notice:<><path d="M4 13h3l9 4V5L7 9H4z"/><path d="M7 13v5M18 9c1.5 1.5 1.5 4.5 0 6"/></>, message:<><path d="M4 5h16v12H9l-5 4z"/><path d="M8 9h8M8 13h5"/></>,
  people:<><circle cx="9" cy="8" r="3"/><circle cx="17" cy="9" r="2.5"/><path d="M3 20c.5-4 2.5-6 6-6s5.5 2 6 6M15 14c3 0 5 2 5.5 5"/></>, shield:<><path d="M12 3 20 6v6c0 5-3.5 8-8 9-4.5-1-8-4-8-9V6z"/><path d="m8 12 2.5 2.5L16 9"/></>,
  machine:<><path d="M4 15h3l2-6h7l2 6h2v3H4z"/><circle cx="8" cy="18" r="2"/><circle cx="17" cy="18" r="2"/><path d="M10 9V6h5"/></>, activity:<><path d="M6 3h12v18H6z"/><path d="M9 8h6M9 12h6M9 16h4"/></>,
  review:<><circle cx="12" cy="12" r="9"/><path d="m8 12 2.5 2.5L16.5 8"/></>, control:<><circle cx="12" cy="12" r="3"/><path d="M12 2v4M12 18v4M2 12h4M18 12h4M5 5l3 3M16 16l3 3M19 5l-3 3M8 16l-3 3"/></>,
  clock:<><circle cx="12" cy="12" r="9"/><path d="M12 7v6l4 2"/></>, check:<path d="m5 12 4 4L19 6"/>, plus:<path d="M12 5v14M5 12h14"/>, warning:<><path d="M12 3 22 20H2Z"/><path d="M12 9v5M12 17h.01"/></>,
}
export function MorningIcon({ name }: { name: IconName }) { return <span className={`morning-icon morning-icon-${name}`} aria-hidden><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round">{paths[name]}</svg></span> }
