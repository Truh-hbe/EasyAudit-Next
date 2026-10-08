import { execFileSync } from 'node:child_process'

import { expect, test, type Page } from '@playwright/test'

import { confirmRemoveMember, dropdownOption, searchCandidates, submitCandidate, teamMemberRow, teamRegion } from './caseTeamView.js'

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
  const { drawer, response } = await searchCandidates(page, CASE_ID, roleKey, 'Candidate')
  expect(response.status()).toBe(200)
  await expect(dropdownOption(page, CANDIDATE_DISPLAY_NAME)).toBeVisible()
  return drawer
}

test('real Case team searches all exact roles, adds, removes, and protects final manager', async ({ page }) => {
  await page.goto(`/review-cases/${CASE_ID}`)
  await expect(page.getByRole('heading', { name: '登录' })).toBeVisible()
  await submitLogin(page)

  const team = teamRegion(page)
  await expect(team.getByText(LEAD_DISPLAY_NAME)).toBeVisible()
  const leadMember = teamMemberRow(page, LEAD_DISPLAY_NAME)
  await expect(leadMember.getByText('审查组长', { exact: true })).toBeVisible()

  for (const roleKey of ['lead', 'auditor', 'reviewer', 'observer']) {
    await searchRole(page, roleKey)
  }

  const drawer = await searchRole(page, 'reviewer')

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
  const addResponse = await submitCandidate(page, CASE_ID, drawer, CANDIDATE_DISPLAY_NAME)
  expect(addResponse.status()).toBe(201)
  expect((await membersReloadPromise).status()).toBe(200)
  expect((await activitiesReloadPromise).status()).toBe(200)
  await expect(team.getByText(CANDIDATE_DISPLAY_NAME)).toBeVisible()
  const candidateMember = teamMemberRow(page, CANDIDATE_DISPLAY_NAME)
  await expect(candidateMember.getByText('复核员', { exact: true })).toBeVisible()

  const activityDeleteReloadPromise = page.waitForResponse(
    (response) =>
      apiPath(response.url()) === `/api/v1/review-cases/${CASE_ID}/activities` &&
      response.request().method() === 'GET',
  )
  const memberDeleteResponse = await confirmRemoveMember(page, CASE_ID, CANDIDATE_USER_ID, CANDIDATE_DISPLAY_NAME)
  expect(memberDeleteResponse.status()).toBe(200)
  expect((await activityDeleteReloadPromise).status()).toBe(200)
  await expect(team.getByText(CANDIDATE_DISPLAY_NAME)).toHaveCount(0)
  await expect(page.getByText('移除审查成员')).toBeVisible()

  const finalManagerResponse = await confirmRemoveMember(
    page,
    CASE_ID,
    '00000000-0000-4000-8000-0000000003b1',
    LEAD_DISPLAY_NAME,
  )
  expect(finalManagerResponse.status()).toBe(409)
  // 409 暂无结构化原因：界面不显示后端 detail，提示里同时说明“最后一名管理者”这一可能原因。
  await expect(team.getByText(/不能移除最后一名管理者/)).toBeVisible()
  expect(await page.getByText('Cannot remove the final').count()).toBe(0)
  await expect(teamMemberRow(page, LEAD_DISPLAY_NAME)).toHaveCount(1)
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

  const team = teamRegion(page)
  await expect(team.getByText('M5.3 Browser Observer')).toBeVisible()
  const forbiddenResponsePromise = page.waitForResponse(
    (response) =>
      apiPath(response.url()) === `/api/v1/review-cases/${CASE_ID}/member-candidates` &&
      response.request().method() === 'GET',
  )
  await team.getByRole('button', { name: '添加成员' }).click()
  const drawer = page.getByRole('dialog', { name: '添加成员' })
  expect((await forbiddenResponsePromise).status()).toBe(403)
  // 打开抽屉后的首次候选读取就是 403；之后输入关键字不会再显示任何候选名称。
  await expect(drawer.getByRole('alert')).toContainText('当前用户没有管理审查团队的权限。')
  await drawer.getByLabel('成员').fill('Candidate')
  await expect(drawer.getByRole('alert')).toContainText('当前用户没有管理审查团队的权限。')
  await expect(page.getByText(CANDIDATE_DISPLAY_NAME)).toHaveCount(0)
})
