import { expect, type Locator, type Page } from '@playwright/test'

// 添加参与人 / 执行人抽屉：候选人来自服务端搜索，选中后提交。
export async function openAssignDrawer(page: Page, openerName: string, title: string): Promise<Locator> {
  await page.getByRole('button', { name: openerName, exact: true }).click()
  const drawer = page.getByRole('dialog', { name: title })
  await expect(drawer).toBeVisible()
  return drawer
}

export async function searchCandidate(drawer: Locator, fieldLabel: string, query: string) {
  await drawer.getByRole('combobox', { name: fieldLabel }).fill(query)
}

export async function pickCandidate(drawer: Locator, fieldLabel: string, query: string, displayName: string) {
  await searchCandidate(drawer, fieldLabel, query)
  // 下拉列表的 role=option 是读屏用的隐藏节点；可点击的选项项带 title。
  await drawer.page().getByTitle(displayName, { exact: true }).click()
}
