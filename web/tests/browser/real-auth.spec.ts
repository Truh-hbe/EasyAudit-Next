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
const PROVISIONED_LOGIN_NAME = 'browser-provisioned-user'
const PROVISIONED_DISPLAY_NAME = 'Browser Provisioned User'
const INITIAL_PASSWORD = 'initial-password-000'
const REPLACEMENT_PASSWORD = 'replacement-password-111'

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
  await submitLogout(page)
  await expect(page.getByRole('heading', { name: '登录' })).toBeVisible()
  await expect(page.getByText(READY_DISPLAY_NAME)).toHaveCount(0)
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

  await submitLogout(page)
  await expect(page.getByRole('heading', { name: '登录' })).toBeVisible()
  expect((await context.cookies()).some((cookie) => cookie.name === COOKIE_NAME)).toBe(false)
})
