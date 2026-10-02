import { execFileSync } from 'node:child_process'

import { expect, test, type Page, type Route } from '@playwright/test'

const ADMIN_LOGIN_NAME = 'browser-m5-5-admin'
const ADMIN_PASSWORD = 'm5-5-browser-admin-password-000'
const FIRST_DISPLAY_NAME = 'M5.5 Browser Pilot Lead'
const FIRST_LOGIN_NAME = 'browser-m5-5-lead'
const FIRST_INITIAL_PASSWORD = 'm5-5-browser-lead-initial-000'
const FIRST_CHANGED_PASSWORD = 'm5-5-browser-lead-changed-111'
const FIRST_RESET_PASSWORD = 'm5-5-browser-lead-reset-222'
const FIRST_RESET_CHANGED_PASSWORD = 'm5-5-browser-lead-final-333'
const SECOND_DISPLAY_NAME = 'M5.5 Browser Pilot Collaborator'
const SECOND_LOGIN_NAME = 'browser-m5-5-collaborator'
const SECOND_INITIAL_PASSWORD = 'm5-5-browser-collab-initial-000'
const SECOND_CHANGED_PASSWORD = 'm5-5-browser-collab-changed-111'
const INACTIVE_DISPLAY_NAME = 'M5.5 Browser Inactive Candidate'
const INACTIVE_LOGIN_NAME = 'browser-m5-5-inactive'
const INACTIVE_PASSWORD = 'm5-5-browser-inactive-password-000'
const FOREIGN_USER_ID = '00000000-0000-4000-8000-000000000561'
const FOREIGN_PLAN_ID = '00000000-0000-4000-8000-000000000564'
const FOREIGN_CASE_ID = '00000000-0000-4000-8000-000000000565'
const ADMIN_CASE_ID = '00000000-0000-4000-8000-000000000556'
const DEPARTMENT_NAME = 'M5.5 Pilot Department'
const EDITED_DEPARTMENT_NAME = 'M5.5 Pilot Department Edited'

function apiPath(url: string): string {
  return new URL(url).pathname
}

function isCaseDetailPath(pathname: string): boolean {
  return /^\/api\/v1\/review-cases\/[^/]+$/.test(pathname)
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

async function submitFailedLogin(page: Page, loginName: string, password: string) {
  const responsePromise = page.waitForResponse(
    (response) =>
      apiPath(response.url()) === '/api/v1/auth/login' &&
      response.request().method() === 'POST',
  )
  await page.getByLabel('登录名').fill(loginName)
  await page.getByLabel('密码').fill(password)
  await page.getByRole('button', { name: '登录' }).click()
  expect((await responsePromise).status()).toBe(401)
  await expect(page.getByRole('alert')).toContainText('登录名或密码无效')
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

async function createAdminUser(
  page: Page,
  displayName: string,
  loginName: string,
  initialPassword: string,
): Promise<string> {
  const responsePromise = page.waitForResponse(
    (response) =>
      apiPath(response.url()) === '/api/v1/admin/users' &&
      response.request().method() === 'POST',
  )
  await page.getByLabel('显示名称').fill(displayName)
  await page.getByLabel('登录名').fill(loginName)
  await page.getByLabel('初始密码').fill(initialPassword)
  await page.getByLabel('主要部门').selectOption({ label: EDITED_DEPARTMENT_NAME })
  await page.getByRole('button', { name: '创建用户' }).click()
  const response = await responsePromise
  expect(response.status()).toBe(201)
  const body = (await response.json()) as { id: string }
  await expect(
    page.getByRole('region', { name: '用户' }).getByRole('listitem').filter({ hasText: displayName }),
  ).toBeVisible()
  return body.id
}

async function deactivateAdminUser(page: Page, displayName: string) {
  const users = page.getByRole('region', { name: '用户' })
  const row = users.getByRole('listitem').filter({ hasText: displayName })
  await row.getByRole('button', { name: '编辑' }).click()
  await page.getByLabel('用户启用').uncheck()
  const responsePromise = page.waitForResponse(
    (response) =>
      apiPath(response.url()).includes('/api/v1/admin/users/') &&
      response.request().method() === 'PATCH',
  )
  await page.getByRole('button', { name: '保存用户' }).click()
  expect((await responsePromise).status()).toBe(200)
  await expect(row).toContainText('停用')
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

async function createPlan(page: Page, title: string): Promise<string> {
  const responsePromise = page.waitForResponse(
    (response) =>
      apiPath(response.url()) === '/api/v1/review-plans' &&
      response.request().method() === 'POST',
  )
  await page.getByLabel('计划名称').fill(title)
  await page.getByRole('button', { name: '保存计划并继续' }).click()
  const response = await responsePromise
  expect(response.status()).toBe(201)
  const body = (await response.json()) as { id: string }
  await expect(page.getByRole('heading', { name: '新建审查活动' })).toBeVisible()
  return body.id
}

async function addMember(
  page: Page,
  caseId: string,
  roleKey: string,
  query: string,
  displayName: string,
): Promise<void> {
  const team = page.getByRole('region', { name: '团队管理' })
  await team.getByLabel('团队角色').selectOption(roleKey)
  await team.getByLabel('搜索成员').fill(query)
  const searchResponsePromise = page.waitForResponse(
    (response) =>
      apiPath(response.url()) === `/api/v1/review-cases/${caseId}/member-candidates` &&
      response.request().method() === 'GET',
  )
  await team.getByRole('button', { name: '搜索候选人' }).click()
  expect((await searchResponsePromise).status()).toBe(200)
  const candidate = team
    .getByRole('list', { name: '候选成员' })
    .getByRole('listitem')
    .filter({ hasText: displayName })
  await expect(candidate).toBeVisible()
  const addResponsePromise = page.waitForResponse(
    (response) =>
      apiPath(response.url()) === `/api/v1/review-cases/${caseId}/members` &&
      response.request().method() === 'POST',
  )
  await candidate.getByRole('button', { name: '添加' }).click()
  expect((await addResponsePromise).status()).toBe(201)
  await expect(team.locator('ul.surface-list').first().getByText(displayName)).toBeVisible()
}

async function removeMember(
  page: Page,
  caseId: string,
  userId: string,
  displayName: string,
): Promise<number> {
  const team = page.getByRole('region', { name: '团队管理' })
  const member = team.locator('ul.surface-list').first().locator('li').filter({ hasText: displayName })
  await expect(member).toBeVisible()
  const responsePromise = page.waitForResponse(
    (response) =>
      apiPath(response.url()) === `/api/v1/review-cases/${caseId}/members/${userId}` &&
      response.request().method() === 'DELETE',
  )
  await member.getByRole('button', { name: '移除' }).click()
  const response = await responsePromise
  return response.status()
}

async function fetchStatus(page: Page, path: string): Promise<{ status: number; body: string }> {
  return page.evaluate(async (requestPath) => {
    const response = await fetch(requestPath)
    return { status: response.status, body: await response.text() }
  }, path)
}

test.describe.configure({ mode: 'serial', retries: 0 })

test.beforeAll(() => {
  execFileSync('python', ['tests/browser/seed_m5_5_real_acceptance.py'], {
    env: process.env,
    stdio: 'inherit',
  })
})

test('real M5.5 pilot completes exact cases, recovery, isolation, and collaboration', async ({
  page,
  browser,
}) => {
  await page.goto('/admin')
  await expect(page.getByRole('heading', { name: '登录' })).toBeVisible()
  await submitLogin(page, ADMIN_LOGIN_NAME, ADMIN_PASSWORD)
  await expect(page.getByRole('heading', { name: '管理设置' })).toBeVisible()
  await expect(page.getByText('M5.5 Browser Controlled Pilot')).toBeVisible()
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
  const departments = page.getByRole('region', { name: '部门' })
  const departmentRow = departments.getByRole('listitem').filter({ hasText: DEPARTMENT_NAME })
  await expect(departmentRow).toBeVisible()
  await departmentRow.getByRole('button', { name: '编辑' }).click()
  await departments.getByLabel('部门名称').fill(EDITED_DEPARTMENT_NAME)
  const departmentEditResponsePromise = page.waitForResponse(
    (response) =>
      apiPath(response.url()).startsWith('/api/v1/admin/departments/') &&
      response.request().method() === 'PATCH',
  )
  await departments.getByRole('button', { name: '保存部门' }).click()
  expect((await departmentEditResponsePromise).status()).toBe(200)
  await expect(departments.getByRole('listitem').filter({ hasText: EDITED_DEPARTMENT_NAME })).toBeVisible()

  const firstUserId = await createAdminUser(
    page,
    FIRST_DISPLAY_NAME,
    FIRST_LOGIN_NAME,
    FIRST_INITIAL_PASSWORD,
  )
  const secondUserId = await createAdminUser(
    page,
    SECOND_DISPLAY_NAME,
    SECOND_LOGIN_NAME,
    SECOND_INITIAL_PASSWORD,
  )
  await createAdminUser(page, INACTIVE_DISPLAY_NAME, INACTIVE_LOGIN_NAME, INACTIVE_PASSWORD)
  await deactivateAdminUser(page, INACTIVE_DISPLAY_NAME)

  const firstContext = await browser.newContext({ baseURL: 'https://127.0.0.1:4173', ignoreHTTPSErrors: true })
  const firstPage = await firstContext.newPage()
  const secondContext = await browser.newContext({ baseURL: 'https://127.0.0.1:4173', ignoreHTTPSErrors: true })
  const secondPage = await secondContext.newPage()
  let planPostCount = 0
  let casePostCount = 0
  firstPage.on('request', (request) => {
    if (apiPath(request.url()) === '/api/v1/review-plans' && request.method() === 'POST') planPostCount += 1
    if (apiPath(request.url()) === '/api/v1/review-cases' && request.method() === 'POST') casePostCount += 1
  })

  try {
    await firstPage.goto('/me/workbench')
    await expect(firstPage.getByRole('heading', { name: '登录' })).toBeVisible()
    await submitLogin(firstPage, FIRST_LOGIN_NAME, FIRST_INITIAL_PASSWORD)
    await expect(firstPage.getByRole('heading', { name: '需要修改密码' })).toBeVisible()
    await submitPasswordChange(firstPage, FIRST_INITIAL_PASSWORD, FIRST_CHANGED_PASSWORD)
    await expect(firstPage.getByRole('heading', { name: '我的工作' })).toBeVisible()

    await firstPage.goto('/review-plans/new')
    const processPlanId = await createPlan(firstPage, 'M5.5 Process Plan')
    await expectStepTwoReload(firstPage, processPlanId)
    await firstPage.getByRole('radio', { name: /process_review@1/ }).check()
    await firstPage.getByLabel('审查活动名称').fill('M5.5 Process Case')
    await firstPage.getByLabel('区域代码').fill('M55-PROCESS')
    await firstPage.getByLabel('审查类型').fill('')
    const rejectedCasePromise = firstPage.waitForResponse(
      (response) => apiPath(response.url()) === '/api/v1/review-cases' && response.request().method() === 'POST',
    )
    await firstPage.getByRole('button', { name: '创建审查活动' }).click()
    expect((await rejectedCasePromise).status()).toBe(422)
    await expect(firstPage.getByText(/review_type/)).toBeVisible()
    await expect(firstPage.getByLabel('审查类型')).toBeFocused()
    expect(planPostCount).toBe(1)

    const processCasePromise = firstPage.waitForResponse(
      (response) => apiPath(response.url()) === '/api/v1/review-cases' && response.request().method() === 'POST',
    )
    const processDetailPromise = firstPage.waitForResponse(
      (response) => isCaseDetailPath(apiPath(response.url())) && response.request().method() === 'GET',
    )
    await firstPage.getByLabel('审查类型').fill('standard')
    await firstPage.getByRole('button', { name: '创建审查活动' }).click()
    const processCaseResponse = await processCasePromise
    expect(processCaseResponse.status()).toBe(201)
    const processCase = (await processCaseResponse.json()) as {
      id: string
      plan_id: string
      scenario_key: string
      scenario_version: number
      scenario_data: Record<string, string>
    }
    expect(processCase.plan_id).toBe(processPlanId)
    expect(processCase.scenario_key).toBe('process_review')
    expect(processCase.scenario_version).toBe(1)
    expect(processCase.scenario_data).toEqual({ area_code: 'M55-PROCESS', review_type: 'standard' })
    expect(casePostCount).toBe(2)
    expect((await processDetailPromise).status()).toBe(200)
    await expect(firstPage.getByRole('heading', { name: 'M5.5 Process Case' })).toBeVisible()
    await firstPage.reload()
    await expect(firstPage.getByRole('heading', { name: 'M5.5 Process Case' })).toBeVisible()

    await addMember(firstPage, processCase.id, 'reviewer', SECOND_DISPLAY_NAME, SECOND_DISPLAY_NAME)
    expect(await removeMember(firstPage, processCase.id, secondUserId, SECOND_DISPLAY_NAME)).toBe(200)
    await expect(firstPage.getByText('移除审查成员')).toBeVisible()
    const activitiesBeforeFinalManager = await fetchStatus(
      firstPage,
      `/api/v1/review-cases/${processCase.id}/activities`,
    )
    const finalManagerResponse = await (async () => {
      const team = firstPage.getByRole('region', { name: '团队管理' })
      const lead = team.locator('ul.surface-list').first().locator('li').filter({ hasText: FIRST_DISPLAY_NAME })
      const responsePromise = firstPage.waitForResponse(
        (response) =>
          apiPath(response.url()) === `/api/v1/review-cases/${processCase.id}/members/${firstUserId}` &&
          response.request().method() === 'DELETE',
      )
      await lead.getByRole('button', { name: '移除' }).click()
      return responsePromise
    })()
    expect((await finalManagerResponse).status()).toBe(409)
    await expect(firstPage.getByText('团队状态发生冲突，请刷新后重试。')).toBeVisible()
    const activitiesAfterFinalManager = await fetchStatus(
      firstPage,
      `/api/v1/review-cases/${processCase.id}/activities`,
    )
    expect(activitiesAfterFinalManager.status).toBe(200)
    expect(activitiesAfterFinalManager.body).toBe(activitiesBeforeFinalManager.body)
    await expect(firstPage.getByRole('region', { name: '团队管理' }).getByText(FIRST_DISPLAY_NAME)).toHaveCount(1)
    await addMember(firstPage, processCase.id, 'lead', SECOND_DISPLAY_NAME, SECOND_DISPLAY_NAME)

    await firstPage.getByRole('link', { name: '审查活动' }).click()
    await firstPage.getByRole('link', { name: '新建审查计划' }).click()
    const compliancePlanId = await createPlan(firstPage, 'M5.5 Compliance Plan')
    await firstPage.getByRole('radio', { name: /compliance_review@1/ }).check()
    await firstPage.getByLabel('审查活动名称').fill('M5.5 Compliance Case')
    await firstPage.getByLabel('标准 / 依据').fill('M55-STANDARD')
    await firstPage.getByLabel('范围摘要').fill('M5.5 controlled pilot scope')
    const complianceCasePromise = firstPage.waitForResponse(
      (response) => apiPath(response.url()) === '/api/v1/review-cases' && response.request().method() === 'POST',
    )
    await firstPage.getByRole('button', { name: '创建审查活动' }).click()
    const complianceCaseResponse = await complianceCasePromise
    expect(complianceCaseResponse.status()).toBe(201)
    const complianceCase = (await complianceCaseResponse.json()) as {
      plan_id: string
      scenario_key: string
      scenario_version: number
      scenario_data: Record<string, string>
    }
    expect(complianceCase.plan_id).toBe(compliancePlanId)
    expect(complianceCase.scenario_key).toBe('compliance_review')
    expect(complianceCase.scenario_version).toBe(1)
    expect(complianceCase.scenario_data).toEqual({
      standard_reference: 'M55-STANDARD',
      scope_summary: 'M5.5 controlled pilot scope',
    })
    expect(planPostCount).toBe(2)

    await firstPage.getByRole('link', { name: '审查活动' }).click()
    await firstPage.getByRole('link', { name: '新建审查计划' }).click()
    const ambiguousPlanId = await createPlan(firstPage, 'M5.5 Ambiguous Case Plan')
    await firstPage.getByRole('radio', { name: /process_review@1/ }).check()
    await firstPage.getByLabel('审查活动名称').fill('M5.5 Ambiguous Case')
    await firstPage.getByLabel('区域代码').fill('M55-AMBIGUOUS')
    await firstPage.getByLabel('审查类型').fill('standard')
    const abortHandler = async (route: Route) => {
      if (apiPath(route.request().url()) === '/api/v1/review-cases' && route.request().method() === 'POST') {
        await route.fetch()
        await route.abort('failed')
        return
      }
      await route.continue()
    }
    await firstPage.route('**/api/v1/review-cases', abortHandler)
    const beforeAmbiguousCasePosts = casePostCount
    try {
      await firstPage.getByRole('button', { name: '创建审查活动' }).click()
      await expect(firstPage.getByRole('alert')).toContainText('结果未知')
      expect(casePostCount).toBe(beforeAmbiguousCasePosts + 1)
      // Pilot-3: an unknown outcome is retried by hand (same Idempotency-Key), never automatically.
      await expect(firstPage.getByRole('button', { name: '重试创建审查活动' })).toBeEnabled()
      expect(ambiguousPlanId).toMatch(/^[0-9a-f-]{36}$/)
    } finally {
      await firstPage.unroute('**/api/v1/review-cases', abortHandler)
    }

    const foreignCase = await fetchStatus(firstPage, `/api/v1/review-cases/${FOREIGN_CASE_ID}`)
    const foreignPlan = await fetchStatus(firstPage, `/api/v1/review-plans/${FOREIGN_PLAN_ID}`)
    expect(foreignCase.status).toBe(404)
    expect(foreignPlan.status).toBe(404)
    expect(foreignCase.body).not.toContain('Foreign Case Must Stay Hidden')
    expect(foreignPlan.body).not.toContain('Foreign Plan Must Stay Hidden')
    const invalidRole = await fetchStatus(
      firstPage,
      `/api/v1/review-cases/${processCase.id}/member-candidates?role_key=not-a-real-role&q=Foreign&limit=20`,
    )
    expect(invalidRole.status).toBe(422)
    expect(invalidRole.body).not.toContain('M5.5 Foreign Candidate Name')
    const inactiveCandidate = await fetchStatus(
      firstPage,
      `/api/v1/review-cases/${processCase.id}/member-candidates?role_key=reviewer&q=${encodeURIComponent(INACTIVE_DISPLAY_NAME)}&limit=20`,
    )
    expect(inactiveCandidate.status).toBe(200)
    expect(inactiveCandidate.body).not.toContain(INACTIVE_DISPLAY_NAME)
    await firstPage.goto(`/review-cases/${FOREIGN_CASE_ID}`)
    await expect(firstPage.getByRole('heading', { name: '审查活动不可用' })).toBeVisible()
    await expect(firstPage.locator('body')).not.toContainText('M5.5 Foreign Case Must Stay Hidden')

    const adminOnlyCase = await fetchStatus(page, `/api/v1/review-cases/${ADMIN_CASE_ID}`)
    const foreignAdminUser = await fetchStatus(page, `/api/v1/admin/users/${FOREIGN_USER_ID}`)
    const foreignAdminMutation = await page.evaluate(async (userId) => {
      const response = await fetch(`/api/v1/admin/users/${userId}`, {
        method: 'PATCH',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ display_name: 'should-not-change' }),
      })
      return { status: response.status, body: await response.text() }
    }, FOREIGN_USER_ID)
    expect(adminOnlyCase.status).not.toBe(200)
    expect(foreignAdminUser.status).toBe(404)
    expect(foreignAdminMutation.status).toBe(404)
    expect(foreignAdminUser.body).not.toContain('M5.5 Foreign Candidate Name')
    expect(foreignAdminMutation.body).not.toContain('M5.5 Foreign Candidate Name')

    await secondPage.goto(`/review-cases/${processCase.id}`)
    await expect(secondPage.getByRole('heading', { name: '登录' })).toBeVisible()
    await submitLogin(secondPage, SECOND_LOGIN_NAME, SECOND_INITIAL_PASSWORD)
    await expect(secondPage.getByRole('heading', { name: '需要修改密码' })).toBeVisible()
    await submitPasswordChange(secondPage, SECOND_INITIAL_PASSWORD, SECOND_CHANGED_PASSWORD)
    await expect(secondPage.getByRole('heading', { name: 'M5.5 Process Case' })).toBeVisible()
    await expect(secondPage.getByRole('region', { name: '团队管理' }).getByText(SECOND_DISPLAY_NAME)).toBeVisible()
    await secondPage.getByRole('link', { name: '我的工作' }).click()
    await expect(secondPage.getByRole('heading', { name: '我的工作' })).toBeVisible()
    await expect(secondPage.getByRole('link', { name: 'M5.5 Process Case' })).toBeVisible()

    await page.getByLabel('目标用户').selectOption({ label: FIRST_DISPLAY_NAME })
    await page.getByLabel('临时密码').fill(FIRST_RESET_PASSWORD)
    const resetResponsePromise = page.waitForResponse(
      (response) => apiPath(response.url()).includes('/credential-reset') && response.request().method() === 'POST',
    )
    await page.getByRole('button', { name: '重置凭据' }).click()
    const resetResponse = await resetResponsePromise
    expect(resetResponse.status()).toBe(200)
    const resetBody = (await resetResponse.json()) as Record<string, unknown>
    expect(resetBody).not.toHaveProperty('temporary_password')
    await expect(page.getByLabel('临时密码')).toHaveValue('')
    await expect(page.locator('body')).not.toContainText(FIRST_RESET_PASSWORD)

    await firstPage.reload()
    await expect(firstPage.getByRole('heading', { name: '登录' })).toBeVisible()
    await submitFailedLogin(firstPage, FIRST_LOGIN_NAME, FIRST_CHANGED_PASSWORD)
    await submitLogin(firstPage, FIRST_LOGIN_NAME, FIRST_RESET_PASSWORD)
    await expect(firstPage.getByRole('heading', { name: '需要修改密码' })).toBeVisible()
    await expect(firstPage.locator('body')).not.toContainText(FIRST_RESET_PASSWORD)
    await submitPasswordChange(firstPage, FIRST_RESET_PASSWORD, FIRST_RESET_CHANGED_PASSWORD)
    await expect(firstPage.getByRole('heading', { name: '审查活动不可用' })).toBeVisible()
  } finally {
    await secondContext.close()
    await firstContext.close()
  }
})
