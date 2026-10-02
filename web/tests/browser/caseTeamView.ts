import { expect } from '@playwright/test'
import type { Locator, Page, Response } from '@playwright/test'

export const CASE_ROLE_LABELS: Record<string, string> = {
  lead: '审查组长',
  auditor: '审查员',
  reviewer: '复核员',
  observer: '观察员',
}

export function teamRegion(page: Page): Locator {
  return page.getByRole('region', { name: '团队管理' })
}

export function teamMemberRow(page: Page, displayName: string): Locator {
  return teamRegion(page).getByRole('list', { name: '团队成员' }).getByRole('listitem').filter({ hasText: displayName })
}

export function addMemberDrawer(page: Page): Locator {
  return page.getByRole('dialog', { name: '添加成员' })
}

// 下拉选项的可见节点只有 title（role="option" 的节点是对读屏暴露的隐藏副本，Playwright 点不到）。
// 弹层挂在 body 末尾，排在已选值（同样带 title）之后，所以取最后一个。
export function dropdownOption(page: Page, name: string): Locator {
  return page.getByTitle(name, { exact: true }).last()
}

// 打开“添加成员”抽屉（已打开则复用），选择角色并输入关键字；返回抽屉和该关键字对应的候选接口响应。
export async function searchCandidates(
  page: Page,
  caseId: string,
  roleKey: string,
  query: string,
): Promise<{ drawer: Locator; response: Response }> {
  const drawer = addMemberDrawer(page)
  if (!(await drawer.isVisible())) {
    await teamRegion(page).getByRole('button', { name: '添加成员' }).click()
    await expect(drawer).toBeVisible()
  }
  await drawer.getByLabel('团队角色').click()
  await dropdownOption(page, CASE_ROLE_LABELS[roleKey] ?? roleKey).click()
  const responsePromise = page.waitForResponse((response) => {
    const url = new URL(response.url())
    return (
      url.pathname === `/api/v1/review-cases/${caseId}/member-candidates` &&
      response.request().method() === 'GET' &&
      url.searchParams.get('role_key') === roleKey &&
      url.searchParams.get('q') === query
    )
  })
  await drawer.getByLabel('成员').fill(query)
  return { drawer, response: await responsePromise }
}

// 在已搜索出候选人的抽屉里选择候选人并提交，返回添加接口的响应。
export async function submitCandidate(
  page: Page,
  caseId: string,
  drawer: Locator,
  displayName: string,
): Promise<Response> {
  await dropdownOption(page, displayName).click()
  const responsePromise = page.waitForResponse(
    (response) =>
      new URL(response.url()).pathname === `/api/v1/review-cases/${caseId}/members` &&
      response.request().method() === 'POST',
  )
  await drawer.getByRole('button', { name: '添加成员' }).click()
  return responsePromise
}

// 点击成员行的“移除”并在确认框中确认；返回对应的 DELETE 响应。
export async function confirmRemoveMember(
  page: Page,
  caseId: string,
  userId: string,
  displayName: string,
): Promise<Response> {
  const member = teamMemberRow(page, displayName)
  await expect(member).toBeVisible()
  const responsePromise = page.waitForResponse(
    (response) =>
      new URL(response.url()).pathname === `/api/v1/review-cases/${caseId}/members/${userId}` &&
      response.request().method() === 'DELETE',
  )
  await member.getByRole('button', { name: /移除/ }).click()
  await page.getByRole('dialog', { name: '移除成员' }).getByRole('button', { name: '确认移除' }).click()
  return responsePromise
}
