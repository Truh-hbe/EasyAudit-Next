import { execFileSync } from 'node:child_process'

import { expect, test, type Page } from '@playwright/test'

const LOGIN_NAME = 'browser-lifecycle-user'
const PASSWORD = 'lifecycle-browser-password-000'

test.describe.configure({ mode: 'serial', retries: 0 })

test.beforeAll(() => {
  execFileSync('python', ['tests/browser/seed_case_lifecycle_real_acceptance.py'], {
    env: process.env,
    stdio: 'inherit',
  })
})

async function login(page: Page) {
  await page.goto('/review-plans/new')
  await page.getByLabel('登录名').fill(LOGIN_NAME)
  await page.getByLabel('密码').fill(PASSWORD)
  await page.getByRole('button', { name: '登录' }).click()
  await expect(page.getByText('Lifecycle Browser User')).toBeVisible()
  await page.getByRole('link', { name: '审查活动' }).click()
  await page.getByRole('link', { name: '新建审查计划' }).click()
  await expect(page.getByRole('heading', { name: '新建审查计划' })).toBeVisible()
}

// 从界面新建 draft 活动，停在活动详情页。
async function createDraftCase(page: Page, scenario: 'process_review' | 'compliance_review', title: string) {
  await login(page)
  await page.getByLabel('计划名称').fill(`${title} Plan`)
  await page.getByRole('button', { name: '保存计划并继续' }).click()
  await expect(page.getByRole('heading', { name: '新建审查活动' })).toBeVisible()
  await page.getByRole('radio', { name: new RegExp(`${scenario}@1`) }).check()
  await page.getByLabel('审查活动名称').fill(title)
  if (scenario === 'process_review') {
    await page.getByLabel('区域代码').fill('area-a')
    await page.getByLabel('审查类型').fill('standard')
  } else {
    await page.getByLabel('标准 / 依据').fill('ISO 9001')
    await page.getByLabel('范围摘要').fill('Assembly line')
  }
  await page.getByRole('button', { name: '创建审查活动' }).click()
  await expect(page.getByRole('heading', { level: 1, name: title })).toBeVisible()
}

const commands = (page: Page) => page.getByRole('region', { name: '活动操作' })
const status = (page: Page, text: string) => page.getByRole('article').locator('header').getByText(text, { exact: true })

async function driveToInProgress(page: Page) {
  await expect(status(page, '草稿')).toBeVisible()
  // draft：没有开始/完成入口，也不能录入发现项。
  expect(await commands(page).getByRole('button', { name: '开始活动' }).count()).toBe(0)
  await expect(page.getByText('后才能新建发现项')).toBeVisible()
  expect(await page.getByRole('button', { name: '新建发现项' }).count()).toBe(0)

  await commands(page).getByRole('button', { name: '安排活动' }).click()
  await expect(status(page, '已排期')).toBeVisible()
  await commands(page).getByRole('button', { name: '开始活动' }).click()
  await expect(status(page, '审查中')).toBeVisible()
  await expect(page.getByRole('button', { name: '新建发现项' })).toBeVisible()
}

test('process_review: a new draft case advances to in_progress through the UI and accepts a finding', async ({ page }) => {
  await createDraftCase(page, 'process_review', 'Lifecycle Process Case')
  await driveToInProgress(page)

  await page.getByLabel('标题').fill('Lifecycle Process Finding')
  await page.getByLabel('问题类型').fill('control_gap')
  await page.getByLabel('项目类别').fill('assembly')
  await page.getByRole('button', { name: '新建发现项' }).click()
  await expect(page.getByRole('heading', { level: 1, name: 'Lifecycle Process Finding' })).toBeVisible()
})

test('compliance_review: a new draft case advances to in_progress through the UI and accepts a finding', async ({ page }) => {
  await createDraftCase(page, 'compliance_review', 'Lifecycle Compliance Case')
  await driveToInProgress(page)

  await page.getByLabel('标题').fill('Lifecycle Compliance Finding')
  await page.getByLabel('条款 / 要求').fill('8.5.1')
  await page.getByRole('radio', { name: '观察项' }).check()
  await page.getByRole('button', { name: '新建发现项' }).click()
  await expect(page.getByRole('heading', { level: 1, name: 'Lifecycle Compliance Finding' })).toBeVisible()
})

test('a draft case can be cancelled with a reason, and an empty reason is rejected by the server', async ({ page }) => {
  await createDraftCase(page, 'process_review', 'Lifecycle Cancel Case')
  await commands(page).getByRole('button', { name: '取消活动' }).click()
  const dialog = page.getByRole('dialog', { name: '取消活动' })
  await dialog.getByRole('button', { name: '确认取消' }).click()
  await expect(dialog.getByText('requires a reason')).toBeVisible()
  expect(await status(page, '已取消').count()).toBe(0)
  await dialog.getByLabel('取消原因').fill('计划调整')
  await dialog.getByRole('button', { name: '确认取消' }).click()
  await expect(status(page, '已取消')).toBeVisible()
  await expect(commands(page).getByText('当前状态没有可执行的操作')).toBeVisible()
})

// 完成现场工作 → 恢复现场（填原因）→ 录入发现项 → 作废发现项（使其为终态）→ 再完成现场工作 → 关闭。
async function reopenFieldworkJourney(
  page: Page,
  scenario: 'process_review' | 'compliance_review',
  title: string,
  fillFinding: () => Promise<void>,
) {
  await createDraftCase(page, scenario, title)
  await driveToInProgress(page)

  await commands(page).getByRole('button', { name: '完成现场工作' }).click()
  await page.getByRole('dialog', { name: '完成现场工作' }).getByRole('button', { name: '确认完成' }).click()
  await expect(status(page, '待关闭')).toBeVisible()
  expect(await page.getByRole('button', { name: '新建发现项' }).count()).toBe(0)

  // 空原因由后端拒绝；弹层保留。
  await commands(page).getByRole('button', { name: '恢复现场' }).click()
  const dialog = page.getByRole('dialog', { name: '恢复现场' })
  await dialog.getByRole('button', { name: '确认恢复' }).click()
  await expect(dialog.getByText('requires a reason')).toBeVisible()
  expect(await status(page, '审查中').count()).toBe(0)
  await dialog.getByLabel('恢复原因').fill('补录漏记的发现项')
  await dialog.getByRole('button', { name: '确认恢复' }).click()
  await expect(status(page, '审查中')).toBeVisible()

  await fillFinding()
  await page.getByRole('button', { name: '新建发现项' }).click()
  await expect(page.getByRole('heading', { level: 1, name: `${title} Finding` })).toBeVisible()
  await page.getByRole('button', { name: '作废发现项' }).click()
  const voidDialog = page.getByRole('dialog', { name: '作废发现项' })
  await voidDialog.getByLabel('作废原因').fill('演示用，作废以便关闭')
  await voidDialog.getByRole('button', { name: '确认作废' }).click()
  await expect(page.getByText('已作废', { exact: true }).first()).toBeVisible()
  await page.getByRole('link', { name: '返回审查活动' }).click()
  await expect(page.getByRole('heading', { level: 1, name: title })).toBeVisible()

  await commands(page).getByRole('button', { name: '完成现场工作' }).click()
  await page.getByRole('dialog', { name: '完成现场工作' }).getByRole('button', { name: '确认完成' }).click()
  await expect(status(page, '待关闭')).toBeVisible()
  await commands(page).getByRole('button', { name: '关闭活动' }).click()
  await page.getByRole('dialog', { name: '关闭活动' }).getByRole('button', { name: '确认关闭' }).click()
  await expect(status(page, '已关闭')).toBeVisible()
}

test('process_review: reopen fieldwork from awaiting_closure, record a finding, finish and close again', async ({ page }) => {
  const title = 'Reopen Process Case'
  await reopenFieldworkJourney(page, 'process_review', title, async () => {
    await page.getByLabel('标题').fill(`${title} Finding`)
    await page.getByLabel('问题类型').fill('control_gap')
    await page.getByLabel('项目类别').fill('assembly')
  })
})

test('compliance_review: reopen fieldwork from awaiting_closure, record a finding, finish and close again', async ({ page }) => {
  const title = 'Reopen Compliance Case'
  await reopenFieldworkJourney(page, 'compliance_review', title, async () => {
    await page.getByLabel('标题').fill(`${title} Finding`)
    await page.getByLabel('条款 / 要求').fill('8.5.1')
    await page.getByRole('radio', { name: '不符合项' }).check()
  })
})
