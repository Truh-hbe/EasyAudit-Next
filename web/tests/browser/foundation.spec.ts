import { expect, test } from '@playwright/test'

test('serves the frontend foundation from the HTTPS browser origin', async ({ page }) => {
  await page.goto('/')

  await expect(
    page.getByRole('heading', { name: 'EasyAudit Next Product Surface' }),
  ).toBeVisible()
  expect(new URL(page.url()).protocol).toBe('https:')
})
