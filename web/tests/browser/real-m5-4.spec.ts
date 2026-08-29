import { execFileSync } from 'node:child_process'

import { expect, test, type Page } from '@playwright/test'

const ADMIN_LOGIN_NAME = 'browser-m5-4-admin'
const ADMIN_PASSWORD = 'm5-4-browser-admin-password-000'
const MANAGER_DISPLAY_NAME = 'M5.4 Browser Case Manager'
const NEW_USER_DISPLAY_NAME = 'M5.4 Browser Created User'
const NEW_USER_LOGIN_NAME = 'browser-m5-4-created'
const NEW_USER_INITIAL_PASSWORD = 'm5-4-browser-created-password-000'
const NEW_USER_CHANGED_PASSWORD = 'm5-4-browser-changed-password-111'
const RESET_PASSWORD = 'm5-4-browser-reset-password-222'
const RESET_CHANGED_PASSWORD = 'm5-4-browser-reset-changed-333'
const DEPARTMENT_NAME = 'M5.4 Pilot Department'

function apiPath(url: string): string {
  return new URL(url).pathname
}

async function submitLogin(page: Page, loginName: string, password: string) {
  const responsePromise = page.waitForResponse(
    (response) =>
      apiPath(response.url()) === '/api/v1/auth/login' &&
      response.request().method() === 'POST',
  )
  await page.getByLabel('登录名').fill(loginName)
  await page.getByLabel('密码').fill(password)
  await page.getByRole('button', { name: '登录' }).click()
  const response = await responsePromise
  expect(response.status()).toBe(200)
}

async function submitPasswordChange(page: Page, currentPassword: string, newPassword: string) {
  const responsePromise = page.waitForResponse(
    (response) =>
      apiPath(response.url()) === '/api/v1/me/password' &&
      response.request().method() === 'POST',
  )
  await page.getByLabel('当前密码').fill(currentPassword)
  await page.getByLabel('新密码', { exact: true }).fill(newPassword)
  await page.getByLabel('确认新密码').fill(newPassword)
  await page.getByRole('button', { name: '修改密码' }).click()
  expect((await responsePromise).status()).toBe(200)
}

test.describe.configure({ mode: 'serial', retries: 0 })

test.beforeAll(() => {
  execFileSync('python', ['tests/browser/seed_m5_4_real_acceptance.py'], {
    env: process.env,
    stdio: 'inherit',
  })
})

test('real administrator configures users, protects Case managers, and resets credentials', async ({
  page,
  browser,
}) => {
  await page.goto('/admin')
  await expect(page.getByRole('heading', { name: '登录' })).toBeVisible()
  await submitLogin(page, ADMIN_LOGIN_NAME, ADMIN_PASSWORD)
  await expect(page.getByRole('heading', { name: '管理设置' })).toBeVisible()
  await expect(page.getByText('M5.4 Browser Acceptance')).toBeVisible()
  await expect(page.getByText('process_review@1')).toBeVisible()
  await expect(page.getByText('compliance_review@1')).toBeVisible()
  await expect(page.getByText('代码已注册')).toHaveCount(2)
  await expect(page.getByText('可用')).toHaveCount(2)

  const departmentResponsePromise = page.waitForResponse(
    (response) =>
      apiPath(response.url()) === '/api/v1/admin/departments' &&
      response.request().method() === 'POST',
  )
  await page.getByLabel('部门名称').fill(DEPARTMENT_NAME)
  await page.getByRole('button', { name: '创建部门' }).click()
  expect((await departmentResponsePromise).status()).toBe(201)
  await expect(page.getByText(DEPARTMENT_NAME)).toBeVisible()

  const userResponsePromise = page.waitForResponse(
    (response) =>
      apiPath(response.url()) === '/api/v1/admin/users' &&
      response.request().method() === 'POST',
  )
  await page.getByLabel('显示名称').fill(NEW_USER_DISPLAY_NAME)
  await page.getByLabel('登录名').fill(NEW_USER_LOGIN_NAME)
  await page.getByLabel('初始密码').fill(NEW_USER_INITIAL_PASSWORD)
  await page.getByLabel('主要部门').selectOption({ label: DEPARTMENT_NAME })
  await page.getByRole('button', { name: '创建用户' }).click()
  expect((await userResponsePromise).status()).toBe(201)
  await expect(page.getByText(NEW_USER_DISPLAY_NAME)).toBeVisible()

  const targetContext = await browser.newContext({
    baseURL: 'https://127.0.0.1:4173',
    ignoreHTTPSErrors: true,
  })
  const targetPage = await targetContext.newPage()
  try {
    await targetPage.goto('/me/workbench')
    await expect(targetPage.getByRole('heading', { name: '登录' })).toBeVisible()
    await submitLogin(targetPage, NEW_USER_LOGIN_NAME, NEW_USER_INITIAL_PASSWORD)
    await expect(targetPage.getByRole('heading', { name: '需要修改密码' })).toBeVisible()
    await submitPasswordChange(targetPage, NEW_USER_INITIAL_PASSWORD, NEW_USER_CHANGED_PASSWORD)
    await expect(targetPage.getByRole('heading', { name: '我的工作' })).toBeVisible()

    const managerRow = page.locator('li').filter({ hasText: MANAGER_DISPLAY_NAME }).first()
    await managerRow.getByRole('button', { name: '编辑' }).click()
    await page.getByRole('checkbox', { name: '用户启用' }).uncheck()
    const conflictResponsePromise = page.waitForResponse(
      (response) =>
        apiPath(response.url()).includes('/api/v1/admin/users/') &&
        response.request().method() === 'PATCH',
    )
    await page.getByRole('button', { name: '保存用户' }).click()
    expect((await conflictResponsePromise).status()).toBe(409)
    await expect(page.getByRole('status')).toContainText('状态冲突')

    await page.getByRole('checkbox', { name: '用户启用' }).check()
    const restoreManagerPromise = page.waitForResponse(
      (response) =>
        apiPath(response.url()).includes('/api/v1/admin/users/') &&
        response.request().method() === 'PATCH',
    )
    await page.getByRole('button', { name: '保存用户' }).click()
    expect((await restoreManagerPromise).status()).toBe(200)

    const createdUserRow = page.locator('li').filter({ hasText: NEW_USER_DISPLAY_NAME }).first()
    await createdUserRow.getByRole('button', { name: '编辑' }).click()
    await page.getByRole('checkbox', { name: '用户启用' }).uncheck()
    const disableUserPromise = page.waitForResponse(
      (response) =>
        apiPath(response.url()).includes('/api/v1/admin/users/') &&
        response.request().method() === 'PATCH',
    )
    await page.getByRole('button', { name: '保存用户' }).click()
    expect((await disableUserPromise).status()).toBe(200)
    await expect(page.getByText(NEW_USER_DISPLAY_NAME)).toBeVisible()

    await page.locator('li').filter({ hasText: NEW_USER_DISPLAY_NAME }).first().getByRole('button', { name: '编辑' }).click()
    await page.getByRole('checkbox', { name: '用户启用' }).check()
    const enableUserPromise = page.waitForResponse(
      (response) =>
        apiPath(response.url()).includes('/api/v1/admin/users/') &&
        response.request().method() === 'PATCH',
    )
    await page.getByRole('button', { name: '保存用户' }).click()
    expect((await enableUserPromise).status()).toBe(200)

    await page.getByLabel('目标用户').selectOption({ label: NEW_USER_DISPLAY_NAME })
    await page.getByLabel('临时密码').fill(RESET_PASSWORD)
    const resetResponsePromise = page.waitForResponse(
      (response) =>
        apiPath(response.url()).includes('/credential-reset') &&
        response.request().method() === 'POST',
    )
    await page.getByRole('button', { name: '重置凭据' }).click()
    expect((await resetResponsePromise).status()).toBe(200)
    await expect(page.getByRole('status')).toContainText('临时凭据已重置')
    await expect(page.getByLabel('临时密码')).toHaveValue('')

    await targetPage.reload()
    await expect(targetPage.getByRole('heading', { name: '登录' })).toBeVisible()
    await submitLogin(targetPage, NEW_USER_LOGIN_NAME, RESET_PASSWORD)
    await expect(targetPage.getByRole('heading', { name: '需要修改密码' })).toBeVisible()
    await submitPasswordChange(targetPage, RESET_PASSWORD, RESET_CHANGED_PASSWORD)
    await expect(targetPage.getByRole('heading', { name: '我的工作' })).toBeVisible()
  } finally {
    await targetContext.close()
  }
})
