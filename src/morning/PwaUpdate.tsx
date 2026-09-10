import { useRegisterSW } from 'virtual:pwa-register/react'

export function PwaUpdate() {
  useRegisterSW({
    immediate: true,
    onRegisteredSW: (_url, registration) => { void registration?.update() },
  })
  return null
}
