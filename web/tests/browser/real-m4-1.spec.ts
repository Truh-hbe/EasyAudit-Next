import { execFileSync } from 'node:child_process'

import { expect, test, type Page } from '@playwright/test'

const LOGIN_NAME = 'browser-compliance-lead'
const PASSWORD = 'compliance-password-000'
const DISPLAY_NAME = 'M4.1 Compliance Lead'
const CASE_TITLE = 'M4.1 Compliance Browser Case'
const CASE_ID = '00000000-0000-4000-8000-000000000377'
const FINDING_TITLE = 'M4.1 Compliance Observation'
const FINDING_ID = '00000000-0000-4000-8000-000000000386'

function apiPath(url: string): string {
  return new URL(url).pathname
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

test.describe.configure({ mode: 'serial', retries: 0 })

test.beforeAll(() => {
  execFileSync('python', ['tests/browser/seed_m4_1_real_acceptance.py'], {
    env: process.env,
    stdio: 'inherit',
  })
})

test('real compliance observation closes through shared Product routes and exact Scenario UI', async ({
  page,
}) => {
  await page.goto('/me/workbench')
  await expect(page.getByRole('heading', { name: '登录' })).toBeVisible()
  await submitLogin(page)

  await expect(page.getByText(DISPLAY_NAME)).toBeVisible()
  await expect(page.getByRole('heading', { name: '我的工作' })).toBeVisible()
  const complianceCaseLink = page.getByRole('link', { name: CASE_TITLE })
  await expect(complianceCaseLink).toBeVisible()
  await expect(page.getByText('Visible Product Case A')).toHaveCount(0)
  await expect(page.getByText('M3.5.5 End-to-End Product Case')).toHaveCount(0)

  const caseResponsePromise = page.waitForResponse(
    (response) =>
      apiPath(response.url()) === `/api/v1/review-cases/${CASE_ID}` &&
      response.request().method() === 'GET',
  )
  await complianceCaseLink.click()
  const caseResponse = await caseResponsePromise
  expect(caseResponse.status()).toBe(200)
  const casePayload = (await caseResponse.json()) as {
    scenario_key: string
    scenario_version: number
  }
  expect(casePayload.scenario_key).toBe('compliance_review')
  expect(casePayload.scenario_version).toBe(1)
  await expect(page.getByRole('heading', { name: CASE_TITLE })).toBeVisible()
  await expect(page.getByText('ISO 9001:2015')).toBeVisible()
  await expect(page.getByText('Assembly control and document retention')).toBeVisible()

  const findingLink = page.getByRole('link', { name: FINDING_TITLE })
  await expect(findingLink).toBeVisible()
  await findingLink.click()
  await expect(page.getByRole('heading', { name: FINDING_TITLE })).toBeVisible()
  await expect(page.getByText('7.5.3')).toBeVisible()
  await expect(page.getByText('observation', { exact: true })).toBeVisible()
  await expect(page.getByText('暂无 Action Item。')).toBeVisible()
  await expect(page.getByText('暂无 Finding Submission。')).toBeVisible()
  await expect(page.getByRole('button', { name: '接受 Observation' })).toBeVisible()
  await expect(page.getByRole('button', { name: '签发不符合项' })).toHaveCount(0)

  const transitionRequestPromise = page.waitForRequest(
    (request) =>
      apiPath(request.url()) === `/api/v1/findings/${FINDING_ID}/transitions` &&
      request.method() === 'POST',
  )
  const transitionResponsePromise = page.waitForResponse(
    (response) =>
      apiPath(response.url()) === `/api/v1/findings/${FINDING_ID}/transitions` &&
      response.request().method() === 'POST',
  )
  await page.getByRole('button', { name: '接受 Observation' }).click()

  const transitionRequest = await transitionRequestPromise
  const requestPayload = transitionRequest.postDataJSON() as {
    action: string
    reason: string | null
  }
  expect(requestPayload).toEqual({ action: 'accept_observation', reason: null })
  const transitionResponse = await transitionResponsePromise
  expect(transitionResponse.status()).toBe(200)
  const transitionPayload = (await transitionResponse.json()) as { lifecycle: string }
  expect(transitionPayload.lifecycle).toBe('closed')

  await expect(page.locator('.status-pill')).toHaveText('closed')
  await expect(page.getByText('Observation 已接受并闭环。')).toBeVisible()
  await expect(page.getByRole('button', { name: '接受 Observation' })).toHaveCount(0)
  await expect(page.getByText('暂无 Action Item。')).toBeVisible()
  await expect(page.getByText('暂无 Finding Submission。')).toBeVisible()
  await expect(page.getByText('finding.transitioned', { exact: true })).toBeVisible()
})
