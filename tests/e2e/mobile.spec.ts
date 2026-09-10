import { expect, test } from '@playwright/test'

test('Morning renders its mobile login surface and PWA manifest', async ({ page, request }) => {
  await page.route('**/api/morning/auth/session', route => route.fulfill({ json: { authenticated: false } }))
  await page.setViewportSize({ width: 360, height: 800 })
  await page.goto('/')
  await expect(page.getByRole('heading', { name: 'Morning' })).toBeVisible()
  await expect(page.getByRole('tab', { name: 'Log in' })).toBeVisible()
  expect((await page.locator('meta[name="theme-color"]').getAttribute('content'))).toBe('#315f78')
  const manifest = await request.get('/manifest.webmanifest')
  expect(manifest.ok()).toBeTruthy()
  expect((await manifest.json()).short_name).toBe('Morning')
})
