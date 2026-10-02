import { execFileSync } from 'node:child_process'

import { expect, test, type Page } from '@playwright/test'

const LOGIN_NAME = 'browser-pilot-3-user'
const PASSWORD = 'pilot-3-browser-password-000'

function apiPath(url: string): string {
  return new URL(url).pathname
}

async function login(page: Page) {
  await page.goto('/review-plans/new')
  await page.getByLabel('登录名').fill(LOGIN_NAME)
  await page.getByLabel('密码').fill(PASSWORD)
  await page.getByRole('button', { name: '登录' }).click()
  await expect(page.getByText('Pilot-3 Browser User')).toBeVisible()
  await page.getByRole('link', { name: '审查活动' }).click()
  await page.getByRole('link', { name: '新建审查计划' }).click()
  await expect(page.getByRole('heading', { name: '新建审查计划' })).toBeVisible()
}

/**
 * Let the first POST reach the server (it commits), then drop the response: the browser sees a
 * timeout while the creation actually succeeded. Later POSTs pass through untouched.
 */
async function loseFirstResponse(page: Page, pathname: string) {
  const keys: (string | undefined)[] = []
  await page.route(`**${pathname}`, async (route) => {
    const request = route.request()
    if (request.method() !== 'POST') {
      await route.fallback()
      return
    }
    keys.push(request.headers()['idempotency-key'])
    if (keys.length === 1) {
      await route.fetch()
      await route.abort('timedout')
    } else {
      await route.continue()
    }
  })
  return keys
}

test.describe.configure({ mode: 'serial', retries: 0 })

test.beforeAll(() => {
  execFileSync('python', ['tests/browser/seed_pilot_3_real_acceptance.py'], {
    env: process.env,
    stdio: 'inherit',
  })
})

test('a retry after a lost Plan response creates exactly one plan', async ({ page }) => {
  await login(page)
  const keys = await loseFirstResponse(page, '/api/v1/review-plans')
  await page.getByLabel('计划名称').fill('Pilot-3 Retried Plan')
  await page.getByRole('button', { name: '保存计划并继续' }).click()
  await expect(page.getByRole('alert').filter({ hasText: '结果未知' })).toBeVisible()

  const replay = page.waitForResponse(
    (response) =>
      apiPath(response.url()) === '/api/v1/review-plans' &&
      response.request().method() === 'POST',
  )
  await page.getByRole('button', { name: '重试保存计划' }).click()
  const response = await replay
  expect(response.status()).toBe(201)
  expect(response.headers()['idempotent-replayed']).toBe('true')
  const plan = (await response.json()) as { id: string }
  await expect(page.getByRole('heading', { name: '新建审查活动' })).toBeVisible()
  expect(new URL(page.url()).pathname).toBe(`/review-plans/${plan.id}/review-cases/new`)

  expect(keys).toHaveLength(2)
  expect(keys[0]).toBeTruthy()
  expect(keys[1]).toBe(keys[0])

  const plans = await page.request.get('/api/v1/review-plans')
  const titles = ((await plans.json()) as { title: string }[]).map((item) => item.title)
  expect(titles.filter((title) => title === 'Pilot-3 Retried Plan')).toHaveLength(1)
})

test('a retry after a lost Case response creates exactly one case', async ({ page }) => {
  await login(page)
  await page.getByLabel('计划名称').fill('Pilot-3 Case Plan')
  await page.getByRole('button', { name: '保存计划并继续' }).click()
  await expect(page.getByRole('heading', { name: '新建审查活动' })).toBeVisible()

  const keys = await loseFirstResponse(page, '/api/v1/review-cases')
  await page.getByRole('radio', { name: /process_review@1/ }).check()
  await page.getByLabel('审查活动名称').fill('Pilot-3 Retried Case')
  await page.getByLabel('区域代码').fill('area-a')
  await page.getByLabel('审查类型').fill('standard')
  await page.getByRole('button', { name: '创建审查活动' }).click()
  await expect(page.getByRole('alert').filter({ hasText: '结果未知' })).toBeVisible()

  const replay = page.waitForResponse(
    (response) =>
      apiPath(response.url()) === '/api/v1/review-cases' &&
      response.request().method() === 'POST',
  )
  await page.getByRole('button', { name: '重试创建审查活动' }).click()
  const response = await replay
  expect(response.status()).toBe(201)
  expect(response.headers()['idempotent-replayed']).toBe('true')
  const created = (await response.json()) as { id: string }
  expect(new URL(page.url()).pathname).toBe(`/review-cases/${created.id}`)

  expect(keys).toHaveLength(2)
  expect(keys[1]).toBe(keys[0])

  const list = await page.request.get('/api/v1/review-cases?limit=100&offset=0')
  const cases = ((await list.json()) as { items: { title: string }[] }).items
  expect(cases.filter((item) => item.title === 'Pilot-3 Retried Case')).toHaveLength(1)
})
