import { useRegisterSW } from 'virtual:pwa-register/react'

export function PwaUpdate() {
  useRegisterSW({
    immediate: true,
    onRegisteredSW: (_url, registration) => { if (registration) void registration.update().catch(() => undefined) },
  })
  return null
}
