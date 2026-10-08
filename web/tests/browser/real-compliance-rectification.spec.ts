import { execFileSync } from 'node:child_process'

import { expect, test, type Browser, type Page, type Response } from '@playwright/test'

import { openAssignDrawer, pickCandidate } from './assignmentDrawer.js'
import { addMemberDrawer, CASE_ROLE_LABELS, searchCandidates, submitCandidate, teamMemberRow } from './caseTeamView.js'
import { apiPath, submitLogin, submitLogout } from './realSession.js'

// 与 seed_compliance_rectification_real_acceptance.py 一致。
const BASE_URL = `https://127.0.0.1:${process.env.EASYAUDIT_WEB_PORT ?? '4173'}`
const LEAD = { loginName: 'rectify-lead', password: 'rectify-lead-password-000', displayName: 'Rectify Lead' }
const OWNER = { loginName: 'rectify-owner', password: 'rectify-owner-password-000', displayName: 'Rectify Owner' }
const EXECUTOR = {
  loginName: 'rectify-executor',
  password: 'rectify-executor-password-000',
  displayName: 'Rectify Executor',
}
const REVIEWER = {
  loginName: 'rectify-reviewer',
  password: 'rectify-reviewer-password-000',
  displayName: 'Rectify Reviewer',
}
const DEPARTMENT_NAME = 'Rectify Quality Department'

const CASE_TITLE = 'Rectification Compliance Case'
const FINDING_TITLE = 'Rectification Nonconformity'
const ACTION_TITLE = 'Rectification Corrective Action'
const REJECT_REASON = 'Evidence does not show the calibration fix'

test.describe.configure({ mode: 'serial', retries: 0 })

test.beforeAll(() => {
  execFileSync('python', ['tests/browser/seed_compliance_rectification_real_acceptance.py'], {
    env: process.env,
    stdio: 'inherit',
  })
})

type Persona = typeof LEAD

// 每个角色一个独立的浏览器上下文（独立 cookie / 会话）。
async function openSession(browser: Browser, persona: Persona, path: string): Promise<Page> {
  const context = await browser.newContext({ baseURL: BASE_URL, ignoreHTTPSErrors: true })
  const page = await context.newPage()
  await page.goto('/me/workbench')
  await expect(page.getByRole('heading', { name: '登录' })).toBeVisible()
  await submitLogin(page, persona.loginName, persona.password)
  await expect(page.getByText(persona.displayName)).toBeVisible()
  await page.goto(path)
  return page
}

// 先挂起响应等待，再触发操作，避免漏掉响应。
async function respondTo(
  page: Page,
  method: string,
  path: string,
  trigger: () => Promise<unknown>,
  expectedStatus: number,
): Promise<Response> {
  const responsePromise = page.waitForResponse(
    (response) => apiPath(response.url()) === path && response.request().method() === method,
  )
  await trigger()
  const response = await responsePromise
  expect(response.status()).toBe(expectedStatus)
  return response
}

const header = (page: Page) => page.getByRole('article').locator('header')
const lifecycleTag = (page: Page, label: string) => header(page).getByText(label, { exact: true })

// 刷新后状态保持：状态标签来自服务端。
async function expectLifecycleAfterReload(page: Page, label: string) {
  await page.reload()
  await expect(lifecycleTag(page, label)).toBeVisible()
}

test('compliance_review: a nonconformity is rectified, rejected once, re-verified and closed across four roles', async ({
  browser,
}) => {
  test.setTimeout(240_000)

  // ---- 审查组长：建活动并推进到可记录发现项 ----
  const lead = await openSession(browser, LEAD, '/review-plans/new')
  await expect(lead.getByRole('heading', { name: '新建审查计划' })).toBeVisible()
  await lead.getByLabel('计划名称').fill(`${CASE_TITLE} Plan`)
  await respondTo(lead, 'POST', '/api/v1/review-plans', () => lead.getByRole('button', { name: '保存计划并继续' }).click(), 201)
  await expect(lead.getByRole('heading', { name: '新建审查活动' })).toBeVisible()
  await lead.getByRole('radio', { name: /compliance_review@1/ }).check()
  await lead.getByLabel('审查活动名称').fill(CASE_TITLE)
  await lead.getByLabel('标准 / 依据').fill('ISO 9001')
  await lead.getByLabel('范围摘要').fill('Calibration of assembly gauges')
  const caseResponse = await respondTo(
    lead,
    'POST',
    '/api/v1/review-cases',
    () => lead.getByRole('button', { name: '创建审查活动' }).click(),
    201,
  )
  const createdCase = (await caseResponse.json()) as { id: string; lifecycle: string; scenario_key: string }
  expect(createdCase.scenario_key).toBe('compliance_review')
  expect(createdCase.lifecycle).toBe('draft')
  const caseId = createdCase.id
  await expect(lead.getByRole('heading', { level: 1, name: CASE_TITLE })).toBeVisible()
  await expect(lifecycleTag(lead, '草稿')).toBeVisible()

  const commands = lead.getByRole('region', { name: '活动操作' })
  const caseTransitions = `/api/v1/review-cases/${caseId}/transitions`
  for (const [button, lifecycle, label] of [
    ['安排活动', 'scheduled', '已排期'],
    ['开始活动', 'in_progress', '审查中'],
  ] as const) {
    const response = await respondTo(lead, 'POST', caseTransitions, () => commands.getByRole('button', { name: button }).click(), 200)
    expect(((await response.json()) as { lifecycle: string }).lifecycle).toBe(lifecycle)
    await expect(lifecycleTag(lead, label)).toBeVisible()
  }
  await expectLifecycleAfterReload(lead, '审查中')

  // 复核员是验证人：由组长加入活动团队。
  const { drawer } = await searchCandidates(lead, caseId, 'reviewer', 'Rectify Reviewer')
  await submitCandidate(lead, caseId, drawer, REVIEWER.displayName).then((response) => expect(response.status()).toBe(201))
  await expect(addMemberDrawer(lead)).toHaveCount(0)
  await expect(teamMemberRow(lead, REVIEWER.displayName)).toContainText(CASE_ROLE_LABELS.reviewer ?? '')

  // ---- 审查组长：记录不符合项、指定负责人和责任部门、签发 ----
  await lead.getByLabel('标题').fill(FINDING_TITLE)
  await lead.getByLabel('条款 / 要求').fill('7.1.5')
  await lead.getByRole('radio', { name: '不符合项' }).check()
  const findingResponse = await respondTo(
    lead,
    'POST',
    `/api/v1/review-cases/${caseId}/findings`,
    () => lead.getByRole('button', { name: '新建发现项' }).click(),
    201,
  )
  const createdFinding = (await findingResponse.json()) as { id: string; lifecycle: string; scenario_data: { finding_type: string } }
  expect(createdFinding.lifecycle).toBe('open')
  expect(createdFinding.scenario_data.finding_type).toBe('nonconformity')
  const findingId = createdFinding.id
  const findingPath = `/findings/${findingId}`
  await expect(lead.getByRole('heading', { level: 1, name: FINDING_TITLE })).toBeVisible()
  await expect(lifecycleTag(lead, '待处理')).toBeVisible()
  await expect(lead.getByText('不符合项', { exact: true })).toBeVisible()
  // 未指定负责人前不能签发：服务端拒绝，状态不变。
  await respondTo(lead, 'POST', `/api/v1/findings/${findingId}/transitions`, () => lead.getByRole('button', { name: '签发不符合项' }).click(), 422)
  await expect(lead.getByRole('article').getByRole('alert')).toContainText('requires participant role(s): responsible_department, owner')
  await expect(lifecycleTag(lead, '待处理')).toBeVisible()
  expect(await lifecycleTag(lead, '整改中').count()).toBe(0)

  const participants = lead.getByRole('list', { name: '参与方' })
  for (const [roleLabel, query, name] of [
    ['整改负责人', 'Rectify Owner', OWNER.displayName],
    ['责任部门', 'Rectify Quality', DEPARTMENT_NAME],
  ] as const) {
    const participantDrawer = await openAssignDrawer(lead, '添加参与人', '添加参与人')
    await participantDrawer.getByRole('radio', { name: new RegExp(roleLabel) }).check()
    await pickCandidate(participantDrawer, '参与人', query, name)
    await respondTo(
      lead,
      'POST',
      `/api/v1/findings/${findingId}/participants`,
      () => participantDrawer.getByRole('button', { name: '添加参与人' }).click(),
      201,
    )
    await expect(participants.getByText(name, { exact: true })).toBeVisible()
    await expect(participantDrawer).toHaveCount(0)
  }

  const issueResponse = await respondTo(
    lead,
    'POST',
    `/api/v1/findings/${findingId}/transitions`,
    () => lead.getByRole('button', { name: '签发不符合项' }).click(),
    200,
  )
  expect(((await issueResponse.json()) as { lifecycle: string }).lifecycle).toBe('rectifying')
  await expect(lifecycleTag(lead, '整改中')).toBeVisible()
  await expectLifecycleAfterReload(lead, '整改中')

  // ---- 整改负责人：创建整改项并指派执行人 ----
  const owner = await openSession(browser, OWNER, findingPath)
  await expect(owner.getByRole('heading', { level: 1, name: FINDING_TITLE })).toBeVisible()
  await expect(lifecycleTag(owner, '整改中')).toBeVisible()
  await owner.getByRole('button', { name: '新建整改项', exact: true }).click()
  const newActionForm = owner.getByRole('dialog', { name: '新建整改项' })
  await newActionForm.getByLabel('标题').fill(ACTION_TITLE)
  const actionResponse = await respondTo(
    owner,
    'POST',
    `/api/v1/findings/${findingId}/actions`,
    () => newActionForm.getByRole('button', { name: '创建整改项' }).click(),
    201,
  )
  const createdAction = (await actionResponse.json()) as { id: string; lifecycle: string }
  expect(createdAction.lifecycle).toBe('todo')
  const actionId = createdAction.id
  await owner.getByRole('link', { name: ACTION_TITLE }).click()
  await expect(owner.getByRole('heading', { level: 1, name: ACTION_TITLE })).toBeVisible()
  await expect(lifecycleTag(owner, '待开始')).toBeVisible()

  const assignDrawer = await openAssignDrawer(owner, '添加执行人', '添加执行人')
  await pickCandidate(assignDrawer, '执行人', 'Rectify Exec', EXECUTOR.displayName)
  await respondTo(
    owner,
    'POST',
    `/api/v1/action-items/${actionId}/assignees`,
    () => assignDrawer.getByRole('button', { name: '添加执行人' }).click(),
    201,
  )
  await expect(owner.getByRole('region', { name: '整改事项' }).getByText(EXECUTOR.displayName, { exact: true })).toBeVisible()

  // ---- 执行人：开始、完成 ----
  const executor = await openSession(browser, EXECUTOR, `/action-items/${actionId}`)
  await expect(executor.getByRole('heading', { level: 1, name: ACTION_TITLE })).toBeVisible()
  const actionTransitions = `/api/v1/action-items/${actionId}/transitions`
  const startResponse = await respondTo(executor, 'POST', actionTransitions, () => executor.getByRole('button', { name: '开始整改项', exact: true }).click(), 200)
  expect(((await startResponse.json()) as { lifecycle: string }).lifecycle).toBe('in_progress')
  await expect(lifecycleTag(executor, '执行中')).toBeVisible()

  const completeResponse = await respondTo(executor, 'POST', actionTransitions, () => executor.getByRole('button', { name: '完成整改项', exact: true }).click(), 200)
  expect(((await completeResponse.json()) as { lifecycle: string }).lifecycle).toBe('done')
  await expect(lifecycleTag(executor, '已完成')).toBeVisible()
  await expectLifecycleAfterReload(executor, '已完成')

  // ---- 整改负责人：提交整改计划和整改完成 ----
  await owner.goto(findingPath)
  await owner.getByRole('button', { name: '填写整改计划' }).click()
  const planDrawer = owner.getByRole('dialog', { name: '整改计划' })
  await planDrawer.getByLabel('根本原因').fill('Gauge calibration schedule was not enforced')
  const planResponse = await respondTo(
    owner,
    'POST',
    `/api/v1/findings/${findingId}/rectification-submissions`,
    () => planDrawer.getByRole('button', { name: '提交整改计划' }).click(),
    201,
  )
  expect(((await planResponse.json()) as { finding: { lifecycle: string } }).finding.lifecycle).toBe('rectifying')

  async function submitCompletion(comment: string) {
    await owner.getByRole('button', { name: '提交整改完成' }).click()
    const completion = owner.getByRole('dialog', { name: '整改完成' })
    await completion.getByLabel('整改完成说明').fill(comment)
    const response = await respondTo(
      owner,
      'POST',
      `/api/v1/findings/${findingId}/rectification-submissions`,
      () => completion.getByRole('button', { name: '提交验证' }).click(),
      201,
    )
    expect(((await response.json()) as { finding: { lifecycle: string } }).finding.lifecycle).toBe('verifying')
    await expect(lifecycleTag(owner, '待验证')).toBeVisible()
    await expectLifecycleAfterReload(owner, '待验证')
  }
  await submitCompletion('First correction submitted for verification')

  // ---- 复核员：第一次验证被驳回 ----
  const reviewer = await openSession(browser, REVIEWER, findingPath)
  await expect(reviewer.getByRole('heading', { level: 1, name: FINDING_TITLE })).toBeVisible()
  await expect(lifecycleTag(reviewer, '待验证')).toBeVisible()
  await reviewer.getByRole('button', { name: '驳回验证' }).click()
  const rejectDialog = reviewer.getByRole('dialog', { name: '驳回验证' })
  await rejectDialog.getByLabel('驳回原因').fill(REJECT_REASON)
  const rejectResponse = await respondTo(
    reviewer,
    'POST',
    `/api/v1/findings/${findingId}/verification-submissions`,
    () => rejectDialog.getByRole('button', { name: '确认驳回' }).click(),
    201,
  )
  expect(((await rejectResponse.json()) as { finding: { lifecycle: string } }).finding.lifecycle).toBe('rectifying')
  await expect(lifecycleTag(reviewer, '整改中')).toBeVisible()
  await expectLifecycleAfterReload(reviewer, '整改中')

  // ---- 执行人 / 负责人都能看到驳回原因 ----
  await executor.goto(findingPath)
  await expect(lifecycleTag(executor, '整改中')).toBeVisible()
  await expect(executor.getByRole('status').filter({ hasText: '最近一次验证被驳回' })).toContainText(REJECT_REASON)
  await owner.goto(findingPath)
  await expect(owner.getByRole('status').filter({ hasText: '最近一次验证被驳回' })).toContainText(REJECT_REASON)
  await expect(owner.getByRole('list', { name: '提交记录' })).toContainText(REJECT_REASON)

  // ---- 执行人重新打开并完成整改项，负责人重新提交 ----
  await executor.goto(`/action-items/${actionId}`)
  await expect(lifecycleTag(executor, '已完成')).toBeVisible()
  await executor.getByRole('button', { name: '重新打开' }).click()
  const reopenResponse = await respondTo(
    executor,
    'POST',
    actionTransitions,
    () => executor.getByRole('dialog', { name: '重新打开整改项' }).getByRole('button', { name: '确认重新打开' }).click(),
    200,
  )
  expect(((await reopenResponse.json()) as { lifecycle: string }).lifecycle).toBe('in_progress')
  await expect(lifecycleTag(executor, '执行中')).toBeVisible()
  const recompleteResponse = await respondTo(executor, 'POST', actionTransitions, () => executor.getByRole('button', { name: '完成整改项', exact: true }).click(), 200)
  expect(((await recompleteResponse.json()) as { lifecycle: string }).lifecycle).toBe('done')
  await expectLifecycleAfterReload(executor, '已完成')

  await owner.goto(findingPath)
  await submitCompletion('Second correction after reviewer rejection')

  // ---- 复核员：验证通过，发现项关闭 ----
  await reviewer.goto(findingPath)
  await expect(lifecycleTag(reviewer, '待验证')).toBeVisible()
  await reviewer.getByRole('button', { name: '通过验证' }).click()
  const approveResponse = await respondTo(
    reviewer,
    'POST',
    `/api/v1/findings/${findingId}/verification-submissions`,
    () => reviewer.getByRole('dialog', { name: '通过验证' }).getByRole('button', { name: '确认通过' }).click(),
    201,
  )
  expect(((await approveResponse.json()) as { finding: { lifecycle: string } }).finding.lifecycle).toBe('closed')
  await expect(lifecycleTag(reviewer, '已关闭')).toBeVisible()
  await expectLifecycleAfterReload(reviewer, '已关闭')
  const history = reviewer.getByRole('list', { name: '提交记录' })
  await expect(history).toContainText('First correction submitted for verification')
  await expect(history).toContainText(REJECT_REASON)
  await expect(history).toContainText('Second correction after reviewer rejection')

  // ---- 审查组长：完成现场工作并关闭活动 ----
  await lead.goto(`/review-cases/${caseId}`)
  await expect(lifecycleTag(lead, '审查中')).toBeVisible()
  await lead.getByRole('region', { name: '活动操作' }).getByRole('button', { name: '完成现场工作' }).click()
  const finishResponse = await respondTo(
    lead,
    'POST',
    caseTransitions,
    () => lead.getByRole('dialog', { name: '完成现场工作' }).getByRole('button', { name: '确认完成' }).click(),
    200,
  )
  expect(((await finishResponse.json()) as { lifecycle: string }).lifecycle).toBe('awaiting_closure')
  await expect(lifecycleTag(lead, '待关闭')).toBeVisible()
  await lead.getByRole('region', { name: '活动操作' }).getByRole('button', { name: '关闭活动' }).click()
  const closeResponse = await respondTo(
    lead,
    'POST',
    caseTransitions,
    () => lead.getByRole('dialog', { name: '关闭活动' }).getByRole('button', { name: '确认关闭' }).click(),
    200,
  )
  expect(((await closeResponse.json()) as { lifecycle: string }).lifecycle).toBe('closed')
  await expect(lifecycleTag(lead, '已关闭')).toBeVisible()
  await expectLifecycleAfterReload(lead, '已关闭')

  for (const page of [lead, owner, executor, reviewer]) {
    await submitLogout(page)
    await page.context().close()
  }
})
