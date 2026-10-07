import { execFileSync } from 'node:child_process'

import {
  expect,
  request as playwrightRequest,
  test,
  type Page,
} from '@playwright/test'

import { openAssignDrawer, searchCandidate } from './assignmentDrawer.js'
import { notificationViewLabel } from './notificationView.js'

const COOKIE_NAME = '__Host-easyaudit_session'
const BASE_URL = `https://127.0.0.1:${process.env.EASYAUDIT_WEB_PORT ?? '4173'}`

const ADMIN_LOGIN_NAME = 'browser-system-admin'
const ADMIN_PASSWORD = 'admin-password-000'
const READY_LOGIN_NAME = 'browser-ready-user'
const READY_PASSWORD = 'ready-password-000'
const READY_DISPLAY_NAME = 'Browser Ready User'
const VIEWER_LOGIN_NAME = 'browser-viewer-user'
const VIEWER_PASSWORD = 'viewer-password-000'
const VIEWER_DISPLAY_NAME = 'Browser Viewer User'
const PROVISIONED_LOGIN_NAME = 'browser-provisioned-user'
const PROVISIONED_DISPLAY_NAME = 'Browser Provisioned User'
const INITIAL_PASSWORD = 'initial-password-000'
const REPLACEMENT_PASSWORD = 'replacement-password-111'

const JOURNEY_LEAD_LOGIN_NAME = 'browser-journey-lead'
const JOURNEY_LEAD_PASSWORD = 'lead-password-000'
const JOURNEY_LEAD_DISPLAY_NAME = 'M3.5.5 Journey Lead'
const JOURNEY_OWNER_LOGIN_NAME = 'browser-journey-owner'
const JOURNEY_OWNER_PASSWORD = 'owner-password-000'
const JOURNEY_OWNER_DISPLAY_NAME = 'M3.5.5 Journey Owner'
const JOURNEY_REVIEWER_LOGIN_NAME = 'browser-journey-reviewer'
const JOURNEY_REVIEWER_PASSWORD = 'reviewer-password-000'
const JOURNEY_REVIEWER_DISPLAY_NAME = 'M3.5.5 Journey Reviewer'
const JOURNEY_CASE_TITLE = 'M3.5.5 End-to-End Product Case'
const JOURNEY_FINDING_ID = '00000000-0000-4000-8000-000000000384'
const JOURNEY_FINDING_TITLE = 'M3.5.5 Multi-user Finding'
const JOURNEY_ACTION_TITLE = 'M3.5.5 Owner-created corrective Action'

const CASE_A_TITLE = 'Visible Product Case A'
const CASE_B_TITLE = 'Visible Product Case B'
const CASE_C_TITLE = 'Visible Product Case C'
const HIDDEN_H1_TITLE = 'Hidden Candidate H1'
const HIDDEN_H2_TITLE = 'Hidden Candidate H2'
const STALE_CASE_TITLE = 'Viewer Stale Case'

const DESKTOP_VIEWPORT = { width: 1280, height: 800 }
const NARROW_VIEWPORT = { width: 390, height: 844 }

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
  return response
}

async function submitLogout(page: Page) {
  const responsePromise = page.waitForResponse(
    (response) =>
      apiPath(response.url()) === '/api/v1/auth/logout' &&
      response.request().method() === 'POST',
  )
  await page.getByRole('button', { name: '退出登录' }).click()
  const response = await responsePromise
  expect(response.status()).toBe(204)
}

async function expectLoginAtViewport(
  page: Page,
  viewport: { width: number; height: number },
) {
  await page.setViewportSize(viewport)
  expect(page.viewportSize()).toEqual(viewport)
  await expect(page.getByRole('heading', { name: '登录' })).toBeVisible()
  await expect(page.getByLabel('登录名')).toBeVisible()
  await expect(page.getByLabel('密码')).toBeVisible()
  await expect(page.getByRole('button', { name: '登录' })).toBeVisible()
}

async function expectRemediationAtViewport(
  page: Page,
  viewport: { width: number; height: number },
) {
  await page.setViewportSize(viewport)
  expect(page.viewportSize()).toEqual(viewport)
  await expect(page.getByRole('heading', { name: '需要修改密码' })).toBeVisible()
  await expect(page.getByLabel('当前密码')).toBeVisible()
  await expect(page.getByLabel('新密码', { exact: true })).toBeVisible()
  await expect(page.getByLabel('确认新密码')).toBeVisible()
  await expect(page.getByRole('button', { name: '修改密码' })).toBeVisible()
}

async function expectShellAtViewport(
  page: Page,
  viewport: { width: number; height: number },
  displayName: string,
) {
  await page.setViewportSize(viewport)
  expect(page.viewportSize()).toEqual(viewport)
  await expect(page.getByRole('navigation', { name: '主要导航' })).toBeVisible()
  await expect(page.getByText(displayName)).toBeVisible()
  await expect(page.getByRole('heading', { name: '我的工作' })).toBeVisible()
}

async function expectNoBrowserAuthMaterial(page: Page) {
  const clientVisibleAuth = await page.evaluate((cookieName) => {
    const browserGlobals = globalThis as unknown as {
      document: { cookie: string }
      localStorage: { length: number }
      sessionStorage: { length: number }
    }
    return {
      documentCookie: browserGlobals.document.cookie,
      localStorageLength: browserGlobals.localStorage.length,
      sessionStorageLength: browserGlobals.sessionStorage.length,
      cookieName,
    }
  }, COOKIE_NAME)
  expect(clientVisibleAuth.documentCookie).not.toContain(clientVisibleAuth.cookieName)
  expect(clientVisibleAuth.localStorageLength).toBe(0)
  expect(clientVisibleAuth.sessionStorageLength).toBe(0)
}

async function provisionOrdinaryUserThroughRealAdminApi() {
  const adminClient = await playwrightRequest.newContext({
    baseURL: BASE_URL,
    ignoreHTTPSErrors: true,
  })
  try {
    const login = await adminClient.post('/api/v1/auth/login', {
      data: {
        login_name: ADMIN_LOGIN_NAME,
        password: ADMIN_PASSWORD,
      },
    })
    expect(login.status()).toBe(200)

    const created = await adminClient.post('/api/v1/admin/users', {
      data: {
        display_name: PROVISIONED_DISPLAY_NAME,
        login_name: PROVISIONED_LOGIN_NAME,
        initial_password: INITIAL_PASSWORD,
      },
    })
    expect(created.status()).toBe(201)
    const createdUser = (await created.json()) as {
      display_name: string
      platform_role: string
    }
    expect(createdUser.display_name).toBe(PROVISIONED_DISPLAY_NAME)
    expect(createdUser.platform_role).toBe('ordinary_user')
  } finally {
    await adminClient.dispose()
  }
}

async function loginFromWorkbench(
  page: Page,
  loginName: string,
  password: string,
  displayName: string,
) {
  await page.goto('/me/workbench')
  await expect(page.getByRole('heading', { name: '登录' })).toBeVisible()
  await submitLogin(page, loginName, password)
  await expectShellAtViewport(page, DESKTOP_VIEWPORT, displayName)
}

test.describe.configure({ mode: 'serial', retries: 0 })

test('credential-ready session survives hard reload and logout denies protected routes', async ({
  page,
  context,
}) => {
  const authorizationHeaders: Array<string | undefined> = []
  page.on('request', (request) => {
    if (apiPath(request.url()).startsWith('/api/v1/')) {
      authorizationHeaders.push(request.headers().authorization)
    }
  })

  await page.goto('/me/workbench')
  await expectLoginAtViewport(page, DESKTOP_VIEWPORT)

  await submitLogin(page, READY_LOGIN_NAME, READY_PASSWORD)
  await expectShellAtViewport(page, DESKTOP_VIEWPORT, READY_DISPLAY_NAME)
  expect(new URL(page.url()).pathname).toBe('/me/workbench')

  const cookiesAfterLogin = await context.cookies()
  const sessionCookie = cookiesAfterLogin.find((cookie) => cookie.name === COOKIE_NAME)
  expect(sessionCookie).toBeDefined()
  if (sessionCookie === undefined) {
    throw new Error('Secure HttpOnly session cookie was not issued')
  }
  expect(sessionCookie.value).not.toBe('')
  expect(sessionCookie.httpOnly).toBe(true)
  expect(sessionCookie.secure).toBe(true)
  expect(sessionCookie.sameSite).toBe('Strict')
  expect(sessionCookie.path).toBe('/')
  await expectNoBrowserAuthMaterial(page)

  const reloadMePromise = page.waitForResponse(
    (response) =>
      apiPath(response.url()) === '/api/v1/me' &&
      response.request().method() === 'GET',
  )
  await page.reload()
  const reloadMe = await reloadMePromise
  expect(reloadMe.status()).toBe(200)
  const reloadIdentity = (await reloadMe.json()) as {
    display_name: string
    must_change_password: boolean
  }
  expect(reloadIdentity.display_name).toBe(READY_DISPLAY_NAME)
  expect(reloadIdentity.must_change_password).toBe(false)
  await expectShellAtViewport(page, DESKTOP_VIEWPORT, READY_DISPLAY_NAME)
  expect(authorizationHeaders.filter((header) => header !== undefined)).toEqual([])

  await submitLogout(page)
  await expect(page.getByRole('heading', { name: '登录' })).toBeVisible()
  expect((await context.cookies()).some((cookie) => cookie.name === COOKIE_NAME)).toBe(false)
  await expect(page.getByText(READY_DISPLAY_NAME)).toHaveCount(0)
  await expect(page.getByText(CASE_A_TITLE)).toHaveCount(0)

  await page.goto('/me/workbench')
  await expect(page.getByRole('heading', { name: '登录' })).toBeVisible()
  await expect(page.getByRole('navigation', { name: '主要导航' })).toHaveCount(0)
})

test('real admin provisioning preserves remediation across reload and clears user A before user B', async ({
  page,
  context,
}) => {
  await provisionOrdinaryUserThroughRealAdminApi()

  await page.goto('/me/workbench')
  await submitLogin(page, READY_LOGIN_NAME, READY_PASSWORD)
  await expectShellAtViewport(page, DESKTOP_VIEWPORT, READY_DISPLAY_NAME)
  await expect(page.getByText(CASE_A_TITLE)).toBeVisible()
  await submitLogout(page)
  await expect(page.getByRole('heading', { name: '登录' })).toBeVisible()
  await expect(page.getByText(READY_DISPLAY_NAME)).toHaveCount(0)
  await expect(page.getByText(CASE_A_TITLE)).toHaveCount(0)
  expect((await context.cookies()).some((cookie) => cookie.name === COOKIE_NAME)).toBe(false)

  await page.goto('/me/workbench')
  await expectLoginAtViewport(page, DESKTOP_VIEWPORT)
  await expectLoginAtViewport(page, NARROW_VIEWPORT)

  await submitLogin(page, PROVISIONED_LOGIN_NAME, INITIAL_PASSWORD)
  await expectRemediationAtViewport(page, NARROW_VIEWPORT)
  expect(new URL(page.url()).pathname).toBe('/me/credential-remediation')

  const meBefore = await context.request.get(`${BASE_URL}/api/v1/me`)
  expect(meBefore.status()).toBe(200)
  const provisionedIdentity = (await meBefore.json()) as {
    display_name: string
    must_change_password: boolean
  }
  expect(provisionedIdentity.display_name).toBe(PROVISIONED_DISPLAY_NAME)
  expect(provisionedIdentity.must_change_password).toBe(true)
  await expect(page.getByText(READY_DISPLAY_NAME)).toHaveCount(0)
  await expect(page.getByText(CASE_A_TITLE)).toHaveCount(0)
  await expectNoBrowserAuthMaterial(page)

  await expectRemediationAtViewport(page, DESKTOP_VIEWPORT)
  await expectRemediationAtViewport(page, NARROW_VIEWPORT)

  const requiredReloadMePromise = page.waitForResponse(
    (response) =>
      apiPath(response.url()) === '/api/v1/me' &&
      response.request().method() === 'GET',
  )
  await page.reload()
  const requiredReloadMe = await requiredReloadMePromise
  expect(requiredReloadMe.status()).toBe(200)
  const requiredReloadIdentity = (await requiredReloadMe.json()) as {
    display_name: string
    must_change_password: boolean
  }
  expect(requiredReloadIdentity.display_name).toBe(PROVISIONED_DISPLAY_NAME)
  expect(requiredReloadIdentity.must_change_password).toBe(true)
  await expectRemediationAtViewport(page, NARROW_VIEWPORT)

  const passwordResponsePromise = page.waitForResponse(
    (response) =>
      apiPath(response.url()) === '/api/v1/me/password' &&
      response.request().method() === 'POST',
  )
  await page.getByLabel('当前密码').fill(INITIAL_PASSWORD)
  await page.getByLabel('新密码', { exact: true }).fill(REPLACEMENT_PASSWORD)
  await page.getByLabel('确认新密码').fill(REPLACEMENT_PASSWORD)
  await page.getByRole('button', { name: '修改密码' }).click()
  const passwordResponse = await passwordResponsePromise
  expect(passwordResponse.status()).toBe(200)

  await expectShellAtViewport(page, NARROW_VIEWPORT, PROVISIONED_DISPLAY_NAME)
  await expect(page.getByText(READY_DISPLAY_NAME)).toHaveCount(0)
  await expect(page.getByText(CASE_A_TITLE)).toHaveCount(0)

  await page.setViewportSize(DESKTOP_VIEWPORT)
  const readyReloadMePromise = page.waitForResponse(
    (response) =>
      apiPath(response.url()) === '/api/v1/me' &&
      response.request().method() === 'GET',
  )
  await page.reload()
  const readyReloadMe = await readyReloadMePromise
  expect(readyReloadMe.status()).toBe(200)
  const readyReloadIdentity = (await readyReloadMe.json()) as {
    display_name: string
    must_change_password: boolean
  }
  expect(readyReloadIdentity.display_name).toBe(PROVISIONED_DISPLAY_NAME)
  expect(readyReloadIdentity.must_change_password).toBe(false)
  await expectShellAtViewport(page, DESKTOP_VIEWPORT, PROVISIONED_DISPLAY_NAME)
  await expect(page.getByText(READY_DISPLAY_NAME)).toHaveCount(0)
  await expect(page.getByText(CASE_A_TITLE)).toHaveCount(0)

  await submitLogout(page)
  await expect(page.getByRole('heading', { name: '登录' })).toBeVisible()
  expect((await context.cookies()).some((cookie) => cookie.name === COOKIE_NAME)).toBe(false)
})

test('real M3.5.2 manager journey uses Workbench projection, bounded collection, exact Scenario and server management facts', async ({ page }) => {
  await page.goto('/me/workbench')
  await submitLogin(page, READY_LOGIN_NAME, READY_PASSWORD)
  await expectShellAtViewport(page, DESKTOP_VIEWPORT, READY_DISPLAY_NAME)

  await expect(page.getByRole('link', { name: CASE_A_TITLE })).toBeVisible()
  await expect(page.getByRole('link', { name: CASE_B_TITLE })).toBeVisible()
  await expect(page.getByRole('link', { name: CASE_C_TITLE })).toBeVisible()
  await expect(page.getByRole('link', { name: 'Real Browser Finding' })).toBeVisible()
  await expect(page.getByRole('link', { name: 'Real Browser Action' })).toBeVisible()
  await expect(page.getByText(HIDDEN_H1_TITLE)).toHaveCount(0)
  await expect(page.getByText(HIDDEN_H2_TITLE)).toHaveCount(0)

  const caseResponsePromise = page.waitForResponse(
    (response) => apiPath(response.url()) === '/api/v1/review-cases/00000000-0000-4000-8000-000000000370',
  )
  const activityResponsePromise = page.waitForResponse(
    (response) => apiPath(response.url()) === '/api/v1/review-cases/00000000-0000-4000-8000-000000000370/activities',
  )
  const managementResponsePromise = page.waitForResponse(
    (response) => apiPath(response.url()) === '/api/v1/management/review-cases/00000000-0000-4000-8000-000000000370/progress',
  )
  await page.getByRole('link', { name: CASE_A_TITLE }).click()

  expect((await caseResponsePromise).status()).toBe(200)
  const activityResponse = await activityResponsePromise
  const managementResponse = await managementResponsePromise
  expect(activityResponse.status()).toBe(200)
  expect(managementResponse.status()).toBe(200)
  const activities = (await activityResponse.json()) as Array<Record<string, unknown>>
  expect(activities).toHaveLength(1)
  expect(activities[0]?.event_type).toBe('review_case.real_browser_seeded')
  expect('metadata' in (activities[0] ?? {})).toBe(false)
  expect('metadata_json' in (activities[0] ?? {})).toBe(false)

  await expect(page.getByRole('heading', { name: CASE_A_TITLE })).toBeVisible()
  await expect(page.getByText('LINE-A')).toBeVisible()
  await expect(page.getByText('routine')).toBeVisible()
  await expect(page.getByText('Human Case Member')).toBeVisible()
  await expect(page.getByRole('link', { name: 'Real Browser Finding' })).toBeVisible()
  await expect(page.getByText('未知操作')).toBeVisible()
  await expect(page.getByText('review_case.real_browser_seeded')).toBeVisible()
  await expect(page.getByRole('heading', { name: '管理进度' })).toBeVisible()
  await expect(page.getByText('当前用户没有可用的管理进度摘要。')).toHaveCount(0)

  const reloadCasePromise = page.waitForResponse(
    (response) => apiPath(response.url()) === '/api/v1/review-cases/00000000-0000-4000-8000-000000000370',
  )
  await page.reload()
  expect((await reloadCasePromise).status()).toBe(200)
  await expect(page.getByRole('heading', { name: CASE_A_TITLE })).toBeVisible()
  await expect(page.getByText('Human Case Member')).toBeVisible()

  const firstCollectionPromise = page.waitForResponse(
    (response) => {
      const url = new URL(response.url())
      return url.pathname === '/api/v1/review-cases' && url.searchParams.get('limit') === '2' && url.searchParams.get('offset') === '0'
    },
  )
  await page.goto('/review-cases?limit=2&offset=0')
  const firstCollection = await firstCollectionPromise
  expect(firstCollection.status()).toBe(200)
  const firstPayload = (await firstCollection.json()) as {
    items: Array<{ title: string }>
    total: number
  }
  expect(firstPayload.total).toBe(3)
  expect(firstPayload.items.map((item) => item.title)).toEqual([CASE_A_TITLE, CASE_B_TITLE])
  await expect(page.getByText(CASE_A_TITLE)).toBeVisible()
  await expect(page.getByText(CASE_B_TITLE)).toBeVisible()
  await expect(page.getByText(HIDDEN_H1_TITLE)).toHaveCount(0)
  await expect(page.getByText(HIDDEN_H2_TITLE)).toHaveCount(0)

  const secondCollectionPromise = page.waitForResponse(
    (response) => {
      const url = new URL(response.url())
      return url.pathname === '/api/v1/review-cases' && url.searchParams.get('limit') === '2' && url.searchParams.get('offset') === '2'
    },
  )
  await page.getByRole('button', { name: '下一页' }).click()
  const secondCollection = await secondCollectionPromise
  expect(secondCollection.status()).toBe(200)
  const secondPayload = (await secondCollection.json()) as {
    items: Array<{ title: string }>
    total: number
  }
  expect(secondPayload.total).toBe(3)
  expect(secondPayload.items.map((item) => item.title)).toEqual([CASE_C_TITLE])
  await expect(page.getByText(CASE_C_TITLE)).toBeVisible()
  await expect(page.getByText(HIDDEN_H1_TITLE)).toHaveCount(0)
  await expect(page.getByText(HIDDEN_H2_TITLE)).toHaveCount(0)

  await submitLogout(page)
  await expect(page.getByRole('heading', { name: '登录' })).toBeVisible()
  await expect(page.getByText(CASE_C_TITLE)).toHaveCount(0)
})

test('real stale Workbench link revalidates current Case authorization and observer never gains management progress', async ({ page }) => {
  await page.goto('/me/workbench')
  await submitLogin(page, VIEWER_LOGIN_NAME, VIEWER_PASSWORD)
  await expectShellAtViewport(page, DESKTOP_VIEWPORT, VIEWER_DISPLAY_NAME)
  const staleLink = page.getByRole('link', { name: STALE_CASE_TITLE })
  await expect(staleLink).toBeVisible()
  await expect(page.getByText(CASE_A_TITLE)).toHaveCount(0)

  const visibleCasePromise = page.waitForResponse(
    (response) => apiPath(response.url()) === '/api/v1/review-cases/00000000-0000-4000-8000-000000000375',
  )
  const unavailableManagementPromise = page.waitForResponse(
    (response) => apiPath(response.url()) === '/api/v1/management/review-cases/00000000-0000-4000-8000-000000000375/progress',
  )
  await staleLink.click()
  expect((await visibleCasePromise).status()).toBe(200)
  expect((await unavailableManagementPromise).status()).toBe(404)
  await expect(page.getByRole('heading', { name: STALE_CASE_TITLE })).toBeVisible()
  await expect(page.getByText('当前用户没有可用的管理进度摘要。')).toBeVisible()

  await page.goto('/me/workbench')
  await expect(page.getByRole('link', { name: STALE_CASE_TITLE })).toBeVisible()
  execFileSync('python', ['tests/browser/product_fixture_control.py', 'revoke-viewer-case'], {
    env: process.env,
    stdio: 'inherit',
  })

  const refusedCasePromise = page.waitForResponse(
    (response) => apiPath(response.url()) === '/api/v1/review-cases/00000000-0000-4000-8000-000000000375',
  )
  await page.getByRole('link', { name: STALE_CASE_TITLE }).click()
  expect((await refusedCasePromise).status()).toBe(403)
  await expect(page.getByText('内容不存在或无权访问')).toBeVisible()
  await expect(page.getByText(STALE_CASE_TITLE)).toHaveCount(0)
  await expect(page.getByText('LINE-A')).toHaveCount(0)
  await expect(page.getByText(VIEWER_DISPLAY_NAME)).toHaveCount(1)

  const reloadRefusedPromise = page.waitForResponse(
    (response) => apiPath(response.url()) === '/api/v1/review-cases/00000000-0000-4000-8000-000000000375',
  )
  await page.reload()
  expect((await reloadRefusedPromise).status()).toBe(403)
  await expect(page.getByText('内容不存在或无权访问')).toBeVisible()
  await expect(page.getByText(STALE_CASE_TITLE)).toHaveCount(0)

  await submitLogout(page)
  await expect(page.getByRole('heading', { name: '登录' })).toBeVisible()
  await expect(page.getByText(VIEWER_DISPLAY_NAME)).toHaveCount(0)
})

test('real M3.5.5 Lead Owner Reviewer journey preserves server truth through nudge rejection and closure', async ({ page }) => {
  await loginFromWorkbench(
    page,
    JOURNEY_LEAD_LOGIN_NAME,
    JOURNEY_LEAD_PASSWORD,
    JOURNEY_LEAD_DISPLAY_NAME,
  )
  await expect(page.getByRole('link', { name: JOURNEY_CASE_TITLE })).toBeVisible()
  await page.getByRole('link', { name: JOURNEY_CASE_TITLE }).click()
  await expect(page.getByRole('heading', { name: JOURNEY_CASE_TITLE })).toBeVisible()
  await page.getByRole('link', { name: JOURNEY_FINDING_TITLE }).click()
  await expect(page.getByRole('heading', { name: JOURNEY_FINDING_TITLE })).toBeVisible()

  const nudgeRequestPromise = page.waitForRequest(
    (request) =>
      apiPath(request.url()) === `/api/v1/findings/${JOURNEY_FINDING_ID}/nudge` &&
      request.method() === 'POST',
  )
  const nudgeResponsePromise = page.waitForResponse(
    (response) =>
      apiPath(response.url()) === `/api/v1/findings/${JOURNEY_FINDING_ID}/nudge` &&
      response.request().method() === 'POST',
  )
  await page.getByRole('button', { name: '催办', exact: true }).click()
  const nudgeRequest = await nudgeRequestPromise
  const nudgeResponse = await nudgeResponsePromise
  expect(nudgeRequest.postData()).toBeNull()
  expect(nudgeResponse.status()).toBe(200)
  const nudgeResult = (await nudgeResponse.json()) as { recipient_count: number }
  expect(nudgeResult.recipient_count).toBe(1)
  await expect(page.getByText(/服务器已确认催办：已通知 1 人/)).toBeVisible()
  await submitLogout(page)

  await loginFromWorkbench(
    page,
    JOURNEY_OWNER_LOGIN_NAME,
    JOURNEY_OWNER_PASSWORD,
    JOURNEY_OWNER_DISPLAY_NAME,
  )
  await expect(page.getByRole('link', { name: JOURNEY_FINDING_TITLE })).toBeVisible()
  await page.getByRole('navigation', { name: '主要导航' }).getByRole('link', { name: '通知' }).click()
  await expect(page.getByRole('heading', { name: '通知' })).toBeVisible()
  await notificationViewLabel(page, /未读/).click()
  await expect(page.getByText('催办发现项', { exact: true })).toBeVisible()
  await page.getByRole('link', { name: '打开当前目标' }).click()
  await expect(page.getByRole('heading', { name: JOURNEY_FINDING_TITLE })).toBeVisible()

  await page.getByRole('button', { name: '新建整改项', exact: true }).click()
  const newActionForm = page.getByRole('dialog', { name: '新建整改项' })
  await newActionForm.getByLabel('标题').fill(JOURNEY_ACTION_TITLE)
  const createActionResponsePromise = page.waitForResponse(
    (response) =>
      apiPath(response.url()) === `/api/v1/findings/${JOURNEY_FINDING_ID}/actions` &&
      response.request().method() === 'POST',
  )
  await newActionForm.getByRole('button', { name: '创建整改项' }).click()
  const createActionResponse = await createActionResponsePromise
  expect(createActionResponse.status()).toBe(201)
  const createdAction = (await createActionResponse.json()) as { id: string; lifecycle: string }
  expect(createdAction.lifecycle).toBe('todo')
  await expect(page.getByRole('link', { name: JOURNEY_ACTION_TITLE })).toBeVisible()
  await page.getByRole('link', { name: JOURNEY_ACTION_TITLE }).click()
  await expect(page.getByRole('heading', { name: JOURNEY_ACTION_TITLE })).toBeVisible()

  const assigneeSection = page.getByRole('region', { name: '整改事项' })
  const assignDrawer = await openAssignDrawer(page, '添加执行人', '添加执行人')
  await searchCandidate(assignDrawer, '执行人', 'Journey Owner')
  const ownerCandidate = page.getByTitle(JOURNEY_OWNER_DISPLAY_NAME, { exact: true })
  await expect(ownerCandidate).toBeVisible()
  const addAssigneeResponsePromise = page.waitForResponse(
    (response) =>
      apiPath(response.url()) === `/api/v1/action-items/${createdAction.id}/assignees` &&
      response.request().method() === 'POST',
  )
  await ownerCandidate.click()
  await assignDrawer.getByRole('button', { name: '添加执行人' }).click()
  expect((await addAssigneeResponsePromise).status()).toBe(201)
  await expect(assigneeSection.getByText(JOURNEY_OWNER_DISPLAY_NAME, { exact: true })).toBeVisible()

  const startResponsePromise = page.waitForResponse(
    (response) =>
      apiPath(response.url()) === `/api/v1/action-items/${createdAction.id}/transitions` &&
      response.request().method() === 'POST',
  )
  await page.getByRole('button', { name: '开始整改项', exact: true }).click()
  const startResponse = await startResponsePromise
  expect(startResponse.status()).toBe(200)
  expect(((await startResponse.json()) as { lifecycle: string }).lifecycle).toBe('in_progress')
  await expect(page.getByRole('button', { name: '完成整改项', exact: true })).toBeVisible()

  const completeResponsePromise = page.waitForResponse(
    (response) =>
      apiPath(response.url()) === `/api/v1/action-items/${createdAction.id}/transitions` &&
      response.request().method() === 'POST',
  )
  await page.getByRole('button', { name: '完成整改项', exact: true }).click()
  const completeResponse = await completeResponsePromise
  expect(completeResponse.status()).toBe(200)
  expect(((await completeResponse.json()) as { lifecycle: string }).lifecycle).toBe('done')
  await expect(page.getByRole('button', { name: '重新打开' })).toBeVisible()

  await page.getByRole('link', { name: '返回发现项' }).click()
  await page.getByRole('button', { name: '填写整改计划' }).click()
  const planDrawer = page.getByRole('dialog', { name: '整改计划' })
  await planDrawer.getByLabel('根本原因').fill('Real multi-user root cause accepted through Product UI')
  const planResponsePromise = page.waitForResponse(
    (response) =>
      apiPath(response.url()) === `/api/v1/findings/${JOURNEY_FINDING_ID}/rectification-submissions` &&
      response.request().method() === 'POST',
  )
  await planDrawer.getByRole('button', { name: '提交整改计划' }).click()
  expect((await planResponsePromise).status()).toBe(201)
  await page.getByRole('button', { name: '提交整改完成' }).click()
  const firstCompletion = page.getByRole('dialog', { name: '整改完成' })
  await firstCompletion.getByLabel('整改完成说明').fill('First correction completed through assigned Action')
  const firstSubmitResponsePromise = page.waitForResponse(
    (response) =>
      apiPath(response.url()) === `/api/v1/findings/${JOURNEY_FINDING_ID}/rectification-submissions` &&
      response.request().method() === 'POST',
  )
  await firstCompletion.getByRole('button', { name: '提交验证' }).click()
  const firstSubmitResponse = await firstSubmitResponsePromise
  expect(firstSubmitResponse.status()).toBe(201)
  const firstSubmitted = (await firstSubmitResponse.json()) as { finding: { lifecycle: string } }
  expect(firstSubmitted.finding.lifecycle).toBe('verifying')
  await submitLogout(page)

  await loginFromWorkbench(
    page,
    JOURNEY_REVIEWER_LOGIN_NAME,
    JOURNEY_REVIEWER_PASSWORD,
    JOURNEY_REVIEWER_DISPLAY_NAME,
  )
  const verificationLink = page.getByRole('link', { name: JOURNEY_FINDING_TITLE })
  await expect(verificationLink).toBeVisible()
  await verificationLink.click()
  await page.getByRole('button', { name: '驳回验证' }).click()
  const rejectDialog = page.getByRole('dialog', { name: '驳回验证' })
  await rejectDialog.getByLabel('驳回原因').fill('Reviewer requires a second corrective cycle')
  const rejectResponsePromise = page.waitForResponse(
    (response) =>
      apiPath(response.url()) === `/api/v1/findings/${JOURNEY_FINDING_ID}/verification-submissions` &&
      response.request().method() === 'POST',
  )
  await rejectDialog.getByRole('button', { name: '确认驳回' }).click()
  const rejectResponse = await rejectResponsePromise
  expect(rejectResponse.status()).toBe(201)
  const rejected = (await rejectResponse.json()) as { finding: { lifecycle: string } }
  expect(rejected.finding.lifecycle).toBe('rectifying')
  await submitLogout(page)

  await loginFromWorkbench(
    page,
    JOURNEY_OWNER_LOGIN_NAME,
    JOURNEY_OWNER_PASSWORD,
    JOURNEY_OWNER_DISPLAY_NAME,
  )
  await page.getByRole('link', { name: JOURNEY_FINDING_TITLE }).click()
  await expect(page.getByRole('heading', { name: JOURNEY_FINDING_TITLE })).toBeVisible()
  // 驳回原因对整改负责人可读：页面上方提示 + 提交记录。
  await expect(page.getByRole('status').filter({ hasText: '最近一次验证被驳回' })).toContainText(
    'Reviewer requires a second corrective cycle',
  )
  const submissionHistory = page.getByRole('list', { name: '提交记录' })
  await expect(submissionHistory).toContainText('Real multi-user root cause accepted through Product UI')
  await expect(submissionHistory).toContainText('First correction completed through assigned Action')
  await expect(submissionHistory).toContainText('Reviewer requires a second corrective cycle')
  await page.getByRole('link', { name: JOURNEY_ACTION_TITLE }).click()
  await expect(page.getByRole('button', { name: '重新打开' })).toBeVisible()

  const reopenActionResponsePromise = page.waitForResponse(
    (response) =>
      apiPath(response.url()) === `/api/v1/action-items/${createdAction.id}/transitions` &&
      response.request().method() === 'POST',
  )
  await page.getByRole('button', { name: '重新打开' }).click()
  await page.getByRole('dialog', { name: '重新打开整改项' }).getByRole('button', { name: '确认重新打开' }).click()
  const reopenActionResponse = await reopenActionResponsePromise
  expect(reopenActionResponse.status()).toBe(200)
  expect(((await reopenActionResponse.json()) as { lifecycle: string }).lifecycle).toBe('in_progress')

  const secondCompleteResponsePromise = page.waitForResponse(
    (response) =>
      apiPath(response.url()) === `/api/v1/action-items/${createdAction.id}/transitions` &&
      response.request().method() === 'POST',
  )
  await page.getByRole('button', { name: '完成整改项', exact: true }).click()
  const secondCompleteResponse = await secondCompleteResponsePromise
  expect(secondCompleteResponse.status()).toBe(200)
  expect(((await secondCompleteResponse.json()) as { lifecycle: string }).lifecycle).toBe('done')

  await page.getByRole('link', { name: '返回发现项' }).click()
  await page.getByRole('button', { name: '提交整改完成' }).click()
  const secondCompletion = page.getByRole('dialog', { name: '整改完成' })
  await secondCompletion.getByLabel('整改完成说明').fill('Second correction completed after reviewer rejection')
  const secondSubmitResponsePromise = page.waitForResponse(
    (response) =>
      apiPath(response.url()) === `/api/v1/findings/${JOURNEY_FINDING_ID}/rectification-submissions` &&
      response.request().method() === 'POST',
  )
  await secondCompletion.getByRole('button', { name: '提交验证' }).click()
  const secondSubmitResponse = await secondSubmitResponsePromise
  expect(secondSubmitResponse.status()).toBe(201)
  const secondSubmitted = (await secondSubmitResponse.json()) as { finding: { lifecycle: string } }
  expect(secondSubmitted.finding.lifecycle).toBe('verifying')
  // 发现项已提交验证：整改项页面解释原因，且不再给出必然被拒绝的写入口。
  await page.getByRole('link', { name: JOURNEY_ACTION_TITLE }).click()
  await expect(page.getByRole('status').filter({ hasText: '发现项已提交验证' })).toBeVisible()
  expect(await page.getByRole('button', { name: '重新打开整改项', exact: true }).count()).toBe(0)
  expect(await page.getByRole('button', { name: '添加执行人', exact: true }).count()).toBe(0)
  expect(await page.getByRole('button', { name: '上传证据', exact: true }).count()).toBe(0)
  await submitLogout(page)

  await loginFromWorkbench(
    page,
    JOURNEY_REVIEWER_LOGIN_NAME,
    JOURNEY_REVIEWER_PASSWORD,
    JOURNEY_REVIEWER_DISPLAY_NAME,
  )
  await expect(page.getByRole('link', { name: JOURNEY_FINDING_TITLE })).toBeVisible()
  await page.getByRole('link', { name: JOURNEY_FINDING_TITLE }).click()
  const approveResponsePromise = page.waitForResponse(
    (response) =>
      apiPath(response.url()) === `/api/v1/findings/${JOURNEY_FINDING_ID}/verification-submissions` &&
      response.request().method() === 'POST',
  )
  await page.getByRole('button', { name: '通过验证' }).click()
  await page.getByRole('dialog', { name: '通过验证' }).getByRole('button', { name: '确认通过' }).click()
  const approveResponse = await approveResponsePromise
  expect(approveResponse.status()).toBe(201)
  const approved = (await approveResponse.json()) as { finding: { lifecycle: string } }
  expect(approved.finding.lifecycle).toBe('closed')
  await expect(page.getByRole('button', { name: '重新打开' })).toBeVisible()
  await submitLogout(page)

  await loginFromWorkbench(
    page,
    JOURNEY_LEAD_LOGIN_NAME,
    JOURNEY_LEAD_PASSWORD,
    JOURNEY_LEAD_DISPLAY_NAME,
  )
  await page.getByRole('navigation', { name: '主要导航' }).getByRole('link', { name: '管理视图' }).click()
  await expect(page.getByRole('heading', { name: '管理视图' })).toBeVisible()
  const journeyRow = page.getByRole('listitem').filter({ hasText: JOURNEY_CASE_TITLE })
  await expect(journeyRow).toBeVisible()
  await journeyRow.getByRole('link', { name: '查看管理进度' }).click()
  await expect(page.getByRole('heading', { name: JOURNEY_CASE_TITLE })).toBeVisible()
  const findingClosedFact = page.locator('dt', { hasText: '发现项已关闭' }).locator('..')
  await expect(findingClosedFact.locator('dd')).toHaveText('1')
  await expect(page.getByRole('link', { name: JOURNEY_FINDING_TITLE })).toBeVisible()
  await expectNoBrowserAuthMaterial(page)
  await submitLogout(page)
})
