import { expect, test } from '@playwright/test'

const session = {
  authenticated: true,
  principal: { principal_id: 'principal-jaco', display_name: 'Jaco Fouche', role: 'supervisor' },
  csrf_token: 'offline-test-token',
}
const shift = { shift_date: '2026-09-02', shift_kind: 'morning', shift_id: '2026-09-02:morning' }
const me = {
  principal_id: 'principal-jaco', display_name: 'Jaco Fouche', role: 'supervisor',
  crew_id: 'crew-maintenance', crew_name: 'Maintenance',
}
const crews = { crews: [
  { id: 'crew-maintenance', name: 'Maintenance', created_at: 'now' },
] }
const roster = { people: [
  { id: 'person-jaco', name: 'Jaco Fouche', employee_number: null, role: 'Supervisor', active: true, crew_id: 'crew-maintenance', created_at: 'now' },
] }
const machines = { machines: [
  { id: 'machine-1', machine_id: 'RLH1', machine_type: 'LHD', section: null, active: true, created_at: 'now', retired_at: null, control_room_scope: false },
] }
test('can cold-start and create a TMM report with the network offline', async ({ page, context }) => {
  await page.route('**/api/morning/**', async route => {
    const url = new URL(route.request().url())
    const path = url.pathname
    if (path === '/api/morning/auth/session') return route.fulfill({ json: session })
    if (path === '/api/morning/shift') return route.fulfill({ json: shift })
    if (path === '/api/morning/me') return route.fulfill({ json: me })
    if (path === '/api/morning/machines') return route.fulfill({ json: machines })
    if (path === '/api/morning/personnel') return route.fulfill({ json: roster })
    if (path === '/api/morning/crews') return route.fulfill({ json: crews })
    if (path === '/api/morning/home') return route.fulfill({ json: { recent_reports: [], announcements: [], messages: [], unread_count: 0, supervisors: [] } })
    if (path === '/api/morning/roster') return route.fulfill({ json: roster })
    if (path === '/api/morning/draft' && route.request().method() === 'GET') return route.fulfill({ json: { report: null } })
    return route.fulfill({ status: 404, json: { error: `unmocked ${path}` } })
  })

  await page.goto('/')
  await expect(page.getByRole('heading', { name: 'Good morning, Jaco Fouche' })).toBeVisible()
  await page.getByRole('button', { name: /Start new TMM report/ }).click()
  await expect(page.getByRole('heading', { name: 'Start shift report' })).toBeVisible()
  await page.evaluate(async () => {
    const registration = await navigator.serviceWorker.ready
    await registration.update()
    if (navigator.serviceWorker.controller) return
    await new Promise<void>(resolve => navigator.serviceWorker.addEventListener('controllerchange', () => resolve(), { once: true }))
  })
  await page.unroute('**/api/morning/**')
  await context.setOffline(true)
  await page.reload({ waitUntil: 'domcontentloaded' })

  await expect(page.getByRole('heading', { name: 'Good morning, Jaco Fouche' })).toBeVisible()
  await page.getByRole('button', { name: /Start new TMM report/ }).click()
  await expect(page.getByRole('heading', { name: 'Start shift report' })).toBeVisible()
  await page.getByRole('checkbox', { name: 'Maintenance' }).check()
  const start = page.getByRole('button', { name: 'Start report' })
  await expect(start).toBeEnabled()
  await start.click()

  await expect(page.getByRole('heading', { name: 'Attendance' })).toBeVisible()
  await expect(page.getByText('Saved locally — waiting to sync', { exact: true })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Present' })).toBeVisible()
})
