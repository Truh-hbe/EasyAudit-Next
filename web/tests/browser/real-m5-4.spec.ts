import { execFileSync } from 'node:child_process'

import { expect, test, type Page } from '@playwright/test'

import { confirmRemoveMember, dropdownOption, searchCandidates, submitCandidate, teamMemberRow } from './caseTeamView.js'

const ADMIN_LOGIN_NAME = 'browser-m5-4-admin'
const ADMIN_PASSWORD = 'm5-4-browser-admin-password-000'
const MANAGER_DISPLAY_NAME = 'M5.4 Browser Case Manager'
const MANAGER_LOGIN_NAME = 'browser-m5-4-manager'
const MANAGER_PASSWORD = 'm5-4-browser-manager-password-000'
const MANAGER_USER_ID = '00000000-0000-4000-8000-0000000003c2'
const CASE_ID = '00000000-0000-4000-8000-0000000003c7'
const NEW_USER_DISPLAY_NAME = 'M5.4 Browser Created User'
const NEW_USER_LOGIN_NAME = 'browser-m5-4-created'
const NEW_USER_INITIAL_PASSWORD = 'm5-4-browser-created-password-000'
const NEW_USER_CHANGED_PASSWORD = 'm5-4-browser-changed-password-111'
const RESET_PASSWORD = 'm5-4-browser-reset-password-222'
const RESET_CHANGED_PASSWORD = 'm5-4-browser-reset-changed-333'
const DEPARTMENT_NAME = 'M5.4 Pilot Department'
const EDITED_DEPARTMENT_NAME = 'M5.4 Pilot Department Edited'

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

async function confirmDisableUser(page: Page) {
  await page.getByRole('dialog', { name: '停用用户' }).getByRole('button', { name: '确认停用' }).click()
}

async function addLeadMember(page: Page, search: string, displayName: string) {
  const { drawer, response } = await searchCandidates(page, CASE_ID, 'lead', search)
  expect(response.status()).toBe(200)
  await expect(dropdownOption(page, displayName)).toBeVisible()
  expect((await submitCandidate(page, CASE_ID, drawer, displayName)).status()).toBe(201)
  await expect(teamMemberRow(page, displayName)).toBeVisible()
}

async function removeMember(page: Page, userId: string, displayName: string) {
  expect((await confirmRemoveMember(page, CASE_ID, userId, displayName)).status()).toBe(200)
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
  await page.getByRole('button', { name: '新建部门' }).click()
  const departmentDrawer = page.getByRole('dialog', { name: '新建部门' })
  await departmentDrawer.getByLabel('部门名称').fill(DEPARTMENT_NAME)
  await departmentDrawer.getByRole('button', { name: '创建部门' }).click()
  expect((await departmentResponsePromise).status()).toBe(201)
  const departments = page.getByRole('region', { name: '部门' })
  const departmentRow = departments.getByRole('row').filter({ hasText: DEPARTMENT_NAME })
  await expect(departmentRow).toBeVisible()

  await departmentRow.getByRole('button', { name: '编辑' }).click()
  const departmentEditDrawer = page.getByRole('dialog', { name: '编辑部门' })
  await departmentEditDrawer.getByLabel('部门名称').fill(EDITED_DEPARTMENT_NAME)
  const departmentEditResponsePromise = page.waitForResponse(
    (response) =>
      apiPath(response.url()).startsWith('/api/v1/admin/departments/') &&
      response.request().method() === 'PATCH',
  )
  await departmentEditDrawer.getByRole('button', { name: '保存部门' }).click()
  expect((await departmentEditResponsePromise).status()).toBe(200)
  const editedDepartmentRow = departments.getByRole('row').filter({ hasText: EDITED_DEPARTMENT_NAME })
  await expect(editedDepartmentRow).toBeVisible()

  const userResponsePromise = page.waitForResponse(
    (response) =>
      apiPath(response.url()) === '/api/v1/admin/users' &&
      response.request().method() === 'POST',
  )
  await page.getByRole('button', { name: '新建用户' }).click()
  const userDrawer = page.getByRole('dialog', { name: '新建用户' })
  await userDrawer.getByLabel('显示名称').fill(NEW_USER_DISPLAY_NAME)
  await userDrawer.getByLabel('登录名').fill(NEW_USER_LOGIN_NAME)
  await userDrawer.getByLabel('初始密码').fill(NEW_USER_INITIAL_PASSWORD)
  await userDrawer.getByLabel('主要部门').click()
  await page.getByTitle(EDITED_DEPARTMENT_NAME, { exact: true }).last().click()
  await userDrawer.getByRole('button', { name: '创建用户' }).click()
  expect((await userResponsePromise).status()).toBe(201)
  const users = page.getByRole('region', { name: '用户' })
  await expect(users.getByRole('row').filter({ hasText: NEW_USER_DISPLAY_NAME })).toBeVisible()

  const targetContext = await browser.newContext({
    baseURL: `https://127.0.0.1:${process.env.EASYAUDIT_WEB_PORT ?? '4173'}`,
    ignoreHTTPSErrors: true,
  })
  const targetPage = await targetContext.newPage()
  const managerContext = await browser.newContext({
    baseURL: `https://127.0.0.1:${process.env.EASYAUDIT_WEB_PORT ?? '4173'}`,
    ignoreHTTPSErrors: true,
  })
  const managerPage = await managerContext.newPage()
  try {
    await targetPage.goto('/me/workbench')
    await expect(targetPage.getByRole('heading', { name: '登录' })).toBeVisible()
    await submitLogin(targetPage, NEW_USER_LOGIN_NAME, NEW_USER_INITIAL_PASSWORD)
    await expect(targetPage.getByRole('heading', { name: '需要修改密码' })).toBeVisible()
    await submitPasswordChange(targetPage, NEW_USER_INITIAL_PASSWORD, NEW_USER_CHANGED_PASSWORD)
    await expect(targetPage.getByRole('heading', { name: '我的工作' })).toBeVisible()

    await managerPage.goto(`/review-cases/${CASE_ID}`)
    await expect(managerPage.getByRole('heading', { name: '登录' })).toBeVisible()
    await submitLogin(managerPage, MANAGER_LOGIN_NAME, MANAGER_PASSWORD)
    await expect(managerPage.getByRole('heading', { name: 'M5.4 Browser Manager Case' })).toBeVisible()
    await addLeadMember(managerPage, NEW_USER_DISPLAY_NAME, NEW_USER_DISPLAY_NAME)
    await removeMember(managerPage, MANAGER_USER_ID, MANAGER_DISPLAY_NAME)

    const createdUserRow = users.getByRole('row').filter({ hasText: NEW_USER_DISPLAY_NAME })
    await createdUserRow.getByRole('button', { name: '编辑' }).click()
    const userEditDrawer = page.getByRole('dialog', { name: '编辑用户' })
    await userEditDrawer.getByRole('checkbox', { name: '用户启用' }).uncheck()
    const conflictResponsePromise = page.waitForResponse(
      (response) =>
        apiPath(response.url()).includes('/api/v1/admin/users/') &&
        response.request().method() === 'PATCH',
    )
    await userEditDrawer.getByRole('button', { name: '保存用户' }).click()
    await confirmDisableUser(page)
    expect((await conflictResponsePromise).status()).toBe(409)
    await expect(userEditDrawer.getByRole('alert').filter({ hasText: '数据已变化' })).toBeVisible()

    await targetPage.goto(`/review-cases/${CASE_ID}`)
    await expect(targetPage.getByRole('heading', { name: 'M5.4 Browser Manager Case' })).toBeVisible()
    await addLeadMember(targetPage, MANAGER_DISPLAY_NAME, MANAGER_DISPLAY_NAME)

    const disableUserPromise = page.waitForResponse(
      (response) =>
        apiPath(response.url()).includes('/api/v1/admin/users/') &&
        response.request().method() === 'PATCH',
    )
    await userEditDrawer.getByRole('button', { name: '保存用户' }).click()
    await confirmDisableUser(page)
    expect((await disableUserPromise).status()).toBe(200)
    await expect(users.getByRole('row').filter({ hasText: NEW_USER_DISPLAY_NAME })).toBeVisible()

    await users.getByRole('row').filter({ hasText: NEW_USER_DISPLAY_NAME }).getByRole('button', { name: '编辑' }).click()
    await userEditDrawer.getByRole('checkbox', { name: '用户启用' }).check()
    const enableUserPromise = page.waitForResponse(
      (response) =>
        apiPath(response.url()).includes('/api/v1/admin/users/') &&
        response.request().method() === 'PATCH',
    )
    await userEditDrawer.getByRole('button', { name: '保存用户' }).click()
    expect((await enableUserPromise).status()).toBe(200)
    await expect(userEditDrawer).toHaveCount(0)

    await page.getByLabel('目标用户').click()
    await page.getByTitle(NEW_USER_DISPLAY_NAME, { exact: true }).last().click()
    await page.getByLabel('临时密码').fill(RESET_PASSWORD)
    const resetResponsePromise = page.waitForResponse(
      (response) =>
        apiPath(response.url()).includes('/credential-reset') &&
        response.request().method() === 'POST',
    )
    await page.getByRole('button', { name: '重置凭据' }).click()
    await page.getByRole('dialog', { name: '重置凭据' }).getByRole('button', { name: '确认重置' }).click()
    expect((await resetResponsePromise).status()).toBe(200)
    await expect(page.getByText('临时凭据已重置')).toBeVisible()
    await expect(page.getByLabel('临时密码')).toHaveValue('')

    await targetPage.reload()
    await expect(targetPage.getByRole('heading', { name: '登录' })).toBeVisible()
    await submitLogin(targetPage, NEW_USER_LOGIN_NAME, RESET_PASSWORD)
    await expect(targetPage.getByRole('heading', { name: '需要修改密码' })).toBeVisible()
    await submitPasswordChange(targetPage, RESET_PASSWORD, RESET_CHANGED_PASSWORD)
    await expect(targetPage.getByRole('heading', { name: 'M5.4 Browser Manager Case' })).toBeVisible()
  } finally {
    await managerContext.close()
    await targetContext.close()
  }
})
