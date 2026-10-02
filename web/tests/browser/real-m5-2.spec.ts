import { execFileSync } from 'node:child_process'

import { expect, test, type Page } from '@playwright/test'

const LOGIN_NAME = 'browser-m5-2-user'
const PASSWORD = 'm5-2-browser-password-000'
const DISPLAY_NAME = 'M5.2 Browser User'

function apiPath(url: string): string {
  return new URL(url).pathname
}

function isCaseDetailPath(pathname: string): boolean {
  return /^\/api\/v1\/review-cases\/[^/]+$/.test(pathname)
}

async function submitLogin(page: Page) {
  const responsePromise = page.waitForResponse(
    (response) =>
      apiPath(response.url()) === '/api/v1/auth/login' &&
      response.request().method() === 'POST',
  )
  await page.getByLabel('登录名').fill(LOGIN_NAME)
  await page.getByLabel('密码').fill(PASSWORD)
  await page.getByRole('button', { name: '登录' }).click()
  const response = await responsePromise
  expect(response.status()).toBe(200)
}

async function expectStepTwoReload(page: Page, planId: string) {
  const planResponsePromise = page.waitForResponse(
    (response) =>
      apiPath(response.url()) === `/api/v1/review-plans/${planId}` &&
      response.request().method() === 'GET',
  )
  const catalogResponsePromise = page.waitForResponse(
    (response) =>
      apiPath(response.url()) === '/api/v1/review-catalog' &&
      response.request().method() === 'GET',
  )
  await page.reload()
  expect((await planResponsePromise).status()).toBe(200)
  expect((await catalogResponsePromise).status()).toBe(200)
  await expect(page.getByRole('heading', { name: '新建审查活动' })).toBeVisible()
}

test.describe.configure({ mode: 'serial', retries: 0 })

test.beforeAll(() => {
  execFileSync('python', ['tests/browser/seed_m5_2_real_acceptance.py'], {
    env: process.env,
    stdio: 'inherit',
  })
})
test('real plan-first flow creates both exact scenarios and recovers Case step', async ({
  page,
}) => {
  let planPostCount = 0
  page.on('request', (request) => {
    if (apiPath(request.url()) === '/api/v1/review-plans' && request.method() === 'POST') {
      planPostCount += 1
    }
  })

  await page.goto('/review-plans/new')
  await expect(page.getByRole('heading', { name: '登录' })).toBeVisible()
  await submitLogin(page)
  await expect(page.getByText(DISPLAY_NAME)).toBeVisible()

  await page.getByRole('link', { name: '审查活动' }).click()
  await page.getByRole('link', { name: '新建审查计划' }).click()
  await expect(page.getByRole('heading', { name: '新建审查计划' })).toBeVisible()
  await expect(page.getByText('process_review@1')).toBeVisible()
  await expect(page.getByText('compliance_review@1')).toBeVisible()

  const firstPlanResponsePromise = page.waitForResponse(
    (response) =>
      apiPath(response.url()) === '/api/v1/review-plans' &&
      response.request().method() === 'POST',
  )
  await page.getByLabel('计划名称').fill('M5.2 Process Plan')
  await page.getByRole('button', { name: '保存计划并继续' }).dblclick()
  const firstPlanResponse = await firstPlanResponsePromise
  expect(firstPlanResponse.status()).toBe(201)
  const firstPlan = (await firstPlanResponse.json()) as { id: string }
  expect(new URL(page.url()).pathname).toBe(
    `/review-plans/${firstPlan.id}/review-cases/new`,
  )
  await expect(page.getByRole('heading', { name: '新建审查活动' })).toBeVisible()
  expect(planPostCount).toBe(1)

  await expectStepTwoReload(page, firstPlan.id)
  await page.getByLabel('审查场景').selectOption('process_review@1')
  await expect(page.getByLabel('区域代码')).toBeVisible()
  await page.getByLabel('审查活动名称').fill('M5.2 Process Case')
  await page.getByLabel('区域代码').fill('area-a')
  await page.getByLabel('审查类型').fill('')

  const rejectedCasePromise = page.waitForResponse(
    (response) =>
      apiPath(response.url()) === '/api/v1/review-cases' &&
      response.request().method() === 'POST',
  )
  await page.getByRole('button', { name: '创建审查活动' }).click()
  expect((await rejectedCasePromise).status()).toBe(422)
  await expect(page.getByRole('alert')).toContainText('review_type')
  expect(planPostCount).toBe(1)

  const firstCasePromise = page.waitForResponse(
    (response) =>
      apiPath(response.url()) === '/api/v1/review-cases' &&
      response.request().method() === 'POST',
  )
  const firstDetailResponsePromise = page.waitForResponse(
    (response) =>
      isCaseDetailPath(apiPath(response.url())) && response.request().method() === 'GET',
  )
  await page.getByLabel('审查类型').fill('standard')
  await page.getByRole('button', { name: '创建审查活动' }).click()
  const firstCaseResponse = await firstCasePromise
  expect(firstCaseResponse.status()).toBe(201)
  const firstCase = (await firstCaseResponse.json()) as {
    id: string
    plan_id: string
    scenario_key: string
    scenario_version: number
    scenario_data: Record<string, string>
    planned_start_at: string | null
    planned_end_at: string | null
  }
  expect(firstCase.plan_id).toBe(firstPlan.id)
  expect(firstCase.scenario_key).toBe('process_review')
  expect(firstCase.scenario_version).toBe(1)
  expect(firstCase.scenario_data).toEqual({ area_code: 'area-a', review_type: 'standard' })
  expect(firstCase.planned_start_at).toBeNull()
  expect(firstCase.planned_end_at).toBeNull()
  expect(new URL(page.url()).pathname).toBe(`/review-cases/${firstCase.id}`)
  expect((await firstDetailResponsePromise).status()).toBe(200)
  await expect(page.getByRole('heading', { name: 'M5.2 Process Case' })).toBeVisible()

  await page.reload()
  await expect(page.getByRole('heading', { name: 'M5.2 Process Case' })).toBeVisible()
  expect(planPostCount).toBe(1)

  await page.getByRole('link', { name: '审查活动' }).click()
  await page.getByRole('link', { name: '新建审查计划' }).click()
  const secondPlanResponsePromise = page.waitForResponse(
    (response) =>
      apiPath(response.url()) === '/api/v1/review-plans' &&
      response.request().method() === 'POST',
  )
  await page.getByLabel('计划名称').fill('M5.2 Compliance Plan')
  await page.getByRole('button', { name: '保存计划并继续' }).click()
  const secondPlanResponse = await secondPlanResponsePromise
  expect(secondPlanResponse.status()).toBe(201)
  const secondPlan = (await secondPlanResponse.json()) as { id: string }
  await expect(page.getByRole('heading', { name: '新建审查活动' })).toBeVisible()
  await page.getByLabel('审查场景').selectOption('compliance_review@1')
  await expect(page.getByLabel('标准 / 依据')).toBeVisible()
  await page.getByLabel('审查活动名称').fill('M5.2 Compliance Case')
  await page.getByLabel('标准 / 依据').fill('standard-a')
  await page.getByLabel('范围摘要').fill('pilot scope')

  const secondCaseResponsePromise = page.waitForResponse(
    (response) =>
      apiPath(response.url()) === '/api/v1/review-cases' &&
      response.request().method() === 'POST',
  )
  const secondDetailResponsePromise = page.waitForResponse(
    (response) =>
      isCaseDetailPath(apiPath(response.url())) && response.request().method() === 'GET',
  )
  await page.getByRole('button', { name: '创建审查活动' }).click()
  const secondCaseResponse = await secondCaseResponsePromise
  expect(secondCaseResponse.status()).toBe(201)
  const secondCase = (await secondCaseResponse.json()) as {
    id: string
    plan_id: string
    scenario_key: string
    scenario_version: number
    scenario_data: Record<string, string>
  }
  expect(secondCase.plan_id).toBe(secondPlan.id)
  expect(secondCase.scenario_key).toBe('compliance_review')
  expect(secondCase.scenario_version).toBe(1)
  expect(secondCase.scenario_data).toEqual({
    standard_reference: 'standard-a',
    scope_summary: 'pilot scope',
  })
  expect(new URL(page.url()).pathname).toBe(`/review-cases/${secondCase.id}`)
  expect((await secondDetailResponsePromise).status()).toBe(200)
  await expect(page.getByRole('heading', { name: 'M5.2 Compliance Case' })).toBeVisible()
  expect(planPostCount).toBe(2)
})
