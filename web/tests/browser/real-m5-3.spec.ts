import { execFileSync } from 'node:child_process'

import { expect, test, type Page } from '@playwright/test'

const CASE_ID = '00000000-0000-4000-8000-0000000003b5'
const CANDIDATE_USER_ID = '00000000-0000-4000-8000-0000000003b2'
const LOGIN_NAME = 'browser-m5-3-lead'
const PASSWORD = 'm5-3-browser-password-000'
const OBSERVER_LOGIN_NAME = 'browser-m5-3-observer'
const OBSERVER_PASSWORD = 'm5-3-observer-password-000'
const LEAD_DISPLAY_NAME = 'M5.3 Browser Team Lead'
const CANDIDATE_DISPLAY_NAME = 'M5.3 Browser Candidate'

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
  expect((await responsePromise).status()).toBe(200)
}

test.describe.configure({ mode: 'serial', retries: 0 })

test.beforeAll(() => {
  execFileSync('python', ['tests/browser/seed_m5_3_real_acceptance.py'], {
    env: process.env,
    stdio: 'inherit',
  })
})

async function searchRole(page: Page, roleKey: string) {
  const team = page.getByRole('region', { name: '团队管理' })
  await team.getByLabel('团队角色').selectOption(roleKey)
  await team.getByLabel('搜索成员').fill('Candidate')
  const responsePromise = page.waitForResponse(
    (response) =>
      apiPath(response.url()) === `/api/v1/review-cases/${CASE_ID}/member-candidates` &&
      response.request().method() === 'GET',
  )
  await team.getByRole('button', { name: '搜索候选人' }).click()
  expect((await responsePromise).status()).toBe(200)
  const candidateList = team.getByRole('list', { name: '候选成员' })
  await expect(candidateList.getByText(CANDIDATE_DISPLAY_NAME)).toBeVisible()
}

test('real Case team searches all exact roles, adds, removes, and protects final manager', async ({ page }) => {
  await page.goto(`/review-cases/${CASE_ID}`)
  await expect(page.getByRole('heading', { name: '登录' })).toBeVisible()
  await submitLogin(page)

  const team = page.getByRole('region', { name: '团队管理' })
  await expect(team.getByText(LEAD_DISPLAY_NAME)).toBeVisible()
  const leadMember = team.locator('li').filter({ hasText: LEAD_DISPLAY_NAME })
  await expect(leadMember.getByText('审查组长', { exact: true })).toBeVisible()

  for (const roleKey of ['lead', 'auditor', 'reviewer', 'observer']) {
    await searchRole(page, roleKey)
  }

  await searchRole(page, 'reviewer')
  const candidateList = team.getByRole('list', { name: '候选成员' })

  const addResponsePromise = page.waitForResponse(
    (response) =>
      apiPath(response.url()) === `/api/v1/review-cases/${CASE_ID}/members` &&
      response.request().method() === 'POST',
  )
  const membersReloadPromise = page.waitForResponse(
    (response) =>
      apiPath(response.url()) === `/api/v1/review-cases/${CASE_ID}/members` &&
      response.request().method() === 'GET',
  )
  const activitiesReloadPromise = page.waitForResponse(
    (response) =>
      apiPath(response.url()) === `/api/v1/review-cases/${CASE_ID}/activities` &&
      response.request().method() === 'GET',
  )
  await candidateList.getByRole('button', { name: '添加' }).click()
  expect((await addResponsePromise).status()).toBe(201)
  expect((await membersReloadPromise).status()).toBe(200)
  expect((await activitiesReloadPromise).status()).toBe(200)
  await expect(team.getByText(CANDIDATE_DISPLAY_NAME)).toBeVisible()
  const candidateMember = team.locator('li').filter({ hasText: CANDIDATE_DISPLAY_NAME })
  await expect(candidateMember.getByText('复核员', { exact: true })).toBeVisible()

  const memberDeleteResponsePromise = page.waitForResponse(
    (response) =>
      apiPath(response.url()) ===
        `/api/v1/review-cases/${CASE_ID}/members/${CANDIDATE_USER_ID}` &&
      response.request().method() === 'DELETE',
  )
  const activityDeleteReloadPromise = page.waitForResponse(
    (response) =>
      apiPath(response.url()) === `/api/v1/review-cases/${CASE_ID}/activities` &&
      response.request().method() === 'GET',
  )
  await candidateMember.getByRole('button', { name: '移除' }).click()
  expect((await memberDeleteResponsePromise).status()).toBe(200)
  expect((await activityDeleteReloadPromise).status()).toBe(200)
  await expect(team.getByText(CANDIDATE_DISPLAY_NAME)).toHaveCount(0)
  await expect(page.getByText('review_case.member_removed')).toBeVisible()

  const finalManagerResponsePromise = page.waitForResponse(
    (response) =>
      apiPath(response.url()) ===
        `/api/v1/review-cases/${CASE_ID}/members/${'00000000-0000-4000-8000-0000000003b1'}` &&
      response.request().method() === 'DELETE',
  )
  await leadMember.getByRole('button', { name: '移除' }).click()
  expect((await finalManagerResponsePromise).status()).toBe(409)
  await expect(team.getByText('团队状态发生冲突，请刷新后重试。')).toBeVisible()
  await expect(team.locator('li').filter({ hasText: LEAD_DISPLAY_NAME })).toHaveCount(1)
})

test('real non-manager sees safe permission failure without candidate names', async ({ page }) => {
  await page.goto(`/review-cases/${CASE_ID}`)
  await expect(page.getByRole('heading', { name: '登录' })).toBeVisible()
  const loginResponsePromise = page.waitForResponse(
    (response) =>
      apiPath(response.url()) === '/api/v1/auth/login' &&
      response.request().method() === 'POST',
  )
  await page.getByLabel('登录名').fill(OBSERVER_LOGIN_NAME)
  await page.getByLabel('密码').fill(OBSERVER_PASSWORD)
  await page.getByRole('button', { name: '登录' }).click()
  expect((await loginResponsePromise).status()).toBe(200)

  const team = page.getByRole('region', { name: '团队管理' })
  await expect(team.getByText('M5.3 Browser Observer')).toBeVisible()
  await team.getByLabel('团队角色').selectOption('reviewer')
  await team.getByLabel('搜索成员').fill('Candidate')
  const forbiddenResponsePromise = page.waitForResponse(
    (response) =>
      apiPath(response.url()) === `/api/v1/review-cases/${CASE_ID}/member-candidates` &&
      response.request().method() === 'GET',
  )
  await team.getByRole('button', { name: '搜索候选人' }).click()
  expect((await forbiddenResponsePromise).status()).toBe(403)
  await expect(team.getByRole('alert')).toContainText('当前用户没有管理审查团队的权限。')
  await expect(team.getByText(CANDIDATE_DISPLAY_NAME)).toHaveCount(0)
})
