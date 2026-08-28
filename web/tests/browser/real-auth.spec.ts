import { expect, request as playwrightRequest, test } from '@playwright/test'

const COOKIE_NAME = '__Host-easyaudit_session'
const LOGIN_NAME = 'browser-credential-user'
const INITIAL_PASSWORD = 'initial-password-000'
const REPLACEMENT_PASSWORD = 'replacement-password-111'
const BASE_URL = 'https://127.0.0.1:4173'

function apiPath(url: string): string {
  return new URL(url).pathname
}

test('real PostgreSQL + FastAPI credential readiness journey', async ({ page, context }) => {
  const authorizationHeaders: Array<string | undefined> = []
  page.on('request', (request) => {
    if (apiPath(request.url()).startsWith('/api/v1/')) {
      authorizationHeaders.push(request.headers().authorization)
    }
  })

  await page.goto('/review-cases/case-1')
  await expect(page.getByRole('heading', { name: '登录' })).toBeVisible()
  expect(new URL(page.url()).pathname).toBe('/login')

  const loginResponsePromise = page.waitForResponse(
    (response) =>
      apiPath(response.url()) === '/api/v1/auth/login' &&
      response.request().method() === 'POST',
  )
  await page.getByLabel('登录名').fill(LOGIN_NAME)
  await page.getByLabel('密码').fill(INITIAL_PASSWORD)
  await page.getByRole('button', { name: '登录' }).click()
  const loginResponse = await loginResponsePromise
  expect(loginResponse.status()).toBe(200)
  const firstLogin = (await loginResponse.json()) as { session_id: string }
  expect(firstLogin.session_id).not.toBe('')

  await expect(page.getByRole('heading', { name: '需要修改密码' })).toBeVisible()
  expect(new URL(page.url()).pathname).toBe('/me/credential-remediation')

  const cookiesAfterLogin = await context.cookies()
  const tokenZero = cookiesAfterLogin.find((cookie) => cookie.name === COOKIE_NAME)
  expect(tokenZero).toBeDefined()
  if (tokenZero === undefined) {
    throw new Error('Secure HttpOnly session cookie was not issued')
  }
  expect(tokenZero.value).not.toBe('')
  expect(tokenZero.httpOnly).toBe(true)
  expect(tokenZero.secure).toBe(true)
  expect(tokenZero.sameSite).toBe('Strict')
  expect(tokenZero.path).toBe('/')

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

  await expect(page.getByRole('heading', { name: '审查活动' })).toBeVisible()
  expect(new URL(page.url()).pathname).toBe('/review-cases/case-1')

  const cookiesAfterRotation = await context.cookies()
  const tokenOne = cookiesAfterRotation.find((cookie) => cookie.name === COOKIE_NAME)
  expect(tokenOne).toBeDefined()
  if (tokenOne === undefined) {
    throw new Error('Rotated Secure HttpOnly session cookie was not issued')
  }
  expect(tokenOne.value).not.toBe(tokenZero.value)
  expect(tokenOne.httpOnly).toBe(true)
  expect(tokenOne.secure).toBe(true)
  expect(tokenOne.sameSite).toBe('Strict')
  expect(tokenOne.path).toBe('/')

  const staleTokenClient = await playwrightRequest.newContext({
    baseURL: BASE_URL,
    ignoreHTTPSErrors: true,
    extraHTTPHeaders: {
      Cookie: `${COOKIE_NAME}=${tokenZero.value}`,
    },
  })
  try {
    const staleMe = await staleTokenClient.get('/api/v1/me')
    expect(staleMe.status()).toBe(401)
  } finally {
    await staleTokenClient.dispose()
  }

  const currentMe = await context.request.get(`${BASE_URL}/api/v1/me`)
  expect(currentMe.status()).toBe(200)
  expect(authorizationHeaders.filter((header) => header !== undefined)).toEqual([])

  const logoutResponsePromise = page.waitForResponse(
    (response) =>
      apiPath(response.url()) === '/api/v1/auth/logout' &&
      response.request().method() === 'POST',
  )
  await page.getByRole('button', { name: '退出登录' }).click()
  const logoutResponse = await logoutResponsePromise
  expect(logoutResponse.status()).toBe(204)
  await expect(page.getByRole('heading', { name: '登录' })).toBeVisible()
  expect((await context.cookies()).some((cookie) => cookie.name === COOKIE_NAME)).toBe(false)

  const secondLoginResponsePromise = page.waitForResponse(
    (response) =>
      apiPath(response.url()) === '/api/v1/auth/login' &&
      response.request().method() === 'POST',
  )
  await page.getByLabel('登录名').fill(LOGIN_NAME)
  await page.getByLabel('密码').fill(REPLACEMENT_PASSWORD)
  await page.getByRole('button', { name: '登录' }).click()
  const secondLoginResponse = await secondLoginResponsePromise
  expect(secondLoginResponse.status()).toBe(200)
  const secondLogin = (await secondLoginResponse.json()) as { session_id: string }

  await expect(page.getByRole('heading', { name: '我的工作' })).toBeVisible()
  await expect(page.getByRole('navigation', { name: '主要导航' })).toBeVisible()

  const revokeResponse = await context.request.delete(
    `${BASE_URL}/api/v1/me/sessions/${secondLogin.session_id}`,
  )
  expect(revokeResponse.status()).toBe(204)

  await page.reload()
  await expect(page.getByRole('heading', { name: '登录' })).toBeVisible()
  await expect(page.getByRole('navigation', { name: '主要导航' })).toHaveCount(0)
})
