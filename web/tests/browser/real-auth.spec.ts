import { execFileSync } from 'node:child_process'

import {
  expect,
  request as playwrightRequest,
  test,
  type Page,
} from '@playwright/test'

const COOKIE_NAME = '__Host-easyaudit_session'
const BASE_URL = 'https://127.0.0.1:4173'

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
  await expect(page.getByRole('heading', { name: 'ReviewCase 不可用' })).toBeVisible()
  await expect(page.getByText(STALE_CASE_TITLE)).toHaveCount(0)
  await expect(page.getByText('LINE-A')).toHaveCount(0)
  await expect(page.getByText(VIEWER_DISPLAY_NAME)).toHaveCount(1)

  const reloadRefusedPromise = page.waitForResponse(
    (response) => apiPath(response.url()) === '/api/v1/review-cases/00000000-0000-4000-8000-000000000375',
  )
  await page.reload()
  expect((await reloadRefusedPromise).status()).toBe(403)
  await expect(page.getByRole('heading', { name: 'ReviewCase 不可用' })).toBeVisible()
  await expect(page.getByText(STALE_CASE_TITLE)).toHaveCount(0)

  await submitLogout(page)
  await expect(page.getByRole('heading', { name: '登录' })).toBeVisible()
  await expect(page.getByText(VIEWER_DISPLAY_NAME)).toHaveCount(0)
})
