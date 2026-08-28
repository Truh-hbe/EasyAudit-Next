import { expect, test } from '@playwright/test'

test('resolves the server session before choosing anonymous UI', async ({ page }) => {
  await page.route('**/api/v1/me', async (route) => {
    await new Promise((resolve) => setTimeout(resolve, 250))
    await route.fulfill({
      status: 401,
      contentType: 'application/json',
      body: JSON.stringify({ detail: 'Authentication required' }),
    })
  })

  await page.goto('/')

  await expect(page.getByRole('heading', { name: '正在确认服务器会话' })).toBeVisible()
  await expect(page.getByRole('heading', { name: '当前没有有效会话' })).not.toBeVisible()
  expect(new URL(page.url()).protocol).toBe('https:')

  await expect(page.getByRole('heading', { name: '当前没有有效会话' })).toBeVisible()
})
