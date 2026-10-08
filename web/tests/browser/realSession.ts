import { expect, type Page } from '@playwright/test'

export function apiPath(url: string): string {
  return new URL(url).pathname
}

export async function submitLogin(page: Page, loginName: string, password: string) {
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

export async function submitLogout(page: Page) {
  const responsePromise = page.waitForResponse(
    (response) =>
      apiPath(response.url()) === '/api/v1/auth/logout' &&
      response.request().method() === 'POST',
  )
  await page.getByRole('button', { name: '退出登录' }).click()
  const response = await responsePromise
  expect(response.status()).toBe(204)
}
