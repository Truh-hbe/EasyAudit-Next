import { execFileSync } from 'node:child_process'

import { expect, test, type Page } from '@playwright/test'

import { openAssignDrawer, pickCandidate } from './assignmentDrawer.js'

const LOGIN_NAME = 'browser-transfer-owner'
const PASSWORD = 'transfer-browser-password-000'
// 与 seed_transfer_reopen_real_acceptance.py 的 action_id() 一致。
const ACTION_IDS = {
  process_review: '00000000-0000-4000-8000-000000003f15',
  compliance_review: '00000000-0000-4000-8000-000000003f25',
} as const

test.describe.configure({ mode: 'serial', retries: 0 })

test.beforeAll(() => {
  execFileSync('python', ['tests/browser/seed_transfer_reopen_real_acceptance.py'], {
    env: process.env,
    stdio: 'inherit',
  })
})

async function login(page: Page, path: string) {
  await page.goto(path)
  await page.getByLabel('登录名').fill(LOGIN_NAME)
  await page.getByLabel('密码').fill(PASSWORD)
  await page.getByRole('button', { name: '登录' }).click()
  // 登录后落在工作台；再进入目标页面。
  await expect(page.getByText('Transfer Owner')).toBeVisible()
  await page.goto(path)
}

const status = (page: Page, text: string) => page.getByRole('article').locator('header').getByText(text, { exact: true })

for (const [scenario, actionId] of Object.entries(ACTION_IDS)) {
  test(`${scenario}: the finding owner transfers a done action whose only executor was deactivated, and reopens it`, async ({ page }) => {
    await login(page, `/action-items/${actionId}`)
    await expect(page.getByRole('heading', { level: 1, name: `Transfer ${scenario} Action` })).toBeVisible()
    await expect(status(page, '已完成')).toBeVisible()
    const overview = page.getByRole('region', { name: '整改事项' })
    await expect(overview.getByText('Departed Executor')).toBeVisible()

    const drawer = await openAssignDrawer(page, '转交并重开', '转交并重开整改项')
    await pickCandidate(drawer, '新执行人', 'Successor', 'Successor Executor')
    // 原因必填：服务端 / 表单都不接受空原因。
    await drawer.getByRole('button', { name: '确认转交并重开' }).click()
    await expect(drawer.getByText('请填写转交原因')).toBeVisible()
    await drawer.getByRole('textbox', { name: '转交原因' }).fill('原执行人已离职，由新执行人接手')
    await drawer.getByRole('button', { name: '确认转交并重开' }).click()

    await expect(status(page, '执行中')).toBeVisible()
    await expect(page.getByRole('dialog', { name: '转交并重开整改项' })).toHaveCount(0)
    await expect(overview.getByText('Successor Executor')).toBeVisible()
    await expect(overview.getByText('Departed Executor')).toHaveCount(0)
    await expect(page.getByText('转交并重新打开整改项')).toBeVisible()
    await expect(page.getByRole('button', { name: '转交并重开', exact: true })).toHaveCount(0)

    // 新执行人可以接着完成（此处只验证入口回到执行状态）。
    await expect(page.getByRole('button', { name: '完成整改项', exact: true })).toBeVisible()
  })
}
