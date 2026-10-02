import type { Locator, Page } from '@playwright/test'

// antd 按钮型 Radio 的 input 是 0×0、不可见；用户点击的是它外层的 label。
// 状态用 getByRole('radio', …) + toBeChecked 断言（不要求可见），点击走可见的 label，不用 force。
export function notificationViewRadio(page: Page, name: '全部' | RegExp): Locator {
  return page.getByRole('radio', { name })
}

export function notificationViewLabel(page: Page, name: '全部' | RegExp): Locator {
  return page.locator('label').filter({ has: notificationViewRadio(page, name) })
}
